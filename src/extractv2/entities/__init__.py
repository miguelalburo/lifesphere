"""Registry of extractv2 per-entity emitters (basic clinical entities).

Structural emitters (Sample, Intervention, Program, Study, Survival) are
added in a follow-on ticket once the core layer is stable.
"""

from . import (
    diagnosis,
    exposure,
    follow_up,
    other_clinical_attribute,
    pathology_detail,
    subject,
)

EMITTERS = [
    subject,
    diagnosis,
    pathology_detail,
    follow_up,
    exposure,
    other_clinical_attribute,
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
