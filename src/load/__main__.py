"""CLI: ``python -m src.load <dataset> [--dry-run] [--batch-size N]``."""

from __future__ import annotations

import argparse
import sys

from .run import load


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
    parser.add_argument("--database", default=None,
                        help="target Neo4j database name (overrides NEO4J_DATABASE env var)")
    args = parser.parse_args(argv)

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
