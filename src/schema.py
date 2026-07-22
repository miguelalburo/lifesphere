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

# Property type tokens the graph may declare. These are exactly the scalar types
# ``neo4j-admin database import`` understands; a property with no declared type
# is a plain ``string``. Kept here (not in the load layer) so the schema stays
# the single source of truth and unknown tokens fail fast at load time.
PROPERTY_TYPES: frozenset[str] = frozenset({
    "string", "int", "long", "float", "double", "boolean", "byte", "short",
    "char", "point", "date", "localtime", "time", "localdatetime", "datetime",
    "duration",
})
DEFAULT_PROPERTY_TYPE = "string"


@dataclass(frozen=True)
class Node:
    """One node label: its primary-key property and emitted property columns."""

    label: str
    id: str
    properties: tuple[str, ...] = ()
    subtype_labels: tuple[str, ...] = ()
    subtype_from: str | None = None
    # name -> declared type, only for properties annotated non-string. Excluded
    # from eq/hash: types are metadata, not part of node identity.
    property_types: dict[str, str] = field(default_factory=dict, compare=False)

    @property
    def columns(self) -> tuple[str, ...]:
        """Full CSV column order: id first, then declared properties."""
        return (self.id, *self.properties)

    def property_type(self, name: str) -> str:
        """Declared type of a property (``string`` when unannotated)."""
        return self.property_types.get(name, DEFAULT_PROPERTY_TYPE)


@dataclass(frozen=True)
class Edge:
    """One relationship type: allowed endpoint pairs + relationship properties."""

    type: str
    pairs: tuple[tuple[str, str], ...]
    properties: tuple[str, ...] = ()
    property_types: dict[str, str] = field(default_factory=dict, compare=False)

    def has_pair(self, source: str, target: str) -> bool:
        return (source, target) in self.pairs

    def property_type(self, name: str) -> str:
        """Declared type of a property (``string`` when unannotated)."""
        return self.property_types.get(name, DEFAULT_PROPERTY_TYPE)


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
            for prop, typ in node.property_types.items():
                if typ not in PROPERTY_TYPES:
                    errors.append(
                        f"node {node.label!r} property {prop!r} has "
                        f"unknown property type {typ!r}"
                    )
        for edge in self.edges.values():
            if not edge.pairs:
                errors.append(f"edge {edge.type!r} declares no endpoint pairs")
            for prop, typ in edge.property_types.items():
                if typ not in PROPERTY_TYPES:
                    errors.append(
                        f"edge {edge.type!r} property {prop!r} has "
                        f"unknown property type {typ!r}"
                    )
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


def _parse_properties(raw: list | None) -> tuple[tuple[str, ...], dict[str, str]]:
    """Split a ``properties`` list into (ordered names, name->non-string type).

    Each entry is either a bare name (``symbol`` → string) or a single-key
    mapping annotating a type (``{value: float}`` → name ``value``, type
    ``float``). Declared order is preserved; only non-default types are recorded.
    """
    names: list[str] = []
    types: dict[str, str] = {}
    for entry in raw or ():
        if isinstance(entry, dict):
            (name, typ), = entry.items()
            names.append(name)
            if typ != DEFAULT_PROPERTY_TYPE:
                types[name] = typ
        else:
            names.append(entry)
    return tuple(names), types


def load_schema(config_dir: Path | None = None) -> Schema:
    """Load and validate the node/edge catalogue. Raises on inconsistency."""
    base = (config_dir or CONFIG_DIR) / "schema"
    raw_nodes = _load_yaml(base / "nodes.yaml")
    raw_edges = _load_yaml(base / "edges.yaml")

    nodes: dict[str, Node] = {}
    for label, spec in raw_nodes.items():
        props, prop_types = _parse_properties(spec.get("properties"))
        nodes[label] = Node(
            label=label,
            id=spec["id"],
            properties=props,
            subtype_labels=tuple(spec.get("subtypeLabels") or ()),
            subtype_from=spec.get("subtypeFrom"),
            property_types=prop_types,
        )

    edges: dict[str, Edge] = {}
    for type_, spec in raw_edges.items():
        pairs = tuple((p[0], p[1]) for p in (spec.get("pairs") or ()))
        props, prop_types = _parse_properties(spec.get("properties"))
        edges[type_] = Edge(
            type=type_,
            pairs=pairs,
            properties=props,
            property_types=prop_types,
        )

    schema = Schema(nodes=nodes, edges=edges)
    errors = schema.validate()
    if errors:
        raise ValueError(
            "schema is internally inconsistent:\n  " + "\n  ".join(errors)
        )
    return schema
