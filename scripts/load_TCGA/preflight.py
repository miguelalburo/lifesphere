"""Pre-load checks for the driver-based load (scripts/load_TCGA/load_TCGA.sh).

The load path is `MERGE`-based and never fails hard: edge queries MATCH both
endpoints, so an edge whose endpoint node is missing creates nothing and logs
nothing. That makes two failure modes silent, and both are cheap to catch first:

  1. the target database does not exist (the driver would connect to the DBMS
     fine and then fail per-session, or worse, write into the default db);
  2. an endpoint label the dataset does not emit is empty — e.g. the omics
     profile does not emit Sample nodes ("expected from the clinical pass"), so
     loading TCGA_EXPRESSION into a database with no Samples yields the
     observation and Gene nodes but ZERO HAS_EXPRESSION_OBSERVATION edges.

(2) is a warning, not an error: it is legitimate to load omics before clinical
and let the edges land on a later re-run (MERGE makes that safe).

Usage:
    python scripts/load_TCGA/preflight.py --database NAME
        [--create] [--expect-label LABEL ...] [--strict]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.load.neo4j_client import Neo4jClient  # noqa: E402


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _database_status(client: Neo4jClient, name: str) -> str | None:
    """Current status of `name` per SHOW DATABASES, or None if it doesn't exist."""
    try:
        rows = client.query("SHOW DATABASES YIELD name, currentStatus "
                            "WHERE name = $name RETURN name, currentStatus",
                            database="system", name=name)
    except Exception as exc:
        raise RuntimeError(f"cannot run SHOW DATABASES on {client.uri}: {exc}") from exc
    return rows[0]["currentStatus"] if rows else None


def _wait_online(client: Neo4jClient, name: str, timeout: int = 120) -> str | None:
    """Poll until the database reports `online` (creation is asynchronous)."""
    deadline = time.monotonic() + timeout
    status = _database_status(client, name)
    while status is not None and status != "online" and time.monotonic() < deadline:
        time.sleep(2)
        status = _database_status(client, name)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="preflight.py",
                                     description="Verify the load target before running src.load.")
    parser.add_argument("--database", required=True, help="target Neo4j database name")
    parser.add_argument("--create", action="store_true",
                        help="CREATE DATABASE IF NOT EXISTS when absent (Enterprise; "
                             "non-destructive — never drops an existing database)")
    parser.add_argument("--expect-label", action="append", default=[], metavar="LABEL",
                        help="warn if this label has no nodes in the target database "
                             "(repeatable); these are endpoints the dataset does not emit")
    parser.add_argument("--strict", action="store_true",
                        help="treat an empty --expect-label as an error, not a warning")
    args = parser.parse_args(argv)

    with Neo4jClient(database=args.database) as client:
        _log(f"  connected: {client.uri} as {client.user}")

        status = _database_status(client, args.database)
        if status is None:
            if not args.create:
                _log(f"! database '{args.database}' does not exist on {client.uri}. "
                     f"Create it (CREATE DATABASE `{args.database}`) or re-run with --create.")
                return 1
            _log(f"  creating database '{args.database}'")
            client.query(f"CREATE DATABASE `{args.database}` IF NOT EXISTS",
                         database="system")
            status = _wait_online(client, args.database)
        if status != "online":
            _log(f"! database '{args.database}' is '{status}', not online — "
                 "start it before loading")
            return 1
        _log(f"  database '{args.database}': online")

        failed = False
        for label in args.expect_label:
            rows = client.query(f"MATCH (n:`{label}`) RETURN count(n) AS n")
            count = rows[0]["n"] if rows else 0
            if count:
                _log(f"  endpoint {label}: {count} nodes present")
                continue
            failed = failed or args.strict
            _log(f"{'!' if args.strict else '~'} endpoint {label}: 0 nodes in "
                 f"'{args.database}' — edges into {label} will match nothing and be "
                 "silently dropped. Load the clinical dataset first, then re-run this "
                 "load (MERGE makes the re-run safe).")
        if failed:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
