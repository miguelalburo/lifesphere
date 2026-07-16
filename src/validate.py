"""Offline referential-integrity check for standardised CSVs (no Neo4j).

Run before a load to catch dangling edges and duplicate/blank ids early:

    python -m src.validate <dataset> [--strict]

Checks, using ``config/schema`` as the source of truth:
  * every node/edge CSV corresponds to a defined schema label;
  * each node id column is present, non-empty, and unique;
  * every edge endpoint id exists in the referenced node CSV.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from . import DATA_STANDARDISED
from .schema import Schema, load_schema


def _node_ids(path: Path, id_prop: str) -> tuple[set[str], list[str]]:
    """Return (id set, problems) for one node CSV."""
    ids: set[str] = set()
    problems: list[str] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if id_prop not in (reader.fieldnames or []):
            return ids, [f"{path.name}: missing id column {id_prop!r}"]
        for i, row in enumerate(reader, start=2):
            value = (row.get(id_prop) or "").strip()
            if not value:
                problems.append(f"{path.name}:{i}: blank id")
                continue
            if value in ids:
                problems.append(f"{path.name}:{i}: duplicate id {value!r}")
            ids.add(value)
    return ids, problems


def validate(dataset: str, *, standardised_root: Path | None = None,
             config_dir: Path | None = None) -> dict:
    """Validate a standardised dataset. Returns a report with a ``problems`` list."""
    schema: Schema = load_schema(config_dir)
    base = (standardised_root or DATA_STANDARDISED) / dataset
    nodes_dir, edges_dir = base / "nodes", base / "edges"

    problems: list[str] = []
    id_index: dict[str, set[str]] = {}

    for path in sorted(nodes_dir.glob("*.csv")) if nodes_dir.exists() else []:
        node = schema.nodes.get(path.stem)
        if node is None:
            problems.append(f"{path.name}: {path.stem} is not a defined node label")
            continue
        ids, node_problems = _node_ids(path, node.id)
        id_index[node.label] = ids
        problems.extend(node_problems)

    n_edges = 0
    for path in sorted(edges_dir.glob("*.csv")) if edges_dir.exists() else []:
        if path.stem not in schema.edges:
            problems.append(f"{path.name}: {path.stem} is not a defined edge type")
            continue
        with path.open(newline="", encoding="utf-8") as fh:
            for i, row in enumerate(csv.DictReader(fh), start=2):
                n_edges += 1
                start_label, end_label = row.get("startLabel", ""), row.get("endLabel", "")
                for label, key in ((start_label, "startId"), (end_label, "endId")):
                    if label not in id_index:
                        problems.append(
                            f"{path.name}:{i}: endpoint label {label!r} has no loaded node CSV"
                        )
                        continue
                    value = (row.get(key) or "").strip()
                    if value not in id_index[label]:
                        problems.append(
                            f"{path.name}:{i}: dangling {key} {value!r} (no {label} node)"
                        )

    return {
        "dataset": dataset,
        "node_types": len(id_index),
        "node_ids": sum(len(v) for v in id_index.values()),
        "edges": n_edges,
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.validate",
        description="Check referential integrity of standardised CSVs (offline).",
    )
    parser.add_argument("dataset", help="dataset folder name under data/standardised/")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero if any problem is found")
    args = parser.parse_args(argv)

    report = validate(args.dataset)
    for problem in report["problems"]:
        print(problem, file=sys.stderr)
    print(
        f"{report['dataset']}: {report['node_types']} node types, "
        f"{report['node_ids']} node ids, {report['edges']} edges, "
        f"{len(report['problems'])} problems",
        file=sys.stderr,
    )
    return 1 if args.strict and report["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
