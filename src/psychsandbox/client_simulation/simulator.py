from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
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
    UnlockedFact,
)
from ..runtime.disclosure import DisclosureGate
from ..runtime.leakage import normalize_disclosure_text
from ..runtime.state import StateUpdater
from .policies import (
    ClientPolicy,
    ClientPolicyInput,
    CompactPatientActPolicy,
    SimpleClientPolicy,
)

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

    SESSION_FATIGUE_RECOVERY = 0.25

    def __init__(
        self,
        agent: ClientAgent,
        disclosure: DisclosureGate | None = None,
        state_updater: StateUpdater | None = None,
        policy: ClientPolicy | None = None,
    ):
        self.agent = agent
        self.disclosure = disclosure or DisclosureGate()
        self.state_updater = state_updater or StateUpdater()
        self.policy = policy or CompactPatientActPolicy(agent)

    async def respond(self, turn: ClientTurnInput) -> ClientTurnResult:
        started = perf_counter()
        disclosed_ids = self.disclosed_ids(turn.unlocked_facts)
        disclosure = self.disclosure.evaluate(
            turn.profile,
            turn.state,
            turn.counselor_turn.response,
            disclosed_ids,
            session_index=turn.session_index,
        )
        policy = self.policy if turn.patientact_enabled else SimpleClientPolicy()
        signal = await policy.plan_turn(
            ClientPolicyInput(
                profile=turn.profile,
                state=turn.state,
                counselor_message=turn.counselor_turn.response,
                recent_messages=turn.recent_messages,
                disclosure=disclosure,
                recent_signals=turn.recent_signals,
                turn_index=turn.turn_index,
            )
        )
        generation, leakage = await self.agent.generate_utterance(
            profile=turn.profile,
            state=turn.state,
            counselor_message=turn.counselor_turn.response,
            recent_messages=turn.recent_messages,
            disclosure=disclosure,
            signal=signal,
            already_disclosed_ids=set(),
            disclosed_levels=None,
            known_memories=turn.unlocked_facts,
            turn_index=turn.turn_index,
        )
        leakage["policy"] = signal.policy or getattr(policy, "name", "unknown")
        leakage["client_model_calls"] = (
            signal.planning_model_calls + 1 + int(leakage.get("retry_count", 0))
        )
        leakage["client_latency_ms"] = round((perf_counter() - started) * 1000, 3)
        leakage["estimated_cost"] = None
        leakage["cost_note"] = "provider token pricing is not configured"
        unlocked = self.disclosure.unlock(
            turn.profile,
            generation.disclosed_fact_ids,
            session_index=turn.session_index,
            turn_index=turn.turn_index,
            retrieved_facts=disclosure.retrieved,
            evidence_by_fact_id=leakage.get("disclosed_evidence", {}),
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
    def disclosed_ids(facts: list[UnlockedFact]) -> set[str]:
        return {fact.fact_id for fact in facts}

    @staticmethod
    def merge_unlocked(
        existing: list[UnlockedFact], new: list[UnlockedFact]
    ) -> list[UnlockedFact]:
        merged = {fact.fact_id: fact for fact in existing}
        for fact in new:
            previous = merged.get(fact.fact_id)
            if previous is None or previous.content in fact.content:
                merged[fact.fact_id] = fact
            elif fact.content not in previous.content:
                merged[fact.fact_id] = fact.model_copy(
                    update={"content": f"{previous.content}；{fact.content}"}
                )
        return list(merged.values())

    @staticmethod
    def migrate_legacy_unlocked(
        profile: ClientProfile, facts: list[UnlockedFact]
    ) -> tuple[list[UnlockedFact], list[str]]:
        """Map legacy fact IDs only when spoken text identifies one atomic item."""

        current_ids = {item.item_id for item in profile.disclosure_items}
        migrated: list[UnlockedFact] = []
        warnings: list[str] = []
        for fact in facts:
            if fact.fact_id in current_ids:
                migrated.append(fact)
                continue
            spoken = normalize_disclosure_text(fact.content)
            matches = [
                item for item in profile.disclosure_items
                if len(spoken) >= 4
                and spoken in normalize_disclosure_text(item.content)
            ]
            if len(matches) == 1:
                migrated.append(
                    fact.model_copy(update={"fact_id": matches[0].item_id})
                )
                warnings.append(
                    f"mapped legacy spoken fact {fact.fact_id} to {matches[0].item_id}"
                )
            else:
                migrated.append(fact)
                warnings.append(
                    f"kept unmatched legacy spoken fact {fact.fact_id}; matches={len(matches)}"
                )
        return migrated, warnings

    @staticmethod
    def prepare_session_state(
        state: ClientState,
        initial_state: ClientState | None = None,
        trust_retention: float = 0.5,
    ) -> ClientState:
        """Carry longitudinal state while allowing short-term fatigue to recover."""
        baseline = initial_state or state
        retained_trust = baseline.trust + trust_retention * (
            state.trust - baseline.trust
        )
        return state.model_copy(
            update={
                "trust": round(max(0.0, min(1.0, retained_trust)), 4),
                "resistance": baseline.resistance,
                "rupture_state": baseline.rupture_state,
                "fatigue": round(
                    max(0.1, state.fatigue - ClientSimulator.SESSION_FATIGUE_RECOVERY),
                    4,
                )
            }
        )
