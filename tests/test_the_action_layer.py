"""Every action exists ONCE, is reachable from two transports, and is implemented by neither (C-23).

WHAT #51 ACTUALLY ASKED FOR, and why the acceptance criterion is phrased as a reachability guard
rather than as a behaviour test: *"a test asserts every action is reachable from at least two
transports and implemented by none of them."* The card knew the failure mode before the code was
written, because it is this repository's signature defect — a layer built, tested and reached by
nothing (seventeen instances and counting). A behaviour test on `perform()` would have passed on
day one while both front ends carried on doing their own thing.

SO THERE ARE FOUR GUARDS, AND THEY FAIL DIFFERENTLY ON PURPOSE:

    reachability   every catalogued action is dispatched by the panel AND by the CLI, driven
                   through the real router and the real Typer app — not by calling `perform`
    non-duplication  the capability a moved action owns appears in NO front-end module
    mapping        each named legacy route reaches the row it claims to be a mapping onto
    bookkeeping    the codes, the parameter lists and the migration's own remaining work

THE SECOND ONE IS THE NEGATIVE GUARD, so it has a positive twin by construction: the first guard
asserts every row IS reached. A negative guard scans for a pattern and absence has no pattern —
which is exactly how ADR-0037 D4 shipped with `image=` missing from all four launch sites while a
guard forbidding the wrong value passed thirteen times.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
from pathlib import Path

import add_ons
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openfactory import actions
from openfactory.actions import base, catalog


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    from openfactory.api.app import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    return TestClient(app)


@pytest.fixture
def spy(monkeypatch):
    """Replace every action's runner with a recorder, through the CATALOG the layer actually reads.

    `ActionSpec` is frozen, so this rebuilds each row with `dataclasses.replace` rather than
    poking at attributes — a mutation that silently did nothing would make every reachability
    assertion below pass for the wrong reason.

    `by` IS ASSERTED HERE, ONCE, rather than in every call site's expectation. #51's criterion is
    that every action "takes *who asked* as a parameter", and checking it inside the recorder means
    a transport that drops the actor fails every reachability test at once instead of passing them
    all with a dictionary nobody compared."""
    seen: list[tuple[str, dict]] = []

    def recorder(name: str):
        async def run(by=None, **params):
            assert isinstance(by, actions.Actor), f"{name} was reached without an Actor"
            seen.append((name, params))
            return actions.done(f"recorded {name}")
        return run

    monkeypatch.setattr(catalog, "CATALOG", {
        name: dataclasses.replace(spec, run=recorder(name))
        for name, spec in catalog.CATALOG.items()
    })
    return seen


def _code_names(path: str) -> set[str]:
    """Every identifier this module USES — attributes, calls, imports, keyword arguments.

    AST rather than substring search, because the first version of these guards read the source as
    text and tripped on the docstrings that explain why the words must not be there. That is not a
    cosmetic problem: the obvious repair is to delete the explanation, which leaves a guard nobody
    can read and a rule nobody wrote down. Names in code positions are the thing being asserted;
    prose about them is the thing that has to stay."""
    return _names(path)[0]


def _borrowed_names(path: str) -> set[str]:
    """Only what this module reaches for OUTSIDE itself — attribute access and imports.

    The distinction is the whole guard. `bot.py` calls its own `act_job` mapping by a bare name and
    always will; what must never come back is `tv.act_job(...)` — an attribute on the engine's
    module — or an import of it. Collapsing the two would force the mapping function to be renamed
    to satisfy a guard about something else, and a guard that makes you rename correct code is one
    somebody eventually deletes."""
    return _names(path)[1]


def _names(path: str) -> tuple[set[str], set[str]]:
    tree = ast.parse(Path(path).read_text())
    every: set[str] = set()
    borrowed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            every.add(node.attr)
            borrowed.add(node.attr)
        elif isinstance(node, ast.Name):
            every.add(node.id)
        elif isinstance(node, ast.keyword) and node.arg:
            every.add(node.arg)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[-1]
                every.add(name)
                borrowed.add(name)
                borrowed.add(alias.name.split(".")[-1])  # the original, when aliased
            if isinstance(node, ast.ImportFrom) and node.module:
                every.update(node.module.split("."))
                borrowed.update(node.module.split("."))
    return every, borrowed


def _params_for(spec) -> dict[str, object]:
    """Something plausible for each declared parameter, so the reachability guard is not answered
    by a validation refusal. `issue` must survive `_clean_ref`; `enabled` must be a bool."""
    values = {"project": "demo", "issue": "412", "question": "what is up?", "version": "1.2.3",
              "approver": "alice", "password": "x", "enabled": True}
    return {p: values.get(p, "x") for p in spec.required}


# ── 1. reachability: every action, from two transports, through the real entry point ─────────────

@pytest.mark.parametrize("name", list(actions.names()))
def test_the_panel_can_reach_every_action(name, client, spy):
    """Driven through the FastAPI router, not through `perform` — because a route that does not
    exist, or one whose body forgot to await, is invisible to a test that calls the layer."""
    spec = actions.CATALOG[name]

    r = client.post(f"/api/act/{name}", json={"params": _params_for(spec)})

    assert r.status_code == 200, r.text
    assert [n for n, _ in spy] == [name]


@pytest.mark.parametrize("name", list(actions.names()))
def test_the_cli_can_reach_every_action(name, spy):
    """The second universal transport. A shell on the host is where an operator already is when the
    panel is the thing that is down."""
    from openfactory.cli import app as cli

    spec = actions.CATALOG[name]
    argv = ["act", name]
    for key, value in _params_for(spec).items():
        argv += ["--param", f"{key}={value}"]

    result = CliRunner().invoke(cli, argv)

    assert result.exit_code == 0, result.output
    assert [n for n, _ in spy] == [name]


def test_the_panel_lists_the_same_catalogue_the_cli_runs():
    """One table, two front ends — asserted rather than assumed. A panel offering an action the CLI
    cannot run (or the reverse) is the drift this card exists to end, one level up."""
    from openfactory.api.app import app

    with TestClient(app) as c:
        listed = [row["name"] for row in c.get("/api/actions").json()]

    assert listed == list(actions.names())


def test_an_unknown_action_names_what_exists(client):
    r = client.post("/api/act/teleport", json={"params": {}})

    assert r.status_code == 404
    assert "resume" in r.json()["detail"]  # the registry rule: refuse, naming what IS supported


# ── 2. non-duplication: a moved capability lives in NO front end ─────────────────────────────────

#: The transports. Anything here is a mapping: it may parse, render and decide who is asking, and
#: it may not DO.
FRONT_ENDS = ("openfactory/api/app.py", "openfactory/runtime/slack/bot.py", "openfactory/cli.py")

#: `capability marker → the action that now owns it`. A marker appearing in a front end means that
#: front end grew its own second copy — which is precisely how `resume` came to accept the parked
#: job's chosen option in the panel and not in Slack.
#:
#: THIS TABLE GROWS AS THE MIGRATION PROCEEDS. When `start`, `approve_prod` or `promote` move
#: into the catalog, add their markers here — `verify_approver` for the two release rows,
#: `PromotionRunner` for promote. Leaving a row out does not fail anything, which is why
#: `test_the_migration_list_is_honest` below forces the bookkeeping to be updated at the same
#: time.
#:
#: NOT EVERY OBVIOUS MARKER WORKS. `build_board` was the first candidate for `scan` and had to be
#: dropped: `cli.py::poll` and `bot.py::_board_index` both call it LEGITIMATELY, for their own
#: unrelated reads, so it would fail the guard on code that was never duplicating `scan` at all.
#: `list_workflows` is scan's actual marker — the floor-counting query that WAS `scan_now`'s own
#: logic and appears nowhere else in a front end.
OWNED = {
    "act_job": "resume/skip",                # the durable signal to a parked job
    "close_by_observation": "ack",           # closing a review finding's open loop
    "set_enabled": "enable",                 # flipping a project's pickup
    "list_workflows": "scan",                # the floor-counting query scan_now owned
    "start_workflow": "start",               # launching the durable path (temporal_start)
    "Popen": "start",                        # launching the local subprocess path (trigger_job)
    "verify_approver": "approve_prod/promote",  # the credential check both release rows share
    "approve_job": "approve_prod",           # the durable signal to the parked release gate
    # `ask` owns the DISPATCH, not the conversation: the agent must run where agents
    # authenticate (the worker), because the panel's process holds no harness credential —
    # found live when the tech-lead's "answer" in the panel was the CLI's own "Not logged
    # in". The conversation itself is owned by the worker activity (see
    # test_ask_reaches_the_SAME_tech_lead_the_channel_reaches).
    "execute_workflow": "ask",
    "PromotionRunner": "promote",            # running the release synchronously, in-process
    # The one seam every merge answer goes through — four of them since #181 added the
    # re-review, and the marker stays ONE because the seam did: a front end that grew its
    # own way to answer the gate would be a second definition of what the gate accepts.
    "answer_merge_gate": "merge/adjust/discard/review",
    # Ending a RUNNING job (#127). The marker is the engine call itself: until this row existed,
    # the only exit from a wedged job was an operator opening Temporal and terminating by hand —
    # a raw-engine operation on the one surface this product promises they will never need. A
    # front end that reacquired `terminate` would be that door reopening.
    "terminate": "stop",
    "diagnosis": "diagnose",                 # the tech-lead's triage of a parked job
    # The environment round (#99). Each marker is the thing that row OWNS, and the reason the CLI
    # sub-app can be a pure mapping: `env read` may not learn to read a repository, `env check` may
    # not learn to compose a verdict, and `env apply` may not learn to serialise a manifest.
    "infer": "env_read",                     # reaching the module that reads a repository
    # `propose_context`, not `survey`: the survey alone is a listing, and the CAPABILITY is the
    # proposal built on top of it — which is also the only one of the module's verbs that can spend
    # a token. A CLI that reacquired it would be a second place deciding when an agent runs.
    "propose_context": "env_context",        # proposing what a legacy codebase IS
    "readiness": "env_check",                # composing doctor/conformance/floor/box into one verdict
    "safe_dump": "env_apply",                # writing the client's manifest
    # Registering people by invitation (#33). The marker is the check that refuses a sink that
    # keeps nothing BEFORE a link is minted: a front end that reacquired it would be minting links
    # itself, which is the second copy of "who may vouch for whom" this row exists to prevent.
    "sink_is_durable": "people_invite",
    # The product role (#98). ONE marker for five rows, because they share one seam: a front end
    # that CONSTRUCTS the module is doing the work itself, whatever verb it then calls.
    #
    # `product/channel.py` (the file that was `runtime/slack/product_channel.py` until 2026-08-25)
    # is NOT a front end and does not belong in FRONT_ENDS: it is the product role's conversation
    # itself — core code that calls these verbs directly because it IS an implementation, on the
    # side of the line where implementations live. The Slack bot calls it and constructs nothing,
    # which is what this guard checks of bot.py.
    "ProductModule": "product_status/product_requirements/product_ask/product_propose/"
                     "product_accept/product_drop/product_queue/product_promote/"
                     "product_close_card/product_align_card/product_refine_card/"
                     "product_record_decision/product_note_fact/product_file_defect/product_reorder/product_say/"
                     # `product_pending` LISTS rather than acts, and is here for the gate rather
                     # than the corpus: a front end that constructed the module to find out what a
                     # project has staged would be reimplementing the refusal, which is the part
                     # that decides whether the caller may be told anything at all.
                     "product_pending/product_thread/product_triage/product_announce/"
                     "product_needs_action/"
                     # `product_answer` PERFORMS what was staged, so it belongs to the same seam:
                     # a front end that built the module to run a confirmation would be the second
                     # implementation this table exists to forbid.
                     #
                     # `answer_staged` is deliberately NOT the marker, and saying so here is the
                     # honest bookkeeping: `api/app.py` still calls that gate directly, because the
                     # panel answers inside one HTTP request while this row dispatches a workflow —
                     # and a yes on an `accept` runs an agent, which no request should be asked to
                     # stay open for on any deployment.
                     # Naming it would fail the guard for a crossing nobody has paid down, which is
                     # what teaches people to delete guards — the same reason the product
                     # conversation sat outside FRONT_ENDS while it was filed under Slack.
                     "product_baseline/product_answer",
    # `release` owns the PEN, not the judgement: `product.release.release` re-asks the engine
    # whether the job is still parked before signalling, and `_product_release` is the only
    # caller outside the Slack package. A front end that called it directly would be releasing
    # a client's software with no `may_act` check in front of it — the check lives in the row.
    "release": "product_release",
}


@pytest.mark.parametrize("marker,owner", sorted(OWNED.items()))
@pytest.mark.parametrize("module", FRONT_ENDS)
def test_no_front_end_implements_a_moved_action(module, marker, owner):
    """USES, not defines. `bot.act_job` and the panel's `set_enabled` route are still called those
    things and should be — they are the mappings. What must not appear is a front end *calling*
    `tv.act_job` or `registry.set_enabled` itself, which is what both of them used to do."""
    add_ons.source(module)  # the chat front end leaves the public tree with its package
    assert marker not in _borrowed_names(module), (
        f"{module} uses {marker!r}, which belongs to the '{owner}' action. A front end that does "
        f"the work is a second implementation, and the two drift without either side noticing — "
        f"see the table in openfactory/actions/__init__.py."
    )


def test_every_moved_action_brought_a_marker_with_it():
    """The table above is only as strong as its coverage, and coverage is the part that rots.

    Without this, moving `scan` into the catalog and forgetting to add `build_board` to OWNED
    leaves the panel free to grow its own copy again with every guard still green — the migration
    would tighten nothing beyond the four rows somebody happened to think of on the first day. So
    the table is checked AGAINST the catalog: an action that is no longer pending must be named as
    the owner of at least one marker."""
    owners = {name for value in OWNED.values() for name in value.split("/")}
    moved = {name for name in actions.names() if not actions.CATALOG[name].pending}

    assert moved <= owners, (
        f"moved with no marker in OWNED: {sorted(moved - owners)} — name the function or import "
        f"that action now owns, so a front end reacquiring it fails this file."
    )
    assert owners <= set(actions.names()), (
        f"OWNED names actions that do not exist: {sorted(owners - set(actions.names()))}"
    )


def test_the_action_layer_is_the_one_place_that_does_have_them():
    """The positive twin of the guard above. 'Nothing in the front ends does X' is satisfied just
    as well by nothing ANYWHERE doing X — an outage reads as compliance, which is how a guard
    forbidding a wrong value sailed past four launch sites that passed no value at all."""
    layer = _code_names("openfactory/actions/catalog.py")

    for marker, owner in OWNED.items():
        assert marker in layer, f"'{owner}' owns {marker!r} and the catalog does not use it"


def test_the_layer_does_not_learn_a_transport():
    """The other half of "reduced to mappings". A message pre-decorated for one surface renders as
    literal punctuation on the others, and an HTTP status decided inside an action would leave the
    CLI inventing a meaning for 409."""
    layer = _code_names("openfactory/actions/catalog.py") | _code_names("openfactory/actions/base.py")

    for foreign in ("HTTPException", "status_code", "JSONResponse", "mrkdwn", "blocks",
                    "postMessage", "typer", "fastapi", "slack_sdk"):
        assert foreign not in layer, f"the action layer uses {foreign!r} — that is a transport's"


# ── 3. the named routes are mappings onto the rows they claim ────────────────────────────────────

def test_the_legacy_act_route_maps_to_resume_with_the_chosen_option(client, spy):
    """ADR-0010 publishes this URL, so it keeps working — and it is now the same code path the
    Slack verb takes. `choice` is the whole reason this matters: it is the key of an option the
    parked job itself offered, and it existed on this side only."""
    r = client.post("/api/temporal/act/demo/412", json={"action": "resume", "choice": "B"})

    assert r.status_code == 200, r.text
    assert spy == [("resume", {"project": "demo", "issue": "412", "choice": "B"})]


def test_the_legacy_act_route_maps_to_skip(client, spy):
    client.post("/api/temporal/act/demo/412", json={"action": "skip"})

    assert spy == [("skip", {"project": "demo", "issue": "412"})]


def test_the_enable_toggle_maps_to_the_enable_action(client, spy):
    client.post("/api/projects/demo/enabled", json={"enabled": False})

    assert spy == [("enable", {"project": "demo", "enabled": False})]


def test_the_slack_verb_maps_to_the_same_rows(spy, monkeypatch):
    """The front end #51 opens with: the Slack bot never calls the HTTP API, so before this card
    there was nothing the two could share."""
    bot = add_ons.module("openfactory.runtime.slack.bot")

    project = type("_P", (), {"name": "demo", "admins": ["U1"]})()

    out = bot.act_job(project, "412", "skip", by=bot._actor(project, "U1"))

    assert spy == [("skip", {"project": "demo", "issue": "412"})]
    assert out.startswith("✅")


def test_slack_still_refuses_what_this_surface_may_not_do(spy):
    """The allow-list is a SURFACE policy, not an action's. An operator's channel resumes, skips
    and acks; a production release is a different surface with a different gate (ADR-0026)."""
    bot = add_ons.module("openfactory.runtime.slack.bot")

    out = bot.act_job(type("_P", (), {"name": "demo", "admins": []})(), "412", "promote")

    assert "não é permitida" in out
    assert spy == []  # refused before the layer, so nothing was attempted


def test_slack_carries_the_authorization_answer_into_the_layer(monkeypatch):
    """Slack knows `project.admins`; the layer enforces. That split is what C-26 later collapses,
    and building it as one parameter now makes that a rename rather than a migration."""
    bot = add_ons.module("openfactory.runtime.slack.bot")

    project = type("_P", (), {"name": "demo", "admins": ["U-admin"]})()

    out = bot.act_job(project, "412", "skip", by=bot._actor(project, "U-nobody"))

    assert "🔒" in out and "not allowed" in out


# ── 4. bookkeeping — the parts that rot in silence ───────────────────────────────────────────────

def test_every_outcome_code_has_an_http_status():
    """A code with no mapping falls through to 200 and reports a refusal as a success. This is the
    positive guard for a table nobody would think to check."""
    from openfactory.api.app import _STATUS

    assert set(actions.CODES) == set(_STATUS), (
        f"codes without a status: {sorted(set(actions.CODES) - set(_STATUS))}"
    )


def test_every_outcome_code_has_a_slack_mark():
    """The other rendering table. Its lookup is total (`.get(code, '❌')`), which is what makes a
    missing row invisible: a renamed or added code would report "#412 is not parked" behind a cross
    and read as a crash. Same guard as the HTTP one above, for the same reason."""
    _MARK = add_ons.module("openfactory.runtime.slack.bot")._MARK

    assert set(actions.CODES) == set(_MARK), (
        f"codes with no mark: {sorted(set(actions.CODES) - set(_MARK))}"
    )


def test_a_password_never_reaches_a_log_line(caplog, spy):
    """`approve_prod` and `promote` take the approver's password, and this layer writes an audit
    line on EVERY call — including the refusals, which is the path a wrong password takes."""
    import asyncio

    with caplog.at_level("INFO"):
        asyncio.run(actions.perform("promote", by=actions.SYSTEM, project="demo", issue="1",
                                    version="1.0.0", approver="alice", password="hunter2"))

    assert "hunter2" not in caplog.text
    assert "***" in caplog.text  # the key is still shown — the audit line stays readable


def test_every_declared_parameter_is_one_the_runner_accepts():
    """`required`/`optional` are declared by hand so `perform` can tell a forgotten parameter from
    an unwanted one. Declared by hand means they can disagree with the function — and the failure
    is a TypeError inside `perform`'s catch-all, surfacing to an operator as 'could not resume'."""
    import inspect

    for spec in actions.CATALOG.values():
        if spec.pending:
            continue  # a placeholder takes **params on purpose
        accepted = set(inspect.signature(spec.run).parameters)
        assert "by" in accepted, f"{spec.name} does not take `by` — every action takes who asked"
        missing = set(spec.parameters) - accepted
        assert not missing, f"{spec.name} declares {sorted(missing)} but its runner takes none"


def test_the_migration_list_is_honest():
    """`NOT_MOVED` is a literal, and this compares it against what the catalog actually reports.

    Both directions matter. Moving an action and forgetting the list leaves a stale record of the
    work; adding a placeholder and forgetting the list leaves an action nobody knows is missing."""
    reported = tuple(name for name, spec in catalog.CATALOG.items() if spec.pending)

    assert reported == catalog.NOT_MOVED


def test_the_migration_is_FINISHED_and_the_placeholder_machinery_still_works():
    """`NOT_MOVED` is empty: every action in the card's list — resume, skip, approve_prod, promote,
    enable, scan, ask, diagnose — exists once, in the catalog.

    The refusing-placeholder machinery is asserted anyway, because it is what the NEXT migration
    will use and an empty tuple would otherwise leave it untested from the day it stopped being
    needed. A row left out of the catalog until somebody moves the code is invisible; a row that
    refuses is visible in `sdlc act --list`, in the panel, and to every guard that walks it."""
    assert catalog.NOT_MOVED == ()

    placeholder = base.not_moved_yet("someday", still_in="wherever it works today")
    outcome = asyncio.run(placeholder(project="demo"))

    assert outcome.code == actions.UNIMPLEMENTED
    assert "wherever it works today" in outcome.message


def test_ask_reaches_the_SAME_tech_lead_the_channel_reaches(client, monkeypatch):
    """C-24's payoff, asserted from the door furthest from Slack — now in TWO hops, both proven.

    The hop is the fix: `ask` used to run the agent in whichever process served the request, and
    the panel's process holds no harness credential (deliberately), so the tech-lead's "answer"
    there was the CLI's own "Not logged in · Please run /login". The panel now DISPATCHES to the
    worker; the worker's activity runs the same `conversation.answer` the channel always ran."""
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import view as tv

    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _start_project())
    seen = {}

    class _Client:
        async def execute_workflow(self, name, inp, *, id, task_queue):
            seen["workflow"], seen["project"], seen["question"] = name, inp.project, inp.question
            return {"text": "o #69 está travado.", "suggestion": ["resume", "69"]}

    async def _connect():
        return _Client()

    monkeypatch.setattr(tv, "connect", _connect)

    r = client.post("/api/act/ask", json={"params": {"project": "demo", "question": "e o 69?"}})

    assert r.status_code == 200, r.text
    assert seen == {"workflow": "AskWorkflow", "project": "demo", "question": "e o 69?"}
    assert r.json()["message"] == "o #69 está travado."
    assert r.json()["data"]["suggestion"] == ["resume", "69"]


def test_the_workers_ask_activity_runs_the_conversation_the_channel_always_ran():
    """The second hop: one tech-lead, whoever asks. The activity must call the SAME
    `conversation.answer` — a second implementation here is how two front ends drift into two
    different tech-leads, which is the exact disease C-24 cured."""
    import asyncio

    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import activities
    from openfactory.runtime.temporal.io import AskInput
    from openfactory.techlead import conversation

    seen = {}
    real_get = ProjectRegistry.get
    real_answer = conversation.answer
    ProjectRegistry.get = lambda self, name: _start_project()

    def _answer(project, question, **kw):
        seen["project"], seen["question"] = project.name, question
        return conversation.Answer("resposta", ("skip", "7"))

    conversation.answer = _answer
    try:
        out = asyncio.run(activities.techlead_ask(AskInput(project="demo", question="e aí?")))
    finally:
        ProjectRegistry.get = real_get
        conversation.answer = real_answer

    assert seen == {"project": "demo", "question": "e aí?"}
    # `spend` joined the hop (#167): every other agent pass in this platform is priced and the one
    # a person talks to was not. An answer with nothing to report carries `{}` — never a zero,
    # which would read as "this was free".
    assert out == {"text": "resposta", "suggestion": ["skip", "7"], "spend": {}}


def test_and_what_the_answer_COST_survives_the_hop():
    """The half that makes the number worth carrying: it must arrive, not merely exist."""
    import asyncio

    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import activities
    from openfactory.runtime.temporal.io import AskInput
    from openfactory.techlead import conversation

    real_get, real_answer = ProjectRegistry.get, conversation.answer
    ProjectRegistry.get = lambda self, name: _start_project()
    conversation.answer = lambda project, question, **kw: conversation.Answer(
        "resposta", None, spend={"cost_usd": 0.42, "num_turns": 3})
    try:
        out = asyncio.run(activities.techlead_ask(AskInput(project="demo", question="q")))
    finally:
        ProjectRegistry.get, conversation.answer = real_get, real_answer

    assert out["spend"] == {"cost_usd": 0.42, "num_turns": 3}


def test_a_question_with_no_words_is_refused_before_an_agent_is_paid_for(client, monkeypatch):
    from openfactory.registry import ProjectRegistry

    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _start_project())

    r = client.post("/api/act/ask", json={"params": {"project": "demo", "question": "   "}})

    assert r.status_code == 400
    assert "no words" in r.json()["detail"]


# ── perform() itself ─────────────────────────────────────────────────────────────────────────────

async def test_perform_never_raises_and_keeps_the_real_message(monkeypatch):
    """An action that blows up must come back as an Outcome — both front ends have a hard
    must-always-reply rule and both used to implement it by wrapping every call themselves."""
    async def boom(**_kw):
        raise RuntimeError("nuget.org returned 401")

    monkeypatch.setattr(catalog, "CATALOG", {
        "resume": dataclasses.replace(catalog.CATALOG["resume"], run=boom)})

    out = await actions.perform("resume", by=actions.SYSTEM, project="demo", issue="1")

    assert out.ok is False and out.code == actions.FAILED
    assert "401" in out.message  # the cause survives, which is the whole of #66


async def test_an_action_that_reports_nothing_is_a_failure(monkeypatch):
    """A runner returning None would otherwise read as a success with an empty message — the
    silent-success shape. Named rather than trusted: `write-the-guard-not-the-care`."""
    async def forgets(**_kw):
        return None

    monkeypatch.setattr(catalog, "CATALOG", {
        "skip": dataclasses.replace(catalog.CATALOG["skip"], run=forgets)})

    out = await actions.perform("skip", by=actions.SYSTEM, project="demo", issue="1")

    assert out.ok is False and "did not report what it did" in out.message


@pytest.mark.parametrize("typed,expect", [
    ("#412", "412"),   # the decoration a human types
    (" 412 ", "412"),
    ("CONT-412", "CONT-412"),  # a Jira ref is not a number and must survive
])
async def test_a_ref_is_normalised_once_for_every_transport(typed, expect, spy):
    """`#189` and `189` must not be two tickets. The panel knew that; Slack passed whatever was
    typed straight into a Temporal workflow id, so `skip #250` and `skip 250` addressed different
    workflows and only one of them existed."""
    await actions.perform("skip", by=actions.SYSTEM, project="demo", issue=typed)

    assert spy == [("skip", {"project": "demo", "issue": expect})]


@pytest.mark.parametrize("bad", ["../../etc/passwd", "12 34", "a" * 65, "#"])
async def test_a_ref_no_tracker_could_issue_is_refused(bad, spy):
    out = await actions.perform("skip", by=actions.SYSTEM, project="demo", issue=bad)

    assert out.code == actions.INVALID and spy == []


async def test_an_unexpected_parameter_is_named_rather_than_ignored(spy):
    """A front end that renames a field and keeps working silently is how `image=` came to be
    omitted at all four job-launch sites while a guard forbidding the wrong value passed."""
    out = await actions.perform("skip", by=actions.SYSTEM, project="demo", issue="1", choise="B")

    assert out.code == actions.INVALID and "choise" in out.message and spy == []


async def test_a_non_admin_is_refused_before_anything_is_attempted(spy):
    out = await actions.perform("skip", by=actions.Actor(id="U9", via="slack"),
                                project="demo", issue="1")

    assert out.code == actions.DENIED and spy == []


async def test_a_read_only_action_does_not_need_an_admin():
    """`ask` and `diagnose` answer questions. Requiring an admin to ASK would make the tech-lead
    channel useless to the people it exists for — everyone may ask, nobody may act.

    The claim is about the GATE, so that is what is asserted: a non-admin gets past it and fails
    (or succeeds) on the merits downstream. Asserting a particular downstream code would make this
    depend on whether some other test happened to leave a project called "demo" registered —
    which is exactly how it failed once, under random ordering, proving the wrong thing twice."""
    for name, params in (("ask", {"question": "what is running?"}), ("diagnose", {"issue": "412"})):
        out = await actions.perform(name, by=actions.Actor(id="U9", via="slack"),
                                    project="demo", **params)

        assert out.code != actions.DENIED, f"{name} was refused for lack of an admin"


# ── scan — behaviour, not just reachability ─────────────────────────────────────────────────────
#
# `scan` moved from `api/app.py::scan_now` with three defects folded into its ordering, none of
# which had a pre-existing test locking them down (the route had none at all). These pin them
# down at the level they actually broke at: the ACTION, so the guarantee holds for every
# transport rather than for the one route that happened to get a test written against it.

class _FakeBoard:
    def __init__(self, todo: list[str]) -> None:
        self._todo = todo
        #: what `_scan` actually asked for — asserted directly rather than baked into a hardcoded
        #: string here, which would hide a regression on a vendor whose column is not "TO-DO"
        #: (`catalog.py`'s own `_scan` once had exactly that literal).
        self.status_checked: str | None = None

    def pickup_column(self) -> str:
        return "TO-DO"

    def items_in_status(self, status: str) -> list[str]:
        self.status_checked = status
        return list(self._todo)


class _FakeWorkflow:
    def __init__(self, wf_id: str) -> None:
        self.id = wf_id


class _FakeTemporalClient:
    """Just enough of the Temporal client surface for `_scan`: an async iterator of running
    workflows, and `start_workflow` recording what it was asked to launch."""

    def __init__(self, *, running: list[str] = (), fail_started: set[str] = frozenset()) -> None:
        self._running = list(running)
        self._fail_started = fail_started
        self.launched: list[tuple[str, object]] = []

    async def list_workflows(self, _query: str):
        for wf_id in self._running:
            yield _FakeWorkflow(wf_id)

    async def start_workflow(self, workflow_type, params, *, id, task_queue):  # noqa: A002
        if params.issue in self._fail_started:
            # `_scan` matches on the EXCEPTION'S CLASS NAME (`"AlreadyStarted" in
            # type(exc).__name__`), because the real one is `temporalio.exceptions.
            # WorkflowAlreadyStartedError` and this test does not want a `temporalio` import.
            raise _WorkflowAlreadyStartedError("already started")
        self.launched.append((id, params))


class _WorkflowAlreadyStartedError(Exception):
    pass


class _AsyncReturns:
    """`await x` → the wrapped value, for stubbing a zero-arg async function without defining one
    per call site."""

    def __init__(self, value) -> None:
        self._value = value

    def __await__(self):
        async def _inner():
            return self._value
        return _inner().__await__()


def _scan_project(**tracker_opts):
    from openfactory.contracts.project import Project, ProviderRef

    opts = {"board_owner": "o", "board_number": "1", **tracker_opts}
    return Project(name="demo", repo_path="/tmp/demo",
                   tracker=ProviderRef(kind="github", repo="o/demo", options=opts))


@pytest.fixture
def _scan_env(monkeypatch):
    """Everything `_scan` reaches for outside the board and the engine, pinned to something
    deterministic: a resolvable project, a token that needs no real credential, and a box image
    that resolves without hitting `ContainerSandbox`'s own registry lookups."""
    from openfactory.registry import ProjectRegistry

    project = _scan_project()
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: project)
    monkeypatch.setattr("openfactory.credentials.tracker_token", lambda: "tok")
    monkeypatch.setattr("openfactory.factory.resolve_box_image", lambda *_a, **_kw: "openfactory-python")
    return project


async def test_scan_refuses_a_project_with_no_board(monkeypatch):
    from openfactory.registry import ProjectRegistry

    project = _scan_project(board_owner="", board_number="")
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: project)

    out = await actions.perform("scan", by=actions.SYSTEM, project="demo")

    assert out.code == actions.INVALID and "no board configured" in out.message


async def test_scan_builds_the_board_from_the_project_OBJECT(monkeypatch, _scan_env):
    """The defect that made the button die silently: passing the project's PATH STRING to
    `build_board` reads as 'no board configured' even though one is. Asserting the object (not a
    string) reaches `build_board` is the whole regression test."""
    seen = {}

    def _build_board(project, **_kw):
        seen["project"] = project
        return _FakeBoard([])

    monkeypatch.setattr("openfactory.adapters.board.build_board", _build_board)
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect",
                        lambda: _AsyncReturns(_FakeTemporalClient()))

    await actions.perform("scan", by=actions.SYSTEM, project="demo")

    assert seen["project"] is _scan_env  # the OBJECT, never a str


async def test_scan_reports_an_empty_todo_as_success(monkeypatch, _scan_env):
    monkeypatch.setattr("openfactory.adapters.board.build_board", lambda *_a, **_kw: _FakeBoard([]))
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect",
                        lambda: _AsyncReturns(_FakeTemporalClient()))

    out = await actions.perform("scan", by=actions.SYSTEM, project="demo")

    assert out.ok is True and out.data["started"] == []  # empty TO-DO is not a failure


async def test_scan_asks_the_board_for_its_own_pickup_column_by_default(monkeypatch, _scan_env):
    """No `pickup_status` declared — `_scan` asks the board what its pickup column is called,
    rather than assuming "TO-DO". GitHub boards answer "TO-DO", so this is also the everyday
    path and stays green."""
    board = _FakeBoard([])
    monkeypatch.setattr("openfactory.adapters.board.build_board", lambda *_a, **_kw: board)
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect",
                        lambda: _AsyncReturns(_FakeTemporalClient()))

    await actions.perform("scan", by=actions.SYSTEM, project="demo")

    assert board.status_checked == "TO-DO"


async def test_scan_honours_a_declared_pickup_status_over_a_hardcoded_one(monkeypatch):
    """THE BUG: a literal `"TO-DO"` asked an Azure board (whose column is `"To Do"`, or whatever
    `pickup_status` names) for a column it does not have, and reported a correct-looking empty
    queue with cards actually waiting in it — `cli.py`'s `pickup` grew the same fix
    independently, the two sites having drifted apart. `pickup_status` here is set exactly the
    way an Azure DevOps project's registry entry declares it."""
    from openfactory.registry import ProjectRegistry

    project = _scan_project(pickup_status="To Do")
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: project)
    monkeypatch.setattr("openfactory.credentials.tracker_token", lambda: "tok")
    monkeypatch.setattr("openfactory.factory.resolve_box_image",
                        lambda *_a, **_kw: "openfactory-python")
    board = _FakeBoard([])
    monkeypatch.setattr("openfactory.adapters.board.build_board", lambda *_a, **_kw: board)
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect",
                        lambda: _AsyncReturns(_FakeTemporalClient()))

    await actions.perform("scan", by=actions.SYSTEM, project="demo")

    assert board.status_checked == "To Do"  # never the hardcoded "TO-DO"


async def test_scan_counts_the_floor_GLOBALLY_not_just_this_project(monkeypatch, _scan_env):
    """The floor is one agent token across the WHOLE deployment. Counting only this project's
    running workflows would let a manual scan launch a second job while another project's is
    still in flight — overrunning the one thing the floor exists to guarantee."""
    monkeypatch.setattr("openfactory.adapters.board.build_board", lambda *_a, **_kw: _FakeBoard(["9"]))
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect",
                        lambda: _AsyncReturns(_FakeTemporalClient(running=["openfactory-other-1"])))
    monkeypatch.setattr("openfactory.runtime.temporal.max_concurrent_jobs", lambda: 1)

    out = await actions.perform("scan", by=actions.SYSTEM, project="demo")

    assert out.data["started"] == [] and out.data["skipped"] == ["9"]  # the floor was full


async def test_scan_counts_an_already_started_ticket_against_the_floor(monkeypatch, _scan_env):
    """A concurrent scan or the poller may have already claimed a ticket between the TO-DO read
    and this one's launch attempt. Treating that `AlreadyStarted` as 'floor still free' and
    handing the slot to the NEXT ticket would overrun the floor on a race (F1)."""
    client = _FakeTemporalClient(fail_started={"1"})
    monkeypatch.setattr("openfactory.adapters.board.build_board",
                        lambda *_a, **_kw: _FakeBoard(["1", "2"]))
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", lambda: _AsyncReturns(client))
    monkeypatch.setattr("openfactory.runtime.temporal.max_concurrent_jobs", lambda: 1)

    out = await actions.perform("scan", by=actions.SYSTEM, project="demo")

    assert out.data["started"] == [] and out.data["skipped"] == ["1", "2"]
    assert client.launched == []  # ticket "2" never got a slot — "1" already claimed the only one


async def test_scan_starts_what_the_floor_allows(monkeypatch, _scan_env):
    client = _FakeTemporalClient()
    monkeypatch.setattr("openfactory.adapters.board.build_board",
                        lambda *_a, **_kw: _FakeBoard(["1", "2"]))
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", lambda: _AsyncReturns(client))
    monkeypatch.setattr("openfactory.runtime.temporal.max_concurrent_jobs", lambda: 5)

    out = await actions.perform("scan", by=actions.SYSTEM, project="demo")

    assert out.data["started"] == ["1", "2"] and out.ok is True
    assert [wf_id for wf_id, _ in client.launched] == ["openfactory-demo-1", "openfactory-demo-2"]


async def test_scan_reports_a_box_image_refusal_as_invalid_not_a_silent_200(monkeypatch, _scan_env):
    """NORMALISED ON THE MOVE. `scan_now` used to return 200 with the refusal folded into
    `message` — the one branch of that endpoint that did not raise, with no test pinning it.
    Every other `resolve_box_image` refusal in this codebase (`temporal_start`, `cli.poll`) is a
    400; this now matches them."""
    def _refuse(*_a, **_kw):
        raise ValueError("this box cannot honour box.image")

    monkeypatch.setattr("openfactory.adapters.board.build_board",
                        lambda *_a, **_kw: _FakeBoard(["1"]))
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect",
                        lambda: _AsyncReturns(_FakeTemporalClient()))
    monkeypatch.setattr("openfactory.factory.resolve_box_image", _refuse)

    out = await actions.perform("scan", by=actions.SYSTEM, project="demo")

    assert out.code == actions.INVALID and "box.image" in out.message


def test_the_panel_scan_route_maps_its_status_from_the_outcome_code(client, monkeypatch):
    """The end-to-end version of the normalisation above, through the real HTTP route."""
    from openfactory.registry import ProjectRegistry

    project = _scan_project(board_owner="", board_number="")
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: project)

    r = client.post("/api/projects/demo/scan", json={})

    assert r.status_code == 400 and "no board configured" in r.json()["detail"]


# ── start — behaviour, not just reachability ────────────────────────────────────────────────────
#
# `start` moved from TWO routes (`trigger_job`, `temporal_start`) that never shared a line of
# code despite answering the same request. These pin down the one thing that made merging them
# non-trivial: the local path gained the box.image pre-check the durable path always had, and the
# `promote` gap on the local path is asserted as PRESENT — a documented limitation, not something
# this move silently fixed or silently introduced.

def _start_project(**box_kw):
    from openfactory.contracts.project import Project, ProviderRef

    return Project(name="demo", repo_path="/tmp/demo-repo",
                   tracker=ProviderRef(kind="github", repo="o/demo"),
                   **({"box": box_kw} if box_kw else {}))


@pytest.fixture
def _start_env(monkeypatch, tmp_path):
    from openfactory.registry import ProjectRegistry

    project = _start_project()
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: project)
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    return project


async def test_start_launches_a_local_subprocess_by_default(monkeypatch, _start_env):
    calls = []
    monkeypatch.setattr("subprocess.Popen", lambda argv, **kw: calls.append((argv, kw)))

    out = await actions.perform("start", by=actions.SYSTEM, project="demo", issue="7")

    assert out.ok is True and out.data["durable"] is False
    (argv, _kw) = calls[0]
    # THE DEPLOYMENT'S BOX, not a literal. This asserted `worktree` — "trigger_job's own default"
    # — which is the box that isolates the code state and nothing else, handed to every caller
    # who did not name one while `OPENFACTORY_SANDBOX` sat in the compose file being read by the durable
    # path alone. `_start_env` sets no Fargate cluster, so `default_sandbox()` infers the local
    # container.
    assert argv[-5:] == ["run", "demo", "7", "--sandbox", "container"]


async def test_start_creates_the_log_file_before_launching(monkeypatch, _start_env, tmp_path):
    monkeypatch.setattr("subprocess.Popen", lambda argv, **kw: None)

    await actions.perform("start", by=actions.SYSTEM, project="demo", issue="7", sandbox="worktree")

    assert (tmp_path / "logs" / "demo" / "7-run.log").exists()


async def test_start_refuses_a_box_image_the_local_sandbox_cannot_honour(monkeypatch):
    """The gap the move fixed: `trigger_job` never validated `box.image` before spawning the
    subprocess, so a bad declaration failed silently minutes later in a log file nobody was
    watching yet. Every other launch path (`temporal_start`, `scan`, `cli.poll`) already refuses
    up front; the local path was the one exempted by omission."""
    from openfactory.registry import ProjectRegistry

    project = _start_project(image="ghcr.io/acme/custom:1")
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: project)
    launched = []
    monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: launched.append(1))

    out = await actions.perform("start", by=actions.SYSTEM, project="demo", issue="7",
                                sandbox="worktree")

    assert out.code == actions.INVALID and "box.image" in out.message
    assert launched == []  # refused before anything was spawned


async def test_start_local_ignores_promote_a_documented_pre_existing_gap(monkeypatch, _start_env):
    """NOT a regression: `sdlc run` has no `--promote` flag and never did. `trigger_job` accepted
    `promote=True` and silently dropped it; this asserts that limitation survives the move rather
    than being fixed (or worsened) by accident."""
    calls = []
    monkeypatch.setattr("subprocess.Popen", lambda argv, **kw: calls.append(argv))

    out = await actions.perform("start", by=actions.SYSTEM, project="demo", issue="7",
                                promote=True)

    assert out.ok is True
    assert not any("promote" in str(a) for a in calls[0])  # never reaches the subprocess argv


async def test_start_durable_refuses_a_box_that_bounds_only_the_code_state(monkeypatch,
                                                                             _start_env):
    """IT USED TO SAY "only accepts fargate", and that was a vendor name standing in for a rule.

    A durable job runs an agent ON THE WORKER, so its box has to bound something — CPU, memory,
    network, secrets. `worktree` bounds the code state and nothing else; its own registry entry
    says "never for untrusted work". Fargate satisfies that, and so does the local container,
    which is what the OSS compose file runs — and under the old rule a compose install could not
    start a durable job at all, so the human merge gate, park/resume and every deadline existed
    only on our own cloud. Found by trying it on one."""
    out = await actions.perform("start", by=actions.SYSTEM, project="demo", issue="7",
                                durable=True, sandbox="worktree")

    assert out.code == actions.INVALID
    assert "worktree" in out.message and "code state" in out.message, out.message
    # …and the refusal never names a vendor, or the rule is a coincidence again
    assert "fargate" not in out.message.lower(), out.message


async def test_start_durable_accepts_the_box_the_OSS_DISTRIBUTION_runs(monkeypatch, _start_env):
    """The positive twin, and the one the old rule failed. `container` is what
    `docker-compose.yml` sets, under a comment calling it "the real, production path"."""
    client = _FakeTemporalClient()
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", lambda: _AsyncReturns(client))
    monkeypatch.setattr("openfactory.factory.resolve_box_image", lambda *_a, **_kw: "openfactory-python")

    out = await actions.perform("start", by=actions.SYSTEM, project="demo", issue="7",
                                durable=True, sandbox="container")

    assert out.ok is True, out.message
    (_wf_id, params) = client.launched[0]
    assert params.sandbox == "container"


async def test_start_durable_launches_through_the_engine(monkeypatch, _start_env):
    client = _FakeTemporalClient()
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", lambda: _AsyncReturns(client))
    monkeypatch.setattr("openfactory.factory.resolve_box_image", lambda *_a, **_kw: "openfactory-python")

    out = await actions.perform("start", by=actions.SYSTEM, project="demo", issue="7",
                                durable=True, sandbox="fargate", promote=True)

    assert out.ok is True and out.data["workflow_id"] == "openfactory-demo-7"
    (wf_id, params) = client.launched[0]
    assert wf_id == "openfactory-demo-7" and params.promote is True and params.sandbox == "fargate"


async def test_start_durable_reports_an_already_running_job_as_conflict(monkeypatch, _start_env):
    client = _FakeTemporalClient(fail_started={"7"})
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", lambda: _AsyncReturns(client))
    monkeypatch.setattr("openfactory.factory.resolve_box_image", lambda *_a, **_kw: "openfactory-python")

    out = await actions.perform("start", by=actions.SYSTEM, project="demo", issue="7",
                                durable=True, sandbox="fargate")

    assert out.code == actions.CONFLICT


async def test_start_durable_reports_an_unreachable_engine(monkeypatch, _start_env):
    def _boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", _boom)

    out = await actions.perform("start", by=actions.SYSTEM, project="demo", issue="7",
                                durable=True, sandbox="fargate")

    assert out.code == actions.UNAVAILABLE


def test_the_panel_local_start_route_maps_to_start(client, monkeypatch, tmp_path):
    from openfactory.registry import ProjectRegistry

    project = _start_project()
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: project)
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: None)

    r = client.post("/api/jobs", json={"project": "demo", "issue": "#7"})

    assert r.status_code == 200 and r.json()["issue"] == "7"  # the '#' is stripped, once


def test_the_panel_durable_start_route_maps_to_start(client, monkeypatch):
    client_stub = _FakeTemporalClient()
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect",
                        lambda: _AsyncReturns(client_stub))
    monkeypatch.setattr("openfactory.factory.resolve_box_image", lambda *_a, **_kw: "openfactory-python")
    from openfactory.registry import ProjectRegistry

    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _start_project())

    r = client.post("/api/temporal/jobs",
                    json={"project": "demo", "issue": "7", "sandbox": "fargate"})

    assert r.status_code == 200 and r.json()["workflow_id"] == "openfactory-demo-7"


def test_the_panel_durable_start_route_still_refuses_non_fargate(client, monkeypatch):
    from openfactory.registry import ProjectRegistry

    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _start_project())

    r = client.post("/api/temporal/jobs",
                    json={"project": "demo", "issue": "7", "sandbox": "worktree"})

    assert r.status_code == 400


# ── approve_prod / promote — behaviour, not just reachability ──────────────────────────────────
#
# `tests/test_panel_approval_store.py` already exercises `approve_prod`'s cloud allowlist cascade
# end-to-end through the real route (it passed unchanged through this move — the strongest
# evidence the mapping preserves behaviour). These fill the gaps THAT file does not cover: the
# not-parked / engine-down paths for approve_prod, and `promote` itself, which had NO test
# coverage at all before this move (`test_promotion.py` tests `PromotionRunner` directly, never
# the route that builds and calls one).

def _release_manifest(**kw):
    from openfactory.contracts.manifest import Manifest

    return Manifest(prod_approvers=["alice"], **kw)


async def test_approve_prod_signals_the_parked_workflow(monkeypatch, _start_env):
    from openfactory.actions import catalog

    monkeypatch.setattr(catalog, "_prod_allowlist", lambda project: ["alice"])
    monkeypatch.setattr("openfactory.approvals.verify_approver", lambda *a, **kw: True)
    signalled = []

    async def _approve_job(client, project, issue, **kw):
        signalled.append((project, issue, kw))

    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", lambda: _AsyncReturns(object()))
    monkeypatch.setattr("openfactory.runtime.temporal.view.approve_job", _approve_job)

    out = await actions.perform("approve_prod", by=actions.SYSTEM, project="demo", issue="7",
                                version="1.2.0", approver="alice", password="s3cret",
                                comment="ok")

    assert out.ok is True and out.data["signaled"] is True
    assert signalled == [("demo", "7", {"version": "1.2.0", "approver": "alice",
                                        "comment": "ok"})]


async def test_approve_prod_reports_not_parked_as_conflict(monkeypatch, _start_env):
    from openfactory.actions import catalog

    monkeypatch.setattr(catalog, "_prod_allowlist", lambda project: ["alice"])
    monkeypatch.setattr("openfactory.approvals.verify_approver", lambda *a, **kw: True)
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", lambda: _AsyncReturns(object()))

    async def _approve_job(*_a, **_kw):
        raise RuntimeError("job is not parked awaiting prod approval")

    monkeypatch.setattr("openfactory.runtime.temporal.view.approve_job", _approve_job)

    out = await actions.perform("approve_prod", by=actions.SYSTEM, project="demo", issue="7",
                                version="1.2.0", approver="alice", password="s3cret")

    assert out.code == actions.CONFLICT and "not parked" in out.message


async def test_approve_prod_reports_an_unreachable_engine(monkeypatch, _start_env):
    from openfactory.actions import catalog

    monkeypatch.setattr(catalog, "_prod_allowlist", lambda project: ["alice"])
    monkeypatch.setattr("openfactory.approvals.verify_approver", lambda *a, **kw: True)

    def _boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", _boom)

    out = await actions.perform("approve_prod", by=actions.SYSTEM, project="demo", issue="7",
                                version="1.2.0", approver="alice", password="s3cret")

    assert out.code == actions.UNAVAILABLE


async def test_approve_prod_denies_a_bad_password(monkeypatch, _start_env):
    from openfactory.actions import catalog

    monkeypatch.setattr(catalog, "_prod_allowlist", lambda project: ["alice"])
    monkeypatch.setattr("openfactory.approvals.verify_approver", lambda *a, **kw: False)
    monkeypatch.setattr("openfactory.approvals.list_approvers", lambda: ["alice"])  # store IS present

    out = await actions.perform("approve_prod", by=actions.SYSTEM, project="demo", issue="7",
                                version="1.2.0", approver="alice", password="wrong")

    assert out.code == actions.DENIED  # a present store + wrong password = DENIED, not UNAVAILABLE


async def test_promote_denies_a_bad_password_before_touching_the_runner(monkeypatch):
    from openfactory.actions import catalog

    monkeypatch.setattr(catalog, "_forge_and_manifest",
                        lambda name: (object(), _release_manifest(), object()))
    monkeypatch.setattr("openfactory.approvals.verify_approver", lambda *a, **kw: False)
    monkeypatch.setattr("openfactory.approvals.list_approvers", lambda: ["alice"])
    built = []
    monkeypatch.setattr("openfactory.orchestrator.promotion.PromotionRunner",
                        lambda **kw: built.append(kw) or object())

    out = await actions.perform("promote", by=actions.SYSTEM, project="demo", issue="7",
                                version="1.2.0", approver="alice", password="wrong")

    assert out.code == actions.DENIED and built == []


async def test_promote_runs_the_release_and_reports_its_state(monkeypatch, tmp_path):
    from openfactory.actions import catalog

    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path))
    manifest = _release_manifest()
    monkeypatch.setattr(catalog, "_forge_and_manifest",
                        lambda name: (_start_project(), manifest, "the-forge-object"))
    monkeypatch.setattr("openfactory.approvals.verify_approver", lambda *a, **kw: True)
    monkeypatch.setattr("openfactory.adapters.github_app.token_from_env", lambda: "tok")
    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda project, **kw: "the-tracker")
    monkeypatch.setattr("openfactory.adapters.environment.registry.build_observer",
                        lambda project, **kw: "the-observer")

    class _Result:
        class _State:
            value = "done"
        state = _State()
        note = "live in production"

    released = []

    class _FakeRunner:
        def __init__(self, **kw):
            self.kw = kw

        def release_prod(self, ref, *, version, approver, comment):
            released.append((ref, version, approver, comment))
            return _Result()

    monkeypatch.setattr("openfactory.orchestrator.promotion.PromotionRunner", _FakeRunner)

    out = await actions.perform("promote", by=actions.SYSTEM, project="demo", issue="#7",
                                version="1.2.0", approver="alice", password="s3cret",
                                comment="go")

    assert out.ok is True
    assert out.data["state"] == "done" and out.data["note"] == "live in production"
    assert released == [("#7", "1.2.0", "alice", "go")]  # the '#' survives — release_prod's own


def test_the_panel_approve_route_maps_to_approve_prod(client, monkeypatch):
    from openfactory.actions import catalog
    from openfactory.registry import ProjectRegistry

    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _start_project())
    monkeypatch.setattr(catalog, "_prod_allowlist", lambda project: ["alice"])
    monkeypatch.setattr("openfactory.approvals.verify_approver", lambda *a, **kw: True)
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", lambda: _AsyncReturns(object()))

    async def _approve_job(*_a, **_kw):
        return None

    monkeypatch.setattr("openfactory.runtime.temporal.view.approve_job", _approve_job)

    r = client.post("/api/temporal/approve/demo/7",
                    json={"approver": "alice", "password": "s3cret", "version": "1.2.0"})

    assert r.status_code == 200 and r.json()["signaled"] is True


def test_the_panel_promote_route_maps_to_promote(client, monkeypatch, tmp_path):
    from openfactory.actions import catalog

    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(catalog, "_forge_and_manifest",
                        lambda name: (_start_project(), _release_manifest(), object()))
    monkeypatch.setattr("openfactory.approvals.verify_approver", lambda *a, **kw: True)
    monkeypatch.setattr("openfactory.adapters.github_app.token_from_env", lambda: "tok")
    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda project, **kw: "the-tracker")
    monkeypatch.setattr("openfactory.adapters.environment.registry.build_observer",
                        lambda project, **kw: "the-observer")

    class _Result:
        class _State:
            value = "done"
        state = _State()
        note = "ok"

    monkeypatch.setattr("openfactory.orchestrator.promotion.PromotionRunner",
                        lambda **kw: type("_R", (), {"release_prod": lambda *a, **k: _Result()})())

    r = client.post("/api/promote/demo/7",
                    json={"approver": "alice", "password": "s3cret", "version": "1.2.0"})

    assert r.status_code == 200 and r.json()["state"] == "done"


# ── merge / adjust / discard — the human-gated PR becomes answerable (#68, C-32) ────────────────
#
# BEFORE THESE ROWS THE GATE COULD NOT BE ANSWERED AT ALL, and that is the fact worth holding on
# to. With `merge_policy: human` the workflow stays alive in its merge watch for up to fourteen
# days, but `_paused` is never set — so `awaiting_action` is None, `act_job` refuses before
# signalling, and resume/skip both come back CONFLICT. The human path cannot self-heal either: the
# one branch that merges a clean PR is gated on `auto_merge`, False precisely when a human is the
# gate. A green, reviewed, human-gated PR had two exits: github.com, or fourteen days.

@pytest.fixture
def _gate(monkeypatch):
    """The engine, with a merge gate open. Returns the list of signals it received."""
    from openfactory.registry import ProjectRegistry

    sent: list[dict] = []
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _start_project())
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect",
                        lambda: _AsyncReturns(object()))

    async def _answer(client, project, issue, *, answer, instruction="", by=""):
        sent.append({"project": project, "issue": issue, "answer": answer,
                     "instruction": instruction, "by": by})
        return {"pr_url": "https://github.com/o/demo/pull/9", "auto": False}

    monkeypatch.setattr("openfactory.runtime.temporal.view.answer_merge_gate", _answer)
    return sent


async def test_merge_signals_the_gate_and_never_claims_it_landed(_gate):
    """`merge_pr` reports refusal by RETURNING FALSE, not raising, so the only honest thing this
    can say is that the factory is landing it. Claiming 'merged' would be the platform telling
    somebody it acted when the forge may yet refuse."""
    out = await actions.perform("merge", by=actions.SYSTEM, project="demo", issue="7")

    assert out.ok is True and out.data["answer"] == "merge"
    assert _gate == [{"project": "demo", "issue": "7", "answer": "merge",
                      "instruction": "", "by": str(actions.SYSTEM)}]
    assert "merged" not in out.message.lower() or "merging" in out.message.lower()


async def test_adjust_carries_the_humans_words_verbatim(_gate):
    """Free text — the decided design. It is a signal PARAMETER rather than a DecisionRequest
    option key precisely because a key is matched against a fixed list at both consumption sites
    and anything unmatched is silently dropped: free text would arrive and then vanish."""
    out = await actions.perform("adjust", by=actions.SYSTEM, project="demo", issue="7",
                                instruction="  the button should be on the right  ")

    assert out.ok is True
    assert _gate[0]["instruction"] == "the button should be on the right"  # stripped, not mangled


@pytest.mark.parametrize("blank", ["   ", "\n\t "])
async def test_a_whitespace_only_instruction_is_refused_and_signals_nothing(blank, _gate):
    """NOT REDUNDANT with `perform`'s required-parameter check: its emptiness test is
    `in (None, "")`, so `"   "` passes it and would reach an agent as an instruction to do nothing
    in particular, at full price and holding the floor."""
    out = await actions.perform("adjust", by=actions.SYSTEM, project="demo", issue="7",
                                instruction=blank)

    assert out.code == actions.INVALID and _gate == []


async def test_an_enormous_instruction_is_refused(_gate):
    """It becomes an agent's prompt at the same trust level as the ticket body, and lands verbatim
    in an audit line that masks by key name and truncates nothing."""
    out = await actions.perform("adjust", by=actions.SYSTEM, project="demo", issue="7",
                                instruction="x" * 5000)

    assert out.code == actions.INVALID and "2000" in out.message and _gate == []


async def test_the_confirmation_says_HOW_MUCH_it_received(_gate):
    """MEASURED ON THE PILOT (#150). A pasted paragraph reached this action as its last twenty-six
    characters — `prompt()` is a single-line control and a multi-line paste is at the browser's
    mercy. The platform CANNOT detect that: twenty-six characters is a legitimate instruction.

    What it can do is say the number. The echo was a 120-character prefix, which reads identically
    whether it is a whole short instruction or the head of a mangled long one; the operator, who
    knows what they typed, is the only one who can tell — and only if told the size.

    Asserted on both sides of the truncation so the number cannot come from the echo itself."""
    long = ("make it idempotent. " * 30).strip()   # stripped like the action does; echo truncates
    out = await actions.perform("adjust", by=actions.SYSTEM, project="demo", issue="7",
                                instruction=long)
    assert out.ok is True
    assert f"({len(long)} characters)" in out.message, out.message
    assert "…" in out.message, "a truncated echo must still announce itself as one"

    short = "add a test for the empty case"                          # echo carries all of it
    out = await actions.perform("adjust", by=actions.SYSTEM, project="demo", issue="7",
                                instruction=short)
    assert f"({len(short)} characters)" in out.message, out.message
    assert "…" not in out.message, "nothing was cut, so nothing may claim it was"


async def test_discard_says_that_nothing_is_deleted(_gate):
    """The word promises more destruction than the operation performs: `gh pr close` leaves the
    branch and its commits, which is exactly why this needs no password gate."""
    out = await actions.perform("discard", by=actions.SYSTEM, project="demo", issue="7")

    assert out.ok is True and out.data["freed"] is True
    assert "untouched" in out.message or "branch" in out.message


async def test_a_job_not_at_the_merge_gate_is_a_CONFLICT(monkeypatch):
    """Already merged, closed, or never opened a PR. The engine is asked before anything is sent —
    a signal is fire-and-forget, so without the query a stale answer would be reported as done."""
    from openfactory.registry import ProjectRegistry

    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _start_project())
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", lambda: _AsyncReturns(object()))

    async def _refuse(*_a, **_kw):
        raise RuntimeError("this job is not waiting on a merge")

    monkeypatch.setattr("openfactory.runtime.temporal.view.answer_merge_gate", _refuse)

    out = await actions.perform("merge", by=actions.SYSTEM, project="demo", issue="7")

    assert out.code == actions.CONFLICT


def test_the_panel_offers_the_three_answers_as_options_not_prose(client, monkeypatch):
    """THE HUMAN-REACHED END. `/api/inbox` used to answer a merge wait with
    {"how": "review + merge the PR, then it lands on its own"} — true, useless, and pointing at
    github.com, which is the work this product exists to remove. Without this the three rows are
    reachable by two transports and by no person, which IS the card."""
    from openfactory.runtime.temporal import view as tv

    monkeypatch.setattr(tv, "connect", lambda: _AsyncReturns(object()))
    monkeypatch.setattr(tv, "temporal_config", lambda: ("localhost:7233", "default"))

    async def _jobs(_client, _ns):
        return [{"project": "demo", "issue": "7", "title": "t", "state": "awaiting_your_merge",
                 "action": {"pr_url": "https://github.com/o/demo/pull/9", "auto": False}}]

    monkeypatch.setattr(tv, "list_jobs", _jobs)

    row = next(r for r in client.get("/api/inbox").json() if r["kind"] == "merge")

    assert [o["key"] for o in row["options"]] == ["merge", "adjust", "discard"]
    assert next(o for o in row["options"] if o["key"] == "adjust")["needs_text"] is True
    assert all(o["consequence"] for o in row["options"]), "an option without a consequence is a dare"


def test_merge_is_kept_out_of_the_operator_channel():
    """A merge is not a production release, and the two must not blur. The Slack allow-list is
    pinned by value elsewhere; this asserts the new rows did not sneak into it — and the reason
    is structural as well as policy: `act_job` passes only project+issue, so it has no channel to
    carry `adjust`'s free text, and offering merge without adjust would be half a gate."""
    _SLACK_MAY = add_ons.module("openfactory.runtime.slack.bot")._SLACK_MAY

    assert _SLACK_MAY == ("resume", "skip", "ack")
    for row in ("merge", "adjust", "discard"):
        assert row not in _SLACK_MAY


def test_the_merge_rows_never_touch_the_release_machinery():
    """The negative guard. A production release re-checks a person's own password against the
    approver store; a merge deliberately does not, and the line between them is the one thing
    ADR-0026 and test_the_client_releases_production.py exist to keep sharp."""
    import ast

    tree = ast.parse(Path("openfactory/actions/catalog.py").read_text())
    forbidden = {"verify_approver", "approve_job", "PromotionRunner", "release_prod",
                 "_prod_allowlist", "_approval_denied"}
    for name in ("_merge", "_adjust", "_discard", "_answer_gate"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == name)
        used = {getattr(n, "id", None) or getattr(n, "attr", "") for n in ast.walk(fn)}
        assert not (used & forbidden), f"{name} reaches the release machinery: {used & forbidden}"


def test_the_release_rows_still_DO_touch_it():
    """The positive twin. 'The merge rows do not check a password' is satisfied just as well by
    NOTHING checking a password — an outage reading as compliance, which is the exact shape this
    repository keeps recording."""
    import ast

    tree = ast.parse(Path("openfactory/actions/catalog.py").read_text())
    for name in ("_approve_prod", "_promote"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == name)
        used = {getattr(n, "id", None) or getattr(n, "attr", "") for n in ast.walk(fn)}
        assert "verify_approver" in used, f"{name} no longer checks the approver's password"


# ── diagnose — the last row to move, and the layer gap it closes ─────────────────────────────────
#
# Diagnosing lived inside `activities._do_diagnose`, reachable only from the impediment path a
# workflow takes on its way to parking. So the tech-lead could explain a failure the moment it
# happened and NEVER AGAIN: a human looking at a job that parked yesterday had nowhere to ask,
# which is the layer humans were staffing by hand (`openfactory-tech-lead-layer-gap`).

def _parked_floor(monkeypatch, jobs):
    from openfactory.registry import ProjectRegistry

    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _start_project())
    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", lambda: _AsyncReturns(object()))

    async def _jobs(_client, _ns, **_kw):
        return jobs

    monkeypatch.setattr("openfactory.runtime.temporal.view.list_jobs", _jobs)


class _HandOff:
    headline = "the gates cannot pass without a fixture"
    def __str__(self) -> str:  # noqa: D105
        return self.headline


async def test_diagnose_produces_an_analysis_and_publishes_NOTHING(monkeypatch):
    """THE SPLIT THAT MADE THIS MOVABLE. The impediment path posts a ticket comment and a channel
    notice because nobody is watching a job that just parked. An operator asking IS watching, and
    a duplicate comment per question is how a ticket becomes unreadable."""
    _parked_floor(monkeypatch, [{"project": "demo", "issue": "412", "state": "on_hold",
                                 "attention": True, "action": {"note": "gates failed"}}])
    seen = {}

    def _diagnose(project, *, issue, state, note, tracker=None):
        seen.update(project=project.name, issue=issue, state=state, note=note)
        return _HandOff()

    monkeypatch.setattr("openfactory.techlead.diagnosis.diagnose", _diagnose)
    monkeypatch.setattr("openfactory.contracts.handoff_to_plain",
                        lambda ho, ref="": f"analysis: {ho.headline}")

    # "publishes NOTHING" is asserted, not implied (adversarial review): the publish paths are
    # armed to explode, so a regression that starts posting a ticket comment or a channel notice
    # on every operator question fails HERE rather than flooding a real ticket.
    def _no_publish(*_a, **_kw):
        raise AssertionError("the diagnose ACTION published — that is the impediment path's job")

    monkeypatch.setattr("openfactory.factory.notifier_for_project", _no_publish)
    monkeypatch.setattr("openfactory.runtime.temporal.activities._tracker_for", _no_publish)

    out = await actions.perform("diagnose", by=actions.SYSTEM, project="demo", issue="#412")

    assert out.ok, out.message
    assert seen == {"project": "demo", "issue": "412", "state": "on_hold", "note": "gates failed"}
    assert "the gates cannot pass" in out.message
    assert out.data["headline"] == "the gates cannot pass without a fixture"


async def test_diagnosing_a_job_that_is_NOT_parked_is_refused_before_it_costs_anything(monkeypatch):
    """An agent pass plus a repository clone, to explain a problem that does not exist yet."""
    _parked_floor(monkeypatch, [{"project": "demo", "issue": "412", "state": "running",
                                 "attention": False, "action": {}}])

    def _never(*_a, **_kw):
        raise AssertionError("it spent an agent pass on a running job")

    monkeypatch.setattr("openfactory.techlead.diagnosis.diagnose", _never)

    out = await actions.perform("diagnose", by=actions.SYSTEM, project="demo", issue="412")

    assert out.code == actions.CONFLICT
    assert "not waiting on anybody" in out.message


async def test_a_job_the_floor_does_not_have_is_NOT_FOUND(monkeypatch):
    _parked_floor(monkeypatch, [])

    out = await actions.perform("diagnose", by=actions.SYSTEM, project="demo", issue="412")

    assert out.code == actions.NOT_FOUND


async def test_an_unreadable_diagnosis_still_hands_back_the_RAW_NOTE(monkeypatch):
    """The raw `[state]` note from `mark_needs_action` stands whatever happens here, so the person
    is never left with nothing — the rule the impediment path has always followed, kept."""
    _parked_floor(monkeypatch, [{"project": "demo", "issue": "412", "state": "on_hold",
                                 "attention": True,
                                 "action": {"note": "TypeError in the importer"}}])
    monkeypatch.setattr("openfactory.techlead.diagnosis.diagnose", lambda *a, **kw: None)

    out = await actions.perform("diagnose", by=actions.SYSTEM, project="demo", issue="412")

    assert out.code == actions.FAILED
    assert "TypeError in the importer" in out.message


def test_the_panel_offers_somewhere_to_ASK_the_tech_lead():
    """The product owner, 2026-08-05: "I still have not managed to see any tech-lead chat
    happening on the panel". That was right twice over: the backend existed, no front end offered
    it, and when reached it ran in the panel's own credential-less process. This guards the UI half — the
    backend half is the dispatch tests above."""
    from pathlib import Path

    html = Path("openfactory/api/panel.html").read_text()

    assert "askTechlead" in html, "the panel has nowhere to type a question again"
    assert "/api/act/ask" in html, "the ask box does not reach the action layer"
    assert "chatfab" in html, ("the chat lost its floating widget — the product owner's call: a box "
                              "in the middle of the page is terrible")
    assert "answerQuestion" in html and "opts" in html, (
        "the platform's OWN questions (parks, needs-action) must render inside the chat with "
        "their executable options — proactive, like Slack; Slack is only a transport")
    assert "badge" in html, "an impediment waiting on a human must be visible from the closed fab"
