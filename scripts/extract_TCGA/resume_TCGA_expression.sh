#!/bin/bash
#SBATCH --job-name=resume_tcga_expression
#SBATCH --qos=bbdefault
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=24:00:00
set -e

# Offline resume of the expression reshape phase from already-downloaded raw
# files — re-runs only reshape() with the current parsers (no GDC query, no
# re-download), finishing a partial/empty expression_observation.tsv.

# ---------------------------------------------------------------------------
# PATHS  (all vars must be set in .env — no defaults)
# ---------------------------------------------------------------------------

source .env
TS="$(date -d "today" +"%d%m%Y%H%M")"

# ---------------------------------------------------------------------------
# MODULES  (no gdc-client — reshape is offline)
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
# RESUME RESHAPE
# ---------------------------------------------------------------------------
echo "=== RESUMING EXPRESSION RESHAPE $(date -Is) ==="

python scripts/extract_TCGA/resume_omics_reshape.py --layers expression "${RAW_DIR}/TCGA_EXPRESSION"

echo "=== COMPLETED SUCCESSFULLY? $(date -Is) ==="
