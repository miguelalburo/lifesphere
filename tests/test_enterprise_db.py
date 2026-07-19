"""Unit tests for Neo4jClient Enterprise database management.

All tests mock the neo4j driver so no live database is needed.

Covers:
  - verify_create_database_privilege: True/False on matching/missing privileges
  - verify_create_database_privilege: RuntimeError when system DB unavailable
  - provision_database: calls DROP + CREATE against system DB
  - provision_database: raises RuntimeError when privilege missing
  - provision_database: raises ValueError for unsafe database names
  - load() database parameter is forwarded to Neo4jClient
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from src.load.neo4j_client import Neo4jClient


# ──────────────────────────────── Helpers ────────────────────────────────────


def _client(database: str | None = None) -> Neo4jClient:
    """Return a Neo4jClient with env-default credentials."""
    c = Neo4jClient(uri="bolt://test:7687", user="neo4j",
                    password="pass", database=database)
    return c


def _mock_driver(privilege_rows: list[dict] | None = None,
                 raise_on_system: Exception | None = None) -> MagicMock:
    """Build a mock neo4j GraphDatabase.driver instance."""
    driver = MagicMock()
    session_ctx = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session_ctx)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    if raise_on_system is not None:
        driver.session.side_effect = raise_on_system
    else:
        result_mock = MagicMock()
        result_mock.__iter__ = MagicMock(return_value=iter(
            [MagicMock(data=lambda r=r: r) for r in (privilege_rows or [])]
        ))
        session_ctx.run.return_value = result_mock
    return driver


# ───────────────────── verify_create_database_privilege ──────────────────────


class TestVerifyCreateDatabasePrivilege:
    def _run(self, privilege_rows: list[dict]) -> bool:
        c = _client()
        c._driver = _mock_driver(privilege_rows)
        return c.verify_create_database_privilege()

    def test_create_database_action_grants_privilege(self):
        rows = [{"action": "create_database", "segment": "*"}]
        assert self._run(rows) is True

    def test_database_management_action_grants_privilege(self):
        rows = [{"action": "database_management", "segment": "*"}]
        assert self._run(rows) is True

    def test_unrelated_action_returns_false(self):
        rows = [{"action": "read", "segment": "Node"}]
        assert self._run(rows) is False

    def test_empty_privileges_returns_false(self):
        assert self._run([]) is False

    def test_raises_when_system_db_unavailable(self):
        c = _client()
        # Simulate Community Edition: session() raises
        c._driver = MagicMock()
        c._driver.session.side_effect = Exception("not supported on Community")
        with pytest.raises(RuntimeError, match="Community Edition"):
            c.verify_create_database_privilege()


# ──────────────────────────── provision_database ─────────────────────────────


class TestProvisionDatabase:
    def _make_client_with_privilege(self, has_priv: bool) -> Neo4jClient:
        c = _client()
        if has_priv:
            priv_rows = [{"action": "create_database", "segment": "*"}]
        else:
            priv_rows = []
        c._driver = _mock_driver(priv_rows)
        return c

    def test_issues_drop_and_create(self):
        c = self._make_client_with_privilege(True)
        session_ctx = c._driver.session.return_value.__enter__.return_value
        c.provision_database("cholomics")
        calls = session_ctx.run.call_args_list
        issued = [str(ca[0][0]) for ca in calls]
        assert any("DROP DATABASE" in s for s in issued)
        assert any("CREATE DATABASE" in s for s in issued)
        assert any("cholomics" in s for s in issued)

    def test_raises_when_no_privilege(self):
        c = self._make_client_with_privilege(False)
        with pytest.raises(RuntimeError, match="CREATE DATABASE privilege"):
            c.provision_database("cholomics")

    def test_raises_on_unsafe_name(self):
        c = _client()
        c._driver = _mock_driver([])
        with pytest.raises(ValueError, match="Unsafe database name"):
            c.provision_database("bad name; DROP")

    def test_raises_on_name_with_semicolon(self):
        c = _client()
        c._driver = _mock_driver([])
        with pytest.raises(ValueError, match="Unsafe database name"):
            c.provision_database("db;DROP TABLE")

    def test_accepts_hyphenated_name(self):
        c = self._make_client_with_privilege(True)
        # Should not raise ValueError
        session_ctx = c._driver.session.return_value.__enter__.return_value
        c.provision_database("chol-omics_2")
        issued = [str(ca[0][0]) for ca in session_ctx.run.call_args_list]
        assert any("chol-omics_2" in s for s in issued)


# ───────────────────────── load() database parameter ─────────────────────────


class TestLoadDatabaseParameter:
    """Confirm that load(database=...) forwards the name to Neo4jClient."""

    def test_database_passed_to_client(self, tmp_path: Path):
        # Build a minimal standardised dataset
        std = tmp_path / "std" / "DS" / "nodes"
        std.mkdir(parents=True)
        (std / "Subject.csv").write_text("subjectId\nS1\n")

        from src.load.run import load

        captured: list[str | None] = []

        original_init = Neo4jClient.__init__

        def patched_init(self, *a, database=None, **kw):
            captured.append(database)
            original_init(self, *a, database=database, **kw)

        mock_client = MagicMock()
        with patch.object(Neo4jClient, "__init__", patched_init), \
             patch.object(Neo4jClient, "__enter__", return_value=mock_client), \
             patch.object(Neo4jClient, "__exit__", return_value=False):
            load("DS", standardised_root=tmp_path / "std", dry_run=False, database="cholomics")

        assert captured == ["cholomics"]

    def test_dry_run_accepts_database_kwarg(self, tmp_path: Path):
        std = tmp_path / "std" / "DS" / "nodes"
        std.mkdir(parents=True)
        (std / "Subject.csv").write_text("subjectId\nS1\n")

        from src.load.run import load

        # Should not raise
        plan = load("DS", standardised_root=tmp_path / "std", dry_run=True, database="cholomics")
        assert isinstance(plan, dict)
