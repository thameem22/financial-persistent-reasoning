# Financial Persistent Reasoning Engine

Prototype architecture for ingesting SEC filings and maintaining an **evolving enterprise knowledge model**.

## Quick start (end-to-end)

```bash
cd financial-persistent-reasoning
cp .env.example .env

# 1. Start databases
docker compose up -d

# 2. Install + init schema
pip install -e .
python scripts/init_db.py

# 3. Run full pipeline (sample MSFT 10-K → chunks → claims → Neo4j graph)
python -m pipeline.orchestrator --ticker MSFT

# 4. Query results
uvicorn services.layer3_reasoning.query_api.app:app --port 8080
curl http://127.0.0.1:8080/enterprise/MSFT/risks
curl http://127.0.0.1:8080/enterprise/MSFT/capabilities
```

## LLM extraction

| Mode | Command | Behavior |
|------|---------|----------|
| **Auto** (default) | `python -m pipeline.orchestrator` | Uses **Anthropic** if `ANTHROPIC_API_KEY` set, else **OpenAI** if `OPENAI_API_KEY` set, else **mock** rules |
| **Force mock** | `python -m pipeline.orchestrator --mock` | No API calls |
| **Live EDGAR** | `python -m pipeline.orchestrator --edgar` | Downloads real 10-K from SEC |

Set in `.env`:

```env
LLM_PROVIDER=anthropic          # or openai
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-20250514
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

## Architecture

Three layers — see [ARCHITECTURE.md](ARCHITECTURE.md), [SERVICES.md](SERVICES.md), [docs/EDGAR.md](docs/EDGAR.md), and **[docs/DATA_FLOW.md](docs/DATA_FLOW.md)** (step-by-step visual walkthrough with sample MSFT 10-K).

![C4 container diagram](docs/ReasoningEngineC4.png)

```
EDGAR/sample HTML → parse → chunk (Postgres)
                              ↓
                         LLM extract → claims (Postgres)
                              ↓
                         reconcile → Neo4j + audit log
                              ↓
                         FastAPI queries
```

**LLM extracts; code reconciles.** The model never writes Neo4j directly.

## Repository layout

```
services/layer1_ingestion/   edgar_fetcher, document_parser, section_chunker
services/layer2_extraction/  llm_extractor (+ shared/llm_client.py)
services/layer3_reasoning/   entity_resolver, reconciliation_engine, query_api
shared/                      config, db, neo4j, repositories, schemas
pipeline/orchestrator.py     end-to-end CLI
infra/                       Postgres + Neo4j init scripts
```
