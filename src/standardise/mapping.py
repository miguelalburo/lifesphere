"""Declarative mapping: raw per-entity TSVs -> KG node/edge CSVs.

Encodes the model in docs/dev_guides/kg_data_model.md. The extraction grain already
equals the graph grain, so standardisation only selects, renames and cleans columns —
it never re-pivots.

Rules applied by ``run.py``:
- **Rename**: a property column is stripped of ``strip_prefix`` when it starts with it
  (``diagnosis_ajcc_pathologic_stage -> ajcc_pathologic_stage``,
  ``demographic_sex_at_birth -> sex_at_birth``).
- **Node vs property**: 1:1 entities are folded in as properties upstream (demographic
  is already columns on ``case``); 1:many entities are their own node specs here.
- **Linkage columns** (case_id, parent ids) are dropped from node properties — they
  drive the edges instead.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeSpec:
    label: str            # graph label / input_label (e.g. "Subject")
    source: str           # entity name -> reads {base}.{source}.tsv
    id_col: str           # source column used as the node id
    strip_prefix: str = ""     # stripped from property names when present
    drop: tuple = ()           # source columns excluded from properties (linkage cols)
    keep: tuple = ()           # if set, ONLY these source columns become properties
    dedup: bool = False        # collapse repeated ids (Program/Project repeat per case)


@dataclass(frozen=True)
class EdgeSpec:
    label: str            # edge input_label (e.g. "HAS_DIAGNOSIS")
    source: str           # entity name -> reads {base}.{source}.tsv
    source_id: str        # column holding the parent node id
    target_id: str        # column holding the child node id
    dedup: bool = False


# ─────────────────────────────── Nodes ───────────────────────────────
# Child specs share the pattern: id = {entity}_id, strip the {entity}_ prefix,
# drop case/parent linkage columns.

_CHILD_DROP = ("case_id", "case_submitter_id")

NODE_SPECS: list[NodeSpec] = [
    NodeSpec("Program", "subject", "program_name", keep=(), dedup=True),
    NodeSpec("Project", "subject", "project_id",
             keep=("project_name", "disease_type", "primary_site", "program_name"),
             dedup=True),
    # Subject = case (extractor already emits {base}.subject.tsv); fold demographic_*
    # in, drop project/program (their own nodes).
    NodeSpec("Subject", "subject", "case_id",
             strip_prefix="demographic_",
             drop=("project_id", "project_name", "program_name")),

    NodeSpec("Diagnosis", "diagnosis", "diagnosis_id",
             strip_prefix="diagnosis_", drop=_CHILD_DROP),
    NodeSpec("Treatment", "treatment", "treatment_id",
             strip_prefix="treatment_", drop=(*_CHILD_DROP, "diagnosis_id")),
    NodeSpec("PathologyDetail", "pathology_detail", "pathology_detail_id",
             strip_prefix="pathology_detail_", drop=(*_CHILD_DROP, "diagnosis_id")),
    NodeSpec("FollowUp", "follow_up", "follow_up_id",
             strip_prefix="follow_up_", drop=_CHILD_DROP),
    NodeSpec("MolecularTest", "molecular_test", "molecular_test_id",
             strip_prefix="molecular_test_",
             drop=(*_CHILD_DROP, "parent_entity", "parent_id")),
    NodeSpec("Exposure", "exposure", "exposure_id",
             strip_prefix="exposure_", drop=_CHILD_DROP),
    NodeSpec("FamilyHistory", "family_history", "family_history_id",
             strip_prefix="family_history_", drop=_CHILD_DROP),
    # sample.tsv is post-processed to aliquot grain: sample_id = the aliquot (new
    # Sample PK), with gdc_sample_id / portion_id / analyte_* riding as provenance.
    NodeSpec("Sample", "sample", "sample_id",
             strip_prefix="sample_", drop=_CHILD_DROP),
]

# ─────────────────────────────── Edges ───────────────────────────────
# Each edge is read straight from FK columns in one source table (no joins).

EDGE_SPECS: list[EdgeSpec] = [
    EdgeSpec("HAS_PROJECT", "subject", "program_name", "project_id", dedup=True),
    EdgeSpec("ENROLLS", "subject", "project_id", "case_id"),
    EdgeSpec("HAS_DIAGNOSIS", "diagnosis", "case_id", "diagnosis_id"),
    EdgeSpec("HAS_TREATMENT", "treatment", "diagnosis_id", "treatment_id"),
    EdgeSpec("HAS_PATHOLOGY", "pathology_detail", "diagnosis_id", "pathology_detail_id"),
    EdgeSpec("HAS_FOLLOWUP", "follow_up", "case_id", "follow_up_id"),
    # source node is Diagnosis or FollowUp depending on molecular_test.parent_entity;
    # parent_id already carries the right id, so the edge writes uniformly.
    EdgeSpec("HAS_MOLECULAR_TEST", "molecular_test", "parent_id", "molecular_test_id"),
    EdgeSpec("HAS_EXPOSURE", "exposure", "case_id", "exposure_id"),
    EdgeSpec("HAS_FAMILY_HISTORY", "family_history", "case_id", "family_history_id"),
    EdgeSpec("HAS_SAMPLE", "sample", "case_id", "sample_id"),
]

# KNOWN REFINEMENT (not yet applied): some GDC fields are arrays the extractor
# serialised as Python list literals, e.g. sites_of_involvement -> "['Liver', 'Bone']"
# or route_of_administration -> "['Intravenous']". These are real values, not
# placeholders. A future pass should normalise list-literals to proper multi-value
# properties (e.g. ';'-joined or true arrays) — enumerate the array fields from
# gdc_data_dict.json rather than sniffing brackets, since bracketed text is valid data.

# GDC / BCR placeholder tokens treated as null and scrubbed from values.
PLACEHOLDERS: frozenset = frozenset({
    "", "--",
    "[Not Available]", "[Not Evaluated]", "[Unknown]", "[Not Applicable]",
    "[Not Reported]", "[Discrepancy]", "[Completed]", "[Pending]",
    "not reported", "unknown", "Unknown", "Not Reported",
})
