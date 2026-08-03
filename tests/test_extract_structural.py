"""extract structural operations: Sample (aliquot-grain), Intervention (fan-out),
Program, Study, Survival derivation.
"""

from __future__ import annotations

from src.extract.entities import program, sample, study, survival, treatment

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


# ---------------------------------------------------------------------------
# Survival — OS/DSS/PFI/DFI derivation
# ---------------------------------------------------------------------------

class TestSurvival:
    def test_four_outcome_rows_per_case(self):
        rows = list(survival.iter_rows(CASE))
        types = {r["survival_type"] for r in rows}
        assert types == {"OS", "DSS", "PFI", "DFI"}

    def test_os_event_and_time(self):
        rows = {r["survival_type"]: r for r in survival.iter_rows(CASE)}
        os = rows["OS"]
        assert os["event"] == 1      # dead
        assert os["time_days"] == 500  # days_to_death
        assert os["survival_id"] == "case-001:OS"

    def test_dss_event_when_cancer_related(self):
        rows = {r["survival_type"]: r for r in survival.iter_rows(CASE)}
        dss = rows["DSS"]
        assert dss["event"] == 1
        assert dss["time_days"] == 500
        assert dss["survival_id"] == "case-001:DSS"

    def test_dss_censored_when_not_cancer_related(self):
        case = {**CASE, "demographic": {**CASE["demographic"],
                                         "cause_of_death": "Not Cancer Related"}}
        rows = {r["survival_type"]: r for r in survival.iter_rows(case)}
        dss = rows["DSS"]
        assert dss["event"] == 0
        assert dss["time_days"] == 500

    def test_dss_event_when_cause_unknown_or_blank(self):
        for cause in ("Unknown", "Not Reported", "", None):
            demographic = dict(CASE["demographic"])
            if cause is None:
                demographic.pop("cause_of_death", None)
            else:
                demographic["cause_of_death"] = cause
            case = {**CASE, "demographic": demographic}
            rows = {r["survival_type"]: r for r in survival.iter_rows(case)}
            assert rows["DSS"]["event"] == 1, f"cause_of_death={cause!r}"
            assert rows["DSS"]["time_days"] == 500

    def test_dss_censored_at_contact_when_alive(self):
        case = {
            **EMPTY_CASE,
            "demographic": {"vital_status": "Alive"},
            "follow_ups": [{"days_to_follow_up": "300"}],
        }
        rows = {r["survival_type"]: r for r in survival.iter_rows(case)}
        assert rows["DSS"]["event"] == 0
        assert rows["DSS"]["time_days"] == 300

    def test_pfi_censored_when_no_progression(self):
        rows = {r["survival_type"]: r for r in survival.iter_rows(CASE)}
        pfi = rows["PFI"]
        assert pfi["event"] == 0
        assert pfi["time_days"] == 480  # last contact

    def test_dfi_censored_when_no_recurrence(self):
        rows = {r["survival_type"]: r for r in survival.iter_rows(CASE)}
        dfi = rows["DFI"]
        assert dfi["event"] == 0
        assert dfi["time_days"] == 480

    def test_join_keys_present(self):
        for row in survival.iter_rows(CASE):
            assert row["case_id"] == "case-001"
            assert row["case_submitter_id"] == "TCGA-AA-1234"

    def test_deterministic_survival_id(self):
        row_ids = {r["survival_id"] for r in survival.iter_rows(CASE)}
        assert row_ids == {"case-001:OS", "case-001:DSS", "case-001:PFI", "case-001:DFI"}

    def test_no_survival_rows_when_no_contact_or_death(self):
        # no demographic and no follow_ups → no time reference → no rows
        case = {"case_id": "c3", "submitter_id": "S3"}
        rows = list(survival.iter_rows(case))
        assert rows == []

    def test_survival_event_when_progression(self):
        case = {
            **EMPTY_CASE,
            "demographic": {"vital_status": "Alive"},
            "follow_ups": [{"days_to_follow_up": "300",
                            "days_to_progression": "200",
                            "days_to_recurrence": None,
                            "progression_or_recurrence": "Yes"}],
        }
        rows = {r["survival_type"]: r for r in survival.iter_rows(case)}
        assert rows["PFI"]["event"] == 1
        assert rows["PFI"]["time_days"] == 200
