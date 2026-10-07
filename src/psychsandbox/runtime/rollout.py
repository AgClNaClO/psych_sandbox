"""Isolated session sampling and selection; no weight training or memory merge."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..artifacts import write_json
from ..domain import (
    ClientState, CounselingCase, RFTConfig, RolloutCandidateSummary, RolloutReward,
    RolloutSelection, SessionMemory, SessionPlan, SessionRecord,
)
from ..evaluation.rollout import SessionRolloutEvaluator, compute_rollout_reward
from ..model_client import model_diagnostic_scope
from .progress import ScoringProgress
from .safety import SafetyStateMachine
from .storage import SQLiteStore


Progress = Callable[[dict[str, Any]], None]
GenerateSession = Callable[[int, SessionMemory, ClientState, Progress], Awaitable[SessionRecord]]
JudgeProgress = Callable[[ScoringProgress | None], None]


class RolloutSelectionError(RuntimeError):
    def __init__(self, selection: RolloutSelection):
        self.selection = selection
        super().__init__(f"RFT {selection.status}: {selection.reason} ({selection.batch_id})")


@dataclass
class _ScoringTicks:
    """Aggregate scoring progress across every candidate of one batch.

    ``start_candidate`` books the judge steps the candidate will run, and
    ``step`` counts each of them once (a judge retry replays the same steps and
    must not inflate the bar). Candidates resampled after a scoring failure add
    to the total, so the bar reflects the extra work instead of jumping to done.
    """

    session_index: int
    callback: JudgeProgress | None
    instruments_total: int = 0
    instruments_done: int = 0
    candidates_total: int = 0
    candidates_done: int = 0
    last_instrument: str = ""
    started_at: float = field(default_factory=time.monotonic)
    _counted: set[tuple[int, str]] = field(default_factory=set)

    def start_candidate(self, index: int, instruments: int) -> None:
        self.candidates_total += 1
        self.instruments_total += max(0, instruments)
        self.emit()

    def step(self, index: int, name: str) -> None:
        key = (index, name)
        if key in self._counted:
            return
        self._counted.add(key)
        self.instruments_done += 1
        self.last_instrument = name
        self.emit()

    def finish_candidate(self) -> None:
        self.candidates_done += 1
        self.emit()

    def emit(self) -> None:
        if self.callback is None:
            return
        elapsed = time.monotonic() - self.started_at
        done = self.instruments_done if self.instruments_total else self.candidates_done
        total = self.instruments_total if self.instruments_total else self.candidates_total
        eta = elapsed / done * (total - done) if done > 0 else 0.0
        self.callback(ScoringProgress(
            session_index=self.session_index,
            instruments_done=self.instruments_done,
            instruments_total=self.instruments_total,
            candidates_scored=self.candidates_done,
            candidates_total=self.candidates_total,
            elapsed=elapsed,
            eta=eta,
            last_instrument=self.last_instrument,
        ))


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
        state: ClientState, case: CounselingCase, previous: SessionRecord | None,
        generate: GenerateSession, notify: Callable[[str], None],
        judge_progress: JudgeProgress | None = None,
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
        generation_limit = asyncio.Semaphore(self.config.effective_concurrency)
        judge_limit = asyncio.Semaphore(self.config.effective_judge_concurrency)
        scoring = _ScoringTicks(session_index=plan.session_index, callback=judge_progress)
        notify(
            f"Session {plan.session_index} 批次 {batch_id}：{len(candidates)} 个候选，"
            f"生成并发 {self.config.effective_concurrency}，"
            f"评分并发 {self.config.effective_judge_concurrency}"
        )

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
                    instrument_total = self._instrument_count(candidate)
                    scoring.start_candidate(candidate.summary.index, instrument_total)

                    def on_step(done: int, total: int, name: str) -> None:
                        scoring.step(candidate.summary.index, name)

                    attempt = 0
                    while True:
                        try:
                            with model_diagnostic_scope(diagnostics):
                                async with asyncio.timeout(self.config.judge_timeout_sec):
                                    report = await self._evaluate(
                                        candidate, case, memory, on_step,
                                        with_progress=judge_progress is not None,
                                    )
                            break
                        except ValueError:
                            if attempt >= self.config.judge_retries:
                                raise
                            attempt += 1
                            notify(
                                f"Session {plan.session_index} 候选 {candidate.summary.index}: "
                                f"评分校验失败，第 {attempt}/{self.config.judge_retries} 次重试"
                            )
                    candidate.summary.assessment = report
                    verdict = candidate.session.safety_verdict
                    if not verdict.passed:
                        candidate.summary.status = "rejected"
                        candidate.summary.reason = "规则安全或披露检查未通过：" + "；".join(verdict.reasons)
                    else:
                        candidate.summary.reward = compute_rollout_reward(
                            report, baseline, self.config,
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
                scoring.finish_candidate()

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

            seen: dict[str, int] = {}
            resampled = 0

            def reject_duplicates_and_safety() -> None:
                for candidate in candidates:
                    if candidate.summary.status != "generated":
                        continue
                    session = candidate.session
                    if (
                        session.end_reason == "safety_output_block"
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

            async def judge_pending() -> None:
                await _gather_and_drain(
                    [judge(c) for c in candidates if c.summary.status == "generated"]
                )

            async def resample_failed(statuses: set[str]) -> bool:
                """Replace the first failed candidate, honoring the shared budget."""
                nonlocal resampled
                if resampled >= self.config.resample_limit:
                    return False
                failed = [
                    c for c in candidates
                    if c.summary.status in statuses and not c.replaced
                ]
                if not failed:
                    return False
                failed[0].replaced = True
                replacement = make_candidate(len(candidates) + 1)
                save_candidate(replacement)
                save_batch()
                notify(
                    f"Session {plan.session_index} 补采候选 {replacement.summary.index}"
                    f"（替换 {failed[0].summary.status} 候选 {failed[0].summary.index}）"
                )
                await _gather_and_drain([sample(replacement)])
                resampled += 1
                return True

            # Resample generation-failed candidates first (e.g. transient API
            # errors) so a single network blip does not sink the whole batch.
            while resampled < self.config.resample_limit:
                if not await resample_failed({"generation_failed"}):
                    break
            if resampled:
                hold_if_crisis()

            reject_duplicates_and_safety()
            await judge_pending()

            # Scoring can also fail transiently (e.g. a judge API 500). If we
            # still lack enough eligible candidates, resample those too.
            while resampled < self.config.resample_limit:
                eligible = [c for c in candidates if c.summary.status == "eligible"]
                if len(eligible) >= self.config.min_eligible:
                    break
                if not await resample_failed({"scoring_failed"}):
                    break
                hold_if_crisis()
                reject_duplicates_and_safety()
                await judge_pending()

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

    def _instrument_count(self, candidate: _Candidate) -> int:
        """Judge steps the evaluator will run, used only to size the bar.

        Custom evaluators (test doubles included) may not expose a count; the
        progress bar then falls back to candidate-level steps.
        """
        if candidate.session is None:
            return 0
        counter = getattr(self.evaluator, "instrument_count", None)
        if not callable(counter):
            return 0
        return int(counter(candidate.session))

    async def _evaluate(
        self, candidate: _Candidate, case, memory, on_step, *, with_progress: bool,
    ) -> Any:
        """Score one candidate, adding the tick hook only when it is in use.

        The extra keyword is passed conditionally so evaluators that keep the
        three-argument ``evaluate(session, case, memory)`` contract (for
        example test doubles) keep working without a progress bar.
        """
        if not with_progress:
            return await self.evaluator.evaluate(candidate.session, case, memory)
        return await self.evaluator.evaluate(
            candidate.session, case, memory, on_step=on_step,
        )


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
