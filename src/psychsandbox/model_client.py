from __future__ import annotations

import json
import os
import re
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential


ECNU_JSON_SCHEMA_MODELS = {"ecnu-plus", "ecnu-turbo"}


class ModelGateway(ABC):
    provider_name = "abstract"

    @abstractmethod
    async def complete_structured(
        self,
        *,
        role: str,
        system_prompt: str,
        input_payload: dict[str, Any],
        output_schema: type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        raise NotImplementedError


class OpenAICompatibleGateway(ModelGateway):
    provider_name = "openai_compatible"

    def __init__(self, diagnostic_dir: Path | None = None) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("API mode requires the openai package") from exc
        api_key = os.getenv("MODEL_API_KEY")
        if not api_key:
            raise RuntimeError("MODEL_API_KEY is required for API mode")
        base_url = os.getenv("MODEL_BASE_URL") or None
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=float(os.getenv("MODEL_TIMEOUT_SECONDS", "90")),
        )
        counselor = os.getenv("COUNSELOR_MODEL", "")
        self.models = {
            "client": os.getenv("CLIENT_MODEL", ""),
            "counselor": counselor,
            "supervisor": os.getenv("SUPERVISOR_MODEL", counselor),
            "summarizer": os.getenv("SUMMARY_MODEL", counselor),
        }
        if not self.models["client"] or not counselor:
            raise RuntimeError("CLIENT_MODEL and COUNSELOR_MODEL are required")
        structured_mode = os.getenv("MODEL_STRUCTURED_OUTPUT", "auto").strip().lower()
        if structured_mode not in {"auto", "json_schema", "off"}:
            raise RuntimeError(
                "MODEL_STRUCTURED_OUTPUT must be auto, json_schema, or off"
            )
        self.json_schema_roles = _structured_output_roles(
            mode=structured_mode,
            base_url=base_url,
            models=self.models,
        )
        self.max_tokens = int(os.getenv("MODEL_MAX_TOKENS", "4096"))
        self.diagnostic_dir = Path(diagnostic_dir) if diagnostic_dir else None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    async def _complete_text(
        self,
        *,
        role: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        output_schema: type[BaseModel],
    ) -> str:
        request: dict[str, Any] = {
            "model": self.models[role],
            "temperature": temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if role in self.json_schema_roles:
            schema_name = re.sub(r"[^a-zA-Z0-9_-]", "_", output_schema.__name__)
            request.update(
                {
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema_name,
                            "schema": output_schema.model_json_schema(),
                        },
                    }
                }
            )
        result = await self.client.chat.completions.create(**request)
        return result.choices[0].message.content or ""

    async def complete_structured(
        self,
        *,
        role: str,
        system_prompt: str,
        input_payload: dict[str, Any],
        output_schema: type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        payload = dict(input_payload)
        payload["output_schema"] = output_schema.model_json_schema()
        error = ""
        text = ""
        for attempt in range(2):
            if error:
                payload["repair_instruction"] = (
                    "上次输出未通过 JSON 解析或 schema 校验。请根据错误修复上次输出，"
                    "只返回一个符合 output_schema 的 JSON 对象，不要添加 Markdown 或解释。"
                )
                payload["validation_error"] = error
                payload["invalid_previous_output"] = text[-12000:]
            text = await self._complete_text(
                role=role,
                system_prompt=system_prompt,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                temperature=temperature,
                output_schema=output_schema,
            )
            try:
                return output_schema.model_validate(json.loads(_strip_fence(text)))
            except Exception as exc:
                error = str(exc)
                self._write_invalid_output(
                    role=role,
                    output_schema=output_schema,
                    attempt=attempt + 1,
                    error=error,
                    text=text,
                )
        raise ValueError(
            f"{self.provider_name}/{role} failed {output_schema.__name__}: {error}"
        )

    def _write_invalid_output(
        self,
        *,
        role: str,
        output_schema: type[BaseModel],
        attempt: int,
        error: str,
        text: str,
    ) -> None:
        if self.diagnostic_dir is None:
            return
        self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        path = self.diagnostic_dir / (
            f"{timestamp}-{role}-{output_schema.__name__}-"
            f"attempt-{attempt}-{uuid.uuid4().hex[:8]}.json"
        )
        path.write_text(
            json.dumps(
                {
                    "role": role,
                    "output_schema": output_schema.__name__,
                    "attempt": attempt,
                    "error": error,
                    "raw_response": text,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def create_gateway(*, diagnostic_dir: Path | None = None) -> ModelGateway:
    return OpenAICompatibleGateway(diagnostic_dir=diagnostic_dir)


def _structured_output_roles(
    *, mode: str, base_url: str | None, models: dict[str, str],
) -> set[str]:
    if mode == "off":
        return set()
    if mode == "json_schema":
        return set(models)
    if not base_url or "chat.ecnu.edu.cn" not in base_url.lower():
        return set()
    return {
        role
        for role, model in models.items()
        if model.strip().lower() in ECNU_JSON_SCHEMA_MODELS
    }


def _strip_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        return "\n".join(lines)
    return value
