"""CLI: ``python -m src.extract [options] <output_dir>``

Download clinical/biospecimen tab-delimited files from GDC.

Usage:
  python -m src.extract --project TCGA-PRAD [--biotab] <output_dir>
  python -m src.extract --program TCGA                  <output_dir>
  python -m src.extract --cases uuid1,uuid2             <output_dir>

Exactly one of --project, --program, or --cases is required.

Add any of --expression, --variation, --methylation to also download the
matching open-access omics files (via gdc-client) for the same set of cases
into {output_dir}/omics/{type}/, each with a {type}.files.tsv file<->case map.
Missing data types are skipped silently ("if available").

Each fetch writes one TSV per entity: {base}.subject.tsv (1 row/case), plus
{base}.diagnosis.tsv, .treatment.tsv, .pathology_detail.tsv, .follow_up.tsv,
.molecular_test.tsv, .exposure.tsv, .family_history.tsv,
.other_clinical_attribute.tsv, .file.tsv at their true (1:many) grain, and
{base}.sample.tsv at aliquot grain (sample descriptors merged onto each aliquot;
.aliquot.tsv is consumed by that post-processing step).

--project downloads the per-entity TSVs for the project.
--program downloads the per-entity TSVs for all cases in the program.
--biotab  (with --project or --program) also downloads BCR BioTab files and
          merges clinical_patient data into the case TSV on case_id.
--cases   downloads the per-entity TSVs for the given case UUIDs only
          (comma- or tab-separated).
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from . import download_biotab, download_cases_tsv, download_cases_tsv_by_ids, download_cases_tsv_by_program, download_omics
from .biotab_merge import merge_biotab_into_metadata

_OMICS_TYPES = ("expression", "variation", "methylation")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.extract",
        description="Download GDC clinical/biospecimen data by project or case UUIDs.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", metavar="PROJECT_ID",
                       help="GDC project ID (e.g. TCGA-PRAD).")
    group.add_argument("--program", metavar="PROGRAM",
                       help="GDC program name (e.g. TCGA).")
    group.add_argument("--cases", metavar="UUID[,UUID...]",
                       help="Comma- or tab-separated list of case UUIDs.")
    parser.add_argument("--biotab", action="store_true", default=False,
                        help="Download BCR BioTab files and merge clinical_patient data into the case TSV.")
    parser.add_argument("--expression", action="store_true", default=False,
                        help="Also download open-access gene expression quantification files.")
    parser.add_argument("--variation", action="store_true", default=False,
                        help="Also download open-access masked somatic mutation files.")
    parser.add_argument("--methylation", action="store_true", default=False,
                        help="Also download open-access methylation beta value files.")
    parser.add_argument("output_dir", help="Directory to save files into")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
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
            merge_biotab_into_metadata(biotab_dir, out_dir / f"{project_id}.subject.tsv")
            shutil.rmtree(biotab_dir)
            print(f"  Removed {biotab_dir}")
        omics_selector = ("project", project_id, project_id)

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
            merge_biotab_into_metadata(biotab_dir, out_dir / f"{program}.subject.tsv")
            shutil.rmtree(biotab_dir)
            print(f"  Removed {biotab_dir}")
        omics_selector = ("program", program, program)

    else:
        case_ids = [c.strip() for c in args.cases.replace("\t", ",").split(",") if c.strip()]
        print(f"Cases   : {len(case_ids)} UUIDs")
        print(f"Output  : {out_dir}")
        download_cases_tsv_by_ids(case_ids, out_dir)
        omics_selector = ("cases", case_ids, "cases")

    omics_types = [t for t in _OMICS_TYPES if getattr(args, t)]
    if omics_types:
        mode, value, base_name = omics_selector
        print(f"\n[omics] Requested: {', '.join(omics_types)}")
        download_omics(omics_types, mode, value, out_dir, base_name)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
