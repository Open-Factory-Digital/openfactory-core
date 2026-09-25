"""The expected arrival, and when a move of it is a delay worth telling (REQ-0003)."""

from __future__ import annotations

from datetime import datetime, timedelta

from tracking.events import DELAYED

#: A later arrival by more than this is a delay every shipper on the sailing is told about.
DELAY_WORTH_TELLING = timedelta(hours=6)


def delay_event(sailing: str, told_eta: datetime, new_eta: datetime) -> dict | None:
    """The event to emit when `new_eta` is late enough against the arrival shippers were last told
    — None when it is not, so nobody is told twice about the same delay."""
    if new_eta - told_eta <= DELAY_WORTH_TELLING:
        return None
    return {"event": DELAYED, "sailing": sailing, "eta": new_eta.isoformat()}
