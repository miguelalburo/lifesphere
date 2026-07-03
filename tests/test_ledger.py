"""Unit tests for the load ledger (src/load/ledger).

No live database: the ledger's get/record helpers persist to a JSON file, so every
test drives a ledger file under a tmp dir. content_hash / csv_counts run purely on
CSVs in a tmp dir.
"""

import csv

from src.load import ledger

_URI = "bolt://localhost:7687"
_DB = "neo4j"


def _write_dataset(root, subjects, edges):
    """Create a minimal standardised dir: nodes/Subject.csv + edges/ENROLLS.csv."""
    (root / "nodes").mkdir(parents=True)
    (root / "edges").mkdir(parents=True)
    with open(root / "nodes" / "Subject.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "vital_status"])
        w.writerows(subjects)
    with open(root / "edges" / "ENROLLS.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_id", "target_id"])
        w.writerows(edges)


# --- content_hash ---------------------------------------------------------

def test_content_hash_stable_across_reads(tmp_path):
    _write_dataset(tmp_path, [["c1", "Alive"]], [["p1", "c1"]])
    assert ledger.content_hash(tmp_path) == ledger.content_hash(tmp_path)


def test_content_hash_changes_when_a_csv_changes(tmp_path):
    _write_dataset(tmp_path, [["c1", "Alive"]], [["p1", "c1"]])
    before = ledger.content_hash(tmp_path)
    with open(tmp_path / "nodes" / "Subject.csv", "a", newline="") as f:
        csv.writer(f).writerow(["c2", "Dead"])
    assert ledger.content_hash(tmp_path) != before


def test_content_hash_changes_when_a_csv_is_added(tmp_path):
    _write_dataset(tmp_path, [["c1", "Alive"]], [["p1", "c1"]])
    before = ledger.content_hash(tmp_path)
    with open(tmp_path / "nodes" / "Diagnosis.csv", "w", newline="") as f:
        csv.writer(f).writerow(["id"])
    assert ledger.content_hash(tmp_path) != before


# --- csv_counts -----------------------------------------------------------

def test_csv_counts(tmp_path):
    _write_dataset(tmp_path, [["c1", "Alive"], ["c2", "Dead"]], [["p1", "c1"]])
    assert ledger.csv_counts(tmp_path) == (2, 1)  # 2 node rows, 1 edge row


# --- get / record round-trip ---------------------------------------------

def test_get_returns_none_before_any_load(tmp_path):
    lf = tmp_path / "ledger.json"
    assert ledger.get(lf, _URI, _DB, "TCGA") is None


def test_record_then_get_round_trip(tmp_path):
    lf = tmp_path / "ledger.json"
    ledger.record(lf, _URI, _DB, "TCGA", "deadbeef", 10, 5)
    got = ledger.get(lf, _URI, _DB, "TCGA")
    assert got["sha256"] == "deadbeef"
    assert got["node_count"] == 10
    assert got["edge_count"] == 5


def test_record_persists_across_instances(tmp_path):
    lf = tmp_path / "ledger.json"
    ledger.record(lf, _URI, _DB, "TCGA", "deadbeef", 10, 5)
    # A fresh read (simulating a later process) still sees the entry on disk.
    assert ledger.get(lf, _URI, _DB, "TCGA")["sha256"] == "deadbeef"


def test_record_upserts_same_target(tmp_path):
    lf = tmp_path / "ledger.json"
    ledger.record(lf, _URI, _DB, "TCGA", "aaa", 1, 1)
    ledger.record(lf, _URI, _DB, "TCGA", "bbb", 2, 2)
    got = ledger.get(lf, _URI, _DB, "TCGA")
    assert got["sha256"] == "bbb"          # overwritten, not duplicated
    assert len(ledger._read(lf)) == 1


def test_entries_are_scoped_per_target(tmp_path):
    lf = tmp_path / "ledger.json"
    ledger.record(lf, _URI, _DB, "TCGA", "aaa", 1, 1)
    ledger.record(lf, _URI, "other_db", "TCGA", "bbb", 2, 2)
    # Same dataset, different database → independent entries, no false skip.
    assert ledger.get(lf, _URI, _DB, "TCGA")["sha256"] == "aaa"
    assert ledger.get(lf, _URI, "other_db", "TCGA")["sha256"] == "bbb"
    assert len(ledger._read(lf)) == 2


def test_read_tolerates_missing_and_corrupt_file(tmp_path):
    missing = tmp_path / "nope.json"
    assert ledger._read(missing) == {}
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not valid json")
    assert ledger._read(corrupt) == {}
