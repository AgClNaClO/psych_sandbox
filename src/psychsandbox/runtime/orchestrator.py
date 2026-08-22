from __future__ import annotations

import json
import random
import uuid
from collections.abc import Callable
from pathlib import Path

from ..agents.client import ClientAgent
from ..agents.counselor import CounselorAgent
from ..datasets import CaseRepository
from ..evaluation import (
    ClientSimulationEvaluator,
    LongitudinalEvaluator,
    PsychEvalSupervisor,
    SupervisorAgent,
)
from ..client_simulation import ClientSimulator, ClientTurnInput
from ..client_simulation.prompts import CLIENT_PROMPT_VERSION
from ..domain import (
    CounselingCase,
    ClientTurnSignal,
    Message,
    RunResult,
    SandboxConfig,
    SessionMemory,
    SessionPlan,
    SessionRecord,
    Trajectory,
    UnlockedClientProfile,
)
from ..model_client import ModelGateway, create_gateway
from ..skills import SkillCatalog, SkillRegistry
from ..therapies import normalize_therapy_id
from .disclosure import DisclosureGate
from .memory import MemoryConsolidator
from .memory_pipeline import (
    ClientMergeAgent,
    DialogueSummaryAgent,
    MemoryExtractionAgent,
)
from .planning import PlanBuilder
from .safety import SafetyStateMachine
from .state import StateUpdater
from .storage import SQLiteStore


def _therapy_codes(therapy: str) -> list[str]:
    """Map sandbox therapy IDs to the PsychEval codes used by E.7/E.8/E.9."""
    return [{
        "behavioral": "bt",
        "cbt": "cbt",
        "humanistic_existential": "het",
        "psychodynamic": "pdt",
        "postmodern": "pmt",
    }[normalize_therapy_id(therapy)]]


class CounselingSandbox:
    def __init__(
        self,
        config: SandboxConfig,
        *,
        gateway: ModelGateway | None = None,
        repository: CaseRepository | None = None,
        store: SQLiteStore | None = None,
    ):
        self.config = config
        self.gateway = gateway or create_gateway(
            diagnostic_dir=config.trace_dir / "diagnostics",
        )
        self.repository = repository or CaseRepository.from_project(
            config.project_root
        )
        self.registry = SkillRegistry.from_project(config.project_root)
        self.skill_catalog = SkillCatalog(self.registry)
        self.client = ClientAgent(
            self.gateway,
            config.temperature_client,
            planning_temperature=config.temperature_client_planner,
            pullback_after=config.client_pullback_after,
            leak_retry_limit=config.disclosure_leak_retry_limit,
        )
        self.counselor = CounselorAgent(
            self.gateway,
            self.skill_catalog,
            config.temperature_counselor,
        )
        self.supervisor = SupervisorAgent()
        self.client_evaluator = ClientSimulationEvaluator()
        self.holistic_supervisor = PsychEvalSupervisor(
            self.gateway,
            config.project_root / "prompts" / "eval",
            temperature=config.temperature_supervisor,
        )
        self.safety = SafetyStateMachine()
        self.disclosure = DisclosureGate()
        self.state_updater = StateUpdater()
        self.client_simulator = ClientSimulator(
            self.client, self.disclosure, self.state_updater
        )
        self.consolidator = MemoryConsolidator()
        self.longitudinal = LongitudinalEvaluator()
        self.plan_builder = PlanBuilder()
        self.memory_extractor = MemoryExtractionAgent(self.gateway)
        self.client_merger = ClientMergeAgent(self.gateway)
        self.summarizer = DialogueSummaryAgent(self.gateway)
        self.store = store or SQLiteStore(config.database_path)

    async def run_case(
        self,
        case_id: str,
        therapy: str | None = None,
        session_count: int = 3,
        seed: int = 42,
        resume_run_id: str | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> RunResult:
        random.seed(seed)
        case = self.repository.get(case_id)
        selected_therapy = normalize_therapy_id(therapy) if therapy else case.therapy
        if selected_therapy != case.therapy:
            raise ValueError(
                f"Case {case_id} supports {case.therapy}, not {selected_therapy}"
            )
        if resume_run_id:
            existing = self.store.load_run(resume_run_id)
            if existing.case_id != case_id or existing.therapy != selected_therapy:
                raise ValueError(
                    "Resume run must use the original case and therapy: "
                    f"{existing.case_id}/{existing.therapy}"
                )
        previous_sessions = self.store.load_sessions(resume_run_id) if resume_run_id else []
        memory = self.store.load_memory(resume_run_id) if resume_run_id else None
        run_id = resume_run_id or f"run-{uuid.uuid4().hex[:12]}"
        if memory is None:
            memory = self._initial_memory(case)
            self.store.start_run(
                run_id, case_id, selected_therapy, self.gateway.provider_name, seed,
                self.config.model_dump(mode="json"),
            )
            self.store.save_case(case)
        notify = progress_callback or (lambda _message: None)
        notify(
            f"运行 {run_id} 已开始；案例={case_id}；"
            f"待执行 sessions={max(0, session_count - len(previous_sessions))}"
        )
        sessions = list(previous_sessions)
        start = len(sessions) + 1
        try:
            for session_index in range(start, session_count + 1):
                notify(f"Session {session_index}/{session_count} 开始")
                plan = self._plan_for(case, session_index, sessions)
                memory_before = memory.model_copy(deep=True)
                initial_state = (
                    self.client_simulator.prepare_session_state(
                        sessions[-1].final_state
                    )
                    if sessions else case.profile.initial_state.model_copy(deep=True)
                )
                session = await self._run_session(case, plan, memory, initial_state)
                report = await self.supervisor.evaluate(
                    session, case=case, memory_before=memory_before
                )
                session.supervisor_report = report
                session.client_simulation_report = await self.client_evaluator.evaluate(
                    session
                )
                session.longitudinal_report = self.longitudinal.evaluate(
                    session, sessions
                )
                baseline_next = self._baseline_next_plan(
                    case, session, session_index + 1
                )
                provisional_next = self.plan_builder.build(
                    session.plan,
                    baseline_next,
                    session.longitudinal_report,
                )
                session.counselor_review = await self.counselor.review_session(
                    session=session,
                    memory=memory,
                    baseline_next=provisional_next,
                )
                session.next_session_plan = self.plan_builder.build(
                    session.plan,
                    baseline_next,
                    session.longitudinal_report,
                    session.counselor_review,
                )
                await self._consolidate_memory_pipeline(
                    case, session, plan, memory
                )
                memory = self.consolidator.consolidate(
                    memory, session, next_index=session_index + 1
                )
                trajectory = Trajectory(
                    trajectory_id=f"traj-{uuid.uuid4().hex[:12]}",
                    run_id=run_id,
                    case_id=case_id,
                    session_index=session_index,
                    model_config_snapshot={
                        "provider": self.gateway.provider_name,
                        "seed": seed,
                        "temperature_client": self.config.temperature_client,
                        "temperature_client_planner": self.config.temperature_client_planner,
                        "temperature_counselor": self.config.temperature_counselor,
                        "counselor_pipeline": "plan_react_review_v1",
                        "client_pipeline": (
                            CLIENT_PROMPT_VERSION
                            if self.config.patientact_enabled
                            else "direct_generation_v1"
                        ),
                        "trace_schema_version": 3,
                    },
                    memory_before=memory_before,
                    plan=plan,
                    session=session,
                    reward=report.overall_score,
                    safety_passed=all(
                        metric.score >= 7
                        for metric in report.metrics
                        if metric.name
                        in {"ethics_and_safety", "hidden_information_leakage"}
                    ),
                )
                self.store.save_session(run_id, session, memory, trajectory)
                self._append_jsonl(trajectory)
                sessions.append(session)
                notify(
                    f"Session {session_index}/{session_count} 完成；"
                    f"turns={len(session.turn_records)}；督导={report.overall_score}"
                )
                if (
                    session.end_reason == "imminent_risk"
                    or session.longitudinal_report.stage_action == "close"
                ):
                    break
            status = (
                "safety_hold"
                if sessions and sessions[-1].end_reason == "imminent_risk"
                else "completed"
            )
            result = RunResult(
                run_id=run_id,
                case_id=case_id,
                therapy=selected_therapy,
                seed=seed,
                sessions=sessions,
                final_memory=memory,
            )
            holistic_report = None
            try:
                holistic_report = await self.holistic_supervisor.evaluate(result, case)
                self.store.save_holistic_report(run_id, holistic_report)
            except Exception as exc:
                notify(f"整体督导评估失败：{type(exc).__name__}:{exc}")
            result.holistic_report = holistic_report
            self.store.finish_run(run_id, status=status)
            notify(f"运行 {run_id} 已结束；状态={status}")
            return result
        except BaseException:
            self.store.finish_run(run_id, status="failed")
            notify(f"运行 {run_id} 失败；状态已记录为 failed")
            raise

    async def _run_session(
        self, case: CounselingCase, plan: SessionPlan, memory: SessionMemory, state
    ) -> SessionRecord:
        initial = state.model_copy(deep=True)
        messages = [
            Message(
                session_index=plan.session_index,
                turn_index=0,
                role="client",
                content=self.client_simulator.start_session(
                    case.profile, memory, plan.session_index
                ),
            )
        ]
        decisions, risks, interventions, new_fact_ids, turn_records = [], [], [], [], []
        recent_signals: list[ClientTurnSignal] = []
        end_reason = "max_turns"
        for turn_index in range(1, self.config.max_turns_per_session + 1):
            client_text = messages[-1].content
            risk = self.safety.assess_input(client_text)
            risks.append(risk)
            state_before = state.model_dump(mode="json")
            counselor_turn = await self.counselor.respond(
                memory=memory,
                plan=plan,
                client_message=client_text,
                recent_messages=[m.model_dump(mode="json") for m in messages],
                risk=risk,
                counselor_turn_count=turn_index - 1,
            )
            output_risk = self.safety.assess_output(counselor_turn.response, risk)
            risks.append(output_risk)
            decisions.append(counselor_turn.decision)
            if counselor_turn.decision.goal_progress >= plan.completion_threshold:
                counselor_turn.decision.end_session = True
            interventions.extend(counselor_turn.decision.selected_atomic_skill_ids)
            messages.append(Message(
                session_index=plan.session_index,
                turn_index=turn_index,
                role="counselor",
                content=counselor_turn.response,
            ))
            if risk.requires_immediate_stop or output_risk.requires_immediate_stop:
                turn_records.append({
                    "turn_index": turn_index,
                    "client_input": client_text,
                    "planning": counselor_turn.planning.model_dump(mode="json"),
                    "observation": counselor_turn.observation.model_dump(mode="json"),
                    "decision": counselor_turn.decision.model_dump(mode="json"),
                    "input_safety": risk.model_dump(mode="json"),
                    "output_safety": output_risk.model_dump(mode="json"),
                    "state_before": state_before,
                    "state_after": state_before,
                    "state_update": {"rule_delta": {}, "model_signal_delta": {}},
                })
                end_reason = "imminent_risk" if risk.requires_immediate_stop else "safety_output_block"
                break
            client_turn = await self.client_simulator.respond(
                ClientTurnInput(
                    profile=case.profile,
                    state=state,
                    counselor_turn=counselor_turn,
                    recent_messages=messages,
                    unlocked_facts=memory.unlocked_profile.facts,
                    recent_signals=recent_signals,
                    session_index=plan.session_index,
                    turn_index=turn_index,
                    patientact_enabled=self.config.patientact_enabled,
                )
            )
            disclosure = client_turn.disclosure
            signal = client_turn.signal
            client_generation = client_turn.generation
            leakage = client_turn.leakage
            memory.unlocked_profile.facts = self.client_simulator.merge_unlocked(
                memory.unlocked_profile.facts, client_turn.newly_unlocked
            )
            new_fact_ids.extend(
                item.fact_id for item in client_turn.newly_unlocked
            )
            state = client_turn.state_after
            state_delta = client_turn.state_update
            recent_signals.append(signal)
            messages.append(Message(
                session_index=plan.session_index,
                turn_index=turn_index,
                role="client",
                content=client_generation.utterance,
            ))
            turn_records.append({
                "turn_index": turn_index,
                "client_input": client_text,
                "planning": counselor_turn.planning.model_dump(mode="json"),
                "observation": counselor_turn.observation.model_dump(mode="json"),
                "decision": counselor_turn.decision.model_dump(mode="json"),
                "disclosure_decision": disclosure.model_dump(mode="json"),
                "client_turn_signal": signal.model_dump(mode="json"),
                "client_generation": client_generation.model_dump(mode="json"),
                "client_leakage": {
                    **leakage,
                    "exposed_to_counselor": False,
                },
                "input_safety": risk.model_dump(mode="json"),
                "output_safety": output_risk.model_dump(mode="json"),
                "state_before": state_before,
                "state_after": state.model_dump(mode="json"),
                "state_update": state_delta,
            })
            if counselor_turn.decision.end_session:
                end_reason = "counselor_goal_complete"
                break
        summary = self._summary(plan, messages, interventions)
        return SessionRecord(
            session_id=f"session-{uuid.uuid4().hex[:12]}",
            session_index=plan.session_index,
            plan=plan,
            initial_state=initial,
            final_state=state,
            messages=messages,
            decisions=decisions,
            turn_records=turn_records,
            summary=summary,
            newly_unlocked_fact_ids=list(dict.fromkeys(new_fact_ids)),
            interventions_used=list(dict.fromkeys(interventions)),
            risk_events=risks,
            end_reason=end_reason,
        )

    @staticmethod
    def _initial_memory(case: CounselingCase) -> SessionMemory:
        profile = case.profile
        return SessionMemory(
            case_id=case.case_id,
            unlocked_profile=UnlockedClientProfile(
                client_id=profile.client_id,
                public_background={
                    "age": profile.static_traits.age,
                    "gender": profile.static_traits.gender,
                    "occupation": profile.static_traits.occupation,
                    "main_problem": profile.main_problem,
                    "topic": profile.topic,
                    "language_style": profile.language_style,
                },
                expressed_problems=[profile.main_problem],
                confirmed_goals=[profile.core_demands],
            ),
            confirmed_goals=[profile.core_demands],
        )

    def _plan_for(
        self, case: CounselingCase, index: int, sessions: list[SessionRecord]
    ) -> SessionPlan:
        if sessions and sessions[-1].next_session_plan:
            return sessions[-1].next_session_plan
        if index <= len(case.global_plan):
            return case.global_plan[index - 1].model_copy(update={"therapy": case.therapy})
        return self.consolidator.next_plan(case.global_plan[-1], index)

    def _baseline_next_plan(
        self,
        case: CounselingCase,
        session: SessionRecord,
        next_index: int,
    ) -> SessionPlan:
        if next_index <= len(case.global_plan):
            return case.global_plan[next_index - 1].model_copy(
                update={"therapy": case.therapy}
            )
        return self.consolidator.next_plan(session.plan, next_index)

    @staticmethod
    def _summary(
        plan: SessionPlan, messages: list[Message], interventions: list[str]
    ) -> str:
        client_points = [m.content for m in messages if m.role == "client"][-2:]
        return (
            f"第{plan.session_index}次会谈围绕{'、'.join(plan.objectives[:2])}展开；"
            f"使用技能 {', '.join(dict.fromkeys(interventions)) or '支持性探索'}；"
            f"来访者末段表达：{' / '.join(client_points)}"
        )

    async def _consolidate_memory_pipeline(
        self,
        case: CounselingCase,
        session: SessionRecord,
        plan: SessionPlan,
        memory: SessionMemory,
    ) -> None:
        """Run the PsychEval E.7/E.8/E.9 post-session consolidation pipeline.

        E.7 extracts only what the client actually disclosed in this session,
        E.8 merges it into the counselor's longitudinal, ground-truth-gated
        profile, and E.9 writes the evidence-bound clinical summary that bridges
        to the next session.
        """
        therapy_codes = _therapy_codes(case.therapy)
        extracted = await self.memory_extractor.extract(
            session.messages,
            therapy_codes,
            session.session_index,
        )
        memory.evolving_profile = await self.client_merger.merge(
            memory.evolving_profile,
            extracted,
            case.profile,
            therapy_codes,
        )
        session.clinical_summary = await self.summarizer.summarize(
            session.session_index,
            session.messages,
            plan,
            therapy_codes,
        )

    def _append_jsonl(self, trajectory: Trajectory) -> None:
        path = Path(self.config.trace_dir) / f"{trajectory.run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(trajectory.model_dump_json() + "\n")
