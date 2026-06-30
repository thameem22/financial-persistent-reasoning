"""Initialize Postgres schema and Neo4j constraints."""

from __future__ import annotations

from pathlib import Path

from shared.config import get_settings
from shared.db import get_connection
from shared.neo4j_client import run_cypher


def init_postgres() -> None:
    sql_path = Path(__file__).resolve().parent.parent / "infra" / "postgres" / "001_init.sql"
    sql = sql_path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with get_connection() as conn:
        for statement in statements:
            conn.execute(statement)


def init_neo4j() -> None:
    cypher_path = Path(__file__).resolve().parent.parent / "infra" / "neo4j" / "constraints.cypher"
    for line in cypher_path.read_text(encoding="utf-8").splitlines():
        statement = line.strip()
        if statement and not statement.startswith("//"):
            run_cypher(statement)


def init_all() -> None:
    init_postgres()
    init_neo4j()
    print("Database init complete.")
    print(f"  Postgres: {get_settings().database_url}")
    print(f"  Neo4j:    {get_settings().neo4j_uri}")


if __name__ == "__main__":
    init_all()
