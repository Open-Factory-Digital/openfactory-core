"""The floor's schedule read is paid on a clock, not on every frame (GitHub issue #146).

WHAT THIS FILE HOLDS, and why each case runs the thing rather than reading about it:

`/api/floor` used to run `floor.gather(want=floor.EVERYTHING)` with nothing memoizing the slow
tier, and the panel asked for it on EVERY engine frame — under a comment claiming the route's slow
reads were "cached server-side (`_STREAM_SLOW_S`)", which was the SSE stream's own per-connection
local. Measured on `bda024d`: two `/api/floor` requests cost two `tv.intake` reads, and one
`tv.intake` costs `1 + N + P` sequential schedule describes (one for the poller, one per enabled
project, one more per project declaring a `product`) — 2 for one project, 11 for five with
products.

THIS IS NOT A NEW DECISION. The repository already decided this exact read must be throttled, for
the SSE stream, and holds the window at 5..30 s in
`test_a_frame_does_not_erase_what_it_omits.py::test_the_slow_facts_are_CACHED_rather_than_read_
every_two_seconds`. The route simply never got the same treatment; §7 below holds the two to one
number so the panel's claim cannot drift apart from the code again.

AND IT IS A RATE LIMIT, NOT A DERIVED VALUE, which is why ADR-0023 ("the map is derived, not
learned") does not bite: that record is about a value whose staleness is a WRONG ANSWER. This is
how often a network read is paid for, with a stated window — and §5 proves the verdict itself is
still computed from whatever was read.

§8 IS THE SECOND PASS (2026-09-17, on review). The first one memoized `/api/floor` and left the
other two readers of `tv.intake` calling it directly — `/api/temporal/jobs`, which the panel's
`loadEngine` hits on a 20-second interval and again ~600-800 ms after most manual actions, and the
SSE stream, which kept its own per-connection copy. Driving all three inside one window counted
**3** reads at `tv.intake`; after routing them through `reading.intake_cached` it is **1**. The
same section holds the inversion that made one memo serve both failure semantics: the public
`intake_cached` wraps the RAW read and RAISES, so the panel routes reach their own `except` and
answer `connected: False`, while `_intake` catches for the floor and reports unread. Before the
inversion the memo wrapped the catching half, so a panel route calling it would have put
`"intake": null` on a `"connected": true` frame.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import yaml

from openfactory import floor
from openfactory.floor import reading

# ── the bench ───────────────────────────────────────────────────────────────────────────────────

def _registry(path, n: int = 1, *, product: bool = False) -> None:
    """`n` enabled projects, `product` on each or on none. Written as YAML rather than built in
    memory because `_watcher_schedule_ids` reads the registry itself — the count under test is a
    function of what is REGISTERED, and a double in front of that would measure nothing."""
    projects = {}
    for i in range(n):
        name = f"p{i}"
        entry: dict = {"name": name, "repo_path": f"/work/{name}", "enabled": True,
                       "tracker": {"kind": "github", "repo": f"acme/{name}",
                                   "options": {"board_number": "1"}}}
        if product:
            entry["product"] = {"docs_repo": "acme/docs"}
        projects[name] = entry
    path.write_text(yaml.safe_dump({"projects": projects}))


class _Counter:
    """A stand-in for `tv.intake` that counts how often it was actually called."""

    def __init__(self, answer: dict | None = None):
        self.calls = 0
        self.answer = answer if answer is not None else {
            "known": True, "on": True, "note": "", "watchers": {}}

    async def __call__(self, _client=None):
        self.calls += 1
        return self.answer


@pytest.fixture
def engine(monkeypatch, tmp_path):
    """One enabled project, a reachable fake engine, and a counted `tv.intake`.

    No live engine is reached and none may be (`conftest._no_live_durable_engine`): `connect` hands
    back a sentinel and every read below it is a double, so what these cases measure is call
    counts, never wall-clock latency.
    """
    from openfactory.runtime.temporal import view as tv

    reg = tmp_path / "registry.yaml"
    _registry(reg)
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKENS", raising=False)

    counter = _Counter()

    async def _connect(*_a, **_k):
        return object()

    async def _no_jobs(*_a, **_k):
        return []

    monkeypatch.setattr(tv, "connect", _connect)
    monkeypatch.setattr(tv, "intake", counter)
    monkeypatch.setattr(tv, "list_jobs", _no_jobs)
    monkeypatch.setattr(tv, "temporal_config", lambda: ("localhost:7233", "default"))
    return counter


def _client():
    from starlette.testclient import TestClient

    from openfactory.api import app as api

    return TestClient(api.app)


# ── 1-2. the route pays for the schedules once per window ───────────────────────────────────────

def test_two_floor_requests_inside_the_window_read_the_schedules_ONCE(engine):
    """The property from #146, at the surface that has it. On `bda024d` this is 2.

    BOTH ANSWERS ARE ASSERTED 200 so the case cannot pass on a route that 500s before it ever
    reaches the read — a call count of one is also what a broken route produces."""
    client = _client()
    first, second = client.get("/api/floor"), client.get("/api/floor")

    assert first.status_code == 200 and second.status_code == 200, (
        f"the floor route did not answer ({first.status_code}, {second.status_code}) — this case "
        f"measures a read count and would have 'passed' on a 500")
    assert engine.calls == 1, (
        f"two /api/floor requests cost {engine.calls} schedule reads, not 1 — each one is 1+N+P "
        f"sequential describes, and the panel asks on every engine frame (#146)")


@pytest.mark.asyncio
async def test_and_a_request_PAST_the_window_reads_them_again(engine):
    """A rate limit that never expires is a snapshot. Driven by STATING a time through
    `gather(now=...)` — the memo takes the caller's clock exactly as `_budget_cached` does — rather
    than by sleeping, which would put `INTAKE_TTL_S` seconds of wall clock in the suite."""
    t0 = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    sentinel = object()

    await floor.gather(sentinel, want=("intake",), now=t0)
    await floor.gather(sentinel, want=("intake",),
                       now=t0 + timedelta(seconds=reading.INTAKE_TTL_S / 2))
    assert engine.calls == 1, "the window is not holding the read at all"

    await floor.gather(sentinel, want=("intake",),
                       now=t0 + timedelta(seconds=reading.INTAKE_TTL_S + 1))
    assert engine.calls == 2, (
        f"a request {reading.INTAKE_TTL_S + 1}s later still got the cached read — a paused poller "
        f"would read as running for as long as the process lives")


# ── 3. an answer nobody read is never cached ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_read_that_FAILED_is_not_cached_and_a_recovered_engine_answers_at_once(
        monkeypatch, engine):
    """`_intake` degrades to `None` when the read below it broke. Caching that would keep a
    transient engine blip on screen for the whole window AFTER the thing recovered — the rule
    `_budget_cached` already carries one tier up, and the reason this memo is stricter than the
    stream's (which caches whatever it got, and drops the lot on a blip instead)."""
    from openfactory.runtime.temporal import view as tv

    async def _broken(_client=None):
        engine.calls += 1
        raise RuntimeError("the engine went away")

    monkeypatch.setattr(tv, "intake", _broken)
    t0 = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    sentinel = object()

    got = await floor.gather(sentinel, want=("intake",), now=t0)
    assert got.intake is None, "a failed schedule read must reach the ladder as unread"

    monkeypatch.setattr(tv, "intake", engine)          # the engine comes back, inside the window
    recovered = await floor.gather(sentinel, want=("intake",), now=t0 + timedelta(seconds=1))
    assert recovered.intake == engine.answer, (
        "a failed read was cached, so the floor reported a dead engine for the whole window after "
        "it recovered")


@pytest.mark.asyncio
async def test_an_answer_whose_known_is_FALSE_is_not_cached_either(monkeypatch, engine):
    """`intake` answers `known: False` ITSELF when a schedule cannot be described — it does not
    raise, so the `None` case above never fires for it. That is the shape a paused-then-resumed
    engine actually produces, and it must be re-asked rather than held."""
    from openfactory.runtime.temporal import view as tv

    unread = _Counter({"known": False, "on": None, "note": "", "watchers": {}})
    monkeypatch.setattr(tv, "intake", unread)
    t0 = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    sentinel = object()

    await floor.gather(sentinel, want=("intake",), now=t0)
    await floor.gather(sentinel, want=("intake",), now=t0 + timedelta(seconds=1))
    assert unread.calls == 2, (
        "an answer that says it could not read the schedule was cached as if it had — the floor "
        "then reports 'I could not check' for the window after the engine came back")


# ── 4. a cheap caller is not handed a slow-tier answer ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_caller_that_did_not_ASK_for_intake_is_not_served_the_memo(engine):
    """The whole point of `want` is that what you did not pay for reads as UNREAD rather than as
    fine (`gather`'s own docstring). A memo consulted outside the `want` check would quietly hand
    a fast-tier caller a slow-tier fact — and the ladder would then state it."""
    t0 = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    sentinel = object()

    await floor.gather(sentinel, want=("intake",), now=t0)
    assert engine.calls == 1

    cheap = await floor.gather(sentinel, want=("jobs",), now=t0 + timedelta(seconds=1))
    assert cheap.intake is None, (
        "a caller that asked only for the job list was handed the cached schedule read — it did "
        "not pay for that tier and the ladder must report it unread")
    assert floor.state(await floor.gather(sentinel, want=(), now=t0), "").word == "Unknown"


# ── 5. what is cached is the READ, not the verdict ──────────────────────────────────────────────

def test_the_VERDICT_is_still_computed_on_every_request(engine):
    """ADR-0023 is about a derived value going stale. Nothing derived is stored here: the two
    bodies are identical because the ladder ran twice over the same facts, not because an answer
    was kept. Asserted on the whole payload, not on one field."""
    client = _client()
    first, second = client.get("/api/floor"), client.get("/api/floor")
    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json(), "the memo changed what the floor SAYS, not just what it "\
        "costs to say it"
    assert first.json()["word"], "the route answered with no verdict at all"


# ── 6. the cost itself, counted ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("n", "product", "expected"),
                         [(1, False, 2), (3, False, 4), (3, True, 7), (5, True, 11)])
def test_one_intake_costs_ONE_DESCRIBE_PER_SCHEDULE_plus_the_poller(monkeypatch, tmp_path,
                                                                    n, product, expected):
    """`1 + N + P`, counted against a client that records every `describe()` — the number this
    change is justified by, and the reason the issue's own `1+N` is wrong: a project declaring a
    `product` carries a SECOND standing loop (`_watcher_schedule_ids`).

    Held here so the next refactor cannot quietly make it `1 + 3N`: the memo makes the read rarer,
    it does not make it cheaper, and a caching change is exactly the kind that hides a cost growing
    underneath it."""
    import asyncio

    from openfactory.runtime.temporal import view as tv

    seen: list[str] = []

    class _Desc:
        schedule = type("S", (), {"state": type("T", (), {"paused": False, "note": ""})(),
                                  "spec": None})()
        info = None

    class _Handle:
        def __init__(self, sid: str):
            self.sid = sid

        async def describe(self):
            seen.append(self.sid)
            return _Desc()

    class _Engine:
        def get_schedule_handle(self, sid: str):
            return _Handle(sid)

    reg = tmp_path / "registry.yaml"
    _registry(reg, n, product=product)
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))

    answer = asyncio.run(tv.intake(_Engine()))
    assert answer["known"] is True, "the counted read did not actually reach a schedule"
    assert len(seen) == expected, (
        f"{n} project(s){' with a product' if product else ''} cost {len(seen)} schedule describes, "
        f"not {expected} (1 poller + {n} watch + {n if product else 0} product) — {seen}")
    assert len(set(seen)) == len(seen), f"a schedule was described twice in one intake: {seen}"


# ── 7. the route and the stream ride ONE window ─────────────────────────────────────────────────

def test_the_route_and_the_stream_share_ONE_window():
    """Two numbers deciding one behaviour is how the panel's comment came to describe a cache the
    route did not have. Asserted on the VALUES the two modules export — never on source text,
    which is satisfied by the paragraph explaining the very thing it forbids (CONTRIBUTING).

    The stream's own bound (5..30 s, `test_a_frame_does_not_erase_what_it_omits.py`) still holds
    that guard non-vacuous: it reads `api._STREAM_SLOW_S`, which now comes from here."""
    from openfactory.api import app as api

    assert api._STREAM_SLOW_S == reading.INTAKE_TTL_S, (
        f"the stream throttles on {api._STREAM_SLOW_S}s and the route on {reading.INTAKE_TTL_S}s — "
        f"they describe the same schedules and the panel's comment names one number for both")
    assert 5 <= reading.INTAKE_TTL_S <= 30, (
        f"the shared window is {reading.INTAKE_TTL_S}s, outside the bound this tree already "
        f"accepted for this read")


# ── 8. every reader of the schedule read comes through the ONE memo ──────────────────────────────

async def _one_stream_frame():
    """Run `/api/temporal/stream`'s generator for exactly ONE frame and return it.

    DRIVEN THROUGH THE ROUTE FUNCTION, with a stated disconnect, rather than through
    `TestClient.stream`. The generator is an infinite `while not await request.is_disconnected()`
    loop with a 2-second sleep, and reading one frame through the test client then closing it hung
    past a 120 s timeout on this machine (measured 2026-09-17) — the client waits for a generator
    that is waiting for a disconnect the transport never delivers. Everything inside `gen()` is the
    real route: the connect, the window check, the intake read and the frame. Only the socket the
    loop asks about is stated.
    """
    from openfactory.api import app as api

    class _OneFrame:
        def __init__(self):
            self.asked = 0

        async def is_disconnected(self):
            self.asked += 1
            return self.asked > 1

    response = await api.temporal_stream(_OneFrame())
    async for chunk in response.body_iterator:
        return chunk
    raise AssertionError("the stream yielded nothing at all")


@pytest.mark.asyncio
async def test_NO_READER_of_the_schedules_bypasses_the_memo(engine):
    """Three surfaces read `tv.intake`, and after #146's first pass only one of them was throttled.

    `/api/floor` had the memo; `/api/temporal/jobs` had nothing at all (the panel's `loadEngine`
    calls it on a 20-second interval AND ~600-800 ms after most manual actions); the SSE stream had
    its own per-connection window, so N browsers meant N copies. What the three shared was the
    NUMBER, not the memo — under a panel comment saying the schedule read was memoized
    process-wide.

    COUNTED AT `tv.intake`, because that is the read being limited: a count taken at
    `intake_cached` would be satisfied by a caller that never reached it. Measured by driving all
    three inside one window: **3** before this change, **1** after (2026-09-17). At 1 + N + P
    sequential describes that is 33 round trips rather than 11 on a five-project deployment, every
    20 seconds, per browser.
    """
    client = _client()

    floor_answer = client.get("/api/floor")
    jobs_answer = client.get("/api/temporal/jobs")
    frame = await _one_stream_frame()

    assert floor_answer.status_code == 200 and jobs_answer.status_code == 200, (
        f"a route did not answer ({floor_answer.status_code}, {jobs_answer.status_code}) — this "
        f"case measures a read count and would have 'passed' on a 500")
    assert jobs_answer.json()["connected"] is True, (
        f"/api/temporal/jobs did not reach the engine at all ({jobs_answer.json()}) — its intake "
        f"read never happened, so the count below would measure nothing")
    assert '"intake"' in frame, (
        f"the stream frame carries no intake ({frame[:160]!r}) — it never made the read this case "
        f"is counting (#139 holds that the frame must carry it)")

    assert engine.calls == 1, (
        f"the floor, /api/temporal/jobs and one stream frame cost {engine.calls} schedule reads "
        f"inside one {reading.INTAKE_TTL_S}s window, not 1 — a reader is bypassing the memo, and "
        f"each bypass is 1 + N + P sequential describes (#146)")


@pytest.mark.asyncio
async def test_a_FAILED_read_still_RAISES_for_the_panel_routes_and_reads_unread_for_the_floor(
        monkeypatch, engine):
    """The inversion, asserted on both sides — the thing most likely to break silently.

    `intake_cached` is public and wraps the RAW `tv.intake`, so it raises; `_intake` is the
    catching wrapper the floor uses. It was the other way round when the memo landed: the memo
    wrapped the catching `_intake`, and a panel route calling it would have been handed `None` from
    a failed read. That arrives on the wire as `"intake": null` beside `"connected": true` — a
    frame claiming the engine answered, about a read that did not — and steps over the `except`
    branch those routes already have.

    So: a failed read must reach `/api/temporal/jobs` as its own `connected: False` frame, and
    reach the floor as unread. One memo, two failure semantics, and neither is inherited from the
    other by accident.
    """
    from openfactory.runtime.temporal import view as tv

    async def _broken(_client=None):
        engine.calls += 1
        raise RuntimeError("the engine went away mid-describe")

    monkeypatch.setattr(tv, "intake", _broken)

    body = _client().get("/api/temporal/jobs").json()
    assert body["connected"] is False, (
        f"a failed schedule read was swallowed and the panel was told the engine answered: {body} "
        f"— the route's own except branch never ran")
    assert "intake" not in body, (
        f"the failed read reached the page as an intake value rather than as a disconnected "
        f"frame: {body}")
    assert body.get("error"), "the disconnected frame names no cause"

    got = await floor.gather(object(), want=("intake",),
                             now=datetime(2026, 9, 17, 12, 0, tzinfo=UTC))
    assert got.connected is True and got.intake is None, (
        f"the floor did not degrade: connected={got.connected!r} intake={got.intake!r}. The floor "
        f"reports an unreadable fact as unread and never raises — that is this module's contract, "
        f"and `_intake` is the wrapper that holds it")
    assert floor.state(got, "").word, "the ladder could not judge a floor with an unread intake"

    assert reading._intake_memo is None, (
        "a read that raised was stored, so every surface would serve the failure for the window "
        "after the engine recovered")


@pytest.mark.asyncio
async def test_an_ENGINE_BLIP_ON_THE_STREAM_drops_the_SHARED_memo(monkeypatch, engine):
    """"Never carry an intake read from before the blip" (#139) has to hold PROCESS-WIDE now.

    The stream has always cleared its own `slow` pair when the engine failed, because keeping it
    would show the page the poller's state from before the failure. Once the read became shared
    (#146, second pass) that line stopped being sufficient on its own: it forces a re-read, and
    this memo could answer the re-read with the exact value the blip was meant to discard — the
    guard would still have found its line and the page would still have been told about a poller
    nobody could reach. So the blip drops the memo too, and the invariant is the whole process's.

    DRIVEN THROUGH THE REAL GENERATOR, three passes — a good frame, an engine that dies inside the
    frame, a recovered engine — because what is under test is a line in the stream's `except`
    branch. Calling `reading.forget_intake()` from the case instead would pass whether or not
    anything in `app.py` ever calls it.

    COUNTED AT `tv.intake` INSIDE ONE UNEXPIRED WINDOW: the loop's sleep is stubbed out, so neither
    the generator's 10 s window nor the memo's can expire between passes. A second read therefore
    means the blip dropped the memo, not that a clock ran out. The sibling case in
    `test_a_frame_does_not_erase_what_it_omits.py` drives the same path and asserts on the FRAME's
    contents; this one holds the count, which is what #146 is about.
    """
    from openfactory.api import app as api
    from openfactory.runtime.temporal import view as tv

    alive = [True]

    async def _list_jobs(*_a, **_k):
        if not alive[0]:
            raise RuntimeError("the engine went away")
        return []

    async def _no_wait(*_a, **_k):
        return None

    monkeypatch.setattr(tv, "list_jobs", _list_jobs)
    monkeypatch.setattr(tv, "ui_base", lambda: "")
    monkeypatch.setattr(api.asyncio, "sleep", _no_wait)

    class _Socket:
        def __init__(self):
            self.asked = 0

        async def is_disconnected(self):
            self.asked += 1
            alive[0] = self.asked != 2      # the second pass dies, the third recovers
            return self.asked > 3

    response = await api.temporal_stream(_Socket())
    frames = [c async for c in response.body_iterator if c.startswith("data: ")]

    assert len(frames) == 3, f"the loop did not run three passes: {frames}"
    assert '"connected": false' in frames[1], (
        f"the engine died and the stream did not say so: {frames[1]!r}")
    assert engine.calls == 2, (
        f"the schedules were read {engine.calls} time(s) across the blip, not 2 — the frame after "
        f"the blip was served from a memo filled BEFORE the engine died, so the page is told "
        f"about a poller nobody could reach (#139). Clearing the generator's own `slow` stopped "
        f"being enough when the read became process-wide (#146)")


def test_the_STREAM_is_what_drops_it_and_the_request_scoped_routes_never_reach_it(
        monkeypatch, engine):
    """WHY ONLY THE STREAM CALLS `forget_intake`, held as a fact rather than argued in a comment.

    `/api/floor` and `/api/temporal/jobs` are request-scoped: they raise into their own `except`,
    answer one degraded payload, and re-read on the next request. They also cannot reach the memo
    at all while the engine is down — `gather` gates intake behind `got.connected`, and the jobs
    route builds `"jobs": await tv.list_jobs(...)` before `"intake"` in the same dict. So there is
    no path on which a route's own failure strands a pre-blip answer for it to serve.

    EXECUTED: the engine is made unreachable and both routes are driven. If this ever goes red,
    that route needs a `forget_intake` of its own.
    """
    from openfactory.runtime.temporal import view as tv

    async def _dead(*_a, **_k):
        raise RuntimeError("the engine went away")

    monkeypatch.setattr(tv, "connect", _dead)

    floor_body = _client().get("/api/floor").json()
    jobs_body = _client().get("/api/temporal/jobs").json()

    assert floor_body["word"], "the floor did not answer at all with the engine down"
    assert jobs_body["connected"] is False, (
        f"the jobs route did not report the engine as unreachable: {jobs_body}")
    assert engine.calls == 0, (
        f"a route whose engine is unreachable still consulted the schedule memo ({engine.calls} "
        f"read(s)) — that is the path that would strand a pre-blip answer, and it is supposed to "
        f"be unreachable")
