"""Sample table at aliquot grain.

Each GDC aliquot becomes one row. The originating GDC sample id is preserved as
``gdc_sample_id``; the aliquot's ``aliquot_id`` becomes ``sample_id`` (matching
the KG's sampleId key).
"""

from .._base import Iter, case_ident

NAME = "sample"
COLUMNS = None  # discovered dynamically via emit()


def iter_rows(case: dict) -> Iter:
    ident = case_ident(case)
    for smp in case.get("samples") or []:
        gdc_sample_id = smp.get("sample_id", "")
        gdc_sample_submitter_id = smp.get("submitter_id", "")
        sample_scalars = {
            k: (v if v is not None else "")
            for k, v in smp.items()
            if k not in ("sample_id", "submitter_id") and not isinstance(v, (dict, list))
        }
        for portion in smp.get("portions") or []:
            for analyte in portion.get("analytes") or []:
                for aliquot in analyte.get("aliquots") or []:
                    row = dict(ident)
                    row["sample_id"] = aliquot.get("aliquot_id", "")
                    row["sample_submitter_id"] = aliquot.get("submitter_id", "")
                    row["gdc_sample_id"] = gdc_sample_id
                    row["gdc_sample_submitter_id"] = gdc_sample_submitter_id
                    row.update(sample_scalars)
                    for k, v in aliquot.items():
                        if k not in ("aliquot_id", "submitter_id") and not isinstance(v, (dict, list)):
                            row[k] = v if v is not None else ""
                    yield row
