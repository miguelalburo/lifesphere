"""CLI: ``python -m src.extract <project_id> [--out data/raw/<dataset>]``."""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import DATA_RAW
from .run import extract


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.extract",
        description="Fetch GDC cases and write extract TSVs.",
    )
    parser.add_argument("project_id", help="GDC project id (e.g. TCGA-CHOL)")
    parser.add_argument(
        "--out", type=Path, default=None,
        help="output directory (default: data/raw/<project_id>/)",
    )
    args = parser.parse_args(argv)

    out_dir = args.out or (DATA_RAW / args.project_id)
    extract(args.project_id, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
