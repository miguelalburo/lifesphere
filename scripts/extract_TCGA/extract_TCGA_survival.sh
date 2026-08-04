#!/bin/bash
#SBATCH --job-name=extract_tcga_survival
#SBATCH --qos=bbdefault
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=08:00:00
set -e

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
module load gdc-client/1.6.0-GCCcore-13.3.0

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
# RUN EXTRACTION
# ---------------------------------------------------------------------------
echo "=== RUNNING EXTRACTION $(date -Is) ==="

# --survival ignores project/program scope and always pulls the full TCGA
# pan-cancer study list; it needs subject.tsv for the barcode->case_id
# crosswalk, so it targets the clinical output dir and must run after
# extract_TCGA_clinical.sh has completed (see submit_extract_TCGA.sh).
python -m src.extract --program TCGA --survival --out "${RAW_DIR}/TCGA_CLINICAL"

echo "=== COMPLETED SUCCESSFULLY? $(date -Is) ==="
