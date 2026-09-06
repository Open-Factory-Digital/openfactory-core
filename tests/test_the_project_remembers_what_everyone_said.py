"""Project memory across stores (#33, hole 3): one read over everything anybody said.

Memory was per conversation: `transcript.recent` reads one thread out of the last few hundred
rows, the tech-lead's messages live in a second store, and nothing read across threads or across
the two — so "knows everything everyone said" was not a property either read could grow into by
scanning harder. Now `memory/recall.py` keeps one inverted index per project, refreshed from what
is NEW in both stores, forgetting what retention forgets, and answers a question out of it ranked
by how much of the question a turn carries and how recent it is. The product role gets the block
beside the conversation in front of it, and `product_recall` gives it to a person with the link
to where and when.

A PRIVATE CONVERSATION STAYS PRIVATE: #46 made the per-person key the one control over who reads
a conversation, and a project-wide read that surfaced Ana's private turns to Bruno's question
would undo it from the other side.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory import actions
from openfactory.actions import catalog
from openfactory.actions.base import PRODUCT, Actor
from openfactory.memory import messages, recall
from openfactory.memory.recall import (
    CHANNEL,
    CONVERSATION,
    INDEX_FILE,
    Hit,
    MemoryIndex,
    Said,
    gather,
    refresh,
    render_recall,
    tokens,
)

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _ts(days: float) -> str:
    return (T0 + timedelta(days=days)).isoformat()


def _row(days: float, where: str, text: str, *, role: str = "person", actor: str = "ana") -> dict:
    return {"ts": _ts(days), "ticket": where, "role": role, "extra": {"text": text, "actor": actor}}


ROWS = [
    _row(0, "acme", "precisamos do fechamento mensal do #12"),
    _row(1, "person:bruno", "o fechamento atrasou de novo", actor="bruno"),
    _row(2, "person:ana", "segredo: a Ana pediu o relatório de fechamento", actor="ana"),
    _row(3, "acme", "anotado — abro o #12 quando confirmarem", role="agent", actor=""),
    _row(4, "acme", "e o boleto?", actor="carla"),
]
MSGS = [
    messages.Message(kind=messages.TOLD, text="o fechamento vai atrasar uma semana", ts=_ts(1.5),
                     channel="C1", by="dora"),
    messages.Message(kind=messages.SAID, text="fechamento: o #12 entrou na fila", ts=_ts(3.5),
                     channel="C1"),
    messages.Message(kind=messages.ANSWERED, text="yes", ts=_ts(3.6), channel="C1"),
]


@pytest.fixture
def stores(monkeypatch):
    """Both stores in memory: the transcript rows through the `transcript_rows` seam, the
    channel through `messages.read`."""
    calls: list[int] = []

    def transcript_rows(fetch: int) -> list[dict]:
        calls.append(fetch)
        return sorted(ROWS, key=lambda r: r["ts"])[-fetch:]

    monkeypatch.setattr(recall.messages, "read", lambda project, scan=None: list(MSGS))
    return SimpleNamespace(transcript_rows=transcript_rows, calls=calls)


def _recall(query: str, tmp_path: Path, stores, **kw) -> list[Hit]:
    return recall.recall("acme", query, index_dir=tmp_path, transcript_rows=stores.transcript_rows,
                         now=T0 + timedelta(days=5), **kw)


# --- words -----------------------------------------------------------------------------------

def test_words_are_flattened_and_stopwords_dropped():
    assert tokens("Fechamento MENSAL — a ação do #12 e o boleto") == [
        "fechamento", "mensal", "acao", "12", "boleto"]
    assert tokens("ação") == tokens("acao") == ["acao"]
    assert tokens("a o e de the and") == []


# --- the index -----------------------------------------------------------------------------

def _said(i: str, text: str, *, days: float = 0, where: str = "acme") -> Said:
    return Said(id=i, ts=_ts(days), store=CONVERSATION, where=where, role="person", actor="ana",
                text=text)


def test_the_index_adds_once_and_advances_its_watermark():
    index = MemoryIndex(project="acme")
    assert index.add(_said("1", "fechamento mensal", days=1))
    assert not index.add(_said("1", "fechamento mensal", days=1)), "added twice"
    assert not index.add(_said("2", "   ", days=2)), "an empty turn was indexed"
    assert index.postings["fechamento"] == ["1"] and index.last_ts[CONVERSATION] == _ts(1)


def test_the_index_round_trips_through_disk_and_refuses_a_stranger(tmp_path):
    index = MemoryIndex(project="acme")
    index.add(_said("1", "fechamento mensal"))
    index.save(tmp_path / INDEX_FILE)
    back = MemoryIndex.load(tmp_path / INDEX_FILE, "acme")
    assert back.rows == index.rows and back.postings == index.postings
    assert back.last_ts == index.last_ts
    assert MemoryIndex.load(tmp_path / INDEX_FILE, "other").rows == {}, "another project's index"
    (tmp_path / INDEX_FILE).write_text('{"version": 99, "project": "acme"}')
    assert MemoryIndex.load(tmp_path / INDEX_FILE, "acme").rows == {}, "an unknown version"
    assert MemoryIndex.load(tmp_path / "nowhere.json", "acme").rows == {}


def test_forgetting_drops_rows_and_their_words():
    index = MemoryIndex(project="acme")
    index.add(_said("old", "boleto antigo", days=0))
    index.add(_said("new", "boleto novo", days=10))
    assert index.forget_before(_ts(5)) == 1
    assert "old" not in index.rows and index.postings["boleto"] == ["new"]
    assert "antigo" not in index.postings


def test_search_prefers_more_of_the_question_then_rarer_words_then_newer():
    index = MemoryIndex(project="acme")
    index.add(_said("a", "fechamento mensal", days=1))
    index.add(_said("b", "fechamento", days=2))
    index.add(_said("c", "fechamento", days=3))
    index.add(_said("d", "boleto raro", days=0))
    ids = [h.said.id for h in index.search("fechamento mensal")]
    assert ids[:1] == ["a"], "the row carrying both words did not come first"
    assert ids[1:3] == ["c", "b"], "ties did not go to the newest"
    assert [h.said.id for h in index.search("boleto")] == ["d"]
    assert index.search("nada disso") == [] and index.search("") == []
    one, = index.search("raro")
    assert one.score > index.search("fechamento")[0].score, "a rare word weighs no more"


# --- the two stores ------------------------------------------------------------------------

def test_gather_reads_both_stores_and_says_where_each_turn_came_from(stores):
    said, full = gather("acme", fetch=100, transcript_rows=stores.transcript_rows)
    assert not full
    by_store = {s.store: [] for s in said}
    for s in said:
        by_store[s.store].append(s)
    assert len(by_store[CONVERSATION]) == 5 and len(by_store[CHANNEL]) == 2
    told = next(s for s in by_store[CHANNEL] if s.actor == "dora")
    assert (told.where, told.role) == ("C1", "person")
    assert not any("yes" == s.text for s in said), "an answer row is not something anybody said"
    agent = next(s for s in by_store[CONVERSATION] if s.role == "agent")
    assert agent.actor == ""


def test_refresh_reads_once_and_then_only_what_is_new(tmp_path, stores, monkeypatch):
    index = refresh("acme", tmp_path, transcript_rows=stores.transcript_rows, now=T0)
    assert len(index.rows) == 7 and (tmp_path / INDEX_FILE).is_file()
    assert index.last_ts[CONVERSATION] == _ts(4)
    ROWS.append(_row(6, "acme", "o boleto venceu", actor="carla"))
    try:
        again = refresh("acme", tmp_path, transcript_rows=stores.transcript_rows, now=T0)
        assert len(again.rows) == 8 and again.last_ts[CONVERSATION] == _ts(6)
        assert stores.calls == [recall.FETCH, recall.FETCH], "the store was asked more than once"
    finally:
        ROWS.pop()


def test_refresh_widens_the_window_when_everything_it_saw_was_new(tmp_path):
    """A window that came back full and entirely newer than the index may have rows sitting
    between — read again, wider, up to the ceiling."""
    many = [_row(10 + i / 100, "acme", f"turno {i}") for i in range(3)]
    seen: list[int] = []

    def rows(fetch: int) -> list[dict]:
        seen.append(fetch)
        return many[-2:] if fetch <= 2 else many

    index = MemoryIndex(project="acme")
    index.add(_said("older", "antes de tudo", days=1))
    index.save(tmp_path / INDEX_FILE)
    monkeypatch_fetch = 2
    original = recall.FETCH
    recall.FETCH = monkeypatch_fetch
    try:
        got = refresh("acme", tmp_path, transcript_rows=rows, now=T0)
    finally:
        recall.FETCH = original
    assert seen == [2, 8], seen
    assert len(got.rows) == 4


def test_a_store_that_will_not_answer_costs_the_refresh_and_keeps_the_index(tmp_path):
    index = MemoryIndex(project="acme")
    index.add(_said("1", "fechamento mensal"))
    index.save(tmp_path / INDEX_FILE)

    def broken(fetch: int) -> list[dict]:
        raise RuntimeError("the table is gone")

    got = refresh("acme", tmp_path, transcript_rows=broken, now=T0)
    assert list(got.rows) == ["1"]


def test_the_index_forgets_what_retention_forgot(tmp_path, stores):
    late = T0 + timedelta(days=recall.RETENTION_DAYS + 3)
    index = refresh("acme", tmp_path, transcript_rows=stores.transcript_rows, now=late)
    assert {r["ts"] for r in index.rows.values()} == {_ts(3), _ts(3.5), _ts(4)}, (
        "older turns survived — the cutoff is 180 days before `now`, and the turn ON it stays")


# --- recall ----------------------------------------------------------------------------------

def test_a_private_conversation_comes_back_only_to_its_own_person(tmp_path, stores):
    for_bruno = _recall("fechamento", tmp_path, stores, own="person:bruno")
    wheres = {h.said.where for h in for_bruno}
    assert "person:ana" not in wheres, "Ana's private conversation reached Bruno"
    assert "person:bruno" in wheres and "acme" in wheres and "C1" in wheres
    for_ana = _recall("fechamento", tmp_path, stores, own="person:ana")
    assert "person:ana" in {h.said.where for h in for_ana}
    for_room = _recall("fechamento", tmp_path, stores, own="acme")
    assert not any(h.said.where.startswith("person:") for h in for_room)


def test_the_current_conversation_is_left_out_and_the_limit_holds(tmp_path, stores):
    hits = _recall("fechamento", tmp_path, stores, own="acme", exclude_where="acme")
    assert hits and not any(h.said.where == "acme" for h in hits)
    assert len(_recall("fechamento", tmp_path, stores, own="acme", limit=1)) == 1


def test_the_block_says_who_where_and_when_within_a_budget():
    hits = [Hit(_said("1", "fechamento mensal", days=1), 2.0),
            Hit(Said(id="2", ts=_ts(2), store=CHANNEL, where="channel", role="agent", actor="",
                     text="fechamento na fila"), 1.0)]
    text = render_recall(hits, agent_name="Ana PO")
    assert text.startswith("## Said elsewhere in this project")
    assert "- 2026-09-02 · ana, in `acme`: fechamento mensal" in text
    assert "- 2026-09-03 · Ana PO, in the channel: fechamento na fila" in text
    assert render_recall([]) == ""
    assert render_recall(hits, budget=60).count("\n") == 1, "the budget did not cut"


# --- the role and the row ------------------------------------------------------------------

def test_what_was_said_elsewhere_reaches_the_role_beside_the_conversation(monkeypatch):
    from openfactory.runtime.temporal import activities

    hits = [Hit(_said("1", "fechamento mensal", days=1), 2.0)]
    asked: dict = {}

    def fake_recall(project, query, *, index_dir, own="", exclude_where="", **_kw):
        asked.update(project=project, query=query, own=own, exclude=exclude_where)
        return hits

    monkeypatch.setattr(recall, "recall", fake_recall)
    monkeypatch.setattr("openfactory.paths.project_memory_dir", lambda p: Path("/nowhere"))
    project = SimpleNamespace(name="acme", product=SimpleNamespace(agent_name="Ana PO"))
    out = activities._with_elsewhere(project, "## The conversation so far\nana: oi", "fechamento?",
                                     own="person:bruno", agent_name="Ana PO")
    assert out.startswith("## The conversation so far\nana: oi\n\n## Said elsewhere")
    assert asked == {"project": "acme", "query": "fechamento?", "own": "person:bruno",
                     "exclude": "person:bruno"}
    monkeypatch.setattr(recall, "recall", lambda *a, **k: [])
    assert activities._with_elsewhere(project, "before", "x", own="acme") == "before"

    def broken(*a, **k):
        raise RuntimeError("no index")

    monkeypatch.setattr(recall, "recall", broken)
    assert activities._with_elsewhere(project, "before", "x", own="acme") == "before"


def test_both_turns_of_the_role_read_the_project_memory():
    src = (ROOT / "openfactory/runtime/temporal/activities.py").read_text(encoding="utf-8")
    assert "before = _with_elsewhere(project, before, request, own=key" in src, "ask forgot"
    assert "said = _with_elsewhere(project, said, inp.message, own=thread" in src, "say forgot"


@pytest.fixture
def row(monkeypatch, tmp_path):
    project = SimpleNamespace(name="acme", product=SimpleNamespace(agent_name="Ana PO"))
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (object(), project, None))
    monkeypatch.setattr("openfactory.paths.project_memory_dir", lambda p: tmp_path)
    monkeypatch.setattr(recall, "gather", lambda *a, **k: (
        [Said(id="1", ts=_ts(1), store=CONVERSATION, where="acme", role="person", actor="ana",
              text="precisamos do fechamento mensal"),
         Said(id="2", ts=_ts(2), store=CONVERSATION, where="person:ana", role="person",
              actor="ana", text="fechamento privado")], False))
    return project


@pytest.mark.asyncio
async def test_product_recall_answers_with_where_and_when(row):
    bruno = Actor(id="bruno", via="panel", conversation="person:bruno")
    out = await actions.perform("product_recall", by=bruno, project="acme", query="fechamento")
    assert out.ok, out.message
    assert [h["where"] for h in out.data["hits"]] == ["acme"], "Ana's private turn reached Bruno"
    assert "ana, in `acme`: precisamos do fechamento mensal" in out.message
    ana = Actor(id="ana", via="panel", conversation="person:ana")
    out = await actions.perform("product_recall", by=ana, project="acme", query="fechamento")
    assert {h["where"] for h in out.data["hits"]} == {"acme", "person:ana"}
    none = await actions.perform("product_recall", by=bruno, project="acme", query="boleto")
    assert none.ok and "nothing in this project mentions 'boleto'" in none.message
    empty = await actions.perform("product_recall", by=bruno, project="acme", query="  ")
    assert not empty.ok


def test_the_row_is_a_read():
    spec = actions.spec("product_recall")
    assert spec.scope == PRODUCT and spec.needs_admin is False
    assert tuple(spec.required) == ("project", "query") and tuple(spec.optional) == ()
