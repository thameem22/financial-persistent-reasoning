#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Starting Postgres + Neo4j (Docker required)"
docker compose up -d
sleep 5

echo "==> Installing package"
pip install -e . -q

echo "==> Initializing databases"
python scripts/init_db.py

echo "==> Running end-to-end pipeline (sample MSFT 10-K)"
python -m pipeline.orchestrator --ticker MSFT --mock

echo ""
echo "==> Done. Start API:"
echo "    uvicorn services.layer3_reasoning.query_api.app:app --port 8080"
echo "    curl http://127.0.0.1:8080/enterprise/MSFT/risks"
