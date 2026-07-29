from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class BoundarySignal:
    detected: bool
    repeated: bool = False
    evidence: tuple[str, ...] = ()


class DialogueLoopGuard:
    """Detect explicit boundaries and repeated counselor replies."""

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
        history = recent_messages
        if (
            history
            and history[-1].get("role") == "client"
            and history[-1].get("content") == client_message
        ):
            history = history[:-1]
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
