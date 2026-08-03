"""Methylation beta-value extraction and reshape.

Pipeline:
  1. query_methylation_files()  — query GDC /files for open Methylation Beta Value files
  2. write_manifest()           — write gdc-client manifest.tsv
  3. write_file_metadata()      — write file→aliquot+assay metadata TSV
  4. download_file()            — download one beta-value TSV via GDC data API
  5. reshape()                  — reshape per-sample files to observation-grain TSV
  6. extract_methylation()      — orchestrate the full pipeline

reshape() writes methylation_observation.tsv to the dataset raw directory.
Run ``standardise --profile omics`` on that directory to produce graph CSVs.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Iterator

from .. import gdc_api
from .download import download_all
from ...observation import METHYLATION_OBS_COLUMNS, obs_id as _obs_id

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
_METHYLATION_FILTERS = [
    {"op": "=", "content": {"field": "experimental_strategy", "value": "Methylation Array"}},
    {"op": "=", "content": {"field": "data_type", "value": "Methylation Beta Value"}},
    {"op": "=", "content": {"field": "data_category", "value": "DNA Methylation"}},
    {"op": "=", "content": {"field": "access", "value": "open"}},
]

# Observation column set and surrogate-id minting are the shared canonical
# contract (src/observation.py) so this GDC reshaper and the traditional
# reshaper cannot drift. CpG probe ids are used as-is (no version stripping).
_OBS_COLUMNS = METHYLATION_OBS_COLUMNS


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
    """Return a deterministic assay id as 'platform|strategy|Methylation Beta Value'."""
    platform = file_meta.get("platform") or "unknown"
    strategy = file_meta.get("experimental_strategy") or "unknown"
    return f"{platform}|{strategy}|Methylation Beta Value"


def pipeline_version(file_meta: dict) -> str:
    """Return the workflow_type string from a GDC /files response entry."""
    return (file_meta.get("analysis") or {}).get("workflow_type", "")


def _parse_beta_file(path: Path) -> Iterator[dict]:
    """Yield one dict per CpG row from a GDC Methylation Beta Value TSV.

    Handles both GDC methylation layouts:

    * Annotated array files carry a header row beginning ``Composite Element
      REF`` with columns Beta_value, Chromosome, Start, End, Gene_Symbol, ...
    * ``sesame`` level3betas files are headerless, two columns:
      ``<probe_id>\\t<beta_value>``.

    Comment lines (starting with #) are skipped. For the headerless format a
    synthetic ``Composite Element REF`` / ``Beta_value`` header is applied and
    the first line is treated as data.
    """
    with path.open(newline="", encoding="utf-8") as fh:
        header: list[str] | None = None
        for line in fh:
            line = line.rstrip("\n\r")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if header is None:
                if parts and parts[0] == "Composite Element REF":
                    header = parts  # annotated format: consume the header row
                    continue
                # headerless sesame format: (probe_id, beta_value)
                header = ["Composite Element REF", "Beta_value"]
                # fall through — this first line is already data
            if len(parts) < 2:
                continue
            yield dict(zip(header, parts))


def reshape(entries: list[dict], out_path: Path, *, dataset: str = "") -> int:
    """Reshape per-sample beta-value files to observation-grain TSV.

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
            for row in _parse_beta_file(entry["path"]):
                cpg_id = row.get("Composite Element REF", "")
                if not cpg_id:
                    continue
                beta_value = row.get("Beta_value", "")
                chromosome = row.get("Chromosome", "")
                start_pos = row.get("Start", "")
                gene_symbol = row.get("Gene_Symbol", "")
                # GDC uses "." for missing annotation values
                if gene_symbol == ".":
                    gene_symbol = ""
                if chromosome == ".":
                    chromosome = ""
                if start_pos == ".":
                    start_pos = ""
                writer.writerow({
                    "methylation_observation_id": _obs_id(sample_id, cpg_id),
                    "sample_id": sample_id,
                    "cpg_id": cpg_id,
                    "beta_value": beta_value,
                    "num_cpg_sites": "1",
                    "modification_type": "5mC",
                    "methylation_status": "",
                    "chromosome": chromosome,
                    "start_position": start_pos,
                    "gene_symbol": gene_symbol,
                    "assay_id": assay_id,
                    "source_dataset": dataset,
                    "source_file": source_file,
                    "pipeline_version": pipeline_version,
                })
                count += 1
    return count


def query_methylation_files(
    project_id: str | None = None,
    case_id: str | None = None,
    *,
    program_name: str | None = None,
) -> list[dict]:
    """Query GDC /files for open Methylation Beta Value files.

    Scope by project_id (single project) or program_name (all projects in program).
    case_id further narrows to a single case.
    """
    clauses: list[dict] = [*_METHYLATION_FILTERS]
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
    """Write file→aliquot+assay metadata TSV."""
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


def extract_methylation(
    selector: str, out_dir: Path, *, is_program: bool = False, max_workers: int = 8,
) -> None:
    """Full methylation extraction pipeline for one GDC project or program."""
    meth_dir = out_dir / "methylation"
    meth_dir.mkdir(parents=True, exist_ok=True)

    scope = f"program {selector}" if is_program else selector
    print(
        f"Querying GDC /files for {scope} Methylation Beta Value files...",
        file=sys.stderr, flush=True,
    )
    files = query_methylation_files(
        program_name=selector if is_program else None,
        project_id=None if is_program else selector,
    )
    if not files:
        print("  No methylation files found.", file=sys.stderr)
        return

    print(f"  {len(files)} files found.", file=sys.stderr, flush=True)
    write_manifest(files, meth_dir / "manifest.tsv")
    write_file_metadata(files, meth_dir / "file_metadata.tsv")

    print(
        f"Downloading methylation files to {meth_dir} ({max_workers} workers)...",
        file=sys.stderr, flush=True,
    )
    downloaded = download_all(files, meth_dir, max_workers=max_workers)
    entries: list[dict] = []
    for f in files:
        file_id = f.get("file_id", "")
        entries.append({
            "path": downloaded[file_id],
            "sample_id": aliquot_id(f),
            "assay_id": assay_id(f),
            "source_file": file_id,
            "pipeline_version": pipeline_version(f),
        })

    print(f"Reshaping {len(entries)} methylation files...", file=sys.stderr, flush=True)
    obs_path = out_dir / "methylation_observation.tsv"
    count = reshape(entries, obs_path, dataset=selector)
    print(
        f"  Wrote {count:,} observations to {obs_path.name}",
        file=sys.stderr, flush=True,
    )
