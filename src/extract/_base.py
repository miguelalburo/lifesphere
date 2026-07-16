"""Shared helpers for per-entity emitters."""

from __future__ import annotations

from typing import Callable, Iterator

Iter = Iterator[dict]

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
    iter_rows_fn: Callable[[dict], Iter],
) -> tuple[list[str], list[dict]]:
    """Collect all rows from a batch of cases and discover the column union.

    Returns ``(columns, rows)`` with CASE_IDENT promoted to the front.
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
