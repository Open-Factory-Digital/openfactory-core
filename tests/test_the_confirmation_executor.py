"""What a "yes" does, and the fact that every surface does the same thing with it — #105.

The ten confirmation branches used to live inside `runtime/slack/product_channel.py::_handle`, so
the panel's answer route imported the Slack package to run a write — a documented crossing in
`test_provider_seams`, now deleted. They are `openfactory/product/confirm.py` and the preamble
(`may_act` → compare-and-swap pop → "somebody beat us") is INSIDE, because that preamble is not
boilerplate: the pop is a compare-and-swap on the staged object's identity plus the fingerprint
the button was posted for, and leaving it to the caller reopens the window in every new transport.

What this file is for is the part an extraction loses quietly:

  1. THE KINDS — every kind that can be STAGED must be one the executor can PERFORM. Derived from
     the `remember(...)` sites, because a hand-kept list is a list somebody forgets.
  2. THE CLICK'S MEMORY — routing through `handle` used to record the turn; a direct call does not
     unless somebody wrote it, and nothing asserted it before.
  3. THE THIRD CALLER — `product_answer`, the pair of `product_pending`, and the reason it runs on
     the worker rather than in whichever process took the request.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import openfactory.product.channel as pc
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.product import confirm as executor

ADMIN, OUTSIDER = "U1", "U9"
KEY = "C0PROD"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


def _project():
    return Project(name="books", repo_path="/t",
                   tracker=ProviderRef(kind="github", repo="a/b"),
                   forge=ProviderRef(kind="github", repo="a/b"),
                   product=ProductConfig(docs_repo="a/docs", channel_id=KEY,
                                         admins=[ADMIN], agent_name="Nina"))


class _Module:
    """Boundary fake: the write is recorded, everything between is production code."""

    def __init__(self):
        self.wrote: list[str] = []

    def note_fact(self, *, term, body, said_by, where=""):
        from types import SimpleNamespace

        self.wrote.append(term)
        return SimpleNamespace(ok=True, existed=False, detail="", ref="")


def _stage(term="erp", body="a firma usa Primavera"):
    pc.forget(KEY)
    pc.remember(KEY, {"kind": "fact", "term": term, "body": body, "said_by": ADMIN})
    entry = pc.pending_for(KEY)
    return pc.proposal_token(KEY, entry), entry


# ── 1. every kind that can be staged can be performed ───────────────────────────────────────────

def _staged_kinds() -> set[str]:
    """The `kind` of every proposal this codebase can stage, READ OFF the `remember(...)` sites.

    Listing them by hand is the failure this derivation exists to prevent: a tenth kind staged by
    a new branch would fall through the dispatch table to the DRAFT executor, which reads
    `entry["answer"]` — so the client's yes would raise a KeyError, the handler would answer "algo
    quebrou do meu lado", and every test here would still be green.
    """
    kinds: set[str] = set()
    for path in ROOT.joinpath("openfactory").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "remember"):
                continue
            for arg in node.args:
                if not isinstance(arg, ast.Dict):
                    continue
                for key, value in zip(arg.keys, arg.values, strict=False):
                    if (isinstance(key, ast.Constant) and key.value == "kind"
                            and isinstance(value, ast.Constant)):
                        kinds.add(value.value)
    return kinds


def test_the_scan_finds_the_staging_sites_at_all():
    """The positive twin, first. `assert every kind is handled` passes just as happily over a scan
    that found nothing — this repository has shipped three guards that were green over live
    defects for exactly that reason."""
    kinds = _staged_kinds()

    assert {"fact", "accept", "close", "draft"} <= kinds, (
        f"the staging-site scan found {sorted(kinds)} — it has broken, and a broken scan reports "
        f"an empty set, which reads as compliance")


def test_every_staged_kind_has_an_executor():
    """The whole point of a dispatch table over a chain of `if`: the question is answerable.

    `draft` is the documented default and the only one allowed to be missing from the table — the
    original chain ended with a bare `if waiting and is_yes(...)`, so an untyped entry is a
    requirement proposal. Anything ELSE missing is a yes that raises."""
    missing = sorted(_staged_kinds() - set(executor._EXECUTORS) - {"draft"})

    assert not missing, (
        f"these kinds can be staged and have no executor: {missing}. A yes on one falls to the "
        f"draft branch, which reads `entry['answer']` — the client hears 'algo quebrou do meu "
        f"lado' about a proposal they correctly approved")


def test_the_table_has_no_executor_for_a_kind_nobody_stages():
    """The other direction, and it is not symmetry for its own sake: a branch kept alive for a
    kind no site produces is code nothing can reach, which is this repository's signature defect
    with the arrow reversed."""
    unreachable = sorted(set(executor._EXECUTORS) - _staged_kinds())

    assert not unreachable, (
        f"{unreachable} are executors for kinds nothing stages — either a staging site was "
        f"deleted and its branch left behind, or the scan stopped seeing it")


# ── 2. the preamble is inside, and it is the same one for every transport ───────────────────────

def test_an_unauthorised_yes_does_not_consume_the_proposal():
    """AUTHZ BEFORE POP. The real approver's later yes still has to find it — the rule that used
    to be repeated in eight branches and is now stated once."""
    _, entry = _stage()
    module = _Module()

    said = executor.confirm(_project(), key=KEY, entry=entry, module=module, user=OUTSIDER,
                            lang="pt-BR")

    assert module.wrote == [], "an outsider's yes performed the write"
    assert pc.pending_for(KEY) is not None, "an unauthorised yes consumed the proposal"
    assert said, "the refusal was silent — indistinguishable from a broken bot"


def test_a_proposal_replaced_since_the_read_is_NOT_performed():
    """The compare-and-swap, driven at the seam it protects: the caller holds the entry it read
    and judged, and something else was staged meanwhile. Identity, not equality — every `remember`
    stores a fresh dict, so a replacement can never impersonate the proposal that was approved."""
    _, entry = _stage("erp", "a firma usa Primavera")
    pc.remember(KEY, {"kind": "fact", "term": "erp", "body": "a firma usa SAP", "said_by": ADMIN})
    module = _Module()

    said = executor.confirm(_project(), key=KEY, entry=entry, module=module, user=ADMIN,
                            lang="pt-BR")

    assert module.wrote == [], "the yes performed a proposal that had already been replaced"
    assert pc.pending_for(KEY) is not None, "the replacement was destroyed by a stale yes"
    assert said, "a yes that performed nothing said nothing"


def test_the_receipt_goes_out_BEFORE_THE_WRITE():
    """Order is the whole content of the promise. Every branch reaches a checkout, the client's
    board or an agent, and the person has just approved something irreversible — a receipt that
    arrives with the answer is not a receipt.

    IT IS ASSERTED ON THE ORDER, AND THE FIRST VERSION OF THIS TEST WAS DECORATION. It was named
    "before the authorisation" and asserted the same two events, so moving `on_it` past `may_act`
    left it green: for an authorised person both orders produce receipt-then-write. What can
    actually break is the receipt not preceding the slow part, so that is what this says.
    """
    _, entry = _stage()
    order: list[str] = []

    class _Watched(_Module):
        def note_fact(self, **kw):
            order.append("wrote")
            return super().note_fact(**kw)

    module = _Watched()
    executor.confirm(_project(), key=KEY, entry=entry, module=module, user=ADMIN, lang="pt-BR",
                     on_it=lambda: order.append("receipt"))

    assert module.wrote == ["erp"], "the write never ran, so the order proves nothing"
    assert order == ["receipt", "wrote"], order


# ── 3. the click keeps its turn in the conversation's memory ────────────────────────────────────

def test_an_approved_CLICK_still_lands_in_the_conversation_memory(monkeypatch):
    """IT USED TO BE FREE AND IS NOT ANY MORE. The click resolved through the Slack `handle`,
    which records the incoming turn on arrival and her reply afterwards (ADR-0024 layer 0). Now
    that the gate calls the executor directly, the recording is a line somebody had to write — and
    without it the transcript shows a proposal nobody ever answered, so the next turn re-offers,
    or discusses, something the person already approved."""
    from openfactory.memory import transcript

    said: list[tuple[str, str]] = []
    monkeypatch.setattr(transcript, "record",
                        lambda name, **kw: said.append((kw.get("role"), kw.get("text"))) or "ts")

    token, _ = _stage()
    module = _Module()
    pc.confirm_by_click(_project(), token=token, approved=True, user=ADMIN, module=module)

    assert module.wrote == ["erp"], "the click did not reach the write"
    assert ("person", "sim") in said, f"the click left no turn in the memory: {said}"
    assert any(role == "agent" and text for role, text in said), (
        f"her answer to the confirmation was never recorded: {said}")


def test_a_transcript_OUTAGE_never_costs_the_person_their_write(monkeypatch):
    """The record must never be able to eat the answer. Both calls are wrapped, and the arm that
    matters is the first one: it happens BEFORE the write, so an unguarded raise there would turn
    a DynamoDB blip into an approval that silently did nothing."""
    from openfactory.memory import transcript

    def _boom(*_a, **_kw):
        raise RuntimeError("dynamo is having a day")

    monkeypatch.setattr(transcript, "record", _boom)

    token, _ = _stage()
    module = _Module()
    code, sentence = executor.answer_staged(_project(), token=token, approved=True, user=ADMIN,
                                            module=module)

    assert (code, module.wrote) == ("done", ["erp"])
    assert sentence, "the write happened and the person was told nothing"


def test_a_crash_in_a_branch_still_answers_the_person(monkeypatch, caplog):
    """SILENCE IS THE WORST ANSWER, and this catch-all came WITH the executor: routing through
    `handle` used to supply it. Without it a crash reaches the listener as an exception and the
    person who clicked gets nothing — indistinguishable from being ignored, and invisible to us
    until they complain."""
    import logging

    token, _ = _stage()

    class _Broken(_Module):
        def note_fact(self, **_kw):
            raise RuntimeError("the corpus checkout died")

    with caplog.at_level(logging.ERROR, logger="openfactory.product.confirm"):
        code, sentence = executor.answer_staged(_project(), token=token, approved=True,
                                                user=ADMIN, module=_Broken())

    assert code == "done" and sentence, "a crashing branch answered with silence"
    assert any("OPENFACTORY_PRODUCT_MUTE" in r.getMessage() for r in caplog.records), (
        "the mute is invisible in the logs, so nobody would ever find it")


# ── 4. the third caller: the `product_answer` row ───────────────────────────────────────────────

def _actor(**kw):
    from openfactory.actions import Actor

    return Actor(id=kw.pop("id", "ana"), display="Ana", via=kw.pop("via", "panel"), admin=True,
                 scopes=frozenset({"product"}), **kw)


@pytest.fixture
def _resolvable(monkeypatch):
    """A project the row can resolve, so a refusal is the row's and never `no such project` —
    the trap this suite already records once, where deleting every consent check stayed green."""
    from openfactory.actions import catalog

    project = _project()
    monkeypatch.setattr(catalog, "_product_module",
                        lambda _name, **_kw: (object(), project, None))
    return project


@pytest.mark.asyncio
async def test_product_answer_refuses_without_consent(_resolvable):
    from openfactory.actions import catalog

    outcome = await catalog._product_answer(project="books", token=f"{KEY}|abc", answer="approve",
                                            by=_actor())

    assert not outcome.ok and outcome.code == catalog.INVALID, outcome.message
    assert "yes" in outcome.message, outcome.message


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["sim", "true", "", "maybe"])
async def test_product_answer_refuses_a_third_thing(_resolvable, answer):
    """A question with two buttons cannot be answered with a third thing. `sim` is the one that
    matters: it is what a client would type, and accepting it here would mean the transport's
    vocabulary depends on which surface you came from."""
    from openfactory.actions import catalog

    outcome = await catalog._product_answer(project="books", token=f"{KEY}|abc", answer=answer,
                                            by=_actor(), yes=True)

    assert not outcome.ok and outcome.code == catalog.INVALID, outcome.message


@pytest.mark.asyncio
async def test_product_answer_refuses_without_a_token(_resolvable):
    from openfactory.actions import catalog

    outcome = await catalog._product_answer(project="books", token="  ", answer="approve",
                                            by=_actor(), yes=True)

    assert not outcome.ok and outcome.code == catalog.INVALID
    assert "product_pending" in outcome.message, (
        "the refusal does not say where a token comes from — the pair is the whole design")


class _Engine:
    """The durable engine, doubled at the seam the row actually uses."""

    def __init__(self, raw):
        self.raw, self.seen = raw, []

    async def execute_workflow(self, name, inp, **kw):
        self.seen.append((name, inp, kw.get("id", "")))
        return self.raw


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome_name,code", [
    ("unauthorized", "denied"),
    ("gone", "conflict"),
    ("replaced", "conflict"),
    ("expired", "conflict"),
])
async def test_product_answer_maps_each_named_outcome(_resolvable, monkeypatch, outcome_name,
                                                      code):
    """THE OUTCOME IS CARRIED, NEVER INFERRED FROM THE PROSE. Telling "unauthorized" apart from
    "done" by comparing Portuguese is how a refusal gets recorded as a decision — the reason the
    gate returns a pair at all (C-33), and it has to survive the trip through the worker."""
    from openfactory.actions import catalog

    engine = _Engine({"outcome": outcome_name, "message": "não deu"})
    monkeypatch.setattr(catalog, "_connected", _returns(engine))

    result = await catalog._product_answer(project="books", token=f"{KEY}|abc", answer="approve",
                                           by=_actor(), yes=True)

    assert not result.ok and result.code == code, (result.code, result.message)
    assert result.message == "não deu", "the client's sentence was replaced by a generic one"


def _returns(engine):
    async def _connected():
        return engine, None

    return _connected


@pytest.mark.asyncio
async def test_product_answer_dispatches_to_the_worker_and_carries_the_answer(_resolvable,
                                                                              monkeypatch):
    """A yes on an `accept` chains into the breakdown and a yes on an `align` ends in a model call,
    and WHICH KIND A TOKEN NAMES is not knowable until the entry is read — which only the pop that
    performs it may do. So the row dispatches: answering in-process would run an agent on
    somebody's laptop, or in the panel's container, which carries the harness binary and no
    credential for it."""
    from openfactory.actions import catalog

    engine = _Engine({"outcome": "done", "message": "Registrado. **erp**"})
    monkeypatch.setattr(catalog, "_connected", _returns(engine))

    result = await catalog._product_answer(project="books", token=f"{KEY}|abc", answer="reject",
                                           by=_actor(via="cli"), yes=True)

    assert result.ok, result.message
    (name, inp, wid), = engine.seen
    assert name == "ProductAnswerWorkflow", name
    assert (inp.token, inp.approved, inp.actor, inp.via) == (f"{KEY}|abc", False, "ana", "cli")
    assert "**" not in result.message, (
        "the row returned mrkdwn — the panel renders it as literal asterisks")


@pytest.mark.asyncio
async def test_the_workflow_id_cannot_be_shaped_by_the_caller(_resolvable, monkeypatch):
    """The token's key half is caller-supplied. A workflow id is an identity in somebody else's
    system, so anything outside the safe set becomes `-` rather than travelling into it."""
    from openfactory.actions import catalog

    engine = _Engine({"outcome": "done", "message": "ok"})
    monkeypatch.setattr(catalog, "_connected", _returns(engine))

    await catalog._product_answer(project="books", token="a b/c\n|x", answer="approve",
                                  by=_actor(), yes=True)

    (_, _, wid), = engine.seen
    assert " " not in wid and "/" not in wid and "\n" not in wid, wid


@pytest.mark.asyncio
async def test_an_unreadable_engine_is_reported_and_nothing_is_performed(_resolvable,
                                                                         monkeypatch):
    from openfactory.actions import catalog

    class _Dead:
        async def execute_workflow(self, *_a, **_kw):
            raise RuntimeError("temporal: deadline exceeded reaching namespace acme.x9k2")

    monkeypatch.setattr(catalog, "_connected", _returns(_Dead()))

    result = await catalog._product_answer(project="books", token=f"{KEY}|abc", answer="approve",
                                           by=_actor(), yes=True)

    assert not result.ok and result.code == catalog.FAILED
    assert "deadline" not in result.message and "acme" not in result.message, (
        f"the engine's diagnosis went to the client: {result.message}")


# ── 5. the class rule: a row may not run a confirmation in the caller's process ─────────────────

def _agent_reaching_kinds() -> set[str]:
    """Staged kinds whose executor calls a module verb that reaches an agent, DERIVED.

    Two of the nine do today (`accept` chains into `break_down`, `align` ends in
    `_role().ask_json`) and the number is not the point — a tenth added later is why this is read
    off the source instead of written down."""
    # BORROWED, NOT COPIED. `_agent_spending_verbs` closes `_role`/`ask_json`/`survey` over
    # `ProductModule` transitively; a second copy here would answer a different question the day
    # somebody widens the seed, and the two would disagree about which rows are safe.
    from test_the_product_role_lives_outside_slack import _agent_spending_verbs

    spending = _agent_spending_verbs((ROOT / "openfactory/product/module.py").read_text())
    tree = ast.parse((ROOT / "openfactory/product/confirm.py").read_text())
    bodies = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def _spends(fn, seen: frozenset[str]) -> bool:
        """CLOSED OVER THIS FILE'S OWN HELPERS, and the first version was not — it looked only for
        `module.<verb>` in the executor's own body and answered `align` alone. `accept` calls
        `module.accept` (cheap) and then hands the module to `_also_broke_it_down`, which is where
        `break_down` is: exactly one hop, and exactly the hop a reader would miss."""
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            if (isinstance(node.func, ast.Attribute)
                    and getattr(node.func.value, "id", "") == "module"
                    and node.func.attr in spending):
                return True
            name = getattr(node.func, "id", "")
            if name in bodies and name not in seen and _spends(bodies[name], seen | {name}):
                return True
        return False

    return {kind for kind, fn in executor._EXECUTORS.items()
            if fn.__name__ in bodies and _spends(bodies[fn.__name__], frozenset({fn.__name__}))}


def test_a_yes_can_cost_an_agent_pass_and_the_row_knows_it():
    """The measurement the `product_answer` row's process choice rests on. If this ever answers
    the empty set, the row is dispatching a workflow for nothing and somebody should be told —
    and if it grows, the argument only gets stronger."""
    kinds = _agent_reaching_kinds()

    assert kinds, ("no staged kind reaches an agent any more — either the derivation broke, or "
                   "`product_answer` can stop dispatching to the worker")
    assert {"accept", "align"} <= kinds, sorted(kinds)


def _reaches(names: set[str], source: str) -> list[tuple[str, int]]:
    """Where `source` reaches one of `names`, IN EITHER SHAPE.

    A CALL IS NOT ALWAYS THE CALLEE. `asyncio.to_thread(answer_staged, …)` hands the function
    somewhere else to be run — the idiom this very file's neighbours use three lines away, and the
    one somebody writing the obvious version of this row would reach for. A scan that saw only
    `answer_staged(...)` would walk straight past it; the agent-spend guard next door shipped with
    exactly that hole and it was live.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        callee = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if callee in names:
            found.append((callee, node.lineno))
        for arg in list(node.args) + [k.value for k in node.keywords]:
            for inner in ast.walk(arg):
                got = (getattr(inner, "id", "") if isinstance(inner, ast.Name)
                       else getattr(inner, "attr", "") if isinstance(inner, ast.Attribute) else "")
                if got in names:
                    found.append((got, inner.lineno))
    return sorted(set(found))


def test_the_executor_reach_scan_can_SEE_one():
    """The positive twin, and it plants BOTH shapes — a scan that only ever ran over a clean file
    is a scan nobody has watched find anything."""
    direct = _reaches({"answer_staged"}, "async def _r(**k):\n    return answer_staged(1)\n")
    handed = _reaches({"answer_staged"},
                      "async def _r(**k):\n    return await to_thread(answer_staged, 1)\n")

    assert [n for n, _ in direct] == ["answer_staged"], direct
    assert [n for n, _ in handed] == ["answer_staged"], handed
    # …and a row that dispatches by string is not accused, or the guard cries wolf on the fix
    assert not _reaches({"answer_staged"},
                        'async def _r(**k):\n    await c.execute_workflow("ProductAnswerWorkflow")\n')


def test_no_row_runs_the_confirmation_EXECUTOR_in_the_callers_process():
    """The class rule, stated for the seam the agent-spend scan cannot see.

    That scan looks for `module.<verb>` inside `catalog.py`, and a row calling `answer_staged`
    reaches `break_down` three hops away through two modules — invisible to it, and live the day
    somebody writes the obvious two-line version of this row. So: the catalogue may not call the
    executor or the gate at all; it dispatches and waits."""
    src = (ROOT / "openfactory/actions/catalog.py").read_text()
    forbidden = _reaches({"answer_staged", "confirm"}, src)

    assert not forbidden, (
        f"a row calls {sorted(forbidden)} directly: a yes on an `accept` or an `align` would run "
        f"an agent in whichever process served the request. Dispatch ProductAnswerWorkflow")
    # THE POSITIVE HALF, AND IT IS AN EXACT NAME RATHER THAN A SUBSTRING. `"x" in src` was the
    # first version and it passed over `ProductAnswerWorkflowX` — a typo'd dispatch is precisely
    # the failure the neighbouring registration guard exists for, and this one waved it through.
    from test_the_product_role_lives_outside_slack import _dispatched_workflow_names

    assert "ProductAnswerWorkflow" in _dispatched_workflow_names(src), (
        "no row dispatches the confirmation to the worker — the guard above is satisfied by the "
        "capability not existing at all")


def test_the_confirmation_workflow_is_registered_on_the_worker():
    """A workflow dispatched BY STRING and never registered is a NotFoundError at run time, in
    production, on the one path a client uses to say yes."""
    from openfactory.runtime.temporal import worker

    names = {getattr(w, "__name__", "") for w in _registered_workflows()}

    assert "ProductAnswerWorkflow" in names, sorted(names)
    assert worker.product_role_answer in worker.WORKER_ACTIVITIES, (
        "the activity the workflow calls is not registered — the workflow would start and then "
        "fail to find what it runs")


def _registered_workflows():
    """The list the Worker is built with, read off the source rather than by starting one."""
    import re

    src = (ROOT / "openfactory/runtime/temporal/worker.py").read_text()
    block = src[src.index("workflows=["):]
    block = block[:block.index("]")]
    from openfactory.runtime.temporal import workflow as wf

    return [getattr(wf, n) for n in re.findall(r"\b(\w+Workflow)\b", block) if hasattr(wf, n)]
