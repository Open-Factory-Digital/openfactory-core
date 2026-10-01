"""A private key is read one way, whatever its case (#347).

TWO READERS DISAGREED. Measured on `34c91c7`: `person_of("Person:bruno")` was "bruno" (it tested
its prefix lower-cased) while `owner_of` left `Person:bruno` as it is, so `key_for` refused Bruno
that key while the read model was ready to call it his. The read model's redaction found a key's
prefix in lower case only, so `Person:bruno` was no key to it: a pack that did not know bruno
handed Ana `said in Person:bruno`, his key and his id.

THE READING DECIDED (`product/conversation.py`). "Is it private?" reads the prefix whatever its
case, because it refuses. "Whose is it?" reads the key only as a surface mints it, because it
grants: v0.2.0 to v0.3.0 read `Person:bob` as a room, so turns anybody wrote under that spelling
may be in a store today, and folding the case would hand them to Bob as his own. A case-variant
key is private and nobody's.

Every reader is held to that one answer here, beside the key as a surface mints it, which stays
Bruno's on every one of them. Without that control, readers that refused every key would pass.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from openfactory.product.conversation import (
    PERSON,
    is_private,
    key_for,
    owner_of,
    person_of,
)

ANA, BRUNO = "person:ana", "person:bruno"

#: Bruno's key and one of his sessions as `api/app.py::_conversation_of` and `session_key` mint them
MINTED = ["person:bruno", "person:bruno~k3f9a2"]
#: the same two in casings no surface mints, the session key among them (the issue's own example)
VARIANTS = ["Person:bruno", "PERSON:bruno", "pErSoN:bruno", "Person:bruno~k3f9a2",
            "PERSON:bruno~k3f9a2"]


def _received(key: str) -> bool:
    """Whether Bruno's socket, subscribed to `key`, is handed its frames."""
    from openfactory.api.product_chat import Subscriber, may_receive

    sub = Subscriber(person="bruno", own=BRUNO, product="acme", project="acme",
                     conversation=key, may_read_room=True, frames=asyncio.Queue())
    return may_receive(sub, product="acme", conversation=key)


def _on_the_agenda(key: str) -> bool:
    """Whether what is owed in `key` is on Bruno's agenda."""
    from openfactory.memory.ledger import DELIVERY, Loop
    from openfactory.product import agenda

    loop = Loop(kind=DELIVERY, subject="7", owner="product", ts="2026-09-20T10:00:00+00:00",
                context={"conversation": key})
    return agenda.sees(agenda.Viewer(own=BRUNO, person="bruno"),
                       agenda.audience(loop, room="acme"))


def _answered(key: str) -> bool:
    """Whether a decision asked of Bruno in `key` is his to answer from his own conversation."""
    from openfactory.memory.ledger import DECISION, Loop
    from openfactory.product import module

    loop = Loop(kind=DECISION, subject="d", owner="product", ts="2026-09-20T10:00:00+00:00",
                context=module._asked_of("bruno", key))
    return module._answered_by(loop, person="bruno", where=(BRUNO,), room="acme")


def _recalled(key: str, index_dir) -> bool:
    """Whether a turn in another of Bruno's sessions is handed what was said under `key`."""
    from openfactory.memory.recall import recall

    rows = [{"ticket": key, "ts": "2026-09-20T10:00:00+00:00", "role": "person",
             "extra": {"text": "o fechamento contabil roda no quinto dia util", "actor": "bruno"}}]
    own = "person:bruno~zz99"
    found = recall("acme", "fechamento contabil", index_dir=index_dir, own=own,
                   exclude_where=own, transcript_rows=lambda _fetch: rows,
                   messages_scan=lambda *_a, **_k: [], now=datetime(2026, 9, 25, tzinfo=UTC))
    return any(h.said.where == key for h in found)


def _distilled_as_his(key: str, monkeypatch) -> bool:
    """Whether the distillate of `key` is read as Bruno's (`distil._audience`)."""
    from openfactory.product import distil

    monkeypatch.setattr("openfactory.product.speaker.person",
                        lambda project, who: SimpleNamespace(id=who))
    monkeypatch.setattr("openfactory.product.documents.record.turn_audience",
                        lambda person, private: f"reading-of-{person.id}")
    return distil._audience(SimpleNamespace(name="acme"), key) == "reading-of-bruno"


def _called_his(key: str) -> bool:
    """Whether the read model tells Bruno a line said in `key` was said in his own conversation."""
    from openfactory.product.model import Names

    said = Names({"bruno"}, speaker="bruno").redact(f"said in {key}, yes")
    return said == "said in [your private conversation], yes"


@pytest.mark.parametrize("key,his", [(k, True) for k in MINTED] + [(k, False) for k in VARIANTS])
def test_every_reader_gives_one_answer_to_whose_a_key_is(key, his, tmp_path, monkeypatch):
    assert is_private(key), "a private key read as a room"
    answers = {
        "owner_of": owner_of(key) == BRUNO,
        "person_of": person_of(key) == "bruno",
        "key_for": key_for(named=key, own=BRUNO) == key,
        "the socket": _received(key),
        "the agenda": _on_the_agenda(key),
        "a decision asked there": _answered(key),
        "recall": _recalled(key, tmp_path / "index"),
        "the distillate": _distilled_as_his(key, monkeypatch),
        "the read model": _called_his(key),
    }
    assert answers == dict.fromkeys(answers, his), (
        f"{key!r} is {'Bruno' if his else 'nobody'}'s, and these readers say otherwise: "
        f"{sorted(name for name, said in answers.items() if said != his)}")


@pytest.mark.parametrize("key", VARIANTS)
def test_a_case_variant_of_a_person_s_key_is_nobody_s_and_never_a_room(key):
    assert is_private(key)
    # its owner is no key a surface mints, so no caller's own key can ever equal it
    assert not owner_of(key).startswith(PERSON)
    assert person_of(key) == ""
    for own in (BRUNO, ANA, ""):
        assert key_for(named=key, own=own) is None, own


@pytest.mark.parametrize("key", ["Person:bruno", "PERSON:bruno~k3f9a2", "Visitor:abcdefgh12"])
def test_the_read_model_withholds_a_private_key_whatever_its_case(key):
    """Ana's model does not know bruno, so nothing else would withhold his id from her."""
    from openfactory.product.model import Names

    said = Names({"ana"}, speaker="ana").redact(f"said in {key}, yes")
    assert said == "said in [a private conversation], yes"
