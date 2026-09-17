"""Reading the facts the ladder judges — and letting a caller choose what it can afford.

The split is `techlead/watch.py`'s, deliberately: *"The activity gathers the state; this decides
what is worth saying."* Everything expensive lives here so `state.py` stays pure and a test can
state a world instead of standing one up.

THREE CADENCES, BECAUSE THE READS COST WILDLY DIFFERENT AMOUNTS — measured, not guessed:

    fast   ~2-4 Temporal RPCs   the job list. Safe every couple of seconds.
    slow   1+N+P schedule reads the poller's cadence, the build stamps, the registry, the boxes.
                                `intake` describes the poller, one schedule per enabled project,
                                and one more for each project declaring a `product` — 2 reads for
                                one project, 11 for five with products (measured 2026-09-16), one
                                round trip after another. Doing that on the fast tick turns a
                                status line into load, so the schedule half rides `INTAKE_TTL_S`.
    costly a subprocess + TLS   the API budget is asked of each tracker through the port; on the
                                one vendor that reports one it spawns a CLI and makes an HTTPS
                                round trip: 100-500 ms. It belongs on a minute-scale clock, or is
                                better inherited from the poller, which already reads it every tick.

WHAT YOU DO NOT PAY FOR IS REPORTED AS UNREAD, NEVER AS FINE. Every field of `FloorInputs` is
optional and defaults to `None`, which rung 8 renders as "it could not read X". That is what makes
a cheap call honest: a caller may skip the whole slow tier and the answer degrades to Unknown
rather than quietly becoming a promise nobody checked.

NOTHING ON THE GATHERING PATH RAISES. A floor that cannot be described is a floor described as
undescribable — the one thing this module may never do is take a surface down while trying to tell
it something.

THE ONE DELIBERATE EXCEPTION IS `intake_cached`, and it is public for that reason. It is the shared
rate limit on the schedule read, and its OTHER callers (`/api/temporal/jobs` and the SSE stream in
`api/app.py`) each have their own `except` branch that answers `connected: False` — a frame that
says the engine did not answer. Handing those a `None` instead would put `"intake": None` on a
`connected: True` frame and step over the branch they already have. So the memo raises, and
`_intake` — the floor's own caller — is the wrapper that catches and degrades to unread.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from openfactory.floor.ladder import FloorInputs

log = logging.getLogger("openfactory.floor")

#: What a caller asks for. Names match `FloorInputs` fields, so a reader can see exactly what a
#: given cadence pays for — and a typo is a field that stays `None` and reads as unread, which is
#: honest but silent, so `gather` refuses an unknown name outright.
FAST: tuple[str, ...] = ("jobs",)
SLOW: tuple[str, ...] = ("intake", "build", "projects")
COSTLY: tuple[str, ...] = ("budget",)
EVERYTHING: tuple[str, ...] = FAST + SLOW + COSTLY

_KNOWN = frozenset(EVERYTHING)


async def gather(client=None, *, want: tuple[str, ...] = FAST + SLOW,
                 budget: dict | None = None, now: datetime | None = None) -> FloorInputs:
    """Read what `want` names; leave the rest unread.

    `client` is an already-connected Temporal client when the caller has one. Reuse matters: the
    tech-lead's own gatherer holds a single client across two reads *"rather than in a second
    `asyncio.run` that would re-resolve the engine's address and re-authenticate once per
    question"*.

    `budget` lets a caller HAND IN a budget summary it already has — the poller reads it on every
    tick — instead of paying for a second subprocess. Passing it is not the same as asking for it:
    `want` still decides whether an absent one is read or left unread.
    """
    unknown = sorted(set(want) - _KNOWN)
    if unknown:
        # Refused rather than ignored: an unrecognised name would silently leave its field `None`,
        # which the ladder reports as "could not read" — a typo would read as a degraded factory.
        raise ValueError(f"gather() cannot read {unknown} — known fields are {sorted(_KNOWN)}")

    got = FloorInputs(now=now or datetime.now(UTC), budget=budget)
    needs_engine = bool({"jobs", "intake"} & set(want))

    if needs_engine:
        client, got.connected, got.engine_address, got.engine_error = await _engine(client)

    if "jobs" in want and got.connected:
        got.jobs = await _jobs(client)
    if "intake" in want and got.connected:
        got.intake = await _intake(client, now=got.now)
    if "projects" in want:
        got.projects = _projects()
    if "build" in want:
        got.build = _build()
    if "budget" in want and got.budget is None:
        got.budget = _budget_cached(now=got.now)
    return got


#: HOW OFTEN THE SCHEDULE READ IS ACTUALLY PAID FOR, and it is the SAME number the SSE stream
#: rides (`api/app.py::_STREAM_SLOW_S` takes its value from here). One window, one constant: the
#: panel's own comment claimed for years that "the route's slow reads are cached server-side
#: (`_STREAM_SLOW_S`)" while `/api/floor` had no cache at all, and two numbers deciding one
#: behaviour is how that claim came to be false without anybody editing it (GitHub issue #146).
#:
#: ONE WINDOW AND ONE MEMO, since 2026-09-17. The first pass shared the number and left two of the
#: three readers calling `tv.intake` themselves, so the comment above was still describing more
#: than the code did. All three now come through `intake_cached`: driving `/api/floor`,
#: `/api/temporal/jobs` and one stream frame inside one window counted **3** reads at `tv.intake`
#: before and **1** after.
#:
#: MEASURED, NOT GUESSED (2026-09-16, driving `tv.intake` with a client that counts
#: `get_schedule_handle(...).describe()`): one `intake` costs **1 + N + P** describes — one for the
#: poller, one per enabled project's watch schedule, one more per project declaring a `product`.
#: 1 project → 2, 3 → 4, 3 with products → 7, 5 with products → 11. They are SEQUENTIAL
#: (`{sid: await _one(sid) for sid in ...}`), so that is that many round trips one after another.
#: The panel asks for this on every engine frame, and the stream ticks every 2 seconds.
#:
#: Ten seconds is far inside the poller's own three-minute tick, so nothing observable lags — the
#: same reason the stream already gives for the same read, and the bound
#: `tests/test_a_frame_does_not_erase_what_it_omits.py` holds it to (5..30 s).
INTAKE_TTL_S = 10.0
_intake_memo: tuple[float, dict] | None = None


async def intake_cached(client, *, now: datetime | None = None) -> dict:
    """`tv.intake(client)`, at most once per `INTAKE_TTL_S` — a rate limit on a network read, not
    a derived value (ADR-0023 is about the second kind, and does not reach this).

    EVERY READER OF `tv.intake` COMES THROUGH HERE, which is the half the first cut of #146 left
    undone. There are three (measured 2026-09-17 by counting calls at `tv.intake` while driving all
    three inside one window: **3** before, **1** after): `/api/floor` through `gather`,
    `/api/temporal/jobs`, and the SSE stream. Only the first was throttled, while the panel's
    comment said the schedule read was memoized process-wide — so a five-project deployment with
    products still paid 11 sequential describes every 20 s per browser on `loadEngine`, plus one
    more 600-800 ms after most manual actions. What the route and the stream shared was the
    NUMBER, not the memo.

    IT RAISES, AND THAT IS WHY IT IS THE PUBLIC ONE. `/api/temporal/jobs` and the stream each wrap
    their engine reads in an `except` that answers `connected: False`; a helper that swallowed the
    failure would hand them `"intake": None` on a `connected: True` frame and quietly step over the
    branch they already have. The floor wants the opposite — unread, never an exception — so
    `_intake` below catches for it. Inverting the two is what lets one memo serve both semantics.

    THE CLOCK IS THE CALLER'S, exactly as `_budget_cached(now=got.now)` already is, so a test
    states a time instead of sleeping. The panel routes have no clock to pass and take the wall
    clock, which is what they read today.

    STRICTER THAN THE STREAM, DELIBERATELY. The stream caches whatever `tv.intake` handed it; this
    caches only an answer that was actually READ — a read that raised stores nothing, and `intake`
    answers `known: False` itself when the schedule could not be described. Holding either would
    keep a transient engine blip on screen for the whole window after the thing recovered, which is
    `_budget_cached`'s rule one tier up. The stream can afford the weaker rule because it drops its
    cache on a blip (`slow, slow_at = {}, 0.0`); a process-wide memo has no blip to hang that on,
    so it declines to store the failure in the first place. The cost of the strictness is that an
    engine that is down is re-asked on every request — which is the read nobody is being charged
    for anyway, since it is failing.
    """
    global _intake_memo
    from openfactory.runtime.temporal import view as tv

    stamp = (now or datetime.now(UTC)).timestamp()
    if _intake_memo and stamp - _intake_memo[0] < INTAKE_TTL_S:
        return _intake_memo[1]
    got = await tv.intake(client)
    if got.get("known") is not False:
        _intake_memo = (stamp, got)
    return got


#: THE OTHER BOUNDED MEMO, and the one whose rule the intake memo above inherits: on a vendor
#: that reports a budget the read spawns a CLI and makes an HTTPS round trip, so a floor polled
#: every couple of seconds would fork a subprocess every couple of seconds. Sixty seconds is far
#: inside the poller's own three-minute tick, so nothing observable lags — a budget that fell
#: below the floor is reported within one poll of the poller acting on it.
_BUDGET_TTL_S = 60.0
_budget_memo: tuple[float, dict] | None = None


def _budget_cached(*, now: datetime | None = None) -> dict:
    global _budget_memo

    stamp = (now or datetime.now(UTC)).timestamp()
    if _budget_memo and stamp - _budget_memo[0] < _BUDGET_TTL_S:
        return _budget_memo[1]
    got = _budget()
    # An UNREAD budget is never cached: it is a failure, and holding it would keep a transient
    # `gh` hiccup on screen for a minute after the thing recovered.
    if got.get("state") != "unread":
        _budget_memo = (stamp, got)
    return got


async def _engine(client):
    """`(client, connected, address, error)` — never raises.

    `connected` is tri-state on purpose. `False` is a fact ("it did not answer"); `None` would mean
    nobody asked, and the ladder must be able to tell those apart before it says anything about a
    factory it may simply not have looked at.
    """
    from openfactory.runtime.temporal import view as tv

    try:
        address, _ = tv.temporal_config()
    except Exception as exc:  # noqa: BLE001 — a deployment with no runtime extra still answers
        return None, False, "", str(exc)[:200]
    if client is not None:
        return client, True, address, ""
    try:
        return await tv.connect(), True, address, ""
    except Exception as exc:  # noqa: BLE001 — the floor degrades, it never 500s
        log.warning("floor: the engine did not answer (%s)", str(exc)[:160])
        return None, False, address, str(exc)[:200]


async def _jobs(client) -> list[dict] | None:
    from openfactory.runtime.temporal import view as tv

    try:
        _, namespace = tv.temporal_config()
        return await tv.list_jobs(client, namespace)
    except Exception as exc:  # noqa: BLE001
        log.warning("floor: could not list the jobs (%s)", str(exc)[:160])
        return None


async def _intake(client, *, now: datetime | None = None) -> dict | None:
    """The FLOOR's reader: `intake_cached`, degraded to unread rather than raised.

    This is the catching half of the pair, and it is this way round on purpose. The memo used to
    wrap this function, so a panel route that called the memo directly would have got `None` from
    a failed read — `"intake": None` on a `connected: True` frame — instead of reaching its own
    `except`. Inverting them keeps both behaviours off one memo: raising for the panel routes,
    unread for the floor, which is the whole of this module's contract.
    """
    try:
        return await intake_cached(client, now=now)
    except Exception as exc:  # noqa: BLE001 — `intake` already answers `known: False` itself, so
        # reaching here means something below it broke; unread is the honest report either way.
        log.warning("floor: could not read the poller schedule (%s)", str(exc)[:160])
        return None


def _projects() -> list[dict] | None:
    """Name, pickup switch and box verdict per project — the three the ladder judges.

    `enabled` is deliberately `None` rather than `True` when the registry could not be read for a
    project: an unknown pickup is not an armed one, and rung 8 says so.
    """
    from openfactory.box_prove import health
    from openfactory.registry import ProjectRegistry

    try:
        found = ProjectRegistry().list()
    except Exception as exc:  # noqa: BLE001 — an unreadable registry is `None`, not `[]`. `[]`
        # would tell the floor there are no projects, which is a claim.
        log.warning("floor: could not read the project list (%s)", str(exc)[:160])
        return None
    rows = []
    for p in found:
        rows.append({"name": p.name,
                     "enabled": bool(p.enabled) if getattr(p, "enabled", None) is not None
                                else None,
                     "box": health(p)})
    return rows


def _build() -> dict | None:
    from openfactory.namespace import build_agreement

    try:
        return build_agreement()
    except Exception as exc:  # noqa: BLE001
        log.warning("floor: could not read the build stamps (%s)", str(exc)[:160])
        return None


#: How the per-vendor answers collapse into ONE word for the floor. `low` first because it is
#: the only state that changes what the poller does; `unread` before `ok` because a safety net
#: that is missing on one vendor is worth more of a sentence than a healthy one elsewhere;
#: `not_reported` last because a vendor with nothing to say says nothing about the others.
_STATE_RANK = {"low": 0, "unread": 1, "ok": 2, "not_reported": 3}


def budgets(projects=None) -> list[dict]:
    """One row per (tracker kind, credential) among the ENABLED projects — asked of the PORT.

    THE READ THAT USED TO NAME A VENDOR. Four core sites imported `github_project.github_rate` and
    ran it whatever the deployment tracked on, so a Jira-only deployment spawned `gh` on every
    floor read and every poll tick and logged a GitHub remedy. Every row here comes from
    `build_tracker(project).budget()`: a vendor that reports one answers with a `Budget`, a vendor
    that has none declares `NOT_REPORTED`, and a probe that failed raises — three states, each
    rendered as itself.

    ONCE PER CREDENTIAL, NOT ONCE PER PROJECT. The budget is the credential's, not the project's,
    and one deployment hosts N projects on the same App installation; asking N times would spend
    N subprocesses to learn one number. `projects` lists WHICH projects share each row, so the
    poller can skip exactly the ones on an exhausted vendor and keep scanning the rest.

    THE ROW IS KEYED BY THE CREDENTIAL'S IDENTITY, NEVER BY ITS VALUE. The first version keyed
    on the token itself, and the App mint returns a fresh token on every call — so on the one
    deployment shape the App exists for (N projects, no static token) the "once" held only in
    the guard, which shared a static variable: three projects cost three mints and three probes
    (measured 2026-08-26). `tracker_credential_source` names the variable or the deployment
    row the credential comes from, and the value is resolved once per NEW key, below the
    dedup — so the mint is paid once per credential too.

    `projects=None` reads the registry; an unreadable registry is an empty list, and the summary
    of an empty list is `not_reported` — there is nobody to report for.
    """
    from openfactory.adapters.tracker.base import NOT_REPORTED, BudgetUnreadable
    from openfactory.adapters.tracker.registry import build_tracker, tracker_kind
    from openfactory.credentials import (
        deployment_tracker_token,
        tracker_credential_source,
        tracker_token_for,
    )

    if projects is None:
        from openfactory.registry import ProjectRegistry

        try:
            projects = [p for p in ProjectRegistry().list() if getattr(p, "enabled", True)]
        except Exception as exc:  # noqa: BLE001 — the floor degrades, it never raises
            log.warning("floor: could not read the project list for the budget (%s)",
                        str(exc)[:160])
            projects = []

    rows: dict[tuple[str, str], dict] = {}
    for project in projects:
        kind = tracker_kind(project)
        name = str(getattr(project, "name", "") or "")
        key = (kind, tracker_credential_source(project))
        if key in rows:
            rows[key]["projects"].append(name)
            continue
        row: dict = {"kind": kind, "projects": [name]}
        try:
            token = tracker_token_for(project) or deployment_tracker_token(project)
        except Exception as exc:  # noqa: BLE001 — a mint that failed is an unread budget
            log.warning("floor: could not resolve %s's tracker credential (%s)", name,
                        str(exc)[:160])
            token = None
        try:
            answer = build_tracker(project, token=token).budget()
        except BudgetUnreadable as exc:
            row.update(state="unread", error=str(exc)[:200])
            log.warning("floor: %s's %s budget could not be read (%s) — the poller scans "
                        "without that safety net", name, kind, str(exc)[:160])
        except Exception as exc:  # noqa: BLE001 — an unknown tracker kind, a builder that raised
            row.update(state="unread", error=str(exc)[:200])
            log.warning("floor: could not ask %s's tracker (%s) for its budget (%s)", name, kind,
                        str(exc)[:160])
        else:
            if answer == NOT_REPORTED:
                row.update(state="not_reported")
            else:
                row.update(
                    state="low" if answer.low else "ok", vendor=answer.vendor or kind,
                    resource=answer.resource or "API", remaining=answer.remaining,
                    limit=answer.limit, reset_epoch=answer.reset_epoch, floor=answer.floor,
                    reset_at=(datetime.fromtimestamp(answer.reset_epoch, UTC).strftime("%H:%M")
                              if answer.reset_epoch else ""))
        rows[key] = row
    return list(rows.values())


def budget_summary(rows: list[dict]) -> dict:
    """The ONE row a single-sentence surface renders — the worst of the vendors' answers.

    `state` is one of `low | unread | ok | not_reported`, and the three that are not `low` all
    mean "nothing is pausing pickups" — with different sentences. The poller FAILS OPEN on
    `unread` (it scans anyway), so an unreadable probe must never be rendered as "pickups are
    paused"; `not_reported` is a vendor that has no budget, which is a fact and not a failure."""
    if not rows:
        return {"state": "not_reported"}
    worst = min(rows, key=lambda r: _STATE_RANK.get(str(r.get("state")), 99))
    return {k: v for k, v in worst.items() if k != "projects"}


def _budget() -> dict:
    """`budget_summary(budgets())` — three-valued plus one, and the fourth matters.

    `unread` is NOT `low`. The poller FAILS OPEN on a budget it cannot read: it scans anyway. So
    an unreadable probe must never be rendered as "pickups are paused", or the floor would report
    a stop that is not happening. And `not_reported` is not `unread`: a Jira deployment has no
    budget to read, and saying "could not read" about it sends somebody to fix a probe that has
    nothing to probe.
    """
    try:
        return budget_summary(budgets())
    except Exception as exc:  # noqa: BLE001 — nothing in this module raises
        log.warning("floor: could not read the API budget (%s)", str(exc)[:160])
        return {"state": "unread"}
