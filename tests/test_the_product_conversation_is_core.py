"""The product conversation is core: one settling stage, reached from the panel's own entry point.

THE MEASUREMENT THAT OPENED THIS (2026-08-25). `runtime/slack/product_channel.py` — 1,278 lines,
24 functions, zero Slack imports — was the product role's conversation handler, filed under a
vendor. Deleting the Slack package on that tree: 56 failed, 98 errors, 25 test modules
uncollectable, of which five were about Slack; the decision loop, the acceptance loop, the
confirmations, the client's release and memory recall all went with it. Worse than the address:
`ProductModule.settle_acceptance` — the client's "worked / did not work" that closes a delivery
(ADR-0025) — had exactly ONE production caller, in that file, and the panel's turn
(`activities._product_conversation`) reached `module.answer` and nothing else. So on a deployment
without Slack the sweep opened acceptance loops that no client could ever close, and nothing ever
closed the decisions the role had asked a person for.

WHAT THE MOVE RESCUED, AND WHAT IT DID NOT (the reviewer's measurement, same day). Two of the
stage's branches — a typed yes on a staged proposal, the notice for one that expired — now run on
the panel's path and find NOTHING there: every producer of a staged proposal (`offer_draft`, the
typed intents' `remember`) is chat-only, reached through `bot.py` and through nothing else, and on
a mixed deployment the keys never meet (Slack stages under `thread_ts or channel`, the panel reads
under `thread or project name`). The first version of this file claimed both as rescued; they were
green because the tests staged by hand. The claim is withdrawn, the gap is measured below
(`test_the_one_staging_producer_on_the_panel_s_path_is_the_second_yes`), and the two hand-staged
runs say what they are: the stage's behaviour under the panel's key, given a DRAFT producer that
does not exist. Since ADR-0047 one producer does reach the panel — `confirm()` staging the second
yes, the acceptance on the card, under the key the first yes was found under — and the guard says
so as the claim it is.

ADR-0038 D3 — *no capability may live in `runtime/<channel>/`* — had no guard at all; the file
`docs/core` names for it does not exist. This is that guard, in both directions:

  - NEGATIVE: no function in a channel package constructs a `ProductModule` or calls one of its
    methods. A channel renders and parses; it does not do.
  - POSITIVE: the capabilities the move rescued are reached from the panel's own entry point with
    no channel package in the graph — on the call graph AND by running the turn. Until #266 slice
    2 the turn that settled nothing also carried the draft for the panel's propose button; the
    panel's turn is the ONE turn engine now, which stages that draft under the panel's key and
    hears the "sim" typed after it — driven below, as that slice's acceptance.
  - THE GATE, ON THE NEW SURFACE: a "funcionou o #12" typed in the panel's product box reaches
    the client's release — by design, the panel is the reference surface (ADR-0038 D1) — through
    the same `may_act` the channel has asked since ADR-0025, refused for who is not on the list,
    performed for who is, and told WHICH surface the approver spoke from (`via`), because the gate
    used to say `slack` for a person who had never opened Slack.
  - THE TRANSPORT, READ BACK AT EVERY HOP IT LANDS ON: the catalog rows into the workflow input,
    the input into the module and the gates on the worker, the panel's own route into the gates
    and the module the gate builds, the two gates INSIDE the stage (`confirm`'s and the
    rejection's), the token route's reject gate, the module the token gate builds when handed
    none, and the answer row's empty fold — each hop DRIVEN with a value no surface mints and
    read where it lands, because a guard that read the keyword's name off the source passed
    with `via="slack"` hardcoded at two of them (the second review, 2026-08-25), and a run
    that handed a hop `panel` passed with `via="panel"` hardcoded at four more (the third,
    2026-08-26). The stage's default is read back too, by a run through the CHAT handler,
    which hands no transport and must be recorded as the channel it is.

Every guard here has a mutation in `tools/mutations/public_product_conversation_is_core.py`.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import time
from types import SimpleNamespace

import pytest

from tests.test_loops_are_reachable import _call_graph, _called_names, _reachable_from
from tests.the_sink_door import SINK_DOOR

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "openfactory"
CHAT_HANDLER = PACKAGE / "product" / "channel.py"
TURN_ENGINE = PACKAGE / "product" / "engine.py"
WORKER_TURN = PACKAGE / "runtime" / "temporal" / "activities.py"


# ── ADR-0038 D3, at last with a guard ───────────────────────────────────────────────────────────

def _channel_kinds() -> tuple[str, ...]:
    """Every channel kind this tree implements: the registry's own rows plus the rows the
    platform's own packages under `addons/` declare (`channel.<kind>`) — the chat channel is one
    of those since 2026-08-26, its code still in this tree until the export. In the public tree
    the packages are absent and so is their code, and the registry's rows are the whole list."""
    from vendor_addons import declared

    from openfactory.adapters.channel.registry import CHANNELS

    declared_kinds = [name.partition(".")[2] for name in declared() if name.startswith("channel.")]
    return tuple(sorted({*CHANNELS, *declared_kinds}))


def _channel_packages() -> list[pathlib.Path]:
    """`openfactory/runtime/<kind>/` for every kind the tree implements — derived from the
    registry and the packages' declarations, so a second channel add-on is walked the day its
    row lands rather than the day somebody remembers to list it."""
    return [p for p in (PACKAGE / "runtime" / kind for kind in _channel_kinds()) if p.is_dir()]


def _product_module_names() -> set[str]:
    from openfactory.product.module import ProductModule

    return {n for n, _f in inspect.getmembers(ProductModule, inspect.isfunction)
            if not n.startswith("_")} | {"ProductModule"}


def _work_done_in(packages) -> list[str]:
    """`file:line — name` for every call inside a function under `packages` that constructs the
    product module or calls one of its methods. AST, so a comment naming a verb cannot trip it and
    a call split over two lines cannot escape it.

    FUNCTION BODIES ONLY, and that is a stated blind spot: a module-scope `MOD = ProductModule(p)`
    or a lambda bound at import in a channel package returns `[]` here (probed 2026-08-25). No
    channel package has ever built the module at import — it needs a project — so the walk reads
    where the work is done; the twin below is what would catch this walker going blind, and a
    module-scope construction is the shape to add to it the day one appears."""
    names = _product_module_names()
    hits = []
    for package in packages:
        for path in sorted(pathlib.Path(package).rglob("*.py")):
            for fn in ast.walk(ast.parse(path.read_text())):
                if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                for node in ast.walk(fn):
                    if not isinstance(node, ast.Call):
                        continue
                    called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    if called in names:
                        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name
                        hits.append(f"{rel}:{node.lineno} — {called}")
    return hits


def test_the_walk_covers_every_channel_package_the_tree_ships():
    """A guard that walks nothing passes for ever — so what the tree SHIPS decides what must be
    walked, not a name written here. A channel add-on is a `runtime/<kind>/` package whose
    adapter twin `adapters/channel/<kind>.py` exists; every such pair must come out of the
    registry-derived list, and hold real functions. On a tree that ships none (the core-only
    distribution) there is nothing to cover, and the planted-file twin below is what still proves
    the walker can see."""
    shipped = sorted(p for p in (PACKAGE / "runtime").iterdir()
                     if p.is_dir() and (PACKAGE / "adapters" / "channel" / f"{p.name}.py").exists())
    packages = _channel_packages()
    missing = [p.name for p in shipped if p not in packages]
    assert not missing, (
        f"{missing} ship a channel package the channel registry does not know, so the D3 walk "
        f"skips them")
    for package in shipped:
        defined = sum(1 for f in package.rglob("*.py")
                      for n in ast.walk(ast.parse(f.read_text()))
                      if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef))
        assert defined >= 20, f"only {defined} functions under {package.name} — the walk is blind"


def test_the_walk_can_SEE_a_channel_doing_the_work(tmp_path):
    """The positive twin: a channel function that builds the module and calls the acceptance
    closer — the exact shape the move undid — is reported by both names, and a pure renderer
    beside it is not."""
    planted = tmp_path / "bot.py"
    planted.write_text(
        "def on_message(project, text):\n"
        "    from openfactory.product.module import ProductModule\n"
        "    return ProductModule(project).settle_acceptance(text)\n"
        "def render(text):\n"
        "    return text.upper()\n")
    hits = _work_done_in([tmp_path])
    assert {h.rsplit(" — ", 1)[1] for h in hits} == {"ProductModule", "settle_acceptance"}, hits
    assert all("render" not in h for h in hits), hits


def test_no_channel_package_does_the_product_role_s_work():
    """ADR-0038 D3 as code. Measured at zero on 2026-08-25, the day the conversation left the
    Slack package; a hit here is a capability growing back inside a transport."""
    hits = _work_done_in(_channel_packages())
    assert not hits, (
        "a channel package constructs the product module or calls its verbs — that is a "
        "capability living in a transport, and a deployment without that channel loses it:\n  "
        + "\n  ".join(hits))


def test_the_product_package_imports_no_channel_package():
    """The other direction of the same line: core may not reach INTO a channel add-on, at module
    scope or inside a function. The Slack package is one import away from being unremovable."""
    offenders = _channel_imports_in(PACKAGE / "product", kinds=_channel_kinds())
    assert not offenders, "\n  ".join(offenders)


def _core_runtime() -> set[str]:
    """The modules and packages `openfactory/runtime/` carries in THIS tree."""
    return {p.stem if p.is_file() else p.name for p in (PACKAGE / "runtime").iterdir()
            if not p.name.startswith(("_", "."))}


def _channel_imports_in(package: pathlib.Path, *, kinds: tuple[str, ...]) -> list[str]:
    """Imports under `package` that name `openfactory.runtime.<kind>` for any of `kinds`, or a
    `openfactory.runtime.<name>` this tree's core does not carry, or the Slack SDK itself. `kinds`
    is a parameter so the twins below test the WALKER with a kind it names, whatever the registry
    of the tree it runs on happens to know.

    WHAT THE CORE DOES NOT CARRY IS AN ADD-ON'S, BY CONSTRUCTION. The kinds come from the channel
    registry and the add-on packages' declarations, and in the public tree neither names Slack — so
    for a year this banned nothing but the SDK there, and `from openfactory.runtime.slack import …`
    planted in the product package passed. A mutation run found it (#266 slice 3, the row "the
    core reaches into the Slack package" of `public_product_conversation_is_core`)."""
    banned = tuple(f"openfactory.runtime.{k}" for k in kinds) + ("slack_sdk",)
    core = _core_runtime()

    def _reaches(module: str) -> bool:
        parts = module.split(".")
        foreign = parts[:2] == ["openfactory", "runtime"] and len(parts) > 2 \
            and parts[2] not in core
        return module.startswith(banned) or foreign

    out = []
    for path in sorted(package.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module and _reaches(node.module):
                out.append(f"{path.name}:{node.lineno} — from {node.module} import …")
            elif isinstance(node, ast.Import) and any(_reaches(a.name) for a in node.names):
                out.append(f"{path.name}:{node.lineno} — import "
                           f"{', '.join(a.name for a in node.names)}")
    return out


def test_the_import_walk_can_SEE_a_reach_into_a_channel(tmp_path):
    planted = tmp_path / "planted.py"
    planted.write_text("def f():\n    from openfactory.runtime.slack import mrkdwn\n"
                       "    return mrkdwn\nimport json\n")
    assert _channel_imports_in(tmp_path, kinds=("slack",)) == [
        "planted.py:2 — from openfactory.runtime.slack import …"]


def test_the_import_walk_sees_a_reach_into_a_package_the_core_does_not_CARRY(tmp_path):
    """The twin for a tree whose registry names no channel kind: an import of a runtime package
    that is not the core's is caught with no kind named at all — and the core's own runtime
    modules, which the product package does import, are not."""
    planted = tmp_path / "planted.py"
    planted.write_text("def f():\n    from openfactory.runtime.matrix import rooms\n"
                       "    return rooms\n"
                       "def g():\n    from openfactory.runtime.repo_cache import RepoCache\n"
                       "    return RepoCache\n")
    assert "matrix" not in _core_runtime() and "repo_cache" in _core_runtime()
    assert _channel_imports_in(tmp_path, kinds=()) == [
        "planted.py:2 — from openfactory.runtime.matrix import …"]


# ── the rescued capabilities, on the call graph ────────────────────────────────────────────────

#: What the shared stage reaches that the panel's turn did not: the client's verdict on a delivery,
#: the decisions closed by a reply, the loops a reply opens, the notice for an expired proposal,
#: the compare-and-swap that performs or destroys a staged one, and the client's release.
RESCUED = ("settle_acceptance", "close_decisions_answered", "record_decisions",
           "proposal_expired", "consume", "release")


def test_the_rescued_capabilities_are_reached_from_the_panel_s_OWN_entry_point():
    """From `conversation_turn` — the activity every conversation's turn runs on the worker, the
    panel's `product_say` included since #266 slice 3 put it through the door (it was
    `product_role_say`, one workflow per message, until then) — and from nothing else: the seeds
    are that one activity and the Slack package is not in the graph at all. Before the move this
    could only be satisfied through the bot: `_handle` was the sole caller of four of these, and
    `_handle` was reached by `bot.py` alone."""
    edges, seeds = _call_graph(without=("openfactory/runtime/slack/",))
    assert "conversation_turn" in seeds, "the conversation's turn activity is not a seed"
    alive = _reachable_from(edges, {"conversation_turn"})
    missing = [name for name in RESCUED if name not in alive]
    assert not missing, (
        f"{missing} are not reachable from the panel's product turn with the Slack package out of "
        f"the tree — a client on a panel deployment cannot do what a client on Slack can")
    # and the proof is not the chat adapter in disguise: the panel reaches the ENGINE, and never
    # the renderer a chat surface's callbacks go through (`channel.deliver`)
    assert "turn" in alive, "the panel's turn does not reach the turn engine"
    assert "deliver" not in alive, "the panel turn goes through the chat adapter — two paths again"


def test_the_chat_handler_and_the_panel_turn_share_ONE_settling_stage():
    """Two transports, one implementation (ADR-0038 D3, C-23's bar): both callers reach the ONE
    turn engine (#266 slice 2), which settles, and `settle_acceptance` is called by exactly one
    production function — the stage. A second caller is the two-front-ends drift starting over.
    Since #266 slice 3 both reach it through the ONE DOOR: the chat handler hands its message to
    the door (`say`), and the turn every message gets on the worker is `_conversation_turn`."""
    def _calls(path: pathlib.Path, fn_name: str) -> set[str]:
        fn = next(n for n in ast.walk(ast.parse(path.read_text()))
                  if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == fn_name)
        return {getattr(n.func, "id", None) or getattr(n.func, "attr", "")
                for n in ast.walk(fn) if isinstance(n, ast.Call)}

    assert "say" in _calls(CHAT_HANDLER, "handle"), "the chat handler no longer goes through " \
                                                     "the door"
    assert "turn" in _calls(WORKER_TURN, "_conversation_turn"), (
        "the panel's turn no longer reaches the engine — acceptance, typed yes/no and expiry are "
        "Slack-only again")
    assert "settle" in _calls(TURN_ENGINE, "_answer"), "the turn engine no longer settles"
    callers = set()
    for path in PACKAGE.rglob("*.py"):
        for fn in ast.walk(ast.parse(path.read_text())):
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) and any(
                    isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "settle_acceptance"
                    for n in ast.walk(fn)):
                callers.add(fn.name)
    assert callers == {"settle"}, f"the acceptance verdict is implemented in {sorted(callers)}"


# ── the rescued capabilities, by running the panel's turn ──────────────────────────────────────

def _project(admins=("U0APPROVER",)):
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project

    # the approver answers what the client staged: since #266 slice 4 that is the product letting
    # an admin accept on the requester's behalf — these tests pin which verb a turn reaches and
    # what each gate is told, not whose yes it is
    return Project(name="acme", repo_path="/t", language="pt-BR", channel_id="COPS",
                   product=ProductConfig(docs_repo="a/b", slack_channel="CPROD",
                                         agent_name="Nina", slack_admins=list(admins),
                                         accept_on_behalf=True))


#: A transport no surface mints. Every default on the way — `""` on the input, `api` on the
#: worker, `slack` on the gate, `panel` on the route — is itself a valid transport, so a hop that
#: keeps the keyword and replaces the value with one of them is invisible to a run that hands it
#: that same value. The first version of the transport section read the keyword's NAME off the
#: source and passed while `via="slack"` sat hardcoded at two hops (2026-08-25); the second
#: drove the stage's inner gates with `panel` and passed while `via="panel"` sat hardcoded at
#: both (2026-08-26). Now each hop is driven with a value nobody else could have produced, and
#: read where it lands.
SENTINEL_VIA = "hop-sentinel"


class _Module:
    """The product module with the model replaced: what is under test is the TURN's routing —
    which verb a message reaches — not what the verbs do."""

    def __init__(self, *, verdict=None, answer=None):
        from openfactory.product.role import ProductAnswer

        self.calls: list[str] = []
        self.verdict = verdict
        self.reply = answer or ProductAnswer(ok=True, text="resposta")
        self.noted: dict = {}

    def settle_acceptance(self, text):
        self.calls.append("settle_acceptance")
        return self.verdict

    def confirmed(self, reply, *, proposal):
        self.calls.append("confirmed")
        return "neither"

    def close_decisions_answered(self, *, channel=""):
        self.calls.append("close_decisions_answered")
        return 0

    def answer(self, question, *, context="", conversation="", pending=""):
        self.calls.append("answer")
        return self.reply

    def record_decisions(self, labels, *, channel=""):
        self.calls.append("record_decisions")
        return len(labels)

    def note_fact(self, **kw):
        from openfactory.product.authoring import WriteResult

        self.calls.append("note_fact")
        self.noted = kw
        return WriteResult(ok=True, ref="learned", url="")

    def context(self):
        # the chat handler asks before it converses; the panel's turn never does
        self.calls.append("context")
        return SimpleNamespace(available=True, reason="")


@pytest.fixture()
def panel_turn(monkeypatch):
    """Run `_conversation_turn` — the worker side of every conversation's turn, the panel's
    `product_say` included (the one turn engine since #266 slice 2, reached through the door since
    slice 3) — against a module stand-in, with the transcript kept as a list and the staging dict
    clean at both ends. What comes back is the turn's ANSWER, the last reply."""
    from openfactory.memory import transcript
    from openfactory.product import module as module_mod
    from openfactory.product import staging

    recorded: list[tuple[str, str]] = []

    def _record(project, *, thread, role, text, actor="", channel="", **_ids):
        recorded.append((role, text))
        return f"ts{len(recorded)}"

    monkeypatch.setattr(transcript, "record", _record)
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    staging._PENDING.clear()
    staging._EXPIRED_TOMBSTONES.clear()

    built: list[str] = []

    def run(module, message, *, user="U0APPROVER", project=None, via="panel"):
        from openfactory.product.key import product_key
        from openfactory.runtime.temporal.activities import _conversation_turn
        from openfactory.runtime.temporal.io import TurnInput

        def _build(project, *, via="api"):
            built.append(via)
            return module

        monkeypatch.setattr(module_mod, "ProductModule", _build)
        proj = project or _project()
        replies = _conversation_turn(proj, TurnInput(
            product=product_key(proj), project=proj.name, conversation="t1", speaker=user,
            text=message, id=f"m{len(built)}", via=via))
        answers = [r for r in replies if r.kind == "answer"]
        return (answers[-1] if answers else None), recorded

    #: the `via` every module of this turn was built with — read back, like the gate's
    run.built = built
    yield run
    staging._PENDING.clear()
    staging._EXPIRED_TOMBSTONES.clear()


@pytest.fixture()
def chat_turn(monkeypatch):
    """Run a CHAT message's turn — the stage's other caller — with the same stand-ins the panel's
    run uses, in process (`tests/the_chat_turn.py`: the engine and the chat adapter's renderer;
    `handle` itself goes through the door since #266 slice 3). It hands the stage the chat
    adapter's transport, so what its gates are told is the channel's own name: the one hop a run
    through the panel can never read back."""
    from openfactory.memory import transcript
    from openfactory.product import staging

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "ts")
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    staging._PENDING.clear()
    staging._EXPIRED_TOMBSTONES.clear()

    def run(module, message, *, user="U0APPROVER", project=None):
        from tests.the_chat_turn import chat_turn

        return chat_turn(project or _project(), text=message, user=user, thread="t1",
                         module=module)

    yield run
    staging._PENDING.clear()
    staging._EXPIRED_TOMBSTONES.clear()


def test_the_client_s_verdict_typed_in_the_panel_CLOSES_the_delivery(panel_turn):
    """"funcionou" on the panel reaches `settle_acceptance` and comes back as the acceptance
    sentence — not as a conversational reply about it. The model is never asked: the verdict is
    the answer, and it asks nothing further, which is what the panel reads as "nothing to
    confirm"."""
    from openfactory.memory.ledger import ACCEPTANCE, Loop
    from openfactory.product.followup import OWNER, accepted_text

    loop = Loop(kind=ACCEPTANCE, subject="delivery", owner=OWNER, about="#12")
    module = _Module(verdict=("worked", loop, False))

    answer, recorded = panel_turn(module, "funcionou")

    assert answer is not None and answer.text == accepted_text(loop, agent_name="Nina"), answer
    assert answer.options is None
    assert "answer" not in module.calls, f"the verdict went to the model: {module.calls}"
    assert recorded == [("person", "funcionou"), ("agent", answer.text)], recorded


def test_a_yes_typed_in_the_panel_performs_a_proposal_staged_under_ITS_key(panel_turn, gate_saw):
    """The stage's behaviour under the panel's key. Staged BY HAND here, so the executor is what is
    under test — the producers reach the panel's path since #266 slice 2, and
    `test_a_request_typed_in_the_panel_is_STAGED_and_a_typed_yes_there_WRITES_it` drives one. What
    this pins is that a typed "sim" is performed through the same executor the click uses rather
    than answered as small talk — one implementation, three ways in. The executor's gate is told what the
    turn was told: the mutation that kept `via` inside the stage survived a first version of
    this run, which read the write and never asked what the gate had been told; the one that
    hardcoded `panel` there survived the second, which handed the turn `panel` and read `panel`
    back. Driven with the sentinel now, and the chat twin below reads the default."""
    from openfactory.product import staging
    from openfactory.product.voice import fact_noted

    project = _project()
    staging.remember("t1", {"kind": "fact", "term": "fechamento",
                            "body": "o fechamento roda no dia 5", "said_by": "", "source": "",
                            "channel": ""}, lang="pt-BR", project=project)
    module = _Module()

    answer, _ = panel_turn(module, "sim", project=project, via=SENTINEL_VIA)

    assert module.noted.get("term") == "fechamento", f"nothing was written: {module.calls}"
    assert answer.text == fact_noted(term="fechamento", language="pt-BR"), answer.text
    assert staging.pending_for("t1") is None, "the proposal is still staged after a yes"
    assert "answer" not in module.calls, module.calls
    assert gate_saw == [SENTINEL_VIA], gate_saw


def test_a_yes_typed_in_CHAT_is_recorded_at_confirm_s_gate_as_the_channel_s(chat_turn,
                                                                            gate_saw):
    """The chat handler hands the stage no transport, so the gate behind a typed yes is told the
    stage's DEFAULT — and the default must be the channel's own name, not the panel's. A run
    through the panel cannot see this hop: it hands a value and reads that value back."""
    from openfactory.product import staging
    from openfactory.product.voice import fact_noted

    project = _project()
    staging.remember("t1", {"kind": "fact", "term": "fechamento",
                            "body": "o fechamento roda no dia 5", "said_by": "", "source": "",
                            "channel": ""}, lang="pt-BR", project=project)
    module = _Module()

    reply = chat_turn(module, "sim", project=project)

    assert reply == fact_noted(term="fechamento", language="pt-BR"), reply
    assert module.noted.get("term") == "fechamento", f"nothing was written: {module.calls}"
    assert gate_saw == ["slack"], gate_saw


def test_the_chat_handler_hands_the_door_the_CHANNEL_s_own_transport(monkeypatch):
    """The hop the chat runs above cannot see since #266 slice 3: `channel.handle` builds the
    message the door enqueues, and the turn runs on the worker — so the transport the handler
    names is the default every gate behind a chat message is told. It must be the channel's own
    name, never the panel's: read here, on the message that crosses the door."""
    from openfactory.product import channel, door

    crossed: list = []
    monkeypatch.setattr(door, "say",
                        lambda project, message, **_kw: crossed.append(message) or [])

    channel.handle(_project(), text="sim", user="U0APPROVER", thread="t1")

    assert [(m.via, m.conversation, m.speaker) for m in crossed] == [
        ("slack", "t1", "U0APPROVER")], crossed


def test_a_no_typed_in_the_panel_by_its_requester_destroys_the_proposal_and_tells_the_gate(
        panel_turn, gate_saw):
    """The rejection is gated by a different rule (an admin, or the requester) and it FALLS
    THROUGH: the person's "não, não é isso" is the correction, so it reaches the model with the
    discarded proposal gone from the prompt. Hand-staged like its siblings; what it pins is the
    rule and the provenance the gate is told — the turn's, driven with the sentinel, because
    `via="panel"` hardcoded on this gate survived a run that handed it `panel`."""
    from openfactory.product import staging

    project = _project(admins=("U0APPROVER",))
    staging.remember("t1", {"kind": "fact", "term": "fechamento", "body": "dia 5",
                            "said_by": "<@U0NOBODY>", "source": "", "channel": ""},
                     lang="pt-BR", project=project)
    module = _Module()

    answer, _ = panel_turn(module, "não, não é isso", user="U0NOBODY", project=project,
                           via=SENTINEL_VIA)

    assert gate_saw == [SENTINEL_VIA], gate_saw
    assert staging.pending_for("t1") is None, "the requester's own no left the proposal staged"
    assert "answer" in module.calls and answer.text == "resposta", module.calls


def test_a_no_typed_in_CHAT_by_its_requester_is_recorded_at_the_rejection_s_gate_as_the_channel_s(
        chat_turn, gate_saw):
    """The rejection's gate, told the stage's default by the chat handler: the channel's own
    name. Same falling-through as on the panel — the proposal is destroyed and the correction
    reaches the model."""
    from openfactory.product import staging

    project = _project(admins=("U0APPROVER",))
    staging.remember("t1", {"kind": "fact", "term": "fechamento", "body": "dia 5",
                            "said_by": "<@U0NOBODY>", "source": "", "channel": ""},
                     lang="pt-BR", project=project)
    module = _Module()

    reply = chat_turn(module, "não, não é isso", user="U0NOBODY", project=project)

    assert gate_saw == ["slack"], gate_saw
    assert staging.pending_for("t1") is None, "the requester's own no left the proposal staged"
    assert "answer" in module.calls and reply == "resposta", module.calls


def test_a_late_yes_in_the_panel_hears_EXPIRED_when_a_tombstone_sits_under_ITS_key(panel_turn):
    """The tombstone is planted BY HAND, so the expiry branch is what is under test: the "sim" of
    somebody who stepped away past the TTL must not fall through to the model — a polite answer to
    a confirmation of nothing, with the person believing they confirmed."""
    from openfactory.product import staging
    from openfactory.product.voice import proposal_expired

    staging._EXPIRED_TOMBSTONES["t1"] = time.time()
    module = _Module()

    answer, _ = panel_turn(module, "sim")

    assert answer.text == proposal_expired(language="pt-BR"), answer.text
    assert "answer" not in module.calls, module.calls


def test_a_reply_in_the_panel_CLOSES_the_decisions_she_asked_for(panel_turn):
    """A person replying IS the answer to what she asked last round — closed before her new reply
    can open fresh ones, which is the ordering `_handle` already pins for the chat path."""
    module = _Module()

    panel_turn(module, "vamos com a opção B")

    assert "close_decisions_answered" in module.calls, module.calls
    assert module.calls.index("close_decisions_answered") < module.calls.index("answer"), (
        module.calls)


class _Drafting(_Module):
    """The stand-in that hears a REQUEST and drafts it — and writes the draft on a yes."""

    def __init__(self):
        from openfactory.product.role import ProductAnswer

        super().__init__(answer=ProductAnswer(ok=True, text="proposta", is_request=True))
        self.proposed: list = []

    def draft(self, request, *, asked_by=""):
        from openfactory.product.role import ProductAnswer, RequirementDraft

        self.calls.append("draft")
        return ProductAnswer(ok=True, draft=RequirementDraft(
            title="Relatório mensal", must_be_true=["o relatório fecha no dia 5"]))

    def propose(self, answer, *, actor, asked_by="", date="", source=""):
        from openfactory.product.authoring import WriteResult

        self.calls.append("propose")
        self.proposed.append((answer.draft.title, actor, asked_by))
        return WriteResult(ok=True, url="https://forge.example/pull/5", number=5)


def test_a_request_typed_in_the_panel_is_STAGED_and_a_typed_yes_there_WRITES_it(panel_turn):
    """#266 SLICE 2'S ACCEPTANCE: a typed "yes" on the panel confirms a staged draft.

    For a year it could not. The panel's box reached a turn that drafted and never settled, and
    handed the draft back for a propose button of its own — so the "sim" a client typed next was
    answered as small talk and wrote nothing. `a_turn_that_settled_nothing_still_carries_the_DRAFT`
    pinned that shape; it is gone on purpose. Now the request is drafted and STAGED under the
    panel's own key, the reply asks for the yes and carries its options, and the next "sim" typed
    in the same box is performed by the executor a click uses — once."""
    from openfactory.product import staging

    module = _Drafting()
    project = _project(admins=("U0APPROVER",))

    asked, _ = panel_turn(module, "quero um relatório mensal", user="U0CLIENT", project=project)

    assert asked is not None and asked.options is not None, "the draft was not offered for a yes"
    assert "proposta" in asked.text and "Relatório mensal" in asked.text, asked.text
    # staged for the person who asked, in the panel's conversation (#266 slice 4)
    key, staged = staging.find_waiting("t1", "t1")
    assert staged is not None and staged["kind"] == "draft", staged
    assert asked.options.token == staging.proposal_token(key, staged)
    assert "propose" not in module.calls, "a draft was written before anybody said yes"

    done, recorded = panel_turn(module, "sim", user="U0APPROVER", project=project)

    assert module.proposed == [("Relatório mensal", "U0APPROVER", "<@U0CLIENT>")], module.proposed
    assert staging.find_waiting("t1", "t1") == (None, None), "the draft is still staged"
    assert done is not None and done.options is None
    assert ("agent", done.text) in recorded, recorded

    panel_turn(module, "sim", user="U0APPROVER", project=project)

    assert len(module.proposed) == 1, "a second yes wrote the draft again"


@pytest.mark.asyncio
async def test_the_ONE_ROW_hands_the_panel_the_token_of_what_it_staged(monkeypatch):
    """The whole way back, run: the row the panel's box calls (`product_say`), the door it sends
    through, the turn the worker runs for it and the engine behind that — Temporal stood in for by
    a client that runs the worker's own turn in-process (`tests/the_door_in_process.py`). The
    staged draft's TOKEN is what the panel's buttons answer by (`product_answer`), so a row that
    dropped it on the way back would leave the buttons answering nothing while every sentence
    still read right."""
    from openfactory import actions
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor
    from openfactory.memory import transcript
    from openfactory.product import module as module_mod
    from openfactory.product import staging
    from tests.the_door_in_process import DoorInProcess

    module = _Drafting()
    project = _project()
    monkeypatch.setattr(transcript, "record", lambda *a, **k: "ts")
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (module, project, None))
    monkeypatch.setattr(module_mod, "ProductModule", lambda project, *, via="": module)
    engine = DoorInProcess(project)

    async def _connected():
        return engine, None

    monkeypatch.setattr(catalog, "_connected", _connected)
    staging._PENDING.clear()
    try:
        outcome = await actions.perform("product_say", by=Actor(id="U0CLIENT", via="panel"),
                                        project="acme", message="quero um relatório mensal")

        assert outcome.ok, outcome.message
        assert engine.started == ["ConversationWorkflow"], engine.started
        key, staged = staging.find_waiting("acme", "acme")
        assert staged is not None and staged["kind"] == "draft", staged
        assert outcome.data["asks"] is True
        assert outcome.data["token"] == staging.proposal_token(key, staged), outcome.data
        assert "Relatório mensal" in outcome.message
    finally:
        staging._PENDING.clear()


# ── the gap, measured rather than claimed ──────────────────────────────────────────────────────

#: What STAGES a proposal — the producers a typed yes performs: `remember` is the store's write,
#: `offer_draft` stages the conversational draft, `_run_intent` stages the typed kinds.
STAGING_PRODUCERS = ("remember", "offer_draft", "_run_intent")


def test_EVERY_staging_producer_is_on_the_panel_s_path():
    """THE GAP, MEASURED — AND CLOSED (#266 slice 2). With the Slack package out of the graph, no
    seed reached a staging producer for a year while the panel's turn reached the consumer side
    (`confirm_staged`, `_expired_recently`): `settle`'s typed-yes and expiry branches ran on the
    panel and found nothing (the reviewer's finding, 2026-08-25). ADR-0047 brought one producer —
    `confirm()` staging the second yes — and this guard said exactly one, on purpose, until the gap
    closed. It has: the panel's turn IS the engine, so the draft (`offer_draft`) and the typed
    intents (`_run_intent`) are staged from the panel's own activity, and the consumers with them.
    A producer that leaves the panel's path goes red here — that is the drift back to two doors."""
    edges, _seeds = _call_graph(without=("openfactory/runtime/slack/",))
    panel = _reachable_from(edges, {"conversation_turn"})
    missing = [n for n in STAGING_PRODUCERS if n not in panel]
    assert not missing, (
        f"{missing} are not reachable from the panel's turn with the Slack package out of the "
        f"graph — a proposal the chat surface can stage, the panel cannot")
    consumers = {"confirm_staged", "_expired_recently"}
    assert consumers <= panel, f"the consumer side left the panel's turn: {consumers - panel}"


def test_the_walk_can_SEE_a_staging_producer():
    """The twin: the same reader sees `remember(...)` and `staging.remember(...)` inside a
    function — so the zero above measures the panel deployment and not a blind walker — and on a
    tree that ships the Slack package every producer IS reached, through the bot's listener."""
    planted = ast.parse("def f(thread):\n    from openfactory.product import staging\n"
                        "    staging.remember(thread, {})\n    return offer_draft(thread)\n")
    fn = next(n for n in ast.walk(planted) if isinstance(n, ast.FunctionDef))
    assert {"remember", "offer_draft"} <= _called_names(fn), _called_names(fn)
    if not _channel_packages():
        pytest.skip("no channel package ships on this tree, so there is no producer to see")
    edges, seeds = _call_graph()
    alive = _reachable_from(edges, seeds)
    missing = [n for n in STAGING_PRODUCERS if n not in alive]
    assert not missing, f"{missing} unreachable even with the Slack package in — the walk is blind"


# ── the gate, on the new surface ───────────────────────────────────────────────────────────────

def _release_loop(issue=12):
    from openfactory.product import followup

    return followup.release_of(issue, channel="", ts="2026-08-25T10:00:00+00:00",
                               requirement="0006", where="https://staging.example")


@pytest.fixture()
def released(monkeypatch):
    """Every `release()` call, so the tests assert on the ACT and never on the sentence."""
    calls: list[tuple[str, str]] = []

    def _fake(project, issue, *, approver, comment=""):
        calls.append((str(issue), approver))
        return True, ""

    monkeypatch.setattr("openfactory.product.release.release", _fake)
    return calls


def test_a_funcionou_on_a_RELEASE_loop_typed_in_the_panel_is_REFUSED_to_who_may_not_act(
        panel_turn, released):
    """The product box is not a second, softer approver: the same `may_act` the channel has asked
    since ADR-0025 answers here, and a person off the list releases nothing and is told so — not
    handed to the model for a polite reply about production."""
    from openfactory.product.module import unauthorized_message

    project = _project(admins=("U0APPROVER",))
    module = _Module(verdict=("worked", _release_loop(12), False))

    answer, _ = panel_turn(module, "funcionou o #12", user="U0NOBODY", project=project)

    assert released == [], "somebody off the list released production from the panel"
    assert answer.text == unauthorized_message(project), answer.text
    assert "answer" not in module.calls, module.calls


def test_a_funcionou_on_a_RELEASE_loop_typed_in_the_panel_RELEASES_for_who_may(panel_turn,
                                                                                released):
    """The positive twin, and the owner's decision (2026-08-25): the client's "funcionou" in the
    panel's product box releases, gated exactly as the channel's is. The panel is the reference
    surface (ADR-0038 D1); a capability the channel has and the panel lacks is the divergence
    that ADR names."""
    module = _Module(verdict=("worked", _release_loop(12), False))

    answer, _ = panel_turn(module, "funcionou o #12", user="U0APPROVER")

    assert released == [("12", "U0APPROVER")], released
    assert "produção" in answer.text, answer.text


@pytest.fixture()
def gate_saw(monkeypatch):
    """Every transport the policy was told, in order — read at `authz.is_admin`, which is what
    `may_act` builds its `Subject` for. A `via` that stops at the module's constructor and never
    reaches the gate shows up here as `slack`."""
    from openfactory.policy import authz

    seen: list[str] = []
    real = authz.is_admin

    def _recording(subject, project, *, scope):
        seen.append(subject.via)
        return real(subject, project, scope=scope)

    monkeypatch.setattr(authz, "is_admin", _recording)
    return seen


def test_the_gate_is_told_the_PANEL_for_a_release_typed_there(panel_turn, released, gate_saw):
    """Provenance: the record of who authorised the release says which surface they spoke from.
    Before this the module said `api` and the gate said `slack` for one person in one turn."""
    module = _Module(verdict=("worked", _release_loop(12), False))

    panel_turn(module, "funcionou o #12", user="U0APPROVER", via="panel")

    assert gate_saw == ["panel"], gate_saw
    assert released, "the gate was asked and nothing was released"


def test_a_row_that_did_not_say_where_it_came_from_reads_as_api_never_as_slack(panel_turn,
                                                                                released,
                                                                                gate_saw):
    """The value comes from the input, not from a constant: an empty `via` — a caller that did
    not say — reads as `api`, the worker's own name for itself, and never as the channel."""
    module = _Module(verdict=("worked", _release_loop(12), False))

    panel_turn(module, "funcionou o #12", user="U0APPROVER", via="")

    assert gate_saw == ["api"], gate_saw


def test_a_yes_answered_by_TOKEN_tells_both_its_gates_the_transport_too(monkeypatch, gate_saw):
    """The token route (`answer_staged`) is the panel's other way to a yes, and it had the same
    defect one layer down: the worker built the module with the panel's `via` and the two gates
    on the way to the write — the route's own and `confirm`'s — kept saying `slack`."""
    from openfactory.memory import transcript
    from openfactory.product import staging
    from openfactory.product.confirm import answer_staged

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")
    project = _project()
    staging._PENDING.clear()
    try:
        staging.remember("t9", {"kind": "fact", "term": "x", "body": "y", "said_by": "",
                                "source": "", "channel": ""}, lang="pt-BR", project=project)
        token = staging.proposal_token("t9", staging.pending_for("t9", project=project))
        outcome, _ = answer_staged(project, token=token, approved=True, user="U0APPROVER",
                                   module=_Module(), via="panel")
    finally:
        staging._PENDING.clear()
    assert outcome == "done", outcome
    assert gate_saw == ["panel", "panel"], gate_saw


# ── the transport, read back at every hop it lands on ─────────────────────────────────────────
# Every run below hands `SENTINEL_VIA` (defined above the panel's runs, which hand it too) and
# reads it where the hop lands: the workflow input, the module, the gate.


@pytest.fixture()
def dispatched(monkeypatch):
    """The workflow input a catalog row hands the engine — the row's hop, captured where it
    lands. The engine is a fake that records the input and answers `ok`; for the conversation's
    row it is what crossed the DOOR (#266 slice 3): the workflow it signals and the message it
    enqueued, answered at once."""
    from openfactory.actions import catalog

    seen: dict = {}

    class _Engine:
        async def execute_workflow(self, name, inp, **_kw):
            seen["workflow"], seen["input"] = name, inp
            return {"ok": True, "outcome": "done", "message": "feito",
                    "answer": {"ok": True, "text": "resposta"}}

        async def start_workflow(self, name, inp, *, start_signal_args=(), **_kw):
            seen["workflow"], seen["input"] = name, start_signal_args[0]

        def get_workflow_handle(self, _wid):
            class _Handle:
                async def query(self, _name, message_id, **_kw):
                    return {"state": "answered", "replies": [
                        {"text": "resposta", "kind": "answer", "in_reply_to": message_id}]}
            return _Handle()

    async def _connected():
        return _Engine(), None

    monkeypatch.setattr(catalog, "_connected", _connected)
    monkeypatch.setattr(catalog, "_product_module",
                        lambda _name, **_k: (object(), _project(), None))
    return seen


@pytest.mark.asyncio
async def test_the_say_row_carries_its_actor_s_transport_into_the_workflow_input(dispatched):
    """Hop one of the conversation: the actor who came through the door into the input the
    worker reads. Through `perform`, so the row is the one a surface reaches."""
    from openfactory import actions
    from openfactory.actions.base import Actor

    outcome = await actions.perform("product_say", by=Actor(id="alice", via=SENTINEL_VIA),
                                    project="acme", message="quero um relatório mensal")

    assert outcome.ok, outcome.message
    assert dispatched["workflow"] == "ConversationWorkflow"
    assert dispatched["input"].via == SENTINEL_VIA, dispatched["input"]


@pytest.mark.asyncio
async def test_the_answer_row_carries_its_actor_s_transport_into_the_workflow_input(dispatched):
    """Hop one of the token answer: the same reading on the other row that dispatches a `via`."""
    from openfactory import actions
    from openfactory.actions.base import Actor

    outcome = await actions.perform("product_answer",
                                    by=Actor(id="alice", via=SENTINEL_VIA, admin=True),
                                    project="acme", token="t1|abc", answer="approve", yes="yes")

    assert outcome.ok, outcome.message
    assert dispatched["workflow"] == "ProductAnswerWorkflow"
    assert dispatched["input"].via == SENTINEL_VIA, dispatched["input"]


def test_the_worker_s_turn_hands_the_input_s_transport_to_the_module_AND_the_gate(panel_turn,
                                                                                    released,
                                                                                    gate_saw):
    """Hop two of the conversation: the input into the module the turn builds and into the gate
    behind the release. `panel` is what the panel sends and `slack` is the gate's default, so a
    turn that swapped one for the other would pass a run that handed it `panel`."""
    module = _Module(verdict=("worked", _release_loop(12), False))

    panel_turn(module, "funcionou o #12", user="U0APPROVER", via=SENTINEL_VIA)

    assert panel_turn.built == [SENTINEL_VIA], panel_turn.built
    assert gate_saw == [SENTINEL_VIA], gate_saw
    assert released, "the gate was asked and nothing was released"


@pytest.fixture()
def staged_token():
    """A proposal staged BY HAND under a key of its own, and its token — with the stage clean at
    both ends. The gate is what is under test, not the producer (there is none on the panel)."""
    from openfactory.product import staging

    project = _project()
    staging._PENDING.clear()
    try:
        staging.remember("t9", {"kind": "fact", "term": "x", "body": "y", "said_by": "",
                                "source": "", "channel": ""}, lang="pt-BR", project=project)
        yield staging.proposal_token("t9", staging.pending_for("t9", project=project))
    finally:
        staging._PENDING.clear()


@pytest.fixture()
def module_built(monkeypatch):
    """Every `via` a `ProductModule` is built with, in order — and the stand-in it becomes, so
    a yes is performed against no docs repository."""
    from openfactory.product import module as module_mod

    built: list[str] = []
    stand_in = _Module()

    def _build(project, *, via="slack"):
        built.append(via)
        return stand_in

    monkeypatch.setattr(module_mod, "ProductModule", _build)
    return built


@pytest.mark.asyncio
async def test_the_worker_s_answer_row_hands_the_input_s_transport_to_both_gates(
        monkeypatch, staged_token, module_built, gate_saw):
    """Hop two of the token answer: `product_role_answer` — the activity itself, run — builds
    the module with the input's transport and tells the route's gate and `confirm`'s."""
    from openfactory.memory import transcript
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal.activities import product_role_answer
    from openfactory.runtime.temporal.io import ProductAnswerInput

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _project())

    result = await product_role_answer(ProductAnswerInput(
        project="acme", token=staged_token, approved=True, actor="U0APPROVER", via=SENTINEL_VIA))

    assert result["outcome"] == "done", result
    assert module_built == [SENTINEL_VIA], module_built
    assert gate_saw == [SENTINEL_VIA, SENTINEL_VIA], gate_saw


@pytest.mark.asyncio
async def test_a_token_answer_that_did_not_say_where_it_came_from_reads_as_api_never_as_slack(
        monkeypatch, staged_token, module_built, gate_saw):
    """The answer row's fold, the twin the conversation's already had: an empty `via` — a
    caller that did not say — reads as `api`, the worker's own name for itself, at the module
    and at both gates; never as the channel. `or "slack"` here survived the whole suite while
    only the conversation's fold was read (the third review, 2026-08-26)."""
    from openfactory.memory import transcript
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal.activities import product_role_answer
    from openfactory.runtime.temporal.io import ProductAnswerInput

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _project())

    result = await product_role_answer(ProductAnswerInput(
        project="acme", token=staged_token, approved=True, actor="U0APPROVER", via=""))

    assert result["outcome"] == "done", result
    assert module_built == ["api"], module_built
    assert gate_saw == ["api", "api"], gate_saw


def test_a_no_answered_by_TOKEN_tells_the_route_s_reject_gate_the_transport(monkeypatch,
                                                                            staged_token,
                                                                            gate_saw):
    """The token route's OTHER gate — the one a refusal by click passes — read back. Every driven
    run and every plan row on this route approved, so `via=via` dropped on the reject gate
    survived the whole suite while the docstring said `via` was handed to each gate below."""
    from openfactory.product import staging
    from openfactory.product.confirm import answer_staged

    outcome, _ = answer_staged(_project(), token=staged_token, approved=False,
                               user="U0APPROVER", via=SENTINEL_VIA)

    assert outcome == "rejected", outcome
    assert staging.pending_for("t9") is None, "the admin's no left the proposal staged"
    assert gate_saw == [SENTINEL_VIA], gate_saw


def test_the_token_gate_builds_the_module_it_was_handed_NONE_of_with_the_transport_it_was_told(
        monkeypatch, staged_token, module_built, gate_saw):
    """`answer_staged` with no module — the shape of the panel's route and of the Slack click —
    builds one with the transport it was told, so the write it performs is recorded where the
    two gates that authorised it were. The route test reads `panel` here, which a `panel`
    hardcode also satisfies; the sentinel does not."""
    from openfactory.memory import transcript
    from openfactory.product.confirm import answer_staged

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")

    outcome, _ = answer_staged(_project(), token=staged_token, approved=True,
                               user="U0APPROVER", via=SENTINEL_VIA)

    assert outcome == "done", outcome
    assert module_built == [SENTINEL_VIA], module_built
    assert gate_saw == [SENTINEL_VIA, SENTINEL_VIA], gate_saw


def test_the_token_gate_handed_NO_transport_builds_the_module_as_the_channel_s(monkeypatch,
                                                                            staged_token,
                                                                            module_built,
                                                                            gate_saw):
    """The positive twin: the Slack click hands neither a module nor a transport, and its write
    is recorded as the channel's — at the module and at both gates."""
    from openfactory.memory import transcript
    from openfactory.product.confirm import answer_staged

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")

    outcome, _ = answer_staged(_project(), token=staged_token, approved=True,
                               user="U0APPROVER")

    assert outcome == "done", outcome
    assert module_built == ["slack"], module_built
    assert gate_saw == ["slack", "slack"], gate_saw


@pytest.fixture()
def durable_store(monkeypatch):
    """The store the panel's route reads its pending list from and `remember` mirrors into — in
    memory, patched at the two seams `messages` itself resolves (the panel test's own fixture)."""
    from tests.test_the_panel_is_a_channel import _Sink

    store = _Sink()
    monkeypatch.setattr(SINK_DOOR, lambda: store)
    monkeypatch.setattr("openfactory.observability.query.records_of_kind",
                        lambda project, kind, limit=500, **kw: store.of_kind(project, kind,
                                                                             limit))
    return store


def test_the_panel_s_own_route_tells_both_gates_and_the_module_the_PANEL(monkeypatch, tmp_path,
                                                                          durable_store,
                                                                          staged_token,
                                                                          module_built, gate_saw):
    """The route's hop, DRIVEN: a POST on the panel's answer route with a personal credential, the
    identity resolved by the server, the staged proposal found in the durable store, and the
    transport read back at the two gates and at the module the gate builds — `panel`, because
    the route IS the panel. The reviewer hardcoded `via="slack"` on this call and the whole suite
    stayed green (2026-08-25): the only test of the behaviour called `answer_staged` directly.
    And the module: the route hands none, the gate built one with its default, so the write the
    two `panel` gates authorised was recorded as `slack` one line down."""
    from fastapi.testclient import TestClient

    from openfactory.api.app import app
    from openfactory.memory import transcript
    from openfactory.registry import ProjectRegistry

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_IDENTITY", raising=False)
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "mine:alice")
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _project(admins=("alice",)))

    r = TestClient(app).post("/api/messages/acme/answer",
                             json={"token": staged_token, "answer": "approve"},
                             headers={"Authorization": "Bearer mine"})

    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "done" and r.json()["by"] == "alice", r.json()
    assert gate_saw == ["panel", "panel"], gate_saw
    assert module_built == ["panel"], module_built
