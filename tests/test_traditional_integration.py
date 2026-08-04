"""The primary test seam: one fused integration test over a synthetic traditional
dataset — sample metadata + expression matrix + methylation matrix + a small VCF.

Runs `standardise(dataset, "traditional")` (which internally runs the reshape
pre-pass) then `validate()`, asserting zero dangling references against the real
`config/` schema, `traditional.yaml`, and reused `omics.yaml`. This single seam
exercises reshape + interim overlay + both bindings + schema together, covering:

* genes_x_samples (expression) and samples_x_genes (methylation) orientation
* Ensembl version stripping
* assay stamping + dedup (expression/VCF) and assay-omitted graceful skip (methylation)
* sample-id reconciliation skip on a deliberately drifted header
* multi-allelic VCF split
* VEP CSQ gene edge present (annotated rows) vs absent (un-annotated row)
"""

from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent

import pytest

from src.standardise import standardise
from src.validate import validate

DATASET = "TRAD_FULL"

# Sample set: {S1, S2}. S_GHOST appears only in the expression matrix header.
METADATA = """
    sample_id\tsubject_id\tsex\tsample_type
    S1\tsubjX\tfemale\tPrimary Tumor
    S2\tsubjY\tmale\tPrimary Tumor
"""

# genes_x_samples, versioned Ensembl ids, plus a drifted S_GHOST column.
EXPRESSION = """
    gene_id\tS1\tS2\tS_GHOST
    ENSG00000141510.12\t5.2\t3.1\t9.9
    ENSG00000012048.21\t1.0\t0.5\t8.8
"""

# samples_x_genes (transposed), CpG probes as columns, no assay declared.
METHYLATION = """
    sample_id\tcg00000001\tcg00000002
    S1\t0.11\t0.22
    S2\t0.33\t0.44
"""

# Annotated rows (VEP CSQ) + a multi-allelic row + one un-annotated row.
VCF = """
    ##fileformat=VCFv4.2
    ##INFO=<ID=CSQ,Number=.,Type=String,Description="Consequence annotations from Ensembl VEP. Format: Allele|Consequence|IMPACT|SYMBOL|Gene">
    #CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\tS2
    17\t7674220\t.\tC\tT\t50\tPASS\tCSQ=T|missense|MODERATE|TP53|ENSG00000141510\tGT\t0/1\t0/0
    17\t7675000\t.\tA\tG,C\t60\tPASS\tCSQ=G|missense|MODERATE|G1|ENSG00000141510,C|missense|MODERATE|G2|ENSG00000012048\tGT\t1/2\t0/1
    1\t100\t.\tG\tA\t40\tPASS\t.\tGT\t0/1\t0/0
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    return path


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture
def std(tmp_path: Path):
    raw_root = tmp_path / "raw"
    _write(raw_root / DATASET / "sample_metadata.tsv", METADATA)
    _write(raw_root / DATASET / "expression_matrix.tsv", EXPRESSION)
    _write(raw_root / DATASET / "methylation_matrix.tsv", METHYLATION)
    _write(raw_root / DATASET / "variants.vcf", VCF)
    std_root = tmp_path / "standardised"
    standardise(DATASET, "traditional", raw_root=raw_root, out_root=std_root,
                interim_root=tmp_path / "interim", log=False)
    return std_root / DATASET


class TestConsolidatedFusedRun:
    def test_zero_dangling_references(self, std):
        result = validate(DATASET, standardised_root=std.parent)
        assert result["problems"] == [], "\n".join(result["problems"])

    # ── expression: genes_x_samples, Ensembl strip, drifted-header reconciliation ──
    def test_expression_ensembl_stripped(self, std):
        genes = {r["geneId"] for r in _rows(std / "nodes" / "Gene.csv")}
        assert {"ENSG00000141510", "ENSG00000012048"} <= genes

    def test_drifted_sample_reconciled_out(self, std):
        obs = _rows(std / "nodes" / "ExpressionObservation.csv")
        samples = {r["sampleId"] for r in obs}
        assert samples == {"S1", "S2"}          # S_GHOST skipped, not dangling
        assert len(obs) == 4                     # 2 genes × 2 real samples

    # ── methylation: samples_x_genes, CpG platform-qualified, assay omitted ──
    def test_methylation_transposed_and_cpg_ids(self, std):
        # No assay.platform_code declared -> "unknown:" qualification (see
        # docs/unique_ids.md §4 and config/mapping/traditional.yaml).
        cpgs = {r["cpgId"] for r in _rows(std / "nodes" / "CpGSite.csv")}
        assert cpgs == {"unknown:cg00000001", "unknown:cg00000002"}
        assert len(_rows(std / "nodes" / "MethylationObservation.csv")) == 4

    def test_methylation_assay_omitted_but_expression_assay_present(self, std):
        assays = {r["assayId"] for r in _rows(std / "nodes" / "Assay.csv")}
        # expression + VCF assays present; methylation contributed none (omitted).
        assert "traditional-rnaseq-grch38" in assays
        assert "traditional-wgs-grch38" in assays
        assert "" not in assays                  # blank assay never becomes a node

    # ── VCF: multi-allelic split, VEP present vs absent ──
    def test_multiallelic_split(self, std):
        variants = {r["variantId"] for r in _rows(std / "nodes" / "Variant.csv")}
        assert {"17-7675000-A-G", "17-7675000-A-C"} <= variants   # split alleles

    def test_vep_gene_edges_present_and_absent(self, std):
        edges = {(e["startId"], e["endId"])
                 for e in _rows(std / "edges" / "IS_WITHIN_GENE.csv")}
        # present: annotated variants link to shared Gene nodes
        assert ("17-7674220-C-T", "ENSG00000141510") in edges
        assert ("17-7675000-A-C", "ENSG00000012048") in edges
        # absent: the un-annotated variant lands with no gene edge
        assert "1-100-G-A" in {r["variantId"] for r in _rows(std / "nodes" / "Variant.csv")}
        assert not any(start == "1-100-G-A" for start, _ in edges)
