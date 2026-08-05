#!/bin/bash
#SBATCH --job-name=load_tcga
#SBATCH --qos=bbdefault
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=72:00:00
# ^ The driver load is I/O- and network-bound, not CPU-bound: one process streams
#   CSVs off /rds and MERGEs them over bolt. Memory is what it is because
#   src.load.run reads each CSV into row groups in memory before batching, so a
#   large observation CSV is held whole. Time is generous because bolt MERGE is
#   ~1-2 orders of magnitude slower than neo4j-admin import — see the note in
#   submit_load_TCGA.sh about which path to use at full TCGA scale.
set -euo pipefail

# ===========================================================================
# LOAD  (runs on BlueBEAR, where the standardised CSVs are local)
#
# The data is on /rds and is NOT mounted on the Neo4j Enterprise host, so the
# load runs here and talks to the DBMS over bolt (NEO4J_URI from .env). The
# compute node must be able to reach that host:port — check with the preflight
# step below before queueing a 3-day job.
#
# Idempotent and restartable: constraints are CREATE ... IF NOT EXISTS and both
# nodes and edges are MERGEd, so re-running a failed/timed-out job is safe and
# simply re-does the work.
#
# ARGS
#   $1   dataset folder name under STD_DIR (e.g. TCGA_EXPRESSION)
#   $2   target database name             (e.g. lifesphere_test)
#   $3   batch size for MERGE transactions
#   $4   "1" to CREATE the database if absent, "0" to fail when it is
#   $5   "1" for --dry-run (plan only, no connection), "0" to really load
#   $6+  labels the dataset does NOT emit but its edges point at (e.g. Sample)
# The driver (submit_load_TCGA.sh) sets --job-name / --output / --chdir.
# ===========================================================================

DATASET="${1:-}"
DATABASE="${2:-}"
BATCH_SIZE="${3:-1000}"
CREATE_DB="${4:-0}"
DRY_RUN="${5:-0}"
if [[ $# -ge 5 ]]; then shift 5; else shift $#; fi
EXPECT_LABELS=("$@")

if [[ -z "${DATASET}" || -z "${DATABASE}" ]]; then
    echo "usage: load_TCGA.sh <dataset> <database> [batch_size] [create_db] [dry_run] [expect_label ...]" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# PATHS  (all vars must be set in .env — no defaults)
# ---------------------------------------------------------------------------

# sbatch STAGES a copy of this script into the job spool dir, so ${BASH_SOURCE[0]}
# does not resolve back into the repo — script-relative paths break under SLURM.
# The driver passes --chdir=${PROJECT_DIR}, so cwd is normally the repo already;
# fall back to the submit dir, then the script's location (plain-bash runs).
PROJECT_ROOT=""
for _cand in "${PWD}" "${SLURM_SUBMIT_DIR:-}" \
             "$(dirname "$(dirname "$(dirname "$(realpath "${BASH_SOURCE[0]}")")")")"; do
    if [[ -n "${_cand}" && -f "${_cand}/.env" ]]; then PROJECT_ROOT="${_cand}"; break; fi
done
if [[ -z "${PROJECT_ROOT}" ]]; then
    echo "! cannot find .env (looked in ${PWD}, SLURM_SUBMIT_DIR, and the script's repo)" >&2
    exit 2
fi
cd "${PROJECT_ROOT}"                 # `python -m src.load` needs the repo as cwd
source "${PROJECT_ROOT}/.env"        # PROJECT_DIR, VENV_DIR, STD_DIR, NEO4J_URI/USER/PASSWORD

echo "=== LOAD ${DATASET} -> '${DATABASE}' $(date -Is) ==="
echo "    source:  ${STD_DIR}/${DATASET}"
echo "    target:  ${NEO4J_URI}"
echo "    batch:   ${BATCH_SIZE}   dry-run: ${DRY_RUN}"

# ---------------------------------------------------------------------------
# MODULES
# ---------------------------------------------------------------------------
echo "=== LOADING BEAR MODULES $(date -Is) ==="

module purge
module load bluebear
module load bear-apps/2024a
module load Python/3.12.3-GCCcore-13.3.0

# ---------------------------------------------------------------------------
# VIRTUAL ENVIRONMENT
# Same flock discipline as the standardise job: fan-out jobs share one VENV_DIR
# on the mount, and concurrent `pip install`s corrupt each other's site-packages.
# ---------------------------------------------------------------------------
echo "=== SETTING UP VIRTUAL ENVIRONMENT $(date -Is) ==="
mkdir -p "$(dirname "${VENV_DIR}")"
(
    flock 9
    [[ -f ${VENV_DIR}/bin/activate ]] || python3 -m venv --system-site-packages "${VENV_DIR}"
    source "${VENV_DIR}/bin/activate"
    pip install --upgrade pip
    pip install -r requirements.txt
) 9>"${VENV_DIR}.lock"
source "${VENV_DIR}/bin/activate"   # re-activate: the locked subshell's env didn't persist

# ---------------------------------------------------------------------------
# PREFLIGHT — connectivity, target database, endpoint labels this dataset needs
# but does not emit. Skipped on --dry-run (which needs no database at all).
# ---------------------------------------------------------------------------
if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "=== PREFLIGHT SKIPPED (dry run) $(date -Is) ==="
else
    echo "=== PREFLIGHT $(date -Is) ==="
    PREFLIGHT_ARGS=(--database "${DATABASE}")
    if [[ "${CREATE_DB}" -eq 1 ]]; then PREFLIGHT_ARGS+=(--create); fi
    for label in ${EXPECT_LABELS[@]+"${EXPECT_LABELS[@]}"}; do
        PREFLIGHT_ARGS+=(--expect-label "${label}")
    done
    python "${PROJECT_ROOT}/scripts/load_TCGA/preflight.py" "${PREFLIGHT_ARGS[@]}"
fi

# ---------------------------------------------------------------------------
# RUN LOAD   (reads STD_DIR/<dataset>/{nodes,edges}, writes to <database>)
# ---------------------------------------------------------------------------
echo "=== LOADING $(date -Is) ==="

LOAD_ARGS=("${DATASET}" --database "${DATABASE}" --batch-size "${BATCH_SIZE}")
if [[ "${DRY_RUN}" -eq 1 ]]; then LOAD_ARGS+=(--dry-run); fi

python -m src.load "${LOAD_ARGS[@]}"

echo "=== COMPLETED SUCCESSFULLY? $(date -Is) ==="
