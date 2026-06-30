"""
End-to-end pipeline orchestrator.

Chains Layer 1 → Layer 2 → Layer 3 for one document.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from shared.llm_client import llm_available
from shared.repositories import reset_document_pipeline

from services.layer1_ingestion.edgar_fetcher.service import (
    fetch_latest_10k,
    ingest_from_local,
)
from services.layer1_ingestion.section_chunker.service import chunk_document
from services.layer2_extraction.llm_extractor.service import extract_claims
from services.layer3_reasoning.reconciliation_engine.service import reconcile_claims

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_pipeline(
    *,
    ticker: str,
    use_mock: bool = False,
    use_edgar: bool = False,
    sample_html: Path | None = None,
    reset: bool = True,
) -> dict:
    if use_edgar:
        doc_id = fetch_latest_10k(ticker)
        if not doc_id:
            raise RuntimeError(f"No 10-K found for {ticker}")
    else:
        sample = sample_html or Path("data/samples/msft-10k-fy2024.html")
        if not sample.exists():
            raise FileNotFoundError(f"Sample HTML not found: {sample}")
        doc_id = f"doc-{ticker.lower()}-10k-fy2024-sample"
        ingest_from_local(
            doc_id=doc_id,
            company_ticker=ticker.upper(),
            fiscal_period="FY2024",
            filing_date=date(2024, 7, 30),
            local_html_path=sample,
        )

    if reset:
        reset_document_pipeline(doc_id)

    chunk_ids = chunk_document(doc_id)
    claim_ids = extract_claims(doc_id, use_mock=use_mock)
    canonical_ids = reconcile_claims(doc_id)

    mode = "mock" if use_mock or not llm_available() else "llm"
    return {
        "doc_id": doc_id,
        "mode": mode,
        "chunks": len(chunk_ids),
        "claims": len(claim_ids),
        "reconciled": len(canonical_ids),
        "canonical_ids": canonical_ids[:5],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Financial Persistent Reasoning pipeline")
    parser.add_argument("--ticker", default="MSFT")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force rule-based extraction (no LLM API calls)",
    )
    parser.add_argument(
        "--edgar",
        action="store_true",
        help="Fetch live 10-K from SEC EDGAR instead of sample HTML",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Do not delete prior chunks/claims for this doc before re-run",
    )
    args = parser.parse_args()

    try:
        result = run_pipeline(
            ticker=args.ticker,
            use_mock=args.mock,
            use_edgar=args.edgar,
            reset=not args.no_reset,
        )
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc)
        logger.error("Ensure Docker is up: docker compose up -d")
        logger.error("Then init DB: python scripts/init_db.py")
        sys.exit(1)

    print("\nPipeline complete:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    print("\nQuery API:")
    print("  uvicorn services.layer3_reasoning.query_api.app:app --reload --port 8080")
    print(f"  curl http://127.0.0.1:8080/enterprise/{args.ticker.upper()}/risks")


if __name__ == "__main__":
    main()
