"""
Shared helpers for per-entity emitters.

Each entity module (case.py, diagnosis.py, aliquot.py, ...) turns one GDC case
payload into rows at that entity's *true* grain and declares the columns it
writes. The orchestrator in ``cases.py`` fetches every case once (via ``expand``)
and runs all emitters, one output TSV per entity — so 1:many entities such as
follow_ups and treatments are preserved instead of collapsed to their first
element.

Emitter contract, per module:
    NAME:    str                      -> output suffix ``{base}.{NAME}.tsv``
    COLUMNS: list[str]                -> ordered output columns
    iter_rows(case: dict) -> Iterator[dict]

Every child table starts with ``case_id`` + ``case_submitter_id`` so it can be
joined back to ``.case.tsv``; deeper tables also carry their parent ids.
"""

import json
from pathlib import Path
from typing import Iterator

_DATA_DICT: dict[str, list[str]] = json.loads(
    (Path(__file__).resolve().parents[1] / "gdc_data_dict.json").read_text()
)

# Identity columns every child row carries to link back to the case.
CASE_IDENT: list[str] = ["case_id", "case_submitter_id"]


def data_dict(entity: str) -> list[str]:
    """Content fields for an entity, minus anything we emit as an explicit id."""
    drop = {"submitter_id", f"{entity}_id"}
    return [f for f in _DATA_DICT.get(entity, []) if f not in drop]


def case_ident(case: dict) -> dict:
    return {"case_id": case.get("case_id", ""), "case_submitter_id": case.get("submitter_id", "")}


def prefixed(entity: str, item: dict, fields: list[str]) -> dict:
    """{entity}_{field}: value, for each content field."""
    return {f"{entity}_{f}": item.get(f, "") for f in fields}


def child_columns(entity: str, parent_ids: list[str] = ()) -> list[str]:
    """Standard column layout for a 1:many entity emitted from data_dict fields."""
    return [
        *CASE_IDENT,
        *parent_ids,
        f"{entity}_id",
        f"{entity}_submitter_id",
        *(f"{entity}_{f}" for f in data_dict(entity)),
    ]


def child_row(entity: str, case: dict, item: dict, parent: dict = None) -> dict:
    """Standard row for a 1:many entity: case ident + parent ids + entity id + fields."""
    row = case_ident(case)
    if parent:
        row.update(parent)
    row[f"{entity}_id"] = item.get(f"{entity}_id", "")
    row[f"{entity}_submitter_id"] = item.get("submitter_id", "")
    row.update(prefixed(entity, item, data_dict(entity)))
    return row


Iter = Iterator[dict]
