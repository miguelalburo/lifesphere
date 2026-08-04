"""Registry of per-entity emitters."""

from . import (
    diagnosis,
    exposure,
    follow_up,
    other_clinical_attribute,
    pathology_detail,
    program,
    sample,
    study,
    subject,
    treatment,
)

EMITTERS = [
    subject,
    diagnosis,
    pathology_detail,
    follow_up,
    exposure,
    other_clinical_attribute,
    sample,
    treatment,
    program,
    study,
]

EXPAND = [
    "project", "project.program",
    "demographic",
    "diagnoses", "diagnoses.pathology_details",
    "diagnoses.treatments",
    "follow_ups",
    "exposures",
    "other_clinical_attributes",
    "samples", "samples.portions", "samples.portions.analytes",
    "samples.portions.analytes.aliquots",
]

__all__ = ["EMITTERS", "EXPAND"]
