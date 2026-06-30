"""Postgres repositories — explicit read/write paths per layer."""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import uuid4

from shared.db import execute, fetch_all, fetch_one
from shared.schemas.claims import ClaimRecord
from shared.schemas.documents import ChunkRecord, DocumentRecord


# ─── Layer 1: staging ───────────────────────────────────────────────────────


def insert_document(doc: DocumentRecord) -> None:
    execute(
        """
        INSERT INTO staging.documents (
            doc_id, company_ticker, company_cik, doc_type, filing_date,
            fiscal_period, accession_number, source_url, raw_format, raw_path
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (doc_id) DO NOTHING
        """,
        (
            doc.doc_id,
            doc.company_ticker,
            doc.company_cik,
            doc.doc_type,
            doc.filing_date,
            doc.fiscal_period,
            doc.accession_number,
            doc.source_url,
            doc.raw_format,
            doc.raw_path,
        ),
    )


def get_document(doc_id: str) -> dict[str, Any] | None:
    return fetch_one(
        "SELECT * FROM staging.documents WHERE doc_id = %s",
        (doc_id,),
    )


def insert_chunks(chunks: list[ChunkRecord]) -> int:
    for chunk in chunks:
        execute(
            """
            INSERT INTO staging.chunks (
                chunk_id, doc_id, company_ticker, section_path,
                fiscal_period_covered, filing_date, source_url, text
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chunk_id) DO NOTHING
            """,
            (
                chunk.chunk_id,
                chunk.doc_id,
                chunk.company_ticker,
                chunk.section_path,
                chunk.fiscal_period_covered,
                chunk.filing_date,
                chunk.source_url,
                chunk.text,
            ),
        )
    return len(chunks)


def get_chunks_for_doc(doc_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT * FROM staging.chunks
        WHERE doc_id = %s
        ORDER BY section_path
        """,
        (doc_id,),
    )


def get_chunks_by_section(
    company_ticker: str,
    fiscal_period: str,
    section_path: str,
) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT * FROM staging.chunks
        WHERE company_ticker = %s
          AND fiscal_period_covered = %s
          AND section_path = %s
        """,
        (company_ticker, fiscal_period, section_path),
    )


# ─── Layer 2: extraction ────────────────────────────────────────────────────


def insert_claim(claim: ClaimRecord) -> None:
    execute(
        """
        INSERT INTO extraction.claims (
            claim_id, chunk_id, company_ticker, object_class, payload,
            confidence, effective_from, effective_to, stated_from, stated_to,
            extraction_run_id, reconciliation_status
        ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (claim_id) DO NOTHING
        """,
        (
            claim.claim_id,
            claim.chunk_id,
            claim.company_ticker,
            claim.object_class.value,
            json.dumps(claim.payload),
            claim.confidence,
            claim.effective_from,
            claim.effective_to,
            claim.stated_from,
            claim.stated_to,
            claim.extraction_run_id,
            claim.reconciliation_status,
        ),
    )


def get_pending_claims_for_doc(doc_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT c.*
        FROM extraction.claims c
        JOIN staging.chunks ch ON ch.chunk_id = c.chunk_id
        WHERE ch.doc_id = %s
          AND c.reconciliation_status = 'pending'
        ORDER BY c.created_at
        """,
        (doc_id,),
    )


def update_claim_status(claim_id: str, status: str) -> None:
    execute(
        """
        UPDATE extraction.claims
        SET reconciliation_status = %s
        WHERE claim_id = %s
        """,
        (status, claim_id),
    )


# ─── Layer 3: reasoning ───────────────────────────────────────────────────


def upsert_entity_alias(
    alias_text: str,
    canonical_id: str,
    entity_type: str,
    company_ticker: str | None,
) -> None:
    execute(
        """
        INSERT INTO reasoning.entity_aliases (alias_text, canonical_id, entity_type, company_ticker)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (alias_text, canonical_id) DO NOTHING
        """,
        (alias_text, canonical_id, entity_type, company_ticker),
    )


def insert_state_transition(
    *,
    company_ticker: str,
    object_class: str,
    canonical_object_id: str,
    transition_type: str,
    old_value: dict | None,
    new_value: dict | None,
    claim_id: str | None,
    chunk_id: str | None,
    stated_at: date,
    policy_applied: str,
) -> str:
    transition_id = f"st-{uuid4().hex[:12]}"
    execute(
        """
        INSERT INTO reasoning.state_transitions (
            transition_id, company_ticker, object_class, canonical_object_id,
            transition_type, old_value, new_value, claim_id, chunk_id,
            stated_at, policy_applied
        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
        """,
        (
            transition_id,
            company_ticker,
            object_class,
            canonical_object_id,
            transition_type,
            json.dumps(old_value) if old_value else None,
            json.dumps(new_value) if new_value else None,
            claim_id,
            chunk_id,
            stated_at,
            policy_applied,
        ),
    )
    return transition_id


def get_trajectory(company_ticker: str, canonical_object_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT transition_id, stated_at, transition_type, old_value, new_value,
               claim_id, chunk_id, policy_applied
        FROM reasoning.state_transitions
        WHERE company_ticker = %s AND canonical_object_id = %s
        ORDER BY stated_at
        """,
        (company_ticker, canonical_object_id),
    )


def get_provenance_for_chunk(chunk_id: str) -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT ch.*, d.accession_number
        FROM staging.chunks ch
        JOIN staging.documents d ON d.doc_id = ch.doc_id
        WHERE ch.chunk_id = %s
        """,
        (chunk_id,),
    )


def reset_document_pipeline(doc_id: str) -> None:
    """Remove prior chunks, claims, and transitions for a doc so re-runs are idempotent."""
    execute(
        """
        DELETE FROM reasoning.state_transitions st
        USING extraction.claims c
        JOIN staging.chunks ch ON ch.chunk_id = c.chunk_id
        WHERE st.claim_id = c.claim_id AND ch.doc_id = %s
        """,
        (doc_id,),
    )
    execute(
        """
        DELETE FROM extraction.claims c
        USING staging.chunks ch
        WHERE c.chunk_id = ch.chunk_id AND ch.doc_id = %s
        """,
        (doc_id,),
    )
    execute("DELETE FROM staging.chunks WHERE doc_id = %s", (doc_id,))
