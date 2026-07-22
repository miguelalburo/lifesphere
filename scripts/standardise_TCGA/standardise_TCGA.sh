#!/bin/bash
#SBATCH --job-name=standardise_tcga
#SBATCH --qos=bbdefault
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=32G
#SBATCH --time=08:00:00
set -e

# ---------------------------------------------------------------------------
# ARGS
#   $1  dataset folder name under RAW_DIR (e.g. TCGA_CLINICAL)
#   $2  mapping profile (extract | omics)
# The submit wrapper sets --job-name / --output / --chdir per dataset.
# ---------------------------------------------------------------------------
DATASET="$1"
PROFILE="$2"
if [[ -z "${DATASET}" || -z "${PROFILE}" ]]; then
    echo "usage: standardise_TCGA.sh <dataset> <profile>" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# PATHS  (all vars must be set in .env — no defaults)
# ---------------------------------------------------------------------------

source .env
TS="$(date -d "today" +"%d%m%Y%H%M")"

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
# Fan-out jobs share one VENV_DIR on the mount, so serialise creation + install
# behind a lock: without it, concurrent `pip install`s corrupt each other's
# site-packages (e.g. "No such file or directory: .../pytz/__init__.py"). The
# first job installs; the rest block, then find everything already satisfied.
# ---------------------------------------------------------------------------
echo "=== SETTING UP VIRTUAL ENVIRONMENT $(date -Is) ==="
mkdir -p "$(dirname "${VENV_DIR}")"
(
    flock 9
    if [[ ! -f ${VENV_DIR}/bin/activate ]]; then
        python3 -m venv --system-site-packages ${VENV_DIR}
    fi
    source ${VENV_DIR}/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
) 9>"${VENV_DIR}.lock"
source ${VENV_DIR}/bin/activate   # re-activate: the locked subshell's env didn't persist

# ---------------------------------------------------------------------------
# RUN STANDARDISE   (reads RAW_DIR/<dataset>, writes STD_DIR/<dataset>)
# ---------------------------------------------------------------------------
echo "=== STANDARDISING ${DATASET} (profile: ${PROFILE}) $(date -Is) ==="

python -m src.standardise "${DATASET}" --profile "${PROFILE}"

echo "=== COMPLETED SUCCESSFULLY? $(date -Is) ==="
