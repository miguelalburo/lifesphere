"""Follow-up table: n rows per case (GDC ``follow_ups[]``)."""

from .._base import Iter, case_ident, flatten_scalars

NAME = "follow_up"


def iter_rows(case: dict) -> Iter:
    ident = case_ident(case)
    for fu in (case.get("follow_ups") or []):
        row = dict(ident)
        row.update(flatten_scalars(fu))
        yield row
