"""Auto-select a GDC case that has all three open-access omics types.

Queries GDC /files for expression, methylation, and variation data,
intersects the resulting case sets, and returns a CaseSelection with
everything the demonstration script needs to run a single-sample load.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from . import gdc_api
from .omics.expression import _EXPRESSION_FILTERS
from .omics.methylation import _METHYLATION_FILTERS
from .omics.variation import _VARIATION_FILTERS

_FILE_FIELDS = [
    "file_id",
    "file_name",
    "md5sum",
    "file_size",
    "experimental_strategy",
    "platform",
    "data_type",
]
_FILE_EXPAND = [
    "cases",
    "cases.samples.portions.analytes.aliquots",
    "analysis",
]

# ──────────────────────────────── Data types ──────────────────────────────────


@dataclass
class CaseSelection:
    """Everything the demo script needs to run a single-sample load."""

    case_id: str
    project_id: str
    expression_files: list[dict] = field(default_factory=list)
    methylation_files: list[dict] = field(default_factory=list)
    variation_files: list[dict] = field(default_factory=list)
    aliquot_map: dict[str, str] = field(default_factory=dict)
    """Mapping from TCGA barcode (Tumor_Sample_Barcode) → GDC aliquot UUID
    (aliquot_id).  Used to align variation sample_ids with clinical Sample nodes."""


# ────────────────────────────── GDC helpers ───────────────────────────────────


def _query_files(type_filters: list[dict], project_id: str,
                 case_id: str | None = None) -> list[dict]:
    """Fetch all /files hits for a data type, optionally filtered to one case."""
    clauses: list[dict] = [
        {"op": "=", "content": {"field": "cases.project.project_id", "value": project_id}},
        *type_filters,
    ]
    if case_id:
        clauses.append({"op": "=", "content": {"field": "cases.case_id", "value": case_id}})
    filters = {"op": "and", "content": clauses}

    hits: list[dict] = []
    from_pos, total = 0, None
    while total is None or from_pos < total:
        payload = {
            "filters": filters,
            "fields": ",".join(_FILE_FIELDS),
            "expand": ",".join(_FILE_EXPAND),
            "size": 500,
            "from": from_pos,
        }
        d = gdc_api.post(gdc_api.FILES_URL, payload)["data"]
        if total is None:
            total = d["pagination"]["total"]
        hits.extend(d["hits"])
        from_pos += len(d["hits"])
        if not d["hits"]:
            break
    return hits


def _case_ids_from_files(files: list[dict]) -> set[str]:
    """Extract GDC case UUIDs from a /files response hit list."""
    ids: set[str] = set()
    for f in files:
        for case in f.get("cases") or []:
            cid = case.get("case_id", "")
            if cid:
                ids.add(cid)
    return ids


def _aliquot_map_from_files(files: list[dict]) -> dict[str, str]:
    """Build {submitter_barcode: aliquot_uuid} from /files response (with aliquot expand)."""
    mapping: dict[str, str] = {}
    for f in files:
        for case in f.get("cases") or []:
            for smp in case.get("samples") or []:
                for portion in smp.get("portions") or []:
                    for analyte in portion.get("analytes") or []:
                        for aliquot in analyte.get("aliquots") or []:
                            barcode = aliquot.get("submitter_id", "")
                            uuid = aliquot.get("aliquot_id", "")
                            if barcode and uuid:
                                mapping[barcode] = uuid
    return mapping


def _preferred_case_id(case_ids: set[str], expr_files: list[dict]) -> str | None:
    """Pick the case_id whose expression file came from a Primary Tumor sample.

    Falls back to any case_id in the set if no primary tumor is detected.
    """
    for f in expr_files:
        for case in f.get("cases") or []:
            cid = case.get("case_id", "")
            if cid not in case_ids:
                continue
            for smp in case.get("samples") or []:
                sample_type = smp.get("sample_type", "")
                if "primary" in sample_type.lower() or "tumor" in sample_type.lower():
                    return cid
    return next(iter(case_ids), None)


# ──────────────────────────────── Public API ──────────────────────────────────


def select_case(
    preferred_project: str = "TCGA-CHOL",
    fallback_projects: list[str] | None = None,
    log: bool = True,
) -> CaseSelection:
    """Return a CaseSelection for one multi-omic case.

    Searches ``preferred_project`` first, then each project in
    ``fallback_projects`` (default: a small set of common TCGA projects).
    Raises ``RuntimeError`` if no qualifying case is found in any project.
    """

    def _log(msg: str) -> None:
        if log:
            print(msg, file=sys.stderr, flush=True)

    projects = [preferred_project] + (
        fallback_projects if fallback_projects is not None
        else ["TCGA-BRCA", "TCGA-LUAD", "TCGA-UCEC"]
    )

    for project_id in projects:
        _log(f"\nSearching {project_id} for a multi-omic case...")

        _log("  Querying expression files...")
        expr_files = _query_files(_EXPRESSION_FILTERS, project_id)
        expr_cases = _case_ids_from_files(expr_files)
        _log(f"    {len(expr_files)} files, {len(expr_cases)} cases")

        if not expr_cases:
            _log("  No expression data — skipping project.")
            continue

        _log("  Querying methylation files...")
        meth_files = _query_files(_METHYLATION_FILTERS, project_id)
        meth_cases = _case_ids_from_files(meth_files)
        _log(f"    {len(meth_files)} files, {len(meth_cases)} cases")

        _log("  Querying variation files...")
        var_files = _query_files(_VARIATION_FILTERS, project_id)
        var_cases = _case_ids_from_files(var_files)
        _log(f"    {len(var_files)} files, {len(var_cases)} cases")

        multi_omic = expr_cases & meth_cases & var_cases
        _log(f"  Multi-omic cases: {len(multi_omic)}")

        if not multi_omic:
            _log("  No multi-omic cases — skipping project.")
            continue

        case_id = _preferred_case_id(multi_omic, expr_files)
        if case_id is None:
            continue

        _log(f"\nSelected case: {case_id} ({project_id})")

        # Re-query per-case expression and methylation files for download metadata.
        _log("  Fetching per-case expression files...")
        case_expr = _query_files(_EXPRESSION_FILTERS, project_id, case_id=case_id)
        _log(f"    {len(case_expr)} file(s)")

        _log("  Fetching per-case methylation files...")
        case_meth = _query_files(_METHYLATION_FILTERS, project_id, case_id=case_id)
        _log(f"    {len(case_meth)} file(s)")

        # Build barcode → UUID map from all aliquots of this case (RNA + DNA).
        _log("  Fetching per-case variation files for aliquot map...")
        case_var_for_map = _query_files(_VARIATION_FILTERS, project_id, case_id=case_id)
        _log(f"    {len(case_var_for_map)} file(s)")
        aliquot_map = _aliquot_map_from_files(case_expr + case_meth + case_var_for_map)
        _log(f"  Aliquot map: {len(aliquot_map)} barcode→UUID entries")

        return CaseSelection(
            case_id=case_id,
            project_id=project_id,
            expression_files=case_expr,
            methylation_files=case_meth,
            variation_files=var_files,
            aliquot_map=aliquot_map,
        )

    raise RuntimeError(
        "No multi-omic case found in any of: "
        + ", ".join(projects)
        + ". Check GDC availability or widen fallback_projects."
    )
