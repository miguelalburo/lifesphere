"""Subject (case-level) table: one row per case.

Emits all scalar case-level fields under their true GDC names, plus 1:1
nested objects (demographic, project/program) flattened with dot notation.
1:many arrays (diagnoses, exposures, …) are handled by separate emitters.
"""

from .._base import Iter, case_ident, flatten_scalars

NAME = "subject"

_NESTED_1_1 = frozenset({"demographic", "project"})


def iter_rows(case: dict) -> Iter:
    row = dict(case_ident(case))
    for k, v in case.items():
        if k in ("case_id", "submitter_id"):
            continue
        if isinstance(v, list):
            continue
        if isinstance(v, dict) and k in _NESTED_1_1:
            row.update(flatten_scalars(v, prefix=k))
        elif isinstance(v, dict):
            pass  # skip unrecognised nested objects (e.g. annotations)
        else:
            row[k] = v if v is not None else ""
    yield row
