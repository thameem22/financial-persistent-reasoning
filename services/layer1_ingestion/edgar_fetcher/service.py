"""
EDGAR fetcher — Layer 1

Reads:  SEC data.sec.gov submissions API, Archives download URLs
Writes: staging.documents, raw file to data/raw/

Does NOT parse, chunk, or extract.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import httpx

from shared.config import get_settings
from shared.repositories import insert_document
from shared.schemas.documents import DocumentRecord

TICKER_CIK: dict[str, str] = {
    "MSFT": "0000789019",
    "AMZN": "0001018724",
}


def _headers() -> dict[str, str]:
    return {"User-Agent": get_settings().sec_user_agent}


def fetch_submissions(cik: str) -> dict[str, Any]:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    with httpx.Client(headers=_headers(), timeout=60.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def download_filing(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=_headers(), timeout=120.0) as client:
        response = client.get(url)
        response.raise_for_status()
        dest.write_bytes(response.content)
    return dest


def ingest_from_local(
    *,
    doc_id: str,
    company_ticker: str,
    fiscal_period: str,
    filing_date: date,
    local_html_path: Path,
    source_url: str = "local://sample",
) -> str:
    """Dry-run path: register a local HTML file as if fetched from EDGAR."""
    settings = get_settings()
    raw_dest = settings.data_dir / company_ticker / f"{doc_id}.html"
    raw_dest.parent.mkdir(parents=True, exist_ok=True)
    raw_dest.write_text(local_html_path.read_text(encoding="utf-8"), encoding="utf-8")

    doc = DocumentRecord(
        doc_id=doc_id,
        company_ticker=company_ticker,
        company_cik=TICKER_CIK.get(company_ticker),
        doc_type="10-K",
        filing_date=filing_date,
        fiscal_period=fiscal_period,
        accession_number=None,
        source_url=source_url,
        raw_format="html",
        raw_path=str(raw_dest),
    )
    insert_document(doc)
    return doc_id


def fetch_latest_10k(ticker: str) -> str | None:
    """Fetch most recent 10-K from EDGAR for ticker. Returns doc_id."""
    cik = TICKER_CIK.get(ticker.upper())
    if not cik:
        raise ValueError(f"Unknown ticker: {ticker}")

    submissions = fetch_submissions(cik)
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])

    for idx, form in enumerate(forms):
        if form != "10-K":
            continue
        accession = accessions[idx]
        filing_date = date.fromisoformat(filing_dates[idx])
        primary = primary_docs[idx]
        accession_path = accession.replace("-", "")
        cik_short = str(int(cik))
        source_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_short}/"
            f"{accession_path}/{primary}"
        )
        doc_id = f"doc-{ticker.lower()}-10k-{filing_date.year}"
        fiscal_period = f"FY{filing_date.year}"

        settings = get_settings()
        raw_dest = settings.data_dir / ticker.upper() / f"{doc_id}.html"
        download_filing(source_url, raw_dest)

        insert_document(
            DocumentRecord(
                doc_id=doc_id,
                company_ticker=ticker.upper(),
                company_cik=cik,
                doc_type="10-K",
                filing_date=filing_date,
                fiscal_period=fiscal_period,
                accession_number=accession,
                source_url=source_url,
                raw_format="html",
                raw_path=str(raw_dest),
            )
        )
        return doc_id
    return None
