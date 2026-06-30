"""
Section chunker — Layer 1

Reads:  cleaned text + staging.documents metadata
Writes: staging.chunks (Postgres)

Splits by SEC Items (1, 1A, 7, 8), not token count.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from shared.repositories import get_document, insert_chunks
from shared.schemas.documents import ChunkRecord
from shared.section_patterns import SECTION_PATTERNS

from services.layer1_ingestion.document_parser.service import parse_document


def _find_section_starts(text: str) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for pattern in SECTION_PATTERNS:
        for match in pattern.regex.finditer(text):
            matches.append((match.start(), pattern.section_path))
    matches.sort(key=lambda item: item[0])
    deduped: list[tuple[int, str]] = []
    seen_paths: set[str] = set()
    for start, path in matches:
        if path in seen_paths:
            continue
        seen_paths.add(path)
        deduped.append((start, path))
    return deduped


def chunk_document(doc_id: str) -> list[str]:
    doc = get_document(doc_id)
    if not doc:
        raise ValueError(f"Document not found: {doc_id}")

    text = parse_document(doc_id)
    starts = _find_section_starts(text)
    if not starts:
        raise ValueError(f"No SEC sections found in document: {doc_id}")

    chunks: list[ChunkRecord] = []
    chunk_ids: list[str] = []

    for index, (start, section_path) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        section_text = text[start:end].strip()
        if len(section_text) < 20:
            continue

        chunk_id = f"chk-{uuid4().hex[:12]}"
        chunk_ids.append(chunk_id)
        chunks.append(
            ChunkRecord(
                chunk_id=chunk_id,
                doc_id=doc_id,
                company_ticker=doc["company_ticker"],
                section_path=section_path,
                fiscal_period_covered=doc["fiscal_period"],
                filing_date=doc["filing_date"]
                if isinstance(doc["filing_date"], date)
                else date.fromisoformat(str(doc["filing_date"])),
                source_url=doc["source_url"],
                text=section_text,
            )
        )

    insert_chunks(chunks)
    return chunk_ids
