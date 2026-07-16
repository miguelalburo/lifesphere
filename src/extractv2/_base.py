"""Shared helpers for extractv2 emitters.

Emitter contract (same shape as v1's _base.py):
    NAME:     str
    iter_rows(case: dict) -> Iterator[dict]

Key difference from v1: no allowlist filtering, no {entity}_ prefix on content
columns. Only the cross-entity join keys are qualified (case_id /
case_submitter_id). Nested 1:1 objects (demographic, project) are flattened
with dot notation; 1:many arrays are handled by separate entity emitters.
"""

from __future__ import annotations

from typing import Iterator

CASE_IDENT: list[str] = ["case_id", "case_submitter_id"]


def flatten_scalars(d: dict, *, prefix: str = "") -> dict:
    """Recursively flatten a dict into scalar values, skipping list fields.

    Nested dicts produce dotted keys (``demographic.age_at_index``).
    None values become empty strings.
    """
    out: dict[str, object] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten_scalars(v, prefix=key))
        elif not isinstance(v, list):
            out[key] = v if v is not None else ""
    return out


def case_ident(case: dict) -> dict:
    return {
        "case_id": case.get("case_id", ""),
        "case_submitter_id": case.get("submitter_id", ""),
    }


def emit(
    cases: list[dict],
    iter_rows_fn,
) -> tuple[list[str], list[dict]]:
    """Collect all rows from a batch of cases and discover the column union.

    Returns ``(columns, rows)`` where columns is in first-seen order with
    CASE_IDENT promoted to the front.
    """
    rows: list[dict] = [row for case in cases for row in iter_rows_fn(case)]
    seen: dict[str, None] = {}
    for row in rows:
        for k in row:
            seen[k] = None
    columns = list(seen)
    for k in reversed(CASE_IDENT):
        if k in seen:
            columns.remove(k)
            columns.insert(0, k)
    return columns, rows


Iter = Iterator[dict]
