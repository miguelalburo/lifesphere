import subprocess
import sys
from pathlib import Path

from . import gdc_api


def fetch_manifest(project_id: str) -> list[dict]:
    payload = {
        "filters": {
            "op": "and",
            "content": [
                {"op": "=", "content": {"field": "cases.project.project_id", "value": project_id}},
                {"op": "=", "content": {"field": "data_format", "value": "bcr biotab"}},
            ],
        },
        "fields": "file_id,file_name,md5sum,file_size,state",
        "size": 500,
    }
    result = gdc_api.post(gdc_api.FILES_URL, payload)
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
            f.write(
                f"{h['file_id']}\t{h['file_name']}\t{h.get('md5sum', '')}\t"
                f"{h.get('file_size', '')}\t{h.get('state', '')}\n"
            )


def download_biotab(project_id: str, out_dir: Path) -> None:
    print(f"\n[1/2] Fetching BCR BioTab manifest for {project_id}...")
    hits = fetch_manifest(project_id)
    if not hits:
        return

    print(f"  Found {len(hits)} files:")
    for h in hits:
        print(f"    {h['file_name']}  ({(h.get('file_size') or 0) / 1024:.1f} KB)")

    biotab_dir = out_dir / "biotab"
    biotab_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = biotab_dir / "manifest.txt"
    write_manifest(hits, manifest_path)
    print(f"  Manifest written to {manifest_path}")

    print("  Running gdc-client download...")
    result = subprocess.run(
        ["gdc-client", "download", "-m", str(manifest_path), "-d", str(biotab_dir),
         "--no-file-md5sum", "-n", "4"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(f"  gdc-client exited with code {result.returncode}")
    print(f"  Done. Files saved under {biotab_dir}/")
