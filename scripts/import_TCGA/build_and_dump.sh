#!/bin/bash
#SBATCH --job-name=import_tcga_build
#SBATCH --qos=bbdefault
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --time=48:00:00
# ^ Sized for ~1B nodes / 10B edges: the string id-map + relationship linking
#   are RAM- and CPU-hungry, and the store build is long. bbdefault may not
#   grant 256G / 48h — you likely need a high-memory QoS/partition; adjust the
#   --qos above (see BlueBEAR docs) if the job won't dispatch.
set -euo pipefail

# ===========================================================================
# BUILD + DUMP  (runs on BlueBEAR, where the standardised data is local)
#
# neo4j-admin import is an OFFLINE tool: it builds a store from CSVs and needs
# no running server. So we build the whole combined store here — data is local
# on /rds, no mount, full speed — then `dump` it into ONE compressed artifact
# and copy that back to /rds for the Enterprise host to pull with scp.
#
# WHY A SLURM JOB (not the plain-shell driver): the fast node-local scratch on
# BlueBEAR (/scratch) only exists inside a job and is wiped at job end, so the
# store is built there and the .dump is copied out before we exit.
#
# ARGS
#   $@  dataset folder names under STD_DIR to combine into the one database.
#       Empty -> every dir under STD_DIR that has a nodes/ subdir.
# The driver (submit_import_TCGA.sh) sets --output / --chdir and passes SIF path.
# ===========================================================================

SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
source .env    # PROJECT_DIR, STD_DIR, LOG_DIR, VENV_DIR, NEO4J_DATABASE,
               # NEO4J_SIF, HPC_DUMP_DIR — see .env.example
TS="$(date -d "today" +"%d%m%Y%H%M")"

# --- build workspace --------------------------------------------------------
# BUILD_ROOT selects where the store is built (default: node-local /scratch):
#   /scratch (default)  -> fast node-local disk, but capped at the node's local
#                          capacity. At this scale the store is ~0.5-1TB, which
#                          may NOT fit — check `df -h /scratch` in a test job.
#   ${DATA_DIR}/build   -> large /rds (BeeGFS): slower, but holds a big store and
#                          isn't the flaky mount. Set BUILD_ROOT in .env to flip.
BUILD_ROOT="${BUILD_ROOT:-/scratch}"
mkdir -p "${BUILD_ROOT}"
WORKDIR="$(mktemp -d "${BUILD_ROOT}/${USER}_${SLURM_JOBID}.XXXXXX")"
export TMPDIR="${WORKDIR}"
# The dump is copied to HPC_DUMP_DIR before we exit, so it survives this cleanup;
# scratch is reclaimed at job end anyway, and /rds builds shouldn't linger.
trap 'rm -rf "${WORKDIR}"' EXIT
IMPORT_DIR="${WORKDIR}/import"     # rewritten admin-import CSVs
STORE_DATA="${WORKDIR}/data"       # neo4j store (bound to /data in-container)
DUMP_DIR="${WORKDIR}/dump"         # .dump lands here, then copied to /rds
mkdir -p "${IMPORT_DIR}" "${STORE_DATA}" "${DUMP_DIR}"
echo "=== BUILD_ROOT=${BUILD_ROOT}  WORKDIR=${WORKDIR}  $(date -Is) ==="
df -h "${BUILD_ROOT}" || true      # surface available space up front

# --- python env (only to run the assembler / src.load.bulk) -----------------
echo "=== SETTING UP VIRTUAL ENVIRONMENT $(date -Is) ==="
module purge
module load bluebear
module load bear-apps/2024a
module load Python/3.12.3-GCCcore-13.3.0
mkdir -p "$(dirname "${VENV_DIR}")"
(
    flock 9
    [[ -f ${VENV_DIR}/bin/activate ]] || python3 -m venv --system-site-packages "${VENV_DIR}"
    source "${VENV_DIR}/bin/activate"
    pip install --upgrade pip
    pip install -r requirements.txt
) 9>"${VENV_DIR}.lock"
source "${VENV_DIR}/bin/activate"

# --- which datasets? --------------------------------------------------------
DATASETS=("$@")
if [[ ${#DATASETS[@]} -eq 0 ]]; then
    for d in "${STD_DIR}"/*/; do
        [[ -d "${d}/nodes" ]] && DATASETS+=("$(basename "${d}")")
    done
fi
if [[ ${#DATASETS[@]} -eq 0 ]]; then
    echo "! no datasets with a nodes/ dir under ${STD_DIR}" >&2
    exit 1
fi
echo "=== COMBINING ${#DATASETS[@]} DATASETS INTO '${NEO4J_DATABASE}': ${DATASETS[*]} ==="

# --- assemble the one combined import arg list ------------------------------
# --schema (build indexes/constraints DURING import, saving an online label scan
# after load) needs neo4j-admin >= 2026.05. Enable it only when NEO4J_VERSION is
# high enough; otherwise the constraints are applied at load time instead.
SCHEMA_ARGS=()
if [[ "$(printf '%s\n2026.05\n' "${NEO4J_VERSION}" | sort -V | head -n1)" == "2026.05" ]]; then
    SCHEMA_ARGS=(--schema)
    echo "=== schema-during-import ON (NEO4J_VERSION=${NEO4J_VERSION} >= 2026.05) ==="
else
    echo "=== schema-during-import OFF (NEO4J_VERSION=${NEO4J_VERSION} < 2026.05); constraints apply at load ==="
fi
python "${SCRIPT_DIR}/assemble_import.py" "${DATASETS[@]}" \
    --out "${IMPORT_DIR}" --database "${NEO4J_DATABASE}" "${SCHEMA_ARGS[@]}"
mapfile -t IMPORT_ARGS < "${IMPORT_DIR}/import.args"

# --- neo4j-admin via Apptainer ---------------------------------------------
# Apptainer auto-binds /rds and /scratch, so the arg paths (all under /scratch)
# are identical inside the container. /data is the store dir the image writes to
# by default, so we bind our scratch store there. NEO4J_server_directories_data
# is set too in case this image's conf points elsewhere.
APPTAINER_ARGS=(
    exec
    --bind "${STORE_DATA}:/data"
    --env NEO4J_server_directories_data=/data
    --env NEO4J_ACCEPT_LICENSE_AGREEMENT=yes
    "${NEO4J_SIF}"
)

echo "=== IMPORT FULL $(date -Is) ==="
apptainer "${APPTAINER_ARGS[@]}" \
    neo4j-admin database import full "${IMPORT_ARGS[@]}"

echo "=== DUMP $(date -Is) ==="
apptainer "${APPTAINER_ARGS[@]}" \
    neo4j-admin database dump "${NEO4J_DATABASE}" --to-path="${DUMP_DIR}"

# --- persist the artifact off node-local scratch ----------------------------
mkdir -p "${HPC_DUMP_DIR}"
cp "${DUMP_DIR}/${NEO4J_DATABASE}.dump" "${HPC_DUMP_DIR}/"
cp "${IMPORT_DIR}/constraints.cypher"   "${HPC_DUMP_DIR}/${NEO4J_DATABASE}.constraints.cypher"

echo "=== DONE $(date -Is) ==="
echo "dump:        ${HPC_DUMP_DIR}/${NEO4J_DATABASE}.dump"
echo "constraints: ${HPC_DUMP_DIR}/${NEO4J_DATABASE}.constraints.cypher"
echo "Next: on the Enterprise host run scripts/import_TCGA/load_enterprise.sh"
