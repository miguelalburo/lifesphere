"""Diagnosis table: n rows per case (GDC ``diagnoses[]``)."""

from ._base import Iter, child_columns, child_row

NAME = "diagnosis"
COLUMNS = child_columns(NAME)


def iter_rows(case: dict) -> Iter:
    for diag in (case.get("diagnoses") or []):
        yield child_row(NAME, case, diag)
