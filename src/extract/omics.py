"""
Download open-access omics data files from GDC for a set of cases.

Each omics type maps to a GDC (data_category, data_type) selector:

    expression   Transcriptome Profiling  / Gene Expression Quantification
    variation    Simple Nucleotide Variation / Masked Somatic Mutation
    methylation  DNA Methylation          / Methylation Beta Value

Given whatever case selector the main script used (project, program, or explicit
case UUIDs), we hit the /files endpoint filtered to those cases and the requested
data type(s), write a gdc-client manifest, and download the files into a
temporary staging dir.

A post-processing step then concatenates every per-sample file of a type
vertically into one long ``{out_dir}/{base}.{type}.matrix.tsv`` table, prefixing
each row with ``case_id``/``case_submitter_id``/``file_id``/``aliquot_id`` so the
stacked measurements stay attributable to their case, source file and aliquot.

A second post-process (``omics_reshape.py``) then splits that flat matrix into the
standardiser-ready shape: a deduped feature reference TSV (``{base}.gene.tsv``,
``.cpg_site.tsv``, ``.variant.tsv``) plus a per-assay observation TSV
(``{base}.gene_expression.tsv``, ``.methylation.tsv``, ``.somatic_mutation.tsv``)
carrying the aliquot ``sample_id`` and feature FK. These sit in ``out_dir`` next to
the clinical entity tables; the raw ``.matrix.tsv`` is kept for provenance and is
ignored by the standardiser as an unknown entity. The staging dir is removed.

Only open-access files are requested, so no GDC token is required. Files that are
not available for a given case set are simply skipped ("if available").
"""

import csv
import gzip
import shutil
import subprocess
import sys
from pathlib import Path

from . import gdc_api
from .biotab import write_manifest
from .omics_reshape import reshape_omics_type

# omics type -> GDC (data_category, data_type) selector.
OMICS_SPECS: dict[str, dict[str, str]] = {
    "expression": {
        "data_category": "Transcriptome Profiling",
        "data_type": "Gene Expression Quantification",
    },
    "variation": {
        "data_category": "Simple Nucleotide Variation",
        "data_type": "Masked Somatic Mutation",
    },
    "methylation": {
        "data_category": "DNA Methylation",
        "data_type": "Methylation Beta Value",
    },
}

# Per-file fields fetched for the manifest, size report, and file<->case mapping.
_FILE_FIELDS = ["file_id", "file_name", "md5sum", "file_size", "state"]


def _case_filter(mode: str, value) -> dict:
    """Build the /files case selector matching how the main script queried cases."""
    if mode == "project":
        return {"op": "=", "content": {"field": "cases.project.project_id", "value": value}}
    if mode == "program":
        return {"op": "=", "content": {"field": "cases.project.program.name", "value": value}}
    if mode == "cases":
        return {"op": "in", "content": {"field": "cases.case_id", "value": value}}
    raise ValueError(f"unknown case selector mode: {mode!r}")


def fetch_files(omics_type: str, case_filter: dict) -> list[dict]:
    """Return open-access /files hits for one omics type, over the given cases."""
    spec = OMICS_SPECS[omics_type]
    filters = {
        "op": "and",
        "content": [
            case_filter,
            {"op": "=", "content": {"field": "access", "value": "open"}},
            {"op": "=", "content": {"field": "data_category", "value": spec["data_category"]}},
            {"op": "=", "content": {"field": "data_type", "value": spec["data_type"]}},
        ],
    }
    hits: list[dict] = []
    from_pos, total = 0, None
    while total is None or from_pos < total:
        payload = {
            "filters": filters,
            "fields": ",".join([
                *_FILE_FIELDS,
                "cases.case_id", "cases.submitter_id",
                # aliquot uuid = the Sample node id omics measurements attach to.
                "cases.samples.portions.analytes.aliquots.aliquot_id",
            ]),
            "size": 500,
            "from": from_pos,
        }
        d = gdc_api.post(gdc_api.FILES_URL, payload)["data"]
        if total is None:
            total = d["pagination"]["total"]
        hits.extend(d["hits"])
        if not d["hits"]:
            break
        from_pos += len(d["hits"])
    return hits


def _run_gdc_client(manifest_path: Path, dest_dir: Path) -> None:
    print("  Running gdc-client download...")
    try:
        result = subprocess.run(
            ["gdc-client", "download", "-m", str(manifest_path), "-d", str(dest_dir),
             "--no-file-md5sum", "-n", "4"],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        sys.exit("  gdc-client not found on PATH — install it to download omics files.")
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(f"  gdc-client exited with code {result.returncode}")
    print("  Download complete.")


# ---------------------------------------------------------------------------
# Post-processing: concatenate per-sample downloads into one long TSV per type.
# ---------------------------------------------------------------------------

# Row-identity columns prepended to every concatenated record. aliquot_id is the
# Sample node id (Sample = aliquot); the reshape step uses it as the omics sample_id.
_ID_COLS = ["case_id", "case_submitter_id", "file_id", "aliquot_id"]


def _open_text(path: Path):
    """Open a (possibly gzipped) text file for reading."""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", newline="")
    return open(path, newline="")


def _first_aliquot(case: dict) -> str:
    """Dig out the aliquot uuid from a file's nested case→sample→…→aliquot tree."""
    for sample in case.get("samples") or []:
        for portion in sample.get("portions") or []:
            for analyte in portion.get("analytes") or []:
                for aliquot in analyte.get("aliquots") or []:
                    if aliquot.get("aliquot_id"):
                        return aliquot["aliquot_id"]
    return ""


def _file_meta(hits: list[dict]) -> dict[str, tuple[str, str, str, str]]:
    """file_id -> (case_id, case_submitter_id, file_name, aliquot_id) via first case."""
    meta: dict[str, tuple[str, str, str, str]] = {}
    for h in hits:
        cases = h.get("cases") or [{}]
        c = cases[0]
        meta[h["file_id"]] = (
            c.get("case_id", ""), c.get("submitter_id", ""),
            h.get("file_name", ""), _first_aliquot(c),
        )
    return meta


def _peek_header(path: Path) -> list[str]:
    """First non-comment (``#``) line of a tab file, split into columns."""
    with _open_text(path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            return line.rstrip("\n").split("\t")
    return []


def _iter_commented_rows(path: Path, drop_first_col_prefix: tuple = ()):
    """Yield dict rows from a ``#``-commented, header-led TSV (expression / MAF)."""
    with _open_text(path) as f:
        reader = csv.reader((ln for ln in f if not ln.startswith("#")), delimiter="\t")
        header = next(reader, None)
        if header is None:
            return
        for row in reader:
            if not row:
                continue
            if drop_first_col_prefix and row[0].startswith(drop_first_col_prefix):
                continue
            yield dict(zip(header, row))


def concatenate_omics_type(omics_type: str, dest_dir: Path, meta: dict, out_path: Path) -> int:
    """Stack every downloaded file of ``omics_type`` into one long TSV at ``out_path``.

    Returns the number of data rows written. Each row is prefixed with the
    case/file identity columns so the concatenated table stays attributable.
    """
    # Resolve which files actually landed on disk (dest_dir/{file_id}/{file_name}).
    present = [
        (fid, dest_dir / fid / fname, ci, cs, aliquot)
        for fid, (ci, cs, fname, aliquot) in meta.items()
        if (dest_dir / fid / fname).exists()
    ]
    if not present:
        print("  Nothing to concatenate — no data files found on disk.")
        return 0

    if omics_type == "methylation":
        columns = [*_ID_COLS, "cpg", "beta_value"]
    else:  # expression / variation: take the (shared) header from the first file.
        columns = [*_ID_COLS, *_peek_header(present[0][1])]

    drop_prefix = ("N_",) if omics_type == "expression" else ()
    n = 0
    with open(out_path, "w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for fid, path, case_id, case_submitter_id, aliquot_id in present:
            ident = {"case_id": case_id, "case_submitter_id": case_submitter_id,
                     "file_id": fid, "aliquot_id": aliquot_id}
            if omics_type == "methylation":
                with _open_text(path) as f:
                    for line in f:
                        line = line.rstrip("\n")
                        if not line:
                            continue
                        parts = line.split("\t")
                        writer.writerow({**ident, "cpg": parts[0],
                                         "beta_value": parts[1] if len(parts) > 1 else ""})
                        n += 1
            else:
                for rec in _iter_commented_rows(path, drop_prefix):
                    writer.writerow({**ident, **rec})
                    n += 1
    print(f"  Concatenated {len(present)} files -> {out_path.name} ({n} rows)")
    return n


def download_omics_type(omics_type: str, case_filter: dict, out_dir: Path, base_name: str) -> None:
    """Fetch, manifest, download and concatenate all open-access files of one omics type."""
    spec = OMICS_SPECS[omics_type]
    print(f"\n[omics:{omics_type}] {spec['data_category']} / {spec['data_type']}")
    hits = fetch_files(omics_type, case_filter)
    if not hits:
        print("  No files available for these cases — skipping.")
        return

    total_size = sum((h.get("file_size") or 0) for h in hits)
    print(f"  Found {len(hits)} files ({total_size / 1024 / 1024:.1f} MB).")

    # Download into a temporary staging dir; gdc-client lays files out as
    # {staging}/{file_id}/{file_name}. We concatenate from there into a raw
    # {base}.{type}.matrix.tsv, then reshape that into standardiser-ready feature +
    # observation TSVs, and finally remove the staging dir.
    staging = out_dir / f".{omics_type}_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    manifest_path = staging / "manifest.txt"
    write_manifest(hits, manifest_path)

    try:
        _run_gdc_client(manifest_path, staging)
        # Raw matrix gets a `.matrix.tsv` name so it (a) never collides with a
        # reshaped observation file (methylation's obs entity is also "methylation")
        # and (b) is ignored by the standardiser as an unknown entity.
        concat_path = out_dir / f"{base_name}.{omics_type}.matrix.tsv"
        n = concatenate_omics_type(omics_type, staging, _file_meta(hits), concat_path)
        if n:
            # Reshape the flat matrix into standardiser-ready feature + observation
            # TSVs (Sample→Observation→Feature); see src/extract/omics_reshape.py.
            reshape_omics_type(omics_type, concat_path, out_dir, base_name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def download_omics(omics_types: list[str], mode: str, value, out_dir: Path, base_name: str) -> None:
    """Download + concatenate every requested omics type for the cases picked by ``mode``/``value``."""
    case_filter = _case_filter(mode, value)
    for omics_type in omics_types:
        if omics_type not in OMICS_SPECS:
            raise ValueError(f"unknown omics type: {omics_type!r}")
        download_omics_type(omics_type, case_filter, out_dir, base_name)
