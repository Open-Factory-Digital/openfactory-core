"""A module whose `answer` predates the intake answers EVERY turn — not only the first.

WHAT THE CI RED OF 2026-09-06 ACTUALLY WAS (the review of #66). The channel passed `intake=`
"only when there is one, so a module double that predates the intake keeps answering first turns
exactly as before" — and "first turns" was doing all the work. `note_turn` opens a case with facts
on turn one, so from turn two on the block is non-empty, the keyword is passed, a module that does
not declare it raises, and the channel takes the mute path: the client reads "something broke on my
side" on every turn for `CASE_TTL_SECONDS`, and every occurrence pages. The shipped module declares
`intake`, so no deployment running it is exposed; the suite's doubles and any add-on written to
that comment's promise are. The store leak (#66) is what made it visible; this is what made it a
failure — and after #66 no test reaches a double with a non-empty intake, so this pins the
two-turn shape on purpose.

The keyword goes to a module that DECLARES it — by name or through `**kwargs` — read from the
signature, never by trying and catching (a TypeError raised inside a real `answer` must not be
mistaken for a module that does not take the keyword).
"""

from __future__ import annotations

import pytest

from openfactory.product import case as _case
from openfactory.product import channel as pc


class _Product:
    enabled = True
    slack_channel = "C1"
    agent_name = "Nina"

    def __init__(self, admins):
        self.admins = admins


class _Project:
    name = "books"
    language = "pt-BR"

    def __init__(self, admins=("UADM",)):
        self.product = _Product(list(admins))


class _Answer:
    ok = True
    text = "certo."
    decisions = []
    is_defect = False
    is_request = False


class _Base:
    """Only what the plain-message path touches; anything else raising is the point."""

    def __init__(self):
        self.calls: list[dict] = []

    def settle_acceptance(self, text):
        return None

    def confirmed(self, text, *, proposal):
        return None

    def context(self):
        class _Ctx:
            available = True
            reason = ""

        return _Ctx()

    def close_decisions_answered(self, *, channel=""):
        pass


class _Legacy(_Base):
    """A double written before the intake existed — every fake in the suite, any add-on's."""

    def answer(self, text, *, conversation="", pending=""):
        self.calls.append({"pending": pending})
        return _Answer()


class _Declares(_Base):
    def answer(self, text, *, conversation="", pending="", intake=""):
        self.calls.append({"pending": pending, "intake": intake})
        return _Answer()


class _Kwargs(_Base):
    def answer(self, text, *, conversation="", pending="", **more):
        self.calls.append({"pending": pending, **more})
        return _Answer()


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    from openfactory.memory import transcript

    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    monkeypatch.setattr(transcript, "render", lambda *a, **k: "")
    _case._reset_for_tests()
    yield
    _case._reset_for_tests()


def _two_turns(module):
    project = _Project()
    first = pc.handle(project, text="o backup falha às segundas", user="UADM", thread="C1",
                      channel="C1", module=module)
    assert _case.block_for(project, "C1", "UADM"), "turn one must have opened a case with facts"
    second = pc.handle(project, text="e só no servidor de Lisboa", user="UADM", thread="C1",
                       channel="C1", module=module)
    return first, second


def test_a_double_that_predates_the_intake_answers_the_second_turn_too():
    module = _Legacy()

    first, second = _two_turns(module)

    assert first == second == _Answer.text, (
        f"turn two took the mute path: {second!r} — the keyword was passed to a module that "
        f"does not declare it")
    assert len(module.calls) == 2 and "intake" not in module.calls[1]


def test_a_module_that_declares_the_intake_receives_it_on_the_second_turn():
    module = _Declares()

    _two_turns(module)

    assert module.calls[0]["intake"] == "", "nothing to continue on turn one"
    assert "This intake so far" in module.calls[1]["intake"], module.calls[1]


def test_a_module_taking_kwargs_receives_it_too():
    module = _Kwargs()

    _two_turns(module)

    assert "intake" in module.calls[1] and "This intake so far" in module.calls[1]["intake"]


def test_the_decision_is_read_from_the_signature_not_by_trying(monkeypatch):
    """A TypeError raised INSIDE a real `answer` is that module's failure, not a missing keyword."""
    import inspect

    assert pc._accepts_intake(_Declares()) and pc._accepts_intake(_Kwargs())
    assert not pc._accepts_intake(_Legacy())

    def _unreadable(*a, **k):
        raise ValueError("no signature found")

    monkeypatch.setattr(inspect, "signature", _unreadable)
    assert pc._accepts_intake(_Legacy()), (
        "a callable with no readable signature is treated as the shipped module, which takes it")
