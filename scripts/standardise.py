#!/usr/bin/env python3
"""Standardise raw per-entity TSVs into graph-ready node/edge CSVs (Stage 1).

Usage:
  python scripts/standardise.py <input_dir> <output_dir>
  python scripts/standardise.py data/raw/TCGA_COMBINED data/standardised/TCGA_COMBINED

  --schemas   Path to schema directory (default: config/schemas)
"""

import argparse
import sys
from pathlib import Path

# Allow running from the project root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.standardise.run import run, _DEFAULT_SCHEMA_DIR


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input_dir", type=Path, help="Directory holding {base}.{entity}.tsv/.csv files")
    p.add_argument("output_dir", type=Path, help="Destination for nodes/ and edges/ CSVs")
    p.add_argument("--schemas", type=Path, default=_DEFAULT_SCHEMA_DIR,
                   help="Schema directory containing entities.json, edges.json, placeholders.json")
    args = p.parse_args()
    run(args.input_dir, args.output_dir, args.schemas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
