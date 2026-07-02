"""Derive per-subject survival-outcome nodes from harmonized clinical TSVs.

GDC does **not** ship precomputed survival endpoints (there is no ``OS`` / ``OS.time``
column); they are derived from vital status, death time, follow-up, and
progression/recurrence records. This module is a post-extract reshape (the same role
``biospecimen.py`` / ``omics_reshape.py`` play) that reads three already-written
clinical tables and emits one observation node per outcome, per subject:

  * ``{base}.overall_survival.tsv``          (label ``OverallSurvival``)
  * ``{base}.progression_free_interval.tsv`` (label ``ProgressionFreeInterval``)
  * ``{base}.disease_free_interval.tsv``     (label ``DiseaseFreeInterval``)

All three share one column schema — ``survival_id, case_id, outcome_type, event,
time_days`` — because in the KG they are subclasses of a common ``SurvivalOutcome``
(``is_a: survival outcome`` in ``schema_config.yaml``). Each is wired ``(Subject)
-[:HAS_*]->(<outcome>)`` via ``entities.json`` / ``edges.json``; the generic
standardiser then emits the node + edge with no engine change. Surrogate ids are
deterministic (``{case_id}:OS`` / ``:PFI`` / ``:DFI``) so re-runs are idempotent.

Derivation follows the TCGA Clinical Data Resource (Liu et al., Cell 2018) adapted to
GDC harmonized fields:

  OS  — event = died; time = days_to_death, else last contact (censored).
  PFI — event = progression, recurrence, or death; time = earliest of those, else
        last contact (censored).
  DFI — event = recurrence; time = days_to_recurrence, else last contact (censored).

``last contact`` = max of ``diagnosis.days_to_last_follow_up`` and
``follow_up.days_to_follow_up`` across the subject's records.

Caveats (documented, not silently assumed):
  * ``days_to_death`` must be extracted (``gdc_data_dict.json`` demographic list) — a
    dead subject missing it censors at last contact rather than dropping.
  * TCGA-CDR restricts DFI to subjects tumor-free after initial therapy; GDC's
    harmonized clinical fields carry no clean initial-tumor-free flag, so DFI here is
    a recurrence-based approximation over all subjects.
  * A subject with no usable time for an outcome is skipped for that outcome (the
    standardiser tolerates missing rows); it is not emitted with a null time.

Pure-``csv``; safe to unit-test on hand-built tables with no network.
"""

import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# outcome_type -> (output entity name, id column). Each subclass gets a distinct id
# column because the loader keys node labels by id_col (see neo4j_loader.load_schema);
# a shared id column would collapse the three labels. The shared abstraction lives in
# the identical property schema (outcome_type, event, time_days) + `is_a` inheritance.
_OUTPUTS = {
    "OS":  ("overall_survival", "os_id"),
    "PFI": ("progression_free_interval", "pfi_id"),
    "DFI": ("disease_free_interval", "dfi_id"),
}

_PROPS = ["case_id", "outcome_type", "event", "time_days"]


def _to_int(value: str):
    """Parse a GDC day count; return a non-negative int or ``None``.

    Tolerates floats (``"1688.0"``) and blanks; negatives are data errors -> dropped.
    """
    if value is None or value == "":
        return None
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _min(values) -> int | None:
    vals = [v for v in values if v is not None]
    return min(vals) if vals else None


def _max(values) -> int | None:
    vals = [v for v in values if v is not None]
    return max(vals) if vals else None


def compute_outcomes(subjects, diagnoses, follow_ups) -> dict[str, list[dict]]:
    """Return {outcome_type: [row, ...]} keyed by OS/PFI/DFI. Pure function."""
    # Index child records by case for last-contact and event derivation.
    last_contact: dict[str, list[int]] = {}
    progression: dict[str, list[int]] = {}
    recurrence: dict[str, list[int]] = {}
    prog_or_rec_flag: dict[str, bool] = {}

    for d in diagnoses:
        cid = d.get("case_id", "")
        last_contact.setdefault(cid, []).append(_to_int(d.get("diagnosis_days_to_last_follow_up")))

    for fu in follow_ups:
        cid = fu.get("case_id", "")
        last_contact.setdefault(cid, []).append(_to_int(fu.get("follow_up_days_to_follow_up")))
        progression.setdefault(cid, []).append(_to_int(fu.get("follow_up_days_to_progression")))
        recurrence.setdefault(cid, []).append(_to_int(fu.get("follow_up_days_to_recurrence")))
        if (fu.get("follow_up_progression_or_recurrence") or "").strip().lower() == "yes":
            prog_or_rec_flag[cid] = True

    out: dict[str, list[dict]] = {"OS": [], "PFI": [], "DFI": []}

    for s in subjects:
        cid = s.get("case_id", "")
        if not cid:
            continue
        dead = (s.get("demographic_vital_status") or "").strip() == "Dead"
        dtd = _to_int(s.get("demographic_days_to_death"))
        contact = _max(last_contact.get(cid, []))
        prog = _min(progression.get(cid, []))
        rec = _min(recurrence.get(cid, []))
        flagged = prog_or_rec_flag.get(cid, False)

        # --- Overall Survival ---
        os_time = dtd if (dead and dtd is not None) else contact
        if os_time is not None:
            out["OS"].append(_row(cid, "OS", 1 if dead else 0, os_time))

        # --- Progression-Free Interval (progression | recurrence | death) ---
        pfi_event_times = [t for t in (prog, rec, dtd if dead else None) if t is not None]
        if pfi_event_times or (flagged and contact is not None):
            pfi_time = _min(pfi_event_times) if pfi_event_times else contact
            if pfi_time is not None:
                out["PFI"].append(_row(cid, "PFI", 1, pfi_time))
        elif contact is not None:
            out["PFI"].append(_row(cid, "PFI", 0, contact))

        # --- Disease-Free Interval (recurrence only) ---
        if rec is not None:
            out["DFI"].append(_row(cid, "DFI", 1, rec))
        elif contact is not None:
            out["DFI"].append(_row(cid, "DFI", 0, contact))

    return out


def _row(case_id: str, outcome: str, event: int, time_days: int) -> dict:
    id_col = _OUTPUTS[outcome][1]
    return {
        id_col: f"{case_id}:{outcome}",
        "case_id": case_id,
        "outcome_type": outcome,
        "event": event,
        "time_days": time_days,
    }


def reshape_survival(out_dir: Path, base_name: str) -> None:
    """Read {base}.subject/diagnosis/follow_up.tsv, write the three outcome TSVs."""
    out_dir = Path(out_dir)
    subjects = _read(out_dir / f"{base_name}.subject.tsv")
    if not subjects:
        log.info("! skip survival reshape: no %s.subject.tsv", base_name)
        return
    diagnoses = _read(out_dir / f"{base_name}.diagnosis.tsv")
    follow_ups = _read(out_dir / f"{base_name}.follow_up.tsv")

    outcomes = compute_outcomes(subjects, diagnoses, follow_ups)
    for outcome, (entity, id_col) in _OUTPUTS.items():
        rows = outcomes[outcome]
        path = out_dir / f"{base_name}.{entity}.tsv"
        columns = [id_col, *_PROPS]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columns, delimiter="\t", extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        events = sum(int(r["event"]) for r in rows)
        log.info("  %-42s %7d rows (%d events)", path.name, len(rows), events)
        print(f"  {path.name:42s} {len(rows):7d} rows ({events} events)")
