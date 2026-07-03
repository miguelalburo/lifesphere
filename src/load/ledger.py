"""Load ledger — skip re-ingesting a standardised dataset whose content is unchanged.

The Bolt loader is already idempotent (``MERGE`` on a deterministic ``id`` never
creates duplicate nodes/relationships). This ledger sits on top purely to avoid
*wasted work*: it records, in a JSON file on disk, one entry per (target database,
dataset) carrying a content hash of the standardised CSVs. On a re-run the caller
compares the freshly computed hash against the stored one and skips the load when
nothing changed.

The hash covers every ``nodes/*.csv`` and ``edges/*.csv`` under the input dir, so
any add/remove/edit of a CSV changes it. Entries are keyed by ``uri``/``database``
as well as ``dataset`` so the same CSVs loaded into two different targets are
tracked independently — this replaces the automatic per-DB scoping the old
in-graph ``:_LoadRun`` node had for free.

Because the ledger now lives outside Neo4j, it is *not* wiped when the database is
cleared out-of-band. ``--fresh`` re-records after its load, and ``--force`` always
reloads, but if a database is emptied by some other means the stale entry will
still cause a skip — use ``--force`` in that case.

Pure helpers here read/write a JSON file; nothing in this module opens a driver or
touches Neo4j.
"""

import csv
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LEDGER_FILE = Path(".load_ledger.json")
_LEDGER_VERSION = 1


def _csv_files(input_dir: Path) -> list[Path]:
    """All standardised CSVs (nodes/ then edges/), sorted for a stable hash."""
    nodes = sorted((input_dir / "nodes").glob("*.csv"))
    edges = sorted((input_dir / "edges").glob("*.csv"))
    return nodes + edges


def content_hash(input_dir: Path) -> str:
    """sha256 over the sorted set of (relative_name, per-file sha256) of the CSVs.

    Hashing each file's own digest alongside its path means the result changes if
    a file's bytes change, a file is added/removed, or a file is renamed — but is
    stable across repeated reads and independent of filesystem ordering.
    """
    outer = hashlib.sha256()
    for path in _csv_files(input_dir):
        rel = path.relative_to(input_dir).as_posix()
        inner = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                inner.update(chunk)
        outer.update(rel.encode("utf-8"))
        outer.update(b"\0")
        outer.update(inner.hexdigest().encode("ascii"))
        outer.update(b"\0")
    return outer.hexdigest()


def _row_count(path: Path) -> int:
    with open(path, newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def csv_counts(input_dir: Path) -> tuple[int, int]:
    """Total node rows and edge rows across the standardised CSVs (for provenance)."""
    nodes = sum(_row_count(p) for p in sorted((input_dir / "nodes").glob("*.csv")))
    edges = sum(_row_count(p) for p in sorted((input_dir / "edges").glob("*.csv")))
    return nodes, edges


def _entry_key(uri: str, database: str, dataset: str) -> str:
    """Stable per-target key. Tab-joined so it round-trips as a plain JSON string."""
    return "\t".join((uri, database, dataset))


def _read(ledger_file: Path) -> dict[str, dict]:
    """Return the ``entries`` map, or {} for a missing/empty/corrupt ledger file."""
    try:
        with open(ledger_file, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    entries = data.get("entries")
    return entries if isinstance(entries, dict) else {}


def _write(ledger_file: Path, entries: dict[str, dict]) -> None:
    """Atomically overwrite the ledger file with ``entries``."""
    ledger_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": _LEDGER_VERSION, "entries": entries}
    fd, tmp = tempfile.mkstemp(
        dir=ledger_file.parent, prefix=ledger_file.name, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        os.replace(tmp, ledger_file)  # atomic on the same filesystem
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get(ledger_file: Path, uri: str, database: str, dataset: str) -> dict | None:
    """Return the stored ledger entry for a target/dataset, or None if never loaded."""
    return _read(ledger_file).get(_entry_key(uri, database, dataset))


def record(
    ledger_file: Path,
    uri: str,
    database: str,
    dataset: str,
    sha: str,
    node_count: int,
    edge_count: int,
) -> None:
    """Upsert the ledger entry for a target/dataset after a successful load."""
    entries = _read(ledger_file)
    entries[_entry_key(uri, database, dataset)] = {
        "dataset": dataset,
        "uri": uri,
        "database": database,
        "sha256": sha,
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "node_count": node_count,
        "edge_count": edge_count,
    }
    _write(ledger_file, entries)
