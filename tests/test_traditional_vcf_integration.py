"""Integration test: fused `standardise(dataset, "traditional")` for a VCF.

A bioinformatician's own VCF becomes graph nodes through the one fused command.
The VCF reader's observation + gene-edge TSVs bind through the reused omics
mapping (plus the traditional IS_WITHIN_GENE / Gene overrides), and validate()
sees zero dangling references. A VEP-annotated VCF yields IS_WITHIN_GENE edges
into shared Gene nodes; an un-annotated VCF validates clean with that edge absent.
"""

from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent

import pytest

from src.standardise import standardise
from src.validate import validate

METADATA = """
    sample_id\tsubject_id\tsex
    sampleA\tsubj1\tfemale
    sampleB\tsubj2\tmale
"""

VCF_ANNOTATED = """
    ##fileformat=VCFv4.2
    ##INFO=<ID=CSQ,Number=.,Type=String,Description="Consequence annotations from Ensembl VEP. Format: Allele|Consequence|IMPACT|SYMBOL|Gene">
    #CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsampleA\tsampleB
    17\t7674220\t.\tC\tT\t50\tPASS\tCSQ=T|missense|MODERATE|TP53|ENSG00000141510\tGT\t0/1\t0/0
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


def _csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _run(tmp_path: Path, dataset: str, metadata: str, vcf: str):
    raw_root = tmp_path / "raw"
    std_root = tmp_path / "standardised"
    interim_root = tmp_path / "interim"
    _write(raw_root / dataset / "sample_metadata.tsv", metadata)
    _write(raw_root / dataset / "variants.vcf", vcf)
    standardise(dataset, "traditional", raw_root=raw_root, out_root=std_root,
                interim_root=interim_root, log=False)
    return std_root


class TestAnnotatedVcfEndToEnd:
    DATASET = "TRAD_VCF_ANNOT"

    @pytest.fixture
    def std(self, tmp_path):
        return _run(tmp_path, self.DATASET, METADATA, VCF_ANNOTATED)

    def test_variant_and_observation_nodes(self, std):
        variants = _csv_rows(std / self.DATASET / "nodes" / "Variant.csv")
        obs = _csv_rows(std / self.DATASET / "nodes" / "VariantObservation.csv")
        assert {r["variantId"] for r in variants} == {
            "17-7674220-C-T", "17-7675000-A-G", "17-7675000-A-C"}
        assert len(obs) == 4

    def test_variant_observation_edges(self, std):
        has_obs = _csv_rows(std / self.DATASET / "edges" / "HAS_VARIANT_OBSERVATION.csv")
        observed = _csv_rows(std / self.DATASET / "edges" / "OBSERVED_VARIANT.csv")
        assert len(has_obs) == 4
        assert len(observed) == 4

    def test_is_within_gene_into_shared_gene(self, std):
        genes = {r["geneId"] for r in _csv_rows(std / self.DATASET / "nodes" / "Gene.csv")}
        edges = _csv_rows(std / self.DATASET / "edges" / "IS_WITHIN_GENE.csv")
        assert genes == {"ENSG00000141510", "ENSG00000012048"}
        pairs = {(e["startId"], e["endId"]) for e in edges}
        assert ("17-7674220-C-T", "ENSG00000141510") in pairs
        assert ("17-7675000-A-C", "ENSG00000012048") in pairs
        assert len(edges) == 3

    def test_zero_dangling(self, std):
        result = validate(self.DATASET, standardised_root=std)
        assert result["problems"] == [], "\n".join(result["problems"])


class TestUnannotatedVcfEndToEnd:
    DATASET = "TRAD_VCF_BARE"

    @pytest.fixture
    def std(self, tmp_path):
        return _run(tmp_path, self.DATASET, "sample_id\tsubject_id\nsampleA\tsubj1\n",
                    VCF_UNANNOTATED)

    def test_variant_lands_without_gene_edge(self, std):
        variants = _csv_rows(std / self.DATASET / "nodes" / "Variant.csv")
        assert {r["variantId"] for r in variants} == {"17-7674220-C-T"}
        # gene edge absent (no rows)
        assert _csv_rows(std / self.DATASET / "edges" / "IS_WITHIN_GENE.csv") == []

    def test_zero_dangling(self, std):
        result = validate(self.DATASET, standardised_root=std)
        assert result["problems"] == [], "\n".join(result["problems"])
