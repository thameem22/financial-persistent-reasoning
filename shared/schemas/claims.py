"""Layer 2 claim schemas and Layer 3 reconciliation policies."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ObjectClass(str, Enum):
    DOCTRINE = "Doctrine"
    CAPABILITY = "Capability"
    ACTIVE_STATE = "ActiveState"
    ACTIVE_OBLIGATION = "ActiveObligation"
    RISK = "Risk"
    MANAGEMENT_DECISION = "ManagementDecision"
    CAUSAL_RELATIONSHIP = "CausalRelationship"


OBJECT_CLASSES = list(ObjectClass)


class ReconciliationPolicy(str, Enum):
    NEWER_WINS = "newer_wins"
    APPEND_ONLY = "append_only"
    MANUAL_REVIEW = "manual_review"


def policy_for(object_class: ObjectClass) -> ReconciliationPolicy:
    return {
        ObjectClass.DOCTRINE: ReconciliationPolicy.NEWER_WINS,
        ObjectClass.CAPABILITY: ReconciliationPolicy.NEWER_WINS,
        ObjectClass.ACTIVE_STATE: ReconciliationPolicy.NEWER_WINS,
        ObjectClass.ACTIVE_OBLIGATION: ReconciliationPolicy.APPEND_ONLY,
        ObjectClass.RISK: ReconciliationPolicy.APPEND_ONLY,
        ObjectClass.MANAGEMENT_DECISION: ReconciliationPolicy.MANUAL_REVIEW,
        ObjectClass.CAUSAL_RELATIONSHIP: ReconciliationPolicy.APPEND_ONLY,
    }[object_class]


class DoctrinePayload(BaseModel):
    statement: str
    topic: str
    scope: str = "company-wide"


class CapabilityPayload(BaseModel):
    name: str
    category: str
    description: str = ""


class ActiveStatePayload(BaseModel):
    metric: str
    value: float | int | str
    unit: str = ""
    change_pct: float | None = None
    as_of_period: str


class ActiveObligationPayload(BaseModel):
    obligation_type: str
    description: str
    status: Literal["active", "fulfilled", "expired"] = "active"
    due_by: str | None = None


class RiskPayload(BaseModel):
    risk_category: str
    description: str
    severity: Literal["low", "medium", "high"] = "medium"


class ManagementDecisionPayload(BaseModel):
    decision_type: str
    description: str
    decision_date: str | None = None
    materiality: Literal["low", "medium", "high"] = "medium"


class CausalRelationshipPayload(BaseModel):
    from_ref: str
    to_ref: str
    relationship_type: str
    evidence_quote: str = ""


class ClaimRecord(BaseModel):
    claim_id: str
    chunk_id: str
    company_ticker: str
    object_class: ObjectClass
    payload: dict[str, Any]
    confidence: float = 1.0
    effective_from: date | None = None
    effective_to: date | None = None
    stated_from: date
    stated_to: date | None = None
    extraction_run_id: str
    reconciliation_status: str = "pending"
