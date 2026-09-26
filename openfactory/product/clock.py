"""When a turn is — the date the product role answers on, and when each line before it was said.

THE ROLE HAD NO CLOCK. Its prompt carried the conversation as `who: text` lines, oldest first, with
no time on any of them, and said nowhere what day it was. A person who came back after five days
of silence was answered "como combinamos ontem": the lines read as one sitting, and "yesterday"
was the model's guess at a gap it had no way to see. Nothing in the prompt was wrong; the one fact
that makes "ontem", "hoje" or "semana passada" true or false was simply not in it.

TWO FACTS CLOSE IT, both read from what is already recorded: every line of the conversation says
when it was said (`stamp`, which the transcript's renderer puts before each line), and the turn
says what day and time it is now and how long ago the previous message of this conversation was
(`now_block`) — in whole calendar days, computed here, because counting days between two dates is
arithmetic a model gets wrong and a relative word it then builds on is exactly the defect.

WHOSE DAY. A day starts at midnight somewhere: `product.timezone` in the registry names the zone
the product's people live in (an IANA name), and without one the day is UTC's — said as "UTC" in
the block, so the role never presents a UTC day as the reader's local one. A zone this Python
cannot resolve is logged and read as UTC, never guessed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, tzinfo

log = logging.getLogger(__name__)

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def current() -> datetime:
    """The moment a turn is answered — one function, so a test can say what day it is."""
    return datetime.now(UTC)


def zone_of(project) -> tuple[tzinfo, str]:
    """The zone this product's days are counted in, and its name — UTC when none is declared or
    the declared one cannot be resolved here."""
    name = str(getattr(getattr(project, "product", None), "timezone", "") or "").strip()
    if not name or name.upper() == "UTC":
        return UTC, "UTC"
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name), name
    except Exception:  # noqa: BLE001 — an unknown zone, or no zone data in this image
        log.warning("[%s] product.timezone %r cannot be resolved here; days are counted in UTC",
                    getattr(project, "name", "?"), name)
        return UTC, "UTC"


def _parse(ts: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(ts or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def stamp(ts: str, zone: tzinfo = UTC) -> str:
    """`2026-09-20 16:03` — when a line was said, in the product's zone; "" when `ts` says
    nothing readable, so a row written without one is printed as it always was."""
    when = _parse(ts)
    return when.astimezone(zone).strftime("%Y-%m-%d %H:%M") if when else ""


def days_between(earlier: datetime, later: datetime, zone: tzinfo = UTC) -> int:
    """Whole CALENDAR days from `earlier` to `later` in `zone` — 1 is yesterday, whatever the
    hours: 23:50 and 00:10 are a day apart, and two moments of one afternoon are none."""
    return (later.astimezone(zone).date() - earlier.astimezone(zone).date()).days


def _ago(days: int) -> str:
    if days <= 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def _day(when: datetime) -> str:
    return f"{_WEEKDAYS[when.weekday()]} {when.strftime('%Y-%m-%d %H:%M')}"


def now_block(now: datetime, *, last_ts: str = "", zone: tzinfo = UTC,
              zone_name: str = "UTC") -> str:
    """The prompt block that says when this turn is — facts only, no instruction: the role's
    task says what to do with them. `last_ts` is the previous line of this conversation, "" when
    this message opens it."""
    here = now.astimezone(zone)
    lines = ["## When", f"Now: {_day(here)} ({zone_name})."]
    last = _parse(last_ts)
    if last is None:
        lines.append("This message opens the conversation: nothing was said in it before.")
    else:
        days = days_between(last, now, zone)
        lines.append(f"The previous message of this conversation: {_day(last.astimezone(zone))} — "
                     f"{_ago(days)}.")
    return "\n".join(lines)


__all__ = ["current", "days_between", "now_block", "stamp", "zone_of"]
