# Service reference — DB reads/writes per component

## Layer 1 — Ingestion

### edgar_fetcher
- **Reads:** SEC `data.sec.gov/submissions`, `sec.gov/Archives/...`
- **Writes:** `staging.documents`, `data/raw/{ticker}/*.html`
- **Code:** `services/layer1_ingestion/edgar_fetcher/service.py`
- **Docs:** [docs/EDGAR.md](docs/EDGAR.md)

### document_parser
- **Reads:** raw file path from `staging.documents`
- **Writes:** nothing persisted (returns cleaned text to chunker)
- **Code:** `services/layer1_ingestion/document_parser/service.py`

### section_chunker
- **Reads:** cleaned text, `staging.documents` metadata
- **Writes:** `staging.chunks`
- **Code:** `services/layer1_ingestion/section_chunker/service.py`

## Layer 2 — Extraction

### llm_extractor
- **Reads:** `staging.chunks` via SQL (`get_chunks_for_doc`)
- **Writes:** `extraction.claims` with `reconciliation_status=pending`
- **External:** Anthropic/OpenAI when API keys set; mock rules otherwise
- **Code:** `services/layer2_extraction/llm_extractor/service.py`

## Layer 3 — Reasoning

### entity_resolver
- **Reads:** claim payload strings
- **Writes:** `reasoning.entity_aliases`
- **Code:** `services/layer3_reasoning/entity_resolver/service.py`

### reconciliation_engine
- **Reads:** `extraction.claims` (pending), existing Neo4j nodes
- **Writes:** Neo4j nodes/edges, `reasoning.state_transitions`, updates claim status
- **Code:** `services/layer3_reasoning/reconciliation_engine/service.py`

### query_api
- **Reads:** Neo4j (Cypher), Postgres (`state_transitions`, `chunks`)
- **Writes:** HTTP JSON only
- **Code:** `services/layer3_reasoning/query_api/app.py`

## Pipeline

- **Code:** `pipeline/orchestrator.py`
- **CLI:** `python -m pipeline.orchestrator --ticker MSFT --dry-run`
