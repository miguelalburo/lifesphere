"""The concatenation-based id-minting standard (docs/unique_ids.md).

Covers the shared primitive (`mint_id`), the extract-time assay/variant ids
built from it (colon by default, with the one documented dash exception for
the traditional-path Variant id), and the newly-registered `Survival` derived
key (standardise re-mints `survivalId`, ignoring the raw file's own column —
same guarantee already pinned for the observation surrogate keys in
test_derived_keys.py).
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.extract.omics import expression, methylation, variation
from src.observation import DERIVED_KEYS, ID_SEPARATOR, mint_id, obs_id
from src.reshape.vcf import _variant_id as traditional_variant_id
from src.standardise import standardise

DATASET = "MINI_IDS"


# ── unit: the shared primitive ──────────────────────────────────────────

def test_mint_id_joins_with_default_colon_separator():
    assert mint_id("a", "b", "c") == "a:b:c"
    assert ID_SEPARATOR == ":"


def test_mint_id_accepts_a_custom_separator():
    assert mint_id("a", "b", "c", sep="-") == "a-b-c"


def test_obs_id_is_mint_id_with_two_parts():
    assert obs_id("sample-1", "gene-1") == mint_id("sample-1", "gene-1") == "sample-1:gene-1"


# ── unit: extract-time assay ids are colon-form via mint_id ────────────

def test_expression_assay_id_is_colon_separated():
    file_meta = {
        "platform": "Illumina",
        "experimental_strategy": "RNA-Seq",
        "analysis": {"workflow_type": "STAR - Counts"},
    }
    assert expression.assay_id(file_meta) == "Illumina:RNA-Seq:STAR - Counts"


def test_variation_assay_id_is_colon_separated():
    file_meta = {
        "platform": "Illumina",
        "experimental_strategy": "WGS",
        "analysis": {"workflow_type": "MuTect2 Variant Aggregation and Masking"},
    }
    assert variation.assay_id(file_meta) == "Illumina:WGS:MuTect2 Variant Aggregation and Masking"


def test_methylation_assay_id_is_colon_separated():
    file_meta = {"platform": "Illumina Methylation EPIC", "experimental_strategy": "Methylation Array"}
    assert methylation.assay_id(file_meta) == "Illumina Methylation EPIC:Methylation Array:Methylation Beta Value"


def test_assay_id_falls_back_to_unknown_for_missing_fields():
    assert expression.assay_id({}) == "unknown:unknown:unknown"


# ── unit: the two Variant id-spaces stay separate by construction ──────

def test_gdc_variant_id_uses_colon():
    assert variation._variant_id("chr1", "100", "A", "T") == "chr1:100:A:T"


def test_traditional_variant_id_uses_dash():
    assert traditional_variant_id("chr1", "100", "A", "T") == "chr1-100-A-T"


def test_gdc_and_traditional_variant_ids_never_collide_in_form():
    gdc = variation._variant_id("chr1", "100", "A", "T")
    trad = traditional_variant_id("chr1", "100", "A", "T")
    assert gdc != trad


# ── unit: Survival is registered in DERIVED_KEYS ────────────────────────

def test_survival_builder_matches_mint_id():
    builder = DERIVED_KEYS["Survival"]
    assert builder.sources == ("case_id", "survival_type")
    assert builder.mint(["case-1", "OS"]) == mint_id("case-1", "OS") == "case-1:OS"


# ── behaviour: standardise ignores survival.tsv's own survival_id column ──

def _write_survival(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["case_id", "case_submitter_id", "survival_id", "survival_type", "event", "time_days"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_standardise_mints_survival_id_ignoring_source_column(tmp_path):
    raw_root = tmp_path / "raw"
    std_root = tmp_path / "standardised"
    _write_survival(raw_root / DATASET / "survival.tsv", [
        {"case_id": "case-1", "case_submitter_id": "TCGA-01", "survival_id": "WRONG-DASH-FORM",
         "survival_type": "OS", "event": "1", "time_days": "365"},
    ])

    standardise(DATASET, "survival", raw_root=raw_root, out_root=std_root, log=False)

    node_rows = _rows(std_root / DATASET / "nodes" / "Survival.csv")
    assert [r["survivalId"] for r in node_rows] == ["case-1:OS"]

    edge_rows = _rows(std_root / DATASET / "edges" / "HAS_SURVIVAL_RECORD.csv")
    assert [r["endId"] for r in edge_rows] == ["case-1:OS"]


def test_survival_row_skipped_when_survival_type_is_empty(tmp_path):
    raw_root = tmp_path / "raw"
    std_root = tmp_path / "standardised"
    _write_survival(raw_root / DATASET / "survival.tsv", [
        {"case_id": "case-1", "case_submitter_id": "TCGA-01", "survival_id": "x",
         "survival_type": "", "event": "1", "time_days": "365"},
    ])

    standardise(DATASET, "survival", raw_root=raw_root, out_root=std_root, log=False)

    node_rows = _rows(std_root / DATASET / "nodes" / "Survival.csv")
    assert node_rows == []
