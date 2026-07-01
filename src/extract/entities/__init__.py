"""
Registry of per-entity emitters.

Each module turns one GDC case payload into rows at its true grain (see _base.py).
The orchestrator fetches every case once with ``EXPAND`` and runs ``EMITTERS`` in
order, writing one ``{base}.{NAME}.tsv`` per entity.
"""

from . import (
    aliquot,
    case,
    diagnosis,
    exposure,
    family_history,
    file,
    follow_up,
    molecular_test,
    other_clinical_attribute,
    pathology_detail,
    sample,
    treatment,
)

# Emission order: case first, then clinical children, then biospecimen.
EMITTERS = [
    case,
    diagnosis,
    treatment,
    pathology_detail,
    follow_up,
    molecular_test,
    exposure,
    family_history,
    other_clinical_attribute,
    sample,
    aliquot,
    file,
]

# Nested sub-objects to pull in a single /cases fetch so every emitter can read
# its slice from the same payload.
EXPAND = [
    "project", "project.program",
    "demographic",
    "diagnoses", "diagnoses.treatments", "diagnoses.pathology_details",
    "diagnoses.molecular_tests",
    "follow_ups", "follow_ups.molecular_tests",
    "exposures", "family_histories", "other_clinical_attributes",
    "samples", "samples.portions", "samples.portions.analytes",
    "samples.portions.analytes.aliquots",
    "files",
]

__all__ = ["EMITTERS", "EXPAND"]
