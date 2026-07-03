"""Tests for the survival derivation (src/extract/survival_reshape).

Unit tests pin the OS / PFI / DFI event+time rules (TCGA-CDR adapted to GDC fields)
on hand-built clinical rows, including the death-time-missing censoring fallback and
last-contact aggregation. An integration test runs reshape -> standardise to prove
the emitted TSVs match the schemas and the Subject->outcome edges resolve.
"""

import csv
from pathlib import Path

from src.extract.survival_reshape import compute_outcomes, reshape_survival
from src.standardise.run import run

BASE = "SURV"


def _by_case(rows):
    return {r["case_id"]: r for r in rows}


def _subj(cid, vital, dtd=""):
    return {"case_id": cid, "demographic_vital_status": vital, "demographic_days_to_death": dtd}


def _diag(cid, last_fu=""):
    return {"case_id": cid, "diagnosis_days_to_last_follow_up": last_fu}


def _fu(cid, days_to_fu="", prog="", rec="", flag=""):
    return {
        "case_id": cid,
        "follow_up_days_to_follow_up": days_to_fu,
        "follow_up_days_to_progression": prog,
        "follow_up_days_to_recurrence": rec,
        "follow_up_progression_or_recurrence": flag,
    }


# --------------------------------------------------------------------------- #
# Unit                                                                          #
# --------------------------------------------------------------------------- #

def test_os_dead_uses_days_to_death():
    out = compute_outcomes([_subj("c1", "Dead", "300")], [_diag("c1", "100")], [])
    os_ = _by_case(out["OS"])["c1"]
    assert os_["event"] == 1 and os_["time_days"] == 300
    assert os_["os_id"] == "c1:OS" and os_["outcome_type"] == "OS"


def test_os_alive_censors_at_last_contact():
    out = compute_outcomes([_subj("c1", "Alive")],
                           [_diag("c1", "100")],
                           [_fu("c1", days_to_fu="250")])
    os_ = _by_case(out["OS"])["c1"]
    assert os_["event"] == 0 and os_["time_days"] == 250  # max(100, 250)


def test_os_dead_without_death_time_falls_back_to_last_contact():
    out = compute_outcomes([_subj("c1", "Dead", "")], [_diag("c1", "180")], [])
    os_ = _by_case(out["OS"])["c1"]
    assert os_["event"] == 1 and os_["time_days"] == 180  # censored time, event kept


def test_os_skipped_when_no_time_available():
    out = compute_outcomes([_subj("c1", "Dead", "")], [], [])
    assert out["OS"] == []  # no death time, no follow-up -> not emitted


def test_pfi_event_is_earliest_of_progression_recurrence_death():
    out = compute_outcomes([_subj("c1", "Dead", "500")],
                           [_diag("c1", "100")],
                           [_fu("c1", prog="200", rec="300")])
    pfi = _by_case(out["PFI"])["c1"]
    assert pfi["event"] == 1 and pfi["time_days"] == 200  # min(200,300,500)


def test_pfi_flag_only_yes_uses_last_contact():
    out = compute_outcomes([_subj("c1", "Alive")],
                           [_diag("c1", "400")],
                           [_fu("c1", days_to_fu="400", flag="Yes")])
    pfi = _by_case(out["PFI"])["c1"]
    assert pfi["event"] == 1 and pfi["time_days"] == 400


def test_pfi_censored_when_no_event():
    out = compute_outcomes([_subj("c1", "Alive")], [_diag("c1", "365")], [])
    pfi = _by_case(out["PFI"])["c1"]
    assert pfi["event"] == 0 and pfi["time_days"] == 365


def test_dfi_event_only_on_recurrence():
    out = compute_outcomes([_subj("c1", "Dead", "500")],
                           [_diag("c1", "100")],
                           [_fu("c1", prog="200")])  # progression, NOT recurrence
    dfi = _by_case(out["DFI"])["c1"]
    assert dfi["event"] == 0 and dfi["time_days"] == 100  # death/progression don't count for DFI

    out2 = compute_outcomes([_subj("c1", "Alive")], [_diag("c1", "100")],
                            [_fu("c1", rec="150")])
    dfi2 = _by_case(out2["DFI"])["c1"]
    assert dfi2["event"] == 1 and dfi2["time_days"] == 150


def test_negative_and_blank_days_are_ignored():
    out = compute_outcomes([_subj("c1", "Alive")],
                           [_diag("c1", "-5")],           # bad -> ignored
                           [_fu("c1", days_to_fu="120.0")])  # float tolerated
    os_ = _by_case(out["OS"])["c1"]
    assert os_["time_days"] == 120


# --------------------------------------------------------------------------- #
# Integration: reshape -> standardise                                          #
# --------------------------------------------------------------------------- #

def _tsv(path: Path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, delimiter="\t")
        w.writeheader()
        w.writerows(rows)


def _read(path: Path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_reshape_then_standardise_emits_nodes_and_edges(tmp_path):
    raw = tmp_path / "raw"
    _tsv(raw / f"{BASE}.subject.tsv",
         ["case_id", "demographic_vital_status", "demographic_days_to_death"],
         [_subj("c1", "Dead", "300"), _subj("c2", "Alive")])
    _tsv(raw / f"{BASE}.diagnosis.tsv",
         ["case_id", "diagnosis_days_to_last_follow_up"],
         [_diag("c1", "100"), _diag("c2", "800")])
    _tsv(raw / f"{BASE}.follow_up.tsv",
         ["case_id", "follow_up_days_to_follow_up", "follow_up_days_to_progression",
          "follow_up_days_to_recurrence", "follow_up_progression_or_recurrence"],
         [_fu("c2", days_to_fu="800", rec="600")])

    reshape_survival(raw, BASE)
    assert (raw / f"{BASE}.overall_survival.tsv").exists()

    out = tmp_path / "std"
    run(raw, out)

    os_nodes = {n["id"]: n for n in _read(out / "nodes" / "OverallSurvival.csv")}
    assert os_nodes["c1:OS"]["event"] == "1" and os_nodes["c1:OS"]["timeDays"] == "300"
    assert "caseId" not in os_nodes["c1:OS"]  # dropped from node props
    assert os_nodes["c1:OS"]["outcomeType"] == "OS"

    edges = _read(out / "edges" / "HAS_OVERALL_SURVIVAL.csv")
    pairs = {(e["source_id"], e["target_id"]) for e in edges}
    assert ("c1", "c1:OS") in pairs and ("c2", "c2:OS") in pairs

    dfi = {n["id"]: n for n in _read(out / "nodes" / "DiseaseFreeInterval.csv")}
    assert dfi["c2:DFI"]["event"] == "1" and dfi["c2:DFI"]["timeDays"] == "600"
