"""Neo4j driver for knowledge graph reads and writes."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from neo4j import GraphDatabase, Driver

from shared.config import get_settings

_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        settings = get_settings()
        _driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


@contextmanager
def neo4j_session() -> Iterator[Any]:
    driver = get_driver()
    session = driver.session()
    try:
        yield session
    finally:
        session.close()


def run_cypher(query: str, parameters: dict | None = None) -> list[dict[str, Any]]:
    with neo4j_session() as session:
        result = session.run(query, parameters or {})
        return [record.data() for record in result]


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
