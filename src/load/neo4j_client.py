"""Thin wrapper over the official ``neo4j`` driver: connection + batched writes.

Connection details come from ``.env`` (``NEO4J_URI`` / ``NEO4J_USER`` /
``NEO4J_PASSWORD``). The driver import is lazy so schema/validate/cypher tests
run without ``neo4j`` installed or a live database.

Enterprise extras (``verify_create_database_privilege``, ``provision_database``)
raise ``RuntimeError`` when the connected instance is not Neo4j Enterprise.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Iterator

try:  # optional at import time; only needed when actually loading
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a convenience only
    pass

DEFAULT_URI = "bolt://localhost:7687"
DEFAULT_BATCH = 1000

# Safe database name: letters, digits, hyphens, underscores only.
_SAFE_DB_NAME = re.compile(r"^[A-Za-z0-9_\-]+$")


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

    # ── Enterprise database management ────────────────────────────────────────

    def verify_create_database_privilege(self) -> bool:
        """Return True if the connected user has the CREATE DATABASE privilege.

        Requires an active driver (call inside ``with Neo4jClient() as c:``).
        Runs ``SHOW USER PRIVILEGES`` (the current user's privileges) against the
        ``system`` database.

        Raises ``RuntimeError`` if the instance is not Neo4j Enterprise (Community
        edition does not expose a ``system`` database or multi-database commands).
        """
        try:
            with self._driver.session(database="system") as session:
                result = session.run("SHOW USER PRIVILEGES")
                rows = [r.data() for r in result]
        except Exception as exc:
            raise RuntimeError(
                "Cannot query Neo4j system database — this instance may be "
                "Community Edition (no multi-database support). "
                f"Original error: {exc}"
            ) from exc

        # Any of these GRANTED DBMS actions imply CREATE DATABASE:
        #   create_database      — the specific privilege
        #   database_management  — ALL DATABASE MANAGEMENT
        #   dbms_actions         — ALL DBMS PRIVILEGES (held by the admin role)
        granting = {"create_database", "database_management", "dbms_actions"}
        for row in rows:
            # Scope to the connected user when the query returns a user column.
            row_user = row.get("user")
            if self.user and row_user and row_user != self.user:
                continue
            if str(row.get("access") or "").upper() == "DENIED":
                continue
            if str(row.get("action") or "").lower() in granting:
                return True
        return False

    def provision_database(self, name: str) -> None:
        """Drop (if it exists) and create a fresh Enterprise database named ``name``.

        Raises ``ValueError`` for unsafe database names.
        Raises ``RuntimeError`` if the instance is not Enterprise or if the
        current user lacks CREATE DATABASE privilege.
        """
        if not _SAFE_DB_NAME.match(name):
            raise ValueError(
                f"Unsafe database name {name!r}. "
                "Use letters, digits, hyphens, and underscores only."
            )

        has_priv = self.verify_create_database_privilege()
        if not has_priv:
            raise RuntimeError(
                f"The current Neo4j user does not have CREATE DATABASE privilege. "
                f"Cannot provision database {name!r}. "
                "Grant the privilege with: "
                f"GRANT CREATE DATABASE ON DBMS TO <role>;"
            )

        with self._driver.session(database="system") as session:
            session.run(f"DROP DATABASE `{name}` IF EXISTS")
            session.run(f"CREATE DATABASE `{name}`")

    def query(self, cypher: str, database: str | None = None, **params) -> list[dict]:
        """Run a read query and return all rows as dicts."""
        db = database or self.database
        with self._driver.session(database=db) as session:
            result = session.run(cypher, **params)
            return [r.data() for r in result]
