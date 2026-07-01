"""Family-history table: n rows per case (GDC ``family_histories[]``)."""

from ._base import Iter, child_columns, child_row

NAME = "family_history"
COLUMNS = child_columns(NAME)


def iter_rows(case: dict) -> Iter:
    for fh in (case.get("family_histories") or []):
        yield child_row(NAME, case, fh)
