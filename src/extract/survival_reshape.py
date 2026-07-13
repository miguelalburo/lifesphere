"""Derive per-subject survival-outcome nodes from harmonized clinical TSVs.

GDC does **not** ship precomputed survival endpoints (there is no ``OS`` / ``OS.time``
column); they are derived from vital status, death time, follow-up, and
progression/recurrence records. This module is a post-extract reshape (the same role
``biospecimen.py`` / ``omics_reshape.py`` play) that reads three already-written
clinical tables and emits one unified observation file:

  * ``{base}.survival.tsv``   (label ``Survival``, one row per subject per outcome type)

Each row carries a ``survival_type`` discriminator (``OS`` / ``PFI`` / ``DFI``), a
deterministic surrogate ``survival_id`` (``{case_id}:OS`` etc.), the endpoint event
and time, and the last follow-up time. A single ``HAS_SURVIVAL_RECORD`` edge
connects Subject → Survival.

Derivation follows the TCGA Clinical Data Resource (Liu et al., Cell 2018) adapted to
GDC harmonized fields:

  OS  — event = died; time = days_to_death, else last contact (censored).
  PFI — event = progression, recurrence, or death; time = earliest of those, else
        last contact (censored).
  DFI — event = recurrence; time = days_to_recurrence, else last contact (censored).

``last contact`` = max of ``diagnosis.days_to_last_follow_up`` and
``follow_up.days_to_follow_up`` across the subject's records.

Pure-``csv``; safe to unit-test on hand-built tables with no network.
"""

import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_COLUMNS = ["survival_id", "case_id", "survival_type", "event", "time_days", "last_follow_up_days"]


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


def compute_outcomes(subjects, diagnoses, follow_ups) -> list[dict]:
    """Return a flat list of survival rows covering OS/PFI/DFI. Pure function."""
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

    rows: list[dict] = []

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
            rows.append(_row(cid, "OS", 1 if dead else 0, os_time, contact))

        # --- Progression-Free Interval (progression | recurrence | death) ---
        pfi_event_times = [t for t in (prog, rec, dtd if dead else None) if t is not None]
        if pfi_event_times or (flagged and contact is not None):
            pfi_time = _min(pfi_event_times) if pfi_event_times else contact
            if pfi_time is not None:
                rows.append(_row(cid, "PFI", 1, pfi_time, contact))
        elif contact is not None:
            rows.append(_row(cid, "PFI", 0, contact, contact))

        # --- Disease-Free Interval (recurrence only) ---
        if rec is not None:
            rows.append(_row(cid, "DFI", 1, rec, contact))
        elif contact is not None:
            rows.append(_row(cid, "DFI", 0, contact, contact))

    return rows


def _row(case_id: str, survival_type: str, event: int, time_days: int,
         last_follow_up_days: int | None) -> dict:
    return {
        "survival_id": f"{case_id}:{survival_type}",
        "case_id": case_id,
        "survival_type": survival_type,
        "event": event,
        "time_days": time_days,
        "last_follow_up_days": last_follow_up_days if last_follow_up_days is not None else "",
    }


def reshape_survival(out_dir: Path, base_name: str) -> None:
    """Read {base}.subject/diagnosis/follow_up.tsv, write one unified survival TSV."""
    out_dir = Path(out_dir)
    subjects = _read(out_dir / f"{base_name}.subject.tsv")
    if not subjects:
        log.info("! skip survival reshape: no %s.subject.tsv", base_name)
        return
    diagnoses = _read(out_dir / f"{base_name}.diagnosis.tsv")
    follow_ups = _read(out_dir / f"{base_name}.follow_up.tsv")

    rows = compute_outcomes(subjects, diagnoses, follow_ups)
    path = out_dir / f"{base_name}.survival.tsv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_COLUMNS, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    events = sum(int(r["event"]) for r in rows)
    log.info("  %-42s %7d rows (%d events)", path.name, len(rows), events)
    print(f"  {path.name:42s} {len(rows):7d} rows ({events} events)")
