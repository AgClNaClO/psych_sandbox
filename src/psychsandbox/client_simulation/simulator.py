from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..domain import (
    ClientBehaviorType,
    ClientGeneration,
    ClientProfile,
    ClientState,
    ClientTurnSignal,
    CounselorTurn,
    DisclosureDecision,
    Message,
    SessionMemory,
    UnlockedFact,
)
from ..runtime.disclosure import DisclosureGate
from ..runtime.state import StateUpdater

if TYPE_CHECKING:
    from ..agents.client import ClientAgent


@dataclass(slots=True)
class ClientTurnInput:
    profile: ClientProfile
    state: ClientState
    counselor_turn: CounselorTurn
    recent_messages: list[Message]
    unlocked_facts: list[UnlockedFact]
    recent_signals: list[ClientTurnSignal]
    session_index: int
    turn_index: int
    patientact_enabled: bool = True


@dataclass(slots=True)
class ClientTurnResult:
    generation: ClientGeneration
    signal: ClientTurnSignal
    disclosure: DisclosureDecision
    newly_unlocked: list[UnlockedFact]
    state_after: ClientState
    state_update: dict[str, dict[str, float]]
    leakage: dict[str, Any]


class ClientSimulator:
    """Deep client-simulation module used by the dialogue runtime.

    Callers provide one counselor turn. This module owns memory activation,
    PatientAct-style reaction planning, utterance generation, disclosure
    accounting, leakage checks, and state transition.
    """

    def __init__(
        self,
        agent: ClientAgent,
        disclosure: DisclosureGate | None = None,
        state_updater: StateUpdater | None = None,
    ):
        self.agent = agent
        self.disclosure = disclosure or DisclosureGate()
        self.state_updater = state_updater or StateUpdater()

    async def respond(self, turn: ClientTurnInput) -> ClientTurnResult:
        disclosed_levels = self.disclosed_levels(turn.unlocked_facts)
        disclosure = self.disclosure.evaluate(
            turn.profile,
            turn.state,
            turn.counselor_turn.response,
            disclosed_levels,
        )
        if turn.patientact_enabled:
            signal = await self.agent.plan_turn(
                profile=turn.profile,
                state=turn.state,
                counselor_message=turn.counselor_turn.response,
                recent_messages=turn.recent_messages,
                disclosure=disclosure,
                recent_signals=turn.recent_signals,
                turn_index=turn.turn_index,
            )
        else:
            signal = ClientTurnSignal(
                behavior=ClientBehaviorType.RECOUNTING,
                retrieved_fact_ids=[item.fact_id for item in disclosure.retrieved],
                blocked_fact_ids=[item.fact_id for item in disclosure.blocked],
                rationale="PATIENTACT internal planning disabled by configuration.",
            )
        generation, leakage = await self.agent.generate_utterance(
            profile=turn.profile,
            state=turn.state,
            counselor_message=turn.counselor_turn.response,
            recent_messages=turn.recent_messages,
            disclosure=disclosure,
            signal=signal,
            already_disclosed_ids=set(),
            disclosed_levels=disclosed_levels,
            turn_index=turn.turn_index,
        )
        unlocked = self.disclosure.unlock(
            turn.profile,
            generation.disclosed_fact_ids,
            session_index=turn.session_index,
            turn_index=turn.turn_index,
            retrieved_facts=disclosure.retrieved,
        )
        state_after, state_update = self.state_updater.update(
            turn.state,
            turn.counselor_turn,
            generation,
            signal,
            turn.profile,
        )
        return ClientTurnResult(
            generation=generation,
            signal=signal,
            disclosure=disclosure,
            newly_unlocked=unlocked,
            state_after=state_after,
            state_update=state_update,
            leakage=leakage,
        )

    @staticmethod
    def disclosed_levels(facts: list[UnlockedFact]) -> dict[str, int]:
        levels: dict[str, int] = {}
        for fact in facts:
            levels[fact.fact_id] = max(
                levels.get(fact.fact_id, 0), fact.disclosure_level
            )
        return levels

    @staticmethod
    def merge_unlocked(
        existing: list[UnlockedFact], new: list[UnlockedFact]
    ) -> list[UnlockedFact]:
        merged = {fact.fact_id: fact for fact in existing}
        for fact in new:
            previous = merged.get(fact.fact_id)
            if previous is None or fact.disclosure_level > previous.disclosure_level:
                merged[fact.fact_id] = fact
        return list(merged.values())

    @staticmethod
    def start_session(
        profile: ClientProfile,
        memory: SessionMemory,
        session_index: int,
    ) -> str:
        if session_index == 1:
            opening = profile.opening.strip()
            name_only = any(term in opening for term in ("叫我", "称呼我", "名字是"))
            if len(opening) >= 8 and not name_only:
                return opening
            problem = profile.main_problem.strip().split("。", 1)[0][:90]
            lead = (
                problem
                if problem.startswith(("最近", "近来", "近一个", "这段时间"))
                else f"最近{problem}"
            )
            return (
                f"{lead}，我想先说说这件事。"
                if problem
                else "最近有些事情让我很困扰，我想找个人谈一谈。"
            )
        if memory.last_client_closing:
            return f"上次谈完以后，我还一直在想：{memory.last_client_closing[:90]}"
        if memory.unresolved_topics:
            return f"我想接着谈谈上次还没说完的{memory.unresolved_topics[0]}。"
        if memory.summaries:
            return "上次谈完以后我又想了一些，今天想从那部分继续。"
        return "今天我想接着上次的内容慢慢谈。"
