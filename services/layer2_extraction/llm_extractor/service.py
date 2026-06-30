"""
LLM extractor — Layer 2

Reads:  staging.chunks (Postgres SQL — NOT Neo4j, NOT vector DB)
Writes: extraction.claims (Postgres)

LLM role: produce typed JSON claims with provenance. Does NOT reconcile or write graph.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from uuid import uuid4

from shared.config import get_settings
from shared.llm_client import extract_with_llm, llm_available
from shared.repositories import get_chunks_for_doc, insert_claim
from shared.schemas.claims import (
    ActiveObligationPayload,
    ActiveStatePayload,
    CapabilityPayload,
    ClaimRecord,
    DoctrinePayload,
    ObjectClass,
    RiskPayload,
)

logger = logging.getLogger(__name__)

SECTION_CLASS_MAP: dict[str, list[ObjectClass]] = {
    "Item 1 — Business": [ObjectClass.DOCTRINE, ObjectClass.CAPABILITY],
    "Item 1A — Risk Factors": [ObjectClass.RISK],
    "Item 7 — MD&A": [
        ObjectClass.ACTIVE_STATE,
        ObjectClass.ACTIVE_OBLIGATION,
        ObjectClass.DOCTRINE,
    ],
    "Item 8 — Financial Statements": [
        ObjectClass.ACTIVE_STATE,
        ObjectClass.ACTIVE_OBLIGATION,
    ],
}


def _mock_extract_risks(text: str) -> list[dict]:
    claims = []
    for paragraph in re.split(r"\n{2,}|\.\s+", text):
        paragraph = paragraph.strip()
        if len(paragraph) < 30:
            continue
        lower = paragraph.lower()
        if not any(k in lower for k in ("risk", "regulation", "competition", "cyber")):
            continue
        severity = "high" if "regulatory" in lower or "regulation" in lower else "medium"
        category = (
            "regulatory"
            if "regulation" in lower
            else "competitive"
            if "competition" in lower
            else "cybersecurity"
        )
        claims.append(
            RiskPayload(
                risk_category=category,
                description=paragraph[:500],
                severity=severity,
            ).model_dump()
        )
    return claims


def _mock_extract_doctrine(text: str) -> list[dict]:
    match = re.search(r"Our strategy is[^.]+\.", text, re.I)
    if match or "artificial intelligence" in text.lower():
        statement = match.group(0) if match else text[:200]
        return [
            DoctrinePayload(
                statement=statement,
                topic="AI and cloud strategy",
            ).model_dump()
        ]
    return []


def _mock_extract_capabilities(text: str) -> list[dict]:
    claims = []
    for name in ("Azure", "Copilot", "AWS", "Prime"):
        if name in text:
            claims.append(
                CapabilityPayload(
                    name=name,
                    category="cloud infrastructure" if name == "Azure" else "product",
                    description=f"{name} mentioned in business section",
                ).model_dump()
            )
    return claims


def _mock_extract_active_states(text: str, fiscal_period: str) -> list[dict]:
    claims = []
    revenue_match = re.search(
        r"revenue was \$([\d.]+) billion.*?(\d+)%", text, re.I | re.S
    )
    if revenue_match:
        claims.append(
            ActiveStatePayload(
                metric="Total revenue",
                value=float(revenue_match.group(1)) * 1e9,
                unit="USD",
                change_pct=float(revenue_match.group(2)),
                as_of_period=fiscal_period,
            ).model_dump()
        )
    cloud_match = re.search(
        r"Intelligent Cloud revenue increased (\d+)% to \$([\d.]+) billion", text, re.I
    )
    if cloud_match:
        claims.append(
            ActiveStatePayload(
                metric="Intelligent Cloud revenue",
                value=float(cloud_match.group(2)) * 1e9,
                unit="USD",
                change_pct=float(cloud_match.group(1)),
                as_of_period=fiscal_period,
            ).model_dump()
        )
    return claims


def _mock_extract_obligations(text: str) -> list[dict]:
    if "capital expenditure" in text.lower():
        return [
            ActiveObligationPayload(
                obligation_type="capex",
                description="Increased capital expenditures for AI infrastructure",
            ).model_dump()
        ]
    return []


def _mock_extract_for_class(
    text: str, object_class: ObjectClass, fiscal_period: str
) -> list[dict]:
    extractors = {
        ObjectClass.RISK: lambda t: _mock_extract_risks(t),
        ObjectClass.DOCTRINE: lambda t: _mock_extract_doctrine(t),
        ObjectClass.CAPABILITY: lambda t: _mock_extract_capabilities(t),
        ObjectClass.ACTIVE_STATE: lambda t: _mock_extract_active_states(t, fiscal_period),
        ObjectClass.ACTIVE_OBLIGATION: lambda t: _mock_extract_obligations(t),
    }
    fn = extractors.get(object_class)
    return fn(text) if fn else []


def _effective_from(filing_date: date) -> date:
    return date(filing_date.year - 1, 7, 1) if filing_date.month >= 7 else date(filing_date.year, 1, 1)


def _extract_payloads(chunk: dict, object_class: ObjectClass, *, use_mock: bool) -> list[dict]:
    fiscal_period = chunk["fiscal_period_covered"]
    if use_mock:
        return _mock_extract_for_class(chunk["text"], object_class, fiscal_period)
    return extract_with_llm(chunk, object_class)


def extract_claims(doc_id: str, *, use_mock: bool = False) -> list[str]:
    chunks = get_chunks_for_doc(doc_id)
    if not chunks:
        raise ValueError(f"No chunks for document: {doc_id}")

    settings = get_settings()
    if not use_mock and not llm_available():
        logger.warning(
            "No LLM API key configured (%s); using mock extraction. "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env to use a real model.",
            settings.llm_provider,
        )
        use_mock = True

    run_id = f"run-{uuid4().hex[:12]}"
    claim_ids: list[str] = []

    for chunk in chunks:
        section_path = chunk["section_path"]
        classes = SECTION_CLASS_MAP.get(section_path, [])
        filing_date = chunk["filing_date"]
        if isinstance(filing_date, str):
            filing_date = date.fromisoformat(filing_date)

        for object_class in classes:
            payloads = _extract_payloads(chunk, object_class, use_mock=use_mock)
            for payload in payloads:
                claim_id = f"clm-{uuid4().hex[:12]}"
                claim = ClaimRecord(
                    claim_id=claim_id,
                    chunk_id=chunk["chunk_id"],
                    company_ticker=chunk["company_ticker"],
                    object_class=object_class,
                    payload=payload,
                    confidence=0.85 if use_mock else 0.92,
                    effective_from=_effective_from(filing_date),
                    stated_from=filing_date,
                    extraction_run_id=run_id,
                )
                insert_claim(claim)
                claim_ids.append(claim_id)

    return claim_ids
