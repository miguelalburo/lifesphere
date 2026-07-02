"""Pre-load referential-integrity check for standardised KG CSVs.

The Bolt loader builds edges with ``MATCH (a),(b) MERGE (a)-[r]->(b)`` — if either
endpoint node is missing, Neo4j silently produces no relationship. That turns a data
problem (a dangling FK in the standardised CSVs) into silent edge loss that only
surfaces much later as an unexpectedly empty subgraph.

This module reads the standardised ``nodes/*.csv`` and ``edges/*.csv`` **offline**
(no database) and reports, per edge file, how many source/target ids point at a node
that does not exist. Endpoint labels come from ``edges.json`` via
``neo4j_loader.load_schema``; a polymorphic (``None``) endpoint is checked against the
union of all node ids, since GDC UUIDs are globally unique.

    python3 -m src.load.validate data/standardised/TCGA_COMBINED [--strict]
"""

import argparse
import csv
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .neo4j_loader import _DEFAULT_SCHEMA_DIR, load_schema

log = logging.getLogger(__name__)

_SAMPLE = 5  # how many offending ids to keep as examples per edge


@dataclass
class EdgeReport:
    label: str
    total: int = 0
    dangling_source: int = 0
    dangling_target: int = 0
    src_examples: list[str] = field(default_factory=list)
    tgt_examples: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.dangling_source == 0 and self.dangling_target == 0


def collect_node_ids(nodes_dir: Path) -> tuple[dict[str, set[str]], set[str]]:
    """Return per-label id sets and their union from ``nodes/*.csv``."""
    by_label: dict[str, set[str]] = {}
    everything: set[str] = set()
    for path in sorted(nodes_dir.glob("*.csv")):
        ids: set[str] = set()
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                node_id = (row.get("id") or "").strip()
                if node_id:
                    ids.add(node_id)
        by_label[path.stem] = ids
        everything |= ids
    return by_label, everything


def _endpoint_ids(
    label: str | None, by_label: dict[str, set[str]], everything: set[str]
) -> set[str]:
    """Ids valid for an endpoint: the label's own set, or all ids if polymorphic."""
    if label and label in by_label:
        return by_label[label]
    return everything


def validate(input_dir: Path, schema_dir: Path = _DEFAULT_SCHEMA_DIR) -> list[EdgeReport]:
    """Check every edge file's endpoints against the node id sets."""
    nodes_dir = input_dir / "nodes"
    edges_dir = input_dir / "edges"
    by_label, everything = collect_node_ids(nodes_dir)
    _, edge_schema = load_schema(schema_dir)

    reports: list[EdgeReport] = []
    for path in sorted(edges_dir.glob("*.csv")):
        label = path.stem
        src_label, tgt_label = edge_schema.get(label, (None, None))
        if label not in edge_schema:
            log.warning("edge %s: not in edges.json — checking against all node ids", label)
        valid_src = _endpoint_ids(src_label, by_label, everything)
        valid_tgt = _endpoint_ids(tgt_label, by_label, everything)

        rep = EdgeReport(label=label)
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                s = (row.get("source_id") or "").strip()
                t = (row.get("target_id") or "").strip()
                if not s or not t:
                    continue
                rep.total += 1
                if s not in valid_src:
                    rep.dangling_source += 1
                    if len(rep.src_examples) < _SAMPLE:
                        rep.src_examples.append(s)
                if t not in valid_tgt:
                    rep.dangling_target += 1
                    if len(rep.tgt_examples) < _SAMPLE:
                        rep.tgt_examples.append(t)
        reports.append(rep)
    return reports


def format_report(reports: list[EdgeReport]) -> str:
    lines = [f"{'edge':<24}{'rows':>10}{'dangling_src':>14}{'dangling_tgt':>14}"]
    for r in reports:
        lines.append(
            f"{r.label:<24}{r.total:>10}{r.dangling_source:>14}{r.dangling_target:>14}"
        )
        if not r.ok:
            if r.src_examples:
                lines.append(f"    missing source e.g. {', '.join(r.src_examples)}")
            if r.tgt_examples:
                lines.append(f"    missing target e.g. {', '.join(r.tgt_examples)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Validate referential integrity of standardised KG CSVs.")
    p.add_argument("input_dir", type=Path, help="Dir with nodes/ and edges/ subdirs")
    p.add_argument("--schemas", type=Path, default=_DEFAULT_SCHEMA_DIR)
    p.add_argument("--strict", action="store_true",
                   help="Exit non-zero if any edge has a dangling endpoint.")
    args = p.parse_args(argv)

    reports = validate(args.input_dir, args.schemas)
    print(format_report(reports))

    dangling = [r for r in reports if not r.ok]
    if dangling:
        total = sum(r.dangling_source + r.dangling_target for r in dangling)
        print(f"\n{len(dangling)} edge type(s) with {total} dangling endpoint(s).", file=sys.stderr)
        if args.strict:
            return 1
    else:
        print("\nAll edges reference existing nodes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
