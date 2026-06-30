#!/usr/bin/env python3
"""
Download clinical/biospecimen tab-delimited files for a GDC project.

Sources:
  1. BCR BioTab files  — fetched via gdc-client (manifest download)
  2. Harmonized cases  — fetched from the GDC /cases API endpoint

Usage:
  python download_gdc_clinical.py <project_id> <output_dir>

Example:
  python download_gdc_clinical.py TCGA-PRAD ~/Downloads/tcga-prad-clinical
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

GDC_FILES_URL = "https://api.gdc.cancer.gov/files"
GDC_CASES_URL = "https://api.gdc.cancer.gov/cases"


def gdc_post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"GDC API error {e.code}: {e.read().decode()}")


# ---------------------------------------------------------------------------
# 1. BCR BioTab files via gdc-client
# ---------------------------------------------------------------------------

def fetch_biotab_manifest(project_id: str) -> list[dict]:
    """Return manifest rows for all BCR BioTab files in the project."""
    payload = {
        "filters": {
            "op": "and",
            "content": [
                {"op": "=", "content": {"field": "cases.project.project_id", "value": project_id}},
                {"op": "=", "content": {"field": "data_format",              "value": "bcr biotab"}},
            ],
        },
        "fields": "file_id,file_name,md5sum,file_size,state",
        "size": 500,
    }
    result = gdc_post(GDC_FILES_URL, payload)
    hits = result["data"]["hits"]
    total = result["data"]["pagination"]["total"]
    if total == 0:
        print(f"  No BCR BioTab files found for {project_id}.")
    elif total > len(hits):
        print(f"  Warning: {total} files found but only {len(hits)} returned — increase page size.")
    return hits


def write_manifest(hits: list[dict], path: Path) -> None:
    with open(path, "w", newline="") as f:
        f.write("id\tfilename\tmd5\tsize\tstate\n")
        for h in hits:
            f.write(f"{h['file_id']}\t{h['file_name']}\t{h.get('md5sum','')}\t"
                    f"{h.get('file_size','')}\t{h.get('state','')}\n")


def download_biotab(project_id: str, out_dir: Path) -> None:
    print(f"\n[1/2] Fetching BCR BioTab manifest for {project_id}...")
    hits = fetch_biotab_manifest(project_id)
    if not hits:
        return

    print(f"  Found {len(hits)} files:")
    for h in hits:
        size_kb = (h.get("file_size") or 0) / 1024
        print(f"    {h['file_name']}  ({size_kb:.1f} KB)")

    biotab_dir = out_dir / "biotab"
    biotab_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = biotab_dir / "manifest.txt"
    write_manifest(hits, manifest_path)
    print(f"  Manifest written to {manifest_path}")

    print("  Running gdc-client download...")
    cmd = [
        "gdc-client", "download",
        "-m", str(manifest_path),
        "-d", str(biotab_dir),
        "--no-file-md5sum",
        "-n", "4",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  gdc-client stderr:\n{result.stderr}", file=sys.stderr)
        sys.exit(f"  gdc-client exited with code {result.returncode}")

    n_downloaded = result.stderr.count("Successfully downloaded") or result.stdout.count("Successfully downloaded")
    print(f"  Done. Files saved under {biotab_dir}/")


# ---------------------------------------------------------------------------
# 2. Harmonized cases from /cases endpoint
# ---------------------------------------------------------------------------

CASES_FIELDS = [
    "case_id", "submitter_id",
    "demographic.gender", "demographic.race", "demographic.ethnicity",
    "demographic.vital_status", "demographic.days_to_birth", "demographic.days_to_death",
    "demographic.year_of_birth", "demographic.year_of_death",
    "diagnoses.age_at_diagnosis", "diagnoses.primary_diagnosis",
    "diagnoses.tumor_stage", "diagnoses.tumor_grade",
    "diagnoses.days_to_diagnosis", "diagnoses.days_to_last_follow_up",
    "diagnoses.last_known_disease_status", "diagnoses.tissue_or_organ_of_origin",
    "diagnoses.morphology", "diagnoses.progression_or_recurrence",
    "diagnoses.treatments.treatment_type", "diagnoses.treatments.therapeutic_agents",
    "diagnoses.treatments.treatment_intent_type", "diagnoses.treatments.days_to_treatment_start",
    "exposures.alcohol_history", "exposures.bmi",
    "exposures.height", "exposures.weight", "exposures.years_smoked",
    "samples.sample_id", "samples.submitter_id", "samples.sample_type",
    "samples.tissue_type", "samples.tumor_descriptor",
    "samples.days_to_collection", "samples.days_to_sample_procurement",
]


def fetch_all_cases(project_id: str) -> list[dict]:
    filters = {"op": "=", "content": {"field": "project.project_id", "value": project_id}}
    hits, from_pos, total = [], 0, None
    while total is None or from_pos < total:
        payload = {
            "filters": filters,
            "fields": ",".join(CASES_FIELDS),
            "size": 500,
            "from": from_pos,
        }
        d = gdc_post(GDC_CASES_URL, payload)["data"]
        if total is None:
            total = d["pagination"]["total"]
            print(f"  Total cases: {total}")
        hits.extend(d["hits"])
        from_pos += len(d["hits"])
        print(f"  Fetched {from_pos}/{total}...", flush=True)
    return hits


def flatten_case(c: dict) -> dict:
    demo  = c.get("demographic") or {}
    diag  = (c.get("diagnoses")  or [{}])[0]
    expo  = (c.get("exposures")  or [{}])[0]
    treat = (diag.get("treatments") or [{}])[0]
    samples = c.get("samples") or []
    return {
        "case_id":                    c.get("case_id", ""),
        "submitter_id":               c.get("submitter_id", ""),
        "gender":                     demo.get("gender", ""),
        "race":                       demo.get("race", ""),
        "ethnicity":                  demo.get("ethnicity", ""),
        "vital_status":               demo.get("vital_status", ""),
        "days_to_birth":              demo.get("days_to_birth", ""),
        "days_to_death":              demo.get("days_to_death", ""),
        "year_of_birth":              demo.get("year_of_birth", ""),
        "year_of_death":              demo.get("year_of_death", ""),
        "age_at_diagnosis":           diag.get("age_at_diagnosis", ""),
        "primary_diagnosis":          diag.get("primary_diagnosis", ""),
        "tumor_stage":                diag.get("tumor_stage", ""),
        "tumor_grade":                diag.get("tumor_grade", ""),
        "days_to_diagnosis":          diag.get("days_to_diagnosis", ""),
        "days_to_last_follow_up":     diag.get("days_to_last_follow_up", ""),
        "last_known_disease_status":  diag.get("last_known_disease_status", ""),
        "tissue_or_organ_of_origin":  diag.get("tissue_or_organ_of_origin", ""),
        "morphology":                 diag.get("morphology", ""),
        "progression_or_recurrence":  diag.get("progression_or_recurrence", ""),
        "treatment_type":             treat.get("treatment_type", ""),
        "therapeutic_agents":         treat.get("therapeutic_agents", ""),
        "treatment_intent_type":      treat.get("treatment_intent_type", ""),
        "days_to_treatment_start":    treat.get("days_to_treatment_start", ""),
        "alcohol_history":            expo.get("alcohol_history", ""),
        "bmi":                        expo.get("bmi", ""),
        "height":                     expo.get("height", ""),
        "weight":                     expo.get("weight", ""),
        "years_smoked":               expo.get("years_smoked", ""),
        "sample_types":               "; ".join(sorted({s.get("sample_type", "") for s in samples if s.get("sample_type")})),
        "num_samples":                len(samples),
    }


def download_cases_tsv(project_id: str, out_dir: Path) -> None:
    print(f"\n[2/2] Fetching harmonized cases from GDC /cases endpoint...")
    hits = fetch_all_cases(project_id)
    if not hits:
        print("  No cases found.")
        return

    rows = [flatten_case(c) for c in hits]
    out_path = out_dir / f"gdc_clinical_{project_id}.tsv"
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Saved {len(rows)} cases × {len(rows[0])} columns → {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download GDC clinical/biospecimen tab-delimited files for a project."
    )
    parser.add_argument("project_id",  help="GDC project ID, e.g. TCGA-PRAD")
    parser.add_argument("output_dir",  help="Directory to save files into")
    args = parser.parse_args()

    project_id = args.project_id.upper()
    out_dir    = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Project : {project_id}")
    print(f"Output  : {out_dir}")

    download_biotab(project_id, out_dir)
    download_cases_tsv(project_id, out_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
