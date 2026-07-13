"""Stage 1 engine — apply JSON schemas to raw per-entity TSVs.

Discovers entity files in ``<dataset_dir>`` by naming convention
(``{base}.{entity}.tsv`` or ``.csv``), matches them against
``config/schemas/entities.json`` and ``config/schemas/edges.json``, then writes
graph-ready CSVs:

    {out_dir}/nodes/{Label}.csv     id + cleaned, renamed properties
    {out_dir}/edges/{LABEL}.csv     source_id, target_id [+ declared edge props]

Only nodes and edges whose required files and columns are present are emitted.
Placeholder scrubbing is driven by ``config/schemas/placeholders.json``.
Ontology standardisation is driven by ``config/schemas/standardisation.json`` and
offline crosswalk CSVs in ``config/crosswalks/``.
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
from . import lookup as _lookup_mod

_DEFAULT_SCHEMA_DIR = Path(__file__).parent.parent.parent / "config" / "schemas"

_SUBTYPE_COL = "_subtypeLabel"


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


def _camel(col: str) -> str:
    """snake_case -> camelCase for graph-facing property/column names.

    Applied to OUTPUT headers only (after prefix-stripping), so the graph exposes
    the camelCase convention while the config keeps referencing snake_case source
    columns. Single-token or already-camel names pass through unchanged; the
    structural columns ``id`` / ``source_id`` / ``target_id`` are added separately
    and never routed through here.
    """
    parts = [p for p in col.split("_") if p != ""]
    if not parts:
        return col
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def standardise_node(
    schema: dict,
    src: Path,
    out_dir: Path,
    clean: Callable[[str], str],
    delimiter: str = "\t",
    alias_map: dict[str, str] | None = None,
    lookup: "_lookup_mod.StandardisationLookup | None" = None,
) -> int:
    with open(src, newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        header = canonicalise(reader.fieldnames or [], alias_map) if alias_map else (reader.fieldnames or [])
        reader.fieldnames = header

        id_col = schema["id_col"]
        label = schema["label"]
        keep = schema.get("keep") or []
        drop = set(schema.get("drop") or [])
        strip_prefix = schema.get("strip_prefix", "")
        dedup = schema.get("dedup", False)
        subtype_column = schema.get("subtype_column")
        subtype_map: dict = schema.get("subtype_map") or {}

        if keep:
            prop_cols = [c for c in keep if c in header and c != id_col]
        else:
            prop_cols = [c for c in header if c != id_col and c not in drop]

        # Extra provenance columns from lookup (snake; camelCased in out_header)
        lookup_extra: list[str] = lookup.extra_columns(label) if lookup else []

        prop_out_names = [_camel(_rename(c, strip_prefix)) for c in prop_cols]
        lookup_out_names = [_camel(c) for c in lookup_extra]
        out_header = ["id"] + prop_out_names + lookup_out_names
        if subtype_column:
            out_header.append(_SUBTYPE_COL)

        out_path = out_dir / "nodes" / f"{label}.csv"
        seen: set = set()
        n = 0
        file_exists = out_path.exists() and out_path.stat().st_size > 0
        mode = "a" if file_exists else "w"
        with open(out_path, mode, newline="") as out:
            writer = csv.writer(out)
            if not file_exists:
                writer.writerow(out_header)
            for row in reader:
                node_id = clean(row.get(id_col, ""))
                if not node_id:
                    continue
                if dedup:
                    if node_id in seen:
                        continue
                    seen.add(node_id)

                base_vals = [clean(row.get(c, "")) for c in prop_cols]

                lookup_vals: list[str] = []
                if lookup:
                    lookup_vals = lookup.apply_row(label, row, clean)

                extra_vals: list[str] = []
                if subtype_column:
                    raw_sub = clean(row.get(subtype_column, ""))
                    extra_vals = [subtype_map.get(raw_sub, "")]

                writer.writerow([node_id] + base_vals + lookup_vals + extra_vals)
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
    file_exists = out_path.exists() and out_path.stat().st_size > 0
    mode = "a" if file_exists else "w"
    with open(src, newline="") as f, open(out_path, mode, newline="") as out:
        reader = csv.DictReader(f, delimiter=delimiter)
        header = reader.fieldnames or []
        if alias_map:
            header = canonicalise(header, alias_map)
            reader.fieldnames = header
        prop_cols = [c for c in (schema.get("props") or []) if c in header]
        writer = csv.writer(out)
        if not file_exists:
            writer.writerow(["source_id", "target_id", *(_camel(c) for c in prop_cols)])
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
            writer.writerow([s, t, *(clean(row.get(c, "")) for c in prop_cols)])
            n += 1
    return n


def run(in_dir: Path, out_dir: Path, schema_dir: Path = _DEFAULT_SCHEMA_DIR) -> None:
    (out_dir / "nodes").mkdir(parents=True, exist_ok=True)
    (out_dir / "edges").mkdir(parents=True, exist_ok=True)

    entity_schemas, edge_schemas = load_schemas(schema_dir)
    clean = _make_clean(load_placeholders(schema_dir))
    alias_map = load_alias_map(schema_dir)
    lookup = _lookup_mod.load(schema_dir)
    found = scan_files(in_dir)

    node_plans = match_node_plans(found, entity_schemas, alias_map)
    edge_plans = match_edge_plans(found, edge_schemas, alias_map)

    print(f"Standardising {in_dir} -> {out_dir}")
    print("  nodes:")
    for plan in node_plans:
        n = standardise_node(
            plan["schema"], plan["path"], out_dir, clean, plan["delimiter"], alias_map, lookup
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
