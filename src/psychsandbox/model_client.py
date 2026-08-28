from __future__ import annotations

import json
import hashlib
import os
import re
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential


ECNU_JSON_SCHEMA_MODELS = {"ecnu-plus", "ecnu-turbo"}
ECNU_BASE_URL = "https://chat.ecnu.edu.cn/open/api/v1"
ECNU_EMBEDDING_MAX_CHARS = 8192
_diagnostic_scope: ContextVar[Path | None] = ContextVar("model_diagnostic_scope", default=None)
_request_meta: ContextVar[dict | None] = ContextVar("model_request_meta", default=None)


@contextmanager
def model_diagnostic_scope(directory: Path):
    """Attribute API diagnostics to the current async candidate, not its peers."""
    token = _diagnostic_scope.set(directory)
    try:
        yield
    finally:
        _diagnostic_scope.reset(token)


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

    @property
    def embedding_model(self) -> str:
        raise RuntimeError("This gateway does not configure an embedding model")

    @property
    def embedding_identity(self) -> str:
        return self.embedding_model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("This gateway does not support embeddings")


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
        self.json_object_roles = _json_object_roles(
            mode=structured_mode,
            models=self.models,
            json_schema_roles=self.json_schema_roles,
        )
        self.max_tokens = int(os.getenv("MODEL_MAX_TOKENS", "4096"))
        self.diagnostic_dir = Path(diagnostic_dir) if diagnostic_dir else None

    def _embedding_config(self) -> tuple[str, str, str]:
        chat_base_url = os.getenv("MODEL_BASE_URL", "").strip()
        base_url = os.getenv("EMBEDDING_BASE_URL", "").strip()
        model = os.getenv("EMBEDDING_MODEL", "").strip()
        api_key = os.getenv("EMBEDDING_API_KEY", "").strip()
        if _is_ecnu_endpoint(chat_base_url):
            base_url = base_url or chat_base_url
            if _is_ecnu_endpoint(base_url):
                model = model or "ecnu-embedding-small"
                api_key = api_key or os.getenv("MODEL_API_KEY", "").strip()
        if _is_ecnu_endpoint(base_url):
            base_url = ECNU_BASE_URL
        missing = [name for name, value in (
            ("EMBEDDING_MODEL", model), ("EMBEDDING_BASE_URL", base_url),
            ("EMBEDDING_API_KEY", api_key),
        ) if not value]
        if missing:
            raise RuntimeError("Large skill queries require " + ", ".join(missing))
        return base_url, model, api_key

    @property
    def embedding_model(self) -> str:
        return self._embedding_config()[1]

    @property
    def embedding_identity(self) -> str:
        base_url, model, _ = self._embedding_config()
        identity = [base_url.rstrip("/"), model]
        return hashlib.sha256(json.dumps(identity).encode("utf-8")).hexdigest()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        from openai import AsyncOpenAI

        base_url, model, api_key = self._embedding_config()
        ecnu = _is_ecnu_endpoint(base_url)
        batches: list[list[str]] = []
        batch: list[str] = []
        batch_chars = 0
        for index, text in enumerate(texts):
            if ecnu and len(text) > ECNU_EMBEDDING_MAX_CHARS:
                raise ValueError(
                    f"Embedding input at index {index} exceeds the ChatECNU "
                    f"limit of {ECNU_EMBEDDING_MAX_CHARS} characters"
                )
            if batch and (len(batch) == 64 or (
                ecnu and batch_chars + len(text) > ECNU_EMBEDDING_MAX_CHARS
            )):
                batches.append(batch)
                batch, batch_chars = [], 0
            batch.append(text)
            batch_chars += len(text)
        if batch:
            batches.append(batch)
        vectors = []
        async with AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "60")),
        ) as client:
            for batch in batches:
                result = await client.embeddings.create(
                    model=model, input=batch, encoding_format="float",
                )
                rows = sorted(result.data, key=lambda row: row.index)
                if [row.index for row in rows] != list(range(len(batch))):
                    raise ValueError("Embedding API returned missing or duplicate indices")
                vectors.extend(row.embedding for row in rows)
        return vectors

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    async def _complete_text(
        self,
        *,
        role: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        output_schema: type[BaseModel],
        force_json_schema: bool = False,
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
        if force_json_schema or role in self.json_schema_roles:
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
            _request_meta.set({"response_format": "json_schema", "temperature": temperature})
        elif role in getattr(self, "json_object_roles", set()):
            request.update({"response_format": {"type": "json_object"}})
            _request_meta.set({"response_format": "json_object", "temperature": temperature})
        else:
            _request_meta.set({"response_format": "none", "temperature": temperature})
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
                temperature=0.1 if attempt > 0 else temperature,
                output_schema=output_schema,
                force_json_schema=attempt > 0,
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
        fallback = _lenient_parse(output_schema, text)
        if fallback is not None:
            self._write_invalid_output(
                role=role,
                output_schema=output_schema,
                attempt=3,
                error="fell back to lenient single-field text parse",
                text=text,
            )
            return fallback
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
        diagnostic_dir = _diagnostic_scope.get() or self.diagnostic_dir
        if diagnostic_dir is None:
            return
        diagnostic_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        path = diagnostic_dir / f"{uuid.uuid4().hex[:12]}.json"
        meta = _request_meta.get() or {}
        path.write_text(
            json.dumps(
                {
                    "timestamp": timestamp,
                    "role": role,
                    "output_schema": output_schema.__name__,
                    "attempt": attempt,
                    "error": error,
                    "raw_response": text,
                    "request": meta,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def create_gateway(*, diagnostic_dir: Path | None = None) -> ModelGateway:
    return OpenAICompatibleGateway(diagnostic_dir=diagnostic_dir)


def _is_ecnu_endpoint(base_url: str) -> bool:
    """Match the official HTTPS API endpoint without widening the key boundary."""
    if any(char.isspace() for char in base_url):
        return False
    try:
        url = urlsplit(base_url)
    except ValueError:
        return False
    return (
        url.scheme == "https"
        and url.netloc.lower() in {"chat.ecnu.edu.cn", "chat.ecnu.edu.cn:443"}
        and url.path in {"/open/api/v1", "/open/api/v1/"}
        and not url.query
        and not url.fragment
    )


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


def _json_object_roles(
    *,
    mode: str,
    models: dict[str, str],
    json_schema_roles: set[str],
) -> set[str]:
    """Return roles that should use ``response_format={"type": "json_object"}``.

    Some OpenAI-compatible backends accept the looser ``json_object`` mode but
    reject the stricter ``json_schema`` mode (for example ``ecnu-max``).  The
    ``off`` mode disables all structured-output hints, while the explicit
    ``json_schema`` mode keeps every role on the stricter path and therefore
    leaves nothing for ``json_object``.
    """
    if mode == "off":
        return set()
    return set(models) - json_schema_roles


def _lenient_parse(
    output_schema: type[BaseModel],
    text: str,
) -> BaseModel | None:
    """Best-effort fallback for schemas whose single required field is a string.

    Some backends (notably ``ecnu-max`` under a strong role-play system prompt)
    ignore JSON constraints and emit the intended natural-language value
    directly. For text-oriented schemas (for example ``ClientUtterance``) that
    value is still meaningful, so we wrap it back into the schema. Schemas with
    multiple required fields or non-string payloads are left untouched so that
    genuine validation errors still surface.
    """
    stripped = text.strip()
    if not stripped:
        return None
    required = [
        name
        for name, field in output_schema.model_fields.items()
        if field.is_required()
    ]
    if len(required) != 1:
        return None
    candidate = required[0]
    try:
        return output_schema.model_validate({candidate: stripped})
    except Exception:
        return None


def _strip_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        return "\n".join(lines)
    return value
