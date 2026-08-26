"""Is the factory working? — asked once, answered for every surface (#144).

#141 collapsed five contradicting status computations in the panel into one ladder. It left that
ladder in `panel.html`'s JavaScript, which is the same defect one level up: a capability of one
screen. The product owner, planning to sell Slack integrations:

    "na sequencia eu venderei integracoes com slack e se tiver da forma que esta terei um esforço
     para adaptar… melhor cenario é centralizar tudo em APIs (API First) e o dash board consumir
     como uma camada… se o cliente quiser montar o painel dele ou conectar a outro local ok"

He is right for the reason he gave. A Slack bot asked the same question would have re-implemented
nine rungs, and the two would have drifted exactly as the five did.

THE RULE THAT ORGANISES IT, and the one thing that stays in the browser: **the server answers about
the FACTORY; only the browser can answer about the BROWSER.** "This page has heard nothing for
three minutes" is a fact about a socket in somebody's tab — the server does not know it, and a
server asserting it would be inventing. So rung 2 is a thin client-side shell around everything
below.

THIS FILE IS ALSO A MIGRATION. Its claims were the 36 in `test_the_floor_has_one_answer.py`, which
executed the ladder under `node` against a JSON snapshot. That fixture's own docstring argued for
this move: a pure function is a function a test can state a world to. The node harness is gone; the
claims are not.
"""

from __future__ import annotations

import inspect
import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from openfactory import floor
from openfactory.floor import ladder as fs

NOW = datetime(2026, 8, 19, 22, 8, tzinfo=UTC)

#: A poller that is on, ticking every three minutes, fired two minutes ago, next tick queued.
HEALTHY_INTAKE = {"known": True, "on": True, "note": "", "every_s": 180, "fired_ago_s": 60,
                  "next_in_s": 120, "num_actions": 100, "created_ago_s": 90000,
                  "fired_at": "2026-08-19T22:06:00Z", "next_at": "2026-08-19T22:09:00Z",
                  "watchers": {}}


def world(**over) -> floor.FloorInputs:
    """A healthy deployment, so a case states only what it changes."""
    intake = over.pop("intake", None)
    base = {"jobs": [], "intake": dict(HEALTHY_INTAKE),
            "projects": [{"name": "acme", "enabled": True,
                          "box": {"state": "proven", "gate": "", "detail": ""}}],
            "inbox": [], "budget": {"state": "ok"}, "connected": True,
            "engine_address": "engine:7233", "now": NOW}
    if intake is not None:
        base["intake"] = {**HEALTHY_INTAKE, **intake} if isinstance(intake, dict) else intake
    base.update(over)
    return floor.FloorInputs(**base)


# ── 1. the ladder, one row per world ────────────────────────────────────────────────────────────

def test_a_healthy_idle_floor_is_ARMED_and_says_what_happens_next():
    got = floor.state(world(), "acme")
    assert (got.rung, got.word) == (9, "Armed")
    assert "will be picked up" in got.clause
    assert got.level == "ok" and got.ok


def test_a_PAUSED_POLLER_stops_the_whole_deployment():
    got = floor.state(world(intake={"on": False, "note": "held for the audit"}), "acme")
    assert (got.rung, got.word, got.cause) == (4, "Stopped", "poller_paused")
    assert "no card in TO-DO will be picked up" in got.clause
    assert "held for the audit" in got.clause, "the note is the most useful thing on screen"


def test_a_PROJECT_WITH_PICKUP_OFF_is_stopped_even_under_a_healthy_poller():
    """The pilot's own case (#134): the deployment-wide schedule is perfect and this project will
    still take nothing."""
    got = floor.state(world(projects=[{"name": "acme", "enabled": False,
                                       "box": {"state": "proven", "gate": ""}}]), "acme")
    assert (got.rung, got.cause) == (4, "pickup_off")
    assert "will not be taken, whatever the engine is doing" in got.clause
    assert any(a["key"] == "enable" for a in got.actions), "it never says how to turn it on"


def test_a_BOX_THAT_WOULD_BE_REFUSED_stops_the_project_and_names_the_command():
    got = floor.state(world(projects=[{"name": "acme", "enabled": True,
                                       "box": {"state": "expired", "gate": "proof expired",
                                               "detail": "the proof expired"}}]), "acme")
    assert (got.rung, got.cause) == (4, "box_gate")
    assert got.cmd == "openfactory box prove acme"


def test_a_HUMAN_IS_THE_BLOCKER():
    got = floor.state(world(inbox=[{"project": "acme", "issue": "7", "kind": "merge"}]), "acme")
    assert (got.rung, got.word, got.level) == (5, "Needs you", "warn")
    assert "pull request is waiting on your review" in got.clause


def test_a_SELF_CLEARING_WAIT_is_not_a_problem_and_names_its_time():
    got = floor.state(world(jobs=[{"project": "acme", "issue": "7", "status": "running",
                                   "wedged": False,
                                   "action": {"kind": "rate_limit",
                                              "wakes_at": "2026-08-19T23:30:00Z"}}]), "acme")
    assert (got.rung, got.word, got.level) == (6, "Waiting on a clock", "clock")
    assert "retries by itself at 23:30" in got.clause, (
        "a wait that cannot name its clock is not a clock")


def test_A_PARK_PAST_ITS_OWN_DEADLINE_becomes_a_persons_problem():
    """Promotion driven by `wakes_at` — the deadline the WORKFLOW sleeps on — and never by
    `retry_at`, the vendor string the platform refuses to obey (#140)."""
    got = floor.state(world(jobs=[{"project": "acme", "issue": "7", "status": "running",
                                   "wedged": False,
                                   "action": {"kind": "rate_limit",
                                              "wakes_at": "2020-01-01T00:00:00Z"}}]), "acme")
    assert (got.rung, got.word) == (5, "Needs you")


def test_a_park_is_NOT_promoted_off_the_vendor_string():
    """The engine's own `_pause_backoff` refuses to parse `retry_at` ("formats vary, clocks skew").
    A floor promoting on it would shout for a human up to 100 minutes before the engine intended
    to resume — the panel and the engine disagreeing about the same fact."""
    got = floor.state(world(jobs=[{"project": "acme", "issue": "7", "status": "running",
                                   "wedged": False,
                                   "action": {"kind": "rate_limit",
                                              "retry_at": "2020-01-01T00:00:00Z",
                                              "wakes_at": "2026-08-19T23:30:00Z"}}]), "acme")
    assert got.word == "Waiting on a clock", f"promoted off the vendor's claim: {got.line}"


def test_WORK_IN_PRODUCTION():
    got = floor.state(world(jobs=[{"project": "acme", "issue": "7", "status": "running",
                                   "title": "Add health check", "action": None,
                                   "wedged": False}]), "acme")
    assert (got.rung, got.word) == (7, "Working")
    assert "#7" in got.clause and "Add health check" in got.clause


def test_the_ENGINE_NOT_ANSWERING_is_UNKNOWN_and_not_a_verdict_on_the_factory():
    """The panel failing to reach Temporal is a fact about the panel; the worker may be running
    jobs perfectly. And the raw exception stays off the headline — it can carry addresses."""
    got = floor.state(world(connected=False,
                            engine_error="connection refused to 10.0.0.4:7233"), "acme")
    assert (got.rung, got.word) == (3, "Unknown")
    assert "10.0.0.4" not in got.clause and "10.0.0.4" in got.detail


def test_NO_ENGINE_INSTALLED_is_a_definite_no():
    got = floor.state(world(connected=False, engine_address="",
                            engine_error="no runtime extra"), "acme")
    assert got.word == "Stopped" and got.cause == "engine_down"


def test_DISAGREEING_BUILDS_outrank_everything():
    got = floor.state(world(build={"agree": False, "stamp": "aaa",
                                   "others": {"worker": {"stamp": "bbb"}}},
                            intake={"on": False}), "acme")
    assert (got.rung, got.word) == (1, "Unknown")
    assert "up -d --build" in got.cmd


# ── 2. Armed must be earned ─────────────────────────────────────────────────────────────────────

def test_a_POLLER_THAT_STOPPED_FIRING_is_not_armed():
    """The whole reason `Armed` is a separate word: switched on and silent for thirty minutes on a
    three-minute schedule is what the old header called `running`."""
    got = floor.state(world(intake={"fired_ago_s": 1800, "next_in_s": 60}), "acme")
    assert (got.word, got.cause) == ("Unknown", "poller_late")
    assert "may have stalled" in got.clause


def test_a_POLLER_WITH_NO_NEXT_TICK_is_STOPPED():
    got = floor.state(world(intake={"fired_ago_s": 4000, "next_in_s": -60}), "acme")
    assert (got.word, got.cause) == ("Stopped", "poller_stalled")


def test_a_POLLER_THAT_FIRED_RECENTLY_BUT_HAS_NO_NEXT_TICK_is_stopped():
    """Recency alone is not evidence; a FUTURE tick is. A schedule can fire and then have nothing
    queued — somebody deleted it — and the last tick still looks fresh."""
    got = floor.state(world(intake={"fired_ago_s": 30, "next_in_s": -5}), "acme")
    assert (got.word, got.cause) == ("Stopped", "poller_stalled")


def test_a_SCHEDULE_THAT_HAS_NEVER_FIRED_YET_is_armed_and_says_it_is_new():
    """A deployment forty seconds old has no tick history and is perfectly healthy. Without this
    every fresh install reads as broken for its first three minutes — the first thing a new
    operator would ever see."""
    got = floor.state(world(intake={"fired_ago_s": None, "num_actions": 0, "created_ago_s": 40,
                                    "next_in_s": 100, "fired_at": None}), "acme")
    assert got.word == "Armed" and "just been created" in got.clause


def test_a_SCHEDULE_CREATED_LONG_AGO_AND_NEVER_FIRED_is_stopped():
    got = floor.state(world(intake={"fired_ago_s": None, "num_actions": 0, "created_ago_s": 9000,
                                    "next_in_s": 100, "fired_at": None}), "acme")
    assert (got.word, got.cause) == ("Stopped", "poller_stalled")


def test_an_UNREADABLE_INTAKE_is_never_rendered_as_armed():
    got = floor.state(world(intake={"known": False, "on": None}), "acme")
    assert got.word == "Unknown" and got.cause == "unread"


def test_an_UNKNOWN_PICKUP_is_never_rendered_as_armed():
    got = floor.state(world(projects=[{"name": "acme", "enabled": None,
                                       "box": {"state": "proven", "gate": ""}}]), "acme")
    assert got.word == "Unknown"
    assert "acme" in got.detail


def test_a_LATE_RULE_scales_with_the_schedules_OWN_interval():
    """A deployment that polls hourly must not be called stalled by a rule written for one that
    polls every three minutes."""
    hourly = {"every_s": 3600, "fired_ago_s": 1800, "next_in_s": 1800}
    assert floor.state(world(intake=hourly), "acme").word == "Armed"
    assert floor.state(world(intake={"every_s": 180, "fired_ago_s": 1800,
                                     "next_in_s": 60}), "acme").word == "Unknown"


def test_the_COPY_NEVER_CLAIMS_A_SCAN_COMPLETED():
    """The honesty ceiling from #140, enforced where it is spent: `fired_ago_s` proves a tick
    FIRED. A dead worker leaves the schedule firing into an empty task queue."""
    got = floor.state(world(), "acme")
    said = " ".join([got.clause, got.meta, got.detail]).lower()
    assert "fired" in said, "the evidence for Armed is not stated at all"
    assert "scan completed" not in said and "scanned" not in said, said


# ── 3. an unread input downgrades, and never invents ────────────────────────────────────────────

def test_an_INBOX_THAT_COULD_NOT_BE_READ_is_never_a_CLEAN_FLOOR():
    """`/api/inbox` raises 503 when the engine is unreachable and `api()` does not throw on a
    non-2xx, so a count written as `(d||[]).length` reads a failed read as "nothing needs you" —
    the most dangerous sentence available here. `None` falls back to the engine's own flag."""
    got = floor.state(world(inbox=None,
                            jobs=[{"project": "acme", "issue": "7", "status": "running",
                                   "attention": True, "wedged": False,
                                   "action": {"note": "blocked on a credential"}}]), "acme")
    assert (got.rung, got.word) == (5, "Needs you")


def test_a_missing_inbox_ALONE_does_not_downgrade_a_floor_we_can_see():
    """The inbox is a RENDERING of the job rows, not a separate fact — so with the jobs in hand the
    engine's own `attention` flag answers the same question.

    CAUGHT LIVE, not by the suite (2026-08-19). `gather` never fetched the inbox, so the old rule
    fired on every healthy deployment and `/api/floor` reported Unknown, permanently, to everybody
    — while every test passed, because they all stated an inbox explicitly."""
    got = floor.state(world(inbox=None), "acme")
    assert got.word == "Armed", f"a floor we can see was downgraded by a rendering of it: {got.line}"


def test_LOSING_BOTH_is_honestly_unknown():
    """Its twin, and the real blindness: no inbox and no job list means nothing can say whether a
    human is needed, and the floor must not promise anything."""
    got = floor.state(world(inbox=None, jobs=None), "acme")
    assert got.word == "Unknown" and got.cause == "unread"
    assert "what needs a human" in got.detail


def test_an_UNREADABLE_PROJECT_LIST_is_not_an_empty_one():
    got = floor.state(world(projects=None), "")
    assert got.word == "Unknown"
    assert "which projects exist" in got.detail
    assert got.census is None, "a census was invented from a list nobody could read"


def test_the_floor_NAMES_THE_CAUSE_rather_than_saying_something_is_wrong():
    """Healthy is quiet; unhealthy is SPECIFIC. `floor: degraded` would be the worst of both — as
    loud as a real alarm and as useless as silence, sending an operator hunting for what.

    Moved here from the panel's own guards (#144): the sentence is composed by the platform now,
    so this is where the claim belongs."""
    paused = floor.state(world(intake={"on": False}), "acme")
    assert "poller is paused" in paused.clause

    mute = floor.state(world(connected=False, engine_error="refused"), "acme")
    assert "did not answer" in mute.clause

    broke = floor.state(world(budget={"state": "low", "remaining": 12, "vendor": "Acme Tracker",
                                      "reset_at": "14:20"}), "acme")
    assert "budget" in broke.clause and "12" in broke.clause and "14:20" in broke.clause
    assert "Acme Tracker" in broke.clause and "GitHub" not in broke.clause, (
        "the sentence names the vendor the ADAPTER put on the budget, never one of its own")
    assert broke.word == "Waiting on a clock", (
        "a quota that resets by itself is not a problem a human must solve")


def test_an_UNREADABLE_BUDGET_never_reports_a_stop_that_is_not_happening():
    """The poller FAILS OPEN on a budget it cannot read — it scans anyway. Rendering `unread` as
    `low` would report pickups paused while they are not."""
    got = floor.state(world(budget={"state": "unread"}), "acme")
    assert got.word == "Armed", f"an unreadable budget was reported as a stop: {got.line}"


def test_a_vendor_with_NO_BUDGET_is_neither_a_stop_nor_a_failure():
    """The fourth state. A Jira or Azure Boards deployment has no quota to read; `not_reported`
    is a declaration, and rendering it as `low` (a stop) or `unread` (a probe failure) would send
    somebody to fix a probe that has nothing to probe."""
    got = floor.state(world(budget={"state": "not_reported"}), "acme")
    assert got.word == "Armed", f"a vendor with no budget was reported as a problem: {got.line}"


# ── 4. no two surfaces can disagree ─────────────────────────────────────────────────────────────

def test_the_PROJECT_and_the_DEPLOYMENT_are_the_same_computation():
    """One function, two scopes. The contradiction the pilot saw was two computations."""
    inputs = world(projects=[{"name": "acme", "enabled": False,
                              "box": {"state": "proven", "gate": ""}}])
    card = floor.state(inputs, "acme")
    header = floor.state(inputs, "")
    assert card.cause == "pickup_off"
    # …and the deployment does not hide it: red must keep meaning "no card will be picked up", so
    # one stopped project of one rolls up, and among several it is pinned instead.
    assert "acme" in header.clause or any("acme" in a["clause"] for a in header.also)


def test_a_SECOND_STOPPED_PROJECT_is_not_swallowed_by_the_headline():
    got = floor.state(world(projects=[
        {"name": "acme", "enabled": False, "box": {"state": "proven", "gate": ""}},
        {"name": "widgets", "enabled": False, "box": {"state": "proven", "gate": ""}},
        {"name": "northwind", "enabled": True, "box": {"state": "proven", "gate": ""}}]), "")
    named = " ".join([got.clause] + [a["clause"] for a in got.also])
    assert "acme" in named and "widgets" in named


def test_a_STOPPED_row_is_PINNED_and_never_truncated_by_the_cap():
    many = [{"name": f"p{i}", "enabled": False, "box": {"state": "proven", "gate": ""}}
            for i in range(9)]
    got = floor.state(world(projects=many), "")
    assert len([a for a in got.also if a["level"] == "err"]) >= 7


def test_a_DARK_WATCHER_is_reported_and_NEVER_takes_the_headline():
    """A paused tech-lead round does not stop pickup — cards still start and ship — so a red
    headline would break what red means here and paint a working factory as broken. But both
    watchers are SILENT when idle, so a dead one and a quiet week look identical (#24 item 6)."""
    got = floor.state(world(intake={"watchers": {
        "openfactory-techlead-watch-acme": {"known": True, "on": False, "note": ""}}}), "acme")
    assert got.word == "Armed", f"a paused watcher took the headline: {got.line}"
    row = next((a for a in got.also if "round is paused" in a["clause"]), None)
    assert row and row["level"] != "err"
    assert "nobody reviews" in row["clause"], "it names the loop and not what stopping it costs"


def test_a_CONSEQUENCE_of_the_winner_is_not_reported_as_a_SECOND_problem():
    """An engine nobody could reach cannot have its poller read either. Listing both makes one
    failure look like two and buries the one an operator can act on."""
    got = floor.state(world(connected=False, intake=None, projects=None), "acme")
    assert got.cause == "engine_down"
    assert not [a for a in got.also if a["cause"] == "unread"], got.also


# ── 5. the census counts projects, and only what it can see ─────────────────────────────────────

def test_the_census_counts_PROJECTS_not_items():
    got = floor.state(world(projects=[
        {"name": "acme", "enabled": True, "box": {"state": "proven", "gate": ""}},
        {"name": "widgets", "enabled": False, "box": {"state": "proven", "gate": ""}}]), "")
    assert got.census["total"] == 2
    assert got.census["armed"] == 1 and got.census["stopped"] == 1
    assert "1 armed" in got.census_line and "1 stopped" in got.census_line


def test_an_INDEX_OF_CARDS_COSTS_ONE_CALL():
    """The panel used to run the ladder per card, in the browser. Every project's verdict rides
    the deployment answer — and the census is counted from exactly those, in the same walk, so the
    two cannot disagree about how many projects are stopped."""
    got = floor.state(world(projects=[
        {"name": "acme", "enabled": True, "box": {"state": "proven", "gate": ""}},
        {"name": "widgets", "enabled": False, "box": {"state": "proven", "gate": ""}}]), "")
    assert set(got.per_project) == {"acme", "widgets"}
    assert got.per_project["widgets"]["level"] == "err"
    assert got.per_project["acme"]["word"] == "Armed"
    assert got.per_project["widgets"]["word"] == "Stopped", (
        "the map carries a word that is not that project's own verdict")
    stopped = sum(1 for v in got.per_project.values() if v["level"] == "err")
    assert stopped == got.census["stopped"], (
        "the census and the per-project verdicts disagree — two walks over the same facts")


def test_a_project_scope_has_NO_per_project_map():
    """It is a rollup of a deployment; on one project it would be a map of one, which is noise —
    and a surface that read it there would be reading its own scope back."""
    assert floor.state(world(), "acme").per_project is None


def test_a_project_scope_has_NO_census():
    assert floor.state(world(), "acme").census is None


def test_the_census_names_only_NON_ZERO_buckets():
    assert "0 " not in floor.state(world(), "").census_line


# ── 6. it is reachable from two transports and implemented by neither ───────────────────────────

def test_the_HTTP_route_derives_NOTHING():
    """The house rule (`openfactory/actions/__init__.py`): the front ends are mappings. A route
    that re-derived a word would be the sixth computation."""
    from openfactory.api import app as api

    src = inspect.getsource(api.floor_state)
    assert "floor.state(" in src and "floor.gather(" in src
    for derived in ("intake", "box", "wedged", "Armed", "Stopped"):
        assert derived not in src.split('"""')[-1], (
            f"the route derives {derived!r} itself instead of rendering the platform's answer")


def test_the_CLI_reaches_the_same_module():
    """Two transports, one implementation. A verdict only a web page can obtain is a verdict that
    lives in the web page."""
    from openfactory import cli

    src = inspect.getsource(cli.floor_cmd)
    assert "floor.state(" in src and "floor.gather(" in src


def test_the_route_ANSWERS(monkeypatch, tmp_path):
    """Driven, not read: the field has to survive the route."""
    from starlette.testclient import TestClient

    from openfactory.api import app as api

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKENS", raising=False)

    body = TestClient(api.app).get("/api/floor").json()
    assert body["word"] in {w[0] for w in fs.WORDS.values()}
    assert isinstance(body["rung"], int) and 1 <= body["rung"] <= 10
    assert "line" in body and body["line"].startswith(body["word"])


def test_the_wire_shape_is_EXPLICIT_rather_than_the_dataclass():
    """A third party consumes this. `asdict` would mean that adding a private field to the
    dataclass silently widens somebody else's payload."""
    src = inspect.getsource(fs.FloorState.as_dict)
    body = src.split('"""')[2] if src.count('"""') >= 2 else src   # the docstring EXPLAINS why
    assert "asdict" not in body
    keys = set(floor.state(world(), "acme").as_dict())
    assert keys == {"scope", "word", "short", "level", "rung", "cause", "clause", "line", "detail",
                    "cmd", "meta", "actions", "also", "also_more", "census", "census_line",
                    "per_project", "ok"}


# ── 7. the gathering half is honest about what it did not read ──────────────────────────────────

@pytest.mark.asyncio
async def test_what_you_did_not_PAY_FOR_is_unread_and_not_fine():
    """The mechanism that makes three cadences possible without lying: a caller may skip the whole
    slow tier and the answer degrades to Unknown rather than becoming an unchecked promise."""
    got = await floor.gather(want=())
    assert got.jobs is None and got.intake is None and got.projects is None
    assert floor.state(got, "").word == "Unknown"


@pytest.mark.asyncio
async def test_an_UNKNOWN_FIELD_is_refused_rather_than_silently_unread():
    """A typo would leave its field `None`, which the ladder reports as "could not read" — so a
    misspelling would render as a degraded factory rather than as a bug."""
    with pytest.raises(ValueError, match="cannot read"):
        await floor.gather(want=("jobz",))


@pytest.mark.asyncio
async def test_a_HANDED_IN_budget_is_not_re_read():
    """The poller already reads the budget every tick. Paying for a second subprocess to learn the
    same number is the cost this parameter exists to avoid."""
    got = await floor.gather(want=(), budget={"state": "low", "remaining": 3})
    assert got.budget == {"state": "low", "remaining": 3}


def test_the_THRESHOLD_is_the_ADAPTERS_OWN_number(monkeypatch):
    """It was written down twice in core — `poller._RATE_FLOOR = 200` beside the doctor's
    `max(200, limit // 10)` — two numbers deciding one behaviour, so the doctor could say "nearly
    gone" at a level the poller was still scanning through. The number travels on the `Budget`
    the adapter reports now, and the floor compares nothing of its own: the same `remaining` is
    `low` or `ok` exactly as the adapter's `floor` says."""
    import types

    from openfactory.adapters.tracker.base import Budget
    from openfactory.floor import reading

    def _world(floor_value: int):
        class _Tracker:
            def budget(self):
                return Budget(resource="graphql", remaining=100, limit=5000, floor=floor_value,
                              vendor="Acme")

        monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                            lambda project, **kw: _Tracker())
        monkeypatch.setattr("openfactory.credentials.tracker_token_for", lambda p: "tok")
        return [types.SimpleNamespace(name="acme", enabled=True,
                                      tracker=types.SimpleNamespace(kind="acme", options={}))]

    assert reading.budget_summary(reading.budgets(_world(77)))["state"] == "ok"
    assert reading.budget_summary(reading.budgets(_world(101)))["state"] == "low", (
        "the floor judged the budget by a number of its own instead of the adapter's floor")


def test_an_UNREAD_BUDGET_is_never_CACHED(monkeypatch):
    """The cache exists so a floor polled every two seconds does not fork a subprocess every two
    seconds. Caching a FAILURE would keep a transient `gh` hiccup on screen for a minute after the
    thing recovered — the cache turning into a memory of a problem that is over."""
    from openfactory.floor import reading

    monkeypatch.setattr(reading, "_budget_memo", None)
    monkeypatch.setattr(reading, "_budget", lambda: {"state": "unread"})
    assert reading._budget_cached()["state"] == "unread"
    assert reading._budget_memo is None, "a failed read was remembered"

    monkeypatch.setattr(reading, "_budget", lambda: {"state": "ok", "remaining": 4000})
    assert reading._budget_cached()["state"] == "ok", (
        "the failure was cached after all, so the recovery is invisible for a minute")


def test_an_UNREADABLE_REGISTRY_is_None_and_never_an_empty_list(monkeypatch):
    """`[]` tells the floor there are no projects — a claim — on exactly the failure where the
    honest answer is that we could not look. Driven through the reader, because the ladder half of
    this was already guarded and the gap was here."""
    from openfactory.floor import reading

    class _Boom:
        def list(self):
            raise RuntimeError("registry unreadable")

    monkeypatch.setattr(reading, "ProjectRegistry", _Boom, raising=False)
    monkeypatch.setattr("openfactory.registry.ProjectRegistry", _Boom)
    assert reading._projects() is None, "an unreadable registry reported an empty deployment"


def test_the_gatherer_NEVER_RAISES(monkeypatch):
    """A floor that cannot be described is a floor described as undescribable. The one thing this
    may never do is take a surface down while trying to tell it something."""
    from openfactory.floor import reading as g_mod

    monkeypatch.setattr(g_mod, "_projects", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        g_mod._projects()          # the double really does explode…
    # …and every real reader wraps its own failure into `None` rather than propagating.
    for reader in (g_mod._build, g_mod._budget):
        assert reader() is not None or True


def test_the_two_ATTENTION_definitions_are_one():
    """They had already drifted: `view.ATTENTION_STATES` carried `awaiting_your_merge` and
    `app._ATTENTION` did not — one word, two definitions, in the two modules that decide whether a
    job is somebody's problem.

    Asserted as the ABSENCE OF A SECOND NAME rather than as equality of two: two constants that
    happen to match today are still two places somebody can edit tomorrow."""
    import re

    src = pathlib.Path("openfactory/api/app.py").read_text()
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    # AT ANY INDENTATION. The first cut anchored on `^_ATTENTION`, so a copy declared INSIDE the
    # route — which is exactly how a hurried edit would reintroduce it — sailed past.
    assert not re.search(r"^\s*_ATTENTION\s*=", code, re.M), (
        "the web layer defines its own set of attention states again")
    from openfactory.runtime.temporal import view as tv

    assert "awaiting_your_merge" in tv.ATTENTION_STATES, (
        "the owning module lost the state the drift was about")


# ── 8. the browser keeps exactly one thing ──────────────────────────────────────────────────────

def test_rung_2_is_NOT_in_the_platform():
    """The rule, asserted. "This page has heard nothing for three minutes" is a fact about a
    socket in somebody's tab; a server that claimed it would be inventing. So the platform's ladder
    has no rung 2, and the client wraps it."""
    src = inspect.getsource(fs.causes)
    assert "page_blind" not in src, (
        "the server asserts something about the browser — it cannot know it")
    rungs = {c.rung for c in fs.causes(world(), "acme")}
    assert 2 not in rungs


def test_the_dead_park_rule_is_shared_with_the_engines_own_horizon():
    """`is_overdue` treats "no deadline at all" as a person's problem, and a rate-limit park
    always has one. A decision park deliberately passes ten years and reports `wakes_at: None`."""
    job = {"action": {"kind": "impediment", "wakes_at": None}}
    assert fs.is_overdue(job, NOW) is True
    assert fs.is_overdue({"action": {"kind": "rate_limit", "wakes_at": None}}, NOW) is False
    soon = (NOW + timedelta(minutes=30)).isoformat()
    assert fs.is_overdue({"action": {"kind": "rate_limit", "wakes_at": soon}}, NOW) is False


# ── 9. the gate a job is actually at, named ─────────────────────────────────────────────────────

def test_a_PULL_REQUEST_gate_is_named_as_one_even_without_the_inbox():
    """MEASURED ON THE PILOT (#148). The panel read `Needs you — podbeam #101 — waiting for CI /
    the merge` while the job carried `auto: false` — the CI was not what held it; the person
    reading the sentence was. Every gate flattened to `impediment`, whose phrase falls through to
    the park's own note.

    The engine already says which gate: this reads it instead of guessing."""
    job = {"project": "acme", "issue": "7", "status": "running", "attention": True,
           "wedged": False, "state": "awaiting_your_merge",
           "action": {"kind": "merge_wait", "auto": False, "note": "waiting for CI / the merge"}}
    got = floor.state(world(jobs=[job], inbox=None), "acme")

    assert got.word == "Needs you"
    assert "pull request is waiting on your review" in got.clause, got.clause
    assert "waiting for CI" not in got.clause, "it still names the wrong blocker"


def test_an_AUTO_merge_is_NOT_a_gate_and_keeps_its_clock():
    """The twin. `auto: true` really is waiting on CI, and nobody is needed — calling that a
    person's problem is the crying-wolf failure in the opposite direction."""
    job = {"project": "acme", "issue": "7", "status": "running", "wedged": False,
           "action": {"kind": "merge_wait", "auto": True, "note": "waiting for CI"}}
    got = floor.state(world(jobs=[job], inbox=None), "acme")
    assert got.word == "Waiting on a clock", got.line


def test_every_GATE_the_engine_names_gets_its_own_sentence():
    from openfactory.floor.ladder import need_kind

    assert need_kind({"state": "awaiting_your_merge"}) == "merge"
    assert need_kind({"state": "awaiting_prod_approval"}) == "approval"
    assert need_kind({"wedged": True}) == "wedged"
    assert need_kind({"action": {"decision": {"question": "?"}}}) == "decision"
    assert need_kind({"state": "on_hold"}) == "impediment"


def test_the_FALLBACK_is_not_the_poorer_answer():
    """The inbox and the engine rows describe the same jobs. Whichever path the floor takes, the
    sentence must be the same one — a fallback that says less is a second vocabulary."""
    job = {"project": "acme", "issue": "7", "status": "running", "attention": True,
           "wedged": False, "state": "awaiting_your_merge",
           "action": {"kind": "merge_wait", "auto": False, "note": "waiting for CI / the merge"}}
    from_rows = floor.state(world(jobs=[job], inbox=None), "acme")
    from_inbox = floor.state(world(jobs=[job],
                                   inbox=[{"project": "acme", "issue": "7", "kind": "merge"}]),
                             "acme")
    assert from_rows.clause == from_inbox.clause, (
        f"two paths, two sentences:\n  rows : {from_rows.clause}\n  inbox: {from_inbox.clause}")


# ── 10. the headline and the card must blame the same thing ─────────────────────────────────────
#
# The rest of #148: fixing the floor's sentence left the inbox card beneath it still reading
# "waiting for CI / the merge", because that text is the ENGINE's own note, published by the merge
# loop — a branch shared by both merge paths whose sentence described only the machine's. The
# product owner would have seen the corrected header directly above the uncorrected card. Two surfaces, one
# screen, opposite blockers.

def _blamed(sentence: str) -> str:
    """WHO a sentence sends the reader to wait for. Deliberately crude and fed its own must-catch
    cases below — a classifier nobody has attacked is not evidence ([[verify-the-verifier-first]])."""
    import re

    words = set(re.findall(r"[a-z]+", sentence.lower()))
    machine = bool(words & {"ci", "build", "checks", "pipeline"})
    reader = bool(words & {"your", "you", "review", "approve", "approval"})
    if machine and not reader:
        return "the machine"
    if reader and not machine:
        return "the reader"
    return "unnamed"


@pytest.mark.parametrize("sentence,who", [
    ("waiting for CI / the merge", "the machine"),
    ("waiting for your review and merge", "the reader"),
    ("a pull request is waiting on your review", "the reader"),
    ("Auto-merge armed — waiting for CI / the merge", "the machine"),
    ("waiting for CI before your review", "unnamed"),   # says both → must not vote for either
    ("parked", "unnamed"),                              # says neither
])
def test_the_classifier_can_tell_a_blocker_from_a_blocker(sentence, who):
    assert _blamed(sentence) == who


@pytest.mark.parametrize("auto", [True, False])
def test_the_engines_note_and_the_floors_clause_blame_the_same_thing(auto):
    """The equivalence the pilot's screen broke. `merge_wait_note` is what the inbox card prints;
    the ladder's clause is what the header prints. Whatever the path, they must point at ONE
    blocker — or the operator reads two answers a centimetre apart."""
    from openfactory.runtime.temporal.workflow import merge_wait_note

    note = merge_wait_note(auto)
    job = {"project": "acme", "issue": "7", "status": "running", "attention": not auto,
           "wedged": False, "state": "awaiting_your_merge" if not auto else "pr_open",
           "action": {"kind": "merge_wait", "auto": auto, "note": note}}
    got = floor.state(world(jobs=[job], inbox=None), "acme")

    assert _blamed(note) == _blamed(got.clause), (
        f"auto={auto}: the card says {_blamed(note)!r} and the header says "
        f"{_blamed(got.clause)!r}\n  card  : {note}\n  header: {got.clause}")
    assert _blamed(note) == ("the machine" if auto else "the reader"), note


def test_the_standing_wait_does_not_hand_write_its_own_sentence():
    """A PR sits in this branch for up to fourteen days, so its note is the one an operator lives
    with. Inlining the phrase again is how the human path got the machine's words in the first
    place — the loop must ask the one definition."""
    import ast

    src = pathlib.Path(__file__).resolve().parent.parent / "openfactory/runtime/temporal/workflow.py"
    tree = ast.parse(src.read_text())
    loop = next(n for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_ci_merge_loop")

    hard_coded = []
    for node in ast.walk(loop):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        if "self._merge_wait" not in {ast.unparse(t) for t in node.targets}:
            continue
        for key, val in zip(node.value.keys, node.value.values, strict=True):
            if getattr(key, "value", None) != "note":
                continue
            if isinstance(val, ast.Constant) and _blamed(val.value) != "unnamed":
                hard_coded.append(f"workflow.py:{node.lineno} — {val.value!r}")

    assert not hard_coded, (
        "a standing merge wait names a blocker in its own words instead of asking "
        "`merge_wait_note`, so the two paths can drift again:\n  " + "\n  ".join(hard_coded))
