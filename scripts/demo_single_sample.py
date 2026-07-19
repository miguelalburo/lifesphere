#!/usr/bin/env python3
"""Single-sample multi-omic Enterprise load demonstration (issue #41).

Steps
-----
1. Auto-select a TCGA-CHOL case with all three open-access omics types.
2. Verify CREATE DATABASE privilege on the Neo4j Enterprise instance.
3. Provision a fresh ``cholomics`` database (wipe + create).
4. Load full TCGA-CHOL clinical into ``cholomics``.
5. For the selected case, extract each omics layer (expression, methylation,
   variation), standardise, validate --strict, and load into ``cholomics``.
6. Run graph verification queries confirming:
   - Observations link to aliquot Sample nodes that trace back to Subject.
   - Shared Gene nodes carry both MEASURES_GENE and IS_WITHIN_GENE edges.

Usage
-----
    source .venv/bin/activate
    python scripts/demo_single_sample.py [--db cholomics] [--dry-run]

Environment
-----------
Reads NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (or defaults) from .env.
Set NEO4J_URI=bolt://localhost:7687 for a local Enterprise instance.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a plain script.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src import DATA_RAW, DATA_STANDARDISED
from src.extract.case_selector import CaseSelection, select_case
from src.extract.omics.expression import (
    aliquot_id as expr_aliquot_id,
    assay_id as expr_assay_id,
    pipeline_version as expr_pipeline,
    download_file as download_expr,
    reshape as expr_reshape,
)
from src.extract.omics.methylation import (
    aliquot_id as meth_aliquot_id,
    assay_id as meth_assay_id,
    pipeline_version as meth_pipeline,
    download_file as download_meth,
    reshape as meth_reshape,
)
from src.extract.omics.variation import (
    assay_id as var_assay_id,
    pipeline_version as var_pipeline,
    download_file as download_var,
    reshape as var_reshape,
)
from src.load.neo4j_client import Neo4jClient
from src.load.run import load
from src.standardise import standardise
from src.validate import validate

# ──────────────────────────────────────────────────────────────────────────────

TARGET_DB = "cholomics"
CLINICAL_DATASET = "TCGA-CHOL"
OMICS_DATASET_SUFFIX = "_omics"  # dataset name under data/raw and data/standardised


def _log(msg: str, *, bold: bool = False) -> None:
    prefix = "\033[1m" if bold else ""
    suffix = "\033[0m" if bold else ""
    print(f"{prefix}{msg}{suffix}", file=sys.stderr, flush=True)


def _section(title: str) -> None:
    _log(f"\n{'─' * 60}", bold=True)
    _log(f"  {title}", bold=True)
    _log(f"{'─' * 60}", bold=True)


# ──────────────────────────── Step helpers ────────────────────────────────────


def step_select_case(preferred_project: str) -> CaseSelection:
    _section("Step 1: Auto-select a multi-omic case")
    sel = select_case(preferred_project=preferred_project, log=True)
    _log(f"\nChosen case  : {sel.case_id}")
    _log(f"Project      : {sel.project_id}")
    _log(f"Expression   : {len(sel.expression_files)} file(s)")
    _log(f"Methylation  : {len(sel.methylation_files)} file(s)")
    _log(f"Variation    : {len(sel.variation_files)} project MAF file(s)")
    _log(f"Aliquot map  : {len(sel.aliquot_map)} barcode → UUID entries")
    return sel


def step_provision_db(client: Neo4jClient, db_name: str) -> None:
    _section(f"Step 2–3: Verify privilege & provision {db_name!r}")
    _log("  Checking CREATE DATABASE privilege...")
    try:
        has_priv = client.verify_create_database_privilege()
    except RuntimeError as exc:
        _log(f"ERROR: {exc}", bold=True)
        sys.exit(1)
    if not has_priv:
        _log(
            f"ERROR: current Neo4j user does NOT have CREATE DATABASE privilege.\n"
            f"Grant it with:  GRANT CREATE DATABASE ON DBMS TO <role>;\n"
            "Cannot continue.",
            bold=True,
        )
        sys.exit(1)
    _log("  Privilege confirmed.")
    _log(f"  Provisioning {db_name!r} (DROP IF EXISTS + CREATE)...")
    try:
        client.provision_database(db_name)
    except RuntimeError as exc:
        _log(f"ERROR: {exc}", bold=True)
        sys.exit(1)
    _log(f"  {db_name!r} is ready.")


def step_load_clinical(db_name: str, dry_run: bool) -> None:
    _section(f"Step 4: Load TCGA-CHOL clinical → {db_name!r}")
    # The clinical dataset must already be standardised under data/standardised/.
    clinical_std = DATA_STANDARDISED / CLINICAL_DATASET
    if not clinical_std.exists():
        _log(
            f"  Clinical standardised dir not found: {clinical_std}\n"
            f"  Run: python -m src.extract TCGA-CHOL --clinical\n"
            f"       python -m src.standardise TCGA-CHOL"
        )
        sys.exit(1)
    _log(f"  Loading {CLINICAL_DATASET} into {db_name!r} ...")
    plan = load(CLINICAL_DATASET, database=db_name, dry_run=dry_run)
    _log(
        f"  {'planned' if dry_run else 'loaded'}: "
        f"{len(plan['nodes'])} node types, {len(plan['edges'])} edge types"
    )


def step_extract_omics(sel: CaseSelection, raw_root: Path) -> Path:
    """Download and reshape all three omics layers for the selected case."""
    _section("Step 5a: Extract omics layers")
    omics_dataset = sel.project_id + OMICS_DATASET_SUFFIX
    dataset_raw = raw_root / omics_dataset

    # ── Expression ──────────────────────────────────────────────────────────
    _log("  [expression] Downloading files...")
    expr_dir = dataset_raw / "expression"
    expr_entries = []
    for f in sel.expression_files:
        fid, fname = f.get("file_id", ""), f.get("file_name", "")
        _log(f"    {fname}")
        local = download_expr(fid, fname, expr_dir)
        expr_entries.append({
            "path": local,
            "sample_id": expr_aliquot_id(f),
            "assay_id": expr_assay_id(f),
            "source_file": fid,
            "pipeline_version": expr_pipeline(f),
        })
    obs_path = dataset_raw / "expression_observation.tsv"
    n = expr_reshape(expr_entries, obs_path, dataset=omics_dataset)
    _log(f"  [expression] {n:,} observations → {obs_path.name}")

    # ── Methylation ──────────────────────────────────────────────────────────
    _log("  [methylation] Downloading files...")
    meth_dir = dataset_raw / "methylation"
    meth_entries = []
    for f in sel.methylation_files:
        fid, fname = f.get("file_id", ""), f.get("file_name", "")
        _log(f"    {fname}")
        local = download_meth(fid, fname, meth_dir)
        meth_entries.append({
            "path": local,
            "sample_id": meth_aliquot_id(f),
            "assay_id": meth_assay_id(f),
            "source_file": fid,
            "pipeline_version": meth_pipeline(f),
        })
    obs_path = dataset_raw / "methylation_observation.tsv"
    n = meth_reshape(meth_entries, obs_path, dataset=omics_dataset)
    _log(f"  [methylation] {n:,} observations → {obs_path.name}")

    # ── Variation ────────────────────────────────────────────────────────────
    _log("  [variation] Downloading project MAF(s)...")
    var_dir = dataset_raw / "variation"
    var_entries = []
    for f in sel.variation_files:
        fid, fname = f.get("file_id", ""), f.get("file_name", "")
        _log(f"    {fname}")
        local = download_var(fid, fname, var_dir)
        var_entries.append({
            "path": local,
            "assay_id": var_assay_id(f),
            "source_file": fid,
            "pipeline_version": var_pipeline(f),
        })
    obs_path = dataset_raw / "variation_observation.tsv"
    # Filter MAF rows to this case's aliquots (by barcode) and map to UUIDs.
    keep_barcodes: set[str] | None = (
        set(sel.aliquot_map.keys()) if sel.aliquot_map else None
    )
    n = var_reshape(
        var_entries,
        obs_path,
        dataset=omics_dataset,
        sample_id_map=sel.aliquot_map if sel.aliquot_map else None,
        keep_barcodes=keep_barcodes,
    )
    _log(f"  [variation] {n:,} observations → {obs_path.name}")

    return dataset_raw


def step_standardise_validate_load(
    sel: CaseSelection,
    raw_root: Path,
    std_root: Path,
    db_name: str,
    dry_run: bool,
) -> None:
    """Standardise → validate --strict → load omics for the selected case."""
    _section("Step 5b–5d: Standardise / Validate / Load omics")
    omics_dataset = sel.project_id + OMICS_DATASET_SUFFIX

    _log(f"  Standardising {omics_dataset} with omics profile...")
    summary = standardise(omics_dataset, "omics", raw_root=raw_root, out_root=std_root)
    n_nodes = sum(summary["nodes"].values())
    n_edges = sum(summary["edges"].values())
    _log(
        f"    {len(summary['nodes'])} node types ({n_nodes} rows), "
        f"{len(summary['edges'])} edge types ({n_edges} rows)"
    )

    _log("  Validating referential integrity (--strict)...")
    report = validate(omics_dataset, standardised_root=std_root)
    if report["problems"]:
        _log("  VALIDATION FAILED — problems found:", bold=True)
        for p in report["problems"]:
            _log(f"    {p}")
        sys.exit(1)
    _log(
        f"  Validation passed: {report['node_types']} node types, "
        f"{report['node_ids']} node ids, {report['edges']} edges, "
        f"0 problems."
    )

    _log(f"  Loading {omics_dataset} into {db_name!r} ...")
    plan = load(omics_dataset, standardised_root=std_root, database=db_name, dry_run=dry_run)
    _log(
        f"  {'planned' if dry_run else 'loaded'}: "
        f"{len(plan['nodes'])} node types, {len(plan['edges'])} edge types"
    )


def step_verify_graph(client: Neo4jClient, sel: CaseSelection, db_name: str) -> None:
    """Run Cypher queries to confirm the graph satisfies all acceptance criteria."""
    _section("Step 6: Graph verification queries")

    queries = [
        (
            "ExpressionObservation→Sample→Subject chain",
            f"""
            MATCH (eo:ExpressionObservation)<-[:HAS_EXPRESSION_OBSERVATION]-(s:Sample)
                  <-[:PROVIDED_SAMPLE]-(sub:Subject)
            WHERE sub.subjectId IS NOT NULL
            RETURN count(eo) AS n_observations, count(DISTINCT s) AS n_samples,
                   count(DISTINCT sub) AS n_subjects
            """,
        ),
        (
            "MethylationObservation→Sample→Subject chain",
            f"""
            MATCH (mo:MethylationObservation)<-[:HAS_METHYLATION_OBSERVATION]-(s:Sample)
                  <-[:PROVIDED_SAMPLE]-(sub:Subject)
            WHERE sub.subjectId IS NOT NULL
            RETURN count(mo) AS n_observations, count(DISTINCT s) AS n_samples,
                   count(DISTINCT sub) AS n_subjects
            """,
        ),
        (
            "VariantObservation→Sample→Subject chain",
            f"""
            MATCH (vo:VariantObservation)<-[:HAS_VARIANT_OBSERVATION]-(s:Sample)
                  <-[:PROVIDED_SAMPLE]-(sub:Subject)
            WHERE sub.subjectId IS NOT NULL
            RETURN count(vo) AS n_observations, count(DISTINCT s) AS n_samples,
                   count(DISTINCT sub) AS n_subjects
            """,
        ),
        (
            "Shared Gene nodes (MEASURES_GENE + IS_WITHIN_GENE)",
            """
            MATCH (g:Gene)
            WHERE ((:ExpressionObservation)-[:MEASURES_GENE]->(g))
              AND ((:Variant)-[:IS_WITHIN_GENE]->(g))
            RETURN count(g) AS shared_gene_nodes
            """,
        ),
        (
            "All three observation types present",
            """
            RETURN
              count { (eo:ExpressionObservation) }  AS n_expr,
              count { (mo:MethylationObservation) }  AS n_meth,
              count { (vo:VariantObservation) }       AS n_var
            """,
        ),
    ]

    all_ok = True
    for label, cypher in queries:
        try:
            rows = client.query(cypher.strip(), database=db_name)
            _log(f"  [{label}]")
            for row in rows:
                _log(f"    {row}")
            # Basic sanity: none of the counts should be zero for a real load.
            for row in rows:
                for key, val in row.items():
                    if isinstance(val, int) and val == 0:
                        _log(f"    WARNING: {key} = 0 — check the load.", bold=True)
                        all_ok = False
        except Exception as exc:
            _log(f"  ERROR running [{label}]: {exc}", bold=True)
            all_ok = False

    if all_ok:
        _log("\nAll verification checks passed.", bold=True)
    else:
        _log("\nSome checks produced warnings or errors — review output above.", bold=True)


# ────────────────────────────────── Main ──────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts/demo_single_sample.py",
        description="Single-sample multi-omic Enterprise load demonstration.",
    )
    parser.add_argument(
        "--db", default=TARGET_DB,
        help=f"target Neo4j database name (default: {TARGET_DB})",
    )
    parser.add_argument(
        "--project", default="TCGA-CHOL",
        help="preferred GDC project to search for a multi-omic case (default: TCGA-CHOL)",
    )
    parser.add_argument(
        "--raw-root", type=Path, default=DATA_RAW,
        help="root directory for raw downloads (default: data/raw/)",
    )
    parser.add_argument(
        "--std-root", type=Path, default=DATA_STANDARDISED,
        help="root directory for standardised output (default: data/standardised/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="plan loads without writing to Neo4j (omits graph verification)",
    )
    parser.add_argument(
        "--skip-clinical", action="store_true",
        help="skip TCGA-CHOL clinical load (assume it is already in the database)",
    )
    args = parser.parse_args(argv)

    # Step 1: select case (pure GDC API, no Neo4j)
    sel = step_select_case(args.project)

    if args.dry_run:
        _log("\n[dry-run] Skipping Neo4j connection, privilege check, and DB provision.")
    else:
        # Steps 2–3: provision database
        with Neo4jClient() as client:
            step_provision_db(client, args.db)

    # Step 4: load clinical (runs via standard load path)
    if not args.skip_clinical:
        step_load_clinical(args.db, args.dry_run)
    else:
        _log("\n[--skip-clinical] Skipping clinical load.")

    # Step 5a: extract omics
    step_extract_omics(sel, args.raw_root)

    # Steps 5b–5d: standardise → validate → load
    step_standardise_validate_load(sel, args.raw_root, args.std_root, args.db, args.dry_run)

    # Step 6: graph verification
    if not args.dry_run:
        with Neo4jClient() as client:
            step_verify_graph(client, sel, args.db)
    else:
        _log("\n[dry-run] Skipping graph verification queries.")

    _log("\nDemo complete.", bold=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
