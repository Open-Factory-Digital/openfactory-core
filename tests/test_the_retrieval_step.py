"""The engine retrieves before the turn; the role reads files; `[[BUSCA: …]]` asks for more (#269
slice 2, ADR-0053 D8, D12).

THE ACCEPTANCE CRITERIA, each a test below by name:

  - the search before the turn is a file in the role's facts pack, named by its manifest;
  - that search never includes a line said in a group to somebody else — an explicit search may;
  - a `[[BUSCA]]` round works on a stub harness — the engine searches, writes the hits as a file,
    and asks again — and it is bounded;
  - every search is recorded: who formulated it, the query, the hits and the conversation.

And the rules around them: a private conversation's lines reach only that conversation, a pack
another conversation's turn may read is searched as a room, a memory that could not be searched
is a gap and never "nothing was found", and the switch turns the whole step off.
"""

from __future__ import annotations

import logging
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.contracts import AgentRunResult
from openfactory.product import role as product_role
from openfactory.product.index import retrieval
from openfactory.product.index.items import conversation_digest
from openfactory.product.module import ProductModule
from openfactory.product.role import SEARCH_ROUNDS, SEARCHES_PER_ROUND, ProductRole
from tests import index_bed as bed


@pytest.fixture(autouse=True)
def _no_embedder_is_remembered():
    from openfactory.adapters.embed import registry

    registry._reset_for_tests()
    yield
    registry._reset_for_tests()


def _ts(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _recall(project, lines) -> None:
    """The product's conversation lines, as this turn's recall index would hold them."""
    from openfactory.memory.recall import INDEX_FILE, MemoryIndex
    from openfactory.paths import project_memory_dir

    held = MemoryIndex(project=project.name)
    for line in lines:
        held.add(line)
    held.save(Path(project_memory_dir(project)) / INDEX_FILE)


def _module(tmp_path, project, *, question: str, conversation: str = "person:U1",
            audience: str = "client", own: bool = True):
    """What `ProductModule._write_facts` and the role's search read of a module answering
    `question` — its checkout, its board, the turn's view and scope — and nothing else."""
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    ctx = SimpleNamespace(available=True, corpus=bed.corpus(tmp_path / "context"),
                          requirements_dir="requirements", domain=None)
    fake = SimpleNamespace(
        project=project, _combined=str(root), _turn_view=str(root) if own else str(tmp_path),
        _workspace=lambda: None, _board_cards=lambda: bed.cards(), context=lambda: ctx,
        _facts_for="U1", _question=question, _said_before="", _conversation=conversation,
        _documents_audience=audience, _product_model=None)
    fake._search_for_the_role = types.MethodType(ProductModule._search_for_the_role, fake)
    return fake, root


def _written(fake) -> Path:
    into = ProductModule._write_facts(fake)
    assert into is not None
    fake._facts_dir = into
    return into


class _Harness:
    """A harness that answers from a script, one answer per ask, and records every prompt."""

    name = "stub"

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        said = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return AgentRunResult(ok=True, summary=said)


class _Sandbox:
    def run(self, **_kw):
        return 0, ""


def _ws():
    from openfactory.adapters.sandbox.base import Workspace

    return Workspace(path="/tmp", branch="main", base_branch="main")


def _ask(role, question="Is there a fuel surcharge on our invoices?"):
    return role.answer(sandbox=_Sandbox(), workspace=_ws(), question=question)


# ── acceptance: before the turn, a file ─────────────────────────────────────────────────────────

def test_before_the_turn_the_hits_are_a_file_in_the_facts_pack(tmp_path):
    project, _index = bed.build(tmp_path)
    fake, _root = _module(tmp_path, project,
                          question="What holds today about invoice numbering?")

    into = _written(fake)

    found = (into / retrieval.FOUND_DIR / retrieval.BEFORE).read_text()
    assert "What holds today: REQ-0009." in found and "SUPERSEDED · REQ-0004" in found
    readme = (into / "README.md").read_text()
    assert f"`{into.name}/found/before-the-turn.md`" in readme
    assert retrieval.recorded(bed.KEY)[-1]["by"] == retrieval.ENGINE


def test_the_pre_turn_search_never_includes_an_unaddressed_line(tmp_path):
    """D12: what a group said to somebody else is searchable and never prompted — the engine's
    own search leaves it out, and only a search somebody asked for finds it, marked."""
    project, _index = bed.build(tmp_path)
    _recall(project, [
        bed.said("tidewater", "the zeppelin tariff is agreed for next year", ts=_ts(3)),
        bed.said("tidewater", "between us, the zeppelin tariff is a bluff", ts=_ts(2),
                 addressed=False)])
    fake, _root = _module(tmp_path, project, question="What about the zeppelin tariff?")

    into = _written(fake)

    before = (into / "found" / "before-the-turn.md").read_text()
    assert "zeppelin tariff is agreed" in before
    assert "bluff" not in before, "a line not said to the role was put in front of it"

    fake._search_for_the_role(["zeppelin tariff"], 1)

    asked = (into / "found" / "search-1.md").read_text()
    assert "bluff" in asked and "said in a group to somebody else" in asked


# ── the conversations' own rules ────────────────────────────────────────────────────────────────

def test_a_private_conversation_s_lines_reach_only_that_conversation(tmp_path):
    project, _index = bed.build(tmp_path)
    _recall(project, [bed.said("person:ana", "my zeppelin quote is private", ts=_ts(1))])

    bruno, _r = _module(tmp_path, project, question="the zeppelin quote",
                        conversation="person:bruno")
    into = _written(bruno)
    bruno._search_for_the_role(["zeppelin quote"], 1)
    assert "zeppelin quote is private" not in (into / "found" / "before-the-turn.md").read_text()
    assert "zeppelin quote is private" not in (into / "found" / "search-1.md").read_text()

    ana, _r = _module(tmp_path, project, question="the zeppelin quote", conversation="person:ana")
    into = _written(ana)
    ana._search_for_the_role(["zeppelin quote"], 1)
    assert "zeppelin quote is private" in (into / "found" / "search-1.md").read_text()
    assert "zeppelin quote is private" not in (into / "found" / "before-the-turn.md").read_text(), \
        "the conversation in front of the role is not searched before its own turn"


def test_a_pack_another_conversation_may_read_is_searched_as_a_room(tmp_path):
    """The shared view's degrade: an engineer in private, whose pack another turn may read, is
    searched for as a room — no internal document, and no private line, even their own."""
    project, _index = bed.build(tmp_path)
    _recall(project, [bed.said("person:edu", "my zeppelin note", ts=_ts(1))])
    question = "Nordwind margin discount renewed zeppelin note"

    own, _r = _module(tmp_path, project, question=question, conversation="person:edu",
                      audience="internal")
    into = _written(own)
    own._search_for_the_role([question], 1)
    assert "margin-review" in (into / "found" / "search-1.md").read_text()

    shared, _r = _module(tmp_path, project, question=question, conversation="person:edu",
                         audience="internal", own=False)
    into = _written(shared)
    shared._search_for_the_role([question], 1)
    for name in ("before-the-turn.md", "search-1.md"):
        text = (into / "found" / name).read_text()
        assert "margin-review" not in text and "12 percent" not in text, name
        assert "my zeppelin note" not in text, name


def test_a_client_s_own_turn_is_searched_for_a_client(tmp_path):
    """The module's scope, on the path every turn takes: a client in a conversation of their own
    — the pack theirs alone — is searched as a client, and the internal document is not found."""
    project, _index = bed.build(tmp_path)
    question = "Nordwind margin discount renewed"

    client, _r = _module(tmp_path, project, question=question, conversation="person:cai")
    into = _written(client)
    client._search_for_the_role([question], 1)

    for name in ("before-the-turn.md", "search-1.md"):
        text = (into / "found" / name).read_text()
        assert "margin-review" not in text and "12 percent" not in text, name


def test_the_scope_of_a_pack_others_may_read_is_a_room_s(tmp_path):
    """The module's own rule, beside the step's: the scope a shared pack is searched with is the
    client's audience, whatever the turn's own would be — two belts, each held."""
    from openfactory.contracts.document import CLIENT, INTERNAL
    from openfactory.product.module import _the_search_scope

    project, _index = bed.build(tmp_path)
    own, root = _module(tmp_path, project, question="x", conversation="person:edu",
                        audience=INTERNAL)
    shared, _r = _module(tmp_path, project, question="x", conversation="person:edu",
                         audience=INTERNAL, own=False)

    assert _the_search_scope(own, str(root)) == (INTERNAL, "person:edu", True)
    assert _the_search_scope(shared, str(root)) == (CLIENT, "person:edu", False)


def test_a_search_for_a_pack_others_may_read_is_a_room_s_whatever_it_is_handed(tmp_path):
    """The step's own belt: handed an internal audience and a private conversation for a pack that
    is not the turn's alone, both searches are still a room's."""
    project, _index = bed.build(tmp_path)
    _recall(project, [bed.said("person:edu", "my zeppelin note", ts=_ts(1))])
    question = "Nordwind margin discount renewed zeppelin note"

    _found, before = retrieval.before_the_turn(project, question=question, audience="internal",
                                               conversation="person:edu", own=False)
    _founds, asked = retrieval.for_the_role(project, [question], round_=1, audience="internal",
                                            conversation="person:edu", own=False)

    for text in (before, asked):
        assert "margin-review" not in text and "my zeppelin note" not in text


def test_the_search_before_the_turn_runs_once_per_turn(tmp_path):
    """The role is built again for a draft or a judgement after the answer: the pack it gets
    carries the same file, and the search is not run — nor recorded — twice."""
    project, _index = bed.build(tmp_path)
    fake, _root = _module(tmp_path, project, question="invoice numbering")

    first = _written(fake)
    second = _written(fake)

    assert (second / "found" / "before-the-turn.md").read_text().startswith("# Found")
    assert first != second
    assert [r["by"] for r in retrieval.recorded(bed.KEY)] == [retrieval.ENGINE]


def test_the_search_before_the_turn_never_runs_under_the_semaphore(tmp_path):
    from openfactory.product import semaphore
    from openfactory.product.module import _the_search_before_the_turn

    project, _index = bed.build(tmp_path)
    fake, root = _module(tmp_path, project, question="invoice numbering")

    with semaphore.held(project):
        assert _the_search_before_the_turn(fake, str(root)) == ({}, [])
    assert retrieval.recorded(bed.KEY) == []


# ── acceptance: the marker ──────────────────────────────────────────────────────────────────────

def test_a_busca_round_works_on_a_stub_harness(tmp_path):
    """The model writes the marker; the engine searches, writes the hits as a file, and asks again
    with the same prompt and a note naming the file; the reply carries no marker."""
    project, _index = bed.build(tmp_path)
    fake, _root = _module(tmp_path, project, question="Is there a fuel surcharge?")
    into = _written(fake)
    harness = _Harness("[[BUSCA: fuel surcharge]]",
                       "No — the fuel surcharge was dropped in 2022 (REQ-0007).")
    role = ProductRole(harness, mounted={"facts": into.name}, search=fake._search_for_the_role)

    answer = _ask(role)

    assert len(harness.prompts) == 2
    first, second = harness.prompts
    assert "[[BUSCA: <what to look for" in first, "the marker is offered to a role that can use it"
    assert second.startswith(first), "the turn continues with the prompt it was asked"
    assert f"`{into.name}/found/search-1.md`" in second
    found = (into / "found" / "search-1.md").read_text()
    assert "REQ-0007" in found and "DROPPED" in found
    assert f"`{into.name}/found/search-1.md`" in (into / "README.md").read_text()
    assert answer.ok and answer.text.startswith("No — the fuel surcharge") and "[[" not in answer.text
    last = retrieval.recorded(bed.KEY)[-1]
    assert (last["by"], last["round"], last["query"]) == (retrieval.ROLE, 1, "fuel surcharge")


def test_the_marker_is_bounded(caplog):
    """A role that asks for a search on every round gets `SEARCH_ROUNDS` of them, is told the
    last one is the last, and its answer stands — with the marker stripped."""
    asked: list = []

    def search(queries, round_):
        asked.append((tuple(queries), round_))
        return f"round {round_}: nothing new."

    harness = _Harness("[[BUSCA: fuel surcharge]]\nStill looking.")
    role = ProductRole(harness, mounted={"facts": ".openfactory-facts-ab12"}, search=search)

    with caplog.at_level(logging.WARNING, logger="openfactory.product.role"):
        answer = _ask(role)

    assert len(harness.prompts) == SEARCH_ROUNDS + 1
    assert [r for _q, r in asked] == list(range(1, SEARCH_ROUNDS + 1))
    assert "No more searches this turn" in harness.prompts[-1]
    assert "you may search once more" in harness.prompts[1] if SEARCH_ROUNDS > 1 else True
    assert answer.text == "Still looking." and "[[" not in answer.text
    assert "OPENFACTORY_PRODUCT_SEARCH_BOUND" in caplog.text
    assert "unparsed marker" not in caplog.text, \
        "the search marker is the role's own plumbing, stripped by name — not by the safety net"


def test_a_round_runs_a_few_searches_at_most():
    asked: list = []
    harness = _Harness("\n".join(f"[[BUSCA: thing {n}]]" for n in range(6)), "done")
    role = ProductRole(harness, search=lambda queries, round_: asked.append(queries) or "ok")

    _ask(role)

    assert asked == [[f"thing {n}" for n in range(SEARCHES_PER_ROUND)]]


def test_a_role_that_cannot_search_is_never_offered_the_marker():
    """No search wired — no pack, the switch off, a double — no marker in the prompt, and one the
    model writes anyway is plumbing that never reaches a person."""
    harness = _Harness("[[BUSCA: anything]]\nHello.")
    role = ProductRole(harness)

    answer = _ask(role)

    assert "[[BUSCA" not in harness.prompts[0] and len(harness.prompts) == 1
    assert answer.text == "Hello."


def test_a_search_that_failed_is_said_and_the_turn_goes_on():
    def broken(queries, round_):
        raise RuntimeError("the index is on fire")

    harness = _Harness("[[BUSCA: x]]", "Answered from what I have.")
    answer = _ask(ProductRole(harness, search=broken))

    assert "could not be run" in harness.prompts[1] and answer.text == "Answered from what I have."
    assert "on fire" not in harness.prompts[1], "the failure's own words stay in the log"


def test_the_module_offers_the_search_only_to_an_answer_with_its_pack_written(tmp_path,
                                                                            monkeypatch):
    from openfactory.product import facts
    from openfactory.product.loader import Corpus

    root = tmp_path / "ws"
    (root / "docs").mkdir(parents=True)
    monkeypatch.setattr(facts, "gather", lambda name, cards, read=None, **_k: (
        {"board.md": "# board\n" * 5}, []))
    monkeypatch.setattr("openfactory.product.module._the_search_before_the_turn",
                        lambda _m, _r: ({}, []))
    # #268's pieces of the role, which this is not about: no sources beyond the one, no chain
    monkeypatch.setattr("openfactory.product.module._the_sight", lambda _m: None)
    monkeypatch.setattr("openfactory.product.module._the_chain", lambda _m, _rm: "")
    fake = SimpleNamespace(
        _agent=_Harness("x"), _corpus_note=lambda: "",
        project=SimpleNamespace(name="acme", product=None, language=""),
        context=lambda: SimpleNamespace(corpus=Corpus(), domain=None),
        _board_cards=lambda: [], _workspace=lambda: None, _combined=str(root),
        _mounted_code=str(root / "code"), _search_for_the_role=lambda q, r: "note",
        mounts=lambda: None, onboarding=lambda: [])
    fake._write_facts = lambda: ProductModule._write_facts(fake)
    fake.mounted = lambda: ProductModule.mounted(fake)

    assert ProductModule._role(fake).search is None, "a draft or a judgement never searches"
    fake._facts_for, fake._question = "U1", "is there a fuel surcharge?"
    assert ProductModule._role(fake).search is fake._search_for_the_role
    monkeypatch.setenv(retrieval.SWITCH_ENV, "off")
    assert ProductModule._role(fake).search is None


# ── acceptance: every search is recorded ────────────────────────────────────────────────────────

def test_every_search_is_recorded_with_who_asked_the_query_the_hits_and_the_conversation(
        tmp_path, caplog):
    project, _index = bed.build(tmp_path)

    with caplog.at_level(logging.INFO, logger="openfactory.product.index"):
        retrieval.before_the_turn(project, question="What holds today about invoice numbering?",
                                  conversation="person:ana")
        retrieval.for_the_role(project, ["fuel surcharge"], round_=1,
                               conversation="person:ana")

    engine, role = retrieval.recorded(bed.KEY)[-2:]
    assert (engine["by"], role["by"]) == (retrieval.ENGINE, retrieval.ROLE)
    assert engine["query"] == "What holds today about invoice numbering?"
    assert role["query"] == "fuel surcharge" and role["round"] == 1 and role["overheard"]
    assert engine["conversation"] == conversation_digest("person:ana")
    assert "req:0009" in {h["id"].split("!")[0] for h in engine["hits"]}
    assert any(shown.split("!")[0] == "req:0004" for h in engine["hits"]
               for shown in h["history"]), "the record says what was shown under what"
    raw = retrieval.searches_path(bed.KEY).read_text()
    assert "person:ana" not in raw, "the conversation is kept as a digest, never read back"
    assert "invoice numbering" not in caplog.text, "the log carries the counts, never the words"
    assert "OPENFACTORY_PRODUCT_SEARCH product=" in caplog.text
    assert "OPENFACTORY_PRODUCT_FOUND project=tidewater by=engine searches=1 hits=" in caplog.text
    assert "OPENFACTORY_PRODUCT_FOUND project=tidewater by=role searches=1" in caplog.text, \
        "what retrieval costs a turn is measured: a line per file, with its size"


def test_the_record_forgets_what_the_transcript_forgets(tmp_path):
    from openfactory.memory.transcript import RETENTION_DAYS
    from openfactory.product.index.search import Found, Query

    old = datetime.now(UTC) - timedelta(days=RETENTION_DAYS + 5)
    retrieval.record(bed.KEY, by=retrieval.ENGINE, found=Found(query=Query(text="old words"),
                                                                hits=[]), now=old)
    retrieval.record(bed.KEY, by=retrieval.ENGINE, found=Found(query=Query(text="new words"),
                                                                hits=[]))

    assert [r["query"] for r in retrieval.recorded(bed.KEY)] == ["new words"]


def test_a_deletion_request_forgets_what_was_derived_from_the_conversations(tmp_path,
                                                                           monkeypatch):
    """`forget-conversations` deletes the rows; the index's lines, the search record's queries and
    the recall index the sync reads lines from are derived from them, and go with them — or the
    next turn would read the forgotten lines back into the index."""
    from typer.testing import CliRunner

    from openfactory.cli import app
    from openfactory.memory import transcript
    from openfactory.memory.recall import INDEX_FILE
    from openfactory.paths import project_memory_dir
    from openfactory.product.index.search import Query
    from openfactory.registry import ProjectRegistry

    project, _index = bed.build(tmp_path, said=[
        bed.said("tidewater", "the zeppelin tariff is agreed", ts=_ts(1))])
    ProjectRegistry().add(project)
    _recall(project, [bed.said("tidewater", "the zeppelin tariff is agreed", ts=_ts(1))])
    retrieval.run(project, Query(text="zeppelin tariff"), by=retrieval.ENGINE, conversation="")
    assert retrieval.recorded(bed.KEY)
    monkeypatch.setattr(transcript, "forget", lambda _where, **_k: 1)

    done = CliRunner().invoke(app, ["project", "forget-conversations", project.name, "--yes"])

    assert done.exit_code == 0, done.output
    assert "deleted 1 line(s) from the product's index" in done.output
    assert retrieval.recorded(bed.KEY) == []
    assert not (Path(project_memory_dir(project)) / INDEX_FILE).exists()
    found = retrieval.run(project, Query(text="zeppelin tariff"), by=retrieval.ENGINE,
                          conversation="")
    assert not found.hits, "a forgotten line came back from the index"
    assert retrieval.run(project, Query(text="invoice numbering"), by=retrieval.ENGINE,
                         conversation="").hits, "the documents are not a conversation's"


# ── the step's edges ────────────────────────────────────────────────────────────────────────────

def test_the_switch_turns_the_step_off(tmp_path, monkeypatch):
    from openfactory.product.module import _may_search, _the_search_before_the_turn

    project, _index = bed.build(tmp_path)
    fake, root = _module(tmp_path, project, question="invoice numbering")
    fake._facts_dir = tmp_path
    monkeypatch.setenv(retrieval.SWITCH_ENV, "off")

    assert _the_search_before_the_turn(fake, str(root)) == ({}, [])
    assert not _may_search(fake)


def test_a_memory_that_could_not_be_searched_is_a_gap_never_nothing(tmp_path, monkeypatch):
    project, _index = bed.build(tmp_path)
    fake, _root = _module(tmp_path, project, question="invoice numbering")

    def broken(*_a, **_k):
        raise RuntimeError("database disk image is malformed")

    monkeypatch.setattr(retrieval, "before_the_turn", broken)
    into = _written(fake)

    assert not (into / "found").exists()
    readme = (into / "README.md").read_text()
    assert "could not be searched" in readme and "unknown, not absent" in readme
    assert "database disk image is malformed" not in readme, \
        "what failed, in its own words, is the operator's — never in what the role reads"


def test_a_short_message_is_searched_with_the_lines_before_it():
    said = ("## Conversa até aqui (mais antigo primeiro)\n"
            "pessoa: what did we decide about invoice numbering?\n"
            "você: REQ-0009 holds.\n\n## Said elsewhere in this project\n- elsewhere: noise")

    assert retrieval.query_of("e o segundo?", said) == (
        "e o segundo?\nwhat did we decide about invoice numbering?\nREQ-0009 holds.")
    assert retrieval.query_of("what holds about invoice numbering?", said) == (
        "what holds about invoice numbering?")


def test_the_facts_section_names_what_the_engine_found():
    role = ProductRole(_Harness("x"), mounted={"facts": ".openfactory-facts-ab12"})

    section = "\n".join(role._facts_section())

    assert ".openfactory-facts-ab12/found/before-the-turn.md" in section
    assert product_role._FOUND_BEFORE == retrieval.BEFORE


def test_the_scheduled_pass_brings_the_index_up_to_the_documents(tmp_path, monkeypatch):
    """After the documents are read on the schedule, the index holds them — searchable at the next
    turn, without that turn paying for it."""
    from openfactory.product.domain import Domain
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    project = bed.project(tmp_path)
    ProjectRegistry().add(project)
    tree = bed.context(tmp_path)
    monkeypatch.setattr(ProductModule, "context", lambda self, **_k: SimpleNamespace(
        docs_path=str(tree), docs_commit="c0ffee", reason="", domain=Domain(),
        corpus=bed.corpus(tree), requirements_dir="requirements"))
    monkeypatch.setattr("openfactory.product.documents.ingest.ModelReader",
                        lambda **_k: bed.FixtureReader())

    acts._do_ingest_documents(KnowledgeRefreshInput(project=project.name))

    found = retrieval.run(project, retrieval.Query(text="What holds today about invoice "
                                                        "numbering?"),
                          by=retrieval.ENGINE, conversation="")
    assert any(h.number == 9 for h in found.hits)
    assert any(h.source.startswith("client/minutes/") for h in found.hits)
