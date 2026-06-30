"""
Entity resolver — Layer 3

Reads:  strings from claim payloads
Writes: reasoning.entity_aliases (Postgres)

Maps surface names to stable canonical IDs for graph nodes and audit log.
"""

from __future__ import annotations

import hashlib
import re

from shared.repositories import upsert_entity_alias
from shared.schemas.claims import ObjectClass


def company_id(ticker: str) -> str:
    canonical = f"entity:{ticker.upper()}"
    upsert_entity_alias(ticker.upper(), canonical, "company", ticker.upper())
    upsert_entity_alias(ticker.title(), canonical, "company", ticker.upper())
    return canonical


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "unknown"


def resolve_object_id(
    *,
    company_ticker: str,
    object_class: ObjectClass,
    payload: dict,
) -> str:
    ticker = company_ticker.upper()

    if object_class == ObjectClass.RISK:
        topic = payload.get("description", "")[:80]
        slug = _slug(topic)
        canonical = f"risk:{ticker}:{slug}"
        upsert_entity_alias(payload.get("description", "")[:120], canonical, "risk", ticker)
        return canonical

    if object_class == ObjectClass.CAPABILITY:
        name = payload.get("name", "unknown")
        canonical = f"capability:{ticker}:{_slug(name)}"
        upsert_entity_alias(name, canonical, "capability", ticker)
        return canonical

    if object_class == ObjectClass.DOCTRINE:
        topic = payload.get("topic", payload.get("statement", "doctrine")[:40])
        canonical = f"doctrine:{ticker}:{_slug(str(topic))}"
        upsert_entity_alias(str(topic), canonical, "doctrine", ticker)
        return canonical

    if object_class == ObjectClass.ACTIVE_STATE:
        metric = payload.get("metric", "state")
        period = payload.get("as_of_period", "unknown")
        canonical = f"state:{ticker}:{_slug(metric)}-{period.lower()}"
        upsert_entity_alias(metric, canonical, "active_state", ticker)
        return canonical

    if object_class == ObjectClass.ACTIVE_OBLIGATION:
        desc = payload.get("description", "obligation")
        canonical = f"obligation:{ticker}:{_slug(desc)}"
        upsert_entity_alias(desc[:120], canonical, "obligation", ticker)
        return canonical

    if object_class == ObjectClass.MANAGEMENT_DECISION:
        desc = payload.get("description", "decision")
        canonical = f"decision:{ticker}:{_slug(desc)}"
        upsert_entity_alias(desc[:120], canonical, "decision", ticker)
        return canonical

    if object_class == ObjectClass.CAUSAL_RELATIONSHIP:
        key = f"{payload.get('from_ref')}->{payload.get('to_ref')}"
        digest = hashlib.sha256(key.encode()).hexdigest()[:12]
        return f"causal:{ticker}:{digest}"

    digest = hashlib.sha256(str(payload).encode()).hexdigest()[:12]
    return f"{object_class.value.lower()}:{ticker}:{digest}"
