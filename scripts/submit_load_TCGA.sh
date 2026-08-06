#!/bin/bash
# Driver: load standardised datasets into a running Neo4j over bolt, from
# BlueBEAR. Plain shell — run from anywhere, paths come from .env.
#
# WHY A SLURM JOB: the standardised CSVs live on /rds and are NOT mounted on the
# Neo4j host, so the load has to run where the data is and push it over the wire.
# Login nodes are not the place for a multi-hour streaming job.
#
# WHICH LOAD PATH: this is the driver (`src.load`) path — batched MERGE over
# bolt, idempotent, restartable, and safe against a live database that already
# holds data. It is also SLOW: at full-TCGA expression scale (~10^8-10^9
# observation rows) it will not finish in any sane wall time. For a full
# rebuild of the whole graph use the offline path instead
# (scripts/submit_import_TCGA.sh -> neo4j-admin import + dump + load). Use this
# one for test databases, single-modality top-ups, and re-runs into an existing
# graph.
#
# Usage:
#   scripts/submit_load_TCGA.sh [options] [dataset ...]
#
# Options:
#   -d, --database NAME   target database (default: lifesphere-test)
#   -b, --batch-size N    rows per MERGE transaction (default: 1000)
#       --create-database CREATE DATABASE IF NOT EXISTS when absent (Enterprise).
#                         Never drops an existing database.
#       --dry-run         plan the load without connecting to Neo4j
#       --parallel        submit datasets independently instead of chaining them
#
# No datasets = every dir under STD_DIR with a nodes/ subdir. Multiple datasets
# are chained with afterok dependencies by default: they MERGE into shared
# reference dimensions (Sample, Gene, Assay), and concurrent MERGEs on the same
# nodes deadlock in Neo4j. --parallel only if you know they are disjoint.
#
# NOTE ON THE NAME: Neo4j database names take alphanumerics, dots and dashes --
# NOT underscores. `lifesphere_test` is not a legal database name, so it could
# never exist and --create-database cannot conjure it; the real database is
# `lifesphere-test`. Keep the dash.
#
# Example (the expression load into the test database):
#   scripts/submit_load_TCGA.sh --database lifesphere-test TCGA_EXPRESSION
set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
source "${SCRIPT_DIR}/../.env"   # PROJECT_DIR, STD_DIR, LOG_DIR, NEO4J_URI

DATABASE="lifesphere-test"
BATCH_SIZE=1000
CREATE_DB=0
DRY_RUN=0
PARALLEL=0
DATASETS=()

usage() {
    echo "usage: $(basename "${BASH_SOURCE[0]}") [-d|--database NAME] [-b|--batch-size N]" \
         "[--create-database] [--dry-run] [--parallel] [dataset ...]" >&2
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--database)     DATABASE="${2:-}"; [[ -n "${DATABASE}" ]] || usage; shift 2 ;;
        -b|--batch-size)   BATCH_SIZE="${2:-}"; [[ -n "${BATCH_SIZE}" ]] || usage; shift 2 ;;
        --create-database) CREATE_DB=1; shift ;;
        --dry-run)         DRY_RUN=1; shift ;;
        --parallel)        PARALLEL=1; shift ;;
        -h|--help)         usage ;;
        -*)                echo "! unknown option: $1" >&2; usage ;;
        *)                 DATASETS+=("$1"); shift ;;
    esac
done

# --- which datasets? --------------------------------------------------------
if [[ ${#DATASETS[@]} -eq 0 ]]; then
    for d in "${STD_DIR}"/*/; do
        [[ -d "${d}/nodes" ]] && DATASETS+=("$(basename "${d}")")
    done
fi
if [[ ${#DATASETS[@]} -eq 0 ]]; then
    echo "! no datasets with a nodes/ dir under ${STD_DIR}" >&2
    exit 1
fi

TS="$(date -d "today" +"%d%m%Y%H%M")"
mkdir -p "${LOG_DIR}/load"

echo "target: '${DATABASE}' at ${NEO4J_URI}"
echo "datasets: ${DATASETS[*]}"

DEP=""
for dataset in "${DATASETS[@]}"; do
    base="${STD_DIR}/${dataset}"
    if ! compgen -G "${base}/nodes/*.csv" > /dev/null; then
        echo "! skip ${dataset}: no node CSVs under ${base}/nodes" >&2
        continue
    fi

    # Endpoint labels the dataset's edges point at but the dataset does not emit.
    # The omics profile explicitly leaves Sample to the clinical pass, and edges
    # are MATCH-then-MERGE: with no Samples in the target database, every
    # HAS_*_OBSERVATION edge silently creates nothing. Preflight warns loudly.
    case "${dataset}" in
        *EXPRESSION*|*METHYLATION*|*VARIATION*) expect=(Sample) ;;
        *)                                      expect=() ;;
    esac

    echo "submitting ${dataset} -> ${DATABASE}${DEP:+ (after ${DEP})}"
    jobid=$(sbatch --parsable \
        ${DEP:+--dependency="afterok:${DEP}"} \
        --job-name="load_${dataset}_${DATABASE}" \
        --chdir="${PROJECT_DIR}" \
        --output="${LOG_DIR}/load/${dataset}_${DATABASE}_%j_${TS}.log" \
        "${SCRIPT_DIR}/load_TCGA/load_TCGA.sh" \
        "${dataset}" "${DATABASE}" "${BATCH_SIZE}" "${CREATE_DB}" "${DRY_RUN}" \
        ${expect[@]+"${expect[@]}"})
    echo "  job ${jobid}  log: ${LOG_DIR}/load/${dataset}_${DATABASE}_${jobid}_${TS}.log"

    if [[ "${PARALLEL}" -eq 0 ]]; then
        DEP="${jobid}"
    fi
done
