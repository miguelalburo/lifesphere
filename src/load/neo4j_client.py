"""Thin wrapper over the official ``neo4j`` driver: connection + batched writes.

Connection details come from ``.env`` (``NEO4J_URI`` / ``NEO4J_USER`` /
``NEO4J_PASSWORD``). The driver import is lazy so schema/validate/cypher tests
run without ``neo4j`` installed or a live database.
"""

from __future__ import annotations

import os
from typing import Iterable, Iterator

try:  # optional at import time; only needed when actually loading
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a convenience only
    pass

DEFAULT_URI = "bolt://localhost:7687"
DEFAULT_BATCH = 1000


def _chunks(rows: list[dict], size: int) -> Iterator[list[dict]]:
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


class Neo4jClient:
    """Context-managed Neo4j session with a batched-write helper."""

    def __init__(self, uri: str | None = None, user: str | None = None,
                 password: str | None = None, database: str | None = None):
        self.uri = uri or os.getenv("NEO4J_URI", DEFAULT_URI)
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "neo4j")
        self.database = database or os.getenv("NEO4J_DATABASE") or None
        self._driver = None

    def __enter__(self) -> "Neo4jClient":
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self._driver.verify_connectivity()
        return self

    def __exit__(self, *exc) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def run(self, query: str, **params) -> None:
        """Run a single statement (e.g. a constraint) in its own transaction."""
        with self._driver.session(database=self.database) as session:
            session.run(query, **params)

    def run_batches(self, query: str, rows: Iterable[dict],
                    batch_size: int = DEFAULT_BATCH) -> int:
        """Run ``query`` over ``rows`` in transactional batches. Returns row count."""
        rows = list(rows)
        with self._driver.session(database=self.database) as session:
            for chunk in _chunks(rows, batch_size):
                session.execute_write(lambda tx, c=chunk: tx.run(query, rows=c).consume())
        return len(rows)
