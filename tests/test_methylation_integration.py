"""Integration test: methylation reshape → standardise (omics profile) → validate.

Pipeline under test:
  1. Synthetic GDC beta-value TSVs written to tmp raw dir.
  2. reshape() merges them into methylation_observation.tsv.
  3. standardise("MINI", "omics") writes node/edge CSVs.
  4. Sample.csv pre-populated to simulate the clinical standardise pass.
  5. validate() run → zero dangling references.

Uses the real config/ schema and config/mapping/omics.yaml so that any drift
between the mapping and the schema is caught here.
"""

from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent

import pytest

from src.extract.omics.methylation import reshape
from src.standardise import standardise
from src.validate import validate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BETA_FILE = dedent("""\
    Composite Element REF\tBeta_value\tChromosome\tStart\tEnd\tGene_Symbol\tGene_Type\tTranscript_ID\tPosition_to_TSS\tCGI_Coordinate\tFeature_Type
    cg00000001\t0.1234\tchr1\t10000\t10038\tTP53\tprotein_coding\tENST00000269305\t-100\tchr1:9800-10100\tS_Shore
    cg00000002\t0.5678\tchr17\t50000\t50038\tBRCA1\tprotein_coding\tENST00000357654\t200\t.\tIsland
""")

DATASET = "METHYLATION_MINI"
SAMPLE_ID = "al-meth-001"
ASSAY_ID = "Illumina Human Methylation 450|Methylation Array|Methylation Beta Value"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    return path


def _csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def pipeline_dirs(tmp_path: Path):
    """Build raw dir, run reshape, standardise omics, then pre-write Sample.csv."""
    raw_root = tmp_path / "raw"
    std_root = tmp_path / "standardised"
    dataset_raw = raw_root / DATASET

    # 1. Write two synthetic beta-value files (two aliquots, same two CpGs)
    f1 = dataset_raw / "methylation" / "file-m001" / "sample1_methylation.tsv"
    f2 = dataset_raw / "methylation" / "file-m002" / "sample2_methylation.tsv"
    _write(f1, BETA_FILE)
    _write(f2, BETA_FILE)

    entries = [
        {"path": f1, "sample_id": SAMPLE_ID, "assay_id": ASSAY_ID,
         "source_file": "file-m001", "pipeline_version": "SeSAMe"},
        {"path": f2, "sample_id": "al-meth-002", "assay_id": ASSAY_ID,
         "source_file": "file-m002", "pipeline_version": "SeSAMe"},
    ]

    # 2. Reshape → methylation_observation.tsv
    obs_path = dataset_raw / "methylation_observation.tsv"
    reshape(entries, obs_path, dataset=DATASET)

    # 3. Standardise with omics profile (real schema + omics.yaml)
    standardise(DATASET, "omics", raw_root=raw_root, out_root=std_root, log=False)

    # 4. Pre-populate Sample.csv (simulates clinical standardise pass)
    sample_csv = std_root / DATASET / "nodes" / "Sample.csv"
    _write(sample_csv, f"sampleId\n{SAMPLE_ID}\nal-meth-002\n")

    return {"raw": raw_root, "std": std_root}


# ---------------------------------------------------------------------------
# Node CSV assertions
# ---------------------------------------------------------------------------

class TestOmicsStandardise:
    def test_methylation_observation_node_csv_written(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "nodes" / "MethylationObservation.csv"
        assert path.exists()

    def test_cpg_site_node_csv_written(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "nodes" / "CpGSite.csv"
        assert path.exists()

    def test_assay_node_csv_written(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "nodes" / "Assay.csv"
        assert path.exists()

    def test_methylation_observation_count(self, pipeline_dirs):
        # 2 samples × 2 CpGs = 4 observation rows
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "MethylationObservation.csv")
        assert len(rows) == 4

    def test_cpg_site_dedup(self, pipeline_dirs):
        # 2 unique CpG sites across 2 samples
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "CpGSite.csv")
        assert len(rows) == 2

    def test_assay_dedup(self, pipeline_dirs):
        # 1 unique assay across both samples
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "Assay.csv")
        assert len(rows) == 1

    def test_beta_value_populated(self, pipeline_dirs):
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "MethylationObservation.csv")
        values = {r.get("betaValue") for r in rows}
        assert values == {"0.1234", "0.5678"}

    def test_num_cpg_sites_populated(self, pipeline_dirs):
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "MethylationObservation.csv")
        assert all(r.get("numCpGSites") == "1" for r in rows)

    def test_modification_type_populated(self, pipeline_dirs):
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "MethylationObservation.csv")
        assert all(r.get("modificationType") == "5mC" for r in rows)

    def test_cpg_annotation_on_cpg_site(self, pipeline_dirs):
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "CpGSite.csv")
        row = next(r for r in rows if r["cpgId"] == "cg00000001")
        assert row.get("chromosome") == "chr1"
        assert row.get("startPosition") == "10000"
        assert row.get("geneSymbol") == "TP53"

# ---------------------------------------------------------------------------
# Edge CSV assertions
# ---------------------------------------------------------------------------

    def test_has_methylation_observation_edge(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "edges" / "HAS_METHYLATION_OBSERVATION.csv"
        assert path.exists()
        rows = _csv_rows(path)
        assert len(rows) == 4  # 2 samples × 2 CpGs

    def test_measures_cpg_edge(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "edges" / "MEASURES_CPG.csv"
        assert path.exists()
        rows = _csv_rows(path)
        assert len(rows) == 4

    def test_assayed_by_edge(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "edges" / "ASSAYED_BY.csv"
        assert path.exists()
        rows = _csv_rows(path)
        # 2 samples × 1 assay = 2 edges (deduped)
        assert len(rows) == 2

# ---------------------------------------------------------------------------
# Validate: zero dangling references
# ---------------------------------------------------------------------------

class TestValidateZeroDangling:
    def test_zero_problems(self, pipeline_dirs):
        result = validate(DATASET, standardised_root=pipeline_dirs["std"])
        assert result["problems"] == [], "\n".join(result["problems"])

    def test_node_types_present(self, pipeline_dirs):
        result = validate(DATASET, standardised_root=pipeline_dirs["std"])
        # Sample (pre-written), MethylationObservation, CpGSite, Assay
        assert result["node_types"] == 4

    def test_edge_count(self, pipeline_dirs):
        result = validate(DATASET, standardised_root=pipeline_dirs["std"])
        # HAS_METHYLATION_OBSERVATION(4) + MEASURES_CPG(4) + ASSAYED_BY(2) = 10
        assert result["edges"] == 10
