"""Treatment table: n rows per diagnosis (GDC ``diagnoses[].treatments[]``).

Linked to its parent diagnosis via ``diagnosis_id`` — the old extractor kept only
``diagnoses[0].treatments[0]``, dropping >90% of treatments per case.
"""

from ._base import Iter, child_columns, child_row

NAME = "treatment"
COLUMNS = child_columns(NAME, parent_ids=["diagnosis_id"])


def iter_rows(case: dict) -> Iter:
    for diag in (case.get("diagnoses") or []):
        parent = {"diagnosis_id": diag.get("diagnosis_id", "")}
        for tx in (diag.get("treatments") or []):
            yield child_row(NAME, case, tx, parent)
