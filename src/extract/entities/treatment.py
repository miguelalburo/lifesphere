"""Treatment table: n rows per (diagnosis × aliquot) (GDC ``diagnoses[].treatments[]``).

UNDERWENT_INTERVENTION sources from Sample at aliquot grain. Each treatment row is
fanned out to every aliquot of the subject so the edge is enforced at aliquot level.
The same fan-out is applied post-hoc by ``biospecimen.merge_treatment_sample`` when
processing an existing extract without re-downloading.
"""

from ._base import Iter, child_columns, child_row

NAME = "treatment"
COLUMNS = ["sample_id", *child_columns(NAME, parent_ids=["diagnosis_id"])]


def _aliquot_ids(case: dict) -> list[str]:
    """Collect all aliquot_ids from the case's biospecimen hierarchy, deduplicated."""
    seen: set[str] = set()
    ids: list[str] = []
    for sample in (case.get("samples") or []):
        for portion in (sample.get("portions") or []):
            for analyte in (portion.get("analytes") or []):
                for aliquot in (analyte.get("aliquots") or []):
                    aid = aliquot.get("aliquot_id", "")
                    if aid and aid not in seen:
                        seen.add(aid)
                        ids.append(aid)
    return ids or [""]


def iter_rows(case: dict) -> Iter:
    aliquot_ids = _aliquot_ids(case)
    for diag in (case.get("diagnoses") or []):
        parent = {"diagnosis_id": diag.get("diagnosis_id", "")}
        for tx in (diag.get("treatments") or []):
            base_row = child_row(NAME, case, tx, parent)
            for aid in aliquot_ids:
                row = dict(base_row)
                row["sample_id"] = aid
                yield row
