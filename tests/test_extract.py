"""extract core emit layer — pure emission over GDC case-payload dicts.

Covers: full-field emission, true GDC column names (no {entity}_ prefix),
qualified join keys (case_id / case_submitter_id), correct grain, and the
emit() column-discovery helper.
"""

from __future__ import annotations

import pytest

from src.extract._base import CASE_IDENT, emit
from src.extract.entities import (
    diagnosis,
    exposure,
    follow_up,
    other_clinical_attribute,
    pathology_detail,
    subject,
)

# ---------------------------------------------------------------------------
# Shared synthetic payload
# ---------------------------------------------------------------------------

CASE = {
    "case_id": "case-001",
    "submitter_id": "TCGA-AA-1234",
    "disease_type": "Adenomas and Adenocarcinomas",
    "primary_site": "Colon",
    "index_date": "2010-01-01",
    "project": {
        "project_id": "TCGA-COAD",
        "name": "TCGA Colon Adenocarcinoma",
        "program": {
            "name": "TCGA",
            "program_id": "pgm-001",
        },
    },
    "demographic": {
        "gender": "female",
        "age_at_index": 45,
        "race": "white",
    },
    "diagnoses": [
        {
            "diagnosis_id": "diag-001",
            "submitter_id": "TCGA-AA-1234-D1",
            "primary_diagnosis": "Adenocarcinoma, NOS",
            "icd_10_code": "C18.9",
            "morphology": "8140/3",
            "tumor_grade": "G2",
            "pathology_details": [
                {
                    "pathology_detail_id": "pd-001",
                    "submitter_id": "TCGA-AA-1234-PD1",
                    "breslow_thickness": "1.2",
                }
            ],
        },
        {
            "diagnosis_id": "diag-002",
            "submitter_id": "TCGA-AA-1234-D2",
            "primary_diagnosis": "Recurrence",
            "tumor_grade": "G3",
            "pathology_details": [],
        },
    ],
    "exposures": [
        {
            "exposure_id": "exp-001",
            "submitter_id": "TCGA-AA-1234-E1",
            "cigarettes_per_day": "10",
            "alcohol_history": "Yes",
        }
    ],
    "follow_ups": [
        {
            "follow_up_id": "fu-001",
            "submitter_id": "TCGA-AA-1234-F1",
            "days_to_follow_up": "365",
            "vital_status": "Alive",
        }
    ],
    "other_clinical_attributes": [
        {
            "other_clinical_attribute_id": "oca-001",
            "submitter_id": "TCGA-AA-1234-OCA1",
            "bmi": "25.0",
        }
    ],
}

EMPTY_CASE = {"case_id": "c2", "submitter_id": "TCGA-BB-0000"}


# ---------------------------------------------------------------------------
# Subject (case-level)
# ---------------------------------------------------------------------------

class TestSubject:
    def test_one_row_per_case(self):
        rows = list(subject.iter_rows(CASE))
        assert len(rows) == 1

    def test_join_keys_present(self):
        row = list(subject.iter_rows(CASE))[0]
        assert row["case_id"] == "case-001"
        assert row["case_submitter_id"] == "TCGA-AA-1234"

    def test_case_level_fields_present(self):
        row = list(subject.iter_rows(CASE))[0]
        assert row["disease_type"] == "Adenomas and Adenocarcinomas"
        assert row["primary_site"] == "Colon"
        assert row["index_date"] == "2010-01-01"

    def test_nested_demographic_flattened(self):
        row = list(subject.iter_rows(CASE))[0]
        assert row["demographic.gender"] == "female"
        assert row["demographic.age_at_index"] == 45
        assert row["demographic.race"] == "white"

    def test_nested_project_flattened(self):
        row = list(subject.iter_rows(CASE))[0]
        assert row["project.project_id"] == "TCGA-COAD"
        assert row["project.program.name"] == "TCGA"

    def test_no_entity_prefix(self):
        row = list(subject.iter_rows(CASE))[0]
        assert not any(k.startswith("subject_") for k in row)

    def test_lists_not_in_row(self):
        row = list(subject.iter_rows(CASE))[0]
        for key in ("diagnoses", "exposures", "follow_ups", "other_clinical_attributes"):
            assert key not in row

    def test_empty_case(self):
        rows = list(subject.iter_rows(EMPTY_CASE))
        assert len(rows) == 1
        row = rows[0]
        assert row["case_id"] == "c2"
        assert row["case_submitter_id"] == "TCGA-BB-0000"


# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------

class TestDiagnosis:
    def test_one_row_per_diagnosis(self):
        rows = list(diagnosis.iter_rows(CASE))
        assert len(rows) == 2

    def test_join_keys_on_each_row(self):
        for row in diagnosis.iter_rows(CASE):
            assert row["case_id"] == "case-001"
            assert row["case_submitter_id"] == "TCGA-AA-1234"

    def test_true_gdc_column_names(self):
        row = list(diagnosis.iter_rows(CASE))[0]
        # true GDC name — no "diagnosis_" prefix
        assert row["primary_diagnosis"] == "Adenocarcinoma, NOS"
        assert row["icd_10_code"] == "C18.9"
        assert row["morphology"] == "8140/3"
        assert row["tumor_grade"] == "G2"
        assert "diagnosis_primary_diagnosis" not in row

    def test_diagnosis_id_present(self):
        rows = list(diagnosis.iter_rows(CASE))
        assert rows[0]["diagnosis_id"] == "diag-001"
        assert rows[1]["diagnosis_id"] == "diag-002"

    def test_pathology_details_list_excluded(self):
        for row in diagnosis.iter_rows(CASE):
            assert "pathology_details" not in row

    def test_no_rows_when_no_diagnoses(self):
        assert list(diagnosis.iter_rows(EMPTY_CASE)) == []


# ---------------------------------------------------------------------------
# PathologyDetail
# ---------------------------------------------------------------------------

class TestPathologyDetail:
    def test_grain_one_row_per_pathology_detail(self):
        rows = list(pathology_detail.iter_rows(CASE))
        # only diag-001 has a pathology_detail; diag-002 has none
        assert len(rows) == 1

    def test_carries_case_and_diagnosis_id(self):
        row = list(pathology_detail.iter_rows(CASE))[0]
        assert row["case_id"] == "case-001"
        assert row["case_submitter_id"] == "TCGA-AA-1234"
        assert row["diagnosis_id"] == "diag-001"

    def test_true_column_names(self):
        row = list(pathology_detail.iter_rows(CASE))[0]
        assert row["breslow_thickness"] == "1.2"
        assert "pathology_detail_breslow_thickness" not in row

    def test_no_rows_when_no_diagnoses(self):
        assert list(pathology_detail.iter_rows(EMPTY_CASE)) == []


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------

class TestExposure:
    def test_one_row_per_exposure(self):
        rows = list(exposure.iter_rows(CASE))
        assert len(rows) == 1

    def test_carries_case_and_first_diagnosis_id(self):
        row = list(exposure.iter_rows(CASE))[0]
        assert row["case_id"] == "case-001"
        assert row["case_submitter_id"] == "TCGA-AA-1234"
        assert row["diagnosis_id"] == "diag-001"

    def test_true_column_names(self):
        row = list(exposure.iter_rows(CASE))[0]
        assert row["cigarettes_per_day"] == "10"
        assert row["alcohol_history"] == "Yes"
        assert "exposure_cigarettes_per_day" not in row

    def test_empty_diagnosis_id_when_no_diagnoses(self):
        case = {**EMPTY_CASE, "exposures": [{"exposure_id": "e1", "cigarettes_per_day": "5"}]}
        row = list(exposure.iter_rows(case))[0]
        assert row["diagnosis_id"] == ""

    def test_no_rows_when_no_exposures(self):
        assert list(exposure.iter_rows(EMPTY_CASE)) == []


# ---------------------------------------------------------------------------
# FollowUp
# ---------------------------------------------------------------------------

class TestFollowUp:
    def test_one_row_per_follow_up(self):
        rows = list(follow_up.iter_rows(CASE))
        assert len(rows) == 1

    def test_join_keys_present(self):
        row = list(follow_up.iter_rows(CASE))[0]
        assert row["case_id"] == "case-001"
        assert row["case_submitter_id"] == "TCGA-AA-1234"

    def test_true_column_names(self):
        row = list(follow_up.iter_rows(CASE))[0]
        assert row["days_to_follow_up"] == "365"
        assert row["vital_status"] == "Alive"
        assert "follow_up_days_to_follow_up" not in row

    def test_no_rows_when_no_follow_ups(self):
        assert list(follow_up.iter_rows(EMPTY_CASE)) == []


# ---------------------------------------------------------------------------
# OtherClinicalAttribute
# ---------------------------------------------------------------------------

class TestOtherClinicalAttribute:
    def test_one_row_per_attribute(self):
        rows = list(other_clinical_attribute.iter_rows(CASE))
        assert len(rows) == 1

    def test_join_keys_and_true_names(self):
        row = list(other_clinical_attribute.iter_rows(CASE))[0]
        assert row["case_id"] == "case-001"
        assert row["bmi"] == "25.0"
        assert "other_clinical_attribute_bmi" not in row

    def test_no_rows_when_absent(self):
        assert list(other_clinical_attribute.iter_rows(EMPTY_CASE)) == []


# ---------------------------------------------------------------------------
# emit() helper — column discovery
# ---------------------------------------------------------------------------

class TestEmit:
    def test_case_ident_columns_come_first(self):
        cols, _ = emit([CASE], subject.iter_rows)
        assert cols[0] == "case_id"
        assert cols[1] == "case_submitter_id"

    def test_column_union_across_cases(self):
        case1 = {"case_id": "c1", "submitter_id": "s1", "disease_type": "T1"}
        case2 = {"case_id": "c2", "submitter_id": "s2", "primary_site": "Colon"}
        cols, rows = emit([case1, case2], subject.iter_rows)
        assert "disease_type" in cols
        assert "primary_site" in cols
        assert len(rows) == 2

    def test_empty_cases_list(self):
        cols, rows = emit([], subject.iter_rows)
        assert rows == []
        assert cols == []

    def test_diagnosis_emit_grain(self):
        cols, rows = emit([CASE], diagnosis.iter_rows)
        assert len(rows) == 2  # two diagnoses in CASE
        assert cols[0] == "case_id"
        assert "primary_diagnosis" in cols

    def test_no_duplicate_columns(self):
        cols, _ = emit([CASE, CASE], subject.iter_rows)
        assert len(cols) == len(set(cols))
