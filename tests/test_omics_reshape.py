"""Tests for the omics reshape bridge (src/extract/omics_reshape).

Unit tests assert each reshaper's contract on hand-built concatenated matrices
(feature dedup, surrogate ids, ensembl version strip, MAF sample linkage). An
integration test then runs reshape -> standardise -> validate to prove the emitted
TSVs match the real schemas and the Sample->Observation->Feature chain resolves
with no dangling edges.
"""

import csv
from pathlib import Path

import pytest

from src.extract.omics_reshape import (
    reshape_expression,
    reshape_methylation,
    reshape_variation,
)
from src.load.validate import validate
from src.standardise.run import run

BASE = "OMX"


def _tsv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(header)
        w.writerows(rows)


def _read(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


# --------------------------------------------------------------------------- #
# Unit                                                                          #
# --------------------------------------------------------------------------- #

def test_reshape_expression_dedups_genes_and_strips_version(tmp_path):
    _tsv(tmp_path / f"{BASE}.expression.matrix.tsv",
         ["case_id", "case_submitter_id", "file_id", "aliquot_id",
          "gene_id", "gene_name", "gene_type",
          "unstranded", "tpm_unstranded", "fpkm_unstranded", "fpkm_uq_unstranded"],
         [["c1", "S1", "f1", "al1", "ENSG000001.15", "TP53", "protein_coding", "10", "5.5", "2.2", "3.3"],
          # same gene, different aliquot/file -> gene deduped, two observations
          ["c1", "S1", "f2", "al2", "ENSG000001.9", "TP53", "protein_coding", "20", "7.7", "4.4", "6.6"],
          ["c1", "S1", "f1", "al1", "ENSG000002.1", "EGFR", "protein_coding", "0", "0.0", "0.0", "0.0"]])

    n_genes, n_obs = reshape_expression(tmp_path / f"{BASE}.expression.matrix.tsv", tmp_path, BASE)
    assert (n_genes, n_obs) == (2, 3)

    genes = _read(tmp_path / f"{BASE}.gene.tsv")
    assert {g["ensembl"] for g in genes} == {"ENSG000001", "ENSG000002"}  # version stripped

    obs = _read(tmp_path / f"{BASE}.gene_expression.tsv")
    o = obs[0]
    assert o["expression_id"] == "f1:ENSG000001"          # deterministic surrogate
    assert o["sample_id"] == "al1" and o["gene_ensembl"] == "ENSG000001"
    assert o["tpm"] == "5.5" and o["fpkm"] == "2.2"


def test_reshape_methylation(tmp_path):
    _tsv(tmp_path / f"{BASE}.methylation.matrix.tsv",
         ["case_id", "case_submitter_id", "file_id", "aliquot_id", "cpg", "beta_value"],
         [["c1", "S1", "f1", "al1", "cg001", "0.83"],
          ["c1", "S1", "f1", "al1", "cg002", "0.12"]])

    n_cpg, n_obs = reshape_methylation(tmp_path / f"{BASE}.methylation.matrix.tsv", tmp_path, BASE)
    assert (n_cpg, n_obs) == (2, 2)
    obs = {o["methylation_id"]: o for o in _read(tmp_path / f"{BASE}.methylation.tsv")}
    assert obs["f1:cg001"]["sample_id"] == "al1"
    assert obs["f1:cg001"]["beta_value"] == "0.83"


def test_reshape_variation_variant_key_sample_and_vaf(tmp_path):
    _tsv(tmp_path / f"{BASE}.variation.matrix.tsv",
         ["case_id", "case_submitter_id", "file_id", "aliquot_id",
          "Hugo_Symbol", "Gene", "Chromosome", "Start_Position",
          "Reference_Allele", "Tumor_Seq_Allele2", "Variant_Type",
          "Variant_Classification", "Consequence", "IMPACT",
          "Tumor_Sample_UUID", "t_depth", "t_alt_count"],
         [["c1", "S1", "f1", "", "TP53", "ENSG000001.2", "chr17", "7577120",
           "C", "T", "SNP", "Missense_Mutation", "missense_variant", "MODERATE",
           "tumaliq1", "100", "25"]])

    n_var, n_obs = reshape_variation(tmp_path / f"{BASE}.variation.matrix.tsv", tmp_path, BASE)
    assert (n_var, n_obs) == (1, 1)

    var = _read(tmp_path / f"{BASE}.variant.tsv")[0]
    assert var["variant_id"] == "chr17:7577120:C>T"
    assert var["gene_ensembl"] == "ENSG000001"           # version stripped

    call = _read(tmp_path / f"{BASE}.somatic_mutation.tsv")[0]
    assert call["variant_id"] == "chr17:7577120:C>T"
    assert call["sample_id"] == "tumaliq1"               # MAF row aliquot, not file
    assert call["vaf"] == "0.2500"


# --------------------------------------------------------------------------- #
# Integration: reshape -> standardise -> validate                              #
# --------------------------------------------------------------------------- #

@pytest.fixture
def omics_std(tmp_path):
    raw = tmp_path / "raw"
    out = tmp_path / "std"
    raw.mkdir()

    # Sample node (Sample = aliquot): ids al1, al2 so omics sample_id resolves.
    _tsv(raw / f"{BASE}.sample.tsv",
         ["case_id", "case_submitter_id", "sample_id", "sample_sample_type"],
         [["c1", "S1", "al1", "Primary Tumor"],
          ["c1", "S1", "al2", "Primary Tumor"]])

    # Raw concatenated omics matrices (as omics.py would emit them).
    _tsv(raw / f"{BASE}.expression.matrix.tsv",
         ["case_id", "case_submitter_id", "file_id", "aliquot_id",
          "gene_id", "gene_name", "gene_type", "unstranded",
          "tpm_unstranded", "fpkm_unstranded", "fpkm_uq_unstranded"],
         [["c1", "S1", "f1", "al1", "ENSG000001.15", "TP53", "protein_coding", "10", "5.5", "2.2", "3.3"],
          ["c1", "S1", "f2", "al2", "ENSG000001.9", "TP53", "protein_coding", "20", "7.7", "4.4", "6.6"]])
    _tsv(raw / f"{BASE}.methylation.matrix.tsv",
         ["case_id", "case_submitter_id", "file_id", "aliquot_id", "cpg", "beta_value"],
         [["c1", "S1", "m1", "al1", "cg001", "0.83"]])

    from src.extract.omics_reshape import reshape_omics
    reshape_omics(raw, BASE, ["expression", "methylation"])

    run(raw, out)
    return out


def test_omics_chain_resolves_with_no_dangling(omics_std):
    # Feature + observation + Sample nodes all present.
    assert {g["id"] for g in _read_csv(omics_std, "nodes", "Gene")} == {"ENSG000001"}
    expr = _read_csv(omics_std, "nodes", "Expression")
    assert len(expr) == 2
    assert {s["id"] for s in _read_csv(omics_std, "nodes", "Sample")} == {"al1", "al2"}

    # Sample -> Expression -> Gene chain wired.
    has_expr = _read_csv(omics_std, "edges", "HAS_EXPRESSION")
    of_gene = _read_csv(omics_std, "edges", "OF_GENE")
    assert {e["source_id"] for e in has_expr} == {"al1", "al2"}
    assert {e["target_id"] for e in of_gene} == {"ENSG000001"}

    # No dangling omics endpoints.
    reports = {r.label: r for r in validate(omics_std)}
    for label in ("HAS_EXPRESSION", "OF_GENE", "HAS_METHYLATION", "AT_CPG"):
        assert reports[label].ok, f"{label} has dangling endpoints"


def _read_csv(std: Path, kind: str, label: str) -> list[dict]:
    with open(std / kind / f"{label}.csv", newline="") as f:
        return list(csv.DictReader(f))
