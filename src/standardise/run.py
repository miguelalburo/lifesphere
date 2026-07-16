"""Standardise engine: a raw dataset directory -> node/edge CSVs.

Pure-``csv`` (no pandas) and grain-preserving: one output row per source row
(``dedup`` collapses on id). Never fails hard on absent data — a missing file,
unbound mapping, or missing id column is logged ``! skip`` and the engine moves
on, so a schema/profile may safely describe entities not present in a dataset.

Column binding (which raw column feeds which schema property) is delegated to
:class:`~src.standardise.aliases.ColumnResolver`; ``report`` reuses it to show
mapping coverage without writing any output.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from .. import DATA_RAW, DATA_STANDARDISED
from ..schema import Node, Schema, load_schema
from .aliases import ColumnResolver
from .mapping import EdgeMapping, Mapping, NodeMapping, load_mapping, load_placeholders
from .transform import scrub, strip_prefix


def _log(msg: str, enabled: bool) -> None:
    if enabled:
        print(msg, file=sys.stderr, flush=True)


def _delimiter(path: Path) -> str:
    return "\t" if path.suffix.lower() in (".tsv", ".tab") else ","


def _header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as fh:
        return csv.DictReader(fh, delimiter=_delimiter(path)).fieldnames or []


def _write_node(node: Node, cfg: NodeMapping, src: Path, out_dir: Path,
                placeholders: frozenset[str], mapping: "Mapping",
                log: bool) -> int | None:
    columns = list(node.columns)
    if node.subtype_from and node.subtype_from not in columns:
        columns.append(node.subtype_from)

    delim = _delimiter(src)
    with src.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=delim)
        fields = reader.fieldnames or []
        if cfg.key not in fields:
            _log(f"! skip node {node.label}: id column {cfg.key!r} not in {src.name}", log)
            return None
        resolver = ColumnResolver(
            fields, cfg.props, cfg.aliases, mapping.aliases,
            (*mapping.strip_header_prefix, *cfg.strip_header_prefix),
            shared_aliases=mapping.shared_aliases,
        )
        resolved = resolver.resolved_map(columns[1:])  # prop -> raw column | None

        out_path = out_dir / f"{node.label}.csv"
        seen: set[str] = set()
        count = 0
        with out_path.open("w", newline="", encoding="utf-8") as out_fh:
            writer = csv.writer(out_fh)
            writer.writerow(columns)
            for row in reader:
                node_id = strip_prefix(scrub(row.get(cfg.key), placeholders), cfg.strip_prefix)
                if not node_id:
                    continue
                if cfg.dedup and node_id in seen:
                    continue
                seen.add(node_id)
                record = [node_id]
                for prop in columns[1:]:
                    raw = resolved[prop]
                    record.append(scrub(row.get(raw) if raw else "", placeholders))
                writer.writerow(record)
                count += 1
    _log(f"  wrote nodes/{node.label}.csv ({count} rows)", log)
    return count


def _write_edge(edge_type: str, cfg: EdgeMapping, pair: tuple[str, str], src: Path,
                out_dir: Path, properties: tuple[str, ...], placeholders: frozenset[str],
                mapping: "Mapping", log: bool) -> int | None:
    start_label, end_label = pair
    header = ["startId", "endId", "startLabel", "endLabel", *properties]

    delim = _delimiter(src)
    with src.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=delim)
        fields = reader.fieldnames or []
        for key in (cfg.start_key, cfg.end_key):
            if key not in fields:
                _log(f"! skip edge {edge_type}: column {key!r} not in {src.name}", log)
                return None
        resolver = ColumnResolver(
            fields, cfg.props, cfg.aliases, mapping.aliases,
            (*mapping.strip_header_prefix, *cfg.strip_header_prefix),
            shared_aliases=mapping.shared_aliases,
        )
        resolved = resolver.resolved_map(properties)

        out_path = out_dir / f"{edge_type}.csv"
        seen: set[tuple[str, str]] = set()
        count = 0
        with out_path.open("w", newline="", encoding="utf-8") as out_fh:
            writer = csv.writer(out_fh)
            writer.writerow(header)
            for row in reader:
                start_id = strip_prefix(scrub(row.get(cfg.start_key), placeholders), cfg.strip_start_prefix)
                end_id = strip_prefix(scrub(row.get(cfg.end_key), placeholders), cfg.strip_end_prefix)
                if not start_id or not end_id:
                    continue
                if cfg.dedup and (start_id, end_id) in seen:
                    continue
                seen.add((start_id, end_id))
                record = [start_id, end_id, start_label, end_label]
                for prop in properties:
                    raw = resolved[prop]
                    record.append(scrub(row.get(raw) if raw else "", placeholders))
                writer.writerow(record)
                count += 1
    _log(f"  wrote edges/{edge_type}.csv ({count} rows)", log)
    return count


def standardise(dataset: str, profile: str = "extract", *, raw_root: Path | None = None,
                out_root: Path | None = None, config_dir: Path | None = None,
                log: bool = True) -> dict:
    """Standardise one dataset. Returns a summary of row counts and skips."""
    schema = load_schema(config_dir)
    mapping: Mapping = load_mapping(profile, config_dir)
    placeholders = load_placeholders(config_dir)

    raw_dir = (raw_root or DATA_RAW) / dataset
    out_dir = (out_root or DATA_STANDARDISED) / dataset
    nodes_dir, edges_dir = out_dir / "nodes", out_dir / "edges"
    nodes_dir.mkdir(parents=True, exist_ok=True)
    edges_dir.mkdir(parents=True, exist_ok=True)

    summary: dict = {"nodes": {}, "edges": {}, "skipped": []}

    for label, cfg in mapping.nodes.items():
        node = schema.nodes.get(label)
        if node is None:
            _log(f"! skip node {label}: not defined in schema", log)
            summary["skipped"].append(label)
            continue
        if not cfg.bound:
            _log(f"! skip node {label}: mapping unbound (no key)", log)
            summary["skipped"].append(label)
            continue
        src = raw_dir / cfg.file
        if not src.exists():
            _log(f"! skip node {label}: {cfg.file} not found", log)
            summary["skipped"].append(label)
            continue
        count = _write_node(node, cfg, src, nodes_dir, placeholders, mapping, log)
        if count is None:
            summary["skipped"].append(label)
        else:
            summary["nodes"][label] = count

    for edge_type, cfg in mapping.edges.items():
        edge = schema.edges.get(edge_type)
        if edge is None:
            _log(f"! skip edge {edge_type}: not defined in schema", log)
            summary["skipped"].append(edge_type)
            continue
        if not cfg.bound:
            _log(f"! skip edge {edge_type}: mapping unbound (no start/end key)", log)
            summary["skipped"].append(edge_type)
            continue
        pair = cfg.pair or edge.pairs[0]
        if not edge.has_pair(*pair):
            _log(f"! skip edge {edge_type}: pair {pair} not in schema", log)
            summary["skipped"].append(edge_type)
            continue
        src = raw_dir / cfg.file
        if not src.exists():
            _log(f"! skip edge {edge_type}: {cfg.file} not found", log)
            summary["skipped"].append(edge_type)
            continue
        count = _write_edge(edge_type, cfg, pair, src, edges_dir, edge.properties,
                            placeholders, mapping, log)
        if count is None:
            summary["skipped"].append(edge_type)
        else:
            summary["edges"][edge_type] = count

    return summary


def _enrich_unused(rep: dict, src: Path) -> None:
    """Replace plain-string unused columns with {column, samples} dicts in-place."""
    sampled = _sample_values(src, rep["unused"])
    rep["unused"] = [{"column": c, "samples": sampled[c]} for c in rep["unused"]]


def _sample_values(src: Path, columns: list[str], max_values: int = 5) -> dict[str, list[str]]:
    """Read src once; collect up to max_values distinct non-empty values per column."""
    samples: dict[str, set[str]] = {c: set() for c in columns}
    delim = _delimiter(src)
    with src.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=delim)
        for row in reader:
            for col in columns:
                val = row.get(col, "")
                if val and len(samples[col]) < max_values:
                    samples[col].add(val)
    return {c: list(v) for c, v in samples.items()}


def report(dataset: str, profile: str = "extract", *, raw_root: Path | None = None,
           config_dir: Path | None = None, values: bool = False) -> dict:
    """Column-binding coverage per node/edge, without writing any output.

    For each entry whose source file exists, reports which schema properties were
    matched (and by which strategy), which are unmatched, and which raw columns
    are unused — the guided view for filling in a mapping profile.

    When ``values=True``, unused columns are returned as ``{"column": str,
    "samples": list[str]}`` dicts with up to 5 distinct non-empty sample values.
    When ``values=False`` (default) they remain plain strings.
    """
    schema: Schema = load_schema(config_dir)
    mapping: Mapping = load_mapping(profile, config_dir)
    raw_dir = (raw_root or DATA_RAW) / dataset

    out: dict = {"nodes": {}, "edges": {}, "skipped": []}

    for label, cfg in mapping.nodes.items():
        node = schema.nodes.get(label)
        if node is None:
            out["skipped"].append((label, "not in schema"))
            continue
        src = raw_dir / cfg.file
        if not src.exists():
            out["skipped"].append((label, f"{cfg.file} not found"))
            continue
        fields = _header(src)
        props = list(node.properties)
        if node.subtype_from:
            props.append(node.subtype_from)
        resolver = ColumnResolver(
            fields, cfg.props, cfg.aliases, mapping.aliases,
            (*mapping.strip_header_prefix, *cfg.strip_header_prefix),
            shared_aliases=mapping.shared_aliases,
        )
        rep = resolver.report(props, reserved=tuple(k for k in (cfg.key,) if k))
        rep["key"] = cfg.key
        rep["key_present"] = bool(cfg.key) and cfg.key in fields
        if values and rep["unused"]:
            _enrich_unused(rep, src)
        out["nodes"][label] = rep

    for edge_type, cfg in mapping.edges.items():
        edge = schema.edges.get(edge_type)
        if edge is None:
            out["skipped"].append((edge_type, "not in schema"))
            continue
        src = raw_dir / cfg.file
        if not src.exists():
            out["skipped"].append((edge_type, f"{cfg.file} not found"))
            continue
        fields = _header(src)
        resolver = ColumnResolver(
            fields, cfg.props, cfg.aliases, mapping.aliases,
            (*mapping.strip_header_prefix, *cfg.strip_header_prefix),
            shared_aliases=mapping.shared_aliases,
        )
        reserved = tuple(k for k in (cfg.start_key, cfg.end_key) if k)
        rep = resolver.report(edge.properties, reserved=reserved)
        rep["start_key"] = cfg.start_key
        rep["end_key"] = cfg.end_key
        rep["endpoints_present"] = all(k in fields for k in reserved) if reserved else False
        if values and rep["unused"]:
            _enrich_unused(rep, src)
        out["edges"][edge_type] = rep

    return out


def format_report(rep: dict) -> str:
    """Render a :func:`report` result as a human-readable coverage summary."""
    lines: list[str] = []
    for kind in ("nodes", "edges"):
        for name, r in rep[kind].items():
            n_match, n_un = len(r["matched"]), len(r["unmatched"])
            lines.append(f"\n{name}  ({n_match} matched, {n_un} unmatched)")
            if kind == "nodes":
                flag = "" if r["key_present"] else "  <-- MISSING / unbound"
                lines.append(f"  key: {r['key']}{flag}")
            else:
                flag = "" if r["endpoints_present"] else "  <-- MISSING / unbound"
                lines.append(f"  endpoints: {r['start_key']} -> {r['end_key']}{flag}")
            for prop, raw, strat in r["matched"]:
                lines.append(f"    ✓ {prop:<28} <- {raw}  [{strat}]")
            if r["unmatched"]:
                lines.append(f"    unmatched props: {', '.join(r['unmatched'])}")
            if r["unused"]:
                parts = []
                for entry in r["unused"][:12]:
                    if isinstance(entry, dict):
                        samples = entry.get("samples") or []
                        sample_str = f" [{', '.join(str(s) for s in samples[:5])}]" if samples else ""
                        parts.append(f"{entry['column']}{sample_str}")
                    else:
                        parts.append(entry)
                preview = ", ".join(parts)
                more = f" (+{len(r['unused']) - 12} more)" if len(r["unused"]) > 12 else ""
                lines.append(f"    unused columns: {preview}{more}")
            if r["collisions"]:
                lines.append(f"    ambiguous headers: {r['collisions']}")
    for name, why in rep["skipped"]:
        lines.append(f"\n{name}  skipped: {why}")
    return "\n".join(lines)
