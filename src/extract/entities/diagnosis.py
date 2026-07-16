"""Diagnosis table: n rows per case (GDC ``diagnoses[]``)."""

from .._base import Iter, case_ident, flatten_scalars

NAME = "diagnosis"
COLUMNS = None  # discovered dynamically via emit()


def iter_rows(case: dict) -> Iter:
    ident = case_ident(case)
    for diag in (case.get("diagnoses") or []):
        row = dict(ident)
        row.update(flatten_scalars(diag))
        yield row
