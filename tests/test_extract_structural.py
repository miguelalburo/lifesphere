"""extract structural operations: Sample (aliquot-grain), Intervention (fan-out),
Program, Study, Survival derivation.
"""

from __future__ import annotations

from src.extract.entities import program, sample, study, treatment

# ---------------------------------------------------------------------------
# Shared synthetic payload
# ---------------------------------------------------------------------------

CASE = {
    "case_id": "case-001",
    "submitter_id": "TCGA-AA-1234",
    "disease_type": "Adenomas and Adenocarcinomas",
    "primary_site": "Colon",
    "project": {
        "project_id": "TCGA-COAD",
        "name": "TCGA Colon Adenocarcinoma",
        "disease_type": "Adenomas and Adenocarcinomas",
        "primary_site": "Colon",
        "program": {"name": "TCGA", "program_id": "pgm-001"},
    },
    "demographic": {
        "vital_status": "Dead",
        "days_to_death": "500",
        "cause_of_death": "Cancer Related",
    },
    "diagnoses": [
        {
            "diagnosis_id": "diag-001",
            "primary_diagnosis": "Adenocarcinoma, NOS",
            "days_to_last_follow_up": "480",
            "treatments": [
                {
                    "treatment_id": "tx-001",
                    "therapeutic_agents": "FOLFOX",
                    "treatment_type": "Chemotherapy",
                },
            ],
        }
    ],
    "follow_ups": [
        {
            "follow_up_id": "fu-001",
            "days_to_follow_up": "480",
            "days_to_progression": None,
            "days_to_recurrence": None,
            "progression_or_recurrence": "No",
        }
    ],
    "samples": [
        {
            "sample_id": "s-001",
            "submitter_id": "TCGA-AA-1234-01",
            "sample_type": "Primary Tumor",
            "tissue_type": "Tumor",
            "portions": [
                {
                    "portion_id": "p-001",
                    "analytes": [
                        {
                            "analyte_id": "an-001",
                            "analyte_type": "DNA",
                            "aliquots": [
                                {"aliquot_id": "al-001", "submitter_id": "TCGA-AA-1234-01D"},
                                {"aliquot_id": "al-002", "submitter_id": "TCGA-AA-1234-01R"},
                            ],
                        }
                    ],
                }
            ],
        }
    ],
}

EMPTY_CASE = {"case_id": "c2", "submitter_id": "TCGA-BB-0000"}


# ---------------------------------------------------------------------------
# Sample — aliquot-grain collapse
# ---------------------------------------------------------------------------

class TestSample:
    def test_one_row_per_aliquot(self):
        rows = list(sample.iter_rows(CASE))
        assert len(rows) == 2

    def test_aliquot_id_becomes_sample_id(self):
        rows = list(sample.iter_rows(CASE))
        assert rows[0]["sample_id"] == "al-001"
        assert rows[1]["sample_id"] == "al-002"

    def test_originating_gdc_sample_id_preserved(self):
        row = list(sample.iter_rows(CASE))[0]
        assert row["gdc_sample_id"] == "s-001"
        assert row["gdc_sample_submitter_id"] == "TCGA-AA-1234-01"

    def test_sample_level_fields_on_every_aliquot(self):
        for row in sample.iter_rows(CASE):
            assert row["sample_type"] == "Primary Tumor"
            assert row["tissue_type"] == "Tumor"

    def test_join_keys_present(self):
        for row in sample.iter_rows(CASE):
            assert row["case_id"] == "case-001"
            assert row["case_submitter_id"] == "TCGA-AA-1234"

    def test_no_rows_when_no_samples(self):
        assert list(sample.iter_rows(EMPTY_CASE)) == []


# ---------------------------------------------------------------------------
# Treatment — fan-out to aliquot grain
# ---------------------------------------------------------------------------

class TestTreatment:
    def test_one_row_per_treatment_per_aliquot(self):
        rows = list(treatment.iter_rows(CASE))
        # 1 treatment × 2 aliquots = 2 rows
        assert len(rows) == 2

    def test_sample_id_is_aliquot_id(self):
        rows = list(treatment.iter_rows(CASE))
        aliquot_ids = {r["sample_id"] for r in rows}
        assert aliquot_ids == {"al-001", "al-002"}

    def test_diagnosis_id_carried(self):
        for row in treatment.iter_rows(CASE):
            assert row["diagnosis_id"] == "diag-001"

    def test_true_column_names(self):
        row = list(treatment.iter_rows(CASE))[0]
        assert row["therapeutic_agents"] == "FOLFOX"
        assert row["treatment_type"] == "Chemotherapy"
        assert "treatment_therapeutic_agents" not in row

    def test_join_keys_present(self):
        for row in treatment.iter_rows(CASE):
            assert row["case_id"] == "case-001"

    def test_no_rows_when_no_treatments(self):
        case = {**EMPTY_CASE, "diagnoses": [{"diagnosis_id": "d1", "treatments": []}]}
        assert list(treatment.iter_rows(case)) == []


# ---------------------------------------------------------------------------
# Program — one row per case (dedup in standardise collapses to one per program)
# ---------------------------------------------------------------------------

class TestProgram:
    def test_one_row_per_case(self):
        rows = list(program.iter_rows(CASE))
        assert len(rows) == 1

    def test_program_name_present(self):
        row = list(program.iter_rows(CASE))[0]
        assert row["name"] == "TCGA"

    def test_join_keys_present(self):
        row = list(program.iter_rows(CASE))[0]
        assert row["case_id"] == "case-001"

    def test_no_rows_when_no_program(self):
        case = {**EMPTY_CASE, "project": {"project_id": "P1"}}
        assert list(program.iter_rows(case)) == []


# ---------------------------------------------------------------------------
# Study — one row per case (dedup collapses to one per project)
# ---------------------------------------------------------------------------

class TestStudy:
    def test_one_row_per_case(self):
        rows = list(study.iter_rows(CASE))
        assert len(rows) == 1

    def test_project_fields_present(self):
        row = list(study.iter_rows(CASE))[0]
        assert row["project_id"] == "TCGA-COAD"
        assert row["project_name"] == "TCGA Colon Adenocarcinoma"

    def test_program_name_carried(self):
        # needed for HAS_STUDY edge (Program -> Study)
        row = list(study.iter_rows(CASE))[0]
        assert row["program_name"] == "TCGA"

    def test_join_keys_present(self):
        row = list(study.iter_rows(CASE))[0]
        assert row["case_id"] == "case-001"

    def test_no_rows_when_no_project(self):
        assert list(study.iter_rows(EMPTY_CASE)) == []


