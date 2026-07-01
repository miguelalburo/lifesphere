"""Follow-up table: n rows per case (GDC ``follow_ups[]``)."""

from ._base import Iter, child_columns, child_row

NAME = "follow_up"
COLUMNS = child_columns(NAME)


def iter_rows(case: dict) -> Iter:
    for fu in (case.get("follow_ups") or []):
        yield child_row(NAME, case, fu)
