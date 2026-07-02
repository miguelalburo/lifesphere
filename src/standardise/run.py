"""Stage 1 engine — apply the mapping in ``mapping.py`` to raw per-entity TSVs.

Reads ``{in_dir}/{base}.{entity}.tsv`` (the extractor's output) and writes
graph-ready CSVs:
    {out_dir}/nodes/{Label}.csv     id + cleaned, renamed properties
    {out_dir}/edges/{LABEL}.csv     source_id, target_id

Pure-``csv`` (no pandas), matching the extractor. Grain is preserved 1:1 from the
source table, so no aggregation happens here.

    python3 -m src.standardise.run <in_dir> <base> [--out <dir>]
    python3 -m src.standardise.run data/raw/dlbc TCGA-DLBC
"""

import argparse
import csv
import sys
from pathlib import Path

from .mapping import EDGE_SPECS, NODE_SPECS, PLACEHOLDERS, EdgeSpec, NodeSpec


def _clean(value: str) -> str:
    """Scrub placeholder tokens to empty."""
    v = (value or "").strip()
    return "" if v in PLACEHOLDERS else v


def _src_path(in_dir: Path, base: str, entity: str) -> Path:
    return in_dir / f"{base}.{entity}.tsv"


def _rename(col: str, strip_prefix: str) -> str:
    if strip_prefix and col.startswith(strip_prefix):
        return col[len(strip_prefix):]
    return col


def standardise_node(spec: NodeSpec, in_dir: Path, base: str, out_dir: Path) -> int:
    src = _src_path(in_dir, base, spec.source)
    if not src.exists():
        print(f"  ! skip node {spec.label}: missing {src.name}", file=sys.stderr)
        return 0

    with open(src, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        header = reader.fieldnames or []

        if spec.keep:
            prop_cols = [c for c in spec.keep if c in header]
        else:
            prop_cols = [c for c in header if c != spec.id_col and c not in spec.drop]

        out_header = ["id"] + [_rename(c, spec.strip_prefix) for c in prop_cols]
        out_path = out_dir / "nodes" / f"{spec.label}.csv"
        seen: set = set()
        n = 0
        with open(out_path, "w", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(out_header)
            for row in reader:
                node_id = _clean(row.get(spec.id_col, ""))
                if not node_id:
                    continue
                if spec.dedup:
                    if node_id in seen:
                        continue
                    seen.add(node_id)
                writer.writerow([node_id] + [_clean(row.get(c, "")) for c in prop_cols])
                n += 1
    return n


def standardise_edge(spec: EdgeSpec, in_dir: Path, base: str, out_dir: Path) -> int:
    src = _src_path(in_dir, base, spec.source)
    if not src.exists():
        print(f"  ! skip edge {spec.label}: missing {src.name}", file=sys.stderr)
        return 0

    out_path = out_dir / "edges" / f"{spec.label}.csv"
    seen: set = set()
    n = 0
    with open(src, newline="") as f, open(out_path, "w", newline="") as out:
        reader = csv.DictReader(f, delimiter="\t")
        writer = csv.writer(out)
        writer.writerow(["source_id", "target_id"])
        for row in reader:
            s = _clean(row.get(spec.source_id, ""))
            t = _clean(row.get(spec.target_id, ""))
            if not s or not t:
                continue
            if spec.dedup:
                key = (s, t)
                if key in seen:
                    continue
                seen.add(key)
            writer.writerow([s, t])
            n += 1
    return n


def run(in_dir: Path, base: str, out_dir: Path) -> None:
    (out_dir / "nodes").mkdir(parents=True, exist_ok=True)
    (out_dir / "edges").mkdir(parents=True, exist_ok=True)

    print(f"Standardising {base} from {in_dir} -> {out_dir}")
    print("  nodes:")
    for spec in NODE_SPECS:
        n = standardise_node(spec, in_dir, base, out_dir)
        print(f"    {spec.label:<16} {n:>7} rows")
    print("  edges:")
    for spec in EDGE_SPECS:
        n = standardise_edge(spec, in_dir, base, out_dir)
        print(f"    {spec.label:<20} {n:>7} rows")
    print("Done.")


def main(argv: list[str] = None) -> int:
    p = argparse.ArgumentParser(description="Standardise raw GDC per-entity TSVs into KG node/edge CSVs.")
    p.add_argument("in_dir", type=Path, help="Directory holding {base}.{entity}.tsv files")
    p.add_argument("base", help="File base name, e.g. TCGA-DLBC or TCGA")
    p.add_argument("--out", type=Path, default=None,
                   help="Output dir (default: data/standardised/{base})")
    args = p.parse_args(argv)
    out_dir = args.out or Path("data/standardised") / args.base
    run(args.in_dir, args.base, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
