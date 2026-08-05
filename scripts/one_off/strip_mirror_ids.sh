#!/bin/bash
#SBATCH --job-name=strip_mirror_ids
#SBATCH --qos=bbdefault
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=12:00:00
# ^ Streaming rewrite: constant memory, bounded by /rds I/O. sbatch it, or just
#   run it in an interactive job — do NOT run it on a login node (80GB+ of I/O).
set -euo pipefail

# ===========================================================================
# ONE-OFF (#74): strip mirror-id properties from omics observation node CSVs.
#
# Observation nodes carry sampleId / assayId / <entity>Id properties that
# duplicate what the edges already encode. src/load builds edges from
# edges/*.csv, never from these node properties, so removing them is
# load-safe — it only drops storage overhead.
#
# This is a STOPGAP: it edits standardise output in place, ahead of the real
# fix (remove the properties from config/schema/nodes.yaml and re-standardise).
# Re-running standardise regenerates the columns, so re-run this after.
#
# SAFETY
#   * drops columns BY HEADER NAME, never by position;
#   * never drops column 1 (the node's own id) — protects Gene.geneId etc.;
#   * ABORTS on any row that is not exactly <header> plain comma-separated
#     fields, or that contains a double quote — awk cannot parse RFC-4180
#     quoting, so anything it could corrupt stops the run instead;
#   * writes a sibling temp file and only replaces the original after the
#     rewrite succeeds and the last row checks out (needs free space equal to
#     the file being rewritten);
#   * idempotent — a file with no mirror columns left is skipped.
#
# Usage (on the cluster, where /rds is local):
#   scripts/one_off/strip_mirror_ids.sh [--dry-run] [--keep-original] [dataset ...]
#
# Default datasets: every dir under STD_DIR. Only the five omics observation
# node files are touched; anything else is left alone.
#
#   scripts/one_off/strip_mirror_ids.sh --dry-run TCGA_EXPRESSION   # inspect
#   scripts/one_off/strip_mirror_ids.sh TCGA_EXPRESSION             # do it
# ===========================================================================

# sbatch STAGES a copy of this script into the job spool dir, so ${BASH_SOURCE[0]}
# does not resolve back into the repo — script-relative paths break under SLURM.
# Look for the repo root in the submit dir, then cwd, then (plain-bash runs) the
# script's own location.
PROJECT_ROOT=""
for _cand in "${SLURM_SUBMIT_DIR:-}" "${PWD}" \
             "$(dirname "$(dirname "$(dirname "$(realpath "${BASH_SOURCE[0]}")")")")"; do
    if [[ -n "${_cand}" && -f "${_cand}/.env" ]]; then PROJECT_ROOT="${_cand}"; break; fi
done
if [[ -z "${PROJECT_ROOT}" ]]; then
    echo "! cannot find .env (looked in SLURM_SUBMIT_DIR, ${PWD}, and the script's repo). " \
         "sbatch from the repo root, or set STD_DIR in the environment." >&2
    exit 2
fi
source "${PROJECT_ROOT}/.env"    # STD_DIR

DRY_RUN=0
KEEP_ORIGINAL=0
DATASETS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)       DRY_RUN=1; shift ;;
        --keep-original) KEEP_ORIGINAL=1; shift ;;
        -h|--help)
            echo "usage: $(basename "${BASH_SOURCE[0]}") [--dry-run] [--keep-original] [dataset ...]" >&2
            exit 2 ;;
        *)               DATASETS+=("$1"); shift ;;
    esac
done

# The five omics observation nodes in scope for #74. Clinical/low-volume
# observation nodes are deliberately excluded — see the issue.
OBSERVATION_NODES=(
    ExpressionObservation
    MethylationObservation
    VariantObservation
    ProteinObservation
    MetaboliteObservation
)
# Mirror ids to remove wherever they appear as a NON-first column.
MIRROR_PROPS="sampleId,assayId,geneId,cpgId,variantId,proteinId,metaboliteId"

if [[ ${#DATASETS[@]} -eq 0 ]]; then
    for d in "${STD_DIR}"/*/; do
        [[ -d "${d}/nodes" ]] && DATASETS+=("$(basename "${d}")")
    done
fi

echo "=== STRIP MIRROR IDS (#74) $(date -Is) ==="
echo "    STD_DIR:  ${STD_DIR}"
echo "    datasets: ${DATASETS[*]}"
echo "    dropping: ${MIRROR_PROPS} (never column 1)"
[[ "${DRY_RUN}" -eq 1 ]] && echo "    DRY RUN — nothing will be written"

# A killed job (SLURM timeout, Ctrl-C) must not leave a half-written temp file
# the size of the input sitting on /rds.
CURRENT_TMP=""
trap 'if [[ -n "${CURRENT_TMP}" ]]; then rm -f "${CURRENT_TMP}"; fi; exit 130' INT TERM

strip_file() {
    local src="$1" tmp="$1.stripped.$$" label; label="$(basename "${src}")"
    local header keep_desc

    header="$(head -n 1 "${src}")"
    # Which columns survive? Computed from the header alone, before any I/O.
    # Fields are '|'-joined: a non-whitespace IFS keeps empty fields (no mirror
    # columns -> empty middle field), which whitespace IFS would collapse.
    keep_desc="$(awk -F, -v props="${MIRROR_PROPS}" '
        NR == 1 {
            split(props, p, ","); for (i in p) drop[p[i]] = 1
            for (i = 1; i <= NF; i++)
                if (i == 1 || !($i in drop)) keep = keep (keep ? "," : "") i
                else removed = removed (removed ? "," : "") $i
            print keep "|" removed "|" NF
        }' <<< "${header}")"
    local keep_cols removed_names n_fields
    IFS='|' read -r keep_cols removed_names n_fields <<< "${keep_desc}"

    if [[ -z "${removed_names}" ]]; then
        echo "= skip ${label}: no mirror columns present (already stripped?)"
        return 0
    fi

    local bytes; bytes="$(stat -c %s "${src}")"
    echo "--- ${label}: ${n_fields} cols, $(numfmt --to=iec "${bytes}") — removing: ${removed_names}"

    if [[ "${DRY_RUN}" -eq 1 ]]; then
        echo "    would keep columns ${keep_cols}"
        return 0
    fi

    # Free space check: peak usage is original + rewritten copy.
    local avail; avail="$(df -P --block-size=1 "$(dirname "${src}")" | awk 'NR==2 {print $4}')"
    if (( avail < bytes )); then
        echo "! ${label}: need up to $(numfmt --to=iec "${bytes}") free, have $(numfmt --to=iec "${avail}")" >&2
        return 1
    fi

    # Single streaming pass. Aborts (exit 3) on anything awk could mangle; the
    # partial temp file is removed rather than left on /rds (it is as large as
    # the work done so far).
    CURRENT_TMP="${tmp}"
    if ! LC_ALL=C awk -F, -v OFS=, -v keep="${keep_cols}" -v nf="${n_fields}" '
        BEGIN { n = split(keep, k, ",") }
        index($0, "\"") {
            print "! row " NR " contains a double quote — quoted CSV cannot be " \
                  "rewritten with awk; aborting" > "/dev/stderr"; bad = 1; exit 3
        }
        NF != nf {
            print "! row " NR " has " NF " fields, expected " nf \
                  " (embedded comma?); aborting" > "/dev/stderr"; bad = 1; exit 3
        }
        { for (i = 1; i <= n; i++) printf "%s%s", $k[i], (i < n ? OFS : ORS) }
        END { if (!bad) print "    rows written (incl. header): " NR > "/dev/stderr" }
    ' "${src}" > "${tmp}"; then
        rm -f "${tmp}"
        echo "! ${label}: rewrite aborted, original untouched" >&2
        return 1
    fi

    # Truncation guard: the last input row, transformed, must be the last output
    # row. Cheap (tail only) and catches a short/interrupted write.
    local want got
    want="$(tail -n 1 "${src}" | LC_ALL=C awk -F, -v OFS=, -v keep="${keep_cols}" '
        BEGIN { n = split(keep, k, ",") }
        { for (i = 1; i <= n; i++) printf "%s%s", $k[i], (i < n ? OFS : ORS) }')"
    got="$(tail -n 1 "${tmp}")"
    if [[ "${want}" != "${got}" ]]; then
        CURRENT_TMP=""   # keep it: a mismatch is worth inspecting by hand
        echo "! ${label}: last row mismatch — leaving ${tmp} in place for inspection" >&2
        return 1
    fi

    if [[ "${KEEP_ORIGINAL}" -eq 1 ]]; then
        mv "${src}" "${src}.orig"
        echo "    original kept at ${src}.orig"
    else
        rm -f "${src}"
    fi
    mv "${tmp}" "${src}"
    CURRENT_TMP=""
    echo "    done: $(numfmt --to=iec "${bytes}") -> $(numfmt --to=iec "$(stat -c %s "${src}")")  $(date -Is)"
}

rc=0
for dataset in "${DATASETS[@]}"; do
    for node in "${OBSERVATION_NODES[@]}"; do
        src="${STD_DIR}/${dataset}/nodes/${node}.csv"
        [[ -f "${src}" ]] || continue
        echo "=== ${dataset}/${node} $(date -Is) ==="
        strip_file "${src}" || rc=1
    done
done

echo "=== FINISHED (rc=${rc}) $(date -Is) ==="
exit "${rc}"
