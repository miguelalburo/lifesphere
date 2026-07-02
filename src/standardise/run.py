"""Stage 1 engine — apply JSON schemas to raw per-entity TSVs.

Discovers entity files in ``<dataset_dir>`` by naming convention
(``{base}.{entity}.tsv`` or ``.csv``), matches them against
``config/schemas/entities.json`` and ``config/schemas/edges.json``, then writes
graph-ready CSVs:

    {out_dir}/nodes/{Label}.csv     id + cleaned, renamed properties
    {out_dir}/edges/{LABEL}.csv     source_id, target_id

Only nodes and edges whose required files and columns are present are emitted.
Placeholder scrubbing is driven by ``config/schemas/placeholders.json``.
Pure-``csv`` (no pandas). Grain is preserved 1:1 from the source table.

    python3 -m src.standardise.run <dataset_dir> [--out <dir>] [--schemas <dir>]
    python3 -m src.standardise.run data/raw/TCGA_COMBINED
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Callable

from .aliases import canonicalise, load_alias_map
from .detect import match_edge_plans, match_node_plans, scan_files

_DEFAULT_SCHEMA_DIR = Path(__file__).parent.parent.parent / "config" / "schemas"


def load_schemas(schema_dir: Path) -> tuple[list[dict], list[dict]]:
    with open(schema_dir / "entities.json") as f:
        entity_schemas = json.load(f)
    with open(schema_dir / "edges.json") as f:
        edge_schemas = json.load(f)
    return entity_schemas, edge_schemas


def load_placeholders(schema_dir: Path) -> frozenset[str]:
    """Load placeholder tokens from placeholders.json; falls back to empty set."""
    p = schema_dir / "placeholders.json"
    if not p.exists():
        print(f"  ! {p} not found — no placeholder scrubbing applied", file=sys.stderr)
        return frozenset()
    with open(p) as f:
        return frozenset(json.load(f))


def _make_clean(placeholders: frozenset[str]) -> Callable[[str], str]:
    def clean(value: str) -> str:
        v = (value or "").strip()
        return "" if v in placeholders else v
    return clean


def _rename(col: str, strip_prefix: str) -> str:
    if strip_prefix and col.startswith(strip_prefix):
        return col[len(strip_prefix):]
    return col


def standardise_node(
    schema: dict,
    src: Path,
    out_dir: Path,
    clean: Callable[[str], str],
    delimiter: str = "\t",
    alias_map: dict[str, str] | None = None,
) -> int:
    with open(src, newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        header = canonicalise(reader.fieldnames or [], alias_map) if alias_map else (reader.fieldnames or [])
        reader.fieldnames = header

        id_col = schema["id_col"]
        keep = schema.get("keep") or []
        drop = set(schema.get("drop") or [])
        strip_prefix = schema.get("strip_prefix", "")
        dedup = schema.get("dedup", False)

        if keep:
            prop_cols = [c for c in keep if c in header and c != id_col]
        else:
            prop_cols = [c for c in header if c != id_col and c not in drop]

        out_header = ["id"] + [_rename(c, strip_prefix) for c in prop_cols]
        out_path = out_dir / "nodes" / f"{schema['label']}.csv"
        seen: set = set()
        n = 0
        with open(out_path, "w", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(out_header)
            for row in reader:
                node_id = clean(row.get(id_col, ""))
                if not node_id:
                    continue
                if dedup:
                    if node_id in seen:
                        continue
                    seen.add(node_id)
                writer.writerow([node_id] + [clean(row.get(c, "")) for c in prop_cols])
                n += 1
    return n


def standardise_edge(
    schema: dict,
    src: Path,
    out_dir: Path,
    clean: Callable[[str], str],
    delimiter: str = "\t",
    alias_map: dict[str, str] | None = None,
) -> int:
    out_path = out_dir / "edges" / f"{schema['label']}.csv"
    source_id = schema["source_id"]
    target_id = schema["target_id"]
    dedup = schema.get("dedup", False)
    seen: set = set()
    n = 0
    with open(src, newline="") as f, open(out_path, "w", newline="") as out:
        reader = csv.DictReader(f, delimiter=delimiter)
        if alias_map:
            reader.fieldnames = canonicalise(reader.fieldnames or [], alias_map)
        writer = csv.writer(out)
        writer.writerow(["source_id", "target_id"])
        for row in reader:
            s = clean(row.get(source_id, ""))
            t = clean(row.get(target_id, ""))
            if not s or not t:
                continue
            if dedup:
                key = (s, t)
                if key in seen:
                    continue
                seen.add(key)
            writer.writerow([s, t])
            n += 1
    return n


def run(in_dir: Path, out_dir: Path, schema_dir: Path = _DEFAULT_SCHEMA_DIR) -> None:
    (out_dir / "nodes").mkdir(parents=True, exist_ok=True)
    (out_dir / "edges").mkdir(parents=True, exist_ok=True)

    entity_schemas, edge_schemas = load_schemas(schema_dir)
    clean = _make_clean(load_placeholders(schema_dir))
    alias_map = load_alias_map(schema_dir)
    found = scan_files(in_dir)

    node_plans = match_node_plans(found, entity_schemas, alias_map)
    edge_plans = match_edge_plans(found, edge_schemas, alias_map)

    print(f"Standardising {in_dir} -> {out_dir}")
    print("  nodes:")
    for plan in node_plans:
        n = standardise_node(
            plan["schema"], plan["path"], out_dir, clean, plan["delimiter"], alias_map
        )
        print(f"    {plan['schema']['label']:<16} {n:>7} rows")
    print("  edges:")
    for plan in edge_plans:
        n = standardise_edge(
            plan["schema"], plan["path"], out_dir, clean, plan["delimiter"], alias_map
        )
        print(f"    {plan['schema']['label']:<20} {n:>7} rows")
    print("Done.")


def main(argv: list[str] = None) -> int:
    p = argparse.ArgumentParser(description="Standardise raw per-entity TSVs into KG node/edge CSVs.")
    p.add_argument("in_dir", type=Path, help="Directory holding {base}.{entity}.tsv/.csv files")
    p.add_argument("--out", type=Path, default=None,
                   help="Output dir (default: data/standardised/<in_dir_name>)")
    p.add_argument("--schemas", type=Path, default=_DEFAULT_SCHEMA_DIR,
                   help="Directory containing entities.json, edges.json, placeholders.json")
    args = p.parse_args(argv)
    out_dir = args.out or Path("data/standardised") / args.in_dir.name
    run(args.in_dir, out_dir, args.schemas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
