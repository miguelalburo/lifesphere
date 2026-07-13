"""Treatment table: n rows per diagnosis (GDC ``diagnoses[].treatments[]``).

After the v2 re-parenting, UNDERWENT_INTERVENTION sources from Sample instead of
Diagnosis. A ``sample_id`` column is added using the case's first sample id.
"""

from ._base import Iter, child_columns, child_row

NAME = "treatment"
COLUMNS = ["sample_id", *child_columns(NAME, parent_ids=["diagnosis_id"])]


def iter_rows(case: dict) -> Iter:
    samples = case.get("samples") or []
    first_sample_id = samples[0].get("sample_id", "") if samples else ""
    for diag in (case.get("diagnoses") or []):
        parent = {"diagnosis_id": diag.get("diagnosis_id", "")}
        for tx in (diag.get("treatments") or []):
            row = child_row(NAME, case, tx, parent)
            row["sample_id"] = first_sample_id
            yield row
