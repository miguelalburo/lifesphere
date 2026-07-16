"""Column lookup / alias matching — how a raw source column feeds a schema property.

A :class:`ColumnResolver` is bound to one file's headers and answers, for each
canonical schema property, "which raw column supplies this, and by what rule?".
Resolution is a layered chain tried in strict priority order (first match wins),
so a binding is either explicit config or an *exact* structural match — never a
silent guess:

    1. override    node ``props: {canonical: raw}``            (highest priority)
    2. alias       raw->canonical table (node overlays global)
    3. camel       camelCase(raw) == canonical
    4. normalized  lower+strip-non-alnum equal on both sides
    5. suffix      dotted GDC names, e.g. ``diagnoses.tumor_grade`` -> ``tumorGrade``

Because ``resolve`` also returns the strategy that hit, the same object powers the
``--report`` coverage view used to fill in a mapping profile against real data.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from .transform import camel

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def _normalize(name: str) -> str:
    """Casefold and drop every non-alphanumeric char (snake/camel/space agnostic)."""
    return _NON_ALNUM.sub("", name.lower())


def _index(pairs: list[tuple[str, str]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Build a first-wins lookup, recording collisions for auditing."""
    out: dict[str, str] = {}
    collisions: dict[str, list[str]] = {}
    for key, value in pairs:
        if not key:
            continue
        if key in out:
            collisions.setdefault(key, [out[key]]).append(value)
        else:
            out[key] = value
    return out, collisions


class Resolution(NamedTuple):
    raw: str | None
    strategy: str


class ColumnResolver:
    """Resolves canonical schema properties against one file's raw columns."""

    def __init__(self, fieldnames: list[str], props: dict[str, str] | None = None,
                 node_aliases: dict[str, str] | None = None,
                 global_aliases: dict[str, str] | None = None,
                 strip_prefixes: tuple[str, ...] = ()):
        self.fieldnames = list(fieldnames)
        self._present = set(fieldnames)
        self._props = props or {}
        self._strip_prefixes = tuple(strip_prefixes)

        # raw->canonical alias table (node entries override global entries)
        self._canon_to_raw: dict[str, str] = {}
        for raw, canon in {**(global_aliases or {}), **(node_aliases or {})}.items():
            if raw in self._present:
                self._canon_to_raw.setdefault(canon, raw)

        # Index by full header first (higher priority), then by prefix-stripped
        # header, so an exact `morphology` always beats a stripped
        # `diagnosis_morphology`. Values stay the real raw column names.
        full = [(c, c) for c in fieldnames]
        stripped = [(form, c) for c in fieldnames for form in self._stripped_forms(c)]
        self._camel, self._camel_collisions = _index(
            [(camel(name), c) for name, c in full + stripped]
        )
        self._norm, _ = _index([(_normalize(name), c) for name, c in full + stripped])
        dotted = [(c.rsplit(".", 1)[-1], c) for c in fieldnames if "." in c]
        self._suffix_camel, _ = _index([(camel(seg), c) for seg, c in dotted])
        self._suffix_norm, _ = _index([(_normalize(seg), c) for seg, c in dotted])

    def _stripped_forms(self, field: str) -> list[str]:
        """Header names after removing any configured table-name prefix."""
        return [
            field[len(p):]
            for p in self._strip_prefixes
            if p and field.startswith(p) and len(field) > len(p)
        ]

    @property
    def collisions(self) -> dict[str, list[str]]:
        """camelCase keys that more than one raw column maps to (first was kept)."""
        return self._camel_collisions

    def resolve(self, prop: str) -> Resolution:
        override = self._props.get(prop)
        if override and override in self._present:
            return Resolution(override, "override")
        if prop in self._canon_to_raw:
            return Resolution(self._canon_to_raw[prop], "alias")
        if prop in self._camel:
            return Resolution(self._camel[prop], "camel")
        norm = _normalize(prop)
        if norm in self._norm:
            return Resolution(self._norm[norm], "normalized")
        if prop in self._suffix_camel:
            return Resolution(self._suffix_camel[prop], "suffix")
        if norm in self._suffix_norm:
            return Resolution(self._suffix_norm[norm], "suffix")
        return Resolution(None, "unmatched")

    def resolved_map(self, props) -> dict[str, str | None]:
        """Precompute {canonical -> raw column | None} for a set of properties."""
        return {p: self.resolve(p).raw for p in props}

    def report(self, props, *, reserved: tuple[str, ...] = ()) -> dict:
        """Coverage for a set of properties: matched / unmatched / unused columns.

        ``reserved`` names raw columns already consumed elsewhere (id key, edge
        endpoint columns) so they aren't reported as unused.
        """
        matched: list[tuple[str, str, str]] = []
        unmatched: list[str] = []
        used: set[str] = set()
        for prop in props:
            res = self.resolve(prop)
            if res.raw:
                matched.append((prop, res.raw, res.strategy))
                used.add(res.raw)
            else:
                unmatched.append(prop)
        consumed = used | set(reserved)
        unused = [c for c in self.fieldnames if c not in consumed]
        return {
            "matched": matched,
            "unmatched": unmatched,
            "unused": unused,
            "collisions": self.collisions,
        }
