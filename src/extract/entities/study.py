"""Study (project) table: one row per case (dedup collapses to one per project).

Includes ``program_name`` so the HAS_STUDY edge (Program → Study) can be built
from this file alone without a join.
"""

from .._base import Iter, case_ident

NAME = "study"
COLUMNS = None  # discovered dynamically via emit()


def iter_rows(case: dict) -> Iter:
    proj = case.get("project") or {}
    proj_id = proj.get("project_id", "")
    if not proj_id:
        return
    row = case_ident(case)
    row["project_id"] = proj_id
    row["project_name"] = proj.get("name", "")
    row["program_name"] = (proj.get("program") or {}).get("name", "")
    for k, v in proj.items():
        if k in ("project_id", "name", "program") or isinstance(v, (dict, list)):
            continue
        row[k] = v if v is not None else ""
    yield row
