"""Anthropic / OpenAI structured extraction for Layer 2."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from shared.config import get_settings
from shared.schemas.claims import (
    ActiveObligationPayload,
    ActiveStatePayload,
    CapabilityPayload,
    DoctrinePayload,
    ObjectClass,
    RiskPayload,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You extract structured enterprise facts from SEC filing text.
Return ONLY facts explicitly supported by the text. Do not summarize the whole section.
One distinct fact per array item. Use exact wording from the filing where possible."""


class RiskClaimList(BaseModel):
    claims: list[RiskPayload] = Field(default_factory=list)


class DoctrineClaimList(BaseModel):
    claims: list[DoctrinePayload] = Field(default_factory=list)


class CapabilityClaimList(BaseModel):
    claims: list[CapabilityPayload] = Field(default_factory=list)


class ActiveStateClaimList(BaseModel):
    claims: list[ActiveStatePayload] = Field(default_factory=list)


class ActiveObligationClaimList(BaseModel):
    claims: list[ActiveObligationPayload] = Field(default_factory=list)


SCHEMA_BY_CLASS: dict[ObjectClass, type[BaseModel]] = {
    ObjectClass.RISK: RiskClaimList,
    ObjectClass.DOCTRINE: DoctrineClaimList,
    ObjectClass.CAPABILITY: CapabilityClaimList,
    ObjectClass.ACTIVE_STATE: ActiveStateClaimList,
    ObjectClass.ACTIVE_OBLIGATION: ActiveObligationClaimList,
}


def _build_user_prompt(chunk: dict, object_class: ObjectClass) -> str:
    return (
        f"Company: {chunk['company_ticker']}\n"
        f"Section: {chunk['section_path']}\n"
        f"Filing date: {chunk['filing_date']}\n"
        f"Fiscal period: {chunk['fiscal_period_covered']}\n"
        f"Extract object class: {object_class.value}\n\n"
        f"--- BEGIN SECTION TEXT ---\n{chunk['text']}\n--- END SECTION TEXT ---"
    )


def _anthropic_extract(chunk: dict, object_class: ObjectClass) -> list[dict]:
    import anthropic

    settings = get_settings()
    schema_model = SCHEMA_BY_CLASS[object_class]
    tool_schema = schema_model.model_json_schema()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(chunk, object_class)}],
        tools=[
            {
                "name": "submit_claims",
                "description": f"Submit extracted {object_class.value} claims",
                "input_schema": tool_schema,
            }
        ],
        tool_choice={"type": "tool", "name": "submit_claims"},
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_claims":
            parsed = schema_model.model_validate(block.input)
            return [claim.model_dump() for claim in parsed.claims]
    return []


def _openai_extract(chunk: dict, object_class: ObjectClass) -> list[dict]:
    from openai import OpenAI

    settings = get_settings()
    schema_model = SCHEMA_BY_CLASS[object_class]
    client = OpenAI(api_key=settings.openai_api_key)

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(chunk, object_class)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "submit_claims",
                "strict": True,
                "schema": schema_model.model_json_schema(),
            },
        },
    )
    content = response.choices[0].message.content
    if not content:
        return []
    parsed = schema_model.model_validate(json.loads(content))
    return [claim.model_dump() for claim in parsed.claims]


def llm_available() -> bool:
    settings = get_settings()
    if settings.llm_provider == "openai":
        return bool(settings.openai_api_key)
    return bool(settings.anthropic_api_key)


def extract_with_llm(chunk: dict, object_class: ObjectClass) -> list[dict]:
    if object_class not in SCHEMA_BY_CLASS:
        logger.warning("No LLM schema for %s", object_class)
        return []

    settings = get_settings()
    try:
        if settings.llm_provider == "openai":
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is not set")
            return _openai_extract(chunk, object_class)
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        return _anthropic_extract(chunk, object_class)
    except Exception:
        logger.exception(
            "LLM extraction failed for %s / %s",
            chunk.get("chunk_id"),
            object_class.value,
        )
        raise
