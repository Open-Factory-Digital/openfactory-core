"""A person has more than one conversation with the product role (#335).

The product owner's page is a list of conversations, like every chat a person already uses: the
project's room, shared, and as many of one's own as one opens. A session is the person's private
key with a session id after it — `person:ana~k3f9a2` — and every rule that asked "is this the
caller's own key?" now asks "is its OWNER the caller's own key?". These tests hold that rule
wherever a private conversation is read:

  1. the key: minted only on one's own key, refused on anybody else's, never free text;
  2. the socket: a session's frames reach its owner and nobody else;
  3. the page names a session by its id alone — it still never spells a private key;
  4. memory: what Ana said in one session informs her others, and never Bruno's;
  5. the agenda, the distillate and the read model read a session as its owner's;
  6. the list of conversations lists one's own and nobody else's.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from openfactory import actions
from openfactory.actions import catalog
from openfactory.actions.base import PRODUCT, Actor
from openfactory.product.conversation import (
    is_private,
    key_for,
    owner_of,
    person_of,
    session_key,
    session_of,
)

ANA, BRUNO = "person:ana", "person:bruno"


# ── 1. the key ──────────────────────────────────────────────────────────────────────────────────

def test_a_session_is_its_owner_s_key_with_an_id_after_it():
    key = session_key(ANA, "k3f9a2")
    assert key == "person:ana~k3f9a2"
    assert is_private(key) and owner_of(key) == ANA and session_of(key) == "k3f9a2"
    assert person_of(key) == "ana" and person_of(ANA) == "ana"
    # a session of a session is the same person's, never nested
    assert session_key(key, "zz99") == "person:ana~zz99"
    # the first conversation keeps its key: what was said before sessions is where it was
    assert owner_of(ANA) == ANA and session_of(ANA) == ""


@pytest.mark.parametrize("session", ["", "ab", "K3F9A2!", "a b c d", "x" * 25, "../ana", "ana~b"])
def test_a_session_id_is_short_letters_and_digits_never_free_text(session):
    assert session_key(ANA, session) is None


def test_a_room_has_no_sessions_and_no_owner():
    assert session_key("acme", "k3f9a2") is None
    assert owner_of("acme") == "acme" and session_of("acme") == "" and person_of("acme") == ""
    assert person_of("visitor:abc~k3f9") == ""


def test_a_suffix_that_is_not_a_session_id_is_part_of_the_key():
    """`person:ana~Bruno` is not Ana's session: its suffix is no id the page could mint, so it is
    a key of its own — and a private key that is not the caller's."""
    assert owner_of("person:ana~Bruno Silva") == "person:ana~Bruno Silva"
    assert key_for(named="person:ana~Bruno Silva", own=ANA) is None


def test_one_s_own_session_may_be_named_and_another_person_s_never():
    assert key_for(named="person:ana~k3f9a2", own=ANA) == "person:ana~k3f9a2"
    assert key_for(named="person:bruno~k3f9a2", own=ANA) is None
    assert key_for(named="person:ana~k3f9a2", own=BRUNO) is None
    assert key_for(named="person:ana~k3f9a2", own="") is None
    # a CASE-changed prefix is still private, and still not Bruno's
    assert key_for(named="Person:ana~k3f9a2", own=BRUNO) is None


# ── 2. the socket ───────────────────────────────────────────────────────────────────────────────

def _sub(own: str, conversation: str):
    from openfactory.api.product_chat import Subscriber

    return Subscriber(person=own.split(":", 1)[-1], own=own, product="acme", project="acme",
                      conversation=conversation, may_read_room=True, frames=asyncio.Queue())


def test_a_session_s_frames_reach_its_owner_and_nobody_else():
    from openfactory.api.product_chat import may_receive

    key = "person:ana~k3f9a2"
    assert may_receive(_sub(ANA, key), product="acme", conversation=key)
    assert not may_receive(_sub(BRUNO, key), product="acme", conversation=key)
    assert not may_receive(_sub("", key), product="acme", conversation=key)
    # a subscriber of Ana's first conversation is not handed her session's frames
    assert not may_receive(_sub(ANA, ANA), product="acme", conversation=key)


# ── 3. the page names a session by its id ───────────────────────────────────────────────────────

def _project():
    return SimpleNamespace(name="acme", product=SimpleNamespace(agent_name="Clara",
                                                                 docs_repo="acme/docs"))


def test_the_page_opens_its_own_session_by_id():
    from openfactory.api.product_chat import conversation_for

    ana = Actor(id="ana", via="panel", conversation=ANA)
    key, why = conversation_for(ana, _project(), {"room": False, "session": "k3f9a2"})
    assert (key, why) == ("person:ana~k3f9a2", "")
    # no session: her first conversation, as before
    assert conversation_for(ana, _project(), {"room": False})[0] == ANA
    # the room still wins when the page asks for the room
    assert conversation_for(ana, _project(), {"room": True, "session": "k3f9a2"})[0] == "acme"


@pytest.mark.parametrize("session", ["bruno", "../x", "A B"])
def test_a_session_the_page_cannot_mint_is_refused(session):
    from openfactory.api.product_chat import conversation_for

    ana = Actor(id="ana", via="panel", conversation=ANA)
    key, why = conversation_for(ana, _project(), {"room": False, "session": session})
    if session == "bruno":
        # a well-formed id is Ana's own session called "bruno" — never Bruno's conversation
        assert key == "person:ana~bruno" and not why
    else:
        assert key == "" and why


def test_a_caller_nobody_keyed_has_no_sessions():
    from openfactory.api.product_chat import conversation_for

    cli = Actor(id="cli", via="cli")
    key, why = conversation_for(cli, _project(), {"room": False, "session": "k3f9a2"})
    assert key == "" and why


# ── 4. memory ───────────────────────────────────────────────────────────────────────────────────

def _row(where: str, text: str, ts: str, role: str = "person", actor: str = "") -> dict:
    return {"ticket": where, "ts": ts, "role": role, "extra": {"text": text, "actor": actor}}


def test_what_ana_said_in_one_session_informs_her_others_and_never_bruno_s(tmp_path):
    from openfactory.memory.recall import recall

    rows = [_row("person:ana~aaaa1", "o fechamento contabil roda no quinto dia util",
                 "2026-09-20T10:00:00+00:00", actor="ana"),
            _row("person:bruno~bbbb1", "o fechamento contabil do bruno e segredo",
                 "2026-09-20T11:00:00+00:00", actor="bruno")]

    def hits(own: str) -> set[str]:
        found = recall("acme", "fechamento contabil", index_dir=tmp_path / own.replace(":", "_"),
                       own=own, exclude_where=own, transcript_rows=lambda _fetch: rows,
                       messages_scan=lambda *_a, **_k: [],
                       now=datetime(2026, 9, 25, tzinfo=UTC))
        return {h.said.where for h in found}

    assert hits("person:ana~cccc1") == {"person:ana~aaaa1"}
    assert hits(ANA) == {"person:ana~aaaa1"}
    assert hits("person:bruno~dddd1") == {"person:bruno~bbbb1"}
    assert hits("acme") == set(), "a room's turn read somebody's private conversation"


# ── 5. the agenda, the distillate, the read model ───────────────────────────────────────────────

def test_what_is_owed_in_a_session_is_on_its_owner_s_agenda_and_nobody_else_s():
    from openfactory.memory.ledger import DELIVERY, Loop
    from openfactory.product import agenda

    loop = Loop(kind=DELIVERY, subject="7", owner="product", ts="2026-09-20T10:00:00+00:00",
                context={"conversation": "person:ana~k3f9a2"})
    where = agenda.audience(loop, room="acme")
    assert not where.room
    assert agenda.sees(agenda.Viewer(own=ANA, person="ana"), where)
    # a turn in another of Ana's sessions reads it too: it is Ana's, wherever she is
    assert agenda.sees(agenda.Viewer(own="person:ana~zz99"), where)
    assert not agenda.sees(agenda.Viewer(own=BRUNO, person="bruno"), where)
    assert not agenda.sees(agenda.Viewer(own="person:bruno~k3f9a2"), where)
    assert not agenda.sees(agenda.Viewer(own="acme"), where)


def test_a_decision_asked_in_a_session_is_its_owner_s_to_answer_from_any_of_them():
    from openfactory.memory.ledger import DECISION, Loop
    from openfactory.product import agenda, module

    scope = module._asked_of("ana", "person:ana~k3f9a2")
    loop = Loop(kind=DECISION, subject="d", owner="product", ts="2026-09-20T10:00:00+00:00",
                context=scope)
    assert module._answered_by(loop, person="ana", where=("person:ana~zz99",), room="acme")
    assert module._answered_by(loop, person="ana", where=(ANA,), room="acme")
    assert not module._answered_by(loop, person="bruno", where=("person:ana~zz99",), room="acme")
    assert not module._answered_by(loop, person="ana", where=("acme",), room="acme")
    # and it is on her panel's agenda, which is keyed by her first conversation's key
    where = agenda.audience(loop, room="acme")
    assert agenda.sees(agenda.Viewer(own=ANA, person="ana"), where)
    assert not agenda.sees(agenda.Viewer(own=BRUNO, person="bruno"), where)


def test_the_distillate_of_a_session_is_its_owner_s_reading(monkeypatch):
    from openfactory.product import distil

    seen: list = []
    monkeypatch.setattr("openfactory.product.speaker.person",
                        lambda project, who: seen.append(who) or SimpleNamespace(id=who))
    monkeypatch.setattr("openfactory.product.documents.record.turn_audience",
                        lambda person, private: f"reading-of-{person.id}")
    assert distil._audience(_project(), "person:ana~k3f9a2") == "reading-of-ana"
    assert seen == ["ana"]


def test_the_read_model_calls_one_s_own_session_one_s_own():
    from openfactory.product.model import Names

    names = Names.__new__(Names)
    names.speaker = "ana"
    import re

    match = re.search(r"person:[^\s]+", "in person:ana~k3f9a2 today")
    assert names._conversation(match) == "[your private conversation]"
    names.speaker = "bruno"
    assert names._conversation(match) == "[a private conversation]"


# ── 6. the list of conversations ────────────────────────────────────────────────────────────────

@pytest.fixture
def stored(monkeypatch):
    from openfactory.memory import transcript

    rows = [
        _row("acme", "@po bom dia a todos", "2026-09-20T09:00:00+00:00", actor="ana"),
        _row("person:ana~aaaa1", "@po Qual é o valor mensal do plano empresarial para cinquenta "
                                 "pessoas com suporte?", "2026-09-20T10:00:00+00:00", actor="ana"),
        _row("person:ana~aaaa1", "Depende do plano.", "2026-09-20T10:01:00+00:00", role="agent"),
        _row("person:bruno~bbbb1", "o segredo do bruno", "2026-09-21T10:00:00+00:00",
             actor="bruno"),
        _row(ANA, "minha primeira conversa", "2026-09-19T10:00:00+00:00", actor="ana"),
        _row("person:ana~eeee1", "outra pergunta", "2026-09-22T10:00:00+00:00", actor="ana"),
    ]
    # newest first, as some stores hand them back: the title is still the FIRST thing asked
    monkeypatch.setattr(transcript, "rows", lambda project, limit=0: (list(reversed(rows)), False))
    monkeypatch.setattr(catalog, "_product_module",
                        lambda _name, **_k: (object(), SimpleNamespace(
                            name="acme", product=SimpleNamespace(agent_name="Clara")), None))


@pytest.mark.asyncio
async def test_a_person_is_listed_their_own_conversations_newest_first(stored):
    out = await actions.perform("product_sessions", by=Actor(id="ana", via="panel",
                                                               conversation=ANA), project="acme")
    assert out.ok, out.message
    listed = out.data["sessions"]
    assert [s["session"] for s in listed] == ["eeee1", "aaaa1", ""]
    first = listed[1]
    assert first["title"].startswith("Qual é o valor mensal") and first["title"].endswith("…")
    assert "@po" not in first["title"] and len(first["title"]) <= 61
    assert first["turns"] == 2 and first["last"] == "Depende do plano."
    assert out.data["room"]["key"] == "acme" and out.data["agent"] == "Clara"
    assert "bruno" not in repr(out.data), "another person's conversation was listed"


@pytest.mark.asyncio
async def test_a_caller_nobody_keyed_is_listed_the_room_alone(stored):
    out = await actions.perform("product_sessions", by=Actor(id="cli", via="cli"), project="acme")
    assert out.ok and out.data["sessions"] == [] and out.data["keyed"] is False
    assert out.data["room"]["text"] == "@po bom dia a todos"


def test_the_list_is_registered_as_a_read_of_the_product_area():
    spec = actions.spec("product_sessions")
    assert spec.scope == PRODUCT and spec.needs_admin is False
    assert tuple(spec.required) == ("project",)
