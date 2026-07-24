from __future__ import annotations

import json
import random
import uuid
from pathlib import Path

from ..agents import ClientAgent, CounselorAgent, LLMSupervisorAgent, SupervisorAgent
from ..datasets import CaseRepository
from ..domain import (
    CounselingCase,
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
from ..skills import HierarchicalSkillRetriever, SkillRegistry
from .disclosure import DisclosureGate
from .memory import MemoryConsolidator
from .safety import SafetyStateMachine
from .state import StateUpdater
from .storage import SQLiteStore


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
            config.provider,
            local_model_name=config.local_model_name,
            local_device=config.local_device,
        )
        self.repository = repository or CaseRepository(
            config.processed_dataset_dir,
            config.project_root / "data" / "profiles",
        )
        skills_path = config.processed_dataset_dir / "skills.json"
        if not skills_path.exists():
            skills_path = config.project_root / "data" / "skills" / "cbt.json"
        self.registry = SkillRegistry.from_json(skills_path)
        self.retriever = HierarchicalSkillRetriever(self.registry)
        self.client = ClientAgent(self.gateway, config.temperature_client)
        self.counselor = CounselorAgent(self.gateway, config.temperature_counselor)
        self.supervisor = SupervisorAgent()
        self.llm_supervisor = (
            LLMSupervisorAgent(self.gateway, config.temperature_supervisor)
            if config.provider != "mock"
            else None
        )
        self.safety = SafetyStateMachine()
        self.disclosure = DisclosureGate()
        self.state_updater = StateUpdater()
        self.consolidator = MemoryConsolidator()
        self.store = store or SQLiteStore(config.database_path)

    async def run_case(
        self,
        case_id: str,
        therapy: str = "cbt",
        session_count: int = 3,
        seed: int = 42,
        resume_run_id: str | None = None,
    ) -> RunResult:
        random.seed(seed)
        case = self.repository.get(case_id)
        if therapy != case.therapy:
            raise ValueError(f"Case {case_id} supports {case.therapy}, not {therapy}")
        previous_sessions = self.store.load_sessions(resume_run_id) if resume_run_id else []
        memory = self.store.load_memory(resume_run_id) if resume_run_id else None
        run_id = resume_run_id or f"run-{uuid.uuid4().hex[:12]}"
        if memory is None:
            memory = self._initial_memory(case)
            self.store.start_run(
                run_id, case_id, therapy, self.gateway.provider_name, seed,
                self.config.model_dump(mode="json"),
            )
            self.store.save_case(case)
        sessions = list(previous_sessions)
        start = len(sessions) + 1
        for session_index in range(start, session_count + 1):
            plan = self._plan_for(case, session_index, sessions)
            memory_before = memory.model_copy(deep=True)
            initial_state = (
                sessions[-1].final_state.model_copy(deep=True)
                if sessions else case.profile.initial_state.model_copy(deep=True)
            )
            session = await self._run_session(case, plan, memory, initial_state)
            report = await self.supervisor.evaluate(
                session, case=case, memory_before=memory_before
            )
            session.supervisor_report = report
            if self.llm_supervisor:
                try:
                    session.llm_supervisor_report = await self.llm_supervisor.evaluate(
                        session, case=case, memory_before=memory_before
                    )
                except Exception as exc:
                    session.evaluation_errors.append(
                        f"llm_supervisor:{type(exc).__name__}:{exc}"
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
                    "temperature_counselor": self.config.temperature_counselor,
                },
                memory_before=memory_before,
                plan=plan,
                session=session,
                reward=report.overall_score,
                safety_passed=all(
                    metric.score >= 7
                    for metric in report.metrics
                    if metric.name in {"ethics_and_safety", "hidden_information_leakage"}
                ),
            )
            self.store.save_session(run_id, session, memory, trajectory)
            self._append_jsonl(trajectory)
            sessions.append(session)
            if session.end_reason == "imminent_risk":
                break
        self.store.finish_run(run_id)
        return RunResult(
            run_id=run_id,
            case_id=case_id,
            therapy=therapy,
            seed=seed,
            sessions=sessions,
            final_memory=memory,
        )

    async def _run_session(
        self, case: CounselingCase, plan: SessionPlan, memory: SessionMemory, state
    ) -> SessionRecord:
        initial = state.model_copy(deep=True)
        messages = [
            Message(
                session_index=plan.session_index,
                turn_index=0,
                role="client",
                content=case.profile.opening if plan.session_index == 1
                else "我想接着上次谈到的内容继续。",
            )
        ]
        decisions, risks, interventions, new_fact_ids, turn_records = [], [], [], [], []
        end_reason = "max_turns"
        for turn_index in range(1, self.config.max_turns_per_session + 1):
            client_text = messages[-1].content
            risk = self.safety.assess_input(client_text)
            risks.append(risk)
            candidates = self.retriever.retrieve(
                plan=plan, client_message=client_text, risk=risk
            )
            state_before = state.model_dump(mode="json")
            counselor_turn = await self.counselor.respond(
                memory=memory,
                plan=plan,
                client_message=client_text,
                recent_messages=[m.model_dump(mode="json") for m in messages],
                candidates=candidates,
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
                    "candidate_meta_skill_ids": [
                        item.meta_skill_id for item in candidates.meta_skills
                    ],
                    "candidate_atomic_skill_ids": [
                        item.skill_id for item in candidates.atomic_skills
                    ],
                    "decision": counselor_turn.decision.model_dump(mode="json"),
                    "input_safety": risk.model_dump(mode="json"),
                    "output_safety": output_risk.model_dump(mode="json"),
                    "state_before": state_before,
                    "state_after": state_before,
                    "state_update": {"rule_delta": {}, "model_signal_delta": {}},
                })
                end_reason = "imminent_risk" if risk.requires_immediate_stop else "safety_output_block"
                break
            already = {item.fact_id for item in memory.unlocked_profile.facts} | set(new_fact_ids)
            allowed = self.disclosure.allowed(
                case.profile, state, client_text + counselor_turn.response, already
            )
            client_generation = await self.client.respond(
                profile=case.profile,
                state=state,
                plan=plan,
                counselor_message=counselor_turn.response,
                recent_messages=messages,
                allowed_facts=allowed,
                turn_index=turn_index,
            )
            unlocked = self.disclosure.unlock(
                case.profile,
                client_generation.disclosed_fact_ids,
                session_index=plan.session_index,
                turn_index=turn_index,
            )
            memory.unlocked_profile.facts.extend(unlocked)
            new_fact_ids.extend(item.fact_id for item in unlocked)
            state, state_delta = self.state_updater.update(
                state, counselor_turn, client_generation
            )
            messages.append(Message(
                session_index=plan.session_index,
                turn_index=turn_index,
                role="client",
                content=client_generation.utterance,
            ))
            turn_records.append({
                "turn_index": turn_index,
                "client_input": client_text,
                "candidate_meta_skill_ids": [
                    item.meta_skill_id for item in candidates.meta_skills
                ],
                "candidate_atomic_skill_ids": [
                    item.skill_id for item in candidates.atomic_skills
                ],
                "decision": counselor_turn.decision.model_dump(mode="json"),
                "client_generation": client_generation.model_dump(mode="json"),
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
        next_plan = self.consolidator.next_plan(plan, plan.session_index + 1)
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
            next_session_plan=next_plan,
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
        if index <= len(case.global_plan):
            return case.global_plan[index - 1].model_copy(update={"therapy": case.therapy})
        if sessions and sessions[-1].next_session_plan:
            return sessions[-1].next_session_plan
        return self.consolidator.next_plan(case.global_plan[-1], index)

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

    def _append_jsonl(self, trajectory: Trajectory) -> None:
        path = Path(self.config.trace_dir) / f"{trajectory.run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(trajectory.model_dump_json() + "\n")
