#!/usr/bin/env python3
"""
Integration tester for the omics extraction pipeline.

Reads the case UUIDs from ``tests/case_uuids.txt`` and runs the full extraction
(``scripts/download_gdc.py``) for those cases with all three omics
types enabled, then checks that each concatenated ``cases.<omics>.tsv`` table
was produced and is non-empty.

This hits the live GDC API and downloads real files via ``gdc-client``, so it is
kept out of the unit-test suite (tests/) and run manually:

    python tests/run_omics_extraction.py                # -> tests/output/
    python tests/run_omics_extraction.py /some/out_dir  # custom output dir
"""

import subprocess
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parent
UUID_FILE = TEST_DIR / "case_uuids.txt"
DOWNLOAD_SCRIPT = REPO_ROOT / "scripts" / "download_gdc.py"
OMICS_TYPES = ("expression", "variation", "methylation")


def read_case_uuids(path: Path) -> list[str]:
    """One UUID per non-comment line; only the first whitespace-separated token."""
    uuids = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        uuids.append(line.split()[0])
    if not uuids:
        sys.exit(f"No case UUIDs found in {path}")
    return uuids


def run_extraction(case_uuids: list[str], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(DOWNLOAD_SCRIPT),
        "--cases", ",".join(case_uuids),
        *(f"--{t}" for t in OMICS_TYPES),
        str(out_dir),
    ]
    print("Running:", " ".join(cmd), "\n")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if result.returncode != 0:
        sys.exit(f"Extraction failed with exit code {result.returncode}")


def check_outputs(out_dir: Path) -> None:
    """Assert each concatenated omics TSV exists and has at least one data row."""
    print("\n=== Verifying concatenated omics tables ===")
    failures = []
    for t in OMICS_TYPES:
        tsv = out_dir / f"cases.{t}.tsv"
        if not tsv.exists():
            failures.append(f"missing: {tsv}")
            continue
        rows = tsv.read_text().count("\n") - 1  # minus header
        status = "OK" if rows > 0 else "EMPTY"
        print(f"  [{status}] {tsv.relative_to(out_dir)}  ({max(rows, 0)} data rows)")
        if rows <= 0:
            failures.append(f"no data rows: {tsv}")
    if failures:
        sys.exit("FAILED:\n  " + "\n  ".join(failures))
    print("\nAll omics tables present and non-empty. PASS.")


def main() -> None:
    out_dir = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else TEST_DIR / "output"
    case_uuids = read_case_uuids(UUID_FILE)
    print(f"Cases  : {len(case_uuids)} -> {', '.join(case_uuids)}")
    print(f"Output : {out_dir}\n")
    run_extraction(case_uuids, out_dir)
    check_outputs(out_dir)


if __name__ == "__main__":
    main()
