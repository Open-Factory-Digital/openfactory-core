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
"""

from __future__ import annotations

import asyncio
import time
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


@pytest.mark.parametrize("why, project, found, kind", [
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
])
def test_everything_else_starts_nothing_and_says_nothing(why, project, found, kind):
    assert live.should_start(project, found, kind=kind) == (False, ""), why


def test_the_cap_holds_it_back_by_name_and_counts_nothing_of_the_units_own():
    up = [RunningPreview(compose_project="openfactory-pv-beta-3", unit="3", project="beta",
                         state="running"),
          RunningPreview(compose_project=preview.compose_project("acme", "12"), unit="12",
                         project="acme", state="running")]
    start, why = live.should_start(_acme(), _offered(), kind="compose", running=up, cap=1)
    assert not start and "at most 1 preview" in why and "beta 3" in why and "acme 12" not in why
    assert live.should_start(_acme(), _offered(), kind="compose", running=up, cap=2) == (True, "")


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
    monkeypatch.setattr(activities, "_running_previews", lambda kind: [RunningPreview(
        compose_project="openfactory-pv-beta-3", unit="3", project="beta", state="running")])
    preview.record(_offered())
    assert _after_the_job(OPEN) == "" and engine.started == []
    now = preview.latest("acme", "12")
    assert now.state == preview.OFFERED, "held back is not failed"
    assert any(n.startswith("The preview did not start on its own: this deployment runs at "
                            "most 1 preview") for n in now.notes), now.notes


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


def test_the_link_of_a_requirements_card_opens_that_card(sink):
    preview.record(_up(unit="req0012", kind="requirement", cards=("12",)))
    assert live.link_for("acme", "12") == "/p/acme/preview/12"


def test_the_hook_never_raises(monkeypatch):
    monkeypatch.setattr(preview, "unit_of_card", lambda *a: (_ for _ in ()).throw(OSError("db")))
    assert live.link_for("acme", "12") == ""
