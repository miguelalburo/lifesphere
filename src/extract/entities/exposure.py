"""Exposure table: n rows per case (GDC ``exposures[]``)."""

from ._base import Iter, child_columns, child_row

NAME = "exposure"
COLUMNS = child_columns(NAME)


def iter_rows(case: dict) -> Iter:
    for exp in (case.get("exposures") or []):
        yield child_row(NAME, case, exp)
