"""Aliquot table: one row per aliquot (n rows per case).

Walks the full TCGA biospecimen hierarchy
``samples[] -> portions[] -> analytes[] -> aliquots[]`` and keeps every id on the
path, so the many aliquots of a case collapse cleanly back to their few samples
(e.g. 113 aliquots -> 2 samples) via ``sample_id``.
"""

from ._base import CASE_IDENT, Iter, case_ident

NAME = "aliquot"

COLUMNS = [
    *CASE_IDENT,
    "sample_id", "sample_type",
    "portion_id",
    "analyte_id", "analyte_type",
    "aliquot_id", "aliquot_submitter_id",
]


def iter_rows(case: dict) -> Iter:
    for sample in (case.get("samples") or []):
        sid = sample.get("sample_id", "")
        stype = sample.get("sample_type", "")
        for portion in (sample.get("portions") or []):
            pid = portion.get("portion_id", "")
            for analyte in (portion.get("analytes") or []):
                aid = analyte.get("analyte_id", "")
                atype = analyte.get("analyte_type", "")
                for aliquot in (analyte.get("aliquots") or []):
                    row = case_ident(case)
                    row.update({
                        "sample_id": sid,
                        "sample_type": stype,
                        "portion_id": pid,
                        "analyte_id": aid,
                        "analyte_type": atype,
                        "aliquot_id": aliquot.get("aliquot_id", ""),
                        "aliquot_submitter_id": aliquot.get("submitter_id", ""),
                    })
                    yield row
