"""Load engine: standardised node/edge CSVs -> Neo4j.

Idempotent and restartable (constraints + MERGE). ``dry_run=True`` builds the
full plan (queries + parsed row batches) without a database connection, which is
how the load path is unit-tested.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from .. import DATA_STANDARDISED
from ..schema import Schema, load_schema
from . import cypher
from .neo4j_client import DEFAULT_BATCH, Neo4jClient

_SUBTYPE_SPLIT = re.compile(r"[:;,]")


def _log(msg: str, enabled: bool) -> None:
    if enabled:
        print(msg, file=sys.stderr, flush=True)


def _props(row: dict, exclude: set[str]) -> dict:
    """Row -> property map, dropping key columns and empty values."""
    return {k: v for k, v in row.items() if k not in exclude and v != ""}


def _read_node_groups(path: Path, id_prop: str, subtype_from: str | None,
                      subtype_labels: tuple[str, ...]) -> dict[tuple[str, ...], list[dict]]:
    """Parse a node CSV into {extra_labels -> [{"id","props"}, ...]} groups."""
    groups: dict[tuple[str, ...], list[dict]] = {}
    allowed = set(subtype_labels)
    exclude = {id_prop} | ({subtype_from} if subtype_from else set())
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            node_id = row.get(id_prop, "")
            if not node_id:
                continue
            extra: tuple[str, ...] = ()
            if subtype_from:
                raw = row.get(subtype_from) or ""
                extra = tuple(
                    lbl for lbl in (t.strip() for t in _SUBTYPE_SPLIT.split(raw))
                    if lbl in allowed
                )
            groups.setdefault(extra, []).append(
                {"id": node_id, "props": _props(row, exclude)}
            )
    return groups


def _read_edge_groups(path: Path) -> dict[tuple[str, str], list[dict]]:
    """Parse an edge CSV into {(startLabel,endLabel) -> [{"startId","endId","props"}]}."""
    fixed = {"startId", "endId", "startLabel", "endLabel"}
    groups: dict[tuple[str, str], list[dict]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            start_id, end_id = row.get("startId", ""), row.get("endId", "")
            if not start_id or not end_id:
                continue
            key = (row.get("startLabel", ""), row.get("endLabel", ""))
            groups.setdefault(key, []).append(
                {"startId": start_id, "endId": end_id, "props": _props(row, fixed)}
            )
    return groups


def load(dataset: str, *, standardised_root: Path | None = None,
         config_dir: Path | None = None, batch_size: int = DEFAULT_BATCH,
         constraints: bool = True, dry_run: bool = False, log: bool = True) -> dict:
    """Load one standardised dataset into Neo4j (or plan it when ``dry_run``)."""
    schema: Schema = load_schema(config_dir)
    base = (standardised_root or DATA_STANDARDISED) / dataset
    nodes_dir, edges_dir = base / "nodes", base / "edges"

    plan: dict = {"constraints": [], "nodes": {}, "edges": {}}
    node_csvs = sorted(nodes_dir.glob("*.csv")) if nodes_dir.exists() else []
    edge_csvs = sorted(edges_dir.glob("*.csv")) if edges_dir.exists() else []

    client = None
    if not dry_run:
        client = Neo4jClient().__enter__()
    try:
        # 1) constraints for every loaded node label
        if constraints:
            for path in node_csvs:
                node = schema.nodes.get(path.stem)
                if node is None:
                    continue
                stmt = cypher.constraint_statement(node)
                plan["constraints"].append(stmt)
                if client:
                    client.run(stmt)
            _log(f"  constraints: {len(plan['constraints'])}", log)

        # 2) nodes
        for path in node_csvs:
            node = schema.nodes.get(path.stem)
            if node is None:
                _log(f"! skip {path.name}: {path.stem} not a schema node", log)
                continue
            groups = _read_node_groups(path, node.id, node.subtype_from, node.subtype_labels)
            total = 0
            for extra_labels, rows in groups.items():
                query = cypher.node_merge_query(node.label, node.id, extra_labels)
                if client:
                    client.run_batches(query, rows, batch_size)
                total += len(rows)
            plan["nodes"][node.label] = total
            _log(f"  loaded {node.label}: {total} rows", log)

        # 3) edges
        for path in edge_csvs:
            edge = schema.edges.get(path.stem)
            if edge is None:
                _log(f"! skip {path.name}: {path.stem} not a schema edge", log)
                continue
            groups = _read_edge_groups(path)
            total = 0
            for (start_label, end_label), rows in groups.items():
                start_node = schema.nodes.get(start_label)
                end_node = schema.nodes.get(end_label)
                if start_node is None or end_node is None:
                    _log(f"! skip {path.name} [{start_label}->{end_label}]: unknown label", log)
                    continue
                query = cypher.edge_merge_query(
                    edge.type, start_label, start_node.id, end_label, end_node.id
                )
                if client:
                    client.run_batches(query, rows, batch_size)
                total += len(rows)
            plan["edges"][edge.type] = total
            _log(f"  loaded {edge.type}: {total} rows", log)
    finally:
        if client:
            client.__exit__(None, None, None)

    return plan
