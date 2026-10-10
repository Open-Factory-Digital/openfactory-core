"""A front that builds on one the breakdown did not file is held, and said with the front it waits on
(#576).

The run (#564's): requirement 66 broke into three fronts. The review refused the first, the
per-version storage, so its card was not filed. The second was filed anyway, as #1000010, its first
criterion "given the per-version rows introduced by the persistence change for REQ-0066"; the
pre-flight parked it a move later: "REQ-0066 per-version persistence doesn't exist yet". The
decomposition had no way to say what a front builds on, and filing none to ask.

Now the decomposition says it (`IssueDraft.builds_on`, by position in its own list), and
`file_issues` files a front after the ones it builds on — and not at all when one of them was not
filed, saying both in one sentence. These run the real `file_issues` and `_file_one`, with a
tracker, a review and a decomposition of the test's own.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from openfactory.product import confirm
from openfactory.product.role import IssueDraft

STORAGE, HISTORY, EXPORT = ("Guardar cada versão entregue", "Mostrar o histórico de versões",
                            "Exportar a lista de clientes")


class _Tracker:
    """Numbers each card it creates, in the order it was asked to."""

    def __init__(self):
        self.created: list[str] = []

    def find_ticket(self, *, title: str):
        return None

    def create_ticket(self, *, title: str, body: str, **_kw) -> str:
        self.created.append(title)
        return f"#{1000000 + len(self.created)}"

    def ticket_url(self, ref: str) -> str:
        return f"https://forge/a/b/issues/{ref.lstrip('#')}"

    def get_ticket(self, ref: str):
        return SimpleNamespace(title="", state="open", raw="")


def _front(title: str, *builds_on: int) -> IssueDraft:
    return IssueDraft(title=title, objective="o", acceptance_criteria=["um critério observável"],
                      cites=66, builds_on=list(builds_on))


def _breakdown(tmp_path, monkeypatch, fronts, *, refused=()):
    """`file_issues` over `fronts`, the review refusing the titles in `refused`."""
    from openfactory.product import module as module_
    from tests.test_the_product_owner_opens_a_card_as_described import _module

    tracker = _Tracker()
    mod = _module(tmp_path, tracker)
    requirement = SimpleNamespace(number=66, title="Versões entregues", body="b", asked_by="",
                                  path="0066.md", is_live=True, is_promise=True,
                                  came_from_the_code=False)
    drafts = SimpleNamespace(ok=True, issues=list(fronts))
    monkeypatch.setattr(mod, "_role", lambda **k: SimpleNamespace(issues_for=lambda **kw: drafts))
    monkeypatch.setattr(mod, "_workspace", lambda: (None, None))
    monkeypatch.setattr(mod, "_read_board", lambda **k: ([], ""))
    monkeypatch.setattr(mod, "context", lambda **k: SimpleNamespace(
        available=True, docs_path=str(tmp_path), link=SimpleNamespace(docs_repo="a/docs"),
        corpus=SimpleNamespace(by_number=lambda n: requirement), docs_commit="",
        requirements_dir="requirements"))
    monkeypatch.setattr(mod, "_open_delivery", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_vetter", lambda req, tr: (
        lambda draft: (None, "o critério cita um código que o requisito não nomeia")
        if draft.title in refused else (draft, "")))
    monkeypatch.setattr(module_, "may_act", lambda *a, **k: True)

    results = mod.file_issues(requirement, actor="<@U1>", tracker=tracker, board=None)
    return results, tracker, confirm._breakdown_reply(results, 66, "", "pt-BR")


def test_TODAYS_RUN_a_front_on_a_refused_one_is_held_and_both_are_named(tmp_path, monkeypatch):
    results, tracker, reply = _breakdown(
        tmp_path, monkeypatch, [_front(STORAGE), _front(HISTORY, 1)], refused={STORAGE})

    assert tracker.created == [], "a front was filed on a foundation nobody filed"
    assert [r.ok for r in results] == [False, False]
    assert f"“{STORAGE}” não foi aberta, então segurei “{HISTORY}”" in results[1].detail
    assert STORAGE in reply and HISTORY in reply, reply


def test_a_front_on_one_that_landed_is_filed_as_today(tmp_path, monkeypatch):
    results, tracker, _reply = _breakdown(
        tmp_path, monkeypatch, [_front(STORAGE), _front(HISTORY, 1)])

    assert tracker.created == [STORAGE, HISTORY]
    assert [r.ok for r in results] == [True, True]


def test_the_others_still_go_ahead_and_the_reply_names_every_front_not_opened(tmp_path,
                                                                             monkeypatch):
    """The reply said the FIRST failure alone; the held front went unnamed behind it."""
    results, tracker, reply = _breakdown(
        tmp_path, monkeypatch, [_front(STORAGE), _front(HISTORY, 1), _front(EXPORT)],
        refused={STORAGE})

    assert tracker.created == [EXPORT]
    assert "2 não deu para registrar" in reply
    assert f"“{STORAGE}” não passou na revisão automática" in reply
    assert f"segurei “{HISTORY}”" in reply


def test_a_front_listed_before_the_one_it_builds_on_is_filed_after_it(tmp_path, monkeypatch):
    """A retry files both, in order; the results keep the decomposition's order."""
    results, tracker, _reply = _breakdown(
        tmp_path, monkeypatch, [_front(HISTORY, 2), _front(STORAGE)])

    assert tracker.created == [STORAGE, HISTORY]
    assert [r.ref for r in results] == ["#1000002", "#1000001"]


def test_a_hold_carries_down_the_chain_naming_the_front_each_one_waits_on(tmp_path, monkeypatch):
    results, tracker, _reply = _breakdown(
        tmp_path, monkeypatch, [_front(STORAGE), _front(HISTORY, 1), _front(EXPORT, 2)],
        refused={STORAGE})

    assert tracker.created == []
    assert f"“{HISTORY}” não foi aberta, então segurei “{EXPORT}”" in results[2].detail


def test_fronts_that_build_on_one_another_in_a_circle_are_filed_in_their_own_order(
        tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="openfactory.product"):
        results, tracker, _reply = _breakdown(
            tmp_path, monkeypatch, [_front(STORAGE, 2), _front(HISTORY, 1)])

    assert tracker.created == [STORAGE, HISTORY]
    assert "in a circle" in caplog.text


def test_a_position_outside_its_own_breakdown_is_read_as_no_dependency_and_logged(caplog):
    """The decomposition's own answer, read: a front builds only on another of the SAME list."""
    import json

    from tests.test_product_role import _call, _req, _role

    answer = json.dumps({"issues": [
        {"title": STORAGE, "objective": "o", "acceptance_criteria": ["c"], "builds_on": [1, 7]},
        {"title": HISTORY, "objective": "o", "acceptance_criteria": ["c"],
         "builds_on": ["1", "#1", None, "x"]},
    ]})
    role, harness = _role(answer=answer)

    with caplog.at_level(logging.INFO, logger="openfactory.product.role"):
        res = _call(role, "issues_for", requirement=_req(66), sources=[])

    assert [i.builds_on for i in res.issues] == [[], [1]]
    assert "builds on [1, 7]; read as []" in caplog.text
    assert '"builds_on": [int]' in harness.prompts[0], "the decomposition is never asked"


@pytest.mark.parametrize("language", ["pt-BR", "en"])
def test_the_held_sentence_names_both_fronts_in_each_language(language):
    from openfactory.product.voice import breakdown_said

    said = breakdown_said("held", title=HISTORY, base=STORAGE, language=language)

    assert STORAGE in said and HISTORY in said and "{" not in said
