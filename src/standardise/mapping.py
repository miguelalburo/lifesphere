"""Source -> schema binding (the mapping profile, e.g. ``config/mapping/extract.yaml``).

A profile says, for each schema node/edge, which raw file and columns feed it.
Bindings can be partial: entries with no ``key`` (or ``start_key``/``end_key``)
are marked incomplete and skipped by the engine rather than failing the run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .. import CONFIG_DIR


@dataclass(frozen=True)
class NodeMapping:
    label: str
    files: tuple[str, ...]            # one or more source files (union, shared dedup)
    key: str | None = None            # raw column holding the node id
    strip_prefix: str | None = None
    dedup: bool = True
    props: dict[str, str] = field(default_factory=dict)    # canonicalProp -> raw_col
    aliases: dict[str, str] = field(default_factory=dict)  # raw_col -> canonicalProp
    strip_header_prefix: tuple[str, ...] = ()              # table-name prefixes on headers

    @property
    def file(self) -> str:
        """First source file (backward-compat accessor)."""
        return self.files[0] if self.files else ""

    @property
    def bound(self) -> bool:
        return bool(self.key)


@dataclass(frozen=True)
class EdgeMapping:
    type: str
    files: tuple[str, ...]            # one or more source files (union, shared dedup)
    pair: tuple[str, str]
    start_key: str | None = None
    end_key: str | None = None
    strip_start_prefix: str | None = None
    strip_end_prefix: str | None = None
    dedup: bool = True
    props: dict[str, str] = field(default_factory=dict)    # relProp -> raw_col
    aliases: dict[str, str] = field(default_factory=dict)  # raw_col -> relProp
    strip_header_prefix: tuple[str, ...] = ()              # table-name prefixes on headers

    @property
    def file(self) -> str:
        """First source file (backward-compat accessor)."""
        return self.files[0] if self.files else ""

    @property
    def bound(self) -> bool:
        return bool(self.start_key and self.end_key)


@dataclass(frozen=True)
class Mapping:
    profile: str
    aliases: dict[str, str] = field(default_factory=dict)         # profile-global raw_col -> canonicalProp
    shared_aliases: dict[str, str] = field(default_factory=dict)  # config/aliases.yaml (lowest priority)
    strip_header_prefix: tuple[str, ...] = ()
    nodes: dict[str, NodeMapping] = field(default_factory=dict)
    edges: dict[str, EdgeMapping] = field(default_factory=dict)
    reshape: list = field(default_factory=list)   # raw reshape: block (parsed by src.reshape)


def _as_tuple(value) -> tuple[str, ...]:
    """Coerce a str | list | None config value into a tuple of strings."""
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_placeholders(config_dir: Path | None = None) -> frozenset[str]:
    data = _load_yaml((config_dir or CONFIG_DIR) / "placeholders.yaml")
    return frozenset(t.lower() for t in (data.get("placeholders") or []))


def load_mapping(profile: str = "extract", config_dir: Path | None = None,
                 _seen: frozenset[str] = frozenset()) -> Mapping:
    path = (config_dir or CONFIG_DIR) / "mapping" / f"{profile}.yaml"
    data = _load_yaml(path)

    shared_path = (config_dir or CONFIG_DIR) / "aliases.yaml"
    shared_aliases: dict[str, str] = {}
    if shared_path.exists():
        shared_aliases = dict(_load_yaml(shared_path) or {})

    # A profile may `include:` others to reuse their bindings (e.g. traditional
    # reuses omics' observation node/edge bindings). Included entries are merged
    # first; this profile's own entries override on conflict.
    inc_nodes: dict[str, NodeMapping] = {}
    inc_edges: dict[str, EdgeMapping] = {}
    inc_aliases: dict[str, str] = {}
    for inc in (data.get("include") or []):
        if inc in _seen or inc == profile:
            continue
        inc_map = load_mapping(inc, config_dir, _seen | {profile})
        inc_nodes.update(inc_map.nodes)
        inc_edges.update(inc_map.edges)
        inc_aliases.update(inc_map.aliases)

    nodes: dict[str, NodeMapping] = {}
    for label, spec in (data.get("nodes") or {}).items():
        raw_file = spec["file"]
        files = tuple(raw_file) if isinstance(raw_file, list) else (raw_file,)
        nodes[label] = NodeMapping(
            label=label,
            files=files,
            key=spec.get("key"),
            strip_prefix=spec.get("strip_prefix"),
            dedup=spec.get("dedup", True),
            props=dict(spec.get("props") or {}),
            aliases=dict(spec.get("aliases") or {}),
            strip_header_prefix=_as_tuple(spec.get("strip_header_prefix")),
        )

    edges: dict[str, EdgeMapping] = {}
    for type_, spec in (data.get("edges") or {}).items():
        pair = spec.get("pair")
        raw_file = spec["file"]
        files = tuple(raw_file) if isinstance(raw_file, list) else (raw_file,)
        edges[type_] = EdgeMapping(
            type=type_,
            files=files,
            pair=tuple(pair) if pair else (),
            start_key=spec.get("start_key"),
            end_key=spec.get("end_key"),
            strip_start_prefix=spec.get("strip_start_prefix"),
            strip_end_prefix=spec.get("strip_end_prefix"),
            dedup=spec.get("dedup", True),
            props=dict(spec.get("props") or {}),
            aliases=dict(spec.get("aliases") or {}),
            strip_header_prefix=_as_tuple(spec.get("strip_header_prefix")),
        )

    return Mapping(
        profile=data.get("profile", profile),
        aliases={**inc_aliases, **dict(data.get("aliases") or {})},
        shared_aliases=shared_aliases,
        strip_header_prefix=_as_tuple(data.get("strip_header_prefix")),
        nodes={**inc_nodes, **nodes},
        edges={**inc_edges, **edges},
        reshape=list(data.get("reshape") or []),
    )
