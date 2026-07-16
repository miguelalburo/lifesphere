"""Treatment (Intervention) table fanned out to aliquot grain.

Each treatment produces one row per aliquot in the case, so the KG edge
HAS_INTERVENTION can join on ``sample_id`` (aliquot id).
"""

from .._base import Iter, case_ident, flatten_scalars

NAME = "treatment"
COLUMNS = None  # discovered dynamically via emit()


def _aliquot_ids(case: dict) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for smp in case.get("samples") or []:
        for portion in smp.get("portions") or []:
            for analyte in portion.get("analytes") or []:
                for aliquot in analyte.get("aliquots") or []:
                    aid = aliquot.get("aliquot_id", "")
                    if aid and aid not in seen:
                        seen.add(aid)
                        ids.append(aid)
    return ids or [""]


def iter_rows(case: dict) -> Iter:
    ident = case_ident(case)
    aliquot_ids = _aliquot_ids(case)
    for diag in case.get("diagnoses") or []:
        diag_id = diag.get("diagnosis_id", "")
        for tx in diag.get("treatments") or []:
            tx_flat = flatten_scalars(tx)
            for aid in aliquot_ids:
                row = dict(ident)
                row["sample_id"] = aid
                row["diagnosis_id"] = diag_id
                row.update(tx_flat)
                yield row
