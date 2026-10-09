"""A breakdown's outcome says what did not land, on every surface it is told on (#564, the part
about the catalog's two doors).

An acceptance from the panel broke a requirement into three fronts; the vet refused the storage
front, the other two were filed, and the panel's answer was "Work filed: #1000010, #1000011" — the
refused front named nowhere but a log line. The conversation's reply (`_breakdown_reply`) says
"1 could not be registered: …" from the same rows; the catalog read the failed rows only when
nothing landed. Now both catalog doors render through the conversation's own function
(`confirm.breakdown_outcome`), plain, because emphasis is a surface's.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from openfactory.actions import catalog
from openfactory.product import confirm, voice
from tests.test_accepting_what_the_code_already_does_files_nothing import (  # noqa: F401
    ADMIN,
    AUTHORED,
    _module,
    _panel_actor,
    _through_the_catalog,
    origin,
)

LANDED = {"ok": True, "ref": "books#41", "detail": "", "url": "", "existed": False}


def _refused(kind: str) -> dict:
    said = voice.breakdown_said(kind, title="keep each delivered version",
                                why="the card cites code the requirement never names",
                                language="en")
    return {"ok": False, "ref": "", "url": "", "existed": False, "detail": said}


@pytest.fixture
def worker(monkeypatch):
    """The breakdown as the worker returns it: one front landed, one refused — set per test."""
    rows: list[dict] = []

    class _Engine:
        async def execute_workflow(self, name, inp, **_kw):
            return list(rows)

    async def _connected():
        return _Engine(), None

    monkeypatch.setattr(catalog, "_connected", _connected)
    return rows


@pytest.mark.parametrize("kind", ["not_vetted", "out_of_time"])
def test_the_acceptance_names_the_front_that_was_not_filed(origin, monkeypatch, worker,  # noqa: F811
                                                            kind):
    mod, _h, _t = _module(origin, monkeypatch)
    _through_the_catalog(mod, monkeypatch)
    worker[:] = [LANDED, _refused(kind)]

    out = asyncio.run(catalog._product_accept(project="books", number=str(AUTHORED),
                                              by=_panel_actor(), yes=True))

    assert out.ok, out.message
    assert "books#41" in out.message
    assert "1 could not be registered" in out.message, out.message
    assert "keep each delivered version" in out.message, "the front that was not filed is unnamed"


def test_the_break_down_row_names_the_front_that_was_not_filed(origin, monkeypatch,  # noqa: F811
                                                                worker):
    from openfactory import actions

    mod, _h, _t = _module(origin, monkeypatch)
    _through_the_catalog(mod, monkeypatch)
    assert mod.accept(AUTHORED, actor=ADMIN).ok
    worker[:] = [LANDED, _refused("not_vetted")]

    out = asyncio.run(actions.CATALOG["product_break_down"].run(
        project="books", number=str(AUTHORED), by=_panel_actor(), yes=True))

    assert out.ok, out.message
    assert "books#41" in out.message and "did not pass the automatic review" in out.message
    assert "**" not in out.message, "the conversation's emphasis reached the action layer"


def test_both_catalog_doors_and_the_conversation_render_through_one_function():
    """A GUARD, so a third door cannot grow a third rendering — the defect was two of them."""
    for door in (catalog._with_the_work_filed, catalog._product_break_down):
        source = inspect.getsource(door)
        assert "_breakdown_said(" in source and "Work filed:" not in source, door.__name__
    assert "breakdown_outcome(" in inspect.getsource(catalog._breakdown_said)
    assert "_breakdown_reply(" in inspect.getsource(confirm.breakdown_outcome)


def test_the_conversation_keeps_its_emphasis_and_the_catalog_has_none():
    from openfactory.product.authoring import WriteResult

    rows = [WriteResult(ok=True, ref="#40")]
    assert "virou **1** tarefa" in confirm._breakdown_reply(rows, 5, "", "pt-BR")
    assert "virou 1 tarefa" in confirm.breakdown_outcome(
        [{"ok": True, "ref": "#40"}], number=5,
        project=type("P", (), {"language": "pt-BR"})())
