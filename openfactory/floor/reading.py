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

import asyncio
import copy
import logging
import os
from dataclasses import dataclass
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
        got.budget = await _budget_cached(now=got.now)
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


@dataclass
class _Flight:
    """The ONE read of its kind this process has in flight, and the loop it belongs to.

    THE LOOP IS PART OF IT, for the reason `view.connect()` keys its pool by the running loop: a
    task belongs to the loop that made it. This module is reached from more than one loop in a
    process's life — `techlead/conversation.py` opens an `asyncio.run` per question and so does the
    CLI's `poller status` — and awaiting a task from another loop raises `RuntimeError: … attached
    to a different loop`, while one whose loop has stopped never resolves at all. So a reader joins
    a flight only while the RUNNING loop is the one that made it, by identity and nothing else."""

    loop: asyncio.AbstractEventLoop
    task: asyncio.Task | None = None


class _OneAtATime:
    """Readers arriving together share ONE read; each is handed the answer separately.

    THE MECHANISM IS #166's AND #165's, AND IT IS HERE SO THERE IS ONE OF IT. It was built for the
    schedule read and the budget read needed exactly the same thing (a subprocess per concurrent
    reader — ten floor reads at the window's expiry spawned ten `gh` processes, measured
    2026-09-19). A second copy beside the first is two mechanisms to keep true; this is one, with
    two instances. Each argument below is `intake_cached`'s, and it holds for any read at all.

    A TASK, NOT A LOCK:

      - A LOCK IS SINGLE FLIGHT ON SUCCESS ONLY. Behind one, a reader queued on a failing read
        takes the lock, finds nothing stored — neither memo stores a failure — and reads again:
        six callers behind a 0.5 s refusal fail at 0.5 / 1.0 / … / 3.0 s, an outage turned into a
        queue. Waiting on the one task hands every waiter THAT read's failure at the instant it
        fails, and it is shared, not stored: the slot empties when the task ends, so a reader
        arriving afterwards tries again, which is what lets a recovered vendor be picked up.
      - IT BELONGS TO NO CALLER. Were the read run inside the first reader's coroutine, that
        reader's cancellation — a browser that went away — would cancel the read under everybody
        queued behind it. Every reader waits through `asyncio.shield`, so one going away takes
        only itself; the read lands, and fills the window, whoever is left to see it.

    ONE SLOT, NOT A TABLE — at most one read in flight is ever registered, so there is nothing here
    for traffic to grow. A reader on another loop does not join it and does not queue behind it: it
    reads for itself and takes the slot, and the displaced read still lands for its own waiters.
    """

    def __init__(self) -> None:
        self.flight: _Flight | None = None

    async def shared(self, read):
        """Join the read in flight, or start it. `read(flight)` is the coroutine function that
        does the work; it is handed its own flight so it can ask `holds` before storing."""
        loop = asyncio.get_running_loop()
        flight = self.flight
        if flight is None or flight.loop is not loop:
            flight = self.flight = _Flight(loop=loop)
            flight.task = loop.create_task(read(flight))
            # THE SLOT IS GIVEN UP BY THE TASK'S ENDING, NOT BY ITS BODY. A `finally` inside the
            # read does not run for a task cancelled before its first step — the coroutine is
            # never entered — and that would leave a finished task in the slot, handing its
            # `CancelledError` to every later reader on this loop until something forgot it. A
            # done callback runs however the task ended. Added HERE, before any waiter's `shield`
            # adds its own, because callbacks run in the order they were added: the slot is empty
            # by the time the first waiter resumes.
            flight.task.add_done_callback(lambda _task, landed=flight: self._give_up(landed))
        return await asyncio.shield(flight.task)

    def _give_up(self, flight: _Flight) -> None:
        """…unless the slot already names somebody else's read, which is not this one's to empty."""
        if self.flight is flight:
            self.flight = None

    def holds(self, flight: _Flight) -> bool:
        """Whether this read is still the registered one — `forget` and a reader on another loop
        both take the slot from under a read in flight, and a read that lost it stores nothing."""
        return self.flight is flight

    def forget(self) -> None:
        self.flight = None


_intake_read = _OneAtATime()


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

    WHAT A CALLER IS HANDED IS ITS OWN (GitHub issue #165). This returned the dict it had stored.
    Before the memo each caller got a freshly built answer, so a write to it reached nobody; once
    the read was process-wide, `first["on"] = "MUTATED BY A CALLER"` was what the next reader got
    for the rest of the window, on every surface. Nothing in the tree writes to it (checked
    2026-09-18: `ladder.py` and `cli.py` only read, `api/app.py` serialises) — the property changed
    under the readers, and the next one to annotate an answer before rendering it could not have
    known. A DEEP copy, because `watchers` is a dict of dicts and a shallow one still shares every
    watcher row; and a copy rather than a read-only view, because two of the three readers hand it
    to `json.dumps`, which refuses a `MappingProxyType`. Measured on the five-projects-with-products
    shape (11 rows of 11 scalars): 0.05 ms a copy, against a read it saves of 11 round trips.

    READERS THAT ARRIVE WHILE A READ IS IN FLIGHT SHARE IT (GitHub issue #166). The memo only
    answers once an answer EXISTS; between the first reader starting a read and that read landing,
    every other reader found the same empty or expired window and started its own. Measured on
    `122e30b` with a 50 ms read: six concurrent readers, **6** reads; six sequential, 1. That
    instant is the expiry of the window with several browsers attached — `1 + N + P` describes,
    times the browsers. Now the first reader starts the read as a task of its own and everybody,
    the first included, waits on that one task: six concurrent readers, **1** read.

    THE SHARING ITSELF LIVES IN `_OneAtATime`, which says why it is a task and not a lock — and
    which the budget memo below now shares, rather than carrying a second copy of it.

    The flight's clock is the clock of the reader that started it, and its `client` likewise: the
    read side has one pooled client per process (`view.connect()`), so there is no second engine
    for a joiner to have meant.
    """
    stamp = (now or datetime.now(UTC)).timestamp()
    if _intake_memo and stamp - _intake_memo[0] < INTAKE_TTL_S:
        return copy.deepcopy(_intake_memo[1])
    return copy.deepcopy(
        await _intake_read.shared(lambda flight: _read_intake(flight, client, stamp)))


async def _read_intake(flight: _Flight, client, stamp: float) -> dict:
    """The read itself, as the task every waiter shares. It fills the window only while the slot
    is still ITS OWN: `forget_intake` and a reader on another loop both take the slot from under a
    read in flight, and a read that lost it still answers its waiters and stores nothing."""
    global _intake_memo
    from openfactory.runtime.temporal import view as tv

    got = await tv.intake(client)
    if got.get("known") is not False and _intake_read.holds(flight):
        _intake_memo = (stamp, got)
    return got


def forget_intake() -> None:
    """Drop the memoized schedule read, so the next caller pays a fresh one.

    THE PROCESS-WIDE HALF OF "NEVER CARRY AN INTAKE READ FROM BEFORE THE BLIP" (#139). The SSE
    stream has always cleared its own copy on an engine failure — keeping it would let the page
    show the poller's state from BEFORE the failure. Once the read became process-wide (#146,
    second pass) clearing the local copy stopped being enough: it only forced a re-read, and this
    memo could answer that re-read with the very value the blip was supposed to discard. The
    invariant is the stream's and it is older than the memo, so the memo yields to it.

    IT COSTS ONE FRESH `1 + N + P` READ AFTER A BLIP, on the exceptional path — which is the same
    trade the whole of #146 argues for, made in the direction that keeps a claim true. During an
    actual outage there is nothing to drop anyway: `intake_cached` never stores a read that failed.

    ONLY THE STREAM CALLS IT, and deliberately. `/api/floor` and `/api/temporal/jobs` are
    request-scoped — they raise into their own `except`, answer one degraded payload and re-read on
    the next request — and neither can consult this memo until the engine has just answered
    something else: `gather` gates intake behind `got.connected`, and the jobs route builds
    `"jobs": await tv.list_jobs(...)` before `"intake"` in the same dict. The stream is the one
    caller holding a loop across a blip, and the one with this invariant written into it.

    AND A READ STILL IN FLIGHT IS DETACHED, NOT WAITED FOR (#166). It STARTED before the blip, so
    letting it land in the window would serve a pre-blip answer as fresh for ten seconds — the
    invariant above, through the door single flight opened. Its waiters keep it: they asked before
    the blip too, and each is a request that re-reads on its own clock. It is not cancelled
    either — this function is synchronous and may be called from a loop the read does not belong
    to; giving up the slot is all that is needed, because `_read_intake` stores nothing once the
    slot is no longer its own.
    """
    global _intake_memo

    _intake_memo = None
    _intake_read.forget()


#: THE OTHER BOUNDED MEMO, and the one whose rule the intake memo above inherits: on a vendor
#: that reports a budget the read spawns a CLI and makes an HTTPS round trip, so a floor polled
#: every couple of seconds would fork a subprocess every couple of seconds. Sixty seconds is far
#: inside the poller's own three-minute tick, so nothing observable lags — a budget that fell
#: below the floor is reported within one poll of the poller acting on it.
_BUDGET_TTL_S = 60.0
_budget_memo: tuple[float, dict] | None = None

_budget_read = _OneAtATime()


#: HOW LONG A FLOOR READ WAITS FOR THE BUDGET before reporting it unread.
#:
#: MEASURED, 2026-09-19, against the real registry: a healthy `gh api rate_limit` is 0.49 s
#: (median of 3, max 0.63 s), so five seconds is ten times what the read costs when the vendor is
#: well — the same headroom `OPENFACTORY_ENGINE_DEADLINE` keeps over the panel's largest engine
#: read. It is the wait a PERSON is behind, not the subprocess's own limit: `gh` is given 60 s by
#: `github_project._run_gh`, and up to a second 60 s on its `@me` retry.
#:
#: A NUMBER A DEPLOYMENT CAN CHANGE, because "slow" is a property of somebody's network and their
#: forge. Read per call, so an operator changes it without a rebuild.
def budget_deadline() -> float:
    try:
        wanted = float(os.environ.get("OPENFACTORY_BUDGET_DEADLINE", "") or 5.0)
    except ValueError:
        log.warning("OPENFACTORY_BUDGET_DEADLINE is not a number (%r) — using 5s",
                    os.environ.get("OPENFACTORY_BUDGET_DEADLINE"))
        return 5.0
    return wanted if wanted > 0 else 5.0


async def _budget_cached(*, now: datetime | None = None) -> dict:
    """The API budget, at most once per `_BUDGET_TTL_S` — read OFF this loop, once for everybody
    waiting, and bounded.

    IT RAN ON THE LOOP'S OWN THREAD, WHICH IS THE PANEL'S ONLY ONE (#185 named it; older than the
    memo). `_budget()` spawns `gh api rate_limit` on the one vendor that reports a budget, and
    `gather` is awaited by `/api/floor` and by the engine stream's frames. Measured 2026-09-19
    with a 10 ms heartbeat ticking on the same loop — its longest gap is what every other request,
    both SSE streams and the socket really waited:

        a real `gh`, one floor read          0.49 s  →  the loop served nothing else for 0.50 s
        a `gh` that hangs 5 s and fails      5.02 s  →                                   5.02 s
        the same, the NEXT floor read        5.01 s  →                                   5.02 s
        ten floor reads arriving together   50.20 s  →  50.21 s, and TEN `gh` processes

    The second row is the bad case and the third is why: an unread budget is never cached (below),
    deliberately — so a `gh` that fails slowly turns the memo off and every floor read pays the
    full stall. The fourth is the window's expiry with several browsers attached.

    THREE THINGS, AND EACH IS LOAD-BEARING:

      - `asyncio.to_thread` — the read leaves the loop, which keeps answering.
      - ONE READ FOR EVERYBODY WAITING (`_OneAtATime`, the mechanism #166 built for the schedule
        read one tier up, now shared rather than copied): ten readers at the expiry cost one
        subprocess.
      - A BOUND, so a `gh` that hangs degrades to the `{"state": "unread"}` the ladder already
        understands rather than holding the floor for the subprocess's own 60 s — or 120, since
        `_run_gh` may retry once as `@me`.

    THE BOUND IS ON THE WAIT, NOT ON `gh`. Cancelling an `asyncio.to_thread` does not kill a
    subprocess: the thread runs on until `gh` returns or its own 60 s timeout ends it, and its
    answer is then discarded. So a hung forge costs one worker thread for up to a minute, and the
    panel answers in five seconds. Spelled out because the alternative — killing the process
    group — is a different and much larger change, and because a reader of this code would
    otherwise believe the subprocess stops when the wait does.
    """
    global _budget_memo

    stamp = (now or datetime.now(UTC)).timestamp()
    if _budget_memo and stamp - _budget_memo[0] < _BUDGET_TTL_S:
        # A COPY, as `intake_cached` hands out and for its reason (#165): this returned the stored
        # dict too, so a caller's write was every floor's budget for the next minute.
        return copy.deepcopy(_budget_memo[1])
    try:
        # THE READ SURVIVES THIS DEADLINE, and the shield that makes it survive is the one every
        # waiter already goes through inside `shared`: what `wait_for` cancels here is this
        # caller's wait, never the task. So a read that ran out of time still lands, still fills
        # the window, and the next floor read is served from it rather than spawning a second
        # subprocess while the first is still running. A second `asyncio.shield` around this call
        # was written first and was dead — the mutation that removed it survived, which in this
        # repository means the code was not doing anything.
        got = await asyncio.wait_for(
            _budget_read.shared(lambda flight: _read_budget(flight, stamp)), budget_deadline())
    except TimeoutError:
        log.warning("floor: the API budget was not read within %.1fs "
                    "(OPENFACTORY_BUDGET_DEADLINE) — reporting it unread. The read itself is "
                    "still running and will fill the window if it lands.", budget_deadline())
        return {"state": "unread"}
    return copy.deepcopy(got)


async def _read_budget(flight: _Flight, stamp: float) -> dict:
    """The blocking read, on a thread of its own, as the task every waiter shares."""
    global _budget_memo

    got = await asyncio.to_thread(_budget)
    # An UNREAD budget is never cached: it is a failure, and holding it would keep a transient
    # `gh` hiccup on screen for a minute after the thing recovered. And only while the slot is
    # still this read's own, exactly as the schedule read stores.
    if got.get("state") != "unread" and _budget_read.holds(flight):
        # NOT COPIED ON THE WAY IN, because it is copied on the way OUT — both of
        # `_budget_cached`'s return paths deepcopy, so what a reader holds is never this
        # object. A second copy here pinned nothing: cutting it changed no behaviour any
        # guard could see, which is what a mutation row measured on 2026-09-20.
        _budget_memo = (stamp, got)
    return got


def forget_budget() -> None:
    """Drop the memoized budget, so the next floor read pays a fresh one. A seam for the suite,
    and the twin of `forget_intake` — which is public for a caller that has an invariant about a
    blip. Nothing in the tree needs that for the budget yet."""
    global _budget_memo

    _budget_memo = None
    _budget_read.forget()


async def _engine(client):
    """`(client, connected, address, error)` — never raises.

    `connected` is tri-state on purpose. `False` is a fact ("it did not answer"); `None` would mean
    nobody asked, and the ladder must be able to tell those apart before it says anything about a
    factory it may simply not have looked at.

    THE IMPORT IS INSIDE THE `try`, AND FOR A WHILE IT WAS NOT (#178). `view` imports `temporalio`
    at its top, so on an install without the `runtime` extra the line that fetches it raises — and
    it sat ABOVE the `try`, under an `except` commented "a deployment with no runtime extra still
    answers". Measured on `main` at `1512d0a` with the library made unimportable: `/api/floor`
    answered 500, which the page reads as its own failure rather than as a fact about the engine.

    AN ABSENT LIBRARY IS ITS OWN SENTENCE, not "the engine did not answer". Both arrive as
    `connected: False` with no address, which the ladder already reads as "no durable engine
    installed" — a fact, `stopped`, not an error about the page. What differs is the remedy, so
    the error carried for the detail line is `host.CLIENT_MISSING` (an install) rather than a
    connect failure (a process to start) or `temporal_config`'s refusal (a variable to set).
    """
    try:
        from openfactory.runtime.temporal import view as tv
    except ImportError as exc:
        # The install sentence only when the library is what is missing; any OTHER import that
        # broke inside `view` is still never a 500, and is reported as itself.
        from openfactory.runtime.host import why_the_engine_cannot_be_read

        return None, False, "", why_the_engine_cannot_be_read(exc)

    try:
        address, _ = tv.temporal_config()
    except Exception as exc:  # noqa: BLE001 — a deployment that declared no engine still answers
        return None, False, "", str(exc)[:200]
    if client is not None:
        return client, True, address, ""
    try:
        return await tv.connect(), True, address, ""
    except Exception as exc:  # noqa: BLE001 — the floor degrades, it never 500s
        log.warning("floor: the engine did not answer (%s)", str(exc)[:160])
        return None, False, address, str(exc)[:200]


async def _jobs(client) -> list[dict] | None:
    try:
        # Inside the `try`, like `_engine`'s (#178): `gather` only reaches this once the engine
        # answered, but "nothing on the gathering path raises" should not rest on its caller.
        from openfactory.runtime.temporal import view as tv

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
