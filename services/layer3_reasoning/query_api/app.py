"""
Query API — Layer 3

Reads:  Neo4j (current graph), Postgres (trajectory, provenance)
Writes: HTTP JSON responses only
"""

from __future__ import annotations

import json
from datetime import date

from fastapi import FastAPI, HTTPException, Query

from shared.neo4j_client import run_cypher
from shared.repositories import get_provenance_for_chunk, get_trajectory

app = FastAPI(title="Financial Persistent Reasoning API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/enterprise/{ticker}/risks")
def current_risks(ticker: str) -> dict:
    rows = run_cypher(
        """
        MATCH (c:Company {ticker: $ticker})-[:HAS_RISK]->(r:Risk)
        WHERE r.status = 'active'
        RETURN r.id AS id, r.payload AS payload, r.stated_at AS stated_at
        ORDER BY r.id
        """,
        {"ticker": ticker.upper()},
    )
    for row in rows:
        if isinstance(row.get("payload"), str):
            row["payload"] = json.loads(row["payload"])
    return {"ticker": ticker.upper(), "risks": rows}


@app.get("/enterprise/{ticker}/capabilities")
def current_capabilities(ticker: str) -> dict:
    rows = run_cypher(
        """
        MATCH (c:Company {ticker: $ticker})-[:OFFERS]->(cap:Capability)
        RETURN cap.id AS id, cap.payload AS payload
        ORDER BY cap.id
        """,
        {"ticker": ticker.upper()},
    )
    for row in rows:
        if isinstance(row.get("payload"), str):
            row["payload"] = json.loads(row["payload"])
    return {"ticker": ticker.upper(), "capabilities": rows}


@app.get("/enterprise/{ticker}/trajectory")
def trajectory(
    ticker: str,
    object_id: str = Query(..., description="Canonical object id, e.g. risk:MSFT:..."),
) -> dict:
    rows = get_trajectory(ticker.upper(), object_id)
    return {"ticker": ticker.upper(), "object_id": object_id, "transitions": rows}


@app.get("/enterprise/{ticker}/provenance/{chunk_id}")
def provenance(ticker: str, chunk_id: str) -> dict:
    row = get_provenance_for_chunk(chunk_id)
    if not row or row["company_ticker"] != ticker.upper():
        raise HTTPException(status_code=404, detail="Chunk not found")
    return {"ticker": ticker.upper(), "provenance": row}


@app.get("/enterprise/{ticker}/as-of")
def as_of(
    ticker: str,
    as_of_date: date = Query(..., alias="date"),
    object_id: str | None = None,
) -> dict:
    """Reconstruct belief from audit log using stated_at <= as_of_date."""
    from shared.db import fetch_all

    sql = """
        SELECT DISTINCT ON (canonical_object_id)
            canonical_object_id, object_class, new_value, stated_at, chunk_id
        FROM reasoning.state_transitions
        WHERE company_ticker = %s AND stated_at <= %s
    """
    params: list = [ticker.upper(), as_of_date]
    if object_id:
        sql += " AND canonical_object_id = %s"
        params.append(object_id)
    sql += " ORDER BY canonical_object_id, stated_at DESC"

    rows = fetch_all(sql, tuple(params))
    return {"ticker": ticker.upper(), "as_of": as_of_date.isoformat(), "objects": rows}
