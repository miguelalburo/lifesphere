"""Dedicated VCF reader behind the reshape door (``type: vcf``).

Not the matrix melt. Reads a multi-sample VCF into canonical variation
observation TSVs, plus an opportunistic IS_WITHIN_GENE edge TSV.

Input contract: the VCF is expected already left-aligned (upstream
``bcftools norm``). The reader itself does only a pure-Python **defensive
multi-allelic split** — re-indexing each per-sample genotype to the correct
allele so every emitted ``VariantObservation`` points at the allele that sample
actually carries. It takes no dependency on bcftools or a reference FASTA.

``variantId`` is synthesized as ``CHROM-POS-REF-ALT`` (dash form) as written — not
the possibly-absent VCF ``ID`` column. Traditional variants therefore form their
own ``Variant`` set, distinct from GDC's colon-keyed set: an accepted, documented
consequence.

Annotation is opportunistic: with a VEP ``CSQ`` INFO field, the ``Gene`` sub-field
is located via the ``##INFO=<ID=CSQ,...Format: ...>`` header (never a hardcoded
position), and one IS_WITHIN_GENE edge is emitted per distinct gene. An
un-annotated VCF still emits variants — only the gene edge is dropped. Only VEP
``CSQ`` is supported in v1.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from ..observation import VARIATION_OBS_COLUMNS, mint_id, obs_id, strip_version
from ._common import log as _log, log_skipped_samples, observation_fieldnames, stamp_row
from .spec import ReshapeSpec

_CSQ_FORMAT_RE = re.compile(r"Format:\s*([^\">]+)")
_GT_SPLIT_RE = re.compile(r"[/|]")

_GENE_EDGE_COLUMNS = ["variant_id", "gene_id"]


def _variant_id(chrom: str, pos: str, ref: str, alt: str) -> str:
    """Traditional variant key: ``CHROM-POS-REF-ALT`` (dash form).

    Dash, not the repo-wide ``:`` (docs/unique_ids.md), is deliberate: it keeps
    this id-space from ever colliding with GDC's colon-keyed one (see module
    docstring) while still going through the one shared minting primitive.
    """
    return mint_id(chrom, pos, ref, alt, sep="-")


def _csq_gene_index(meta_lines: list[str]) -> int | None:
    """Index of the VEP ``Gene`` sub-field, read from the CSQ header Format string."""
    for line in meta_lines:
        if line.startswith("##INFO=<ID=CSQ"):
            m = _CSQ_FORMAT_RE.search(line)
            if m:
                fields = [f.strip() for f in m.group(1).strip().split("|")]
                if "Gene" in fields:
                    return fields.index("Gene")
    return None


def _info_csq(info: str) -> list[str]:
    """Return the CSQ value's per-annotation entries, or [] if no CSQ present."""
    for kv in info.split(";"):
        if kv.startswith("CSQ="):
            return kv[len("CSQ="):].split(",")
    return []


def _genes_for_allele(csq_entries: list[str], allele: str, gene_idx: int) -> list[str]:
    """Distinct Ensembl gene ids annotated for one ALT allele (order-preserving)."""
    genes: list[str] = []
    for entry in csq_entries:
        parts = entry.split("|")
        if not parts or parts[0] != allele:
            continue
        if gene_idx < len(parts):
            gene = strip_version(parts[gene_idx].strip())
            if gene and gene not in genes:
                genes.append(gene)
    return genes


def read_vcf(spec: ReshapeSpec, raw_dir: Path, interim_dir: Path, *, dataset: str,
             sample_ids: set[str] | None = None, log: bool = True) -> list[Path]:
    """Read one VCF into observation + gene-edge TSVs; return the paths written."""
    src = raw_dir / spec.input
    obs_path = interim_dir / (spec.output or "variation_observation.tsv")
    gene_edge_path = interim_dir / (spec.gene_edge_output or "variant_gene.tsv")
    obs_path.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        _log(f"! skip vcf {spec.input}: source not found in raw", log)
        for p in (obs_path, gene_edge_path):
            if p.exists():
                p.unlink()
        return [obs_path, gene_edge_path]

    fieldnames = observation_fieldnames(VARIATION_OBS_COLUMNS, spec.assay)
    skipped_samples: set[str] = set()
    seen_gene_edges: set[tuple[str, str]] = set()

    with src.open(newline="", encoding="utf-8") as fh, \
            obs_path.open("w", newline="", encoding="utf-8") as obs_fh, \
            gene_edge_path.open("w", newline="", encoding="utf-8") as edge_fh:
        obs_writer = csv.DictWriter(obs_fh, fieldnames=fieldnames, delimiter="\t")
        obs_writer.writeheader()
        edge_writer = csv.DictWriter(edge_fh, fieldnames=_GENE_EDGE_COLUMNS, delimiter="\t")
        edge_writer.writeheader()

        meta_lines: list[str] = []
        sample_cols: list[tuple[int, str]] = []   # (column index, sample id)
        gene_idx: int | None = None

        for raw_line in fh:
            line = raw_line.rstrip("\n\r")
            if not line:
                continue
            if line.startswith("##"):
                meta_lines.append(line)
                continue
            if line.startswith("#CHROM"):
                gene_idx = _csq_gene_index(meta_lines)
                cols = line.lstrip("#").split("\t")
                # Fixed VCF columns end at INFO (8); FORMAT + samples follow.
                for i in range(9, len(cols)):
                    sample = cols[i]
                    if sample_ids is not None and sample not in sample_ids:
                        skipped_samples.add(sample)
                        continue
                    sample_cols.append((i, sample))
                continue

            parts = line.split("\t")
            if len(parts) < 8:
                continue
            chrom, pos, _id, ref, alt_field, _qual, filt = parts[:7]
            info = parts[7]
            fmt = parts[8].split(":") if len(parts) > 8 else []
            gt_idx = fmt.index("GT") if "GT" in fmt else None
            alts = alt_field.split(",")   # multi-allelic split
            csq_entries = _info_csq(info) if gene_idx is not None else []

            for a_index, alt in enumerate(alts, start=1):
                vid = _variant_id(chrom, pos, ref, alt)

                # Per-sample genotype re-indexing: a sample carries this allele
                # only if its GT references allele index a_index.
                carriers: list[str] = []
                for ci, sample in sample_cols:
                    if ci >= len(parts) or gt_idx is None:
                        continue
                    gt_parts = parts[ci].split(":")
                    gt = gt_parts[gt_idx] if gt_idx < len(gt_parts) else ""
                    called = [x for x in _GT_SPLIT_RE.split(gt) if x.isdigit()]
                    if str(a_index) in called:
                        carriers.append(sample)

                # An allele nobody carries yields no Variant node — so drop its
                # gene edge too, keeping IS_WITHIN_GENE endpoints resolvable.
                if not carriers:
                    continue

                # Opportunistic gene edges: one per distinct gene for this allele.
                if gene_idx is not None:
                    for gene in _genes_for_allele(csq_entries, alt, gene_idx):
                        if (vid, gene) not in seen_gene_edges:
                            seen_gene_edges.add((vid, gene))
                            edge_writer.writerow({"variant_id": vid, "gene_id": gene})

                for sample in carriers:
                    rec = stamp_row(fieldnames, spec.assay, dataset=dataset,
                                    source_file=spec.input)
                    rec["variant_observation_id"] = obs_id(sample, vid)
                    rec["sample_id"] = sample
                    rec["variant_id"] = vid
                    rec["chromosome"] = chrom
                    rec["position_start"] = pos
                    rec["position_end"] = str(int(pos) + len(ref) - 1) if pos.isdigit() else pos
                    rec["reference_allele"] = ref
                    rec["alternate_allele"] = alt
                    rec["filter_status"] = filt
                    obs_writer.writerow(rec)

    log_skipped_samples(skipped_samples, spec.input, log)
    return [obs_path, gene_edge_path]
