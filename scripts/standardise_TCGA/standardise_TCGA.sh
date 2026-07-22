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
# ---------------------------------------------------------------------------
echo "=== SETTING UP VIRTUAL ENVIRONMENT $(date -Is) ==="
if [[ ! -f ${VENV_DIR}/bin/activate ]]; then
    python3 -m venv --system-site-packages ${VENV_DIR}
fi
source ${VENV_DIR}/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# ---------------------------------------------------------------------------
# RUN STANDARDISE   (reads RAW_DIR/<dataset>, writes STD_DIR/<dataset>)
# ---------------------------------------------------------------------------
echo "=== STANDARDISING ${DATASET} (profile: ${PROFILE}) $(date -Is) ==="

python -m src.standardise "${DATASET}" --profile "${PROFILE}"

echo "=== COMPLETED SUCCESSFULLY? $(date -Is) ==="
