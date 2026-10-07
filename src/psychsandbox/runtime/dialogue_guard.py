from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
import re


BOUNDARY_PHRASES = (
    "不想谈",
    "不想说",
    "不太想",
    "先不谈",
    "换个话题",
    "说说别的",
    "先停一下",
    "不想继续",
    "不愿意谈",
)

# Minimal-answer markers a client falls back on when it has nothing new to add.
# They are content-exhaustion cues, not boundary statements and not clinical
# categories, so they stay separate from BOUNDARY_PHRASES.
CLIENT_WITHDRAWAL_PHRASES = (
    "我不知道",
    "没什么",
    "都行",
    "随便",
    "说不出来",
    "没想过",
    "就这些",
    "想不起来",
    "记不清",
)

SIMPLE_RESPONSE_BEHAVIOR = "simple_response"
IDLE_REASON_SIMPLE_RESPONSE = "consecutive_simple_response"
IDLE_REASON_REPEATED_CONTENT = "repeated_client_content"
IDLE_REASON_WITHDRAWAL = "withdrawal_density"


@dataclass(frozen=True, slots=True)
class BoundarySignal:
    detected: bool
    repeated: bool = False
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClientIdleSignal:
    """Client-side content-exhaustion signal read from the counselor's view.

    This is engineering evidence about the visible dialogue only: it never
    inspects the private profile and never changes the client's own planning.
    """

    detected: bool
    observed_client_turns: int = 0
    reasons: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()


class DialogueLoopGuard:
    """Detect explicit boundaries, repeated replies and client idling."""

    # Thresholds are documented engineering hypotheses, not clinical cut-offs.
    IDLE_WINDOW = 4
    IDLE_MIN_CLIENT_TURNS = 3
    IDLE_MIN_SIGNALS = 2
    IDLE_MIN_SIMPLE_RESPONSES = 2
    IDLE_MIN_WITHDRAWALS = 2

    IDLE_REPAIR = (
        "我注意到我们可能停在原地：你的回应越来越简短，而我也没有带来新的方向。"
        "先不追问刚才那件事。你更想换一个更具体、更安全的话题，"
        "还是由你挑一个此刻最不费力的角度开始？"
        "如果暂时不想选，我们也可以慢下来，先说说此刻身体或情绪上最明显的感觉。"
    )
    IDLE_HANDOVER = (
        "看起来重复提问没有帮上忙，这部分方向先交回给你："
        "你可以告诉我从哪里继续，也可以说今天到这里。"
        "如果你愿意，我只做一件事——陪你把刚才那句话说得更完整一点。"
    )

    def inspect(
        self,
        client_message: str,
        recent_messages: list[dict],
    ) -> BoundarySignal:
        evidence = tuple(
            phrase for phrase in BOUNDARY_PHRASES if phrase in client_message
        )
        if not evidence:
            return BoundarySignal(detected=False)
        history = _trim_current_client_message(client_message, recent_messages)
        prior_boundaries = sum(
            message.get("role") == "client"
            and any(
                phrase in str(message.get("content", ""))
                for phrase in BOUNDARY_PHRASES
            )
            for message in history
        )
        return BoundarySignal(
            detected=True,
            repeated=prior_boundaries >= 1,
            evidence=evidence,
        )

    @staticmethod
    def counselor_response(signal: BoundarySignal) -> str:
        if signal.repeated:
            return (
                "我注意到我刚才的追问没有真正尊重你的边界，对不起。"
                "我们停下这个方向，不需要解释原因。你可以决定换个更轻松的话题，"
                "或者先告诉我此刻怎样陪你会更合适。"
            )
        return (
            "谢谢你直接告诉我。我们先不谈这部分，也不需要说明原因。"
            "可以按你的节奏换个话题；你想聊更容易一点的近况，"
            "还是先说说今天希望得到怎样的支持？"
        )

    def inspect_client_idling(
        self,
        client_message: str,
        recent_messages: list[dict],
        recent_signals: Sequence[Any] = (),
    ) -> ClientIdleSignal:
        """Detect a client that has run out of content in the visible dialogue.

        Three auditable cues are counted over the most recent client turns: the
        same content repeated, consecutive ``simple_response`` behaviours, and a
        minimal-answer marker density. At least ``IDLE_MIN_SIGNALS`` of them must
        agree, after at least ``IDLE_MIN_CLIENT_TURNS`` observed client turns, so
        a single short answer never triggers a repair.
        """
        window = _client_turn_contents(
            client_message, recent_messages
        )[-self.IDLE_WINDOW :]
        if len(window) < self.IDLE_MIN_CLIENT_TURNS:
            return ClientIdleSignal(detected=False, observed_client_turns=len(window))

        reasons: list[str] = []
        evidence: list[str] = []

        normalized = [_normalize(text) for text in window]
        repeated = [
            text
            for index, text in enumerate(window)
            if text and normalized[index] in normalized[:index]
        ]
        if repeated:
            reasons.append(IDLE_REASON_REPEATED_CONTENT)
            evidence.extend(repeated[:2])

        trailing_simple = 0
        recent_window = list(recent_signals)[-self.IDLE_WINDOW :]
        for signal in reversed(recent_window):
            if _signal_behavior(signal) != SIMPLE_RESPONSE_BEHAVIOR:
                break
            trailing_simple += 1
        if trailing_simple >= self.IDLE_MIN_SIMPLE_RESPONSES:
            reasons.append(IDLE_REASON_SIMPLE_RESPONSE)

        withdrawals = [
            text
            for text in window
            if any(phrase in text for phrase in CLIENT_WITHDRAWAL_PHRASES)
        ]
        if len(withdrawals) >= self.IDLE_MIN_WITHDRAWALS:
            reasons.append(IDLE_REASON_WITHDRAWAL)
            evidence.extend(withdrawals[:2])

        return ClientIdleSignal(
            detected=len(reasons) >= self.IDLE_MIN_SIGNALS,
            observed_client_turns=len(window),
            reasons=tuple(reasons),
            evidence=tuple(evidence),
        )

    @classmethod
    def counselor_idle_response(cls, *, repeated: bool = False) -> str:
        """Answer an idle signal by handing the direction back, not by probing."""
        return cls.IDLE_HANDOVER if repeated else cls.IDLE_REPAIR

    @classmethod
    def has_idle_repair(cls, recent_messages: list[dict]) -> bool:
        """Return True when an idle repair was already sent in this session."""
        known = {_normalize(cls.IDLE_REPAIR), _normalize(cls.IDLE_HANDOVER)}
        return any(
            message.get("role") == "counselor"
            and _normalize(str(message.get("content", ""))) in known
            for message in recent_messages
        )

    @staticmethod
    def is_repeated_counselor_response(
        response: str,
        recent_messages: list[dict],
    ) -> bool:
        """Return True when the generated reply exactly repeats a recent reply."""
        normalized = _normalize(response)
        if not normalized:
            return False
        recent_counselor_messages = [
            _normalize(str(message.get("content", "")))
            for message in recent_messages
            if message.get("role") == "counselor"
        ][-4:]
        return normalized in recent_counselor_messages

    @staticmethod
    def repetition_repair_response() -> str:
        return (
            "我注意到我刚才可能重复了同一个问题。我们先停下来校准方向："
            "你希望我更多倾听、帮你一起梳理，还是暂时换个话题？"
        )


def _normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def _trim_current_client_message(
    client_message: str, recent_messages: list[dict]
) -> list[dict]:
    """Drop the trailing copy of the current client message when it was passed in."""
    if (
        recent_messages
        and recent_messages[-1].get("role") == "client"
        and recent_messages[-1].get("content") == client_message
    ):
        return list(recent_messages[:-1])
    return list(recent_messages)


def _client_turn_contents(client_message: str, recent_messages: list[dict]) -> list[str]:
    """Return client utterances in order, including the current one exactly once."""
    history = _trim_current_client_message(client_message, recent_messages)
    contents = [
        str(message.get("content", ""))
        for message in history
        if message.get("role") == "client"
    ]
    contents.append(client_message)
    return contents


def _signal_behavior(signal: Any) -> str:
    """Read a behaviour value from a turn signal object or a serialized mapping."""
    value = (
        signal.get("behavior")
        if isinstance(signal, Mapping)
        else getattr(signal, "behavior", None)
    )
    value = getattr(value, "value", value)
    return "" if value is None else str(value)
