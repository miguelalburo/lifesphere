"""CLI: ``python -m src.extract <project_id> [--out ...]`` or ``--program <name>``."""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import DATA_RAW
from .run import extract, extract_program


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.extract",
        description="Fetch GDC cases and write extract TSVs.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("project_id", nargs="?", help="GDC project id (e.g. TCGA-CHOL)")
    group.add_argument("--program", metavar="NAME", help="GDC program name (e.g. TCGA) — fetches all projects in the program")
    parser.add_argument(
        "--out", type=Path, default=None,
        help="output directory (default: data/raw/<project_id or program>/)",
    )
    args = parser.parse_args(argv)

    if args.program:
        out_dir = args.out or (DATA_RAW / args.program)
        extract_program(args.program, out_dir)
    else:
        out_dir = args.out or (DATA_RAW / args.project_id)
        extract(args.project_id, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
