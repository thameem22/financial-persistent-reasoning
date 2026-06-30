"""Offline unit tests (no Docker required)."""

from __future__ import annotations

from pathlib import Path

from services.layer1_ingestion.document_parser.service import html_to_text
from shared.llm_client import SCHEMA_BY_CLASS
from shared.schemas.claims import ObjectClass
from shared.section_patterns import SECTION_PATTERNS


def test_section_patterns_defined():
    assert len(SECTION_PATTERNS) >= 4


def test_html_to_text_extracts_items():
    html = Path("data/samples/msft-10k-fy2024.html").read_text(encoding="utf-8")
    text = html_to_text(html)
    assert "ITEM 1A" in text.upper() or "RISK FACTORS" in text.upper()
    assert "Azure" in text


def test_llm_schemas_cover_core_classes():
    for cls in (
        ObjectClass.RISK,
        ObjectClass.DOCTRINE,
        ObjectClass.CAPABILITY,
        ObjectClass.ACTIVE_STATE,
        ObjectClass.ACTIVE_OBLIGATION,
    ):
        assert cls in SCHEMA_BY_CLASS
