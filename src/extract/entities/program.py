"""Program table: one row per case (standardise dedup collapses to one per program).

Emits ``case_id`` as a join key so the dedup key can be ``name`` (program name)
while the standardise engine can still link edge rows from other files.
"""

from .._base import Iter, case_ident, flatten_scalars

NAME = "program"
COLUMNS = None  # discovered dynamically via emit()


def iter_rows(case: dict) -> Iter:
    proj = case.get("project") or {}
    prog = proj.get("program") or {}
    if not prog.get("name"):
        return
    row = case_ident(case)
    row.update(flatten_scalars(prog))
    yield row
