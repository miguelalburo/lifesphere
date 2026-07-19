"""CLI: ``python -m src.extract <project_id|--program NAME> --clinical [--out ...]``

Layer flags (at least one required):
  --clinical    fetch /cases and emit clinical TSVs (existing behaviour)
  --expression  RNA-seq STAR-Counts download + reshape
  --methylation DNA-methylation download + reshape
  --variation   somatic-variation MAF download + reshape
  --omics       shorthand for --expression --methylation --variation
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import DATA_RAW
from .run import extract, extract_program

_OMICS_LAYERS = ("expression", "methylation", "variation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.extract",
        description="Fetch GDC data and write extract TSVs.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("project_id", nargs="?", help="GDC project id (e.g. TCGA-CHOL)")
    group.add_argument(
        "--program", metavar="NAME",
        help="GDC program name (e.g. TCGA) — fetches all projects in the program",
    )

    parser.add_argument("--clinical", action="store_true", help="fetch /cases clinical layer")
    parser.add_argument("--expression", action="store_true", help="RNA-seq layer (STAR-Counts download + reshape)")
    parser.add_argument("--methylation", action="store_true", help="DNA-methylation layer (Methylation Beta Value download + reshape)")
    parser.add_argument("--variation", action="store_true", help="somatic-variation layer (Masked Somatic Mutation MAF download + reshape)")
    parser.add_argument(
        "--omics", action="store_true",
        help="all molecular layers (--expression --methylation --variation)",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="output directory (default: data/raw/<project_id or program>/)",
    )

    args = parser.parse_args(argv)

    # --omics expands to all three molecular layers
    omics_requested = [l for l in _OMICS_LAYERS if getattr(args, l) or args.omics]

    if not args.clinical and not omics_requested:
        parser.error(
            "at least one layer flag is required: --clinical, --expression, "
            "--methylation, --variation, or --omics"
        )

    selector = args.program or args.project_id
    out_dir = args.out or (DATA_RAW / selector)

    # Dispatch each requested omics layer.
    if omics_requested:
        for layer in omics_requested:
            if layer == "expression":
                from .omics.expression import extract_expression
                extract_expression(selector, out_dir)
            elif layer == "methylation":
                from .omics.methylation import extract_methylation
                extract_methylation(selector, out_dir)
            elif layer == "variation":
                from .omics.variation import extract_variation
                extract_variation(selector, out_dir)

    if args.clinical:
        if args.program:
            extract_program(args.program, out_dir)
        else:
            extract(args.project_id, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
