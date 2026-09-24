"""A read that failed is never painted as a floor with nothing on it (#298).

WHAT WAS SEEN. On the panel a running job disappeared for a few seconds at a time and came back,
and while it was gone the page offered "▶ Scan TO-DO now" — although a job held the floor and a
scan could start nothing. Three samples of `/api/temporal/jobs` over twenty seconds, one job
running throughout (`v0.3.0-8-g0f8314c`, one machine, Temporal dev server):

    08:41:08  temporal/jobs running: [<project> #2]
    08:41:16  temporal/jobs running: NONE        <-- the job is gone
    08:41:28  temporal/jobs running: [<project> #2]

and the body of the middle one was not an empty answer:

    {"connected": false, "jobs": [],
     "error": "the engine did not answer the job list within 3s (OPENFACTORY_ENGINE_DEADLINE)"}

`[]` MEANT TWO THINGS AT THE TWO ENDS. Four sites built the degraded frame — the route's two
branches and the stream's two — each writing `"jobs": []` beside `connected: false` for a question
it never got to ask. The page read that list as the frame's answer, in so many words ("`[]` means
'I cannot see any' — that is the frame's answer"), so `engine.jobs` went empty, the machine card
cleared, and `scanOffered()` saw no running job. `view._within` arms a three-second window after
one slow read, during which every read is refused without being tried, so one slow read blanked
the floor for several seconds; the reporter's panel logged 61 of them in an hour.

THE SAME SENTENCE, ONE ROUTE OVER. `/api/floor` read the same failed list as `inputs.jobs or []`
and answered "Unknown — nothing is running, and it could not read what needs a human", with
"Also — nothing is running — the next card will be picked up" beneath it: the header the page
draws on every frame, saying of a held floor that nothing is on it. And the pull request page, on
the board's own few-second tick, drew a review timeline it could not read as "no review recorded".

WHAT IS HELD HERE: a frame carries a job list exactly when it read one (`None` otherwise, `[]`
still the engine's own "nothing"); the page keeps the list it last had, marks it as that, and
offers no scan while it cannot say whether the floor is busy; the floor never says "nothing is
running" over a list it did not read. Section 6 joins the two ends: the route's REAL degraded
body is what the page is fed. Section 7 is the rest of the class the same check found — the page's
project list, a remote box's journal, and the poller's CLI after a pause.

EXECUTED, NOT READ, wherever the thing can be run: the routes under `TestClient` and the stream's
own generator, the page's functions under node.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from openfactory import floor
from openfactory.api import app as api

ROOT = Path(__file__).resolve().parent.parent
PANEL = (ROOT / "openfactory" / "api" / "panel.html").read_text(encoding="utf-8")

#: The sentence the reporter captured, verbatim — `view._within`'s own.
DEADLINE = "the engine did not answer the job list within 3s (OPENFACTORY_ENGINE_DEADLINE)"
RUNNING = {"project": "acme", "issue": "2", "status": "running", "state": "running"}
NOW = datetime(2026, 9, 24, 8, 41, 16, tzinfo=UTC)


# ── the bench ───────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def engine(monkeypatch, tmp_path):
    """One registered project and an engine double whose job list the case decides.

    No live engine is reached (`conftest._no_live_durable_engine`): `connect` hands back a
    sentinel and every read below it is a double. `jobs` is what `list_jobs` does — a list to
    answer, or an exception to raise — and `intake` the same for the schedule read."""
    from openfactory.floor import reading
    from openfactory.runtime.temporal import view as tv

    reg = tmp_path / "registry.yaml"
    reg.write_text(yaml.safe_dump({"projects": {"acme": {
        "name": "acme", "repo_path": "/work/acme", "enabled": True,
        "tracker": {"kind": "local", "repo": "acme"}, "forge": {"kind": "local", "repo": "acme"},
        "ci": {"kind": "none", "repo": "acme"}}}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKENS", raising=False)

    bench = {"jobs": [RUNNING], "intake": {"known": True, "on": True, "note": "",
                                            "watchers": {}}}

    async def _connect(*_a, **_k):
        return object()

    async def _list_jobs(*_a, **_k):
        if isinstance(bench["jobs"], BaseException):
            raise bench["jobs"]
        return list(bench["jobs"])

    async def _intake(_client=None):
        if isinstance(bench["intake"], BaseException):
            raise bench["intake"]
        return dict(bench["intake"])

    monkeypatch.setattr(tv, "connect", _connect)
    monkeypatch.setattr(tv, "list_jobs", _list_jobs)
    monkeypatch.setattr(tv, "intake", _intake)
    monkeypatch.setattr(tv, "temporal_config", lambda: ("localhost:7233", "default"))
    monkeypatch.setattr(tv, "ui_base", lambda: "")
    # A PROVEN BOX, so the floor's headline is decided by the job list and not by a gate this
    # bench never set up (`/work/acme` has never been proven on this machine).
    monkeypatch.setattr("openfactory.box_prove.health",
                        lambda _p: {"state": "proven", "gate": "", "detail": ""})
    reading.forget_intake()
    yield bench
    reading.forget_intake()


def _get(path: str) -> dict:
    from starlette.testclient import TestClient

    got = TestClient(api.app).get(path)
    assert got.status_code == 200, f"{path} answered {got.status_code}: {got.text[:300]}"
    return got.json()


def _unreachable():
    from openfactory.runtime.temporal import view as tv

    return tv.EngineUnreachable(DEADLINE)


# ── 1. the route says it could not read, instead of answering "none" ───────────────────────────

def test_the_ROUTE_s_degraded_frame_carries_no_job_list(engine):
    """THE DEFECT, at the route. The engine connected and the job list did not answer inside the
    deadline: the frame said `jobs: []` — "the engine answered, and nothing is running"."""
    engine["jobs"] = _unreachable()
    body = _get("/api/temporal/jobs")
    assert body["connected"] is False and DEADLINE in body["error"], body
    assert body["jobs"] is None, (
        f"the route answered jobs={body['jobs']!r} for a job list it could not read — the page "
        f"paints that as a floor with nothing on it, while a job holds it")


def test_the_ROUTE_with_no_engine_to_ask_carries_no_job_list(engine, monkeypatch):
    """The other degraded branch: no engine library, or nothing declares where the engine is. No
    list was read, so none is sent — `[]` here was the same filler."""
    monkeypatch.setattr(api, "_temporal",
                        lambda: (_ for _ in ()).throw(RuntimeError("no durable engine declared")))
    body = _get("/api/temporal/jobs")
    assert body["connected"] is False and body["jobs"] is None, body


def test_a_job_list_the_route_READ_is_not_thrown_away_with_the_schedule_read_after_it(engine):
    """The PARTIAL read. The job list answers and the schedule read after it does not: the frame
    stays `connected: False` (#146 pins that), and the list the engine DID give travels with it
    rather than being replaced by a `[]` it never said."""
    engine["intake"] = _unreachable()
    body = _get("/api/temporal/jobs")
    assert body["connected"] is False and "intake" not in body, body
    assert body["jobs"] == [RUNNING], (
        f"the route read {[RUNNING]} and sent {body['jobs']!r} — an answer the engine gave was "
        f"dropped because a different read failed after it")


def test_an_EMPTY_list_the_engine_gave_is_still_an_empty_list(engine):
    """The twin. `[]` keeps its one meaning: the engine answered, and nothing is there."""
    engine["jobs"] = []
    body = _get("/api/temporal/jobs")
    assert body["connected"] is True and body["jobs"] == [], body


# ── 2. the stream, which repeated the filler on every tick ──────────────────────────────────────

async def _stream(passes: int, *, before_each=lambda n: None) -> list[dict]:
    """Drive the REAL stream generator for `passes` passes and return the data frames."""
    from starlette.requests import Request

    class _Socket(Request):
        def __init__(self):
            super().__init__({"type": "http", "method": "GET", "path": "/api/temporal/stream",
                              "query_string": b"", "headers": []})
            self.asked = 0

        async def is_disconnected(self):
            self.asked += 1
            before_each(self.asked)
            return self.asked > passes

    response = await api.temporal_stream(_Socket())
    return [json.loads(c[len("data: "):]) async for c in response.body_iterator
            if c.startswith("data: ")]


async def test_the_STREAM_s_degraded_frame_carries_no_job_list(engine, monkeypatch):
    """A good frame with a job on the floor, then a pass whose job list does not answer. The
    second frame is what the page repainted from on every blip."""
    async def _no_wait(*_a, **_k):
        return None

    monkeypatch.setattr(api.asyncio, "sleep", _no_wait)

    def _the_second_pass_fails(n):
        engine["jobs"] = _unreachable() if n == 2 else [RUNNING]

    frames = await _stream(2, before_each=_the_second_pass_fails)
    assert len(frames) == 2, frames
    assert frames[0]["jobs"] == [RUNNING], frames[0]
    assert frames[1]["connected"] is False, frames[1]
    assert frames[1]["jobs"] is None, (
        f"the stream's degraded frame says jobs={frames[1]['jobs']!r} about a list it could not "
        f"read")


async def test_the_STREAM_with_no_engine_to_ask_carries_no_job_list(engine, monkeypatch):
    monkeypatch.setattr(api, "_temporal",
                        lambda: (_ for _ in ()).throw(RuntimeError("no durable engine declared")))
    frames = await _stream(1)
    assert len(frames) == 1 and frames[0]["connected"] is False, frames
    assert frames[0]["jobs"] is None, frames[0]


# ── 3. the floor never says "nothing is running" over a list it did not read ───────────────────

HEALTHY_INTAKE = {"known": True, "on": True, "note": "", "every_s": 180, "fired_ago_s": 60,
                  "next_in_s": 120, "num_actions": 100, "created_ago_s": 90000,
                  "fired_at": "2026-09-24T08:40:16Z", "next_at": "2026-09-24T08:43:16Z",
                  "watchers": {}}
#: A poller created a moment ago, its first tick queued — the ladder's "starting" verdict.
STARTING_INTAKE = {**HEALTHY_INTAKE, "fired_ago_s": None, "num_actions": 0, "created_ago_s": 20}


def _floor(**over) -> floor.FloorInputs:
    base = {"jobs": [], "intake": dict(HEALTHY_INTAKE), "inbox": None, "budget": {"state": "ok"},
            "projects": [{"name": "acme", "enabled": True,
                          "box": {"state": "proven", "gate": "", "detail": ""}}],
            "connected": True, "engine_address": "engine:7233", "now": NOW}
    base.update(over)
    return floor.FloorInputs(**base)


def _said(state) -> str:
    """Everything the answer puts on screen: the headline and every line under it."""
    return " | ".join([state.line, *(c["clause"] for c in state.also)])


def test_the_FLOOR_route_does_not_say_nothing_is_running_when_the_list_did_not_answer(engine):
    """The header the page draws on every frame, at the same moment as the blip: the engine is
    connected, and the job list did not answer inside the deadline."""
    engine["jobs"] = _unreachable()
    for path in ("/api/floor", "/api/floor/acme"):
        body = _get(path)
        said = " | ".join([body["line"], *(c["clause"] for c in body["also"])])
        assert "nothing is running" not in said, (
            f"{path} answered {said!r} over a job list it could not read — a job holds the floor")
        assert body["word"] == "Unknown", body["line"]


@pytest.mark.parametrize("inbox", [None, []], ids=["no-inbox", "inbox-read"])
def test_the_LADDER_says_it_cannot_tell_rather_than_nothing_is_running(inbox):
    """Both shapes of an unread list: with the inbox unread too (what `gather` always has), and
    with an inbox in hand, which used to leave nothing unread at all and fall through to Armed."""
    got = floor.state(_floor(jobs=None, inbox=inbox), "acme")
    said = _said(got)
    assert got.word == "Unknown" and got.cause == "unread", said
    assert "nothing is running" not in said, said
    assert "cannot say whether anything is running" in got.line, got.line


def test_a_poller_that_has_not_fired_yet_does_not_vouch_for_a_list_nobody_read():
    """The "starting" verdict answered Armed — "nothing is running — the poller has just been
    created" — whatever the job list said, and here it said nothing."""
    got = floor.state(_floor(jobs=None, intake=dict(STARTING_INTAKE)), "acme")
    assert got.word != "Armed" and "nothing is running" not in _said(got), _said(got)


@pytest.mark.parametrize("intake", [HEALTHY_INTAKE, STARTING_INTAKE], ids=["ticking", "starting"])
def test_a_list_that_WAS_read_and_is_empty_is_still_Armed(intake):
    """The twin. A ladder that refused to say "nothing is running" at all would pass every case
    above and tell nobody their floor is ready."""
    got = floor.state(_floor(jobs=[], intake=dict(intake)), "acme")
    assert got.word == "Armed" and got.clause.startswith("nothing is running"), got.line


def test_an_engine_that_did_not_answer_at_all_is_still_its_own_sentence():
    """The rung above is untouched: a disconnected engine says so, and nothing about running."""
    got = floor.state(_floor(jobs=None, connected=False, engine_error=DEADLINE), "acme")
    assert got.cause == "engine_down" and "nothing is running" not in _said(got), _said(got)


# ── 4. the pull request page, on the board's own tick ───────────────────────────────────────────

class _Forge:
    """A forge whose review timeline answers what the case says."""

    def __init__(self, events):
        self._events = events

    def pr_status(self, *, pr):
        return "open"

    def pr_body(self, *, pr):
        return "why"

    def pr_diff(self, *, pr):
        return ""

    def pr_events(self, *, pr):
        if isinstance(self._events, BaseException):
            raise self._events
        return self._events


@pytest.mark.parametrize("events,expected", [(OSError("database is locked"), None), ([], [])],
                         ids=["unread", "none-recorded"])
def test_a_review_timeline_that_could_not_be_read_is_not_an_empty_one(monkeypatch, events,
                                                                       expected):
    from types import SimpleNamespace

    from openfactory import credentials
    from openfactory.adapters.forge import registry

    monkeypatch.setattr(registry, "build_forge", lambda *_a, **_k: _Forge(events))
    monkeypatch.setattr(credentials, "forge_token_for", lambda *_a, **_k: "")
    monkeypatch.setattr(credentials, "deployment_forge_token", lambda *_a, **_k: "")
    got = api._pr_detail(SimpleNamespace(name="acme", forge=None), "7")
    assert got["events"] == expected, (
        f"the forge's timeline {'raised' if expected is None else 'was empty'} and the page was "
        f"handed {got['events']!r} — `None` is could not look, `[]` is looked and found none")


# ── 5. the page: keep what it last knew, mark it, offer no scan it cannot vouch for ─────────────

def _without_comments(page: str) -> str:
    page = re.sub(r"/\*.*?\*/", "", page, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", r"\1", line) for line in page.splitlines())


CODE = _without_comments(PANEL)


def _function(name: str) -> str:
    """One whole page function, cut at its own closing brace — or "" when the page has none, so a
    case can be driven against a page that predates the fix and fail on what it DOES."""
    at = CODE.find(f"function {name}(")
    if at < 0:
        return ""
    start = at - 6 if CODE[max(0, at - 6):at] == "async " else at
    depth = 0
    for pos in range(CODE.index("{", at), len(CODE)):
        depth += {"{": 1, "}": -1}.get(CODE[pos], 0)
        if depth == 0:
            return CODE[start:pos + 1]
    raise AssertionError(f"could not find the end of panel function {name}")


def _const(name: str) -> str:
    found = re.search(rf"^const {re.escape(name)}=.*$", CODE, re.M)
    assert found, f"the page no longer defines {name}"
    return found.group(0)


#: What every case stands on: the page's own merge, its scan rule and the two painters, over the
#: page's own starting engine object and a clock the case moves.
PRELUDE = r"""
let clock=1790000000000;Date.now=()=>clock;
let _floorRefused="",_engineAt=0;
"""


def _page(scenario: str, *, start: str | None = None) -> object:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the page's JavaScript cannot be executed here")
    boot = re.search(r"^let projects=[^,]*,engine=(\{[^;]*?\}),", CODE, re.M)
    assert boot, "the page's starting engine object is not where this guard can read it"
    script = "\n".join([
        PRELUDE, f"let engine={start or boot.group(1)};",
        _const("esc"), _const("ENGINE_KEPT_IF_ABSENT"),
        *(_function(f) for f in ("since", "fmtDur", "applyEngineFrame", "jobsStaleLine",
                                 "scanOffered", "_bevents", "paintPR")),
        "console.log(JSON.stringify((()=>{" + scenario + "})()))"])
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-1200:]
    return json.loads(done.stdout)


GOOD = {"connected": True, "jobs": [RUNNING], "intake": {"known": True, "on": True}}
IDLE = {"connected": True, "jobs": []}
#: The frame the reporter captured, in the shape the server sends it now.
BLIP = {"connected": False, "jobs": None, "error": DEADLINE, "build": {}}


def _frames(*frames: dict) -> str:
    return "".join(f"clock+=8000;applyEngineFrame({json.dumps(f)});" for f in frames)


def test_a_frame_that_could_not_read_the_jobs_KEEPS_the_list_the_engine_last_gave():
    """THE DEFECT, on the page: the running job left the screen until the next good frame."""
    got = _page(_frames(GOOD, BLIP) + "return engine.jobs")
    assert got == [RUNNING], f"a failed read cleared the floor: engine.jobs is {got!r}"


def test_the_kept_list_is_MARKED_with_why_and_when_it_was_read():
    got = _page(_frames(GOOD) + "const read=clock;" + _frames(BLIP)
                + "return {read,at:engine.jobs_read_at,why:engine.jobs_unread,"
                  "line:jobsStaleLine()}")
    assert got["at"] == got["read"], (
        "the kept list is dated by the frame that failed, not by the read that produced it")
    assert got["why"] == DEADLINE, f"the reason the list is old was dropped: {got['why']!r}"
    assert "could not be read" in got["line"] and DEADLINE in got["line"], got["line"]
    assert 'data-since="' in got["line"], "the age is printed once and never ticks"


def test_a_list_a_frame_DID_read_replaces_the_kept_one_and_clears_the_mark():
    """The twin, and the old guard's real point: `[]` from an engine that answered is its answer,
    so finished work still leaves the screen — and the mark goes with the failure."""
    got = _page(_frames(GOOD, BLIP, IDLE)
                + "return {jobs:engine.jobs,why:engine.jobs_unread,line:jobsStaleLine()}")
    assert got == {"jobs": [], "why": "", "line": ""}, got


def test_SCAN_is_not_offered_while_the_page_cannot_say_whether_the_floor_is_busy():
    """`scanOffered()` saw an empty list and offered the scan under a job holding the floor. The
    kept list here has NOTHING running in it — an idle floor read, then a read that failed — so
    the only thing standing between the page and the button is that the list is not current."""
    got = _page(_frames(IDLE) + "const before=scanOffered(null);" + _frames(BLIP)
                + "const during=scanOffered(null);" + _frames(IDLE)
                + "return {before,during,after:scanOffered(null)}")
    assert got == {"before": True, "during": False, "after": True}, (
        f"offered before/during/after the blip: {got} — an unknown floor is not an idle one, and "
        f"a floor read idle again is")


def test_SCAN_is_not_offered_before_any_job_list_was_read():
    """At boot the page draws the project before its first engine read lands: `engine.jobs` is
    the `[]` it was declared with, which nobody read."""
    assert _page("return scanOffered(null)") is False


def test_a_list_NEVER_read_says_so_rather_than_how_old_it_is():
    got = _page(_frames(BLIP) + "return {jobs:engine.jobs,line:jobsStaleLine()}")
    assert got["jobs"] == [] and "nothing here says what is running" in got["line"], got


def test_the_project_page_PAINTS_the_mark_and_ASKS_the_scan_rule():
    """The rules are only rules if the page that draws the card reads them."""
    body = _function("refreshProject")
    assert re.search(r"stale\.innerHTML\s*=\s*said", body) and "jobsStaleLine()" in body, (
        "the project page never draws the mark on the list it kept")
    assert re.search(r"sb\.style\.display\s*=\s*scanOffered\(parked\)", body)
    assert 'id="jobsStale"' in _function("renderProject"), "there is nowhere to draw the mark"


def test_the_pull_request_page_tells_an_unread_timeline_and_body_from_empty_ones():
    got = _page("""
      const drawer={innerHTML:"",classList:{add(){},remove(){}},setAttribute(){}};
      globalThis.$=s=>s==="#boardview .drawer"?drawer:{classList:{add(){},remove(){}}};
      const draw=pr=>{globalThis._bd={data:{pr:{ref:"7",state:"open",diff:"",...pr}}};
                      paintPR();return drawer.innerHTML};
      return {unread:draw({events:null,body:null}),empty:draw({events:[],body:""})}""")
    assert "reviews on this pull request could not be read" in got["unread"], got["unread"]
    assert "description could not be read" in got["unread"], got["unread"]
    assert "no review recorded" not in got["unread"] and "nothing written" not in got["unread"]
    assert "no review recorded" in got["empty"] and "nothing written" in got["empty"]


# ── 6. the two ends, joined ─────────────────────────────────────────────────────────────────────

def test_the_route_s_REAL_degraded_body_neither_clears_the_floor_nor_offers_a_scan(engine):
    """What the reporter saw, end to end: a good read with a job running, then the route's own
    answer to a job list that did not answer, fed to the page's own functions. Joined so the two
    ends cannot drift apart behind two green halves."""
    good = _get("/api/temporal/jobs")
    engine["jobs"] = _unreachable()
    blip = _get("/api/temporal/jobs")
    got = _page(_frames(good, blip)
                + "return {jobs:engine.jobs,scan:scanOffered(null),line:jobsStaleLine()}")
    assert got["jobs"] == [RUNNING], f"the job holding the floor left the screen: {got['jobs']!r}"
    assert got["scan"] is False, "a scan is offered over a floor the page cannot see"
    assert DEADLINE in got["line"], got["line"]


# ── 7. the rest of the class: the project list, a remote box's journal, the poller's CLI ────────
#
# Found by the check of every route and frame the page reads, and closed under this issue because
# it names the class: each is a read that failed, arriving as an empty answer.

def _boot_projects_read() -> str:
    """What `boot()` does to learn the project list — the statements between the surface being
    set and the first paint, run as the page runs them."""
    boot = _function("boot")
    start = boot.index('_surface="floor";') + len('_surface="floor";')
    return boot[start:boot.index("render();", start)]


def _index(scenario: str) -> dict:
    """Run `scenario` (an async body) over the page's own project read and index painter, with an
    `api` that answers from `routes` — `{fail: "..."}` rejects, the way `api()` does on a non-2xx."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the page's JavaScript cannot be executed here")
    declared = re.search(r"^let projects=([^,]*),engine=", CODE, re.M)
    assert declared, "the page's starting project list is not where this guard can read it"
    script = "\n".join([
        f"let projects={declared.group(1)};let routes={{}};let _surface='';",
        "async function api(u){const a=routes[u];if(!a||a.fail)throw new Error((a&&a.fail)||'x');"
        "return JSON.parse(JSON.stringify(a.body))}",
        "const nodes={'#app':{innerHTML:''}};function $(s){return nodes[s]||null}",
        "let _floor=null,inbox=null;function needsYouHtml(){return ''}function boxChip(){return ''}",
        "const toasts=[];function toast(a,b){toasts.push(b)}function curProject(){return ''}",
        "let _bd={};",
        _const("esc"),
        *(_function(f) for f in ("loadProjects", "renderIndex", "openBoard")),
        "(async()=>{" + scenario + "})().then(o=>console.log(JSON.stringify(o)))"
        ".catch(e=>{console.error(String(e&&e.stack||e));process.exit(1)})"])
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-1200:]
    return json.loads(done.stdout)


def test_the_BOOT_read_of_the_project_list_does_not_turn_a_failure_into_no_projects():
    """`boot()` read `/api/projects` with `.catch(()=>[])`, so a failed read drew "no projects yet
    — register the first one" on a deployment whose registry is full, and the index's own
    "could not be read" sentence, written for exactly this, could never be reached."""
    got = _index("routes={'/api/projects':{fail:'503 the registry could not be read'}};"
                 + _boot_projects_read() + "renderIndex();return {html:nodes['#app'].innerHTML}")
    assert "no projects yet" not in got["html"], "a read that failed is drawn as no projects"
    assert "the project list could not be read" in got["html"], got["html"]


def test_a_failed_re_read_keeps_the_project_list_the_page_has():
    got = _index("projects=[{name:'acme'}];routes={'/api/projects':{fail:'503'}};"
                 "await loadProjects();return {projects}")
    assert got["projects"] == [{"name": "acme"}], got


def test_a_project_list_that_WAS_read_is_drawn_as_it_is_empty_or_not():
    """The twin: an empty registry that answered is still "no projects yet"."""
    got = _index("routes={'/api/projects':{body:[]}};" + _boot_projects_read()
                 + "renderIndex();const empty=nodes['#app'].innerHTML;"
                 "routes={'/api/projects':{body:[{name:'acme',box:{},tracker:'local',"
                 "forge:'local',enabled:true}]}};await loadProjects();renderIndex();"
                 "return {empty,full:nodes['#app'].innerHTML}")
    assert "no projects yet" in got["empty"], got["empty"]
    assert "acme" in got["full"] and "no projects yet" not in got["full"], got["full"]


def test_the_board_does_not_say_there_is_no_project_when_the_list_could_not_be_read():
    got = _index("projects=null;await openBoard();return {toasts}")
    assert got["toasts"] and "could not be read" in got["toasts"][0], got
    assert "has no project" not in got["toasts"][0], got


class _RemoteTail:
    def __init__(self, answer):
        self._answer = answer

    def fetch_new(self):
        if isinstance(self._answer, BaseException):
            raise self._answer
        return self._answer


@pytest.mark.parametrize("tail", [_RemoteTail(OSError("no credentials for the log group")), None],
                         ids=["the-read-failed", "no-tail-could-be-built"])
def test_a_remote_box_s_journal_that_could_not_be_read_is_not_a_run_that_wrote_none(
        engine, monkeypatch, tail):
    """The run's journal is on a box this panel cannot see. Both ways of failing to reach it — the
    tail's read raised, or no tail could be built — returned the local `[]`, which the page draws
    as "this run wrote no journal on this machine": a claim about the run, made of our failure."""
    from starlette.testclient import TestClient

    monkeypatch.setattr(api, "_boxes_are_remote", lambda: True)
    monkeypatch.setattr(api, "_remote_tail", lambda *_a, **_k: tail)
    got = TestClient(api.app).get("/api/jobs/acme/7/events")
    assert got.status_code == 503, (
        f"the box's journal could not be read and the route answered {got.status_code} "
        f"{got.text[:200]!r}")
    assert "could not read" in got.json()["detail"], got.json()


@pytest.mark.parametrize("remote", [True, False], ids=["the-box-answered-none", "no-remote-box"])
def test_a_journal_that_WAS_read_and_is_empty_is_still_empty(engine, monkeypatch, remote):
    monkeypatch.setattr(api, "_boxes_are_remote", lambda: remote)
    monkeypatch.setattr(api, "_remote_tail", lambda *_a, **_k: _RemoteTail([]))
    assert _get("/api/jobs/acme/7/events") == []


def test_the_briefing_says_it_could_not_read_the_log_rather_than_that_there_is_none():
    """The card's briefing read `/events` with `catch(e){ evs=[] }` and drew "no journal for this
    run on this machine" for a read that failed. The Logs page already said "couldn't read"."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the page's JavaScript cannot be executed here")
    script = "\n".join([_const("esc"), "const _LOG_CAP=200;", _function("logBlock"),
                        "console.log(JSON.stringify({unread:logBlock([],'503 the box is away'),"
                        "none:logBlock([])}))"])
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-1200:]
    got = json.loads(done.stdout)
    assert "couldn't read this run's log" in got["unread"], got["unread"]
    assert "503 the box is away" in got["unread"] and "no journal" not in got["unread"]
    assert "no journal" in got["none"], "a run that wrote nothing is no longer said to have"
    assert re.search(r"logBlock\(evs,\s*evsErr\)", _function("openJobDetail")), (
        "the briefing does not hand the reason its read failed to the log block")


def _poller(monkeypatch, *, jobs):
    """`floor.gather` answering a held poller and `jobs` — `None` when the list was unread."""
    from openfactory.floor import reading as floor_reading
    from openfactory.runtime.temporal import schedule

    intake = {"known": True, "on": False, "note": "rolling", "every_s": 180, "next_in_s": 42}

    async def _gather(client=None, *, want=(), **_kw):
        return floor.FloorInputs(intake=intake, jobs=None if jobs is None else list(jobs),
                                 connected=jobs is not None)

    async def _hold(*, on, note):
        return {"changed": True, "was_on": not on, "note": note}

    monkeypatch.setattr(floor_reading, "gather", _gather)
    monkeypatch.setattr(schedule, "hold_poller", _hold)


@pytest.mark.parametrize("command", [["poller", "pause", "--note", "rolling"], ["poller", "status"]],
                         ids=["pause", "status"])
def test_the_poller_does_not_say_nothing_is_in_flight_over_a_list_it_could_not_read(
        monkeypatch, command):
    """`_poller_reading` returned `got.jobs or []`, so an engine that did not answer the job list
    printed "in flight: nothing" — right after a pause, the one moment an operator reads it as
    clear to roll the deployment, which is how a running job gets interrupted."""
    from typer.testing import CliRunner

    from openfactory.cli import app as cli

    _poller(monkeypatch, jobs=None)
    out = CliRunner().invoke(cli, command).output
    assert "in flight: nothing" not in out, out
    assert "in flight: UNKNOWN" in out and "could not be read" in out, out
    if command[1] == "pause":
        assert "Do not roll" in out, f"a pause over an unknown floor does not warn: {out}"


def test_the_poller_still_says_nothing_is_in_flight_when_the_list_WAS_read_and_is_empty(
        monkeypatch):
    from typer.testing import CliRunner

    from openfactory.cli import app as cli

    _poller(monkeypatch, jobs=[])
    out = CliRunner().invoke(cli, ["poller", "pause", "--note", "rolling"]).output
    assert "in flight: nothing" in out and "UNKNOWN" not in out, out
