"""Import TCGA-CDR survival calls (Liu et al. 2018, Cell) into data/raw.

The Xena TCGA Pan-Cancer Atlas hub (pancanatlas.xenahubs.net) currently returns
S3 AccessDenied on direct fetch, so this pulls the same TCGA-CDR-derived OS/
DSS/DFS/PFS status+time columns from the cBioPortal datahub mirror instead —
one data_clinical_patient.txt per study, git-LFS-backed.

Always pulls the full TCGA pan-cancer study list (STUDY_SLUGS below) — there is
no project/program scoping. Writes ``survival.tsv`` to the given output
directory, replacing whatever was there. Requires ``<out_dir>/subject.tsv`` to
already exist (it supplies the case_submitter_id -> case_id crosswalk, since
cBioPortal keys rows by TCGA barcode and the graph keys Subject by GDC case
UUID) — run ``--clinical`` first.
"""

from __future__ import annotations

import csv
import sys
import urllib.error
import urllib.request
from pathlib import Path

from ..observation import mint_id

STUDY_SLUGS = [
    "acc_tcga_pan_can_atlas_2018", "blca_tcga_pan_can_atlas_2018",
    "brca_tcga_pan_can_atlas_2018", "cesc_tcga_pan_can_atlas_2018",
    "chol_tcga_pan_can_atlas_2018", "coadread_tcga_pan_can_atlas_2018",
    "dlbc_tcga_pan_can_atlas_2018", "esca_tcga_pan_can_atlas_2018",
    "gbm_tcga_pan_can_atlas_2018", "hnsc_tcga_pan_can_atlas_2018",
    "kich_tcga_pan_can_atlas_2018", "kirc_tcga_pan_can_atlas_2018",
    "kirp_tcga_pan_can_atlas_2018", "laml_tcga_pan_can_atlas_2018",
    "lgg_tcga_pan_can_atlas_2018", "lihc_tcga_pan_can_atlas_2018",
    "luad_tcga_pan_can_atlas_2018", "lusc_tcga_pan_can_atlas_2018",
    "meso_tcga_pan_can_atlas_2018", "ov_tcga_pan_can_atlas_2018",
    "paad_tcga_pan_can_atlas_2018", "pcpg_tcga_pan_can_atlas_2018",
    "prad_tcga_pan_can_atlas_2018", "sarc_tcga_pan_can_atlas_2018",
    "skcm_tcga_pan_can_atlas_2018", "stad_tcga_pan_can_atlas_2018",
    "tgct_tcga_pan_can_atlas_2018", "thca_tcga_pan_can_atlas_2018",
    "thym_tcga_pan_can_atlas_2018", "ucec_tcga_pan_can_atlas_2018",
    "ucs_tcga_pan_can_atlas_2018", "uvm_tcga_pan_can_atlas_2018",
]

BASE_URL = "https://media.githubusercontent.com/media/cBioPortal/datahub/master/public"

# (status column, months column, our survival_type) — DFS/PFS renamed to
# DFI/PFI for continuity with the schema's existing survivalType vocabulary.
ENDPOINTS = [
    ("OS_STATUS", "OS_MONTHS", "OS"),
    ("DSS_STATUS", "DSS_MONTHS", "DSS"),
    ("DFS_STATUS", "DFS_MONTHS", "DFI"),
    ("PFS_STATUS", "PFS_MONTHS", "PFI"),
]

DAYS_PER_MONTH = 30.4368  # average Gregorian month length; cBioPortal only gives months


def fetch_study_rows(slug: str) -> list[dict]:
    url = f"{BASE_URL}/{slug}/data_clinical_patient.txt"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        print(f"  ! {slug}: HTTP {e.code}", file=sys.stderr)
        return []
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    reader = csv.DictReader(lines, delimiter="\t")
    return list(reader)


def build_crosswalk(out_dir: Path) -> dict[str, str]:
    crosswalk: dict[str, str] = {}
    with (out_dir / "subject.tsv").open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            barcode = row.get("case_submitter_id", "")
            case_id = row.get("case_id", "")
            if barcode and case_id:
                crosswalk[barcode] = case_id
    return crosswalk


def _status_event(status: str) -> int | None:
    status = (status or "").strip()
    if status.startswith("1:"):
        return 1
    if status.startswith("0:"):
        return 0
    return None


def _months_to_days(months: str) -> int | None:
    try:
        m = float(months)
    except (TypeError, ValueError):
        return None
    return round(m * DAYS_PER_MONTH)


def reshape(patient_rows: list[dict], crosswalk: dict[str, str]) -> tuple[list[dict], int]:
    out_rows: list[dict] = []
    unmatched = 0
    for row in patient_rows:
        barcode = row.get("PATIENT_ID", "")
        case_id = crosswalk.get(barcode)
        if not case_id:
            unmatched += 1
            continue
        for status_col, months_col, survival_type in ENDPOINTS:
            event = _status_event(row.get(status_col, ""))
            time_days = _months_to_days(row.get(months_col, ""))
            if event is None or time_days is None:
                continue
            out_rows.append({
                "case_id": case_id,
                "case_submitter_id": barcode,
                # standardise re-derives survivalId itself (observation.DERIVED_KEYS
                # registers Survival), so this column is written for readability of
                # the raw TSV only — changing it here does not change how it's minted.
                "survival_id": mint_id(case_id, survival_type),
                "survival_type": survival_type,
                "event": event,
                "time_days": time_days,
            })
    return out_rows, unmatched


def extract_survival(out_dir: Path) -> None:
    """Fetch full TCGA pan-cancer survival calls and write survival.tsv to out_dir.

    Ignores any project/program scoping — always pulls the complete pan-cancer
    study list. Requires ``<out_dir>/subject.tsv`` (from ``--clinical``) for the
    barcode -> case_id crosswalk.
    """
    print(f"Building barcode->case_id crosswalk from {out_dir / 'subject.tsv'}...", file=sys.stderr)
    crosswalk = build_crosswalk(out_dir)
    print(f"  {len(crosswalk)} patients in crosswalk", file=sys.stderr)

    all_rows: list[dict] = []
    total_unmatched = 0
    for slug in STUDY_SLUGS:
        print(f"Fetching {slug}...", file=sys.stderr, flush=True)
        patient_rows = fetch_study_rows(slug)
        rows, unmatched = reshape(patient_rows, crosswalk)
        all_rows.extend(rows)
        total_unmatched += unmatched
        print(f"  {len(patient_rows)} patients, {len(rows)} survival rows, {unmatched} unmatched barcodes",
              file=sys.stderr)

    out_path = out_dir / "survival.tsv"
    columns = ["case_id", "case_submitter_id", "survival_id", "survival_type", "event", "time_days"]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Done — wrote {len(all_rows)} rows to {out_path} ({total_unmatched} unmatched barcodes total).",
          file=sys.stderr)
