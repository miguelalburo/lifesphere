#!/usr/bin/env python3
"""
Download clinical/biospecimen tab-delimited files from GDC.

Usage:
  python download_gdc_clinical.py --project TCGA-PRAD [--biotab] <output_dir>
  python download_gdc_clinical.py --program TCGA                  <output_dir>
  python download_gdc_clinical.py --cases uuid1,uuid2             <output_dir>

Exactly one of --project, --program, or --cases is required.

Each fetch writes one TSV per entity: {base}.case.tsv (1 row/case), plus
{base}.diagnosis.tsv, .treatment.tsv, .pathology_detail.tsv, .follow_up.tsv,
.molecular_test.tsv, .exposure.tsv, .family_history.tsv,
.other_clinical_attribute.tsv, .sample.tsv, .aliquot.tsv, .file.tsv at their
true (1:many) grain.

--project downloads the per-entity TSVs for the project.
--program downloads the per-entity TSVs for all cases in the program.
--biotab  (with --project or --program) also downloads BCR BioTab files and
          merges clinical_patient data into the case TSV on case_id.
--cases   downloads the per-entity TSVs for the given case UUIDs only
          (comma- or tab-separated).
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.extract import download_biotab, download_cases_tsv, download_cases_tsv_by_program, download_cases_tsv_by_ids
from src.extract.biotab_merge import merge_biotab_into_metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download GDC clinical/biospecimen data by project or case UUIDs."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--project",
        metavar="PROJECT_ID",
        help="GDC project ID (e.g. TCGA-PRAD). Downloads per-entity TSVs (+ BioTab with --biotab).",
    )
    group.add_argument(
        "--program",
        metavar="PROGRAM",
        help="GDC program name (e.g. TCGA). Downloads cases TSV for all cases in the program.",
    )
    group.add_argument(
        "--cases",
        metavar="UUID[,UUID...]",
        help="Comma- or tab-separated list of case UUIDs. Downloads cases TSV only.",
    )
    parser.add_argument(
        "--biotab",
        action="store_true",
        default=False,
        help="Download BCR BioTab files and merge clinical_patient data into the case TSV (with --project or --program).",
    )
    parser.add_argument("output_dir", help="Directory to save files into")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.project:
        project_id = args.project.upper()
        print(f"Project : {project_id}")
        print(f"Output  : {out_dir}")
        if args.biotab:
            download_biotab(project_id, out_dir)
        download_cases_tsv(project_id, out_dir)
        if args.biotab:
            print("\n[biotab merge] Merging clinical_patient data into case TSV...")
            biotab_dir = out_dir / "biotab"
            merge_biotab_into_metadata(biotab_dir, out_dir / f"{project_id}.case.tsv")
            shutil.rmtree(biotab_dir)
            print(f"  Removed {biotab_dir}")

    elif args.program:
        program = args.program.upper()
        print(f"Program : {program}")
        print(f"Output  : {out_dir}")
        if args.biotab:
            download_biotab(program, out_dir)
        download_cases_tsv_by_program(program, out_dir)
        if args.biotab:
            print("\n[biotab merge] Merging clinical_patient data into case TSV...")
            biotab_dir = out_dir / "biotab"
            merge_biotab_into_metadata(biotab_dir, out_dir / f"{program}.case.tsv")
            shutil.rmtree(biotab_dir)
            print(f"  Removed {biotab_dir}")

    else:
        case_ids = [c.strip() for c in args.cases.replace("\t", ",").split(",") if c.strip()]
        print(f"Cases   : {len(case_ids)} UUIDs")
        print(f"Output  : {out_dir}")
        download_cases_tsv_by_ids(case_ids, out_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
