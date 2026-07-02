"""Subject-level table: one row per case (base fields + 1:1 demographic).

Emitted as ``{base}.subject.tsv`` — "Subject" is the KG naming convention for a
GDC case (see docs/dev_guides/kg_data_model.md). The keys stay ``case_id`` /
``case_submitter_id`` so child tables still join back on them.
"""

from ._base import Iter, data_dict, prefixed

NAME = "subject"

_BASE_FIELDS = [
    "case_id", "submitter_id",
    "disease_type", "primary_site",
    "index_date", "index_date_type",
    "project_id", "project_name", "program_name",
]

COLUMNS = [*_BASE_FIELDS, *(f"demographic_{f}" for f in data_dict("demographic"))]


def iter_rows(case: dict) -> Iter:
    proj = case.get("project") or {}
    demographic = case.get("demographic") or {}
    row = {
        "case_id":         case.get("case_id", ""),
        "submitter_id":    case.get("submitter_id", ""),
        "disease_type":    case.get("disease_type", ""),
        "primary_site":    case.get("primary_site", ""),
        "index_date":      case.get("index_date", ""),
        "index_date_type": case.get("index_date_type", ""),
        "project_id":      proj.get("project_id", ""),
        "project_name":    proj.get("name", ""),
        "program_name":    (proj.get("program") or {}).get("name", ""),
    }
    row.update(prefixed("demographic", demographic, data_dict("demographic")))
    yield row
