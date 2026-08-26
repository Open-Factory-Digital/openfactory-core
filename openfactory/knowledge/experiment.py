"""Choosing which arm a ticket runs in, so the A/B measures the map rather than the calendar.

Turning `knowledge_map` on for a project makes every ticket from that moment run WITH the map, and
the only thing left to compare against is history. That is a before/after, not an experiment, and it
is confounded by everything that changed in between — including this platform's own changes. The
review-repair invocation started being counted on 2026-07-26, so tickets after that date carry cost
and turns that identical tickets before it did not. A before/after would read that as the map making
things worse.

So the arm is chosen PER TICKET, and both arms run under the same platform version, the same ticket
mix, the same week and the same codebase. The work would have been done either way, so the
experiment costs nothing extra — what it costs is that half the tickets run without an accelerator
that may well work, for as long as the window is open.

BALANCE, NOT STRICT ALTERNATION. Ticket numbers have gaps: a split invents new ones, some are never
picked up, a job can be skipped or retried. Alternating blindly (or on parity) drifts under all of
those and leaves one arm short exactly when someone is watching the arms fill up. Choosing the arm
with FEWER runs so far is self-correcting: whatever happened to the last ticket, the next one goes
where the evidence is thinner.

AND IT DEGRADES TOWARD THE PROJECT'S SETTING. If the history cannot be read, the ticket runs the way
the project is configured — with the map. A run is never lost over an experiment, and the failure
shows up as a slightly uneven split rather than as a job that did not happen.

DECIDED ON THE WORKER, OBEYED IN THE BOX. The job itself runs inside an ephemeral Fargate task that
is deliberately credential-less (ADR-0001 D-4) — it talks to GitHub and to nothing else, and the
sandbox scrubs AWS credentials on the way in. Deciding the arm there would mean reading the metrics
table from a container that cannot reach it, degrading to "always inject" every single time: the
experiment would never run while looking exactly as though it were. So the worker chooses and passes
`OPENFACTORY_KNOWLEDGE_ARM` into the box, which does as it is told.
"""

from __future__ import annotations

import logging

log = logging.getLogger("openfactory.knowledge")

INJECTED, OFF = "injected", "off"


def choose_arm(recent: list[str], *, default_on: bool = True) -> bool:
    """Whether THIS ticket should be given the map, from the arms already recorded.

    `recent` is the arm of each prior ticket, in any order. Only decided arms count: `unavailable`
    means the project opted in but the map could not be trusted for that checkout, so the agent ran
    without it — it is evidence about the control, but it was not a CHOICE, and counting it would
    make the chooser think it had already balanced when it had not.
    """
    injected = sum(1 for a in recent if a == INJECTED)
    off = sum(1 for a in recent if a == OFF)
    if injected == off:
        # a tie, including the very first ticket: start with the project's own setting, so a
        # deployment that never turns the experiment on behaves exactly as it does today
        return default_on
    return injected < off


def recent_arms(project_name: str, *, table_name: str | None = None, limit: int = 200) -> list[str]:
    """The arms of this project's past tickets, newest first. `[]` on any trouble.

    Read from the metrics the platform already writes — there is no second store to keep in step,
    and the dashboard the human is watching is reading exactly the same rows."""
    try:
        from openfactory.api.metrics_view import scan_records

        rows = [
            r for r in scan_records(table_name)
            if r.get("kind") == "job"
            and str(r.get("pk") or r.get("project") or "") == project_name
            and r.get("knowledge")
        ]
        rows.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
        return [str(r.get("knowledge")) for r in rows[:limit]]
    except Exception as exc:  # noqa: BLE001 — an experiment must never cost a run
        log.warning("knowledge experiment: could not read past arms for %s (%s); "
                    "falling back to the project's setting", project_name, exc)
        return []


def arm_for(project, *, table_name: str | None = None) -> bool:
    """Whether to inject the map for the next ticket of `project`.

    Returns True unchanged when the experiment is off, which is every project by default: this is
    an operator's instrument for a bounded window, not a mode a client is put into."""
    if not getattr(project, "knowledge_experiment", False):
        return True
    arms = recent_arms(getattr(project, "name", ""), table_name=table_name)
    give = choose_arm(arms)
    log.info("knowledge experiment: %s → arm=%s (from %d recorded)",
             getattr(project, "name", "?"), INJECTED if give else OFF, len(arms))
    return give


#: How the worker's choice reaches the box. An explicit env var rather than an inferred default,
#: because "unset" and "off" must not look alike: unset means nobody is running an experiment.
ARM_ENV = "OPENFACTORY_KNOWLEDGE_ARM"


def arm_env(give_map: bool) -> dict[str, str]:
    """What to put in the job's environment so the box runs the arm the worker chose."""
    return {ARM_ENV: INJECTED if give_map else OFF}


def arm_from_env(env: dict | None = None) -> bool | None:
    """The arm the worker assigned, or None when no experiment is running.

    None is a distinct answer, not a falsy one: it means "nobody chose", and the caller then does
    what the project's own configuration says."""
    import os

    raw = (env if env is not None else os.environ).get(ARM_ENV, "")
    value = str(raw).strip().lower()
    if value == INJECTED:
        return True
    if value == OFF:
        return False
    return None
