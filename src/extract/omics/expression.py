"""Expression quantification extraction and reshape.

Pipeline:
  1. query_expression_files()  — query GDC /files for open RNA-Seq STAR-Counts matrices
  2. write_manifest()          — write gdc-client manifest.tsv
  3. write_file_metadata()     — write file→aliquot+assay metadata TSV
  4. download_file()           — download one STAR-Counts TSV via GDC data API
  5. reshape()                 — reshape matrices to observation-grain TSV
  6. extract_expression()      — orchestrate the full pipeline

reshape() writes expression_observation.tsv to the dataset raw directory.
Run ``standardise --profile omics`` on that directory to produce graph CSVs.
"""

from __future__ import annotations

import csv
import sys
import urllib.request
from pathlib import Path
from typing import Iterator

from .. import gdc_api
from ...observation import EXPRESSION_OBS_COLUMNS, obs_id as _obs_id, strip_version as _strip_version

_DATA_URL = "https://api.gdc.cancer.gov/data"

_FILE_FIELDS = [
    "file_id",
    "file_name",
    "md5sum",
    "file_size",
    "experimental_strategy",
    "platform",
]
_FILE_EXPAND = [
    "cases.samples.portions.analytes.aliquots",
    "analysis",
]
_EXPRESSION_FILTERS = [
    {"op": "=", "content": {"field": "experimental_strategy", "value": "RNA-Seq"}},
    {"op": "=", "content": {"field": "data_type", "value": "Gene Expression Quantification"}},
    {"op": "=", "content": {"field": "data_category", "value": "Transcriptome Profiling"}},
    {"op": "=", "content": {"field": "analysis.workflow_type", "value": "STAR - Counts"}},
    {"op": "=", "content": {"field": "access", "value": "open"}},
]

# Observation column set, surrogate-id minting, and Ensembl stripping are the
# shared canonical contract (src/observation.py) so this GDC reshaper and the
# traditional reshaper cannot drift.
_OBS_COLUMNS = EXPRESSION_OBS_COLUMNS


def pipeline_version(file_meta: dict) -> str:
    """Return the workflow_type string from a GDC /files response entry."""
    return (file_meta.get("analysis") or {}).get("workflow_type", "")


def aliquot_id(file_meta: dict) -> str:
    """Return the aliquot UUID from a GDC /files response entry (cases expand)."""
    try:
        return (
            file_meta["cases"][0]
            ["samples"][0]
            ["portions"][0]
            ["analytes"][0]
            ["aliquots"][0]
            ["aliquot_id"]
        )
    except (KeyError, IndexError):
        return ""


def assay_id(file_meta: dict) -> str:
    """Return a deterministic assay id as 'platform|strategy|workflow'."""
    platform = file_meta.get("platform") or "unknown"
    strategy = file_meta.get("experimental_strategy") or "unknown"
    workflow = (file_meta.get("analysis") or {}).get("workflow_type") or "unknown"
    return f"{platform}|{strategy}|{workflow}"


def _parse_star_counts(path: Path) -> Iterator[dict]:
    """Yield one dict per gene row from a GDC STAR-Counts TSV.

    Skips leading ``#`` comment lines (GDC files begin with e.g.
    ``# gene-model: GENCODE v36``), the N_* summary rows (N_unmapped,
    N_multimapping, N_noFeature, N_ambiguous) and the column-header row itself.
    """
    with path.open(newline="", encoding="utf-8") as fh:
        header: list[str] | None = None
        for line in fh:
            line = line.rstrip("\n\r")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if parts[0].startswith("N_"):
                continue
            if header is None:
                header = parts  # first non-comment, non-N_ line is the column header
                continue
            if len(parts) < len(header):
                continue
            yield dict(zip(header, parts))


def reshape(entries: list[dict], out_path: Path, *, dataset: str = "") -> int:
    """Reshape STAR-Counts files to observation-grain TSV.

    Each entry dict must have: ``path``, ``sample_id``, ``assay_id``.
    Optional keys: ``source_file``, ``pipeline_version``.

    Returns the number of observations written.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_OBS_COLUMNS, delimiter="\t")
        writer.writeheader()
        for entry in entries:
            sample_id = entry["sample_id"]
            assay_id = entry["assay_id"]
            source_file = entry.get("source_file", "")
            pipeline_version = entry.get("pipeline_version", "")
            for row in _parse_star_counts(entry["path"]):
                raw_gene_id = row.get("gene_id", "")
                if not raw_gene_id:
                    continue
                gene_id = _strip_version(raw_gene_id)
                tpm = row.get("tpm_unstranded", "")
                writer.writerow({
                    "expression_observation_id": _obs_id(sample_id, gene_id),
                    "sample_id": sample_id,
                    "gene_id": gene_id,
                    "expression_value": tpm,
                    "expression_unit": "TPM",
                    "assay_id": assay_id,
                    "source_dataset": dataset,
                    "source_file": source_file,
                    "pipeline_version": pipeline_version,
                })
                count += 1
    return count


def query_expression_files(
    project_id: str | None = None,
    case_id: str | None = None,
    *,
    program_name: str | None = None,
) -> list[dict]:
    """Query GDC /files for open RNA-Seq STAR-Counts files.

    Scope by project_id (single project) or program_name (all projects in program).
    case_id further narrows to a single case.
    """
    clauses: list[dict] = [*_EXPRESSION_FILTERS]
    if program_name:
        clauses.insert(0, {"op": "=", "content": {"field": "cases.project.program.name", "value": program_name}})
    elif project_id:
        clauses.insert(0, {"op": "=", "content": {"field": "cases.project.project_id", "value": project_id}})
    if case_id:
        clauses.append({"op": "=", "content": {"field": "cases.case_id", "value": case_id}})
    filters = {
        "op": "and",
        "content": clauses,
    }
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
            print(f"  Total files: {total}", flush=True)
        hits.extend(d["hits"])
        from_pos += len(d["hits"])
        print(f"  Fetched {from_pos}/{total}...", flush=True)
    return hits


def write_manifest(files: list[dict], manifest_path: Path) -> None:
    """Write a gdc-client compatible manifest TSV."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["id", "filename", "md5", "size", "state"],
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        for f in files:
            writer.writerow({
                "id": f.get("file_id", ""),
                "filename": f.get("file_name", ""),
                "md5": f.get("md5sum", ""),
                "size": f.get("file_size", ""),
                "state": "validated",
            })


def write_file_metadata(files: list[dict], metadata_path: Path) -> None:
    """Write file→aliquot+assay metadata TSV (used by reshape to associate files with samples)."""
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with metadata_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["file_id", "file_name", "sample_id", "assay_id", "pipeline_version"],
            delimiter="\t",
        )
        writer.writeheader()
        for f in files:
            writer.writerow({
                "file_id": f.get("file_id", ""),
                "file_name": f.get("file_name", ""),
                "sample_id": aliquot_id(f),
                "assay_id": assay_id(f),
                "pipeline_version": pipeline_version(f),
            })


def download_file(file_id: str, file_name: str, out_dir: Path) -> Path:
    """Download one GDC file to out_dir/{file_id}/{file_name}.

    Resume-safe: skips the download if the file already exists.
    """
    dest = out_dir / file_id
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / file_name
    if out_path.exists():
        return out_path
    url = f"{_DATA_URL}/{file_id}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=300) as resp:
        out_path.write_bytes(resp.read())
    return out_path


def extract_expression(selector: str, out_dir: Path, *, is_program: bool = False) -> None:
    """Full expression extraction pipeline for one GDC project or program."""
    expr_dir = out_dir / "expression"
    expr_dir.mkdir(parents=True, exist_ok=True)

    scope = f"program {selector}" if is_program else selector
    print(
        f"Querying GDC /files for {scope} RNA-Seq expression files...",
        file=sys.stderr, flush=True,
    )
    files = query_expression_files(
        program_name=selector if is_program else None,
        project_id=None if is_program else selector,
    )
    if not files:
        print("  No expression files found.", file=sys.stderr)
        return

    print(f"  {len(files)} files found.", file=sys.stderr, flush=True)
    write_manifest(files, expr_dir / "manifest.tsv")
    write_file_metadata(files, expr_dir / "file_metadata.tsv")

    print(f"Downloading expression files to {expr_dir}...", file=sys.stderr, flush=True)
    entries: list[dict] = []
    for i, f in enumerate(files, 1):
        file_id = f.get("file_id", "")
        file_name = f.get("file_name", file_id)
        print(f"  [{i}/{len(files)}] {file_name}", file=sys.stderr, flush=True)
        local_path = download_file(file_id, file_name, expr_dir)
        entries.append({
            "path": local_path,
            "sample_id": aliquot_id(f),
            "assay_id": assay_id(f),
            "source_file": file_id,
            "pipeline_version": pipeline_version(f),
        })

    print(f"Reshaping {len(entries)} expression files...", file=sys.stderr, flush=True)
    obs_path = out_dir / "expression_observation.tsv"
    count = reshape(entries, obs_path, dataset=selector)
    print(
        f"  Wrote {count:,} observations to {obs_path.name}",
        file=sys.stderr, flush=True,
    )
