"""Exposure table: n rows per case (GDC ``exposures[]``).

After the v2 re-parenting, HAS_PHENOTYPE_OBSERVATION sources from Diagnosis instead of
Subject. A ``diagnosis_id`` column is added using the case's first diagnosis id.
"""

from ._base import Iter, child_columns, child_row

NAME = "exposure"
COLUMNS = ["diagnosis_id", *child_columns(NAME)]


def iter_rows(case: dict) -> Iter:
    diagnoses = case.get("diagnoses") or []
    first_diag_id = diagnoses[0].get("diagnosis_id", "") if diagnoses else ""
    for exp in (case.get("exposures") or []):
        row = child_row(NAME, case, exp)
        row["diagnosis_id"] = first_diag_id
        yield row
