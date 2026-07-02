"""Sample table: n rows per case (GDC ``samples[]``)."""

from ._base import CASE_IDENT, Iter, case_ident

NAME = "sample"

FIELDS = [
    "sample_type", "tissue_type", "tumor_descriptor", "specimen_type",
    "preservation_method", "days_to_collection", "days_to_sample_procurement",
]

COLUMNS = [*CASE_IDENT, "sample_id", "sample_submitter_id",
           "group_id", "group_label", *(f"sample_{f}" for f in FIELDS)]


def experimental_group(sample_type: str) -> tuple[str, str]:
    """Coarse control|treatment arm from GDC ``sample_type``.

    Tumour specimens are the treatment arm; normal/control tissue and blood
    normals are the control arm. Returns ``(group_id, group_label)``.
    """
    is_tumour = "tumor" in (sample_type or "").lower()
    return ("treatment", "Tumour") if is_tumour else ("control", "Normal/Control")


def iter_rows(case: dict) -> Iter:
    for s in (case.get("samples") or []):
        row = case_ident(case)
        row["sample_id"] = s.get("sample_id", "")
        row["sample_submitter_id"] = s.get("submitter_id", "")
        row["group_id"], row["group_label"] = experimental_group(s.get("sample_type", ""))
        row.update({f"sample_{f}": s.get(f, "") for f in FIELDS})
        yield row
