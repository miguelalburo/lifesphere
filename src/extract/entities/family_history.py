"""Family-history table: n rows per case (GDC ``family_histories[]``).

After the v2 re-parenting, HAS_PHENOTYPE_OBSERVATION sources from Diagnosis instead of
Subject. A ``diagnosis_id`` column is added using the case's first diagnosis id.
"""

from ._base import Iter, child_columns, child_row

NAME = "family_history"
COLUMNS = ["diagnosis_id", *child_columns(NAME)]


def iter_rows(case: dict) -> Iter:
    diagnoses = case.get("diagnoses") or []
    first_diag_id = diagnoses[0].get("diagnosis_id", "") if diagnoses else ""
    for fh in (case.get("family_histories") or []):
        row = child_row(NAME, case, fh)
        row["diagnosis_id"] = first_diag_id
        yield row
