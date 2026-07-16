"""Pure value/name transforms used while emitting standardised CSVs.

Deliberately tiny and side-effect-free so they are trivially unit-testable.
"""

from __future__ import annotations

import re

_SEP = re.compile(r"[^0-9a-zA-Z]+")


def camel(name: str) -> str:
    """camelCase a raw column name. Already-camel single tokens pass through.

    ``sample_id`` -> ``sampleId``; ``days to collection`` -> ``daysToCollection``;
    ``gdcSampleId`` -> ``gdcSampleId`` (unchanged).
    """
    if not name:
        return name
    parts = [p for p in _SEP.split(name) if p]
    if not parts:
        return name
    head, *tail = parts
    head = head[0].lower() + head[1:]
    return head + "".join(p[:1].upper() + p[1:] for p in tail)


def scrub(value: str | None, placeholders: frozenset[str]) -> str:
    """Trim whitespace and blank out placeholder/sentinel tokens.

    ``placeholders`` is expected to be a set of lower-cased tokens.
    """
    if value is None:
        return ""
    v = value.strip()
    return "" if v.lower() in placeholders else v


def strip_prefix(value: str, prefix: str | None) -> str:
    """Remove a literal id prefix if present (e.g. ``TCGA-`` accession glue)."""
    if prefix and value.startswith(prefix):
        return value[len(prefix):]
    return value
