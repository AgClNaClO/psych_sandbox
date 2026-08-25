"""Pydantic -> Jinja2 -> model -> Pydantic prompt pipeline.

Implements the canonical LLM-call shape used across the agents::

    用户/业务数据
        ↓
    Pydantic 输入校验          (input_schema.validate)
        ↓
    Jinja2 渲染 Prompt         (render_prompt)
        ↓
    调用大模型                  (gateway.complete_structured, JSON output)
        ↓
    Pydantic 输出解析与验证      (output_schema.model_validate)
        ↓
    业务系统

A single entry point, :func:`run_prompt`, keeps the input schema, the template,
the output schema and the temperature together for one call site.  Input data is
first validated by ``input_schema``; the validated JSON is used both as the render
context and as the model user-message payload.  The gateway receives the rendered
system prompt, requests a structured JSON response, and returns an object already
validated against ``output_schema``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .model_client import ModelGateway
from .prompts import render_prompt

__all__ = ["run_pipeline"]


async def run_pipeline(
    *,
    gateway: ModelGateway,
    role: str,
    template: str,
    input_schema: type[BaseModel],
    output_schema: type[BaseModel],
    temperature: float,
    data: dict[str, Any] | None = None,
    **extra: Any,
) -> BaseModel:
    """Run the full prompt pipeline and return a validated ``output_schema``.

    Parameters
    ----------
    gateway
        The API/structured-output gateway.
    role
        Role key that maps to a model name on ``gateway`` (``client``,
        ``counselor``, ``summarizer``, ...).
    template
        Jinja2 prompt path under ``prompts/`` (forward slashes).
    input_schema
        Pydantic model used to validate the business data before rendering.
    output_schema
        Pydantic model used to validate (and returned from) the model response.
    temperature
        Sampling temperature.
    data
        Raw business/user data that gets validated by ``input_schema``.
    extra
        Optional render-only variables that are merged into the Jinja2 context
        *after* the validated input (never user-controlled model payload).
    """
    # 1. Pydantic 输入校验
    validated = input_schema.model_validate(data or {})
    context = validated.model_dump(mode="json")
    context.update(extra)

    # 2. Jinja2 渲染 + 3. 调用大模型 + 4./5. 结构化输出与 Pydantic 解析
    result = await gateway.complete_structured(
        role=role,
        system_prompt=render_prompt(template, **context),
        input_payload=validated.model_dump(mode="json"),
        output_schema=output_schema,
        temperature=temperature,
    )
    # The gateway already validated against output_schema; re-validate to make
    # the "output parse + verify" stage explicit and to normalize any subclass.
    return output_schema.model_validate(result)