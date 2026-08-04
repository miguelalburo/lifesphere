"""Integration test: variation reshape → standardise (omics profile) → validate.

Pipeline under test:
  1. Synthetic MAF files written to tmp raw dir.
  2. reshape() merges them into variation_observation.tsv.
  3. standardise("MINI", "omics") writes node/edge CSVs.
  4. Sample.csv pre-populated to simulate the clinical standardise pass.
  5. validate() run → zero dangling references.

Also verifies that the variation layer's Gene nodes converge with the
expression layer's Gene nodes (same version-stripped geneId).
"""

from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent

import pytest

from src.extract.omics.expression import reshape as expr_reshape
from src.extract.omics.variation import reshape as var_reshape
from src.standardise import standardise
from src.validate import validate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MAF_FILE = dedent("""\
    # GDC MAF comment
    Hugo_Symbol\tChromosome\tStart_Position\tEnd_Position\tVariant_Classification\tVariant_Type\tReference_Allele\tTumor_Seq_Allele2\tTumor_Sample_Barcode\tGene\tIMPACT\tt_depth\tt_alt_count\tn_depth\tn_alt_count\tFILTER
    TP53\t17\t7674220\t7674220\tMissense_Mutation\tSNP\tC\tT\tvar-al-001\tENSG00000141510.11\tMODERATE\t100\t25\t80\t0\tPASS
    BRCA1\t17\t43092912\t43092912\tFrameshift_Del\tDEL\tAGTC\t-\tvar-al-001\tENSG00000012048.22\tHIGH\t80\t40\t70\t0\tPASS
""")

# Expression STAR-Counts fixture uses same two Ensembl IDs (different versions)
STAR_COUNTS = dedent("""\
    N_unmapped\t0\t0\t0
    N_multimapping\t0\t0\t0
    N_noFeature\t0\t0\t0
    N_ambiguous\t0\t0\t0
    gene_id\tgene_name\tgene_type\tunstranded\tstranded_first\tstranded_second\ttpm_unstranded\tfpkm_unstranded\tfpkm_uq_unstranded
    ENSG00000141510.12\tTP53\tprotein_coding\t1000\t500\t500\t5.25\t2.10\t2.60
    ENSG00000012048.21\tBRCA1\tprotein_coding\t2000\t1000\t1000\t10.50\t4.20\t5.10
""")

DATASET = "VARIATION_MINI"
SAMPLE_ID = "var-al-001"
SAMPLE_ID_2 = "var-al-002"
ASSAY_ID = "Illumina|WXS|Varscan2"
EXPR_ASSAY_ID = "Illumina|RNA-Seq|STAR - Counts"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    return path


def _csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Fixture: variation-only pipeline
# ---------------------------------------------------------------------------

@pytest.fixture
def pipeline_dirs(tmp_path: Path):
    """Build raw dir, run reshape, standardise omics, then pre-write Sample.csv."""
    raw_root = tmp_path / "raw"
    std_root = tmp_path / "standardised"
    dataset_raw = raw_root / DATASET

    # 1. Two MAF files (same mutations, different aliquots)
    f1 = dataset_raw / "variation" / "file-v001" / "project_maf1.maf"
    f2 = dataset_raw / "variation" / "file-v002" / "project_maf2.maf"
    maf2 = MAF_FILE.replace(SAMPLE_ID, SAMPLE_ID_2)
    _write(f1, MAF_FILE)
    _write(f2, maf2)

    entries = [
        {"path": f1, "assay_id": ASSAY_ID,
         "source_file": "file-v001", "pipeline_version": "Varscan2"},
        {"path": f2, "assay_id": ASSAY_ID,
         "source_file": "file-v002", "pipeline_version": "Varscan2"},
    ]

    # 2. Reshape → variation_observation.tsv
    obs_path = dataset_raw / "variation_observation.tsv"
    var_reshape(entries, obs_path, dataset=DATASET)

    # 3. Standardise with omics profile
    standardise(DATASET, "omics", raw_root=raw_root, out_root=std_root, log=False)

    # 4. Pre-populate Sample.csv
    sample_csv = std_root / DATASET / "nodes" / "Sample.csv"
    _write(sample_csv, f"sampleId\n{SAMPLE_ID}\n{SAMPLE_ID_2}\n")

    return {"raw": raw_root, "std": std_root}


# ---------------------------------------------------------------------------
# Fixture: variation + expression together (gene convergence test)
# ---------------------------------------------------------------------------

@pytest.fixture
def combined_dirs(tmp_path: Path):
    """Both variation and expression in one raw dir → shared Gene dimension."""
    raw_root = tmp_path / "raw"
    std_root = tmp_path / "standardised"
    dataset_raw = raw_root / DATASET

    # Variation MAF (plain text fixture)
    maf_path = dataset_raw / "variation" / "file-v001" / "project.maf"
    _write(maf_path, MAF_FILE)
    var_entries = [{"path": maf_path, "assay_id": ASSAY_ID,
                    "source_file": "file-v001", "pipeline_version": "Varscan2"}]
    var_reshape(var_entries, dataset_raw / "variation_observation.tsv", dataset=DATASET)

    # Expression STAR-Counts
    expr_path = dataset_raw / "expression" / "file-e001" / "sample_STAR.tsv"
    _write(expr_path, STAR_COUNTS)
    expr_entries = [{"path": expr_path, "sample_id": "expr-al-001",
                     "assay_id": EXPR_ASSAY_ID, "source_file": "file-e001",
                     "pipeline_version": "STAR - Counts"}]
    expr_reshape(expr_entries, dataset_raw / "expression_observation.tsv", dataset=DATASET)

    standardise(DATASET, "omics", raw_root=raw_root, out_root=std_root, log=False)

    # Pre-populate Sample.csv for both sample ids
    sample_csv = std_root / DATASET / "nodes" / "Sample.csv"
    _write(sample_csv, f"sampleId\n{SAMPLE_ID}\nexpr-al-001\n")

    return {"raw": raw_root, "std": std_root}


# ---------------------------------------------------------------------------
# Node CSV assertions
# ---------------------------------------------------------------------------

class TestVariationOmicsStandardise:
    def test_variant_observation_node_csv_written(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "nodes" / "VariantObservation.csv"
        assert path.exists()

    def test_variant_node_csv_written(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "nodes" / "Variant.csv"
        assert path.exists()

    def test_gene_node_csv_written(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "nodes" / "Gene.csv"
        assert path.exists()

    def test_assay_node_csv_written(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "nodes" / "Assay.csv"
        assert path.exists()

    def test_variant_observation_count(self, pipeline_dirs):
        # 2 samples × 2 mutations = 4 observation rows
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "VariantObservation.csv")
        assert len(rows) == 4

    def test_variant_dedup(self, pipeline_dirs):
        # 2 unique variants across 2 samples
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "Variant.csv")
        assert len(rows) == 2

    def test_gene_dedup(self, pipeline_dirs):
        # 2 unique genes (ENSG00000141510, ENSG00000012048)
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "Gene.csv")
        assert len(rows) == 2

    def test_assay_dedup(self, pipeline_dirs):
        # 1 unique assay across both files
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "Assay.csv")
        assert len(rows) == 1

    def test_variant_properties_populated(self, pipeline_dirs):
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "Variant.csv")
        tp53_row = next(r for r in rows if r["variantId"] == "17:7674220:C:T")
        assert tp53_row["chromosome"] == "17"
        assert tp53_row["startPosition"] == "7674220"
        assert tp53_row["referenceAllele"] == "C"
        assert tp53_row["alternateAllele"] == "T"
        assert tp53_row["variantClass"] == "Missense_Mutation"

    def test_variant_observation_vaf_populated(self, pipeline_dirs):
        rows = _csv_rows(pipeline_dirs["std"] / DATASET / "nodes" / "VariantObservation.csv")
        # t_alt_count=25 / t_depth=100 → 0.2500
        values = {r.get("variantAlleleFrequency") for r in rows}
        assert "0.2500" in values


# ---------------------------------------------------------------------------
# Edge CSV assertions
# ---------------------------------------------------------------------------

class TestVariationEdges:
    def test_has_variant_observation_edge(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "edges" / "HAS_VARIANT_OBSERVATION.csv"
        assert path.exists()
        rows = _csv_rows(path)
        assert len(rows) == 4  # 2 samples × 2 mutations

    def test_observed_variant_edge(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "edges" / "OBSERVED_VARIANT.csv"
        assert path.exists()
        rows = _csv_rows(path)
        assert len(rows) == 4

    def test_is_within_gene_edge_dedup(self, pipeline_dirs):
        path = pipeline_dirs["std"] / DATASET / "edges" / "IS_WITHIN_GENE.csv"
        assert path.exists()
        rows = _csv_rows(path)
        # 2 unique (variant, gene) pairs (same across 2 samples → deduped)
        assert len(rows) == 2

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
        # Sample (pre-written), VariantObservation, Variant, Gene, Assay = 5
        assert result["node_types"] == 5

    def test_edge_count(self, pipeline_dirs):
        result = validate(DATASET, standardised_root=pipeline_dirs["std"])
        # HAS_VARIANT_OBSERVATION(4) + OBSERVED_VARIANT(4) + IS_WITHIN_GENE(2)
        # + ASSAYED_BY(2) = 12
        assert result["edges"] == 12


# ---------------------------------------------------------------------------
# Gene convergence: variation gene_id == expression gene_id
# ---------------------------------------------------------------------------

class TestGeneConvergence:
    def test_gene_ids_converge_across_layers(self, combined_dirs):
        """Variation and expression Gene rows share the same deduped geneId."""
        gene_rows = _csv_rows(combined_dirs["std"] / DATASET / "nodes" / "Gene.csv")
        gene_ids = {r["geneId"] for r in gene_rows}
        # Both layers contribute ENSG00000141510 and ENSG00000012048
        assert "ENSG00000141510" in gene_ids
        assert "ENSG00000012048" in gene_ids
        # No version suffixes
        assert not any("." in g for g in gene_ids)

    def test_gene_dedup_across_layers(self, combined_dirs):
        """Gene dimension has exactly 2 rows despite both layers contributing them."""
        gene_rows = _csv_rows(combined_dirs["std"] / DATASET / "nodes" / "Gene.csv")
        assert len(gene_rows) == 2
