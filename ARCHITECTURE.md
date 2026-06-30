# Architecture

End-to-end data flow for the Financial Persistent Reasoning Engine.

![C4 container diagram](docs/ReasoningEngineC4.png)

See also:
- [docs/DATA_FLOW.md](docs/DATA_FLOW.md) — visual step-by-step data walkthrough (sample MSFT 10-K)
- [docs/EDGAR.md](docs/EDGAR.md) — SEC endpoints, inputs/outputs, and how fetcher output feeds the pipeline.

```
SEC EDGAR (metadata + raw HTML/PDF)
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│ LAYER 1 — INGESTION                                       │
│                                                           │
│  edgar_fetcher      → staging.documents + raw file        │
│  document_parser    → cleaned text                        │
│  section_chunker    → staging.chunks (Item 1, 1A, 7, 8…)  │
└─────────────────────────────┬─────────────────────────────┘
                              │ SQL: SELECT chunks
                              ▼
┌───────────────────────────────────────────────────────────┐
│ LAYER 2 — EXTRACTION                                      │
│                                                           │
│  llm_extractor      → reads chunk text                    │
│                     → Anthropic/OpenAI structured JSON    │
│                     → extraction.claims (pending)         │
└─────────────────────────────┬─────────────────────────────┘
                              │ SQL: SELECT pending claims
                              ▼
┌───────────────────────────────────────────────────────────┐
│ LAYER 3 — REASONING                                       │
│                                                           │
│  entity_resolver    → reasoning.entity_aliases            │
│  reconciliation_engine                                    │
│       → MERGE Neo4j nodes/edges (current model)           │
│       → INSERT reasoning.state_transitions (audit)        │
│  query_api          → Cypher + SQL → HTTP JSON            │
└───────────────────────────────────────────────────────────┘
```

## What EDGAR does vs our code

| Step | Owner | Input | Output |
|------|-------|-------|--------|
| List/download filings | **edgar_fetcher** + SEC API | ticker, form type | Raw `.htm` + `staging.documents` row |
| HTML → text | **document_parser** | raw file | cleaned string |
| Text → sections | **section_chunker** | cleaned text | `staging.chunks` rows |
| Text → typed facts | **llm_extractor** | chunk rows | `extraction.claims` rows |
| Facts → enterprise model | **reconciliation_engine** | claims | Neo4j + `state_transitions` |

EDGAR never chunks, never extracts doctrine/risks, never touches Neo4j.

## Postgres schemas

| Schema | Tables | Written by | Read by |
|--------|--------|------------|---------|
| `staging` | `documents`, `chunks` | Layer 1 | Layer 2, query API (provenance) |
| `extraction` | `claims` | Layer 2 | Layer 3 |
| `reasoning` | `entity_aliases`, `state_transitions` | Layer 3 | query API |

## Neo4j graph

| Node labels | Edge types | Written by | Read by |
|-------------|------------|------------|---------|
| Company, Doctrine, Capability, ActiveState, Obligation, Risk, Decision | IMPLEMENTS, HAS_RISK, OFFERS, EXPOSes, … | reconciliation_engine | query_api |

Trajectory (Enterprise Trajectory) is **derived** from `reasoning.state_transitions` in Postgres, not stored as LLM-extracted nodes.

## Enterprise object classes

| Class | Reconciliation policy |
|-------|----------------------|
| Doctrine | newer-wins |
| Capability | newer-wins + history |
| ActiveState | newer-wins |
| ActiveObligation | append-only; mark fulfilled |
| Risk | append-only; retire when dropped |
| ManagementDecision | append-only; manual review on conflict |
| CausalRelationship | append-only (graph edge) |
| EnterpriseTrajectory | computed from audit log |

## Bitemporal columns on claims

- **effective_from / effective_to** — when fact was true in the world (e.g. FY2024)
- **stated_from / stated_to** — when company asserted it (filing date)

Enables **current state**, **as-of**, and **trajectory** queries.

## Job chain (pipeline)

1. `fetch_filings(ticker, form)` → doc_ids
2. `parse_document(doc_id)`
3. `chunk_document(doc_id)` → chunk_ids
4. `extract_claims(doc_id)` → claim_ids
5. `reconcile_claims(doc_id)`

Each service exposes a `run(...)` function; `pipeline/orchestrator.py` chains them.

## Query patterns

| Question | Primary store |
|----------|---------------|
| Show source paragraph | Postgres `staging.chunks` |
| Current risks / capabilities | Neo4j Cypher |
| How did risk X evolve? | Postgres `state_transitions` |
| Why do we believe X? | Join transition → claim → chunk → document URL |
