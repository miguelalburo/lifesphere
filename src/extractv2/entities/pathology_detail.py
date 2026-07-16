"""Pathology-detail table: n rows per diagnosis (GDC ``diagnoses[].pathology_details[]``)."""

from .._base import Iter, case_ident, flatten_scalars

NAME = "pathology_detail"


def iter_rows(case: dict) -> Iter:
    ident = case_ident(case)
    for diag in (case.get("diagnoses") or []):
        diag_id = diag.get("diagnosis_id", "")
        for pd in (diag.get("pathology_details") or []):
            row = dict(ident)
            row["diagnosis_id"] = diag_id
            row.update(flatten_scalars(pd))
            yield row
