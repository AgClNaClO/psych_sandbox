from __future__ import annotations

import json
import random
import time
import uuid
import traceback
from contextlib import ExitStack
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..agents.client import ClientAgent
from ..agents.counselor import CounselorAgent
from ..artifacts import (
    create_artifact_dir, find_run_dir, local_temp_dir,
    single_simulation, write_json,
)
from ..datasets import CaseRepository
from ..evaluation import (
    LongitudinalEvaluator,
    PsychEvalSupervisor,
    SessionSafetyGate,
)
from ..client_simulation import ClientSimulator, ClientTurnInput
from ..evaluation.rollout import SessionRolloutEvaluator
from ..client_simulation.policies import create_client_policy
from ..client_simulation.prompts import CLIENT_PROMPT_VERSION
from ..domain import (
    CounselingCase,
    ClientTurnSignal,
    Message,
    RunResult,
    RFTConfig,
    SandboxConfig,
    SessionChecklist,
    SessionMemory,
    SessionPlan,
    SessionRecord,
    Trajectory,
    UnlockedClientInfo,
)
from ..model_client import ModelGateway, create_gateway
from ..skills import SkillCatalog, SkillRegistry
from ..therapies import normalize_therapy_id
from .disclosure import DisclosureGate
from .run_management import available_run_dir
from .memory import MemoryConsolidator, merge_session_checklist
from .memory_pipeline import (
    ClientMergeAgent,
    DialogueSummaryAgent,
    MemoryExtractionAgent,
)
from .planning import PlanBuilder
from .safety import SafetyStateMachine
from .state import StateUpdater
from .storage import SQLiteStore
from .rollout import RolloutSelectionError, SessionRolloutRunner, has_saved_rollout_risk, selected_reward
from .leakage import normalize_disclosure_text


def _therapy_codes(therapy: str) -> list[str]:
    """Map sandbox therapy IDs to the PsychEval codes used by E.7/E.8/E.9."""
    return [{
        "behavioral": "bt",
        "cbt": "cbt",
        "humanistic_existential": "het",
        "psychodynamic": "pdt",
        "postmodern": "pmt",
    }[normalize_therapy_id(therapy)]]


def _format_duration(seconds: float) -> str:
    """Format an elapsed duration as a short, human-readable Chinese label."""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.1f}秒"
    minutes, sec = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}分{sec:02d}秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}时{minutes:02d}分"


@dataclass(frozen=True)
class TurnProgress:
    """One in-session progress tick for a live progress bar."""

    session_index: int
    turn_index: int
    total_turns: int
    elapsed: float
    eta: float
    label: str = ""

    def render(self) -> str:
        total = max(1, self.total_turns)
        ratio = min(1.0, max(0.0, self.turn_index / total))
        filled = int(round(ratio * 20))
        bar = "█" * filled + "░" * (20 - filled)
        percent = int(round(ratio * 100))
        eta = "—" if self.turn_index <= 0 else _format_duration(self.eta)
        if self.turn_index >= self.total_turns:
            eta = "无"
        prefix = f"Session {self.session_index}"
        if self.label:
            prefix += f" 候选 {self.label}"
        return (
            f"{prefix} [{bar}] {percent:3d}%  "
            f"已用 {_format_duration(self.elapsed)}  预计剩余 {eta}"
        )


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
        self.gateway = gateway or create_gateway()
        self.run_dir: Path | None = None
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
            skill_selection=config.skill_selection,
        )
        self.safety_gate = SessionSafetyGate()
        self.holistic_supervisor = PsychEvalSupervisor(
            self.gateway,
            config.project_root / "prompts" / "eval",
            temperature=config.temperature_supervisor,
        )
        self.safety = SafetyStateMachine()
        self.disclosure = DisclosureGate()
        self.state_updater = StateUpdater()
        self.client_simulator = ClientSimulator(
            self.client,
            self.disclosure,
            self.state_updater,
            policy=create_client_policy(config.client_policy, self.client),
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
        session_count: int | None = None,
        seed: int | None = None,
        resume_run_id: str | None = None,
        progress_callback: Callable[[str], None] | None = None,
        turn_progress: Callable[[TurnProgress | None], None] | None = None,
    ) -> RunResult:
        with single_simulation(), ExitStack() as resources:
            if resume_run_id:
                resources.enter_context(available_run_dir(self.config.trace_dir, resume_run_id))
            return await self._run_case(
                case_id, therapy, session_count, seed, resume_run_id, progress_callback, turn_progress, resources,
            )

    async def _run_case(
        self, case_id, therapy, session_count, seed, resume_run_id, progress_callback,
        turn_progress, resources: ExitStack,
    ) -> RunResult:
        session_count = session_count if session_count is not None else self.config.session_count
        if not 1 <= session_count <= 100:
            raise ValueError("session_count must be between 1 and 100")
        case = self.repository.get(case_id)
        selected_therapy = normalize_therapy_id(therapy) if therapy else case.therapy
        if selected_therapy != case.therapy:
            raise ValueError(
                f"Case {case_id} supports {case.therapy}, not {selected_therapy}"
            )
        if resume_run_id:
            existing = self.store.load_run_metadata(resume_run_id)
            if existing["status"] == "deleting":
                raise ValueError("Run deletion has started; resume is blocked")
            if existing["case_id"] != case_id or existing["therapy"] != selected_therapy:
                raise ValueError(
                    "Resume run must use the original case and therapy: "
                    f"{existing['case_id']}/{existing['therapy']}"
                )
            if existing["status"] == "safety_hold":
                raise ValueError("A safety_hold run cannot be resumed as ordinary counseling")
            saved_dir = find_run_dir(self.config.trace_dir, resume_run_id)
            if has_saved_rollout_risk(self.store, saved_dir, resume_run_id):
                self.store.finish_run(resume_run_id, status="safety_hold")
                saved_metadata = json.loads((saved_dir / "run.json").read_text(encoding="utf-8"))
                saved_metadata["status"] = "safety_hold"
                write_json(saved_dir / "run.json", saved_metadata)
                raise ValueError("Saved candidate risk requires safety_hold; ordinary resume is blocked")
            previous_rft = RFTConfig.model_validate(existing["config"].get("rft", {}))
            if (previous_rft.enabled or self.config.rft.enabled) and previous_rft != self.config.rft:
                raise ValueError("Resume must preserve the original RFT configuration; start a new run for comparisons")
            if seed is not None and seed != existing["seed"]:
                raise ValueError("Resume must preserve the original seed")
            seed = existing["seed"]
        seed = seed if seed is not None else self.config.seed
        random.seed(seed)
        previous_sessions = self.store.load_sessions(resume_run_id) if resume_run_id else []
        memory = self.store.load_memory(resume_run_id) if resume_run_id else None
        if previous_sessions and memory is None:
            raise ValueError("Saved session is missing its committed memory")
        if previous_sessions and previous_sessions[-1].longitudinal_report and previous_sessions[-1].longitudinal_report.stage_action == "close":
            raise ValueError("The saved course is already closed")
        if memory is not None:
            if any("legacy unlocked_profile" in item for item in memory.migration_warnings):
                legacy_facts = list(memory.unlocked_client_info.facts)
                memory.unlocked_client_info = UnlockedClientInfo(
                    client_id=case.profile.client_id
                )
                for previous in previous_sessions:
                    extracted = await self.memory_extractor.extract(
                        previous.messages,
                        _therapy_codes(case.therapy),
                        previous.session_index,
                    )
                    memory.unlocked_client_info = await self.client_merger.merge(
                        memory.unlocked_client_info,
                        extracted,
                        case.profile,
                        _therapy_codes(case.therapy),
                    )
                spoken = normalize_disclosure_text(" ".join(
                    message.content
                    for previous in previous_sessions
                    for message in previous.messages
                    if message.role == "client"
                ))
                evidenced = [
                    fact for fact in legacy_facts
                    if normalize_disclosure_text(fact.content) in spoken
                ]
                migrated, warnings = self.client_simulator.migrate_legacy_unlocked(
                    case.profile, evidenced
                )
                memory.unlocked_client_info.facts = migrated
                memory.migration_warnings.extend(warnings)
        run_id = resume_run_id or f"run-{uuid.uuid4().hex[:12]}"
        self.run_dir = (
            find_run_dir(self.config.trace_dir, run_id)
            if resume_run_id
            else create_artifact_dir(self.config.trace_dir, case_id, run_id)
        )
        if not resume_run_id:
            resources.enter_context(available_run_dir(self.config.trace_dir, run_id))
        for directory in ("logs", "diagnostics", "tmp"):
            (self.run_dir / directory).mkdir(exist_ok=True)
        if resume_run_id:
            self._sync_jsonl(run_id)
        if hasattr(self.gateway, "diagnostic_dir"):
            self.gateway.diagnostic_dir = self.run_dir / "diagnostics"
        self.counselor.reset_run_state()
        metadata_path = self.run_dir / "run.json"
        metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata_path.exists() else {}
        )
        metadata.update(
            run_id=run_id, case_id=case_id, therapy=selected_therapy,
            seed=seed, requested_sessions=session_count, status="running",
            database=str(self.store.path.resolve()),
            rft=self.config.rft.model_dump(mode="json"),
            models=getattr(self.gateway, "models", {}),
        )
        write_json(metadata_path, metadata)
        if memory is None:
            memory = self._initial_memory(case)
        if not resume_run_id:
            self.store.start_run(
                run_id, case_id, selected_therapy, self.gateway.provider_name, seed,
                self.config.model_dump(mode="json"),
            )
            self.store.save_case(case)
        else:
            self.store.mark_run_running(run_id)
        def notify(message: str) -> None:
            with (self.run_dir / "logs" / "progress.log").open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")
            if progress_callback:
                progress_callback(message)

        notify(
            f"运行 {run_id} 已开始；案例={case_id}；"
            f"待执行 sessions={max(0, session_count - len(previous_sessions))}"
        )
        notify(f"产物目录：{self.run_dir}")
        sessions = list(previous_sessions)
        start = len(sessions) + 1
        run_started_at = time.monotonic()
        with local_temp_dir(self.run_dir / "tmp"):
            try:
                for session_index in range(start, session_count + 1):
                    notify(f"Session {session_index}/{session_count} 开始")
                    plan = self._plan_for(case, session_index, sessions)
                    memory_before = memory.model_copy(deep=True)
                    initial_state = (
                        self.client_simulator.prepare_session_state(
                            sessions[-1].final_state,
                            case.profile.initial_state,
                            self.config.session_trust_retention,
                        )
                        if sessions else case.profile.initial_state.model_copy(deep=True)
                    )
                    if self.config.rft.enabled:
                        session, memory = await self._select_session(
                            run_id, case, plan, memory, initial_state,
                            sessions[-1] if sessions else None, notify, turn_progress,
                        )
                        if turn_progress:
                            turn_progress(None)
                    else:
                        session = await self._run_session(
                            case, plan, memory, initial_state, turn_progress=turn_progress
                        )
                    if session.safety_verdict is None:
                        session.safety_verdict = self.safety_gate.evaluate(
                            session, case, memory_before
                        )
                    session.longitudinal_report = self.longitudinal.evaluate(
                        session, sessions
                    )
                    # Only the selected dialogue reaches E.7/E.8/E.9.  Review
                    # and next-session planning must see the newly merged memory.
                    await self._consolidate_memory_pipeline(
                        case, session, plan, memory
                    )
                    memory = self.consolidator.consolidate(
                        memory, session, next_index=session_index + 1
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
                    rft_reward = selected_reward(session)
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
                            "counselor_pipeline": "evidence_vector_retry_v2",
                            "skill_selection": self.config.skill_selection.model_dump(),
                            "rft": self.config.rft.model_dump(),
                            "generation_temperature_counselor": (
                                self.config.rft.counselor_temperature if self.config.rft.enabled
                                else self.config.temperature_counselor
                            ),
                            "models": getattr(self.gateway, "models", {}),
                            "client_pipeline": (
                                CLIENT_PROMPT_VERSION
                                if self.config.patientact_enabled
                                else "direct_generation_v1"
                            ),
                            "trace_schema_version": 4,
                        },
                        memory_before=memory_before,
                        plan=plan,
                        session=session,
                        reward=rft_reward.total if rft_reward else 0.0,
                        safety_passed=bool(
                            session.safety_verdict and session.safety_verdict.passed
                        ),
                    )
                    self.store.save_session(run_id, session, memory, trajectory)
                    self._sync_jsonl(run_id)
                    sessions.append(session)
                    elapsed = time.monotonic() - run_started_at
                    completed = session_index - start + 1
                    remaining = session_count - session_index
                    eta = (elapsed / completed) * remaining if remaining > 0 else 0.0
                    rft_label = f"RFT={rft_reward.total:.3f}；" if rft_reward else ""
                    notify(
                        f"Session {session_index}/{session_count} 完成；"
                        f"turns={len(session.turn_records)}；{rft_label}"
                        f"已用时间={_format_duration(elapsed)}；"
                        f"预计剩余={_format_duration(eta) if remaining > 0 else '无'}"
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
                (self.run_dir / "result.json").write_text(
                    result.model_dump_json(indent=2), encoding="utf-8"
                )
                metadata.update(status=status, completed_sessions=len(sessions))
                write_json(metadata_path, metadata)
                notify(f"运行 {run_id} 已结束；状态={status}")
                return result
            except BaseException as exc:
                failed_status = (
                    "safety_hold" if isinstance(exc, RolloutSelectionError)
                    and exc.selection.status == "safety_hold" else "failed"
                )
                self.store.finish_run(run_id, status=failed_status)
                with (self.run_dir / "logs" / "errors.log").open("a", encoding="utf-8") as handle:
                    handle.write(traceback.format_exc() + "\n")
                metadata.update(status=failed_status, completed_sessions=len(sessions))
                write_json(metadata_path, metadata)
                notify(f"运行 {run_id} 失败；状态已记录为 {failed_status}")
                raise

    async def _run_session(
        self, case: CounselingCase, plan: SessionPlan, memory: SessionMemory, state,
        *, counselor: CounselorAgent | None = None,
        client_simulator: ClientSimulator | None = None,
        checkpoint: Callable[[dict], None] | None = None,
        turn_progress: Callable[[TurnProgress | None], None] | None = None,
        progress_label: str = "",
    ) -> SessionRecord:
        counselor = counselor or self.counselor
        client_simulator = client_simulator or self.client_simulator
        initial = state.model_copy(deep=True)
        session_started_at = time.monotonic()
        messages: list[Message] = []
        session_checklist = SessionChecklist()
        decisions, risks, interventions, new_fact_ids, turn_records = [], [], [], [], []
        recent_signals: list[ClientTurnSignal] = []
        end_reason = "max_turns"

        def save_progress() -> None:
            if checkpoint:
                checkpoint({
                    "messages": [m.model_dump(mode="json") for m in messages],
                    "decisions": [d.model_dump(mode="json") for d in decisions],
                    "turn_records": list(turn_records),
                    "state": state.model_dump(mode="json"),
                    "session_checklist": session_checklist.model_dump(mode="json"),
                })

        save_progress()
        if turn_progress:
            turn_progress(TurnProgress(
                session_index=plan.session_index,
                turn_index=0,
                total_turns=self.config.max_turns_per_session,
                elapsed=0.0,
                eta=0.0,
                label=progress_label,
            ))
        for turn_index in range(1, self.config.max_turns_per_session + 1):
            client_text = messages[-1].content if messages else ""
            risk = self.safety.assess_input(client_text)
            risks.append(risk)
            state_before = state.model_dump(mode="json")
            counselor_turn = await counselor.respond(
                memory=memory,
                plan=plan,
                client_message=client_text,
                recent_messages=[m.model_dump(mode="json") for m in messages],
                risk=risk,
                counselor_turn_count=turn_index - 1,
                session_checklist=session_checklist,
            )
            session_checklist = merge_session_checklist(
                session_checklist,
                counselor_turn.planning.checklist_update,
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
            save_progress()
            if risk.requires_immediate_stop or output_risk.requires_immediate_stop:
                turn_records.append({
                    "turn_index": turn_index,
                    "client_input": client_text,
                    "planning": counselor_turn.planning.model_dump(mode="json"),
                    "observation": counselor_turn.observation.model_dump(mode="json"),
                    "decision": counselor_turn.decision.model_dump(mode="json"),
                    "skill_queries": [item.model_dump(mode="json") for item in counselor_turn.skill_queries],
                    "input_safety": risk.model_dump(mode="json"),
                    "output_safety": output_risk.model_dump(mode="json"),
                    "state_before": state_before,
                    "state_after": state_before,
                    "state_update": {"rule_delta": {}, "model_signal_delta": {}},
                    "session_checklist": session_checklist.model_dump(mode="json"),
                })
                end_reason = "imminent_risk" if risk.requires_immediate_stop else "safety_output_block"
                save_progress()
                break
            client_turn = await client_simulator.respond(
                ClientTurnInput(
                    profile=case.profile,
                    state=state,
                    counselor_turn=counselor_turn,
                    recent_messages=messages,
                    unlocked_facts=memory.unlocked_client_info.facts,
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
            memory.unlocked_client_info.facts = client_simulator.merge_unlocked(
                memory.unlocked_client_info.facts, client_turn.newly_unlocked
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
                "skill_queries": [item.model_dump(mode="json") for item in counselor_turn.skill_queries],
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
                "session_checklist": session_checklist.model_dump(mode="json"),
            })
            save_progress()
            if turn_progress:
                elapsed = time.monotonic() - session_started_at
                remaining = self.config.max_turns_per_session - turn_index
                eta = (elapsed / turn_index) * remaining if remaining > 0 else 0.0
                turn_progress(TurnProgress(
                    session_index=plan.session_index,
                    turn_index=turn_index,
                    total_turns=self.config.max_turns_per_session,
                    elapsed=elapsed,
                    eta=eta,
                    label=progress_label,
                ))
            if counselor_turn.decision.end_session:
                end_reason = "counselor_goal_complete"
                break
        summary = self._summary(plan, messages, interventions)
        if turn_progress:
            turn_progress(None)
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

    async def _select_session(self, run_id, case, plan, memory, initial_state, previous, notify, turn_progress):
        async def generate(index, branch_memory, branch_state, checkpoint):
            # Forward per-candidate ticks, but swallow the session-end None so a
            # finishing candidate does not detach other candidates' live bars.
            def candidate_progress(progress):
                if progress is not None and turn_progress:
                    turn_progress(progress)

            # Workers do not construct Sandboxes or write formal sessions.
            counselor = CounselorAgent(
                self.gateway, self.skill_catalog, self.config.rft.counselor_temperature,
                skill_selection=self.config.skill_selection,
            )
            client = ClientAgent(
                self.gateway, self.config.temperature_client,
                planning_temperature=self.config.temperature_client_planner,
                pullback_after=self.config.client_pullback_after,
                leak_retry_limit=self.config.disclosure_leak_retry_limit,
            )
            simulator = ClientSimulator(
                client,
                DisclosureGate(),
                StateUpdater(),
                policy=create_client_policy(self.config.client_policy, client),
            )
            branch_case = case.model_copy(deep=True)
            session = await self._run_session(
                branch_case, plan.model_copy(deep=True), branch_memory, branch_state,
                counselor=counselor, client_simulator=simulator, checkpoint=checkpoint,
                turn_progress=candidate_progress if turn_progress else None,
                progress_label=str(index),
            )
            return session

        runner = SessionRolloutRunner(
            self.config.rft,
            SessionRolloutEvaluator(
                self.gateway,
                self.config.project_root / "prompts" / "eval",
                temperature=self.config.rft.judge_temperature,
            ),
            self.store,
            self.run_dir,
        )
        return await runner.run(
            run_id=run_id, plan=plan, memory=memory, state=initial_state,
            case=case, previous=previous, generate=generate, notify=notify,
        )

    @staticmethod
    def _initial_memory(case: CounselingCase) -> SessionMemory:
        profile = case.profile
        return SessionMemory(
            case_id=case.case_id,
            unlocked_client_info=UnlockedClientInfo(client_id=profile.client_id),
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
        memory.unlocked_client_info = await self.client_merger.merge(
            memory.unlocked_client_info,
            extracted,
            case.profile,
            therapy_codes,
        )
        session.clinical_summary = await self.summarizer.summarize(
            session.session_index,
            session.messages,
            plan,
            therapy_codes,
            SessionChecklist.model_validate(
                session.turn_records[-1].get("session_checklist", {})
                if session.turn_records
                else {}
            ),
        )

    def _sync_jsonl(self, run_id: str) -> None:
        """SQLite is authoritative if interruption happened between commit and export."""
        path = self.run_dir / "trajectory.jsonl"
        temporary = self.run_dir / "tmp" / f"t-{uuid.uuid4().hex[:12]}.jsonl"
        with temporary.open("w", encoding="utf-8") as handle:
            for row in self.store.trajectory_rows(run_id):
                handle.write(row + "\n")
        temporary.replace(path)
