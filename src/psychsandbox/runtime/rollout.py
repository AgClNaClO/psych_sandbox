"""Isolated session sampling and selection; no weight training or memory merge."""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..artifacts import write_json
from ..domain import (
    ClientState, RFTConfig, RolloutCandidateSummary, RolloutReward,
    RolloutSelection, SessionMemory, SessionPlan, SessionRecord,
)
from ..evaluation.rollout import SessionRolloutEvaluator, compute_rollout_reward
from ..model_client import model_diagnostic_scope
from .safety import SafetyStateMachine
from .storage import SQLiteStore


Progress = Callable[[dict[str, Any]], None]
GenerateSession = Callable[[int, SessionMemory, ClientState, Progress], Awaitable[SessionRecord]]


class RolloutSelectionError(RuntimeError):
    def __init__(self, selection: RolloutSelection):
        self.selection = selection
        super().__init__(f"RFT {selection.status}: {selection.reason} ({selection.batch_id})")


@dataclass
class _Candidate:
    summary: RolloutCandidateSummary
    memory: SessionMemory
    state: ClientState
    session: SessionRecord | None = None
    partial: dict[str, Any] = field(default_factory=dict)
    replaced: bool = False


def _has_immediate_risk(messages: list[dict]) -> bool:
    safety = SafetyStateMachine()
    return any(
        safety.assess_input(m["content"]).requires_immediate_stop
        for m in messages if m.get("role") == "client"
    )


def has_saved_rollout_risk(store: SQLiteStore, run_dir: Path, run_id: str) -> bool:
    """Recover risk even if the process died between a file checkpoint and DB update."""
    for batch in store.load_rollout_batches(run_id):
        if batch.status == "safety_hold":
            return True
        payloads = store.load_rollout_candidates(batch.batch_id)
        for candidate in batch.candidates:
            path = (run_dir / candidate.artifact_path).resolve()
            if not path.is_relative_to(run_dir.resolve()):
                raise ValueError("Candidate checkpoint must stay inside its run")
            if path.is_file():
                payloads.append(json.loads(path.read_text(encoding="utf-8")))
        for payload in payloads:
            if payload.get("summary", {}).get("status") == "safety_hold":
                return True
            session = payload.get("session") or {}
            if session.get("end_reason") == "imminent_risk" or _has_immediate_risk(session.get("messages", [])):
                return True
            if _has_immediate_risk(payload.get("partial", {}).get("messages", [])):
                return True
    return False


def selected_reward(session: SessionRecord | None) -> RolloutReward | None:
    selection = session.rollout_selection if session else None
    if selection and selection.status == "selected":
        return next(
            (item.reward for item in selection.candidates if item.index == selection.winner_index),
            None,
        )
    return None


class SessionRolloutRunner:
    def __init__(
        self, config: RFTConfig, evaluator: SessionRolloutEvaluator,
        store: SQLiteStore, run_dir: Path,
    ):
        self.config = config
        self.evaluator = evaluator
        self.store = store
        self.run_dir = run_dir

    async def run(
        self, *, run_id: str, plan: SessionPlan, memory: SessionMemory,
        state: ClientState, previous: SessionRecord | None,
        generate: GenerateSession, notify: Callable[[str], None],
    ) -> tuple[SessionRecord, SessionMemory]:
        batch_id = f"batch-{uuid.uuid4().hex[:12]}"
        directory = self.run_dir / "rollouts" / f"s{plan.session_index:03d}__{batch_id}"
        directory.mkdir(parents=True)
        baseline = selected_reward(previous)
        selection = RolloutSelection(
            batch_id=batch_id, session_index=plan.session_index, config=self.config.model_copy(deep=True),
            baseline_client_snapshot=baseline.client_snapshot if baseline else None,
            baseline_session_index=previous.session_index if baseline else None,
        )
        candidates = []

        def save_batch() -> None:
            write_json(directory / "selection.json", selection.model_dump(mode="json"))
            self.store.save_rollout_batch(run_id, selection)

        def save_candidate(candidate: _Candidate) -> None:
            payload = {
                "batch_id": batch_id,
                "summary": candidate.summary.model_dump(mode="json"),
                "session": candidate.session.model_dump(mode="json") if candidate.session else None,
                "memory_after_dialogue": candidate.memory.model_dump(mode="json"),
                "partial": candidate.partial,
            }
            write_json(self.run_dir / candidate.summary.artifact_path, payload)
            self.store.save_rollout_candidate(batch_id, candidate.summary.index, payload)

        def make_candidate(index: int) -> _Candidate:
            path = directory / f"candidate-{index:03d}.json"
            summary = RolloutCandidateSummary(
                index=index, artifact_path=path.relative_to(self.run_dir).as_posix(),
            )
            candidate = _Candidate(
                summary, memory.model_copy(deep=True), state.model_copy(deep=True),
            )
            candidates.append(candidate)
            selection.candidates.append(summary)
            return candidate

        write_json(directory / "input.json", {
            "plan": plan.model_dump(mode="json"), "memory_before": memory.model_dump(mode="json"),
            "initial_state": state.model_dump(mode="json"), "config": self.config.model_dump(mode="json"),
            "baseline_reward": baseline.model_dump(mode="json") if baseline else None,
            "sampling": "same initial context; independent API draws; no per-branch remote seed guarantee",
        })
        for index in range(1, self.config.candidates + 1):
            make_candidate(index)
        save_batch()
        for candidate in candidates:
            save_candidate(candidate)
        generation_limit = asyncio.Semaphore(self.config.concurrency)
        judge_limit = asyncio.Semaphore(self.config.judge_concurrency)

        async def sample(candidate: _Candidate) -> None:
            try:
                async with generation_limit:
                    candidate.summary.status = "generating"
                    save_candidate(candidate)
                    notify(f"Session {plan.session_index} 候选 {candidate.summary.index}: 开始生成")

                    def checkpoint(partial: dict[str, Any]) -> None:
                        candidate.partial = partial
                        if _has_immediate_risk(partial.get("messages", [])):
                            candidate.summary.status = "safety_hold"
                            candidate.summary.reason = "即时风险已在对话前缀中出现"
                            selection.status = "safety_hold"
                            selection.reason = "即时风险触发批次暂停，不推进记忆"
                            save_candidate(candidate)
                            save_batch()
                            raise RolloutSelectionError(selection)
                        save_candidate(candidate)

                    diagnostics = directory / f"d{candidate.summary.index:03d}"
                    with model_diagnostic_scope(diagnostics):
                        async with asyncio.timeout(self.config.candidate_timeout_sec):
                            candidate.session = await generate(
                                candidate.summary.index, candidate.memory, candidate.state, checkpoint,
                            )
                    candidate.summary.turns = len(candidate.session.turn_records)
                    transcript = [(m.role, m.content) for m in candidate.session.messages if m.role in {"client", "counselor"}]
                    candidate.summary.dialogue_hash = hashlib.sha256(
                        json.dumps(transcript, ensure_ascii=False).encode("utf-8")
                    ).hexdigest()
                    candidate.summary.status = "generated"
            except RolloutSelectionError:
                raise
            except asyncio.CancelledError:
                candidate.summary.status = "cancelled"
                candidate.summary.reason = "采样取消，保留已完成的对话前缀"
                raise
            except Exception as exc:
                candidate.summary.status = "generation_failed"
                candidate.summary.reason = f"{type(exc).__name__}: {exc}"[:1200]
            finally:
                save_candidate(candidate)
                save_batch()
                notify(f"Session {plan.session_index} 候选 {candidate.summary.index}: {candidate.summary.status}")

        async def judge(candidate: _Candidate) -> None:
            try:
                async with judge_limit:
                    notify(f"Session {plan.session_index} 候选 {candidate.summary.index}: 开始评分")
                    diagnostics = directory / f"d{candidate.summary.index:03d}"
                    attempt = 0
                    while True:
                        try:
                            with model_diagnostic_scope(diagnostics):
                                async with asyncio.timeout(self.config.judge_timeout_sec):
                                    assessment = await self.evaluator.evaluate(candidate.session, memory)
                            break
                        except ValueError:
                            if attempt >= self.config.judge_retries:
                                raise
                            attempt += 1
                            notify(
                                f"Session {plan.session_index} 候选 {candidate.summary.index}: "
                                f"评分校验失败，第 {attempt}/{self.config.judge_retries} 次重试"
                            )
                    candidate.summary.assessment = assessment
                    if not assessment.safety_passed or assessment.counselor_safety.score < self.config.min_safety_score:
                        candidate.summary.status = "rejected"
                        candidate.summary.reason = f"评分安全门槛未通过：{assessment.safety_reason}"
                    elif assessment.simulation_fidelity.score < self.config.min_fidelity_score:
                        candidate.summary.status = "rejected"
                        candidate.summary.reason = "来访者模拟可信度不足"
                    else:
                        candidate.summary.reward = compute_rollout_reward(
                            assessment, baseline, self.config,
                            baseline_session_index=selection.baseline_session_index,
                        )
                        candidate.summary.status = "eligible"
            except asyncio.CancelledError:
                candidate.summary.status = "cancelled"
                candidate.summary.reason = "评分取消"
                raise
            except Exception as exc:
                candidate.summary.status = "scoring_failed"
                candidate.summary.reason = f"{type(exc).__name__}: {exc}"[:1200]
            finally:
                save_candidate(candidate)
                save_batch()

                notify(f"Session {plan.session_index} 候选 {candidate.summary.index}: {candidate.summary.status}")

        def hold_if_crisis() -> None:
            # An immediate risk anywhere cannot be sampled away by choosing a calmer branch.
            crisis = []
            for candidate in candidates:
                messages = (
                    [m.model_dump(mode="json") for m in candidate.session.messages]
                    if candidate.session else candidate.partial.get("messages", [])
                )
                if (candidate.session and candidate.session.end_reason == "imminent_risk") or _has_immediate_risk(messages):
                    crisis.append(candidate)
            if crisis:
                for candidate in crisis:
                    candidate.summary.status = "safety_hold"
                    candidate.summary.reason = "即时风险触发整批暂停，不用其他候选覆盖"
                    save_candidate(candidate)
                selection.status = "safety_hold"
                selection.reason = "候选中出现即时风险，全部留档并暂停，不推进记忆"
                raise RolloutSelectionError(selection)

        try:
            await _gather_and_drain([sample(candidate) for candidate in candidates])
            hold_if_crisis()

            # Resample candidates whose generation failed (e.g. transient API errors)
            # so a single network blip does not sink the whole batch.
            resampled = 0
            while resampled < self.config.resample_limit:
                failed = [c for c in candidates if c.summary.status == "generation_failed" and not c.replaced]
                if not failed:
                    break
                failed[0].replaced = True
                replacement = make_candidate(len(candidates) + 1)
                save_candidate(replacement)
                save_batch()
                notify(f"Session {plan.session_index} 补采候选 {replacement.summary.index}（替换候选 {failed[0].summary.index}）")
                await _gather_and_drain([sample(replacement)])
                resampled += 1
            if resampled:
                hold_if_crisis()

            seen: dict[str, int] = {}
            for candidate in candidates:
                if candidate.summary.status != "generated":
                    continue
                session = candidate.session
                metrics = {m.name: m for m in session.supervisor_report.metrics} if session.supervisor_report else {}
                required = [metrics.get(name) for name in ("ethics_and_safety", "hidden_information_leakage")]
                if (
                    session.end_reason == "safety_output_block"
                    or any(m is None or m.score < 7 or m.violations for m in required)
                    or any(r.get("client_leakage", {}).get("exposed_to_counselor") for r in session.turn_records)
                ):
                    candidate.summary.status = "rejected"
                    candidate.summary.reason = "规则安全或披露检查未通过"
                elif candidate.summary.dialogue_hash in seen:
                    candidate.summary.status = "duplicate"
                    candidate.summary.duplicate_of = seen[candidate.summary.dialogue_hash]
                    candidate.summary.reason = "与已保留候选的双方对话完全相同，不重复评分"
                else:
                    seen[candidate.summary.dialogue_hash] = candidate.summary.index
                save_candidate(candidate)
            await _gather_and_drain([judge(c) for c in candidates if c.summary.status == "generated"])
            eligible = [c for c in candidates if c.summary.status == "eligible"]
            if len(eligible) < self.config.min_eligible:
                selection.status = "failed"
                selection.reason = f"仅 {len(eligible)} 个不同且合格的候选，至少需要 {self.config.min_eligible} 个"
                raise RolloutSelectionError(selection)
            winner = max(eligible, key=lambda c: (c.summary.reward.total, -c.summary.index))
            winner.summary.status = "selected"
            selection.status = "selected"
            selection.winner_index = winner.summary.index
            selection.reason = "合格候选总分最高；同分时选择编号最小者"
            for candidate in eligible:
                if candidate is not winner:
                    candidate.summary.reason = "合格但未胜出（较低分或同分编号较后）"
                save_candidate(candidate)
            save_batch()
            # Attach only after saving candidate snapshots, avoiding recursive result trees.
            winner.session.rollout_selection = selection.model_copy(deep=True)
            notify(f"Session {plan.session_index} 选中候选 {winner.summary.index}，RFT={winner.summary.reward.total:.3f}")
            return winner.session, winner.memory
        except BaseException as exc:
            if selection.status == "running":
                selection.status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
                selection.reason = f"{type(exc).__name__}: {exc}"[:1200]
            save_batch()
            raise


async def _gather_and_drain(coroutines: list[Awaitable[None]]) -> None:
    """Never leave candidate tasks running after their parent exits."""
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
