"""Reshape-door unit tests for the dedicated VCF reader (``type: vcf``).

Assert on the emitted variation observation + gene-edge TSVs. Covers: dispatch
via reshape_dataset, multi-allelic split with per-sample genotype re-indexing,
variantId = CHROM-POS-REF-ALT, VEP CSQ gene edges located via the header format
(one per distinct gene), and graceful degrade on an un-annotated VCF.
"""

from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent

from src.reshape import parse_specs, reshape_dataset

DATASET = "TRAD_VCF"

VCF_ANNOTATED = """
    ##fileformat=VCFv4.2
    ##INFO=<ID=CSQ,Number=.,Type=String,Description="Consequence annotations from Ensembl VEP. Format: Allele|Consequence|IMPACT|SYMBOL|Gene">
    #CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsampleA\tsampleB
    17\t7674220\t.\tC\tT\t50\tPASS\tCSQ=T|missense|MODERATE|TP53|ENSG00000141510.9\tGT\t0/1\t0/0
    17\t7675000\t.\tA\tG,C\t60\tPASS\tCSQ=G|missense|MODERATE|G1|ENSG00000141510,C|missense|MODERATE|G2|ENSG00000012048\tGT\t1/2\t0/1
"""

VCF_UNANNOTATED = """
    ##fileformat=VCFv4.2
    #CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsampleA
    17\t7674220\t.\tC\tT\t50\tPASS\t.\tGT\t0/1
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    return path


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _run(tmp_path: Path, vcf: str, *, sample_ids=None):
    raw_root = tmp_path / "raw"
    interim_root = tmp_path / "interim"
    _write(raw_root / DATASET / "variants.vcf", vcf)
    specs = parse_specs([{
        "type": "vcf",
        "input": "variants.vcf",
        "output": "variation_observation.tsv",
        "gene_edge_output": "variant_gene.tsv",
    }])
    reshape_dataset(DATASET, specs, raw_root=raw_root, interim_root=interim_root,
                    sample_ids=sample_ids, log=False)
    base = interim_root / DATASET
    return _read(base / "variation_observation.tsv"), _read(base / "variant_gene.tsv")


class TestAnnotatedVcf:
    def test_multiallelic_split_and_genotype_reindex(self, tmp_path):
        obs, _ = _run(tmp_path, VCF_ANNOTATED)
        pairs = {(r["sample_id"], r["variant_id"]) for r in obs}
        # row1: sampleA 0/1 carries T; sampleB 0/0 carries nothing.
        assert ("sampleA", "17-7674220-C-T") in pairs
        assert not any(s == "sampleB" and v == "17-7674220-C-T" for s, v in pairs)
        # row2: sampleA 1/2 carries both G and C; sampleB 0/1 carries only G.
        assert ("sampleA", "17-7675000-A-G") in pairs
        assert ("sampleA", "17-7675000-A-C") in pairs
        assert ("sampleB", "17-7675000-A-G") in pairs
        assert ("sampleB", "17-7675000-A-C") not in pairs
        assert len(obs) == 4

    def test_variant_id_dash_form(self, tmp_path):
        obs, _ = _run(tmp_path, VCF_ANNOTATED)
        ids = {r["variant_id"] for r in obs}
        assert ids == {"17-7674220-C-T", "17-7675000-A-G", "17-7675000-A-C"}

    def test_variant_reference_columns(self, tmp_path):
        obs, _ = _run(tmp_path, VCF_ANNOTATED)
        row = next(r for r in obs if r["variant_id"] == "17-7674220-C-T")
        assert row["chromosome"] == "17"
        assert row["position_start"] == "7674220"
        assert row["reference_allele"] == "C"
        assert row["alternate_allele"] == "T"
        assert row["filter_status"] == "PASS"

    def test_gene_edges_per_distinct_gene(self, tmp_path):
        _, edges = _run(tmp_path, VCF_ANNOTATED)
        pairs = {(e["variant_id"], e["gene_id"]) for e in edges}
        # Gene sub-field located via header Format; version stripped.
        assert ("17-7674220-C-T", "ENSG00000141510") in pairs
        assert ("17-7675000-A-G", "ENSG00000141510") in pairs
        assert ("17-7675000-A-C", "ENSG00000012048") in pairs
        assert len(edges) == 3


class TestUnannotatedVcf:
    def test_variants_still_emitted_no_gene_edges(self, tmp_path):
        obs, edges = _run(tmp_path, VCF_UNANNOTATED)
        assert len(obs) == 1
        assert obs[0]["variant_id"] == "17-7674220-C-T"
        assert edges == []   # only the gene edge is dropped
