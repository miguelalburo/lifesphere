"""Offline bulk-import adapter: standardised CSVs -> ``neo4j-admin import``.

Rewrites the standardised ``nodes/{Label}.csv`` + ``edges/{TYPE}.csv`` into the
header convention ``neo4j-admin database import full`` expects and assembles the
command line, driving everything from the schema. This is the *initial* build
path into a fresh, empty database; the online ``MERGE`` loader in :mod:`run` stays
the idempotent, incremental one.

Two structural rewrites vs. the standardised CSVs:

* **Nodes** — the id column becomes ``{id}:ID({Label})`` (an id-space group named
  after the label so edges resolve into it), typed properties get a ``:type``
  suffix, and a ``subtypeFrom`` column becomes admin-import's ``:LABEL`` column.
* **Edges** — admin-import binds id-space groups statically per file, but a
  standardised edge CSV interleaves several ``(startLabel, endLabel)`` pairs, so
  each edge file is *split* into one file per pair, each with the right
  ``:START_ID(group)`` / ``:END_ID(group)`` header.

Nothing here talks to a database or shells out: :func:`build_import` writes the
files and returns the command + follow-up constraint statements for the caller
to run manually on the DB host (the tool needs a stopped DBMS / empty database).
"""

from __future__ import annotations

import csv
from pathlib import Path

from .. import DATA_IMPORT, DATA_STANDARDISED
from ..schema import Node, Schema, load_schema
from . import cypher
from .run import _SUBTYPE_SPLIT, _read_edge_groups

ARRAY_DELIMITER = ";"


def _typed(col: str, type_: str) -> str:
    """``name`` for a plain string column, ``name:type`` for a typed one."""
    return col if type_ == "string" else f"{col}:{type_}"


def _extra_labels(raw: str | None, allowed: frozenset[str]) -> str:
    """Subtype cell -> ``;``-joined extra labels, filtered to declared ones."""
    parts = (t.strip() for t in _SUBTYPE_SPLIT.split(raw or ""))
    return ARRAY_DELIMITER.join(p for p in parts if p in allowed)


def _write_node_file(node, src: Path, out: Path) -> Path:
    """Rewrite one node CSV into admin-import layout. Returns the written path."""
    allowed = frozenset(node.subtype_labels)
    # The subtype column drives :LABEL, so keep it out of the property columns
    # (mirrors the online loader's exclude in run.py) to avoid emitting it twice.
    props = [p for p in node.properties if p != node.subtype_from]
    header = [f"{node.id}:ID({node.label})"]
    header += [_typed(p, node.property_type(p)) for p in props]
    if node.subtype_from:
        header.append(":LABEL")

    dst = out / f"{node.label}.csv"
    with src.open(newline="", encoding="utf-8") as fh, \
            dst.open("w", newline="", encoding="utf-8") as fout:
        writer = csv.writer(fout)
        writer.writerow(header)
        for row in csv.DictReader(fh):
            node_id = row.get(node.id, "")
            if not node_id:
                continue
            values = [node_id] + [row.get(p, "") for p in props]
            if node.subtype_from:
                values.append(_extra_labels(row.get(node.subtype_from), allowed))
            writer.writerow(values)
    return dst


def _write_edge_files(edge, src: Path, out: Path,
                      nodes: dict[str, Node]) -> list[tuple[str, str, Path]]:
    """Split one edge CSV into one admin-import file per endpoint pair.

    Returns ``[(startLabel, endLabel, path), ...]``. Pairs whose endpoint labels
    are not defined nodes are skipped (mirrors the online loader).
    """
    written: list[tuple[str, str, Path]] = []
    for (start_label, end_label), rows in _read_edge_groups(src).items():
        if start_label not in nodes or end_label not in nodes:
            continue
        header = [f":START_ID({start_label})", f":END_ID({end_label})"]
        header += [_typed(p, edge.property_type(p)) for p in edge.properties]

        dst = out / f"{edge.type}__{start_label}__{end_label}.csv"
        with dst.open("w", newline="", encoding="utf-8") as fout:
            writer = csv.writer(fout)
            writer.writerow(header)
            for row in rows:
                props = row["props"]
                writer.writerow(
                    [row["startId"], row["endId"]]
                    + [props.get(p, "") for p in edge.properties]
                )
        written.append((start_label, end_label, dst))
    return written


def build_import(dataset: str, *, standardised_root: Path | None = None,
                 out_dir: Path | None = None, database: str = "neo4j",
                 config_dir: Path | None = None,
                 id_type: str = "string") -> dict:
    """Rewrite a standardised dataset for ``neo4j-admin database import full``.

    Writes the rewritten CSVs under ``out_dir`` and returns a plan:
    ``command`` (the argv to run on the DB host), ``constraints`` (uniqueness
    statements to apply once the database is started), and the written
    ``node_files`` / ``edge_files``.
    """
    schema: Schema = load_schema(config_dir)
    base = (standardised_root or DATA_STANDARDISED) / dataset
    out = out_dir or (DATA_IMPORT / dataset)
    out.mkdir(parents=True, exist_ok=True)

    nodes_dir, edges_dir = base / "nodes", base / "edges"
    node_csvs = sorted(nodes_dir.glob("*.csv")) if nodes_dir.exists() else []
    edge_csvs = sorted(edges_dir.glob("*.csv")) if edges_dir.exists() else []

    node_args: list[str] = []
    rel_args: list[str] = []
    constraints: list[str] = []
    node_files: list[Path] = []
    edge_files: list[Path] = []

    for path in node_csvs:
        node = schema.nodes.get(path.stem)
        if node is None:
            continue
        dst = _write_node_file(node, path, out)
        node_files.append(dst)
        node_args.append(f"--nodes={node.label}={dst}")
        constraints.append(cypher.constraint_statement(node))

    for path in edge_csvs:
        edge = schema.edges.get(path.stem)
        if edge is None:
            continue
        for _start, _end, dst in _write_edge_files(edge, path, out, schema.nodes):
            edge_files.append(dst)
            rel_args.append(f"--relationships={edge.type}={dst}")

    command = [
        "neo4j-admin", "database", "import", "full",
        f"--id-type={id_type}",
        f"--array-delimiter={ARRAY_DELIMITER}",
        # sparse standardised rows leave many cells blank; treat "" as null so an
        # empty typed column (e.g. betaValue:float) is skipped, not a parse error
        # that aborts the import (matches the online loader dropping empty props).
        "--ignore-empty-strings=true",
        *node_args, *rel_args, database,
    ]
    return {
        "command": command,
        "constraints": constraints,
        "node_files": node_files,
        "edge_files": edge_files,
    }
