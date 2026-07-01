"""Sample table: n rows per case (GDC ``samples[]``)."""

from ._base import CASE_IDENT, Iter, case_ident

NAME = "sample"

FIELDS = [
    "sample_type", "tissue_type", "tumor_descriptor", "specimen_type",
    "preservation_method", "days_to_collection", "days_to_sample_procurement",
]

COLUMNS = [*CASE_IDENT, "sample_id", "sample_submitter_id", *(f"sample_{f}" for f in FIELDS)]


def iter_rows(case: dict) -> Iter:
    for s in (case.get("samples") or []):
        row = case_ident(case)
        row["sample_id"] = s.get("sample_id", "")
        row["sample_submitter_id"] = s.get("submitter_id", "")
        row.update({f"sample_{f}": s.get(f, "") for f in FIELDS})
        yield row
