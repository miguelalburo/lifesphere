"""Integration test: fused `standardise(dataset, "traditional")` for methylation.

Proves the matrix melt is genuinely generic: a methylation beta matrix flows
through the *same* reshape_dataset matrix path and the *same* fused command as
expression, producing MethylationObservation / CpGSite nodes and their edges with
zero dangling references. No methylation-specific reshaper.
"""

from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent

import pytest

from src.standardise import standardise
from src.validate import validate

DATASET = "TRAD_METH"

METADATA = """
    sample_id\tsubject_id\tsex
    sampleA\tsubj1\tfemale
    sampleB\tsubj2\tmale
"""

# samples_x_genes (samples on rows, CpG probes on columns), beta values —
# matches the transposed orientation declared in the real traditional.yaml.
METH_MATRIX = """
    sample_id\tcg00000001\tcg00000002
    sampleA\t0.12\t0.56
    sampleB\t0.85\t0.30
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    return path


def _csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture
def dirs(tmp_path: Path):
    raw_root = tmp_path / "raw"
    interim_root = tmp_path / "interim"
    std_root = tmp_path / "standardised"
    _write(raw_root / DATASET / "sample_metadata.tsv", METADATA)
    _write(raw_root / DATASET / "methylation_matrix.tsv", METH_MATRIX)

    standardise(DATASET, "traditional", raw_root=raw_root, out_root=std_root,
                interim_root=interim_root, log=False)
    return {"raw": raw_root, "interim": interim_root, "std": std_root}


class TestFusedMethylation:
    def test_methylation_observation_count(self, dirs):
        rows = _csv_rows(dirs["std"] / DATASET / "nodes" / "MethylationObservation.csv")
        assert len(rows) == 4  # 2 CpGs × 2 samples

    def test_cpg_probe_ids_used_as_is_and_deduped(self, dirs):
        rows = _csv_rows(dirs["std"] / DATASET / "nodes" / "CpGSite.csv")
        assert {r["cpgId"] for r in rows} == {"cg00000001", "cg00000002"}

    def test_beta_values_bound(self, dirs):
        rows = _csv_rows(dirs["std"] / DATASET / "nodes" / "MethylationObservation.csv")
        assert {r["betaValue"] for r in rows} == {"0.12", "0.85", "0.56", "0.30"}

    def test_methylation_edges(self, dirs):
        has_obs = _csv_rows(dirs["std"] / DATASET / "edges" / "HAS_METHYLATION_OBSERVATION.csv")
        measures = _csv_rows(dirs["std"] / DATASET / "edges" / "MEASURES_CPG.csv")
        assert len(has_obs) == 4
        assert len(measures) == 4

    def test_no_expression_nodes_emitted(self, dirs):
        # Expression matrix absent -> its melt skipped cleanly; no ExpressionObservation.
        assert not (dirs["std"] / DATASET / "nodes" / "ExpressionObservation.csv").exists()


class TestValidateZeroDangling:
    def test_zero_problems(self, dirs):
        result = validate(DATASET, standardised_root=dirs["std"])
        assert result["problems"] == [], "\n".join(result["problems"])
