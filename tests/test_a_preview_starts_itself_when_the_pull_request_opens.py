"""A preview starts itself when the pull request waits for a person, and says where it is once it
is up (#405; ADR-0050 D6 as amended on 2026-09-29).

1. THE DECISION (`live.should_start`) is the offer's judgement, read back: a record the job wrote at
   the gate, a declared shape, a named runtime, nothing already starting or up — and the operator's
   `preview.auto_start`. The cap is asked BEFORE starting, and a start it holds back is said as a
   note, never recorded as a failure.
2. THE START is the job's activity's, after the job returned: the same workflow and the same id a
   click starts, the factory named as who started it; never a failed job over it.
3. THROUGH THE JOB: the walking skeleton's human gate writes the offer and the activity starts from
   it — the two cannot disagree about "this change can be previewed".
4. WHEN IT IS UP the preview's own step comments on the card, in the project's language, with the
   panel's link (no key), and tells the product role once per start.
5. THE HOOK the product role's "your card's PR is ready" message asks: `live.link_for`.
6. WHAT FOLLOWS THE WORK NEVER OUTLASTS THE BEAT (review of #408): both tails run after their
   activity stopped heartbeating, so each is bounded well inside the window the engine counts —
   a preview that HANGS can neither fail the job nor hold its result, a tracker that hangs cannot
   have a stack that came up called dead — and the daemon is asked only once every cheaper
   refusal has said yes.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap
import threading
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest
from temporalio.testing import ActivityEnvironment

from openfactory import preview
from openfactory.contracts import JobState, RunResult
from openfactory.contracts.project import PreviewPolicy, Project
from openfactory.preview import demand, live
from openfactory.preview.plan import RunningPreview
from openfactory.runtime.temporal import activities

PR = "https://forge/acme/shop/pull/12"


@pytest.fixture
def sink(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "compose")
    monkeypatch.delenv("OPENFACTORY_PANEL_URL", raising=False)
    demand._CACHE.clear()
    yield
    demand._CACHE.clear()


def _offered(**kw) -> preview.Preview:
    base = dict(project="acme", unit="12", cards=("12",), state=preview.OFFERED, pr_urls=(PR,),
                branches={PR: "openfactory/12"})
    base.update(kw)
    return preview.Preview(**base)


def _acme(**policy) -> Project:
    return Project(name="acme", repo_path="/src/acme",
                   preview=PreviewPolicy(**policy) if policy else None)


# ── 1. the decision ─────────────────────────────────────────────────────────────────────────────


def test_what_the_offer_judged_startable_starts_on_its_own():
    assert live.should_start(_acme(), _offered(), kind="compose") == (True, "")


#: Every "no" that costs nothing to decide — the project's own choice, or a record the job did
#: not write. The cap is the one refusal that costs (a call to the daemon), so it is asked last.
_THE_CHEAPER_NOES = [
    ("the operator turned it off", _acme(auto_start=False), _offered(), "compose"),
    ("the deployment names no runtime", _acme(), _offered(), "none"),
    ("no runtime at all", _acme(), _offered(), ""),
    ("the base declares no shape — a proposal is offered", _acme(),
     _offered(shape={"case": "draft"}), "compose"),
    ("the offer said why none can start", _acme(), _offered(why="no preview can run"), "compose"),
    ("already starting", _acme(), _offered(state=preview.STARTING), "compose"),
    ("already up", _acme(), _offered(state=preview.LIVE), "compose"),
    ("the last one failed — a person starts it again", _acme(),
     _offered(state=preview.FAILED), "compose"),
    ("nothing was offered", _acme(), None, "compose"),
    ("no pull request on the record", _acme(), _offered(pr_urls=()), "compose"),
]


@pytest.mark.parametrize("why, project, found, kind", _THE_CHEAPER_NOES)
def test_everything_else_starts_nothing_and_says_nothing(why, project, found, kind):
    assert live.should_start(project, found, kind=kind) == (False, ""), why


BETA_IS_UP = RunningPreview(compose_project="openfactory-pv-beta-3", unit="3", project="beta",
                            state="running")


def test_the_cap_holds_it_back_by_name_and_counts_nothing_of_the_units_own():
    up = [BETA_IS_UP,
          RunningPreview(compose_project=preview.compose_project("acme", "12"), unit="12",
                         project="acme", state="running")]
    start, why = live.should_start(_acme(), _offered(), kind="compose", running=up, cap=1)
    assert not start and "at most 1 preview" in why and "beta 3" in why and "acme 12" not in why
    assert live.should_start(_acme(), _offered(), kind="compose", running=up, cap=2) == (True, "")


@pytest.mark.parametrize("why, project, found, kind", _THE_CHEAPER_NOES)
def test_the_previews_up_are_not_read_for_an_answer_something_cheaper_gave(why, project, found,
                                                                          kind):
    """Reading them is a `docker ps -a` (review of #408): handed over as a callable, it is called
    only once every refusal that costs nothing has said yes."""
    read: list = []

    def previews_up():
        read.append(1)
        return ()

    assert live.should_start(project, found, kind=kind, running=previews_up) == (False, "")
    assert read == [], why


def test_the_previews_up_are_read_once_when_the_cap_is_all_that_is_left_to_ask():
    read: list = []

    def previews_up():
        read.append(1)
        return [BETA_IS_UP]

    start, why = live.should_start(_acme(), _offered(), kind="compose", running=previews_up,
                                   cap=1)
    assert not start and "beta 3" in why, "what the callable answered is what the cap judged"
    assert read == [1]


# ── 2. the start ────────────────────────────────────────────────────────────────────────────────


class Engine:
    def __init__(self, *, taken: bool = False, broken: bool = False):
        self.started: list = []
        self.taken, self.broken = taken, broken

    async def start(self, client, params):
        from openfactory.runtime.temporal import view as tv

        if self.broken:
            raise RuntimeError("the engine is down")
        if self.taken:
            raise tv.PreviewAlreadyStarted(preview.workflow_id(params.project, params.unit))
        self.started.append(params)
        return preview.workflow_id(params.project, params.unit)


@pytest.fixture
def engine(monkeypatch, sink):
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import view as tv

    ProjectRegistry().add(_acme())
    eng = Engine()
    monkeypatch.setattr(tv, "start_preview", lambda client, params: eng.start(client, params))
    monkeypatch.setattr(activities, "engine_client", lambda: object())
    monkeypatch.setattr(activities, "_running_previews", lambda kind: ())
    return eng


def _after_the_job(result, issue: str = "#12") -> str:
    return asyncio.run(ActivityEnvironment().run(
        activities._a_preview_starts_on_its_own, "acme", issue, result))


OPEN = RunResult(ticket_id="#12", state=JobState.PR_OPEN, pr_url=PR)


def test_the_activity_starts_the_units_workflow_as_the_factory(engine):
    preview.record(_offered())
    wf = _after_the_job(OPEN)
    assert wf == preview.workflow_id("acme", "12")
    [params] = engine.started
    assert (params.project, params.unit, params.runtime) == ("acme", "12", "compose")
    assert params.started_by == live.AUTO_STARTER
    assert params.start_timeout_minutes == PreviewPolicy().start_timeout_minutes


def test_the_job_activity_hands_its_result_to_the_start(monkeypatch):
    """`run_job` itself — not a helper nobody calls — asks for the start with the job's result."""
    asked: list = []

    async def returned(fn, label, tick=None):
        return OPEN

    async def start(project, issue, result):
        asked.append((project, issue, result.state))
        return ""

    monkeypatch.setattr(activities, "_heartbeat_while", returned)
    monkeypatch.setattr(activities, "_watch_for", lambda inp: None)
    monkeypatch.setattr(activities, "_a_preview_starts_on_its_own", start)
    from openfactory.runtime.temporal.io import RunJobInput

    inp = RunJobInput(project="acme", issue="#12", sandbox="worktree")
    assert asyncio.run(ActivityEnvironment().run(activities.run_job, inp)) is OPEN
    assert asked == [("acme", "#12", JobState.PR_OPEN)]


def test_only_a_pull_request_handed_to_a_person_starts_one(engine):
    preview.record(_offered())
    for result in (RunResult(ticket_id="#12", state=JobState.DONE, pr_url=PR),
                   RunResult(ticket_id="#12", state=JobState.PR_OPEN, pr_url=None),
                   RunResult(ticket_id="#12", state=JobState.ON_HOLD, pr_url=PR)):
        assert _after_the_job(result) == ""
    assert engine.started == []


def test_a_click_that_came_first_is_the_one_start(engine):
    preview.record(_offered())
    engine.taken = True
    assert _after_the_job(OPEN) == "" and engine.started == []


def test_the_job_never_fails_over_its_preview(engine):
    preview.record(_offered())
    engine.broken = True
    assert _after_the_job(OPEN) == ""


def test_a_start_the_cap_held_back_is_a_note_on_the_card_not_a_failure(engine, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PREVIEW_MAX", "1")
    monkeypatch.setattr(activities, "_running_previews", lambda kind: [BETA_IS_UP])
    preview.record(_offered())
    assert _after_the_job(OPEN) == "" and engine.started == []
    now = preview.latest("acme", "12")
    assert now.state == preview.OFFERED, "held back is not failed"
    assert any(n.startswith("The preview did not start on its own: this deployment runs at "
                            "most 1 preview") for n in now.notes), now.notes


def test_a_start_a_person_made_while_the_cap_was_asked_is_not_relabelled_offered(engine,
                                                                                 monkeypatch):
    """The cap's answer is a call to the daemon, and the record the decision read is that old by
    the time the note is written (review of #408): the note goes on the record AS IT IS THEN, and
    only while it is still `offered` — never over a start somebody made in between."""
    monkeypatch.setenv("OPENFACTORY_PREVIEW_MAX", "1")

    def while_a_person_clicked(kind):
        preview.record(_offered(state=preview.STARTING, started_by="somebody"))
        return [BETA_IS_UP]

    monkeypatch.setattr(activities, "_running_previews", while_a_person_clicked)
    preview.record(_offered())
    assert _after_the_job(OPEN) == "" and engine.started == []
    now = preview.latest("acme", "12")
    assert (now.state, now.started_by) == (preview.STARTING, "somebody"), "the click stands"
    assert now.notes == (), "and no held note is written over it"


@pytest.mark.parametrize("why, policy, record", [
    ("the operator turned it off", {"auto_start": False}, _offered()),
    ("already starting", {}, _offered(state=preview.STARTING)),
    ("nothing was offered", {}, None),
])
def test_a_job_asks_the_daemon_nothing_for_a_start_it_was_never_going_to_make(engine, monkeypatch,
                                                                              why, policy, record):
    """Handed over as a value, the previews up were read on every job that opened a pull request
    — one `docker ps -a` after the heartbeat had stopped, for an answer `auto_start: false` had
    already given (review of #408)."""
    from openfactory.registry import ProjectRegistry

    asked: list = []
    monkeypatch.setattr(activities, "_running_previews", lambda kind: asked.append(kind) or ())
    if policy:
        ProjectRegistry().set_preview("acme", policy)
    if record is not None:
        preview.record(record)
    assert _after_the_job(OPEN) == "" and engine.started == []
    assert asked == [], why


def test_a_job_asks_the_daemon_once_when_the_start_is_about_to_be_made(engine, monkeypatch):
    asked: list = []
    monkeypatch.setattr(activities, "_running_previews", lambda kind: asked.append(kind) or ())
    preview.record(_offered())
    assert _after_the_job(OPEN) == preview.workflow_id("acme", "12")
    assert asked == ["compose"]


# ── 3. through the job ──────────────────────────────────────────────────────────────────────────

from tests.test_a_preview_is_started_on_demand import _job, _no_runtime  # noqa: E402
from tests.test_walking_skeleton import repo  # noqa: E402,F401 — the fixture


def test_the_human_gates_offer_is_what_the_activity_starts_from(repo, tmp_path, engine,  # noqa: F811
                                                                 monkeypatch):
    from openfactory.registry import ProjectRegistry

    _no_runtime(monkeypatch)
    runner = _job(repo, tmp_path)
    ProjectRegistry().remove("acme")
    ProjectRegistry().add(runner.project.model_copy(update={"repo_path": str(repo)}))
    result = runner.run("#8")
    assert result.state is JobState.PR_OPEN
    assert _after_the_job(result, "#8") == preview.workflow_id("acme", "8")
    assert [p.unit for p in engine.started] == ["8"]

    # the same job on a project whose operator said no: offered, and nothing starts
    engine.started.clear()
    ProjectRegistry().set_preview("acme", {"auto_start": False})
    assert _after_the_job(result, "#8") == "" and engine.started == []


# ── 4. when it is up ────────────────────────────────────────────────────────────────────────────


class Tracker:
    def __init__(self):
        self.said: list[tuple[str, str]] = []

    def comment(self, ref, body):
        self.said.append((ref, body))


@pytest.fixture
def told(monkeypatch, sink):
    from openfactory.product import events
    from openfactory.registry import ProjectRegistry

    ProjectRegistry().add(Project(name="acme", repo_path="/src/acme", language="pt-BR"))
    tracker, heard = Tracker(), []
    monkeypatch.setattr(activities, "_tracker_for", lambda project: tracker)
    monkeypatch.setattr(events, "preview_up", lambda project, **kw: heard.append(kw) or True)
    return SimpleNamespace(tracker=tracker, heard=heard)


def _up(**kw) -> preview.Preview:
    base = dict(project="acme", unit="12", cards=("12",), state=preview.LIVE, pr_urls=(PR,),
                services={"web": 3000}, expires_at=int(time.time()) + 3600,
                started_at=1_900_000_000, started_by=live.AUTO_STARTER)
    base.update(kw)
    return preview.Preview(**base)


def test_a_preview_that_came_up_is_said_on_its_card_with_a_link_that_holds_no_key(told):
    preview.record(_up())
    assert activities._the_preview_is_up("acme", "12") == ["12"]
    [(ref, body)] = told.tracker.said
    assert ref == "12"
    assert body.startswith("Pré-visualização no ar: /p/acme/preview/12"), body
    assert "UTC" in body and "t=" not in body, "no preview key is ever written to a tracker"
    assert told.heard == [{"card": "12", "url": "/p/acme/preview/12", "key": "12@1900000000"}]


def test_the_link_is_absolute_where_the_deployment_says_where_its_panel_is(told, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PANEL_URL", "https://panel.example/")
    preview.record(_up())
    activities._the_preview_is_up("acme", "12")
    assert "https://panel.example/p/acme/preview/12" in told.tracker.said[0][1]


def test_nothing_is_said_of_a_preview_that_is_not_up(told):
    preview.record(_up(state=preview.FAILED))
    assert activities._the_preview_is_up("acme", "12") == []
    assert told.tracker.said == [] and told.heard == []


def test_a_requirement_across_repositories_is_told_to_the_role_but_not_by_card_number(told):
    """Card numbers collide across a requirement's repositories (ADR-0050 D5): a comment by number
    alone could land on another repository's issue. The role is still told."""
    preview.record(_up(unit="req0012", kind="requirement", cards=("12", "13"),
                       repos={PR: "acme/web", PR + "3": "acme/api"}))
    assert activities._the_preview_is_up("acme", "req0012") == []
    assert [h["card"] for h in told.heard] == ["12", "13"]


def test_a_tracker_that_refuses_the_comment_does_not_silence_the_role(told, monkeypatch):
    def refuse(ref, body):
        raise RuntimeError("403")

    told.tracker.comment = refuse
    preview.record(_up())
    assert activities._the_preview_is_up("acme", "12") == []
    assert told.heard, "the product role is told whatever the tracker did"


def test_the_up_step_says_it_once_it_is_live(monkeypatch):
    """`preview_up` calls the telling only when the stack came up."""
    from openfactory.preview import steps
    from openfactory.preview.plan import PreviewUp
    from openfactory.runtime.temporal.io import PreviewStepInput, PreviewUpInput

    said: list = []
    monkeypatch.setattr(activities, "_the_preview_is_up", lambda p, u: said.append((p, u)))
    monkeypatch.setattr(activities, "_preview_unit", lambda step: (SimpleNamespace(name="acme"),
                                                                   object()))
    for ok in (True, False):
        monkeypatch.setattr(steps, "up", lambda *a, ok=ok, **k: PreviewUp(ok=ok, why="x"))
        from tests.test_a_preview_is_started_on_demand import _plan

        inp = PreviewUpInput(step=PreviewStepInput(project="acme", unit="12", runtime="compose"),
                             plan=_plan())
        asyncio.run(ActivityEnvironment().run(activities.preview_up, inp))
    assert said == [("acme", "12")]


# ── 5. the hook ─────────────────────────────────────────────────────────────────────────────────


def test_the_link_for_a_card_is_there_while_its_preview_is_up_and_only_then(sink):
    assert live.link_for("acme", "#12") == ""
    preview.record(_offered())
    assert live.link_for("acme", "#12") == ""
    preview.record(_up())
    assert live.link_for("acme", "#12") == "/p/acme/preview/12"
    assert live.link_for("acme", "acme/shop#12") == "/p/acme/preview/12"
    assert live.link_for("other", "#12") == "", "another project's record is none of this one's"
    preview.record(_up(expires_at=int(time.time()) - 1))
    assert live.link_for("acme", "#12") == "", "an expired preview has no link"
    assert live.link_for("acme", "no number") == ""


def test_the_link_is_found_whether_it_is_asked_for_by_the_project_or_by_its_name(sink, monkeypatch):
    """Both callers hand the hook the registry's PROJECT, and it compared that to the record's
    project NAME — never equal — so every "ready for you" said "start the preview from the card"
    while one was up (measured building #413). The hook answers the same for either, and the
    round's catch-all carries the link to the requester's message."""
    from types import SimpleNamespace

    from openfactory.product import events

    preview.record(_up())
    project = SimpleNamespace(name="acme")
    assert live.link_for(project, "#12") == live.link_for("acme", "#12") == "/p/acme/preview/12"

    asked: list[str] = []
    monkeypatch.setattr(events, "ready_for_you",
                        lambda project, *, card, pr_url, preview_url="", **kw:
                        asked.append(preview_url) or True)
    assert events.ready_at_the_gate(project, [("12", "https://x/pr/1")]) == ["12"]
    assert asked == ["/p/acme/preview/12"], asked


def test_the_link_of_a_requirements_card_opens_that_card(sink):
    preview.record(_up(unit="req0012", kind="requirement", cards=("12",)))
    assert live.link_for("acme", "12") == "/p/acme/preview/12"


def test_the_hook_never_raises(monkeypatch):
    monkeypatch.setattr(preview, "unit_of_card", lambda *a: (_ for _ in ()).throw(OSError("db")))
    assert live.link_for("acme", "12") == ""


# ── 6. what follows the work never outlasts the beat (review of #408) ───────────────────────────
#
# `_heartbeat_while` and `_heartbeating` beat while the work runs and stop when it returns; the
# start that follows a job and the telling that follows a stack coming up run AFTER that, against
# a window the engine is still counting. Measured before the bound, with the heartbeat
# instrumented: a tail that hung for 3 s returned 4.01 s after the last beat, one that hung for
# 40 s returned after 41.01 s — no ceiling. Each test below makes one thing in a tail hang far
# past the bound it runs under, and reads the clock INSIDE the loop: `asyncio.run` joins the
# threads still running on its way out, so a clock around it would count the very hang the bound
# cut.

#: What hangs, hangs for this long unless the test releases it — far past `CUT + SLACK`.
HANG = 8.0
#: The bound the tails run under here, and the scheduling a loaded machine may add on top of it.
CUT, SLACK = 0.2, 2.0


def _measured(fn, inp, release: threading.Event):
    """`(what the activity returned, seconds from its last beat — its start, when nothing beat —
    to its return)`; `release` is set once the clock is read, so what hung may end."""
    async def run():
        beats: list[float] = []
        env = ActivityEnvironment()
        env.on_heartbeat = lambda *details: beats.append(time.monotonic())
        began = time.monotonic()
        try:
            got = await env.run(fn, inp)
            return got, time.monotonic() - (beats[-1] if beats else began)
        finally:
            release.set()

    return asyncio.run(run())


@pytest.fixture
def the_job_returned(engine, monkeypatch):
    """`run_job` with its pass over at once — the real heartbeat loop, then the real tail."""
    from openfactory.runtime.temporal.io import RunJobInput

    monkeypatch.setattr(activities, "_do_run_job", lambda inp, run_id=None, watch=None: OPEN)
    monkeypatch.setattr(activities, "_watch_for", lambda inp: None)
    monkeypatch.setattr(activities, "_A_PREVIEW_STARTS_WITHIN", CUT)
    preview.record(_offered())
    return RunJobInput(project="acme", issue="#12", sandbox="worktree")


def test_a_daemon_that_never_answers_neither_fails_nor_holds_the_job(the_job_returned, engine,
                                                                     monkeypatch):
    """The probe is a thread, and a thread cannot be cancelled: it runs on in the background and
    its answer is dropped — the coroutine that was waiting for it begins nothing more."""
    release, asked = threading.Event(), []

    def never_answers(kind):
        asked.append(kind)
        release.wait(HANG)
        return ()

    monkeypatch.setattr(activities, "_running_previews", never_answers)
    got, gap = _measured(activities.run_job, the_job_returned, release)
    assert got is OPEN, "the job's result is the activity's, whatever its preview did"
    assert asked == ["compose"], "the hang measured is the daemon's"
    assert gap < CUT + SLACK, f"{gap:.2f}s from the last beat to the return"
    assert engine.started == [], "what was cut begins nothing more"


def test_an_engine_that_never_answers_neither_fails_nor_holds_the_job(the_job_returned, engine,
                                                                      monkeypatch):
    from openfactory.runtime.temporal import view as tv

    asked: list = []

    async def never_answers(client, params):
        asked.append(params.unit)
        await asyncio.sleep(HANG)

    monkeypatch.setattr(tv, "start_preview", never_answers)
    got, gap = _measured(activities.run_job, the_job_returned, threading.Event())
    assert got is OPEN and asked == ["12"]
    assert gap < CUT + SLACK, f"{gap:.2f}s from the last beat to the return"


def test_a_tracker_that_never_answers_neither_fails_nor_holds_the_up_step(told, monkeypatch):
    """The step answers that the stack is up within the bound; the telling, a thread, finishes in
    the background — and tells the product role once, as if nothing had been cut."""
    from openfactory.preview import steps
    from openfactory.preview.plan import PreviewUp
    from openfactory.runtime.temporal.io import PreviewStepInput, PreviewUpInput
    from tests.test_a_preview_is_started_on_demand import _plan

    release, asked = threading.Event(), []

    def never_answers(ref, body):
        asked.append(ref)
        release.wait(HANG)

    told.tracker.comment = never_answers
    monkeypatch.setattr(activities, "_SAID_UP_WITHIN", CUT)
    monkeypatch.setattr(activities, "_preview_unit", lambda step: (SimpleNamespace(name="acme"),
                                                                   object()))
    monkeypatch.setattr(steps, "up", lambda *a, **k: PreviewUp(ok=True, why=""))
    preview.record(_up())
    plan = _plan()
    inp = PreviewUpInput(step=PreviewStepInput(project="acme", unit="12", runtime="compose"),
                         plan=plan)
    got, gap = _measured(activities.preview_up, inp, release)
    assert got.ok and got.expires_at == plan.expires_at, "the stack came up, and the step says so"
    assert asked == ["12"], "the hang measured is the tracker's"
    assert gap < CUT + SLACK, f"{gap:.2f}s from the step's start to its return"
    assert told.heard == [{"card": "12", "url": "/p/acme/preview/12", "key": "12@1900000000"}], \
        "released, the thread finished its telling — once"


def _seconds(node: ast.expr, module) -> float:
    """A window or a period as its source writes it: a name of `module`, a number, or a
    `timedelta(...)` of numbers."""
    if isinstance(node, ast.Name):
        value = getattr(module, node.id)
    elif isinstance(node, ast.Call) and ast.unparse(node.func) == "timedelta":
        value = timedelta(**{kw.arg: ast.literal_eval(kw.value) for kw in node.keywords})
    else:
        value = ast.literal_eval(node)
    return value.total_seconds() if isinstance(value, timedelta) else float(value)


def _windows_of(activity_name: str) -> list[float]:
    """Every heartbeat window the workflows schedule `activity_name` under — read from the source,
    because a workflow's options are the arguments of a call, not names anything can import."""
    from openfactory.runtime.temporal import workflow as wf

    windows = []
    for call in ast.walk(ast.parse(inspect.getsource(wf))):
        if not (isinstance(call, ast.Call) and call.args and isinstance(call.args[0], ast.Name)
                and call.args[0].id == activity_name):
            continue
        windows += [_seconds(kw.value, wf) for kw in call.keywords if kw.arg == "heartbeat_timeout"]
    return windows


def _period_of(beating) -> float:
    """How long a heartbeat loop waits on its work between beats — the `timeout` of its one
    `asyncio.wait`."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(beating)))
    [wait] = [c for c in ast.walk(tree)
              if isinstance(c, ast.Call) and ast.unparse(c.func) == "asyncio.wait"]
    [timeout] = [kw.value for kw in wait.keywords if kw.arg == "timeout"]
    return _seconds(timeout, activities)


@pytest.mark.parametrize("activity_name, beating, bound", [
    ("run_job", activities._heartbeat_while, "_A_PREVIEW_STARTS_WITHIN"),
    ("preview_up", activities._heartbeating, "_SAID_UP_WITHIN"),
])
def test_each_tail_returns_within_half_its_heartbeat_window_of_the_last_beat(activity_name,
                                                                             beating, bound):
    """The beat can be one period old when the work returns, then the tail runs for at most its
    bound: period + bound is the most the engine goes without hearing from the activity before it
    has the result, and it stays within half the window the workflow declares — held here against
    the sources of both, so a window that shrinks or a bound that grows is said."""
    windows = _windows_of(activity_name)
    assert windows, f"no workflow schedules {activity_name} under a heartbeat — nothing to hold"
    period, within = _period_of(beating), getattr(activities, bound)
    for window in windows:
        assert period + within <= window / 2, (
            f"{activity_name}: a beat {period:.0f}s old plus a tail of {within:.0f}s is "
            f"{period + within:.0f}s, past half of the {window:.0f}s window")
