"""Survival table: derives OS, PFI, DFI directly from the case dict.

Produces one row per outcome type (up to three) per case. The derivation reads
true GDC column names via the case dict without the v1-era {entity}_ prefix
(e.g. ``demographic.vital_status``, not ``demographic_vital_status``).
"""

from __future__ import annotations

from .._base import Iter

NAME = "survival"
COLUMNS = None  # discovered dynamically via emit()


def _to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(float(str(value)))
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def iter_rows(case: dict) -> Iter:
    cid = case.get("case_id", "")
    if not cid:
        return

    demographic = case.get("demographic") or {}
    dead = demographic.get("vital_status", "").strip() == "Dead"
    dtd = _to_int(demographic.get("days_to_death"))

    contact_times: list[int] = []
    for d in case.get("diagnoses") or []:
        t = _to_int(d.get("days_to_last_follow_up"))
        if t is not None:
            contact_times.append(t)
    for fu in case.get("follow_ups") or []:
        t = _to_int(fu.get("days_to_follow_up"))
        if t is not None:
            contact_times.append(t)
    contact = max(contact_times) if contact_times else None

    prog_times: list[int] = []
    rec_times: list[int] = []
    flagged = False
    for fu in case.get("follow_ups") or []:
        p = _to_int(fu.get("days_to_progression"))
        if p is not None:
            prog_times.append(p)
        r = _to_int(fu.get("days_to_recurrence"))
        if r is not None:
            rec_times.append(r)
        if (fu.get("progression_or_recurrence") or "").strip().lower() == "yes":
            flagged = True

    base = {"case_id": cid, "case_submitter_id": case.get("submitter_id", "")}

    # OS
    os_time = (dtd if dead and dtd is not None else contact)
    if os_time is not None:
        yield {**base, "survival_id": f"{cid}:OS", "survival_type": "OS",
               "event": 1 if dead else 0, "time_days": os_time,
               "last_follow_up_days": contact if contact is not None else ""}

    # PFI — event if progression, recurrence, or flagged
    pfi_event_times = prog_times + rec_times
    if pfi_event_times or flagged:
        pfi_time = min(pfi_event_times) if pfi_event_times else contact
        if pfi_time is not None:
            yield {**base, "survival_id": f"{cid}:PFI", "survival_type": "PFI",
                   "event": 1, "time_days": pfi_time,
                   "last_follow_up_days": contact if contact is not None else ""}
    elif contact is not None:
        yield {**base, "survival_id": f"{cid}:PFI", "survival_type": "PFI",
               "event": 0, "time_days": contact, "last_follow_up_days": contact}

    # DFI — event only on documented recurrence
    if rec_times:
        yield {**base, "survival_id": f"{cid}:DFI", "survival_type": "DFI",
               "event": 1, "time_days": min(rec_times),
               "last_follow_up_days": contact if contact is not None else ""}
    elif contact is not None:
        yield {**base, "survival_id": f"{cid}:DFI", "survival_type": "DFI",
               "event": 0, "time_days": contact, "last_follow_up_days": contact}
