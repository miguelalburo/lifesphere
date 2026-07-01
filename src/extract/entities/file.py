"""File table: n rows per case (GDC ``files[]``)."""

from ._base import CASE_IDENT, Iter, case_ident

NAME = "file"

FIELDS = [
    "file_name", "data_type", "data_category", "data_format",
    "experimental_strategy", "platform", "access", "file_size",
]

COLUMNS = [*CASE_IDENT, "file_id", "file_submitter_id", *(f"file_{f}" for f in FIELDS)]


def iter_rows(case: dict) -> Iter:
    for fl in (case.get("files") or []):
        row = case_ident(case)
        row["file_id"] = fl.get("file_id", "")
        row["file_submitter_id"] = fl.get("submitter_id", "")
        row.update({f"file_{f}": fl.get(f, "") for f in FIELDS})
        yield row
