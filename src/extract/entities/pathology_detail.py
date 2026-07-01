"""Pathology-detail table: n rows per diagnosis (GDC ``diagnoses[].pathology_details[]``)."""

from ._base import Iter, child_columns, child_row

NAME = "pathology_detail"
COLUMNS = child_columns(NAME, parent_ids=["diagnosis_id"])


def iter_rows(case: dict) -> Iter:
    for diag in (case.get("diagnoses") or []):
        parent = {"diagnosis_id": diag.get("diagnosis_id", "")}
        for pd in (diag.get("pathology_details") or []):
            yield child_row(NAME, case, pd, parent)
