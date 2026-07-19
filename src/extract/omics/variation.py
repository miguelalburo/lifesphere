"""Somatic variation extraction and reshape.

Pipeline:
  1. query_variation_files()  — query GDC /files for open Masked Somatic Mutation MAFs
  2. write_manifest()         — write gdc-client manifest.tsv
  3. write_file_metadata()    — write file→assay metadata TSV
  4. download_file()          — download one MAF via GDC data API
  5. reshape()                — reshape MAF rows to observation-grain TSV
  6. extract_variation()      — orchestrate the full pipeline

reshape() writes variation_observation.tsv to the dataset raw directory.
The sample_id is read from each MAF row's Tumor_Sample_Barcode column.
Run ``standardise --profile omics`` on that directory to produce graph CSVs.
"""

from __future__ import annotations

import csv
import gzip
import sys
import urllib.request
from pathlib import Path
from typing import Iterator

from .. import gdc_api

_DATA_URL = "https://api.gdc.cancer.gov/data"

_FILE_FIELDS = [
    "file_id",
    "file_name",
    "md5sum",
    "file_size",
    "experimental_strategy",
    "platform",
    "data_format",
]
_FILE_EXPAND = [
    "analysis",
]
_VARIATION_FILTERS = [
    {"op": "=", "content": {"field": "data_type", "value": "Masked Somatic Mutation"}},
    {"op": "=", "content": {"field": "data_category", "value": "Simple Nucleotide Variation"}},
    {"op": "=", "content": {"field": "access", "value": "open"}},
]

_OBS_COLUMNS = [
    "variant_observation_id",
    "sample_id",
    "variant_id",
    "gene_id",
    "chromosome",
    "position_start",
    "position_end",
    "reference_allele",
    "alternate_allele",
    "variant_class",
    "impact",
    "variant_allele_frequency",
    "tumor_read_count",
    "tumor_variant_count",
    "normal_read_count",
    "normal_variant_count",
    "filter_status",
    "somatic_status",
    "assay_id",
    "source_dataset",
    "source_file",
    "pipeline_version",
]


def _strip_version(gene_id: str) -> str:
    """Strip Ensembl version suffix: 'ENSG00000141510.12' → 'ENSG00000141510'."""
    return gene_id.split(".")[0]


def _variant_id(chrom: str, pos: str, ref: str, alt: str) -> str:
    """Return 'chrom:pos:ref:alt' as the canonical variant key (GRCh38)."""
    return f"{chrom}:{pos}:{ref}:{alt}"


def _obs_id(sample_id: str, var_id: str) -> str:
    """Return '{sample_id}:{variant_id}' as the observation surrogate key."""
    return f"{sample_id}:{var_id}"


def _compute_vaf(t_depth: str, t_alt_count: str) -> str:
    try:
        depth = float(t_depth)
        alt = float(t_alt_count)
        if depth > 0:
            return f"{alt / depth:.4f}"
        return ""
    except (ValueError, ZeroDivisionError):
        return ""


def _pipeline_version(file_meta: dict) -> str:
    return (file_meta.get("analysis") or {}).get("workflow_type", "")


def _assay_id(file_meta: dict) -> str:
    platform = file_meta.get("platform") or "unknown"
    strategy = file_meta.get("experimental_strategy") or "unknown"
    workflow = (file_meta.get("analysis") or {}).get("workflow_type") or "unknown"
    return f"{platform}|{strategy}|{workflow}"


def _parse_maf(path: Path) -> Iterator[dict]:
    """Yield one dict per mutation row from a GDC Masked Somatic Mutation MAF.

    Handles both plain-text and gzip-compressed (.gz) MAF files.
    Skips comment lines (starting with #) and the column-header row.
    """
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as fh:
        header: list[str] | None = None
        for line in fh:
            line = line.rstrip("\n\r")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if header is None:
                header = parts
                continue
            if len(parts) < 2:
                continue
            yield dict(zip(header, parts))


def reshape(entries: list[dict], out_path: Path, *, dataset: str = "") -> int:
    """Reshape MAF file(s) to observation-grain TSV.

    Each entry dict must have: ``path``, ``assay_id``.
    Optional keys: ``source_file``, ``pipeline_version``.
    The sample_id is read from each row's Tumor_Sample_Barcode column.

    Returns the number of observations written.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_OBS_COLUMNS, delimiter="\t")
        writer.writeheader()
        for entry in entries:
            assay_id = entry["assay_id"]
            source_file = entry.get("source_file", "")
            pipeline_ver = entry.get("pipeline_version", "")
            for row in _parse_maf(entry["path"]):
                sample_id = row.get("Tumor_Sample_Barcode", "")
                if not sample_id:
                    continue
                chrom = row.get("Chromosome", "")
                pos = row.get("Start_Position", "")
                ref = row.get("Reference_Allele", "")
                alt = row.get("Tumor_Seq_Allele2", "")
                if not (chrom and pos and ref and alt):
                    continue
                var_id = _variant_id(chrom, pos, ref, alt)
                raw_gene_id = row.get("Gene", "")
                gene_id = _strip_version(raw_gene_id) if raw_gene_id else ""
                writer.writerow({
                    "variant_observation_id": _obs_id(sample_id, var_id),
                    "sample_id": sample_id,
                    "variant_id": var_id,
                    "gene_id": gene_id,
                    "chromosome": chrom,
                    "position_start": pos,
                    "position_end": row.get("End_Position", ""),
                    "reference_allele": ref,
                    "alternate_allele": alt,
                    "variant_class": row.get("Variant_Classification", ""),
                    "impact": row.get("IMPACT", ""),
                    "variant_allele_frequency": _compute_vaf(
                        row.get("t_depth", ""), row.get("t_alt_count", "")
                    ),
                    "tumor_read_count": row.get("t_depth", ""),
                    "tumor_variant_count": row.get("t_alt_count", ""),
                    "normal_read_count": row.get("n_depth", ""),
                    "normal_variant_count": row.get("n_alt_count", ""),
                    "filter_status": row.get("FILTER", ""),
                    "somatic_status": "Somatic",
                    "assay_id": assay_id,
                    "source_dataset": dataset,
                    "source_file": source_file,
                    "pipeline_version": pipeline_ver,
                })
                count += 1
    return count


def query_variation_files(project_id: str) -> list[dict]:
    """Query GDC /files for open Masked Somatic Mutation MAFs in a project."""
    filters = {
        "op": "and",
        "content": [
            {"op": "=", "content": {
                "field": "cases.project.project_id", "value": project_id,
            }},
            *_VARIATION_FILTERS,
        ],
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
    """Write file→assay metadata TSV."""
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with metadata_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["file_id", "file_name", "assay_id", "pipeline_version"],
            delimiter="\t",
        )
        writer.writeheader()
        for f in files:
            writer.writerow({
                "file_id": f.get("file_id", ""),
                "file_name": f.get("file_name", ""),
                "assay_id": _assay_id(f),
                "pipeline_version": _pipeline_version(f),
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


def extract_variation(project_id: str, out_dir: Path) -> None:
    """Full variation extraction pipeline for one GDC project."""
    var_dir = out_dir / "variation"
    var_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Querying GDC /files for {project_id} Masked Somatic Mutation MAFs...",
        file=sys.stderr, flush=True,
    )
    files = query_variation_files(project_id)
    if not files:
        print("  No variation files found.", file=sys.stderr)
        return

    print(f"  {len(files)} files found.", file=sys.stderr, flush=True)
    write_manifest(files, var_dir / "manifest.tsv")
    write_file_metadata(files, var_dir / "file_metadata.tsv")

    print(f"Downloading variation files to {var_dir}...", file=sys.stderr, flush=True)
    entries: list[dict] = []
    for i, f in enumerate(files, 1):
        file_id = f.get("file_id", "")
        file_name = f.get("file_name", file_id)
        print(f"  [{i}/{len(files)}] {file_name}", file=sys.stderr, flush=True)
        local_path = download_file(file_id, file_name, var_dir)
        entries.append({
            "path": local_path,
            "assay_id": _assay_id(f),
            "source_file": file_id,
            "pipeline_version": _pipeline_version(f),
        })

    print(f"Reshaping {len(entries)} variation file(s)...", file=sys.stderr, flush=True)
    obs_path = out_dir / "variation_observation.tsv"
    count = reshape(entries, obs_path, dataset=project_id)
    print(
        f"  Wrote {count:,} observations to {obs_path.name}",
        file=sys.stderr, flush=True,
    )
