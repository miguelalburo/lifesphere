"""Molecular-test table: n rows per case.

molecular_tests nest under BOTH ``diagnoses[]`` and ``follow_ups[]`` (e.g. TCGA
breast ER/PR/HER2 status lives under follow_ups). Each row records which parent
it came from via ``parent_entity`` ('diagnosis' | 'follow_up') and ``parent_id``.
"""

from ._base import CASE_IDENT, Iter, case_ident, prefixed

NAME = "molecular_test"

# molecular_test is not in gdc_data_dict.json because it nests under two parents;
# its fields are enumerated here.
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
    "parent_entity", "parent_id",
    "molecular_test_id", "molecular_test_submitter_id",
    *(f"molecular_test_{f}" for f in FIELDS),
]


def _row(case: dict, mt: dict, parent_entity: str, parent_id: str) -> dict:
    row = case_ident(case)
    row["parent_entity"] = parent_entity
    row["parent_id"] = parent_id
    row["molecular_test_id"] = mt.get("molecular_test_id", "")
    row["molecular_test_submitter_id"] = mt.get("submitter_id", "")
    row.update(prefixed("molecular_test", mt, FIELDS))
    return row


def iter_rows(case: dict) -> Iter:
    for diag in (case.get("diagnoses") or []):
        for mt in (diag.get("molecular_tests") or []):
            yield _row(case, mt, "diagnosis", diag.get("diagnosis_id", ""))
    for fu in (case.get("follow_ups") or []):
        for mt in (fu.get("molecular_tests") or []):
            yield _row(case, mt, "follow_up", fu.get("follow_up_id", ""))
