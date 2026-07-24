#!/bin/bash
# Driver: build the combined LifeSphere store on BlueBEAR and dump it to /rds.
# Plain shell — run from anywhere, paths come from .env. It (1) ensures the
# pinned Neo4j Apptainer image exists, then (2) submits the build+dump SLURM job
# (node-local scratch only exists inside a job). The dump is left on /rds for the
# Enterprise host to pull; see scripts/import_TCGA/load_enterprise.sh.
#
# Usage:
#   scripts/submit_import_TCGA.sh [dataset ...]   # default: all under STD_DIR
set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
source "${SCRIPT_DIR}/../.env"   # PROJECT_DIR, LOG_DIR, NEO4J_VERSION,
                                 # NEO4J_SIF, NEO4J_DATABASE, HPC_DUMP_DIR

TS="$(date -d "today" +"%d%m%Y%H%M")"
mkdir -p "${LOG_DIR}/import"

# --- ensure the pinned image is present (version MUST match the Enterprise
#     server: store/dump format is version-specific) ---------------------------
if [[ ! -f "${NEO4J_SIF}" ]]; then
    echo "pulling neo4j:${NEO4J_VERSION}-enterprise -> ${NEO4J_SIF}"
    mkdir -p "$(dirname "${NEO4J_SIF}")"
    apptainer pull "${NEO4J_SIF}" "docker://neo4j:${NEO4J_VERSION}-enterprise"
else
    echo "= using existing image ${NEO4J_SIF}"
fi

echo "submitting build+dump for '${NEO4J_DATABASE}' (datasets: ${*:-<all under STD_DIR>})"
sbatch \
    --job-name="import_${NEO4J_DATABASE}" \
    --chdir="${PROJECT_DIR}" \
    --output="${LOG_DIR}/import/${NEO4J_DATABASE}_%j_${TS}.log" \
    "${SCRIPT_DIR}/import_TCGA/build_and_dump.sh" "$@"
