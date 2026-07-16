"""Exposure table: n rows per case (GDC ``exposures[]``).

Carries the first diagnosis's id as ``diagnosis_id`` so the
HAS_PHENOTYPE_OBSERVATION edge can link to Diagnosis instead of Subject.
"""

from .._base import Iter, case_ident, flatten_scalars

NAME = "exposure"
COLUMNS = None  # discovered dynamically via emit()


def iter_rows(case: dict) -> Iter:
    ident = case_ident(case)
    diagnoses = case.get("diagnoses") or []
    first_diag_id = diagnoses[0].get("diagnosis_id", "") if diagnoses else ""
    for exp in (case.get("exposures") or []):
        row = dict(ident)
        row["diagnosis_id"] = first_diag_id
        row.update(flatten_scalars(exp))
        yield row
