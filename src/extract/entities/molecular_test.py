"""Molecular-test table: n rows per case, folded into PhenotypeObservation.

molecular_tests nest under BOTH ``diagnoses[]`` and ``follow_ups[]`` (e.g. TCGA
breast ER/PR/HER2 status lives under follow_ups). After the v2 MolecularTest
retirement, each row is emitted as a PhenotypeObservation (biomarker subtype).

``diagnosis_id`` is always populated: diagnosis-nested tests use their parent
diagnosis directly; follow_up-nested tests fall back to the case's first diagnosis.
"""

from ._base import CASE_IDENT, Iter, case_ident, prefixed

NAME = "molecular_test"

FIELDS = [
    "gene_symbol", "molecular_analysis_method", "test_result",
    "aa_change", "aneuploidy", "antigen", "biospecimen_type", "biospecimen_volume",
    "blood_test_normal_range_lower", "blood_test_normal_range_upper", "cell_count",
    "chromosomal_translocation", "chromosome", "chromosome_arm", "clonality",
    "copy_number", "cytoband", "days_to_test", "exon", "histone_family",
    "histone_variant", "hpv_strain", "intron", "laboratory_test",
    "loci_abnormal_count", "loci_count", "locus", "mismatch_repair_mutation",
    "mitotic_count", "mitotic_total_area", "molecular_consequence", "mutation_codon",
    "pathogenicity", "ploidy", "second_exon", "second_gene_symbol",
    "specialized_molecular_test", "staining_intensity_scale", "staining_intensity_value",
    "test_analyte_type", "test_units", "test_value", "test_value_range",
    "timepoint_category", "transcript", "variant_origin", "variant_type", "zygosity",
]

COLUMNS = [
    *CASE_IDENT,
    "parent_entity", "parent_id", "diagnosis_id",
    "molecular_test_id", "molecular_test_submitter_id",
    "molecular_test_subtype",
    *(f"molecular_test_{f}" for f in FIELDS),
]


def _row(case: dict, mt: dict, parent_entity: str, parent_id: str, diagnosis_id: str) -> dict:
    row = case_ident(case)
    row["parent_entity"] = parent_entity
    row["parent_id"] = parent_id
    row["diagnosis_id"] = diagnosis_id
    row["molecular_test_id"] = mt.get("molecular_test_id", "")
    row["molecular_test_submitter_id"] = mt.get("submitter_id", "")
    row["molecular_test_subtype"] = "biomarker"
    row.update(prefixed("molecular_test", mt, FIELDS))
    return row


def iter_rows(case: dict) -> Iter:
    diagnoses = case.get("diagnoses") or []
    first_diag_id = diagnoses[0].get("diagnosis_id", "") if diagnoses else ""

    for diag in diagnoses:
        diag_id = diag.get("diagnosis_id", "")
        for mt in (diag.get("molecular_tests") or []):
            yield _row(case, mt, "diagnosis", diag_id, diag_id)

    for fu in (case.get("follow_ups") or []):
        for mt in (fu.get("molecular_tests") or []):
            yield _row(case, mt, "follow_up", fu.get("follow_up_id", ""), first_diag_id)
