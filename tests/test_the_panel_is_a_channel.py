"""A deployment with no Slack can be asked a question, and answer it (C-25, #54).

WHY THIS IS THE SECOND IMPLEMENTATION THAT MATTERS. `ChannelAdapter` has had exactly one
implementation since it was written, and a port with one implementation is a hypothesis rather
than a seam: nothing had ever forced the contract to be honest about what a CHANNEL is as opposed
to what Slack does. This provider needs no third-party account, so it is also the only one whose
behaviour can be proven here instead of in somebody's workspace.

AND IT IS LOAD-BEARING, not an exercise. "Never a silent wait — every stall either self-heals or
asks a human with executable options" was true only for deployments that bought Slack. Everyone
else got the question written, handed to `say`, and dropped.

THE LIMITATION IS ASSERTED TOO. The panel is PULL: `start_listeners` opens nothing and a person is
reached by looking. A test says so, because a provider whose weakness is undocumented is one a
deployment picks for a job it cannot do.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from openfactory.adapters.channel.base import ChannelAdapter, ConfirmingChannel
from openfactory.adapters.channel.panel import PanelChannel
from openfactory.adapters.channel.registry import build_channel
from openfactory.memory import messages


class _Project:
    def __init__(self, name: str = "demo", channel: str = "panel") -> None:
        self.name = name
        self.channel = channel


class _Sink:
    """The telemetry sink, in memory — the same row shape the real one persists."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, rec) -> bool:
        # `-> bool` since sweep B4: a sink that answers nothing reads as "did not land", and this
        # double silently failing every panel answer is exactly the honesty the contract buys.
        self.rows.append({"project": rec.project, "kind": rec.kind, "ts": rec.ts,
                          "extra": dict(rec.extra)})
        return True

    def of_kind(self, project: str, kind: str, limit: int) -> list[dict]:
        rows = [r for r in self.rows if r["project"] == project and r["kind"] == kind]
        rows.sort(key=lambda r: str(r["ts"]))
        return rows[-limit:]


@pytest.fixture
def sink(monkeypatch):
    """One in-memory sink behind BOTH the write and the read paths.

    Patched at the two seams `messages` itself resolves — the telemetry sink it records into and
    the query it reads back through — rather than at `messages.write`/`read`. Stubbing those two
    would leave the production call chain untested, and an earlier draft that did it recursed
    forever, because the "original" it captured was the patched one."""
    s = _Sink()
    monkeypatch.setattr("openfactory.runtime.temporal.activities._metrics_sink", lambda: s)
    monkeypatch.setattr("openfactory.observability.query.records_of_kind",
                        lambda project, kind, limit=500, **kw: s.of_kind(project, kind, limit))
    return s


# ── the port ─────────────────────────────────────────────────────────────────────────────────────

def test_the_panel_satisfies_the_channel_contract_by_SHAPE():
    """No inheritance anywhere: the protocols are structural, and satisfying them by shape is the
    whole point — a base class would let this pass by ancestry rather than by contract."""
    channel = PanelChannel()

    assert isinstance(channel, ChannelAdapter)
    assert isinstance(channel, ConfirmingChannel)
    assert PanelChannel.__bases__ == (object,), "it passed by inheritance, which proves nothing"


def test_the_registry_dispatches_to_it_from_CONFIG():
    """The card's own words: "the channel registry dispatches to it". From the project's `channel`
    field, never from an import — which is what makes adding Telegram one module and one row."""
    assert isinstance(build_channel(_Project(channel="panel")), PanelChannel)


def test_an_unknown_channel_is_still_refused_rather_than_defaulted():
    """Adding a second row must not have turned the registry into something that guesses. Silence
    is this axis's failure mode and it is indistinguishable from a quiet factory."""
    with pytest.raises(ValueError, match="unknown channel"):
        build_channel(_Project(channel="telegram"))


# ── saying ───────────────────────────────────────────────────────────────────────────────────────

def test_what_the_factory_says_is_readable_afterwards(sink):
    channel = PanelChannel()

    assert channel.say(project=_Project(), channel="", text="a subida para produção terminou")

    history = messages.read("demo")
    assert [m.text for m in history] == ["a subida para produção terminou"]
    assert history[0].kind == messages.SAID


def test_say_returns_False_instead_of_raising_when_it_cannot_land(monkeypatch):
    """`say`'s callers are scheduled rounds and activities: an exception there turns one
    undelivered message into a retry storm, and a silent failure turns it into an agent that
    looks like it has nothing to say."""
    def _explode(*_a, **_kw):
        raise RuntimeError("the table is gone")

    monkeypatch.setattr(messages, "say", _explode)

    assert PanelChannel().say(project=_Project(), channel="c", text="hello") is False


def test_a_project_with_no_name_is_refused_loudly_not_filed_somewhere(sink, caplog):
    """A message filed under "" is a message in a place nobody reads, which is the failure this
    provider exists to remove rather than reproduce."""
    class _Nameless:
        name = ""

    with caplog.at_level("WARNING"):
        landed = PanelChannel().say(project=_Nameless(), channel="", text="orphan")

    assert landed is False
    assert "OPENFACTORY_PANEL_SAY_NO_PROJECT" in caplog.text


def test_mention_is_the_plain_name_because_a_browser_has_no_namespace():
    """The contract's rule, and the panel is the case that proves it is not a Slack detail: there
    is nothing here that COULD be guessed."""
    assert PanelChannel().mention("alice") == "alice"
    assert PanelChannel().mention("  ") == ""


def test_start_listeners_opens_nothing_and_says_so():
    """PULL, NOT PUSH — the real shape of the difference, asserted so a deployment that needs to
    reach somebody who is not looking picks a different provider knowingly."""
    assert PanelChannel().start_listeners() is None


# ── asking, and being answered ───────────────────────────────────────────────────────────────────

def test_a_question_is_asked_and_stays_pending_until_somebody_answers(sink):
    channel = PanelChannel()

    posted = channel.ask_to_confirm(project=_Project(), channel="", thread="",
                                    text="registro o requisito?", token="req-7",
                                    approve="Sim", reject="Não")

    assert posted is True
    pending = messages.pending("demo")
    assert [(q.token, q.text, q.approve) for q in pending] == [("req-7", "registro o requisito?",
                                                                "Sim")]
    assert messages.answer_of("demo", "req-7") is None


def test_answering_closes_it_and_the_ASKER_can_read_what_was_said(sink):
    """THE ROUND TRIP, which is what makes this a channel rather than a notification system: a
    surface that can only be written to cannot carry a question."""
    PanelChannel().ask_to_confirm(project=_Project(), channel="", thread="", text="registro?",
                                  token="req-7", approve="Sim", reject="Não")

    assert messages.answer(project := "demo", token="req-7", answer="approve", by="alice")

    assert messages.pending(project) == []
    said = messages.answer_of(project, "req-7")
    assert said is not None and said.answer == "approve" and said.by == "alice"


def test_the_question_survives_its_own_answer(sink):
    """Append-only, like the loop ledger. "Who approved that, and what were they shown" has an
    answer here — which it would not if answering overwrote the question."""
    PanelChannel().ask_to_confirm(project=_Project(), channel="", thread="", text="subo?",
                                  token="rel-1", approve="Sim", reject="Não")
    messages.answer("demo", token="rel-1", answer="reject", by="U9")

    kinds = [(m.kind, m.text or m.answer) for m in messages.read("demo")]

    assert kinds == [(messages.ASKED, "subo?"), (messages.ANSWERED, "reject")]


def test_a_confirmation_with_no_token_is_NOT_posted(sink, caplog):
    """False without recording anything is the contract's signal for "the caller owns the prose
    fallback" — so a question is never posted twice, and never lost between the two paths."""
    with caplog.at_level("WARNING"):
        posted = PanelChannel().ask_to_confirm(project=_Project(), channel="", thread="",
                                               text="?", token="", approve="a", reject="r")

    assert posted is False
    assert messages.read("demo") == []
    assert "OPENFACTORY_PANEL_ASK_INCOMPLETE" in caplog.text


def test_two_projects_questions_do_not_mix(sink):
    PanelChannel().ask_to_confirm(project=_Project("alpha"), channel="", thread="", text="a?",
                                  token="t1", approve="s", reject="n")
    PanelChannel().ask_to_confirm(project=_Project("beta"), channel="", thread="", text="b?",
                                  token="t2", approve="s", reject="n")

    assert [q.token for q in messages.pending("alpha")] == ["t1"]
    assert [q.token for q in messages.pending("beta")] == ["t2"]


# ── the panel's own doors ────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    from openfactory.api.app import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKENS", raising=False)
    monkeypatch.delenv("OPENFACTORY_IDENTITY", raising=False)
    return TestClient(app)


def test_the_panel_shows_the_question_with_its_executable_options(client, sink):
    """ADR-0038 D2: a wait is a QUESTION with executable options, never a state. The payload has to
    tell a client exactly how to answer, or the reader is back to reading prose and guessing."""
    PanelChannel().ask_to_confirm(project=_Project(), channel="", thread="", text="registro?",
                                  token="req-7", approve="Sim", reject="Não")

    body = client.get("/api/messages/demo").json()

    assert [m["text"] for m in body["messages"]] == ["registro?"]
    (question,) = body["pending"]
    assert question["token"] == "req-7"
    assert [o["label"] for o in question["options"]] == ["Sim", "Não"]
    assert question["answer"] == {"method": "POST", "url": "/api/messages/demo/answer",
                                  "body": {"token": "req-7", "answer": "approve | reject"}}


def test_answering_through_the_panel_closes_the_question(client, sink, monkeypatch):
    """`by` COMES FROM THE CREDENTIAL, NEVER THE BODY. The adversarial review caught this file's
    first version proving the audit trail by injecting `by` in the JSON — a test of the forgery,
    not of the identity: the panel sends no `by`, so every real answer recorded nobody, and any
    credential-holder could write somebody else's name into the append-only record. The request
    below carries a personal token and NO `by`; the recorded name is the resolver's answer."""
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "mine:alice:Alice Ferreira")
    PanelChannel().ask_to_confirm(project=_Project(), channel="", thread="", text="registro?",
                                  token="req-7", approve="Sim", reject="Não")

    r = client.post("/api/messages/demo/answer",
                    json={"token": "req-7", "answer": "approve"},
                    headers={"Authorization": "Bearer mine"})

    assert r.status_code == 200, r.text
    assert messages.answer_of("demo", "req-7").by == "alice"


def test_a_body_supplied_by_cannot_forge_the_audit_record(client, sink, monkeypatch):
    """The spoof the review named: an anonymous shared-token holder posting {"by": "alice"}.
    The body's `by` is ignored wholesale — an identified person cannot rename themselves and an
    anonymous one cannot become somebody."""
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "shared")
    PanelChannel().ask_to_confirm(project=_Project(), channel="", thread="", text="subo?",
                                  token="rel-9", approve="Sim", reject="Não")

    r = client.post("/api/messages/demo/answer",
                    json={"token": "rel-9", "answer": "approve", "by": "alice"},
                    headers={"Authorization": "Bearer shared"})

    assert r.status_code == 200, r.text
    recorded = messages.answer_of("demo", "rel-9").by
    assert "alice" not in recorded, \
        "a client-asserted name reached the append-only audit record"
    # not "" either: the resolver's honest label for a shared-token caller says exactly what is
    # known — that somebody held the token — which an auditor can grep, where "" reads as a bug
    assert recorded == "somebody with the panel token"


def test_a_SECOND_click_on_a_stale_page_is_not_a_second_decision(client, sink):
    """A browser tab left open is the normal case, not the exotic one. Recording the second click
    would make one decision two, and this platform's decisions spend money."""
    PanelChannel().ask_to_confirm(project=_Project(), channel="", thread="", text="subo?",
                                  token="rel-1", approve="Sim", reject="Não")
    client.post("/api/messages/demo/answer", json={"token": "rel-1", "answer": "approve"})

    again = client.post("/api/messages/demo/answer", json={"token": "rel-1", "answer": "reject"})

    assert again.status_code == 409
    assert messages.answer_of("demo", "rel-1").answer == "approve", "a stale click overwrote it"


def test_an_answer_to_a_question_that_does_not_exist_is_refused(client, sink):
    r = client.post("/api/messages/demo/answer", json={"token": "never-asked", "answer": "approve"})

    assert r.status_code == 409
    assert messages.read("demo") == []


def test_a_third_answer_to_a_two_button_question_is_refused(client, sink):
    PanelChannel().ask_to_confirm(project=_Project(), channel="", thread="", text="?",
                                  token="t", approve="Sim", reject="Não")

    r = client.post("/api/messages/demo/answer", json={"token": "t", "answer": "maybe"})

    assert r.status_code == 400
    assert messages.pending("demo"), "the question was closed by an answer it does not have"


def test_the_answer_route_is_behind_the_panel_gate(client, monkeypatch, sink):
    """It records a human decision in that human's name. `_AUTH` covers every route that acts, and
    a new one that forgets it is a hole nobody opened deliberately."""
    from openfactory.api.app import app

    paths = {r.path for r in app.routes if "answer" in getattr(r, "path", "")}
    assert "/api/messages/{project}/answer" in paths

    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "s3cret")
    guarded = TestClient(app)

    assert guarded.post("/api/messages/demo/answer",
                        json={"token": "t", "answer": "approve"}).status_code == 401


# ── and the promise holds with no Slack at all ───────────────────────────────────────────────────

def test_nothing_on_this_path_imports_slack():
    """THE CARD'S CLAIM, made unfakeable. A panel channel that quietly pulled the Slack package in
    would work perfectly in this suite — `slack_sdk` is installed here — and fail on the day a
    deployment that never installed it tried to be asked a question."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "openfactory"
    for rel in ("adapters/channel/panel.py", "memory/messages.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        imported = [
            n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        ] + [
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
        ]
        offenders = [m for m in imported if "slack" in m.lower()]
        assert not offenders, f"{rel} imports {offenders} — the panel path needs a Slack workspace"


# ── and the panel actually shows it ──────────────────────────────────────────────────────────────

def test_the_panel_page_reaches_the_route_and_renders_the_buttons():
    """THE REACHABILITY GUARD, and this house's most repeated defect: a route with tests, a store
    with tests, and a page that calls neither. Every assertion above would still pass if the panel
    never asked — so the page itself is read.

    Source-text assertions, deliberately: the alternative is a browser in the test suite, and what
    fails here is exactly what would have failed silently — the call disappearing in an edit."""
    import pathlib

    page = (pathlib.Path(__file__).resolve().parents[1] / "openfactory" / "api" / "panel.html").read_text()

    assert "/api/messages/" in page, "the panel never asks what the factory said"
    # the conversation moved into the floating chat (the product owner: the mid-page box was
    # terrible) —
    # same reachability rule, new names: mounted on the project page, refreshed on a timer
    assert "refreshChat" in page
    assert page.count("refreshChat") >= 3, "defined and never called is the defect itself"
    assert "mountChat(name)" in page, "the project page no longer mounts the chat at all"
    assert "answerQuestion" in page, "a question nobody can answer is a state, not a question"
    assert '"/api/messages/${encodeURIComponent(project)}/answer' in page.replace("`", '"')


def test_the_page_shows_a_refusal_instead_of_a_green_toast():
    """A 409 means somebody already answered — on another tab, or another person's screen. A green
    toast over it tells this reader they decided something they did not, which is the exact defect
    the panel's `toggleProject` shipped with (it discarded the response and painted success)."""
    import pathlib

    page = (pathlib.Path(__file__).resolve().parents[1] / "openfactory" / "api" / "panel.html").read_text()
    answer = page[page.index("async function answerQuestion"):]
    answer = answer[:answer.index("async function loadCockpit")]

    assert "r.ok" in answer, "the response is discarded, so a refusal renders as success"
    assert '"err"' in answer


# ── the paths that SPEAK actually reach this provider (adversarial review of C-25) ──────────────

def test_channel_destination_gives_the_panel_somewhere_to_post():
    """Every production say-path guarded itself with `if cfg.channel_id:` — a Slack rule. A
    `channel: panel` project has no Slack channel id and needs none, so each guard read the panel
    deployment as "nothing configured" and stayed silent: provider shipped, gates never passed."""
    from openfactory.adapters.channel.registry import channel_destination

    assert channel_destination(_Project(channel="panel"), "") == "demo"
    assert channel_destination(_Project(channel="panel"), "C123") == "C123"
    assert channel_destination(_Project(channel="slack"), "") == ""      # Slack genuinely needs one
    assert channel_destination(_Project(channel="slack"), "C123") == "C123"


def test_notifier_for_project_has_a_panel_row_that_lands_in_the_store(sink, monkeypatch):
    """The notifier registry knew Slack → Telegram → Null, so on a panel deployment every
    notification — the diagnosis voice, park alerts, deploy outcomes — resolved to the
    NullNotifier and vanished beside an empty message store built to hold it."""
    from openfactory.factory import notifier_for_project

    project = SimpleNamespace(name="demo", channel="panel", channel_id="",
                              channel_options={})
    notifier = notifier_for_project(project)

    notifier.notify(message="o job #412 parou — falta o fixture", level="action_required")

    texts = [m.text for m in messages.read("demo")]
    assert any("#412" in t for t in texts), "the notification never reached the panel store"
    # THE MARK, NOT THE PICTOGRAPH. The level still travels — it just arrives as `!` rather than
    # as a bell, across all three notify adapters. What must never regress is that the URGENCY is
    # carried at all: a notification that reaches the panel stripped of its level reads as an
    # ordinary note, and the whole point of `action_required` is that it is not one.
    assert any(t.startswith("!") for t in texts), "the urgency level was dropped"


# ── C-33 (#70): what CAN hold today — one gate, named outcomes ─────────────────────────────────
#
# The first draft of this section wired the panel's answer route straight into the staged store
# and its tests passed — in one process. In a real deployment the staging dict lives in the
# WORKER's memory and the panel is a separate service, so every panel answer would have found
# "gone". The wiring was reverted before shipping; the process-boundary constraint is recorded on
# #70, which is where the durable-store design belongs. What remains here is the piece that is
# true in any topology: the resolution gate is structured and the Slack click is a mapping over
# it, so the second caller has a seam to arrive at.

def _stage_a_draft() -> str:
    from openfactory.product import channel as pc
    from openfactory.product.role import ProductAnswer, RequirementDraft

    class _Drafting(_WriteSpy):
        def draft(self, request, **kw):
            return ProductAnswer(ok=True, draft=RequirementDraft(
                title="Editar conciliado", must_be_true=["um administrador pode corrigir"]))

    pc.offer_draft(_staged_project(), request="quero editar conciliado", user="U0CLIENT",
                   thread="t1", module=_Drafting())
    entry = pc.pending_for("t1")
    assert entry is not None
    return pc.proposal_token("t1", entry)


def _staged_project(admins=("U0APPROVER",)):
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project as _RealProject

    return _RealProject(name="demo", repo_path="/t", channel_id="COPS",
                        product=ProductConfig(docs_repo="a/b", slack_channel="CPROD",
                                              slack_admins=list(admins)))


class _WriteSpy:
    def __init__(self):
        self.proposed: list = []

    def settle_acceptance(self, text):
        return None

    def propose(self, answer, *, actor, **kw):
        from openfactory.product.authoring import WriteResult

        self.proposed.append(actor)
        return WriteResult(ok=True, url="https://x/pull/9")


@pytest.fixture(autouse=True)
def _clean_staged():
    from openfactory.product import channel as pc

    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


def test_answer_staged_names_its_outcomes_for_a_second_caller():
    """`confirm_by_click` renders one sentence and is done; an HTTP caller has to map outcomes to
    statuses, and telling "unauthorized" apart from "done" by comparing prose is how a refusal
    gets recorded as a decision."""
    from openfactory.product import channel as pc

    token = _stage_a_draft()

    code, sentence = pc.answer_staged(_staged_project(), token=token, approved=True,
                                      user="U0INTRUSO")
    assert (code, bool(sentence)) == ("unauthorized", True)
    assert pc.pending_for("t1") is not None, "an unauthorized answer destroyed the proposal"

    stale = token.partition("|")[0] + "|000000000000"
    code, _ = pc.answer_staged(_staged_project(), token=stale, approved=True, user="U0APPROVER")
    assert code == "replaced"

    code, _ = pc.answer_staged(_staged_project(), token="nunca-visto|abc", approved=True,
                               user="U0APPROVER")
    assert code == "gone"


def test_the_slack_click_still_resolves_through_the_same_gate():
    """The one production caller today, unchanged by the refactor: an approver's click runs the
    staged write and gets a sentence back."""
    from openfactory.product import channel as pc

    token = _stage_a_draft()
    spy = _WriteSpy()

    reply = pc.confirm_by_click(_staged_project(), token=token, approved=True,
                                user="U0APPROVER", module=spy)

    assert spy.proposed == ["U0APPROVER"], "the click no longer reaches the staged write"
    assert isinstance(reply, str) and reply


def test_pending_keeps_only_the_latest_ask_per_conversation(sink):
    """The store-level half that IS durable: a restaged proposal (same key, new fingerprint) must
    not leave its superseded ask pending for ever in an append-only store."""
    messages.ask("demo", "primeira", token="t1|aaa", approve="Sim", reject="Não")
    messages.ask("demo", "segunda", token="t1|bbb", approve="Sim", reject="Não")

    pending = messages.pending("demo")

    assert [q.text for q in pending] == ["segunda"]


# ── C-33 (#70): the staging is DURABLE, so a second process can actually answer ─────────────────
#
# The first wiring of this read another process's memory and passed its tests — in one process.
# These tests simulate the real topology explicitly: the WORKER stages (local dict + durable
# mirror), `pc._PENDING.clear()` plays the process boundary, and the PANEL's process resolves
# from the durable store alone. The fingerprint must survive the freeze/thaw round trip or every
# cross-process answer reads as "replaced".

def _stage_in_the_worker(sink) -> str:
    from openfactory.product import channel as pc
    from openfactory.product.role import ProductAnswer, RequirementDraft

    class _Drafting(_WriteSpy):
        def draft(self, request, **kw):
            return ProductAnswer(ok=True, draft=RequirementDraft(
                title="Editar conciliado", must_be_true=["um administrador pode corrigir"]))

    pc.offer_draft(_staged_project(), request="quero editar conciliado", user="U0CLIENT",
                   thread="t1", module=_Drafting())
    entry = pc.pending_for("t1")
    assert entry is not None
    return pc.proposal_token("t1", entry)


def test_the_fingerprint_survives_the_freeze_thaw_round_trip(sink):
    """THE property everything else rests on: the token minted by the worker must equal the token
    the panel recomputes from the thawed entry — an unfaithful freeze makes every cross-process
    answer read as replaced."""
    from openfactory.product import channel as pc

    token = _stage_in_the_worker(sink)
    entry = pc.pending_for("t1")

    thawed = pc._thaw(pc._freeze(entry))

    assert thawed is not None
    assert pc.proposal_token("t1", thawed) == token


def test_a_DIFFERENT_process_resolves_the_staged_proposal(sink, monkeypatch):
    """The card's done-when, in the real topology: staged in the worker, answered in a process
    that never staged it."""
    from openfactory.product import channel as pc

    token = _stage_in_the_worker(sink)
    pc._PENDING.clear()  # ← the process boundary
    spy = _WriteSpy()

    code, sentence = pc.answer_staged(_staged_project(admins=["alice"]), token=token,
                                      approved=True, user="alice", module=spy)

    assert code == "done", sentence
    assert spy.proposed == ["alice"], "the panel-side approve never reached the staged write"


def test_the_OTHER_surface_cannot_double_run_a_decided_proposal(sink):
    """A panel approve followed by a Slack "sim": the worker still holds its local entry, but the
    durable store says DECIDED — without the guard both surfaces run the act, each convinced it
    decided."""
    from openfactory.product import channel as pc

    token = _stage_in_the_worker(sink)
    worker_entry = pc.pending_for("t1")

    # the panel decides first, in its own process
    panel = dict(_PENDING_SNAPSHOT := {})  # noqa: F841 — explicitness over cleverness
    pc._PENDING.clear()
    spy = _WriteSpy()
    code, _ = pc.answer_staged(_staged_project(admins=["alice"]), token=token,
                               approved=True, user="alice", module=spy)
    assert code == "done"

    # the worker's local dict still holds the entry; a later Slack confirmation must find NOTHING
    pc._PENDING["t1"] = worker_entry
    consumed = pc.consume("t1", worker_entry,
                          fingerprint=token.partition("|")[2],
                          project=_staged_project(), by="U0APPROVER", approved=True)

    assert consumed is None, "one decision ran twice, once per surface"
    assert spy.proposed == ["alice"], "the double-run guard consumed the wrong side"


def test_a_worker_restart_does_not_lose_the_staged_proposal(sink):
    """The same mechanism, other direction: the worker restarts (its dict empties), the client's
    later "sim" still finds the proposal — durably."""
    from openfactory.product import channel as pc

    _stage_in_the_worker(sink)
    pc._PENDING.clear()  # ← the restart

    entry = pc.pending_for("t1", project=_staged_project())

    assert entry is not None
    assert entry.get("kind") == "draft"


def test_the_panel_route_resolves_a_staged_proposal_end_to_end(sink, monkeypatch, client):
    """The full door: staged in the worker, POSTed on the panel with a personal token, resolved
    through the same gate the Slack click uses, identity server-resolved.

    THE GATE IS PATCHED ON THE CORE (#105). The route used to import `product_channel` to resolve
    a staged proposal — the one documented exception in `test_provider_seams` — and now calls
    `openfactory.product.confirm` directly. Patching the channel's re-export would leave this green while
    proving nothing about the code the route actually runs.
    """
    from openfactory.product import channel as pc
    from openfactory.product import confirm as gate
    from openfactory.registry import ProjectRegistry

    token = _stage_in_the_worker(sink)
    pc._PENDING.clear()
    spy = _WriteSpy()
    monkeypatch.setattr(ProjectRegistry, "get",
                        lambda self, name: _staged_project(admins=["alice"]))
    real = gate.answer_staged

    def _with_spy(project, **kw):
        kw["module"] = spy
        return real(project, **kw)

    monkeypatch.setattr(gate, "answer_staged", _with_spy)
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "mine:alice")

    r = client.post("/api/messages/demo/answer", json={"token": token, "answer": "approve"},
                    headers={"Authorization": "Bearer mine"})

    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "done"
    assert spy.proposed == ["alice"]
    assert messages.pending("demo") == [], "the decided proposal stayed pending on the panel"
