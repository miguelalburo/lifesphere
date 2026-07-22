"""CLI: ``python -m src.load <dataset> [--dry-run] [--batch-size N] [--bulk]``."""

from __future__ import annotations

import argparse
import os
import shlex
import sys

from .bulk import build_import
from .run import load


def _emit_bulk(dataset: str, database: str | None) -> int:
    """Write admin-import CSVs and print the command + follow-up constraints.

    Does not execute anything: ``neo4j-admin database import full`` needs to run
    on the DB host against a stopped DBMS / empty database, so we hand the
    reviewed command back to the operator.
    """
    database = database or os.environ.get("NEO4J_DATABASE") or "neo4j"
    plan = build_import(dataset, database=database)
    out = plan["node_files"][0].parent if plan["node_files"] else "(no files)"
    print(f"# wrote {len(plan['node_files'])} node + "
          f"{len(plan['edge_files'])} relationship files to {out}\n", file=sys.stderr)
    print("# 1) run on the DB host, DBMS stopped / database absent:")
    print(shlex.join(plan["command"]))
    print("\n# 2) start the database, then apply uniqueness constraints:")
    for stmt in plan["constraints"]:
        print(f"{stmt};")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.load",
        description="Load standardised node/edge CSVs into Neo4j.",
    )
    parser.add_argument("dataset", help="dataset folder name under data/standardised/")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--no-constraints", action="store_true",
                        help="skip creating uniqueness constraints")
    parser.add_argument("--dry-run", action="store_true",
                        help="plan the load (print queries/counts) without a database")
    parser.add_argument("--bulk", action="store_true",
                        help="emit neo4j-admin bulk-import CSVs + command (fresh DB "
                             "only); prints the command to run manually")
    parser.add_argument("--database", default=None,
                        help="target Neo4j database name (overrides NEO4J_DATABASE env var)")
    args = parser.parse_args(argv)

    if args.bulk:
        return _emit_bulk(args.dataset, args.database)

    plan = load(
        args.dataset,
        batch_size=args.batch_size,
        constraints=not args.no_constraints,
        dry_run=args.dry_run,
        database=args.database,
    )
    n_nodes = sum(plan["nodes"].values())
    n_edges = sum(plan["edges"].values())
    verb = "planned" if args.dry_run else "loaded"
    print(
        f"{verb} {args.dataset}: {len(plan['constraints'])} constraints, "
        f"{len(plan['nodes'])} node types ({n_nodes} rows), "
        f"{len(plan['edges'])} edge types ({n_edges} rows)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
