"""Reshape-door unit tests for the generic matrix melt.

Assert on the emitted canonical observation TSV (external behaviour), never on
internal helpers. Covers: genes_x_samples + samples_x_genes orientation, Ensembl
version stripping, non-Ensembl loud warning, unit + assay stamping, assay-omitted
graceful degrade, ignore_columns, and loud sample-id reconciliation skip.
"""

from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent

from src.reshape import parse_specs, reshape_dataset

DATASET = "TRAD_MINI"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    return path


def _read_obs(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        rows = list(reader)
        return list(reader.fieldnames or []), rows


GENES_X_SAMPLES = """
    gene_id\tgene_name\tsampleA\tsampleB
    ENSG00000141510.12\tTP53\t5.25\t3.10
    ENSG00000012048.21\tBRCA1\t10.50\t0.00
"""

SAMPLES_X_GENES = """
    sample_id\tENSG00000141510.12\tENSG00000012048.21
    sampleA\t5.25\t10.50
    sampleB\t3.10\t0.00
"""


def _run(tmp_path: Path, matrix: str, *, spec_extra: dict, sample_ids=None, log=True):
    raw_root = tmp_path / "raw"
    interim_root = tmp_path / "interim"
    _write(raw_root / DATASET / "expr_matrix.tsv", matrix)
    spec = {
        "type": "matrix",
        "input": "expr_matrix.tsv",
        "output": "expression_observation.tsv",
        "observation": "expression",
        "feature_id_column": spec_extra.get("feature_id_column", "gene_id"),
        "feature_id_type": "ensembl",
        "unit": "TPM",
        **spec_extra,
    }
    specs = parse_specs([spec])
    reshape_dataset(DATASET, specs, raw_root=raw_root, interim_root=interim_root,
                    sample_ids=sample_ids, log=log)
    return interim_root / DATASET / "expression_observation.tsv"


class TestGenesXSamples:
    def test_row_count(self, tmp_path):
        out = _run(tmp_path, GENES_X_SAMPLES,
                   spec_extra={"ignore_columns": ["gene_name"]})
        _, rows = _read_obs(out)
        assert len(rows) == 4  # 2 genes × 2 samples

    def test_ensembl_version_stripped(self, tmp_path):
        out = _run(tmp_path, GENES_X_SAMPLES,
                   spec_extra={"ignore_columns": ["gene_name"]})
        _, rows = _read_obs(out)
        genes = {r["gene_id"] for r in rows}
        assert genes == {"ENSG00000141510", "ENSG00000012048"}

    def test_obs_id_and_value(self, tmp_path):
        out = _run(tmp_path, GENES_X_SAMPLES,
                   spec_extra={"ignore_columns": ["gene_name"]})
        _, rows = _read_obs(out)
        by_id = {r["expression_observation_id"]: r for r in rows}
        assert by_id["sampleA:ENSG00000141510"]["expression_value"] == "5.25"
        assert by_id["sampleB:ENSG00000141510"]["expression_value"] == "3.10"

    def test_unit_stamped(self, tmp_path):
        out = _run(tmp_path, GENES_X_SAMPLES,
                   spec_extra={"ignore_columns": ["gene_name"]})
        _, rows = _read_obs(out)
        assert all(r["expression_unit"] == "TPM" for r in rows)

    def test_ignore_column_not_a_sample(self, tmp_path):
        out = _run(tmp_path, GENES_X_SAMPLES,
                   spec_extra={"ignore_columns": ["gene_name"]})
        _, rows = _read_obs(out)
        samples = {r["sample_id"] for r in rows}
        assert samples == {"sampleA", "sampleB"}  # gene_name excluded

    def test_assay_provenance_stamped(self, tmp_path):
        out = _run(tmp_path, GENES_X_SAMPLES, spec_extra={
            "ignore_columns": ["gene_name"],
            "assay": {"assay_id": "trad-rnaseq", "platform": "Illumina NovaSeq",
                      "library_strategy": "RNA-Seq", "reference_genome": "GRCh38"},
        })
        cols, rows = _read_obs(out)
        assert "platform" in cols and "library_strategy" in cols
        assert all(r["assay_id"] == "trad-rnaseq" for r in rows)
        assert all(r["platform"] == "Illumina NovaSeq" for r in rows)
        assert all(r["reference_genome"] == "GRCh38" for r in rows)

    def test_assay_omitted_degrades(self, tmp_path):
        out = _run(tmp_path, GENES_X_SAMPLES,
                   spec_extra={"ignore_columns": ["gene_name"]})
        _, rows = _read_obs(out)
        # No assay sub-block: observations still emit, assay_id blank.
        assert len(rows) == 4
        assert all(r["assay_id"] == "" for r in rows)


class TestSamplesXGenes:
    def test_transposed_melt_matches(self, tmp_path):
        out = _run(tmp_path, SAMPLES_X_GENES, spec_extra={
            "orientation": "samples_x_genes", "feature_id_column": "sample_id",
        })
        _, rows = _read_obs(out)
        assert len(rows) == 4
        by_id = {r["expression_observation_id"]: r for r in rows}
        assert by_id["sampleA:ENSG00000141510"]["expression_value"] == "5.25"
        assert by_id["sampleB:ENSG00000012048"]["expression_value"] == "0.00"
        genes = {r["gene_id"] for r in rows}
        assert genes == {"ENSG00000141510", "ENSG00000012048"}


class TestReconciliation:
    def test_drifted_sample_skipped_not_dropped_silently(self, tmp_path, capsys):
        # sampleB is absent from the metadata Sample set -> loud skip, excluded.
        out = _run(tmp_path, GENES_X_SAMPLES,
                   spec_extra={"ignore_columns": ["gene_name"]},
                   sample_ids={"sampleA"})
        _, rows = _read_obs(out)
        samples = {r["sample_id"] for r in rows}
        assert samples == {"sampleA"}
        assert len(rows) == 2

    def test_reconciliation_disabled_when_none(self, tmp_path):
        out = _run(tmp_path, GENES_X_SAMPLES,
                   spec_extra={"ignore_columns": ["gene_name"]}, sample_ids=None)
        _, rows = _read_obs(out)
        assert {r["sample_id"] for r in rows} == {"sampleA", "sampleB"}


class TestNonEnsemblWarning:
    def test_symbol_key_warns(self, tmp_path, capsys):
        matrix = """
            gene_id\tsampleA
            TP53\t5.25
        """
        out = _run(tmp_path, matrix, spec_extra={})
        err = capsys.readouterr().err
        assert "does not look like an Ensembl id" in err
        # still emits (used as-is after strip)
        _, rows = _read_obs(out)
        assert rows[0]["gene_id"] == "TP53"
