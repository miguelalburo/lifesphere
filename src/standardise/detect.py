"""File discovery and schema matching for the standardisation pipeline.

Given a dataset directory containing ``{base}.{entity}.tsv`` (or ``.csv``) files,
identifies which node and edge schemas from the JSON config can be satisfied by the
available data, verifying both file presence and required column existence.

Detection order:
  1. By name — entity name parsed from filename matched against schema ``name``
  2. By content — id/FK columns verified to be present in the file header
"""

import csv
import sys
from pathlib import Path

from .aliases import canonicalise


def _delimiter(filepath: Path) -> str:
    return "," if filepath.suffix.lower() == ".csv" else "\t"


def _read_header(filepath: Path, alias_map: dict[str, str] | None = None) -> list[str]:
    with open(filepath, newline="") as f:
        header = next(csv.reader(f, delimiter=_delimiter(filepath)), [])
    return canonicalise(header, alias_map) if alias_map else header


def scan_files(dataset_dir: Path) -> dict[str, Path]:
    """Scan for *.tsv and *.csv files; parse entity name from {base}.{entity}.ext.

    Returns a dict mapping entity_name -> filepath.  Files without a dotted base
    prefix (e.g. ``subject.tsv``) are accepted using the stem directly.  When both
    a .tsv and a .csv exist for the same entity, .tsv wins (processed first).
    Duplicate entity names beyond that keep the first file found.
    """
    found: dict[str, Path] = {}
    candidates: list[Path] = sorted(dataset_dir.glob("*.tsv")) + sorted(dataset_dir.glob("*.csv"))
    for p in candidates:
        stem = p.stem  # e.g. "TCGA.subject" or "subject"
        entity = stem.split(".", 1)[1] if "." in stem else stem
        if entity in found:
            print(
                f"  ! detect: duplicate entity '{entity}' — keeping {found[entity].name},"
                f" ignoring {p.name}",
                file=sys.stderr,
            )
        else:
            found[entity] = p
    return found


def match_node_plans(
    found: dict[str, Path], schemas: list[dict], alias_map: dict[str, str] | None = None
) -> list[dict]:
    """Return one plan per schema where the entity file exists and id_col is present.

    A single file can satisfy multiple schemas (e.g. subject.tsv feeds Program,
    Project, and Subject nodes).  Headers are canonicalised via ``alias_map`` before
    the id_col presence check, so aliased columns still match.

    Each plan: ``{"schema": dict, "path": Path, "delimiter": str}``
    """
    plans: list[dict] = []
    for schema in schemas:
        entity_name = schema["name"]
        if entity_name not in found:
            print(
                f"  ! skip node {schema['label']}: no '{entity_name}.*' file in dataset",
                file=sys.stderr,
            )
            continue
        filepath = found[entity_name]
        header = _read_header(filepath, alias_map)
        id_col = schema["id_col"]
        if id_col not in header:
            print(
                f"  ! skip node {schema['label']}: id_col '{id_col}' absent in {filepath.name}",
                file=sys.stderr,
            )
            continue
        plans.append({"schema": schema, "path": filepath, "delimiter": _delimiter(filepath)})
    return plans


def match_edge_plans(
    found: dict[str, Path], schemas: list[dict], alias_map: dict[str, str] | None = None
) -> list[dict]:
    """Return one plan per edge schema where the source file exists with both FK columns.

    Headers are canonicalised via ``alias_map`` before the FK presence check.

    Each plan: ``{"schema": dict, "path": Path, "delimiter": str}``
    """
    plans: list[dict] = []
    for schema in schemas:
        entity_name = schema["source_entity"]
        if entity_name not in found:
            print(
                f"  ! skip edge {schema['label']}: no '{entity_name}.*' file in dataset",
                file=sys.stderr,
            )
            continue
        filepath = found[entity_name]
        header = _read_header(filepath, alias_map)
        missing = [c for c in (schema["source_id"], schema["target_id"]) if c not in header]
        if missing:
            print(
                f"  ! skip edge {schema['label']}: columns {missing} absent in {filepath.name}",
                file=sys.stderr,
            )
            continue
        plans.append({"schema": schema, "path": filepath, "delimiter": _delimiter(filepath)})
    return plans
