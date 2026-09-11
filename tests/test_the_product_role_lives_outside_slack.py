"""The product role is reachable with no Slack anywhere. The test #98 wrote for itself.

    *"if the person wants to write the tickets and drop them in TO-DO, fine — but the product role
    is available ON THE PLATFORM, not in Slack"* — the product owner, 2026-08-06, settling the
    core/add-on boundary.

ADR-0038 already said it (the panel is the reference surface, a channel is a transport) and
ADR-0040 recorded it. Both were true as decisions and FALSE AS CODE, measured when the card opened:

    openfactory/runtime/slack/product_channel.py     2,165 lines, 54 functions
    openfactory/actions/catalog.py, product rows     0
    openfactory/api/app.py, product routes           0

So on a deployment without Slack the role swept and reconciled on a schedule and nobody could talk
to it — no way to propose a requirement, accept it, drop it or ask it anything.

WHAT THIS FILE DOES NOT CLAIM. The conversation handler moved to `product/channel.py` on
2026-08-25 — it is an implementation, and it is now filed where implementations live; its
pre-conversation stage (`settle`) is what the panel's turn shares with the chat handler, guarded in
`test_the_product_conversation_is_core.py`. What is still open is the PO's own SURFACE — a separate
page with a separate authorization scope, for a BA who has no access to the jobs dashboard — and
the ten typed write-intents `_run_intent` dispatches beside the catalogue's four (E6, in the core
now rather than in a channel). What is asserted here is narrower and is the half that unblocks the
rest: the verbs exist on the transport-neutral layer, and nothing on the way to them touches Slack.
"""

from __future__ import annotations

import ast
import copy
import pathlib
import re
import subprocess
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Captured at import so a monkeypatched test always restores the real resolver, even on failure.
from openfactory.actions.catalog import _product_module as _REAL_PRODUCT_MODULE  # noqa: E402

PRODUCT_ACTIONS = ("product_status", "product_requirements", "product_ask",
                   "product_propose", "product_accept", "product_drop")


def _actor():
    from openfactory.actions.base import Actor

    return Actor(id="t", display="t", admin=True)


def _drafted():
    """A `ProductAnswer` shaped exactly as `product_ask` returns one that carries a requirement."""
    from openfactory.product.role import ProductAnswer, RequirementDraft

    return ProductAnswer(ok=True, text="proposta", is_request=True,
                         draft=RequirementDraft(title="Relatório mensal",
                                                body="O cliente precisa de um fechamento."))


class _FakeModule:
    """Records what it was asked to do and answers success. Deliberately NOT a refusing double:
    the branches under test are the ACTION's, and a module that said no to everything would make
    every assertion below pass for the module's reason instead of the row's."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def _ok(self, *args):
        from openfactory.product.authoring import WriteResult

        self.calls.append(args)
        return WriteResult(ok=True, ref="REQ-0007", url="https://example/pr/1")

    def propose(self, answer, **_kw):
        return self._ok("propose", answer)

    def accept(self, number, **_kw):
        return self._ok("accept", number)

    def drop(self, number, **_kw):
        return self._ok("drop", number)

    # THE SIX WRITE VERBS ANSWER SUCCESS TOO, and that is what makes the consent guard mean
    # something. A fake missing them fails a consent mutation with `AttributeError` — red, but
    # for the wrong reason, and green again the day somebody adds the method. With them here,
    # deleting a `_said_yes` makes the row SUCCEED, which is exactly what the guard asserts
    # against.
    def close_card(self, number, **_kw):
        return self._ok("close_card", number)

    def record_decision(self, number, **_kw):
        return self._ok("record_decision", number)

    def note_fact(self, **kw):
        return self._ok("note_fact", kw.get("term"))

    def file_defect(self, **kw):
        return self._ok("file_defect", kw.get("restated"))


@pytest.fixture
def resolvable_product(monkeypatch):
    """A project the rows can resolve, so the branch under test is reached at all."""
    from openfactory.actions import catalog

    module = _FakeModule()
    # `language` on the stand-in: without it the voice falls back to the platform default,
    # which is English since 2026-08-14 while these assertions are Portuguese
    project = type("_P", (), {"name": "acme", "language": "pt-BR"})()
    monkeypatch.setattr(catalog, "_product_module",
                        lambda _n, **_kw: (module, project, None))
    return module


def test_the_verbs_exist_on_the_transport_neutral_layer():
    from openfactory import actions

    missing = [name for name in PRODUCT_ACTIONS if name not in actions.CATALOG]
    assert not missing, (
        f"the product role has no {missing} action — a deployment without Slack can still only "
        f"sweep and reconcile, which is the state this card was opened about"
    )


def test_the_card_s_OWN_acceptance_test_propose_accept_and_the_card_appears():
    """*"A deployment without `slack_sdk` can propose a requirement, accept it, and see the card
    born on the board."* — #98, stating its own definition of done.

    THE SIBLING BELOW ASSERTS THE ROWS RESOLVE; THIS ONE ASSERTS THE CHAIN RUNS. That difference
    is the whole reason this exists: for most of this card's life the acceptance criterion was
    checked at the level of "the verbs are in the catalogue", which was true while the last third
    of the sentence was unreachable — `ProductModule.accept` wrote the agreement and stopped, and
    the accept→`break_down` chain lived only in the Slack package. A criterion asserted one level
    above the behaviour it describes is how a card closes over a gap.

    IN A SUBPROCESS WITH SLACK BLOCKED, because that is the only way the claim cannot lie. The
    module, the engine and the board are doubled — what is under test is the CHAIN, not a client's
    forge — but everything between them is the real action layer, and a module-scope import of the
    Slack package anywhere on that path fails here and passes every other test in this repository.
    """
    probe = textwrap.dedent("""
        import asyncio, builtins
        real = builtins.__import__
        def guarded(name, *a, **k):
            if name.split(".")[0] == "slack_sdk" or name.startswith("openfactory.runtime.slack"):
                raise ImportError(f"{name} is not installed on this deployment")
            return real(name, *a, **k)
        builtins.__import__ = guarded

        from openfactory.actions import catalog
        from openfactory.actions.base import Actor
        from openfactory.product.authoring import WriteResult
        from openfactory.product.role import ProductAnswer, RequirementDraft

        project = type("_P", (), {"name": "acme", "language": "pt-BR"})()

        class _Module:
            def propose(self, answer, **_kw):
                return WriteResult(ok=True, ref="REQ-0007", url="https://example/pr/1")
            def accept(self, number, **_kw):
                return WriteResult(ok=True, ref="REQ-0007")

        catalog._product_module = lambda _n, **_kw: (_Module(), project, None)

        # The engine, doubled: the breakdown runs on the worker (it spends an agent), so what is
        # asserted here is that accepting DISPATCHES it and reports what came back.
        class _Client:
            async def execute_workflow(self, name, inp, **_kw):
                assert name == "ProductBreakdownWorkflow", name
                return [{"ok": True, "ref": "acme#41", "detail": "", "url": "", "existed": False}]

        async def _connected():
            return _Client(), None

        catalog._connected = _connected
        who = Actor(id="bia", display="Bia Rocha", via="api", admin=True)

        async def main():
            drafted = ProductAnswer(ok=True, text="proposta", is_request=True,
                                    draft=RequirementDraft(title="Fechamento mensal",
                                                           body="O cliente precisa de um fechamento."))
            proposed = await catalog._product_propose(
                project="acme", by=who, answer=drafted.model_dump(mode="json"), yes=True)
            assert proposed.ok, f"propose: {proposed.message}"

            accepted = await catalog._product_accept(
                project="acme", number="7", by=who, yes=True)
            assert accepted.ok, f"accept: {accepted.message}"
            # THE THIRD OF THE SENTENCE, and the part that was unreachable: the card on the board.
            assert "acme#41" in accepted.message, f"no card was filed: {accepted.message}"
            print("OK")

        asyncio.run(main())
    """)
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=180)
    assert done.returncode == 0 and "OK" in done.stdout, (
        "the card's own acceptance test does not run without Slack:\n" + done.stderr[-2500:]
    )


def test_the_whole_path_runs_with_slack_BLOCKED():
    """The rows RESOLVE with Slack blocked — the reachability half, kept beside the behavioural
    one above because they fail for different reasons: this one catches a module-scope import,
    that one catches a chain that stops short.

    Importing `openfactory.actions` and resolving each product row inside a subprocess where `slack_sdk`
    and the Slack package itself raise on import. A module-scope import anywhere on that path —
    the exact shape of the coupling being removed — fails here and passes every other test.
    """
    probe = textwrap.dedent("""
        import builtins
        real = builtins.__import__
        def guarded(name, *a, **k):
            if name.split(".")[0] == "slack_sdk" or name.startswith("openfactory.runtime.slack"):
                raise ImportError(f"{name} is not installed on this deployment")
            return real(name, *a, **k)
        builtins.__import__ = guarded

        from openfactory import actions
        rows = [actions.CATALOG[n] for n in
                ("product_status", "product_ask", "product_propose", "product_accept",
                 "product_drop")]
        assert all(r.run is not None for r in rows), rows

        # The module the rows delegate to, imported for real — this is the half that would drag
        # the channel in if the logic still lived beside it.
        from openfactory.product.module import ProductModule   # noqa: F401
        from openfactory.product.role import ProductAnswer     # noqa: F401
        print("OK")
    """)
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=180)
    assert done.returncode == 0 and "OK" in done.stdout, (
        "the product role cannot be reached without Slack:\n" + done.stderr[-1800:]
    )


def test_this_guard_can_SEE_a_slack_import(tmp_path):
    """The positive twin. A blocker that had stopped blocking would report a clean tree.

    Absence reads as compliance, and that is how three guards in this repository stayed green over
    live defects.
    """
    probe = textwrap.dedent("""
        import builtins
        real = builtins.__import__
        def guarded(name, *a, **k):
            if name.split(".")[0] == "slack_sdk":
                raise ImportError("blocked")
            return real(name, *a, **k)
        builtins.__import__ = guarded
        import slack_sdk
        print("OK")
    """)
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=60)
    assert done.returncode != 0, "the import blocker does not block the import it is given"


def _code_without_prose(fn: ast.AST) -> str:
    """`ast.unparse` of a function with its docstrings removed.

    THE DOCSTRING IS NOT THE CODE, and this repository has been bitten by the difference twice
    before — once by a substring guard that tripped on the prose explaining its own rule, and once
    by one that made somebody delete the comment saying why the OS preference is not consulted.
    A guard that forces you to erase the explanation to go green teaches the wrong lesson, so the
    explanation is what gets stripped, not written around.

    `ast.unparse` already drops comments; docstrings survive as string expressions, so they are
    what has to go."""
    cleaned = copy.deepcopy(fn)
    for node in ast.walk(cleaned):
        body = getattr(node, "body", None)
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module))
                and isinstance(body, list) and body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(cleaned)


@pytest.mark.parametrize("name", PRODUCT_ACTIONS)
def test_no_product_row_names_slack(name):
    """The rows themselves, read as code. A row that reached into the channel for one helper would
    pass the subprocess test above whenever that helper happened to be importable.

    Docstrings are stripped first — see `_code_without_prose`. A row is allowed to EXPLAIN that a
    capability used to live in the Slack package; it is not allowed to reach for it."""
    tree = ast.parse((ROOT / "openfactory/actions/catalog.py").read_text())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == f"_{name}"), None)
    assert fn is not None, f"_{name} is not in catalog.py — the row points at nothing"
    text = _code_without_prose(fn)
    assert "slack" not in text.lower(), f"_{name} names Slack:\n{text[:600]}"


def test_the_draft_runs_where_agents_AUTHENTICATE_not_where_the_request_lands():
    """`product_ask` dispatches to the worker instead of drafting in the serving process.

    THE GUARD THAT WAS HERE BEFORE MEASURED THE WRONG THING, which is why this one reads as code
    rather than trusting a refusal. The row used to call `_harness_missing` — `shutil.which` on
    the harness binary — to keep drafting off the panel. Measured inside the running panel
    container: `claude` is at `/usr/local/bin/claude`, because `docker-compose.yml` builds the
    panel from `docker/worker.Dockerfile`, whose last step is `npm install -g
    @anthropic-ai/claude-code`. The binary is present on exactly the process the check existed to
    stop; what is missing there is `CLAUDE_CODE_OAUTH_TOKEN` and the docker socket. So the check
    would have waved the request through to an unauthenticated agent and returned its "Not logged
    in · Please run /login" as the product role's own answer — the defect `AskWorkflow` was built
    for, one capability later.

    Dispatching makes it impossible rather than detected, so what is asserted is the dispatch.
    """
    tree = ast.parse((ROOT / "openfactory/actions/catalog.py").read_text())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_product_ask"), None)
    assert fn is not None, "_product_ask is not in catalog.py"
    text = ast.unparse(fn)

    assert "ProductAskWorkflow" in text, (
        "_product_ask no longer dispatches to the worker — whichever process serves the request "
        "drafts, and on the panel that process has the harness binary but no credential"
    )
    # THE OTHER HALF, and the one that made this worth writing: dispatching is only true while it
    # is not ALSO drafting locally. A row that kept `module.draft(...)` beside the dispatch would
    # satisfy the assertion above and still run the agent in the wrong process.
    assert ".draft(" not in text, (
        f"_product_ask still drafts in-process as well as dispatching:\n{text[:700]}"
    )
    assert not re.search(r"\bshutil\b|which\(", text), (
        "_product_ask is measuring the harness binary again — that check passes on the panel, "
        "which is the process it would be written to stop"
    )


def test_the_worker_actually_REGISTERS_what_the_panel_dispatches_to():
    """A dispatch to an unregistered workflow fails at the moment a human finally asks.

    This repository's signature defect, in the shape it takes here: `_product_ask` names
    `"ProductAskWorkflow"` as a STRING, so nothing at import time connects the caller to the
    class. Both halves are read off the worker's own registration lists.
    """
    src = (ROOT / "openfactory/runtime/temporal/worker.py").read_text()
    workflows = src.split("workflows=[", 1)[1].split("]", 1)[0]
    activities = src.split("WORKER_ACTIVITIES = [", 1)[1].split("\n]", 1)[0]

    assert "ProductAskWorkflow" in workflows, (
        "the worker does not register ProductAskWorkflow — the panel would dispatch a question "
        "into an unknown workflow type and the client would see a timeout"
    )
    assert "product_role_ask" in activities, (
        "the worker does not register the product_role_ask activity — the workflow would start "
        "and then fail on an unknown activity type"
    )


def test_the_ASK_calls_the_verb_that_can_actually_answer():
    """`draft` and `answer` are different verbs and only one of them speaks.

    THE BUG THIS PINS, WHICH FAILED WITHOUT FAILING. The row called `ProductModule.draft`, whose
    success path is `ProductAnswer(ok=True, draft=…, raw=…)` — no `text`. So `product_ask`
    answered every question with an EMPTY SENTENCE, and its advertised `is_request`, `is_defect`,
    `gesture` and `decisions` were structurally always false, because only `answer` fills them.
    The row's own docstring described `answer`'s behaviour while the call underneath did something
    else, and nothing anywhere raised.

    Read as CODE rather than by running it: the real call needs a corpus, a worktree and an agent
    pass, and a test that mocked all three would be asserting against its own mock.
    """
    src = (ROOT / "openfactory/runtime/temporal/activities.py").read_text()
    body = src.split("def _product_draft(")[1].split("\n@")[0]

    assert ".answer(" in body, (
        "the product ask no longer makes the conversational call — `draft` alone returns no text, "
        "so the client is answered with an empty sentence"
    )
    # AND the draft still happens for a request, or `product_propose` has nothing to commit and
    # the sign-off surface loses the thing it exists to sign off.
    assert ".draft(" in body and "is_request" in body, body[:600]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filed,expect",
    [([{"ok": True, "ref": "acme#41", "url": "", "detail": "", "existed": False}], "acme#41"),
     ([], "could not turn it into units of work"),
     ([{"ok": False, "ref": "", "url": "", "detail": "the board refused", "existed": False}],
      "the board refused")],
    ids=["cards-filed", "nothing-came-back", "the-board-refused"])
async def test_accepting_FILES_THE_WORK_and_never_costs_the_agreement(
        monkeypatch, resolvable_product, filed, expect):
    """The third of the card's own acceptance test: *propose, accept, and see the card born on
    the board*. `ProductModule.accept` writes the agreement and stops — the accept→break_down
    chain lived in the Slack package and nowhere else, so off Slack a client could agree to
    something and no work would ever appear.

    ALL THREE SHAPES RUN THE SUCCESS PATH, which is the point. `_write_outcome` already puts
    `project` and `number` in the acceptance's data, so composing the follow-up by splatting it
    beside the same keywords was a TypeError — on the first successful acceptance, the one branch
    every refusal test walks straight past. It was found by running it, and this is what keeps it
    found.
    """
    from openfactory.actions import catalog

    async def _fake_breakdown(accepted, **_kw):
        return catalog._with_the_work_filed.__wrapped__(accepted, **_kw) \
            if hasattr(catalog._with_the_work_filed, "__wrapped__") else None

    monkeypatch.setattr(catalog, "_connected", _unreachable_engine if filed is None else
                        _engine_returning(filed))
    outcome = await catalog._product_accept(project="acme", number="7", by=_actor(), yes=True)

    assert outcome.ok, outcome.message
    # THE AGREEMENT IS SAID FIRST, ALWAYS. The opposite order reads as "your acceptance failed",
    # about the one thing that certainly did not.
    assert outcome.message.startswith("accepted requirement 7"), outcome.message
    assert expect in outcome.message, outcome.message
    assert outcome.data.get("project") == "acme" and outcome.data.get("number") == 7, outcome.data


def _engine_returning(filed):
    """A durable engine whose ProductBreakdownWorkflow answers `filed`."""
    class _Client:
        async def execute_workflow(self, *_a, **_kw):
            return filed

    async def _connected():
        return _Client(), None

    return _connected


async def _unreachable_engine():
    from openfactory.actions.base import UNAVAILABLE, refused

    return None, refused(UNAVAILABLE, "no engine")


@pytest.mark.asyncio
async def test_a_breakdown_that_EXPLODES_still_reports_the_agreement(monkeypatch,
                                                                    resolvable_product):
    """The catch-all is wide enough to swallow a refactor, so it is worth proving it swallows in
    the right direction: the client is told the requirement is agreed even when the dispatch
    raises outright."""
    from openfactory.actions import catalog

    async def _boom():
        raise RuntimeError("the engine went away mid-sentence")

    monkeypatch.setattr(catalog, "_connected", _boom)
    outcome = await catalog._product_accept(project="acme", number="7", by=_actor(), yes=True)

    assert outcome.ok and outcome.message.startswith("accepted requirement 7"), outcome.message
    assert "agreement is recorded either way" in outcome.message, outcome.message


@pytest.mark.asyncio
async def test_releasing_RE_CHECKS_authorisation_because_nothing_else_will(monkeypatch,
                                                                          resolvable_product):
    """`product.release.release` says of itself *"the caller has ALREADY authorised the person…
    this is the pen, not the judgement"*.

    THIS ROW IS THE ONLY PRODUCT ROW THAT DOES NOT GO THROUGH `ProductModule`, so unlike propose /
    accept / drop — where the module asks `may_act` itself — nothing else in the chain would ask.
    A release that skipped it would put a client's software in front of their users on the say-so
    of whoever held a token.
    """
    from openfactory.actions import catalog

    fired = []
    monkeypatch.setattr("openfactory.product.module.may_act", lambda *_a, **_k: False)
    monkeypatch.setattr("openfactory.product.release.release",
                        lambda *a, **k: (fired.append(a) or (True, "")))

    outcome = await catalog._product_release(project="acme", issue="41", by=_actor(), yes=True)

    assert not outcome.ok and outcome.code == catalog.DENIED, outcome
    assert not fired, "an unauthorised caller reached the release itself"


@pytest.mark.asyncio
async def test_a_release_needs_yes_and_says_what_it_costs(resolvable_product):
    """The one act on this surface whose blast radius is the client's own users."""
    from openfactory.actions import catalog

    outcome = await catalog._product_release(project="acme", issue="41", by=_actor())

    assert not outcome.ok and outcome.code == catalog.INVALID
    assert "in front of the client's users" in outcome.message, outcome.message


@pytest.mark.asyncio
async def test_a_release_that_reached_NOTHING_is_not_reported_as_done(monkeypatch,
                                                                     resolvable_product):
    """`release()` re-asks the engine whether the job is still parked and returns the honest
    sentence when it is not. A client told "it is going out" over a signal that reached no
    workflow is the worst outcome available on this path — so that sentence is carried through
    rather than replaced with a status phrase."""
    from openfactory.actions import catalog

    monkeypatch.setattr("openfactory.product.module.may_act", lambda *_a, **_k: True)
    monkeypatch.setattr("openfactory.product.release.release",
                        lambda *_a, **_k: (False, "o #41 não está mais esperando essa liberação"))

    outcome = await catalog._product_release(project="acme", issue="41", by=_actor(), yes=True)

    assert not outcome.ok, outcome
    assert "não está mais esperando" in outcome.message, outcome.message


@pytest.mark.asyncio
async def test_promoting_says_what_did_NOT_start(monkeypatch, resolvable_product):
    """The spend gate, and the partial case is the one worth pinning: the client is paying for
    what did start and needs to know what did not. Rounding a partial up to success is how a
    board silently drops work somebody approved."""
    from openfactory.actions import catalog
    from openfactory.product.authoring import WriteResult

    resolvable_product.promote = lambda numbers, **_kw: [
        WriteResult(ok=True, ref="acme#1"),
        WriteResult(ok=False, detail="o quadro recusou o #2"),
    ]
    outcome = await catalog._product_promote(project="acme", numbers="1,2", by=_actor(), yes=True)

    assert outcome.ok, outcome.message
    assert "started 1 of 2" in outcome.message and "o quadro recusou" in outcome.message, (
        outcome.message)


#: The verbs that were a branch of `product_channel._handle` and existed nowhere else.
WRITE_ROWS = ("product_close_card", "product_align_card", "product_refine_card",
              "product_record_decision", "product_note_fact", "product_file_defect")


@pytest.mark.asyncio
@pytest.mark.parametrize("row", WRITE_ROWS)
async def test_every_write_verb_REFUSES_without_consent(resolvable_product, row):
    """Six acts that change a client's board or their documentation, and every one of them was
    reachable only by saying yes in a chat product. Consent travels with the act or it is not
    consent — `_said_yes` and not `bool(yes)`, because a transport that sends JSON can send the
    string "false", which is truthy in Python.

    THE PROJECT HAS TO RESOLVE, AND THE FIRST VERSION OF THIS TEST DID NOT KNOW THAT — the same
    mistake this file already records one fixture above. It passed an unregistered project, which
    is refused with NOT_FOUND *before* the consent branch, so deleting every `_said_yes` call left
    it green. Mutation caught it: asserting `not ok` is satisfied by the wrong refusal, so the
    CODE is asserted too.
    """
    from openfactory.actions import catalog

    params = {"project": "acme", "number": "7", "requirement": "3", "decision": "we ship it",
              "term": "fechamento", "body": "roda no dia 5", "restated": "o saldo vem errado",
              "title": "exportar o relatório em CSV"}
    spec = catalog.CATALOG[row]
    outcome = await spec.run(by=_actor(),
                             **{k: v for k, v in params.items() if k in spec.parameters})

    assert not outcome.ok, f"{row} wrote something with no consent: {outcome.message}"
    assert outcome.code == catalog.INVALID, (
        f"{row} was refused for the wrong reason ({outcome.code}) — the consent branch was never "
        f"reached: {outcome.message}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("row,verb", [("product_refine_card", "refine"),
                                      ("product_align_card", "align")])
async def test_the_two_card_verbs_run_where_the_AGENT_runs(monkeypatch, resolvable_product,
                                                           row, verb):
    """`refine` and `align_card` both end in `_role().ask_json(sandbox=…)`, so they carry the same
    constraint `product_ask` does and must not execute in whichever process served the request.

    Asserted on the DISPATCH, and on the verb that travels with it — a helper shared by two rows
    is one place for the verb to be wrong for both."""
    from openfactory.actions import catalog

    seen = {}

    class _Client:
        async def execute_workflow(self, name, inp, **_kw):
            seen["workflow"], seen["verb"] = name, getattr(inp, "verb", None)
            return {"ok": True, "ref": "#7", "detail": "", "url": "", "existed": False}

    async def _connected():
        return _Client(), None

    monkeypatch.setattr(catalog, "_connected", _connected)
    # ONLY WHAT THE ROW DECLARES: `refine` takes no requirement, and passing one anyway made the
    # first version of this test fail on its own argument rather than on the dispatch.
    extra = {"requirement": "3"} if "requirement" in catalog.CATALOG[row].parameters else {}
    outcome = await catalog.CATALOG[row].run(project="acme", number="7", by=_actor(), yes=True,
                                             **extra)

    assert outcome.ok, outcome.message
    assert seen["workflow"] == "ProductCardWorkflow", seen
    assert seen["verb"] == verb, f"{row} dispatched the wrong verb: {seen}"


def test_the_card_activity_REFUSES_a_verb_it_does_not_know():
    """A registry, not a free string. An unknown verb must be refused by name rather than fall
    through and do nothing while the caller reports success — the shape that makes a capability
    look present and be absent."""
    from openfactory.runtime.temporal.activities import _CARD_VERBS

    assert set(_CARD_VERBS) == {"refine", "align"}
    src = (ROOT / "openfactory/runtime/temporal/activities.py").read_text()
    body = src.split("async def product_role_card(")[1].split("\ndef ")[0]
    assert "_CARD_VERBS" in body and "unknown card verb" in body, body[:400]


def test_the_corpus_can_be_LISTED_not_only_written():
    """`product_accept` and `product_drop` take a NUMBER, and until this row existed nothing on
    any transport could say what the numbers were — the Slack channel knew only because it had
    posted them into a thread somebody could scroll back through.

    A surface without that history could only instruct somebody to type a number they got
    elsewhere, which is how a client accepts the wrong requirement.
    """
    from openfactory import actions

    row = actions.CATALOG.get("product_requirements")
    assert row is not None, "nothing can list a client's requirements"
    assert not row.needs_admin, (
        "listing what a product promises was made an admin act — a business analyst who cannot "
        "read the corpus cannot use the writes that take its numbers"
    )
    assert row.scope == actions.PRODUCT


def test_a_write_needs_consent_and_says_so(resolvable_product):
    """Every writing row refuses without `yes`, and the refusal is the sentence, not a log line.

    `_said_yes` is the reason this is not `bool(yes)`: a transport that sends JSON can send the
    STRING "false", which is truthy in Python — consent that can be given by accident is not
    consent, and these three rows are where being wrong costs a client a pull request in their own
    documentation repository.

    THE PROJECT HAS TO RESOLVE FOR THIS TO TEST ANYTHING, and the first version of this test did
    not know that. It passed an unregistered project name, which is refused BEFORE the consent
    branch — so deleting every `_said_yes` call left it green. Mutation-proved after the fix: each
    removal now fails here.
    """
    import asyncio

    from openfactory.actions import catalog

    who = _actor()
    rows = ((catalog._product_propose, {"answer": _drafted().model_dump(mode="json")}),
            (catalog._product_accept, {"number": "7"}),
            (catalog._product_drop, {"number": "7"}))
    for run, params in rows:
        for value in (False, "false", "no", "", None, 0):
            outcome = asyncio.run(run(project="acme", by=who, yes=value, **params))
            assert not outcome.ok, f"{run.__name__} accepted yes={value!r}"
            assert "yes" in outcome.message, outcome.message
        # THE POSITIVE TWIN: a row that refused everything would pass every line above.
        allowed = asyncio.run(run(project="acme", by=who, yes=True, **params))
        assert allowed.ok, f"{run.__name__} refuses even with consent: {allowed.message}"


def test_a_requirement_number_is_parsed_or_refused():
    """`REQ-0007`, `#7` and `7` are the same requirement; anything else is refused by name.

    A transport that coerced silently would act on a number nobody meant — and `accept` is the
    single most consequential act on this surface.
    """
    from openfactory.actions.catalog import _requirement_number

    for raw in ("7", "#7", "REQ-0007", " req-0007 "):
        num, bad = _requirement_number(raw)
        assert bad is None and num == 7, (raw, num, bad)
    for raw in ("", "seven", "REQ-", "#", "7a"):
        num, bad = _requirement_number(raw)
        assert bad is not None and num == 0, (raw, num)
        assert repr(raw) in bad.message, bad.message


def test_the_cli_offers_the_role_without_slack():
    """A tech-lead in a terminal, on a deployment that never installed the channel."""
    import re

    from typer.testing import CliRunner

    from openfactory.cli import app

    result = CliRunner().invoke(app, ["product", "--help"])
    assert result.exit_code == 0, result.output
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    for verb in ("status", "ask", "accept", "drop"):
        assert re.search(rf"^\s*\W?\s*{verb}\b", plain, re.MULTILINE), (
            f"`sdlc product {verb}` is missing:\n{plain}"
        )


def test_propose_refuses_to_redraft_what_nobody_read():
    """`propose` promises that what a human saw is what gets committed.

    `ProductModule.propose` takes the ProductAnswer `draft` produced *"rather than re-deriving
    one"*. On a stateless transport the draft has to travel, so a row that accepted only the
    original words and drafted again would silently commit a DIFFERENT text into the one artefact
    a client is asked to sign off. It refuses instead, and names where to get the draft.
    """
    import asyncio

    from openfactory.actions import catalog
    from openfactory.actions.base import Actor

    proposed: list = []

    class _Module:
        def propose(self, answer, **_kw):
            proposed.append(answer)
            from openfactory.product.authoring import WriteResult

            return WriteResult(ok=True, ref="REQ-0007", url="https://example/pr/1")

    class _Project:
        name = "acme"
        # the double stood in for a project and inherited nothing, so the voice used the
        # platform default — English since 2026-08-14, while these assertions are Portuguese
        language = "pt-BR"

    catalog._product_module = lambda _n, **_kw: (_Module(), _Project(), None)
    try:
        who = Actor(id="t", display="t", admin=True)

        # No `answer` → REFUSED, and the refusal names where to get one.
        no_draft = asyncio.run(catalog._product_propose(
            project="acme", question="quero um relatório mensal", yes=True, by=who))
        # THE SENTENCE, not merely the refusal. Without `answer`, validation would refuse anyway
        # (`model_validate(None)` raises) with "not something `product_ask` produced" — accurate
        # about the payload and useless about the mistake. Mutation-proved: asserting only
        # `not ok` left the branch deletable.
        assert not no_draft.ok, no_draft.message
        assert "Re-drafting" in no_draft.message and "product_ask" in no_draft.message, (
            no_draft.message)
        assert proposed == [], "it re-drafted and committed a text nobody read"

        # A shape that did not come from `product_ask` → REFUSED, not coerced.
        junk = asyncio.run(catalog._product_propose(
            project="acme", answer={"nope": [1, 2]}, yes=True, by=who))
        assert not junk.ok, junk.message
        assert proposed == [], proposed

        # The real answer, handed straight back → committed VERBATIM.
        from openfactory.product.role import ProductAnswer, RequirementDraft

        answer = ProductAnswer(ok=True, text="proposta", is_request=True,
                               draft=RequirementDraft(title="Relatório mensal",
                                                      body="O cliente precisa de um fechamento."))
        ok = asyncio.run(catalog._product_propose(
            project="acme", answer=answer.model_dump(mode="json"), yes=True, by=who))
        assert ok.ok, f"{ok.code}: {ok.message}"
        assert len(proposed) == 1
        assert proposed[0].draft.title == "Relatório mensal", proposed[0].draft
    finally:
        catalog._product_module = _REAL_PRODUCT_MODULE


def test_a_panel_write_is_not_recorded_as_a_slack_one(monkeypatch):
    """`via` is provenance, and it used to be the constant `"slack"` inside `may_act`.

    `authz.may` compares the id against the allowlist and never reads the channel, so this is not
    a permission change — it is the one record that says who authorised a change to a client's
    requirements no longer claiming the panel was Slack. The default stays `"slack"` so the
    channel, which is every other caller, is unchanged.
    """
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor
    from openfactory.product import module as product_module

    seen: list[str] = []

    class _Recording(product_module.ProductModule):
        def __init__(self, project, **kw):
            super().__init__(project, **kw)
            seen.append(self._via)

    monkeypatch.setattr(product_module, "ProductModule", _Recording)
    project = type("_P", (), {"name": "acme", "product": type("_C", (), {"enabled": True})()})()
    monkeypatch.setattr(catalog, "_project", lambda _n: (project, None))

    for via in ("panel", "cli", ""):
        catalog._product_module("acme", by=Actor(id="t", display="t", via=via))
    assert seen == ["panel", "cli", "api"], seen

    # THE DEFAULT IS STILL SLACK'S, checked directly, because every one of the channel's callers
    # relies on it and none of them passes the argument.
    assert product_module.ProductModule(project)._via == "slack"


def test_the_channel_and_the_platform_ask_the_SAME_authorization():
    """One rule, two transports. `may_act` reads `product.admins` whoever is asking — a second
    allowlist for the panel would be the coupling being removed, rebuilt on the other side."""
    from openfactory.product.module import may_act

    project = type("_P", (), {
        "name": "acme",
        "product": type("_C", (), {"enabled": True, "admins": ("U123",)})(),
    })()
    assert may_act(project, "U123") is True
    assert may_act(project, "U123", via="panel") is True
    assert may_act(project, "someone-else", via="panel") is False
    assert may_act(project, "", via="panel") is False


def test_the_staged_proposal_left_the_SLACK_package():
    """The machine that decides whether a "sim" means it was never Slack-specific — its only
    dependencies are `openfactory.memory`, `openfactory.product.voice` and `openfactory.product.role` — and it was
    already reached from a second surface before it moved (`api/app.py` calls `answer_staged`).

    ADR-0038: no capability may live in `runtime/<channel>/`. This is the measurement of that rule
    for the largest thing that was breaking it.
    """
    from openfactory.product import staging

    for name in ("remember", "consume", "pending_for", "find_waiting", "proposal_token",
                 "is_yes", "is_no", "_PENDING"):
        assert hasattr(staging, name), f"{name} is not in openfactory/product/staging.py"


def test_the_channel_still_reaches_the_SAME_staged_state():
    """THE RE-EXPORT IS NOT A COPY, and the difference already produced a defect twice.

    `from … import _PENDING` binds the reference at import time. Eight test fixtures REBIND that
    name to isolate themselves, and after the move a bound copy left writes landing in one dict
    while reads came out of another — a `KeyError` where it was loud, and silently stale where it
    was not. The mutable state is forwarded through the module's `__getattr__` instead, so both
    sides always see whichever dict is current.
    """
    from openfactory.product import channel as pc
    from openfactory.product import staging

    original = staging._PENDING
    try:
        staging._PENDING = {"probe": {"kind": "draft"}}
        assert pc._PENDING == {"probe": {"kind": "draft"}}, (
            "the channel is reading a dict nobody writes to — the re-export was bound rather "
            "than forwarded, and every isolation fixture in this repository would silently stop "
            "isolating"
        )
    finally:
        staging._PENDING = original


def test_the_conversational_turn_CARRIES_ITS_MEMORY():
    """`product_say` is the half `product_ask` is not: the reply that remembers.

    THREE THINGS A NAIVE PORT DROPS, and each was a defect the Slack path already paid for. The
    person's turn is recorded ON ARRIVAL — before the model is asked, so a concurrent follow-up
    sees it — and excluded from the history handed to the prompt, because it is already the
    question. What is STILL WAITING travels as `pending`; its absence is what once let the role
    announce five registered requirements it had only proposed. And a request it makes of a human
    becomes a tracked loop, or it lives in a message and dies when that scrolls away.

    Read as code: the real call needs a corpus, a worktree and an agent pass.
    """
    src = (ROOT / "openfactory/runtime/temporal/activities.py").read_text()
    body = src.split("def _product_conversation(")[1].split("\n@")[0]

    assert ".answer(" in body, "product_say does not hold a conversation — it drafts, like `ask`"
    assert "transcript.record" in body and "transcript.recent" in body, (
        "the turn carries no memory, so every message is turn one")
    assert "pending=" in body and "_proposal_summary" in body, (
        "what is still staged does not reach the prompt — the role can describe a corpus that "
        "does not include the draft it is holding")
    assert "record_decisions" in body, (
        "a request made of a human opens no loop, so nobody is ever reminded")


def test_the_asking_turn_is_EXCLUDED_from_its_own_history():
    """History is strictly what came BEFORE. The arrival row is already the question in the
    prompt, and feeding it back makes the role answer a message it is being asked about twice."""
    src = (ROOT / "openfactory/runtime/temporal/activities.py").read_text()
    body = src.split("def _product_conversation(")[1].split("\n@")[0]

    # THE FILTER ITSELF, not the operator that happens to express it. The first version of this
    # asserted `"!=" in body` and failed on `not (… == …)`, which is the same reading written the
    # other way round — a guard that pins spelling instead of behaviour.
    comprehension = body.split("transcript.recent(")[1].split("]")[0]
    assert "arrival" in comprehension, (
        "the history handed to the prompt is not filtered by the arriving turn, so the role is "
        f"asked about a message that is already in its own conversation:\n{comprehension}")


# ── the gap this file measured, and then closed ─────────────────────────────────────────────────

#: Channels that match intents THEMSELVES rather than asking the core to. EMPTY since 2026-08-25:
#: the one entry was `runtime/slack/product_channel.py`, and it left with the conversation it
#: belonged to — `product/channel.py::_run_intent` is a CORE dispatcher now, beside the catalogue's
#: `_SAY_INTENTS`. Two dispatchers in the core is E6 still owed (fourteen intents beside four rows);
#: a channel parsing on its own is the drift this set exists to name, and there is none left.
_CHANNELS_STILL_DISPATCHING: set[str] = set()


def test_the_CORE_reads_a_typed_sentence_now_and_not_only_the_channel():
    """The positive successor to a guard that measured this as a gap, and has outlived it.

    THE GAP, AS MEASURED: `match_intent` had exactly ONE production caller, inside the Slack
    handler. So "faz a triagem do board" typed into the panel got a conversational reply while the
    same sentence in Slack ran the sweep — two surfaces doing different things with the same words,
    which is what ADR-0038 rule 1 forbids.

    The old test named the gap and told a reader to widen its allowlist when it closed, which would
    have inverted its own claim while staying green. It is replaced rather than edited: a table
    whose name says SLACK ONLY cannot be the guard for the core reaching it too."""
    callers = set()
    for path in (ROOT / "openfactory").rglob("*.py"):
        rel = str(path.relative_to(ROOT))
        if rel == "openfactory/product/intents.py":       # the definition, not a caller
            continue
        if re.search(r"\bmatch_intent\b", path.read_text()):
            callers.add(rel)

    core = {c for c in callers if not c.startswith("openfactory/runtime/")}
    assert core, (
        "no core module reads a typed sentence — the intent matcher is reachable only from a "
        "channel again, and a deployment without one cannot ask for a triage in its own words")

    undocumented = callers - _CHANNELS_STILL_DISPATCHING - core
    assert not undocumented, (
        f"a second channel matches intents on its own: {sorted(undocumented)}. Two transports "
        f"parsing a person's words independently is the drift ADR-0038 forbids — the words belong "
        f"to the core, and a transport should be calling it rather than repeating it")


def test_the_typed_sentence_is_ROUTED_through_perform_and_not_around_it():
    """Where the authorisation lives, asserted on the code.

    `perform` applies the scope and then the admin check with the actor that came through the
    door. Calling the row's function directly would skip both — and the worker cannot make up the
    difference, because `ProductSayInput` carries a bare `asked_by` string with no scopes and no
    admin flag, so a gate built down there would be inventing authority rather than checking it."""
    from openfactory.actions import catalog

    body = ast.unparse(next(
        n for n in ast.walk(ast.parse((ROOT / "openfactory/actions/catalog.py").read_text()))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_say_as_an_intent"))

    assert "actions.perform(" in body, (
        "the intent branch does not go through `perform`, so nothing applies the scope or the "
        "admin check to a sentence that can start work")
    assert "by=by" in body, "it performs as somebody other than the person who typed"
    # every routed row is a real one, and every one of them is read-only
    for intent, row in catalog._SAY_INTENTS.items():
        spec = catalog.CATALOG.get(row)
        assert spec is not None, f"{intent} routes to {row}, which the catalogue does not have"
        assert spec.needs_admin is False, (
            f"{row} is admin-gated, so routing a typed sentence to it makes a sentence a write "
            f"with no confirmation turn — that needs the staging machinery, not this table")


# ── what is STAGED, listable at last ─────────────────────────────────────────────────────────────

def _staged(token="acme|abc123", text="Vou anotar assim — *fecha o #511*", kind="drop",
            number=511):
    """A `Pending` carrying a REAL frozen entry, so `_thaw` validates rather than pattern-matches.

    Hand-writing the payload JSON would test a shape nothing produces — `_freeze` is what actually
    writes it, and the round trip is the whole discriminator."""
    from openfactory.memory.messages import Pending
    from openfactory.product.staging import _freeze

    return Pending(token=token, text=text, ts="2026-08-07T03:00:00Z", channel="acme",
                   approve="Sim", reject="Não", payload=_freeze({"kind": kind, "number": number}))


def _plain_question(token="job-91"):
    """What the tech-lead asks on the panel: no payload, because nothing staged it."""
    from openfactory.memory.messages import Pending

    return Pending(token=token, text="Job 91 is parked — resume or skip?", ts="2026-08-07T02:00:00Z",
                   channel="acme", approve="Resume", reject="Skip", payload="")


@pytest.mark.asyncio
async def test_product_pending_LISTS_what_is_staged(monkeypatch, resolvable_product):
    """The success path RUN, not merely resolved.

    Every refusal test in this file walks past the branch that builds the answer, and this
    codebase has shipped a `TypeError` living exactly there — a row whose refusals were all
    green and whose one success crashed."""
    from openfactory import actions
    from openfactory.memory import messages

    monkeypatch.setattr(messages, "pending", lambda _p, **_k: [_staged()])
    outcome = await actions.perform("product_pending", by=_actor(), project="acme")

    assert outcome.ok, outcome.message
    assert outcome.data["count"] == 1
    row = outcome.data["pending"][0]
    # WHAT is waiting, not merely that something is
    assert row["kind"] == "drop" and row["number"] == 511
    assert row["token"] == "acme|abc123"
    assert row["thread"] == "acme", "the conversation key is what a later answer must carry"
    # the sentence is the CLIENT's — their language, and none of this platform's routing slugs
    assert "1 proposta(s)" in outcome.message, outcome.message
    assert "drop" not in outcome.message, f"an internal kind reached the client: {outcome.message}"


@pytest.mark.asyncio
async def test_product_pending_does_NOT_hand_a_scoped_credential_the_FLOORS_questions(
        monkeypatch, resolvable_product):
    """The store is shared; the credential is not.

    `messages.pending` returns every unanswered question the factory asked — a parked job's
    resume/skip included. A product credential reading those would be the scope boundary leaking
    through a listing, which is the quietest way for one to fail."""
    from openfactory import actions
    from openfactory.memory import messages

    monkeypatch.setattr(messages, "pending",
                        lambda _p, **_k: [_plain_question(), _staged(), _plain_question("job-92")])
    outcome = await actions.perform("product_pending", by=_actor(), project="acme")

    assert outcome.ok, outcome.message
    tokens = [r["token"] for r in outcome.data["pending"]]
    assert tokens == ["acme|abc123"], f"the floor's questions leaked into a product listing: {tokens}"


@pytest.mark.asyncio
async def test_product_pending_reads_the_DURABLE_store_not_this_processes_memory(
        monkeypatch, resolvable_product):
    """`_PENDING` belongs to whichever worker staged the proposal.

    A panel or a CLI answering from it would report "nothing waiting" with perfect confidence
    about the wrong process's memory — the defect the durable mirror exists to prevent, and one
    that only ever shows up on a real deployment where the two are different processes.

    THIS ASSERTED `count == 0` OVER AN EMPTY STORE AND WAS DECORATION. Reading `_PENDING` also
    yields nothing — those dicts carry no frozen payload, so the structural filter drops them —
    and the guard written to catch that mutation was the one test that stayed green under it while
    three others caught it by accident. Absence cannot tell two empty answers apart. So both
    sources are LOADED, with different proposals, and the assertion names which one came back."""
    from openfactory import actions
    from openfactory.memory import messages
    from openfactory.product import staging

    monkeypatch.setattr(staging, "_PENDING",
                        {"acme": {"kind": "decision", "number": 999}})   # this process's memory
    monkeypatch.setattr(messages, "pending",
                        lambda _p, **_k: [_staged(kind="drop", number=511)])  # the durable store
    outcome = await actions.perform("product_pending", by=_actor(), project="acme")

    assert outcome.ok, outcome.message
    assert outcome.data["count"] == 1, outcome.data
    row = outcome.data["pending"][0]
    assert (row["kind"], row["number"]) == ("drop", 511), (
        f"the row answered from this process's dict ({row}) — on a deployment where the panel and "
        f"the worker are different processes that is a confident wrong answer")


@pytest.mark.asyncio
async def test_product_pending_survives_an_unreadable_store(monkeypatch, resolvable_product):
    """A store that cannot be read is an answer, never a traceback: this runs behind a panel
    route and a CLI verb, and both must degrade."""
    from openfactory import actions
    from openfactory.memory import messages

    def _boom(*_a, **_k):
        raise OSError("the table is gone")

    monkeypatch.setattr(messages, "pending", _boom)
    outcome = await actions.perform("product_pending", by=_actor(), project="acme")
    assert not outcome.ok
    assert "could not read what is waiting" in outcome.message


# ── the intents that had no row ──────────────────────────────────────────────────────────────────
#
# `_run_intent`'s dispatch predates the action layer, and nine of its fourteen intents map onto a
# row that already exists. These are two of the four that did not — so "faz a triagem do board"
# reached `module.triage_board` through the Slack handler and through nothing else.

@pytest.mark.asyncio
async def test_product_triage_reads_the_board_and_says_it_in_the_CLIENTS_words(monkeypatch):
    """The success path RUN, and the prose asserted to be the SHARED one.

    A row that composed its own sentence would drift from the channel's by the second release,
    and the client would learn that the answer depends on where they asked."""
    from openfactory import actions
    from openfactory.actions import catalog
    from openfactory.product import voice

    class _Obs:
        kind, ref, detail = "no_acceptance", "#511", "nothing says when it is done"

    class _Report:
        observations = [_Obs()]

    class _M:
        def triage_board(self):
            return _Report(), ""

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (_M(), project, None))
    seen = {}

    def _spy(report, **kw):
        seen["called"] = True
        return "a triagem, em português"

    monkeypatch.setattr(voice, "triage_report", _spy)
    outcome = await actions.perform("product_triage", by=_actor(), project="acme")

    assert outcome.ok, outcome.message
    assert seen.get("called"), "the row composed its own prose instead of `voice.triage_report`"
    assert outcome.message == "a triagem, em português"
    assert outcome.data["findings"] == 1
    assert outcome.data["observations"][0]["ref"] == "#511"


@pytest.mark.asyncio
async def test_product_triage_says_the_problem_is_OURS_when_the_board_cannot_be_read(monkeypatch):
    """The diagnosis is operator prose — English, with a repo slug in it. The log keeps it whole;
    the client hears that the problem is ours, which is the channel's own rule and the reason a
    naive port of this row would leak a repository name into a client's chat."""
    from openfactory import actions
    from openfactory.actions import catalog

    class _M:
        def triage_board(self):
            return None, "GET /repos/acme-internal/billing/issues: 404"

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (_M(), project, None))
    outcome = await actions.perform("product_triage", by=_actor(), project="acme")

    assert not outcome.ok
    assert "acme-internal" not in outcome.message, (
        f"the operator's diagnosis reached the client: {outcome.message}")
    assert "could not read the board" in outcome.message


@pytest.mark.asyncio
async def test_product_announce_is_the_cheapest_proof_the_role_is_configured(monkeypatch):
    from openfactory import actions
    from openfactory.actions import catalog

    class _M:
        def introduce(self):
            return "Oi, sou a PO deste produto."

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (_M(), project, None))
    outcome = await actions.perform("product_announce", by=_actor(), project="acme")

    assert outcome.ok and outcome.message == "Oi, sou a PO deste produto."


# ── one prose, two renderings ────────────────────────────────────────────────────────────────────

class _VoiceModule:
    """A module whose reads succeed, so the row reaches the sentence it composes.

    A refusing double would make every assertion below pass for the module's reason instead of
    the row's — the same trap `_FakeModule` documents."""

    def triage_board(self):
        class _O:
            kind, ref, ticket, detail = "no-criteria", "#511", 511, ""

        class _R:
            observations = [_O(), _O()]
            skipped = []

        return _R(), ""

    def introduce(self):
        return "Oi, sou a PO. **Nada** mudou desde ontem."

    def status_line(self):
        return "vejo o corpus"

    @property
    def available(self):
        return True

    def context(self):
        class _C:
            corpus = None
        return _C()


#: The rows that COMPOSE a sentence from `openfactory/product/voice.py` and can be driven here without a
#: corpus, a forge or an engine. Deliberately not "every product row": `product_requirements`
#: needs a real corpus and the write verbs need consent, and a guard that silently skipped them
#: while claiming to cover everything is worse than one that names its edge.
_COMPOSING_ROWS = ("product_triage", "product_announce", "product_status")


@pytest.mark.asyncio
@pytest.mark.parametrize("row", _COMPOSING_ROWS)
async def test_no_product_row_returns_MRKDWN_in_its_message(row, monkeypatch):
    """`Outcome.message` forbids markup in as many words, and the reason is recorded there: a
    message pre-decorated for Slack renders as literal asterisks in the panel, which is how the
    first impediment alert shipped.

    THIS WAS LIVE WHEN THE GUARD WAS WRITTEN. `voice.triage_report` emits `• **7** …` because it
    is written for someone reading a chat client, and `product_triage` returned it verbatim —
    a defect shipped in the commit that added the row, in a rule stated one import away. The fix
    is not a second set of composers: the prose stays one implementation and the ACTION LAYER
    strips at the boundary that states the rule.

    Note what is NOT asserted: `•` stays. It is a character, not mrkdwn, and it renders as itself
    everywhere. Over-correcting here would have cost the reports their shape for nothing."""
    from openfactory import actions
    from openfactory.actions import catalog

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (_VoiceModule(), project, None))
    outcome = await actions.perform(row, by=_actor(), project="acme")

    assert outcome.ok, outcome.message
    assert "**" not in outcome.message, (
        f"{row} returned mrkdwn in Outcome.message — the panel renders it as literal asterisks:\n"
        f"{outcome.message}")


def test_strip_markup_removes_emphasis_and_LEAVES_the_text_alone():
    """The positive twin, and the arm that matters is the second one: a stripper that ate content
    would be worse than the markup, and silently — the sentence still arrives, just wrong."""
    from openfactory.product.voice import strip_markup

    assert strip_markup("**7** parados") == "7 parados"
    assert strip_markup("responda *sim*") == "responda sim"
    # content survives: a requirement titled with an asterisk is not emphasis
    assert strip_markup("relatório 3 * 4") == "relatório 3 * 4"
    assert strip_markup("linha um\nlinha **dois**") == "linha um\nlinha dois"
    assert strip_markup("") == ""


def test_the_needs_action_prose_is_LANGUAGE_AWARE_now_that_it_is_core():
    """It was hardcoded pt-BR inside the Slack package with no `language` parameter, so a client
    on any other language read Portuguese. Moving the file without adding the parameter would
    have been relocating the defect."""
    from openfactory.product.voice import needs_action_report

    class _R:
        decisions = []

        def mine(self):
            return []

        def handed_back(self):
            return []

    assert "Nada parado" in needs_action_report(_R(), language="pt-BR")
    assert "Nothing parked" in needs_action_report(_R(), language="en")
    # an untranslated language gets understandable text, never a KeyError in a chat listener
    assert needs_action_report(_R(), language="fr-FR").strip()


# ── money is spent where the credentials are ─────────────────────────────────────────────────────

def _agent_spending_verbs(source: str) -> set[str]:
    """`ProductModule` methods that reach an agent, DERIVED rather than listed.

    A hand-kept list is a list somebody forgets to extend — and the thing being protected is
    precisely the new verb nobody thought about. The seed is how this class reaches a model at
    all (`_role()` builds the harness, `ask_json`/`survey` are the calls), closed transitively:
    `product_accept` -> `break_down` -> `file_issues` -> `_role` is three hops, and the row's
    author sees none of them."""
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ProductModule")
    methods = {m.name: m for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def called(fn):
        out = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                out.add(getattr(n.func, "attr", None) or getattr(n.func, "id", None))
        return {x for x in out if x}

    seed, found, growing = {"_role", "ask_json", "survey"}, set(), True
    while growing:
        growing = False
        for name, fn in methods.items():
            if name not in found and called(fn) & (seed | found):
                found.add(name)
                growing = True
    return {n for n in found if not n.startswith("_")}


def _spent_in_process(catalog_source: str, verbs: set[str]) -> list[tuple[str, int]]:
    """A spending verb reached from a row, in EITHER shape.

    THE FIRST VERSION SAW ONLY `module.verb(...)` AND MISSED `asyncio.to_thread(module.verb)` —
    the idiom this very file uses three lines away, and the one a developer copying the cheap
    sibling would reach for. The verb is an ARGUMENT there, never the callee, so the scan walked
    straight past the exact construction it was written to stop. A guard that catches only the
    shape nobody writes is decoration.

    AND THE RECEIVER MATTERS, not only the verb (#156). Matching on the attribute NAME alone made
    `channel.answer(project, token=…)` — a write to the message store — read as the product
    module's agent-spending `answer`. Obeying that would have meant renaming a store API to please
    a scan, which is a worse defect than the one the scan prevents. The product role is reached
    through `module` or `product`; a call on anything else is a different function that happens to
    share a word."""
    receivers = {"module", "product", "product_module", "_module"}
    found = []

    def spends(node) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr in verbs
                and isinstance(node.value, ast.Name) and node.value.id in receivers)

    for n in ast.walk(ast.parse(catalog_source)):
        if not isinstance(n, ast.Call):
            continue
        if spends(n.func):
            found.append((n.func.attr, n.lineno))          # module.verb(...)
        for arg in list(n.args) + [k.value for k in n.keywords]:
            # `to_thread(module.verb)`, `run_in_executor(None, module.verb)`, `partial(...)` —
            # anything handing the bound method somewhere else to be called.
            if spends(arg):
                found.append((arg.attr, arg.lineno))
            elif isinstance(arg, ast.Lambda):
                for inner in ast.walk(arg):
                    if spends(inner):
                        found.append((inner.attr, inner.lineno))
    return sorted(set(found))


def test_no_row_spends_an_agent_pass_in_the_CALLERS_process():
    """The class defect, guarded — and nothing guarded it before.

    Every "runs where the agent runs" assertion in this suite names a row, so each new row had to
    remember on its own. The two failure modes are not symmetric: `product_triage` reads a board
    and classifies deterministically, so answering it in-process is correct and cheap; its
    neighbour `product_needs_action` composes a worktree of two repositories and then spends ONE
    MODEL CALL PER PARKED TICKET. Copying the wrong sibling runs an agent inside the panel
    container — which carries the harness binary and neither its token nor the docker socket —
    and that is green in every test here and broken only in production, where it reads as the
    product role having gone quiet.

    So: a verb that reaches an agent may only be called from an ACTIVITY, never from a row. The
    row dispatches a workflow and waits."""
    verbs = _agent_spending_verbs((ROOT / "openfactory/product/module.py").read_text())
    assert {"review_needs_action", "baseline", "draft"} <= verbs, (
        f"the derivation stopped finding known agent verbs ({sorted(verbs)}) — it has broken, and "
        f"a broken derivation reports an empty set, which reads as compliance")

    stray = _spent_in_process((ROOT / "openfactory/actions/catalog.py").read_text(), verbs)
    assert not stray, (
        f"these run an agent in whichever process served the request: {stray}. Dispatch a "
        f"workflow — the panel's container has the harness binary and no credential for it")


def test_the_in_process_spend_scan_can_SEE_one():
    """The positive twin. `assert not stray` passes just as happily over a scan that finds
    nothing because it is broken, and this repository has shipped three guards that were green
    over live defects for exactly that reason."""
    verbs = _agent_spending_verbs((ROOT / "openfactory/product/module.py").read_text())
    planted = (
        "async def _product_x(*, project, by):\n"
        "    module, proj, bad = _product_module(project, by=by)\n"
        "    review, error = module.review_needs_action(limit=10)\n"
        "    return done('ok')\n"
    )
    found = _spent_in_process(planted, verbs)
    assert [v for v, _ in found] == ["review_needs_action"], found
    # …and a row that only reads is not accused, or the guard cries wolf on every cheap one
    assert not _spent_in_process(
        "async def _y(*, project, by):\n    report, e = module.triage_board()\n", verbs)


def _dispatched_workflow_names(source: str) -> set[str]:
    """Every workflow a row starts BY STRING. That is the whole hazard: nothing at import time
    connects `"ProductNeedsActionWorkflow"` to the class, so a typo or a missing registration is
    discovered by the first person who asks."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", "") not in ("execute_workflow", "start_workflow"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(
                node.args[0].value, str):
            names.add(node.args[0].value)
    return names


def test_every_workflow_a_row_DISPATCHES_is_registered_on_the_worker():
    """The generic form of the guard above, which named one workflow and covered one.

    Each row added since then had to remember on its own, and the failure mode is the worst
    shape this platform has: the dispatch succeeds, the client waits, and the timeout arrives
    minutes later with nothing to read. Derived from the source on both sides, so a new row is
    covered the moment it is written rather than when somebody remembers to extend a list."""
    dispatched = _dispatched_workflow_names((ROOT / "openfactory/actions/catalog.py").read_text())
    assert dispatched, "no row dispatches a workflow by name — the scan has broken"

    src = (ROOT / "openfactory/runtime/temporal/worker.py").read_text()
    registered = src.split("workflows=[", 1)[1].split("]", 1)[0]
    missing = sorted(n for n in dispatched if n not in registered)
    assert not missing, (
        f"{missing} are dispatched by a row and registered by no worker — the call succeeds, the "
        f"client waits, and a timeout arrives with nothing to read")


@pytest.mark.asyncio
async def test_product_needs_action_reports_whose_problem_each_parked_ticket_is(monkeypatch):
    """The success path RUN. Every other test of this row walks a refusal."""
    from openfactory import actions
    from openfactory.actions import catalog

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (object(), project, None))
    seen = {}

    class _Client:
        async def execute_workflow(self, name, inp, **_kw):
            seen["workflow"], seen["limit"], seen["via"] = name, inp.limit, inp.via
            return {"ok": True, "text": "Olhei o que está parado. **Não mexi em nada**",
                    "mine": 2, "theirs": 1,
                    "decisions": [{"ticket": 511, "cause": "requirement", "acted": False}]}

    async def _connected():
        return _Client(), None

    monkeypatch.setattr(catalog, "_connected", _connected)
    outcome = await actions.perform("product_needs_action", by=_actor(), project="acme", limit="3")

    assert outcome.ok, outcome.message
    assert seen["workflow"] == "ProductNeedsActionWorkflow"
    assert seen["limit"] == 3, "the budget the caller asked for did not reach the worker"
    # the markup the worker composed for a chat client does not reach `Outcome.message`
    assert "**" not in outcome.message
    assert outcome.data["mine"] == 2 and outcome.data["theirs"] == 1
    assert outcome.data["decisions"][0]["acted"] is False, "this pass must never claim it acted"


@pytest.mark.asyncio
async def test_product_needs_action_BOUNDS_the_budget_it_is_handed(monkeypatch):
    """`limit` is what stands between a board with three hundred parked tickets and three hundred
    model calls. A row that passed it through unbounded would let one typo spend a day's budget."""
    from openfactory import actions
    from openfactory.actions import catalog

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (object(), project, None))
    seen = {}

    class _Client:
        async def execute_workflow(self, name, inp, **_kw):
            seen["limit"] = inp.limit
            return {"ok": True, "text": "x", "mine": 0, "theirs": 0, "decisions": []}

    async def _connected():
        return _Client(), None

    monkeypatch.setattr(catalog, "_connected", _connected)
    await actions.perform("product_needs_action", by=_actor(), project="acme", limit="9999")
    assert seen["limit"] == 50, f"the cap did not hold: {seen['limit']}"

    bad = await actions.perform("product_needs_action", by=_actor(), project="acme", limit="ten")
    assert not bad.ok and bad.code == actions.INVALID


# ── consent, derived rather than listed ──────────────────────────────────────────────────────────

def _rows_taking_consent():
    from openfactory import actions

    return sorted(n for n, r in actions.CATALOG.items()
                  if r.scope == actions.PRODUCT and "yes" in (r.optional or ()))


def test_every_product_row_that_ASKS_for_consent_refuses_without_it():
    """`WRITE_ROWS` above is a HISTORICAL set — the six verbs that were branches of `_handle`. It
    cannot grow by itself, and every write row added since had to be remembered into it.

    This is the same promise, derived from the catalogue: a row that declares `yes` is a row whose
    author decided the act needs saying so out loud, and there is exactly one correct behaviour
    when it is missing. Twelve rows today, and the thirteenth is covered the moment it is written.

    Asserted on the CODE and not merely on `not ok`: these rows resolve a project that does not
    exist here, so `not ok` is satisfied by the wrong refusal — the trap this file already records
    once, where deleting every `_said_yes` left the test green."""
    rows = _rows_taking_consent()
    assert len(rows) >= 12, f"the derivation found only {rows} — it has broken"


@pytest.mark.asyncio
@pytest.mark.parametrize("row", _rows_taking_consent())
async def test_a_consenting_row_refuses_when_the_yes_is_missing(resolvable_product, row):
    from openfactory.actions import catalog

    params = {"project": "acme", "number": "7", "requirement": "3", "decision": "we ship it",
              "term": "fechamento", "body": "roda no dia 5", "restated": "o saldo vem errado",
              "issue": "41", "numbers": "7", "answer": "sim", "token": "C1|deadbeef",
              "title": "exportar o relatório em CSV"}
    spec = catalog.CATALOG[row]
    outcome = await spec.run(by=_actor(),
                             **{k: v for k, v in params.items() if k in spec.parameters})

    assert not outcome.ok, f"{row} acted with no consent: {outcome.message}"
    assert outcome.code == catalog.INVALID, (
        f"{row} was refused for the wrong reason ({outcome.code}) — the consent branch was never "
        f"reached: {outcome.message}")


@pytest.mark.asyncio
async def test_product_baseline_asks_may_act_and_not_only_admin(monkeypatch):
    """`ProductModule.baseline` is on the module's own list of four verbs that write WITHOUT
    checking, under a header that says "THE YES IS ONE LAYER UP". This row is that layer.

    `needs_admin` alone does not do it: the panel hands `admin=True` to everybody who got through
    the door, so without this check any panel token opens a pull request on a client's
    documentation with nobody on `product.admins` involved."""
    from openfactory import actions
    from openfactory.actions import catalog
    from openfactory.product import module as product_module

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (object(), project, None))
    monkeypatch.setattr(product_module, "may_act", lambda *_a, **_k: False)

    dispatched = []

    class _Client:
        async def execute_workflow(self, name, inp, **_kw):
            dispatched.append(name)
            return {"ok": True, "text": "feito", "existed": False, "url": "", "ref": ""}

    async def _connected():
        return _Client(), None

    monkeypatch.setattr(catalog, "_connected", _connected)
    outcome = await actions.perform("product_baseline", by=_actor(), project="acme", yes=True)

    assert not outcome.ok and outcome.code == actions.DENIED, outcome
    assert not dispatched, "it dispatched the pass before finding out nobody authorised it"


@pytest.mark.asyncio
async def test_product_baseline_carries_the_workers_own_sentence(monkeypatch):
    """`voice.baseline_done` runs the failure detail through `client_safe_detail` and DELIBERATELY
    drops the pull request URL. A row that rebuilt the sentence from the raw fields — which is
    what `_write_outcome` does — would quietly undo both, putting a stack trace and a link in
    front of a client."""
    from openfactory import actions
    from openfactory.actions import catalog
    from openfactory.product import module as product_module

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (object(), project, None))
    monkeypatch.setattr(product_module, "may_act", lambda *_a, **_k: True)

    class _Client:
        async def execute_workflow(self, name, inp, **_kw):
            assert name == "ProductBaselineWorkflow", name
            assert inp.actor == "t", "the row did not carry who asked"
            return {"ok": True, "existed": True, "url": "https://forge/pr/9", "ref": "product/base",
                    "text": "Já tinha proposto isso — **dá uma olhada**."}

    async def _connected():
        return _Client(), None

    monkeypatch.setattr(catalog, "_connected", _connected)
    outcome = await actions.perform("product_baseline", by=_actor(), project="acme", yes="yes")

    assert outcome.ok, outcome.message
    assert outcome.message.startswith("Já tinha proposto isso")
    assert "**" not in outcome.message
    # the url travels as DATA for a surface to link, and never inside the sentence
    assert "https://forge/pr/9" not in outcome.message
    assert outcome.data["url"] == "https://forge/pr/9" and outcome.data["existed"] is True


# ── the PO can actually click it ─────────────────────────────────────────────────────────────────

def _rows_named_by_the_panel() -> set[str]:
    """Every `product_*` row the panel names, whatever the call shape.

    Scanned by LITERAL rather than by `act("…")`, because the reading buttons go through a shared
    helper and the row arrives as a variable — a scan written against one call shape stops seeing
    the rows the moment somebody factors the duplication out, which is the refactor you WANT."""
    html = (ROOT / "openfactory/api/panel.html").read_text()
    return set(re.findall(r"""["']\s*(product_[a-z_]+)\s*["']""", html))


def test_every_row_the_panel_NAMES_exists_in_the_catalogue():
    """A misspelled row is a button that does nothing, and nothing anywhere says so — the POST
    404s, the surface shows a refusal it cannot explain, and the client concludes the product
    role is broken.

    This is the half of "reachable" the generic `POST /api/act/{name}` cannot give you: the route
    exists for every row, so a reachability guard written against the ROUTE is green while the
    button points at nothing."""
    from openfactory import actions

    named = _rows_named_by_the_panel()
    assert named, "the panel names no product row at all — the scan has broken"
    unknown = sorted(n for n in named if n not in actions.CATALOG)
    assert not unknown, (
        f"the panel offers {unknown}, which the catalogue does not have — those buttons 404")


def test_the_POs_page_can_reach_what_the_role_can_DO_not_only_what_it_can_say():
    """Five rows landed in one session and not one of them was reachable from `/product/<name>`.

    That is this repository's signature defect — built, tested, reached by nothing — committed
    five times in a row by the person writing the guards against it, because every reachability
    check in the suite is satisfied by the generic action route. The PO's page is where a client
    without a terminal and without Slack does their work; a capability that is not on it is one
    they do not have."""
    named = _rows_named_by_the_panel()
    # THE FAST ONES ARE BUTTONS. `product_needs_action` and `product_baseline` are NOT, and that
    # is a measurement rather than an omission: they await 20- and 40-minute workflows inside one
    # HTTP request, which no deployment can be asked to hold open — the work carries on, the
    # client reads a refusal, and the money is spent on a report nobody sees. They are
    # `openfactory product` verbs until the PO's surface has a way to be told something later;
    # the panel's message feed
    # is not it, because `_scope_of_path` classifies `/api/messages/` as FLOOR and a product
    # credential is refused it.
    expected = {"product_triage", "product_pending", "product_thread"}
    missing = sorted(expected - named)
    assert not missing, (
        f"{missing} exist, are guarded, and cannot be reached by the client they were written "
        f"for — the PO's page never names them")


#: Rows whose EXPECTED duration outlives an HTTP request, with the measurement beside each. Named
#: rather than derived, and the first attempt at deriving it is why: "the row dispatches a
#: workflow" also condemns `product_ask`, which has shipped on this page for weeks and answers in
#: under a minute. A `start_to_close_timeout` is a CEILING, not a duration — reading it as one
#: makes the guard confidently wrong about the row it was not written for.
_TOO_SLOW_FOR_A_BUTTON = {
    # one `role.ask_json` per parked ticket, up to `limit` (module.py) — minutes, not seconds
    "product_needs_action",
    # one whole-repository agent survey, then a pull request (module.py) — tens of minutes
    "product_baseline",
}


def test_the_panel_does_not_offer_a_pass_that_outlives_the_request():
    """A button may not await work that outlives the request it was clicked in. On either of these
    the client reads a refusal while the worker keeps spending, and the report is discarded — the
    money is gone and nobody reads the answer.

    THE RULE IS ABOUT THE DESIGN, NOT ABOUT A HOSTING PROVIDER, and the first version of this
    docstring got that backwards: it opened with "App Runner drops a request at 120 seconds", so a
    rule the framework must keep everywhere read as a fact about one deployment's vendor. This
    product is sold as agnostic; a guard whose stated reason is our own bill is a guard the next
    deployment is entitled to ignore.

    The number varies and the failure does not: a proxy, a load balancer and a browser tab each
    have their own ceiling, and a laptop lid has none at all. WORSE, `uvicorn` on a developer's
    machine has no ceiling either — so a ten-minute request passes locally and fails wherever a
    client actually runs, which is this repository's signature defect rather than a limitation.
    120 seconds is simply where we measured it first.

    They are `openfactory product` verbs until the PO's surface has a way to be told something
    later. The panel's message feed is not that way: `_scope_of_path` classifies `/api/messages/`
    as FLOOR, so a product credential is refused it, and `bootProduct` never mounts the chat.

    `product_ask` is deliberately NOT here. It spends ONE pass and answers in under a minute; its
    ten-minute ceiling is a bound on the pathological case, not a description of the normal one.
    The difference between it and the two above is how many agent passes the verb spends, which
    is the thing that was actually measured."""
    offered = _rows_named_by_the_panel() & _TOO_SLOW_FOR_A_BUTTON
    assert not offered, (
        f"the panel offers {sorted(offered)}: the client waits two minutes, reads a refusal, and "
        f"the pass they paid for finishes into nothing")


def test_a_dropped_connection_does_not_leave_the_PRODUCT_page_dead():
    """`act` awaits a POST. A dropped connection rejects it, and without a `finally` the handler
    threw before restoring `_prod.busy` — every button on the surface then stayed disabled behind
    a spinner that never stopped, with a reload the client had no reason to try as the only
    remedy."""
    html = (ROOT / "openfactory/api/panel.html").read_text()
    body = html.split("async function prodLook(")[1].split("\nasync function ")[0]
    assert "finally{" in body.replace(" ", ""), (
        "prodLook has no finally — one rejected fetch kills every button on the page")
    assert "_prod.busy=false" in body.replace(" ", "").replace("_prod.busy = false", "_prod.busy=false")


@pytest.mark.asyncio
async def test_product_status_does_not_hand_the_client_the_TEAMS_diagnosis(monkeypatch):
    """Found by LOOKING at the PO's page, not by reading code — it renders in both themes, at the
    top, in bold: "could not read `.openfactory/product.yaml` in acme/dsk-context: could not check out
    acme/dsk-context (branch 'main')".

    A repository slug, a file path and a branch name, in front of a business analyst who can act
    on none of them and now believes the product is broken. `voice.unavailable` already existed
    for exactly this and says the true thing instead: the role cannot see the requirements, so its
    answers would be guesses, and the team has been told.

    THE DIAGNOSIS IS NOT DISCARDED — it travels under `detail` and goes to the log. Losing it
    would trade one bad outcome for a worse one: nobody able to fix the thing."""
    from openfactory import actions
    from openfactory.actions import catalog

    class _Broken:
        available = False

        def context(self):
            class _C:
                corpus = None
            return _C()

        def status_line(self):
            return ("product module unavailable: could not read `.openfactory/product.yaml` in "
                    "acme/dsk-context (branch 'main')")

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (_Broken(), project, None))
    outcome = await actions.perform("product_status", by=_actor(), project="acme")

    assert outcome.ok, outcome.message
    assert "acme/dsk-context" not in outcome.message, outcome.message
    assert ".openfactory/product.yaml" not in outcome.message, outcome.message
    # asserted on the PROPERTY, not on a spelling: the client is told the truth about what the
    # role can and cannot do, in their own language, with no diagnosis in it
    assert outcome.message.strip() and "product module" not in outcome.message
    assert "time" in outcome.message.lower(), (
        f"the client was not told anybody knows: {outcome.message}")
    # …and the team can still read it
    assert "acme/dsk-context" in outcome.data["detail"]
    assert outcome.data["available"] is False


@pytest.mark.asyncio
async def test_a_HEALTHY_corpus_still_reports_what_it_sees(monkeypatch):
    """The positive twin. Routing everything through `unavailable` would make the guard above pass
    and the status line useless — a page that always says "I cannot see it" is not safer, it is
    broken in the other direction."""
    from openfactory import actions
    from openfactory.actions import catalog

    class _Req:
        pass

    class _Corpus:
        requirements = [_Req(), _Req(), _Req()]

        def promises(self):
            return [_Req()]

    class _Fine:
        available = True

        def context(self):
            class _C:
                corpus = _Corpus()
            return _C()

        def status_line(self):
            return "product module ready on acme/dsk-context — 3 requirements, 2 warnings"

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (_Fine(), project, None))
    outcome = await actions.perform("product_status", by=_actor(), project="acme")

    assert outcome.ok, outcome.message
    # the numbers ARE reported — routing everything through "I cannot see it" would be broken in
    # the other direction, which is what this twin exists to catch
    assert "3" in outcome.message and outcome.data["requirements"] == 3
    assert outcome.data["accepted"] == 1 and outcome.data["available"] is True
    # …and the operator's line is nowhere near the client, on the path that ships every day
    assert "acme/dsk-context" not in outcome.message, outcome.message
    assert "acme/dsk-context" in outcome.data["detail"]


@pytest.mark.asyncio
async def test_a_typed_sentence_runs_the_triage_instead_of_talking_about_it(monkeypatch):
    """The behaviour the gap was about, RUN. "faz a triagem do board" typed into the panel used
    to come back as conversation while the same words in Slack ran the sweep."""
    from openfactory import actions
    from openfactory.actions import catalog

    class _M:
        def triage_board(self):
            class _R:
                observations, skipped = [], []
            return _R(), ""

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (_M(), project, None))

    async def _never():
        raise AssertionError("it dispatched a conversation for a sentence it recognised")

    monkeypatch.setattr(catalog, "_connected", _never)
    outcome = await actions.perform("product_say", by=_actor(), project="acme",
                                    message="faz a triagem do board")

    assert outcome.ok, outcome.message
    assert outcome.data["read_as"] == "triage"
    assert outcome.data["performed"] == "product_triage"


@pytest.mark.asyncio
async def test_an_unrecognised_sentence_still_reaches_the_CONVERSATION(monkeypatch):
    """The fallback, and it is the whole reason the table is small. A matcher that swallowed
    everything it half-recognised would turn "e o segundo?" into a board report — so anything
    unmatched goes to the turn that remembers, exactly as before."""
    from openfactory import actions
    from openfactory.actions import catalog

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (object(), project, None))
    reached = {}

    class _Client:
        async def execute_workflow(self, name, inp, **_kw):
            reached["workflow"] = name
            return {"ok": True, "answer": {"ok": True, "text": "claro, o segundo é o fechamento"}}

    async def _connected():
        return _Client(), None

    monkeypatch.setattr(catalog, "_connected", _connected)
    outcome = await actions.perform("product_say", by=_actor(), project="acme",
                                    message="e o segundo?")

    assert outcome.ok, outcome.message
    assert reached["workflow"] == "ProductSayWorkflow"
    assert "read_as" not in outcome.data, "an ordinary sentence was routed as an intent"


@pytest.mark.asyncio
async def test_a_sentence_cannot_reach_what_the_TYPISTS_credential_cannot(monkeypatch):
    """The authorisation question the routing raises, answered by not answering it twice.

    A floor-only credential typing a product sentence is refused by `perform`'s scope check — the
    same one that refuses `product_triage` asked for directly. Routing gains no authority, which
    is the entire argument for routing through `perform` rather than calling the row."""
    from openfactory import actions
    from openfactory.actions import catalog
    from openfactory.actions.base import FLOOR, Actor

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (object(), project, None))
    floor_only = Actor(id="ops", display="Ops", via="cli", admin=True,
                       scopes=frozenset({FLOOR}))

    outcome = await actions.perform("product_say", by=floor_only, project="acme",
                                    message="faz a triagem do board")
    assert not outcome.ok and outcome.code == actions.DENIED, outcome


# ── the client's own documentation is INPUT, not competition ─────────────────────────────────────

def _survey_with(docs, **over):
    from openfactory.onboarding.context import RepoSurvey

    return RepoSurvey(repo="acme/billing", existing_docs=list(docs), **over)


def test_the_survey_SHOWS_the_documentation_the_client_already_wrote():
    """*"if there is client documentation in that context, great — it is part of it; the reverse-
    engineering backfill does not have to be code alone."* — the product owner, on #99 piece 2b.

    `RepoSurvey.existing_docs` has carried the paths since the field was written, and its own
    docstring says what they are for: "the first thing a reverse-engineering session should read,
    and the last thing it should overwrite". NOTHING READ IT. `survey` collected them,
    `render_survey` never mentioned them and `build_prompt` renders this, so every backfill was
    code-only and a client who had written down how their system works watched it be re-derived
    from scratch. Care recorded in a comment, unasserted — the shape this repository keeps paying
    for."""
    from openfactory.onboarding.context import render_survey

    out = render_survey(_survey_with(["README.md", "docs/arquitetura.md", "docs/adr/0001.md"]),
                        language="pt")
    assert "docs/arquitetura.md" in out and "docs/adr/0001.md" in out, out[:600]


def test_the_survey_says_it_found_NONE_rather_than_going_quiet():
    """Absence reads as compliance: a section that simply vanishes when there is no documentation
    is indistinguishable from a survey that never looked, and the reader cannot tell whether the
    client has none or whether we failed to read it."""
    from openfactory.onboarding.context import render_survey

    for lang, expected in (("pt", "nenhuma encontrada"), ("en", "none found")):
        out = render_survey(_survey_with([]), language=lang)
        assert expected in out, out[:400]


def test_a_document_that_DISAGREES_with_the_code_is_a_question_not_a_choice():
    """The most valuable thing this pass can find, and the failure mode is an agent quietly
    picking the code because the code is what it can see. The instruction travels with the list
    or the list is decoration."""
    from openfactory.onboarding.context import build_prompt, render_survey

    survey = _survey_with(["docs/regras-de-fechamento.md"])
    for lang, needle in (("pt", "não escolha em silêncio"), ("en", "do not choose in silence")):
        assert needle in render_survey(survey, language=lang)

    # …and it reaches the AGENT, not only the document the client reads
    assert "docs/regras-de-fechamento.md" in build_prompt(survey, language="pt")


def test_the_spend_scan_sees_the_TO_THREAD_shape_this_file_uses_three_lines_away():
    """The evasion an adversarial pass found in the guard written one commit earlier.

    `_spent_in_process` matched only `module.verb(...)`. But the row next door writes
    `await asyncio.to_thread(module.triage_board)` — the verb is an ARGUMENT there, never the
    callee — so a developer copying the cheap sibling's shape onto an expensive verb produced
    exactly the defect the guard exists to stop, and the guard said nothing."""
    verbs = _agent_spending_verbs((ROOT / "openfactory/product/module.py").read_text())
    for planted in (
        "async def _x():\n    r, e = await asyncio.to_thread(module.review_needs_action)\n",
        "async def _x():\n    r = await asyncio.to_thread(lambda: module.baseline(areas=None))\n",
        "async def _x():\n    r = loop.run_in_executor(None, module.draft)\n",
    ):
        assert _spent_in_process(planted, verbs), f"the scan is blind to:\n{planted}"

    # …and the cheap verb in the same shape is still not accused
    assert not _spent_in_process(
        "async def _y():\n    r, e = await asyncio.to_thread(module.triage_board)\n", verbs)


def test_a_typed_sentence_is_routed_from_the_door_the_PANEL_actually_opens():
    """The gap was reopened by its own fix, and only a reachability question finds that.

    `_say_as_an_intent` was wired into `product_say` — a row called by no panel button, no CLI
    verb and no channel. The panel's ONE free-text box calls `product_ask`. So "faz a triagem do
    board" still spent a drafting pass and came back as prose, while every guard stayed green
    because they all drove `product_say` directly."""

    named = _rows_named_by_the_panel()
    doors = {row for row in named
             if "_say_as_an_intent" in ast.unparse(next(
                 (n for n in ast.walk(ast.parse((ROOT / "openfactory/actions/catalog.py").read_text()))
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == f"_{row}"), ast.Pass()))}
    assert doors, (
        f"no row the panel names routes a typed sentence — the panel offers {sorted(named)} and a "
        f"client typing a command gets prose about it. The routing is reachable by nothing.")
    assert "product_ask" in doors, (
        "the panel's free-text box is `product_ask`; if that row does not route, the client's only "
        "way to type a command does not work")


@pytest.mark.asyncio
async def test_the_ASK_box_runs_the_triage_rather_than_drafting_about_it(monkeypatch):
    """RUN through the row the panel really calls, not the one the guards preferred."""
    from openfactory import actions
    from openfactory.actions import catalog

    class _M:
        def triage_board(self):
            class _R:
                observations, skipped = [], []
            return _R(), ""

    project = type("_P", (), {"name": "acme", "language": "pt-BR", "product": None})()
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (_M(), project, None))

    async def _never():
        raise AssertionError("it spent a drafting pass on a sentence it recognised")

    monkeypatch.setattr(catalog, "_connected", _never)
    outcome = await actions.perform("product_ask", by=_actor(), project="acme",
                                    question="faz a triagem do board")

    assert outcome.ok, outcome.message
    assert outcome.data["performed"] == "product_triage"


def test_the_waiting_sentence_speaks_the_CLIENTS_language_and_no_slugs():
    """It read "2 proposal(s) waiting on a person (accept, draft)" — English, in a thread whose
    every other line is the product's Portuguese voice, listing two of this platform's internal
    entry kinds. `kind` is a routing key, not a word anybody outside this codebase has a meaning
    for; it belongs in the data for a surface to group by."""
    from openfactory.product.voice import waiting_on_you

    assert "esperando" in waiting_on_you(count=2, language="pt-BR")
    assert "waiting" in waiting_on_you(count=2, language="en")
    assert "Nada" in waiting_on_you(count=0, language="pt-BR")
    assert "Nothing" in waiting_on_you(count=0, language="en")
    # an untranslated language gets understandable text rather than a KeyError on a client's page
    assert waiting_on_you(count=1, language="fr-FR").strip()


def test_the_slow_passes_have_a_door_even_though_the_panel_has_none():
    """Taking the two long rows off the panel is only honest if they are reachable somewhere.
    Otherwise the fix for "a button that times out" is "a capability nobody can use", which is
    the same defect wearing a tidier face."""
    cli = (ROOT / "openfactory/cli.py").read_text()
    for row in sorted(_TOO_SLOW_FOR_A_BUTTON):
        assert f'"{row}"' in cli, (
            f"{row} is off the panel by design and has no CLI verb either — it is now reachable "
            f"by nothing at all")


def test_no_product_row_interpolates_a_RAW_EXCEPTION_into_the_client_sentence():
    """The class, guarded — an adversarial pass found two rows shipping it in the same session
    that closed the same defect one row over.

    `refused(FAILED, f"… ({str(exc)[:160]})")` puts a Temporal timeout, a connection reset or a
    provider's stack text in front of a business analyst. It does not matter that the text came
    from an engine rather than from a repo slug: the client can act on neither, and both make the
    product look broken rather than busy. `log.exception` above each keeps the diagnosis whole.

    Scoped to the PRODUCT rows on purpose. The floor's rows answer an operator who has a checkout
    and wants the error — widening this would be asserting a rule nobody agreed to."""
    tree = ast.parse((ROOT / "openfactory/actions/catalog.py").read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or not node.name.startswith("_product_"):
            continue
        for call in ast.walk(node):
            if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "refused"):
                continue
            # the message is the second positional argument
            if len(call.args) < 2 or not isinstance(call.args[1], ast.JoinedStr):
                continue
            rendered = ast.unparse(call.args[1])
            if re.search(r"\bstr\(\s*exc\s*\)|\{exc\b", rendered):
                offenders.append(f"{node.name}:{call.lineno}")
    assert not offenders, (
        f"these put a raw exception in a client's sentence: {offenders} — log it, and tell the "
        f"person what happened in words they can act on")


def test_a_write_answers_with_the_CLIENTS_sentence_and_not_a_branch_slug():
    """`_write_outcome` is shared by every product write, and it prefixed the client's own
    sentence with a branch ref and a forge URL:

        accepted requirement 12 — req/0012-fechamento-mensal
        (https://github.com/acme/dsk-context/pull/57). Pronto — escrevi…

    `detail` IS the sentence `product/voice.py` composed for somebody who was never meant to open
    a pull request. Both decorations already travel in the data for a surface whose reader is an
    operator, which is the same split this session made three times over."""
    from openfactory.actions.catalog import _write_outcome

    class _R:
        ok, detail, url, ref = True, "Pronto — escrevi e mandei para o time conferir.", \
            "https://github.com/acme/dsk-context/pull/57", "req/0012-fechamento-mensal"
        number, merged, existed = 12, False, False

    out = _write_outcome(_R(), did="accepted requirement 12")
    assert out.message == "Pronto — escrevi e mandei para o time conferir."
    assert out.data["url"].endswith("/pull/57") and out.data["ref"].startswith("req/")

    # …and a module that said nothing still reports that something happened
    class _Silent(_R):
        detail = ""

    quiet = _write_outcome(_Silent(), did="accepted requirement 12")
    assert "accepted requirement 12" in quiet.message
    assert "https://" not in quiet.message


# ── the window the idempotency argument skipped ──────────────────────────────────────────────────

class _Forge:
    """A forge with the two facts `propose_baseline` asks for, and a counter for what it did."""

    def __init__(self, *, branches=(), pr_opens=True):
        self.branches, self.pr_opens = list(branches), pr_opens
        self.opened, self.searched = [], 0

    def list_branches(self):
        return list(self.branches)

    def pr_for_head(self, *_a, **_k):
        # "" is "asked, and there is none". `None` means the question could not be asked, and
        # `propose_baseline` refuses on it deliberately — a fake returning None would exercise
        # that refusal and prove nothing about the arm under test.
        self.searched += 1
        return ""

    def open_pr(self, **kw):
        if not self.pr_opens:
            return None
        self.opened.append(kw)
        return "https://forge/pr/9"


def test_a_pushed_branch_with_no_pull_request_does_not_WEDGE_the_first_pass():
    """The window between the push and the pull request — a rate limit, an expired token, a worker
    dying in between.

    Without this arm the verb is permanently broken on that repository: the next run finds no pull
    request, clones fresh, commits, and its `push -u` is rejected as non-fast-forward against the
    branch the first attempt left. Every later attempt fails identically, on a repository where
    nothing is wrong except that a PR was never opened.

    Found by attacking the RETRY the workflow used to do — the docstring justifying it called the
    verb idempotent, which was true of the happy path and asserted of all of them."""
    from openfactory.product import authoring

    forge = _Forge(branches=["main", "product/baseline"])
    result = authoring.propose_baseline(
        forge=forge, docs_repo="acme/ctx", clone_url="https://x/acme/ctx.git", base="main",
        product="acme", observations=7, covered=["billing"], files={"a.md": "x"})

    assert result.ok and result.existed, result.detail
    assert result.url == "https://forge/pr/9"
    assert forge.opened, "it did not open the pull request the previous attempt never got to"
    # …and it did NOT write a second time: no clone, no commit, no push happened on this path
    assert "product/baseline" in result.ref


def test_the_wedge_arm_reports_honestly_when_the_pull_request_STILL_will_not_open():
    """Two failures in a row is a human's problem, and the sentence has to say what state the
    repository is in — the branch IS there, so "nothing was written" would be a lie."""
    from openfactory.product import authoring

    forge = _Forge(branches=["product/baseline"], pr_opens=False)
    result = authoring.propose_baseline(
        forge=forge, docs_repo="acme/ctx", clone_url="https://x/acme/ctx.git", base="main",
        product="acme", observations=7, covered=[], files={"a.md": "x"})

    assert not result.ok
    assert "já está enviada" in result.detail and "à mão" in result.detail


@pytest.mark.parametrize("path,is_doc", [
    ("README.md", True),
    ("docs/arquitetura.md", True),
    ("docs/adr/0001-conciliacao.md", True),
    (".github/CONTRIBUTING.md", True),
    # a documentation SUFFIX is not documentation ANYBODY WROTE about this product
    ("LICENSE.txt", False),
    ("requirements.txt", False),
    ("CHANGELOG.md", False),
    (".github/ISSUE_TEMPLATE/bug.md", False),
    # …and somebody else's manual is not the client's account of their own system
    ("vendor/lib/docs/guide.md", False),
    ("node_modules/left-pad/README.md", False),
])
def test_only_documentation_the_CLIENT_wrote_is_shown_back_to_them(path, is_doc):
    """The section added one commit ago published `LICENSE.txt`, `requirements.txt` and a vendored
    library's manual under "documentação que o cliente já escreveu".

    `existing_docs` had been collected and read by NOTHING, so "every `.txt` is a doc" cost
    nothing. The moment it is shown to the client, that list tells them we did not read what we
    are about to reason over — and the agent is asked to weigh a dependency pin against the code.

    The classifier is fixed rather than the renderer: `files.docs` has exactly one consumer, so
    tightening it there costs nothing and filtering at the display would leave the wrong list in
    the data for the next reader."""
    from pathlib import Path as _P

    from openfactory.onboarding.context import _is_client_doc

    assert _is_client_doc(path, _P(path).suffix.lower()) is is_doc
