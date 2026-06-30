"""SEC section patterns for 10-K chunking."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SectionPattern:
    regex: re.Pattern[str]
    section_path: str


SECTION_PATTERNS: list[SectionPattern] = [
    SectionPattern(
        re.compile(r"ITEM\s+1A[\.\s—\-]+RISK FACTORS", re.I),
        "Item 1A — Risk Factors",
    ),
    SectionPattern(
        re.compile(r"ITEM\s+1[\.\s—\-]+BUSINESS", re.I),
        "Item 1 — Business",
    ),
    SectionPattern(
        re.compile(
            r"ITEM\s+7[\.\s—\-]+MANAGEMENT['']S DISCUSSION",
            re.I,
        ),
        "Item 7 — MD&A",
    ),
    SectionPattern(
        re.compile(r"ITEM\s+8[\.\s—\-]+FINANCIAL STATEMENTS", re.I),
        "Item 8 — Financial Statements",
    ),
]
