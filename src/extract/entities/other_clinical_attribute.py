"""Other-clinical-attribute table: n rows per case (GDC ``other_clinical_attributes[]``)."""

from .._base import Iter, case_ident, flatten_scalars

NAME = "other_clinical_attribute"
COLUMNS = None  # discovered dynamically via emit()


def iter_rows(case: dict) -> Iter:
    ident = case_ident(case)
    for oca in (case.get("other_clinical_attributes") or []):
        row = dict(ident)
        row.update(flatten_scalars(oca))
        yield row
