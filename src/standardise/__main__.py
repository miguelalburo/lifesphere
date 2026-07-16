"""CLI: ``python -m src.standardise <dataset> [--profile extract]``."""

from __future__ import annotations

import argparse
import sys

from .run import format_report, report, standardise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.standardise",
        description="Standardise a raw dataset into node/edge CSVs.",
    )
    parser.add_argument("dataset", help="dataset folder name under data/raw/")
    parser.add_argument("--profile", default="extract", help="mapping profile (default: extract)")
    parser.add_argument("--quiet", action="store_true", help="suppress per-file logging")
    parser.add_argument("--report", action="store_true",
                        help="show column-binding coverage and exit (writes nothing)")
    parser.add_argument("--values", action="store_true",
                        help="include sample values for unused columns in the report (implies --report)")
    args = parser.parse_args(argv)

    if args.report or args.values:
        print(format_report(report(args.dataset, args.profile, values=args.values)))
        return 0

    summary = standardise(args.dataset, args.profile, log=not args.quiet)
    n_nodes = sum(summary["nodes"].values())
    n_edges = sum(summary["edges"].values())
    print(
        f"standardised {args.dataset}: "
        f"{len(summary['nodes'])} node types ({n_nodes} rows), "
        f"{len(summary['edges'])} edge types ({n_edges} rows), "
        f"{len(summary['skipped'])} skipped",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
