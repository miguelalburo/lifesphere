"""The graph definition — the one deep module both stages import.

Loads ``config/schema/nodes.yaml`` + ``config/schema/edges.yaml`` into a
validated :class:`Schema`. Everything downstream (standardise, load, validate)
asks the schema for node id columns, property whitelists, and edge endpoints
rather than hardcoding them, so a pure-config schema change needs no code change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import CONFIG_DIR


@dataclass(frozen=True)
class Node:
    """One node label: its primary-key property and emitted property columns."""

    label: str
    id: str
    properties: tuple[str, ...] = ()
    subtype_labels: tuple[str, ...] = ()
    subtype_from: str | None = None

    @property
    def columns(self) -> tuple[str, ...]:
        """Full CSV column order: id first, then declared properties."""
        return (self.id, *self.properties)


@dataclass(frozen=True)
class Edge:
    """One relationship type: allowed endpoint pairs + relationship properties."""

    type: str
    pairs: tuple[tuple[str, str], ...]
    properties: tuple[str, ...] = ()

    def has_pair(self, source: str, target: str) -> bool:
        return (source, target) in self.pairs


@dataclass(frozen=True)
class Schema:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)

    def node(self, label: str) -> Node:
        return self.nodes[label]

    def edge(self, type_: str) -> Edge:
        return self.edges[type_]

    def validate(self) -> list[str]:
        """Return internal-consistency errors (empty list == consistent).

        Checks that ids are non-empty, subtype labels don't collide with real
        node labels, and every edge endpoint references a defined node label.
        """
        errors: list[str] = []
        labels = set(self.nodes)
        for node in self.nodes.values():
            if not node.id:
                errors.append(f"node {node.label!r} has an empty id")
            if node.subtype_from and not node.subtype_labels:
                errors.append(
                    f"node {node.label!r} sets subtype_from but no subtype_labels"
                )
        for edge in self.edges.values():
            if not edge.pairs:
                errors.append(f"edge {edge.type!r} declares no endpoint pairs")
            for source, target in edge.pairs:
                for role, lbl in (("source", source), ("target", target)):
                    if lbl not in labels:
                        errors.append(
                            f"edge {edge.type!r} {role} {lbl!r} is not a defined node"
                        )
        return errors


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_schema(config_dir: Path | None = None) -> Schema:
    """Load and validate the node/edge catalogue. Raises on inconsistency."""
    base = (config_dir or CONFIG_DIR) / "schema"
    raw_nodes = _load_yaml(base / "nodes.yaml")
    raw_edges = _load_yaml(base / "edges.yaml")

    nodes: dict[str, Node] = {}
    for label, spec in raw_nodes.items():
        nodes[label] = Node(
            label=label,
            id=spec["id"],
            properties=tuple(spec.get("properties") or ()),
            subtype_labels=tuple(spec.get("subtypeLabels") or ()),
            subtype_from=spec.get("subtypeFrom"),
        )

    edges: dict[str, Edge] = {}
    for type_, spec in raw_edges.items():
        pairs = tuple((p[0], p[1]) for p in (spec.get("pairs") or ()))
        edges[type_] = Edge(
            type=type_,
            pairs=pairs,
            properties=tuple(spec.get("properties") or ()),
        )

    schema = Schema(nodes=nodes, edges=edges)
    errors = schema.validate()
    if errors:
        raise ValueError(
            "schema is internally inconsistent:\n  " + "\n  ".join(errors)
        )
    return schema
