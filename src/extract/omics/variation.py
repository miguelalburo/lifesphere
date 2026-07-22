"""Somatic variation extraction and reshape.

Pipeline:
  1. query_variation_files()  — query GDC /files for open Masked Somatic Mutation MAFs
  2. write_manifest()         — write gdc-client manifest.tsv
  3. write_file_metadata()    — write file→assay metadata TSV
  4. download_file()          — download one MAF via GDC data API
  5. reshape()                — reshape MAF rows to observation-grain TSV
  6. extract_variation()      — orchestrate the full pipeline

reshape() writes variation_observation.tsv to the dataset raw directory.
Each MAF row's Tumor_Sample_Barcode (an aliquot barcode) is remapped to the
aliquot UUID via aliquot_map() so sample_id keys the Sample node like the other
omics layers. Run ``standardise --profile omics`` on that directory to produce
graph CSVs.
"""

from __future__ import annotations

import csv
import gzip
import sys
from pathlib import Path
from typing import Iterator

from .. import gdc_api
from .download import download_file
from ...observation import VARIATION_OBS_COLUMNS, obs_id as _obs_id, strip_version as _strip_version

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
    "cases.samples.portions.analytes.aliquots",
]
_VARIATION_FILTERS = [
    {"op": "=", "content": {"field": "data_type", "value": "Masked Somatic Mutation"}},
    {"op": "=", "content": {"field": "data_category", "value": "Simple Nucleotide Variation"}},
    {"op": "=", "content": {"field": "access", "value": "open"}},
]

# Observation column set, surrogate-id minting, and Ensembl stripping are the
# shared canonical contract (src/observation.py). The GDC MAF variant key uses
# a colon form (chrom:pos:ref:alt) and is local to this reshaper — the
# traditional VCF reader mints its own dash form, a deliberately distinct set.
_OBS_COLUMNS = VARIATION_OBS_COLUMNS


def _variant_id(chrom: str, pos: str, ref: str, alt: str) -> str:
    """Return 'chrom:pos:ref:alt' as the canonical GDC variant key (GRCh38)."""
    return f"{chrom}:{pos}:{ref}:{alt}"


def _compute_vaf(t_depth: str, t_alt_count: str) -> str:
    try:
        depth = float(t_depth)
        alt = float(t_alt_count)
        if depth > 0:
            return f"{alt / depth:.4f}"
        return ""
    except (ValueError, ZeroDivisionError):
        return ""


def pipeline_version(file_meta: dict) -> str:
    """Return the workflow_type string from a GDC /files response entry."""
    return (file_meta.get("analysis") or {}).get("workflow_type", "")


def assay_id(file_meta: dict) -> str:
    """Return a deterministic assay id as 'platform|strategy|workflow'."""
    platform = file_meta.get("platform") or "unknown"
    strategy = file_meta.get("experimental_strategy") or "unknown"
    workflow = (file_meta.get("analysis") or {}).get("workflow_type") or "unknown"
    return f"{platform}|{strategy}|{workflow}"


def aliquot_map(files: list[dict]) -> dict[str, str]:
    """Build {aliquot_submitter_barcode: aliquot_uuid} from /files hits.

    Requires the hits to be expanded with
    ``cases.samples.portions.analytes.aliquots``. The MAF's ``Tumor_Sample_Barcode``
    is an aliquot barcode; this map remaps it to the aliquot UUID that keys the
    Sample node (see ``src/extract/entities/sample.py``), so variation
    observations align with expression/methylation on ``sample_id``.
    """
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


def reshape(entries: list[dict], out_path: Path, *, dataset: str = "",
            sample_id_map: dict[str, str] | None = None,
            keep_barcodes: set[str] | None = None) -> int:
    """Reshape MAF file(s) to observation-grain TSV; returns observation count."""
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
                barcode = row.get("Tumor_Sample_Barcode", "")
                if not barcode:
                    continue
                if keep_barcodes is not None and barcode not in keep_barcodes:
                    continue
                sample_id = sample_id_map.get(barcode, barcode) if sample_id_map else barcode
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


def query_variation_files(
    project_id: str | None = None,
    *,
    program_name: str | None = None,
) -> list[dict]:
    """Query GDC /files for open Masked Somatic Mutation MAFs.

    Scope by project_id (single project) or program_name (all projects in program).
    """
    clauses: list[dict] = [*_VARIATION_FILTERS]
    if program_name:
        clauses.insert(0, {"op": "=", "content": {"field": "cases.project.program.name", "value": program_name}})
    elif project_id:
        clauses.insert(0, {"op": "=", "content": {"field": "cases.project.project_id", "value": project_id}})
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
                "assay_id": assay_id(f),
                "pipeline_version": pipeline_version(f),
            })


def extract_variation(selector: str, out_dir: Path, *, is_program: bool = False) -> None:
    """Full variation extraction pipeline for one GDC project or program."""
    var_dir = out_dir / "variation"
    var_dir.mkdir(parents=True, exist_ok=True)

    scope = f"program {selector}" if is_program else selector
    print(
        f"Querying GDC /files for {scope} Masked Somatic Mutation MAFs...",
        file=sys.stderr, flush=True,
    )
    files = query_variation_files(
        program_name=selector if is_program else None,
        project_id=None if is_program else selector,
    )
    if not files:
        print("  No variation files found.", file=sys.stderr)
        return

    print(f"  {len(files)} files found.", file=sys.stderr, flush=True)
    write_manifest(files, var_dir / "manifest.tsv")
    write_file_metadata(files, var_dir / "file_metadata.tsv")

    # Remap each MAF's Tumor_Sample_Barcode → aliquot UUID so variation
    # sample_ids align with the Sample node key (and expression/methylation).
    sample_map = aliquot_map(files)
    print(
        f"  Aliquot map: {len(sample_map)} barcode→UUID entries",
        file=sys.stderr, flush=True,
    )

    print(f"Downloading variation files to {var_dir}...", file=sys.stderr, flush=True)
    entries: list[dict] = []
    for i, f in enumerate(files, 1):
        file_id = f.get("file_id", "")
        file_name = f.get("file_name", file_id)
        print(f"  [{i}/{len(files)}] {file_name}", file=sys.stderr, flush=True)
        local_path = download_file(
            file_id, file_name, var_dir,
            md5=f.get("md5sum"), size=f.get("file_size"),
        )
        entries.append({
            "path": local_path,
            "assay_id": assay_id(f),
            "source_file": file_id,
            "pipeline_version": pipeline_version(f),
        })

    print(f"Reshaping {len(entries)} variation file(s)...", file=sys.stderr, flush=True)
    obs_path = out_dir / "variation_observation.tsv"
    count = reshape(entries, obs_path, dataset=selector, sample_id_map=sample_map)
    print(
        f"  Wrote {count:,} observations to {obs_path.name}",
        file=sys.stderr, flush=True,
    )
