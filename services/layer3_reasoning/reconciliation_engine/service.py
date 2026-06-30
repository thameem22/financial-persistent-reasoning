"""
Reconciliation engine — Layer 3

Reads:  extraction.claims (pending), existing Neo4j nodes
Writes: Neo4j graph (current enterprise model), reasoning.state_transitions (audit)

No LLM. Deterministic merge policies per object class.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from shared.neo4j_client import run_cypher
from shared.repositories import (
    get_pending_claims_for_doc,
    insert_state_transition,
    update_claim_status,
)
from shared.schemas.claims import ObjectClass, ReconciliationPolicy, policy_for

from services.layer3_reasoning.entity_resolver.service import company_id, resolve_object_id

NODE_LABEL = {
    ObjectClass.DOCTRINE: "Doctrine",
    ObjectClass.CAPABILITY: "Capability",
    ObjectClass.ACTIVE_STATE: "ActiveState",
    ObjectClass.ACTIVE_OBLIGATION: "Obligation",
    ObjectClass.RISK: "Risk",
    ObjectClass.MANAGEMENT_DECISION: "Decision",
}


def _get_existing_node(label: str, node_id: str) -> dict[str, Any] | None:
    rows = run_cypher(
        f"MATCH (n:{label} {{id: $id}}) RETURN n.payload AS payload, n.status AS status",
        {"id": node_id},
    )
    return rows[0] if rows else None


def _merge_company(ticker: str) -> None:
    cid = company_id(ticker)
    run_cypher(
        """
        MERGE (c:Company {id: $id})
        SET c.ticker = $ticker, c.name = $ticker
        """,
        {"id": cid, "ticker": ticker.upper()},
    )


def _merge_node(
    *,
    ticker: str,
    label: str,
    node_id: str,
    payload: dict,
    stated_at: date,
    rel: str,
) -> None:
    _merge_company(ticker)
    run_cypher(
        f"""
        MERGE (n:{label} {{id: $id}})
        SET n.payload = $payload,
            n.status = 'active',
            n.stated_at = date($stated_at),
            n.company_ticker = $ticker
        WITH n
        MATCH (c:Company {{id: $company_id}})
        MERGE (c)-[:{rel}]->(n)
        """,
        {
            "id": node_id,
            "payload": json.dumps(payload),
            "stated_at": stated_at.isoformat(),
            "ticker": ticker.upper(),
            "company_id": company_id(ticker),
        },
    )


REL_FOR_CLASS = {
    ObjectClass.DOCTRINE: "HOLDS_DOCTRINE",
    ObjectClass.CAPABILITY: "OFFERS",
    ObjectClass.ACTIVE_STATE: "HAS_STATE",
    ObjectClass.ACTIVE_OBLIGATION: "HAS_OBLIGATION",
    ObjectClass.RISK: "HAS_RISK",
    ObjectClass.MANAGEMENT_DECISION: "HAS_DECISION",
}


def _reconcile_claim(claim: dict) -> str:
    object_class = ObjectClass(claim["object_class"])
    payload = claim["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)

    ticker = claim["company_ticker"]
    canonical_id = resolve_object_id(
        company_ticker=ticker,
        object_class=object_class,
        payload=payload,
    )
    policy = policy_for(object_class)
    label = NODE_LABEL[object_class]
    existing = _get_existing_node(label, canonical_id)

    stated_at = claim["stated_from"]
    if isinstance(stated_at, str):
        stated_at = date.fromisoformat(stated_at)

    if existing is None:
        transition_type = "net_new"
        old_value = None
    elif policy == ReconciliationPolicy.NEWER_WINS:
        old_payload = json.loads(existing["payload"]) if existing.get("payload") else {}
        if old_payload == payload:
            transition_type = "confirm"
            old_value = old_payload
        else:
            transition_type = "supersede"
            old_value = old_payload
    else:
        old_payload = json.loads(existing["payload"]) if existing.get("payload") else {}
        transition_type = "confirm" if old_payload == payload else "net_new"
        old_value = old_payload if transition_type == "confirm" else None

    insert_state_transition(
        company_ticker=ticker,
        object_class=object_class.value,
        canonical_object_id=canonical_id,
        transition_type=transition_type,
        old_value=old_value,
        new_value=payload,
        claim_id=claim["claim_id"],
        chunk_id=claim["chunk_id"],
        stated_at=stated_at,
        policy_applied=policy.value,
    )

    if object_class != ObjectClass.CAUSAL_RELATIONSHIP:
        rel = REL_FOR_CLASS[object_class]
        _merge_node(
            ticker=ticker,
            label=label,
            node_id=canonical_id,
            payload=payload,
            stated_at=stated_at,
            rel=rel,
        )
    else:
        run_cypher(
            """
            MATCH (a {id: $from_id}), (b {id: $to_id})
            MERGE (a)-[r:CAUSAL {type: $rel_type}]->(b)
            SET r.stated_at = date($stated_at)
            """,
            {
                "from_id": payload.get("from_ref"),
                "to_id": payload.get("to_ref"),
                "rel_type": payload.get("relationship_type", "RELATES"),
                "stated_at": stated_at.isoformat(),
            },
        )

    update_claim_status(claim["claim_id"], "merged")
    return canonical_id


def reconcile_claims(doc_id: str) -> list[str]:
    claims = get_pending_claims_for_doc(doc_id)
    if not claims:
        return []
    return [_reconcile_claim(claim) for claim in claims]
