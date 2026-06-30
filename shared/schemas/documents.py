"""Layer 1 staging models."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class DocumentRecord(BaseModel):
    doc_id: str
    company_ticker: str
    company_cik: str | None = None
    doc_type: str
    filing_date: date
    fiscal_period: str
    accession_number: str | None = None
    source_url: str
    raw_format: str = "html"
    raw_path: str | None = None
    ingested_at: datetime | None = None


class ChunkRecord(BaseModel):
    chunk_id: str
    doc_id: str
    company_ticker: str
    section_path: str
    fiscal_period_covered: str
    filing_date: date
    source_url: str
    text: str
