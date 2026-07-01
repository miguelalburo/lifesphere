"""Other-clinical-attribute table: n rows per case (GDC ``other_clinical_attributes[]``)."""

from ._base import Iter, child_columns, child_row

NAME = "other_clinical_attribute"
COLUMNS = child_columns(NAME)


def iter_rows(case: dict) -> Iter:
    for oca in (case.get("other_clinical_attributes") or []):
        yield child_row(NAME, case, oca)
