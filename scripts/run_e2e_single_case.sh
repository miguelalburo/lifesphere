#!/usr/bin/env bash
#
# run_e2e_single_case.sh — end-to-end pipeline test on ONE multi-omic case.
#
# This is the bash equivalent of scripts/demo_single_sample.py, written so each
# LifeSphere pipeline stage is a visible, separately-invoked step. It:
#
#   1. Selects one case that has all three open-access omics layers.
#   2. EXTRACT   — clinical (whole project) + omics (single case) → data/raw/
#   3. STANDARDISE — clinical (extract profile) + omics (omics profile) → data/standardised/
#   4. VALIDATE  — referential integrity, --strict, no Neo4j needed
#   5. PROVISION — wipe+create a fresh Enterprise database
#   6. LOAD      — BioCypher-driven load of both datasets into that database
#   7. VERIFY    — Cypher queries confirming the graph links up
#
# Stages 2–4 and 6 are driven purely through the CLI module entrypoints
# (`python -m src.extract|standardise|validate|load`). Case selection,
# single-case omics extraction, DB provisioning and verification have no CLI,
# so they run as small clearly-labelled inline `python` steps.
#
# Prereqs: a running Neo4j *Enterprise* instance (CREATE DATABASE privilege),
# connection details in .env, and the .venv populated from requirements.txt.
#
# Usage:
#   ./scripts/run_e2e_single_case.sh [-p PROJECT] [-d DATABASE] [--skip-clinical]
#
set -euo pipefail

# ── Locate the repo root (this script lives in scripts/) ──────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# ── Defaults (override via flags) ─────────────────────────────────────────────
PROJECT="TCGA-CHOL"     # preferred GDC project to search for a multi-omic case
DATABASE="cholomics"    # target Neo4j database (will be wiped + recreated)
SKIP_CLINICAL=0

usage() {
  sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--project)   PROJECT="$2"; shift 2 ;;
    -d|--db)        DATABASE="$2"; shift 2 ;;
    --skip-clinical) SKIP_CLINICAL=1; shift ;;
    -h|--help)      usage 0 ;;
    *) echo "Unknown argument: $1" >&2; usage 1 ;;
  esac
done

# ── Pretty logging ────────────────────────────────────────────────────────────
BOLD="$(tput bold 2>/dev/null || true)"; RESET="$(tput sgr0 2>/dev/null || true)"
section() { printf '\n%s%s\n  %s\n%s%s\n' "${BOLD}" "────────────────────────────────────────────────────────────" "$1" "────────────────────────────────────────────────────────────" "${RESET}" >&2; }
step()    { printf '%s▸ %s%s\n' "${BOLD}" "$1" "${RESET}" >&2; }

# ── Activate the virtualenv (CLAUDE.md: always source .venv first) ─────────────
if [[ ! -f "${REPO_ROOT}/.venv/bin/activate" ]]; then
  echo "ERROR: .venv not found at ${REPO_ROOT}/.venv — create it and pip install -r requirements.txt" >&2
  exit 1
fi
# shellcheck disable=SC1091
source "${REPO_ROOT}/.venv/bin/activate"

if [[ ! -f "${REPO_ROOT}/.env" ]]; then
  echo "ERROR: .env not found — copy .env.example and set NEO4J_URI/USER/PASSWORD" >&2
  exit 1
fi

# ── Data-dir fallback ─────────────────────────────────────────────────────────
# .env may point RAW_DIR/STD_DIR/LOG_DIR at an HPC path (e.g. /rds/...) that
# does not exist on this host. Ask the app where it wants to write (it resolves
# .env), and if that location is not writable fall back to repo-local data/.
# python-dotenv does not override already-exported vars, so these exports win.
if [[ -z "${RAW_DIR:-}" ]]; then
  CONFIGURED_RAW="$(python -c 'from src import DATA_RAW; print(DATA_RAW)' 2>/dev/null || true)"
  if [[ -z "${CONFIGURED_RAW}" ]] || ! mkdir -p "${CONFIGURED_RAW}" 2>/dev/null || [[ ! -w "${CONFIGURED_RAW}" ]]; then
    echo "  configured RAW_DIR (${CONFIGURED_RAW:-unset}) is not writable here — using repo-local data/" >&2
    export RAW_DIR="${REPO_ROOT}/data/raw"
    export STD_DIR="${REPO_ROOT}/data/standardised"
    export LOG_DIR="${REPO_ROOT}/logs"
  fi
fi
mkdir -p "${RAW_DIR:-${REPO_ROOT}/data/raw}" "${STD_DIR:-${REPO_ROOT}/data/standardised}" "${LOG_DIR:-${REPO_ROOT}/logs}"

# A file the selection step writes and we source back into bash.
SEL_ENV="$(mktemp "${TMPDIR:-/tmp}/lifesphere_sel.XXXXXX")"
trap 'rm -f "${SEL_ENV}"' EXIT

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1 — Select one multi-omic case and EXTRACT its omics layers
#
# No CLI exists for single-case selection or single-case omics extraction
# (`python -m src.extract` only scopes to a whole project). We reuse the same
# src functions the demo uses, then hand the chosen case back to bash via
# ${SEL_ENV} (CASE_ID / PROJECT_ID / OMICS_DATASET).
# ══════════════════════════════════════════════════════════════════════════════
section "Stage 1: select a multi-omic case + extract omics (single case)"

PROJECT="${PROJECT}" SEL_ENV="${SEL_ENV}" python - <<'PY'
import os
from pathlib import Path

from src import DATA_RAW
from src.extract.case_selector import select_case
from src.extract.omics import expression as expr, methylation as meth, variation as var

project = os.environ["PROJECT"]
sel = select_case(preferred_project=project, log=True)
omics_dataset = f"{sel.project_id}_omics"
dataset_raw = DATA_RAW / omics_dataset

# ── Expression ────────────────────────────────────────────────────────────────
expr_entries = []
for f in sel.expression_files:
    fid, fname = f.get("file_id", ""), f.get("file_name", "")
    local = expr.download_file(fid, fname, dataset_raw / "expression")
    expr_entries.append({
        "path": local, "sample_id": expr.aliquot_id(f), "assay_id": expr.assay_id(f),
        "source_file": fid, "pipeline_version": expr.pipeline_version(f),
    })
n = expr.reshape(expr_entries, dataset_raw / "expression_observation.tsv", dataset=omics_dataset)
print(f"  [expression] {n:,} observations", flush=True)

# ── Methylation ───────────────────────────────────────────────────────────────
meth_entries = []
for f in sel.methylation_files:
    fid, fname = f.get("file_id", ""), f.get("file_name", "")
    local = meth.download_file(fid, fname, dataset_raw / "methylation")
    meth_entries.append({
        "path": local, "sample_id": meth.aliquot_id(f), "assay_id": meth.assay_id(f),
        "source_file": fid, "pipeline_version": meth.pipeline_version(f),
    })
n = meth.reshape(meth_entries, dataset_raw / "methylation_observation.tsv", dataset=omics_dataset)
print(f"  [methylation] {n:,} observations", flush=True)

# ── Variation (project MAF filtered to this case's aliquots) ──────────────────
var_entries = []
for f in sel.variation_files:
    fid, fname = f.get("file_id", ""), f.get("file_name", "")
    local = var.download_file(fid, fname, dataset_raw / "variation")
    var_entries.append({
        "path": local, "assay_id": var.assay_id(f),
        "source_file": fid, "pipeline_version": var.pipeline_version(f),
    })
keep = set(sel.aliquot_map.keys()) if sel.aliquot_map else None
n = var.reshape(
    var_entries, dataset_raw / "variation_observation.tsv", dataset=omics_dataset,
    sample_id_map=sel.aliquot_map or None, keep_barcodes=keep,
)
print(f"  [variation] {n:,} observations", flush=True)

# Hand the selection back to the bash orchestrator.
Path(os.environ["SEL_ENV"]).write_text(
    f"CASE_ID={sel.case_id}\nPROJECT_ID={sel.project_id}\nOMICS_DATASET={omics_dataset}\n",
    encoding="utf-8",
)
PY

# shellcheck disable=SC1090
source "${SEL_ENV}"
echo "  Selected case : ${CASE_ID} (${PROJECT_ID})" >&2
echo "  Omics dataset : ${OMICS_DATASET}" >&2

# ── Clinical extraction (whole project — the clinical grain has no single-case CLI)
if [[ "${SKIP_CLINICAL}" -eq 0 ]]; then
  step "EXTRACT clinical: python -m src.extract ${PROJECT_ID} --clinical"
  python -m src.extract "${PROJECT_ID}" --clinical
else
  echo "  [--skip-clinical] skipping clinical extract/standardise/load" >&2
fi

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 2 — STANDARDISE  (Stage-1 engine: raw TSV → nodes/*.csv + edges/*.csv)
# ══════════════════════════════════════════════════════════════════════════════
section "Stage 2: standardise"
if [[ "${SKIP_CLINICAL}" -eq 0 ]]; then
  step "STANDARDISE clinical: python -m src.standardise ${PROJECT_ID}"
  python -m src.standardise "${PROJECT_ID}"
fi
step "STANDARDISE omics: python -m src.standardise ${OMICS_DATASET} --profile omics"
python -m src.standardise "${OMICS_DATASET}" --profile omics

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 3 — VALIDATE  (referential integrity only, offline, no Neo4j)
# ══════════════════════════════════════════════════════════════════════════════
section "Stage 3: validate --strict"
if [[ "${SKIP_CLINICAL}" -eq 0 ]]; then
  step "VALIDATE clinical: python -m src.validate ${PROJECT_ID} --strict"
  python -m src.validate "${PROJECT_ID}" --strict
fi
# Omics edges reference clinical Sample nodes, so resolve them against the
# clinical dataset (loaded into the same DB at Stage 5). Without clinical we
# cannot check those FKs, so skip strict validation of the cross-dataset edges.
if [[ "${SKIP_CLINICAL}" -eq 0 ]]; then
  step "VALIDATE omics: python -m src.validate ${OMICS_DATASET} --strict --reference ${PROJECT_ID}"
  python -m src.validate "${OMICS_DATASET}" --strict --reference "${PROJECT_ID}"
else
  step "VALIDATE omics (non-strict — no clinical reference for Sample edges): python -m src.validate ${OMICS_DATASET}"
  python -m src.validate "${OMICS_DATASET}"
fi

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 4 — PROVISION a fresh Enterprise database (wipe + create)
# ══════════════════════════════════════════════════════════════════════════════
section "Stage 4: provision database '${DATABASE}' (DROP IF EXISTS + CREATE)"
DATABASE="${DATABASE}" python - <<'PY'
import os, sys
from src.load.neo4j_client import Neo4jClient

db = os.environ["DATABASE"]
with Neo4jClient() as client:
    if not client.verify_create_database_privilege():
        sys.exit("ERROR: current Neo4j user lacks CREATE DATABASE privilege. "
                 "Grant it with: GRANT CREATE DATABASE ON DBMS TO <role>;")
    client.provision_database(db)
    print(f"  {db!r} is ready.", flush=True)
PY

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 5 — LOAD both datasets into the fresh database (BioCypher)
# ══════════════════════════════════════════════════════════════════════════════
section "Stage 5: load → ${DATABASE}"
if [[ "${SKIP_CLINICAL}" -eq 0 ]]; then
  step "LOAD clinical: python -m src.load ${PROJECT_ID} --database ${DATABASE}"
  python -m src.load "${PROJECT_ID}" --database "${DATABASE}"
fi
step "LOAD omics: python -m src.load ${OMICS_DATASET} --database ${DATABASE}"
python -m src.load "${OMICS_DATASET}" --database "${DATABASE}"

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 6 — VERIFY the graph (observation → Sample → Subject chains, shared Genes)
# ══════════════════════════════════════════════════════════════════════════════
section "Stage 6: graph verification"
DATABASE="${DATABASE}" python - <<'PY'
import os, sys
from src.load.neo4j_client import Neo4jClient

db = os.environ["DATABASE"]
checks = {
    "Expression→Sample→Subject":
        "MATCH (eo:ExpressionObservation)<-[:HAS_EXPRESSION_OBSERVATION]-(s:Sample)"
        "<-[:PROVIDED_SAMPLE]-(sub:Subject) "
        "RETURN count(eo) AS observations, count(DISTINCT s) AS samples, count(DISTINCT sub) AS subjects",
    "Methylation→Sample→Subject":
        "MATCH (mo:MethylationObservation)<-[:HAS_METHYLATION_OBSERVATION]-(s:Sample)"
        "<-[:PROVIDED_SAMPLE]-(sub:Subject) "
        "RETURN count(mo) AS observations, count(DISTINCT s) AS samples, count(DISTINCT sub) AS subjects",
    "Variant→Sample→Subject":
        "MATCH (vo:VariantObservation)<-[:HAS_VARIANT_OBSERVATION]-(s:Sample)"
        "<-[:PROVIDED_SAMPLE]-(sub:Subject) "
        "RETURN count(vo) AS observations, count(DISTINCT s) AS samples, count(DISTINCT sub) AS subjects",
    "Shared Gene (MEASURES_GENE + IS_WITHIN_GENE)":
        "MATCH (g:Gene) WHERE ((:ExpressionObservation)-[:MEASURES_GENE]->(g)) "
        "AND ((:Variant)-[:IS_WITHIN_GENE]->(g)) RETURN count(g) AS shared_genes",
}

ok = True
with Neo4jClient() as client:
    for label, cypher in checks.items():
        rows = client.query(cypher, database=db)
        print(f"  [{label}]")
        for row in rows:
            print(f"    {row}")
            if any(isinstance(v, int) and v == 0 for v in row.values()):
                print("    WARNING: a count is 0 — check the load.")
                ok = False

sys.exit(0 if ok else 1)
PY

section "End-to-end single-case test complete → database '${DATABASE}'"
