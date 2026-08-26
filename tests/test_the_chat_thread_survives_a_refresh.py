"""Both halves of a conversation are written down, in one order (#123, pilot 2026-08-16).

    "outra coisa que eu percebi é que ao dar F5 este diálogo some."

Everything the FACTORY said already landed in the panel's message store — which is why the
tech-lead's rounds and the merge narration survived his refresh. What a PERSON said lived in a
JavaScript array in the tab that produced it, so his question, the answer, and any staged
`[[SUGGEST]]` button vanished with the page. A wait ending in nothing is the one shape this
platform is not allowed to have, and a suggestion the tech-lead had just asked somebody to approve
is exactly that.

The same split produced the second complaint in the same screenshot — *"achei estranha a ordem"*.
The panel drew `[...everything the store knows, ...whatever this tab remembers]`, so a narration
that arrived AFTER a typed question was drawn above it. Two feeds, two clocks, one of them absent.

`told` closes both: one append-only store, one clock, the same retention as everything else the
factory has said, and no new infrastructure — which is what keeps §12's promise that a free
deployment loses nothing without a cloud.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openfactory.memory import messages
from openfactory.observability.metrics import InMemoryMetricsSink

PANEL = (Path(__file__).resolve().parents[1] / "openfactory" / "api" / "panel.html").read_text()


def _rows(sink) -> list[dict]:
    return [{"kind": r.kind, "pk": r.project, "ts": r.ts, "extra": r.extra} for r in sink.records]


def _paint_chat() -> str:
    """`paintChat`'s BODY with its comment lines removed.

    THE COMMENTS DESCRIBE THE DEFECT. The block below explains that the old code was
    `[...server, ..._chatLocal]`, and the first version of the guard read that sentence and
    reported the bug as still present — the second time a comment explaining a fix has failed the
    guard for the fix (see `test_no_background_updater_paints_over_a_page_it_does_not_own`)."""
    block = PANEL[PANEL.index("function paintChat"):]
    block = block[:block.index("\n}")]
    return "\n".join(ln for ln in block.splitlines() if not ln.strip().startswith("//"))


# ── 1. the store can hold a person's own words ──────────────────────────────────────────────────

def test_a_person_speaking_is_its_own_kind():
    """Not `said` (the factory), not `answered` (which closes a specific `ask` by token). Somebody
    starting a conversation is a third thing, and the panel renders it on the other side."""
    assert messages.TOLD not in (messages.SAID, messages.ANSWERED, messages.ASKED)

    sink = InMemoryMetricsSink()
    assert messages.told("p", "pode fazer o merge", by="operator-1", channel="p", sink=sink)

    # THE ROUND TRIP, not just the write. `_message` gates the read on a set of kinds, and adding
    # `TOLD` to the writers without adding it there wrote every operator turn straight into a hole
    # — found here, by reading back what had just been written.
    back = messages.read("p", scan=lambda: _rows(sink))
    assert back and back[0].kind == messages.TOLD, (
        f"a person's turn was written and did not survive the read: {back}")
    assert back[0].by == "operator-1" and back[0].ts and back[0].text == "pode fazer o merge"


def test_a_told_row_carries_a_timestamp_from_the_SAME_clock_as_the_rest():
    """The ordering half. A turn with no `ts` cannot be merged into the thread by time, which is
    what forced the browser to append its half at the end."""
    rows: list = []
    sink = lambda project, recs: rows.extend(recs) or len(recs)  # noqa: E731
    messages.say("p", "the factory speaks", sink=sink)
    messages.told("p", "and so does a person", sink=sink)
    stamps = [r.ts for r in rows]
    assert all(stamps) and stamps == sorted(stamps)


# ── 2. the tech-lead row writes both turns ──────────────────────────────────────────────────────

@pytest.fixture
def recorded(monkeypatch):
    """Capture what `_ask` files, without a store, an engine or an agent."""
    from openfactory.actions import catalog

    out: list[tuple[str, str]] = []
    monkeypatch.setattr(messages, "told",
                        lambda project, text, **kw: out.append(("told", text)) or True)
    monkeypatch.setattr(messages, "say",
                        lambda project, text, **kw: out.append(("said", text)) or True)
    return catalog, out


@pytest.mark.asyncio
async def test_a_routed_INSTRUCTION_is_written_down_too(recorded, monkeypatch):
    """It never reaches the worker, so nothing else would ever record it — and "I told it to merge
    and it said X" is precisely the turn somebody wants to find again."""
    catalog, out = recorded
    from openfactory.actions.base import Actor, done

    monkeypatch.setattr(catalog, "_project",
                        lambda name: (type("P", (), {"name": name})(), None))

    async def _routed(said, *, project, by):
        return done("#87: merging the PR now")

    monkeypatch.setattr(catalog, "_floor_say_as_an_intent", _routed)
    out.clear()
    await catalog._ask(project="podbeam", question="pode fazer o merge",
                       by=Actor(id="operator-1", admin=True))

    assert out == [("told", "pode fazer o merge"), ("said", "#87: merging the PR now")], (
        f"the instruction turn is missing from the thread: {out}")


@pytest.mark.asyncio
async def test_the_answer_is_never_lost_to_a_store_that_will_not_write(recorded, monkeypatch):
    """Losing the record of a question is a bad day; refusing to answer it because the record
    failed is a worse one."""
    catalog, out = recorded
    from openfactory.actions.base import Actor, done

    monkeypatch.setattr(catalog, "_project",
                        lambda name: (type("P", (), {"name": name})(), None))
    monkeypatch.setattr(messages, "told",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk is full")))

    async def _routed(said, *, project, by):
        return done("#87: merging the PR now")

    monkeypatch.setattr(catalog, "_floor_say_as_an_intent", _routed)
    outcome = await catalog._ask(project="podbeam", question="merge",
                                 by=Actor(id="operator-1", admin=True))
    assert outcome.ok, "a broken transcript swallowed the operator's merge"


# ── 3. the panel draws ONE thread ───────────────────────────────────────────────────────────────

def test_the_panel_merges_the_two_halves_by_TIME():
    """`[...server, ..._chatLocal]` is what drew a 12:00 narration above an 11:59 question."""
    block = _paint_chat()
    assert "[...server,..._chatLocal]" not in block.replace(" ", ""), (
        "the tab's half is still appended after everything the store knows, whatever the clock says")
    assert re.search(r"\.sort\(", block), "the thread is not ordered at all"


def test_the_panel_renders_a_persons_turn_on_their_own_side():
    """A `told` row read back from the store must not appear as the tech-lead talking to itself."""
    block = _paint_chat()
    assert '"told"' in block or "'told'" in block, "the panel drops the operator's own turns"
    assert 'kind=="told"?"me"' in block.replace(" ", ""), (
        "a person's own words are being rendered as the factory's")


def test_a_turn_the_store_echoes_back_is_not_shown_twice():
    """The tab keeps its optimistic copy until the store answers; without a de-duplication the
    next refresh shows every question twice."""
    block = _paint_chat()
    assert "echoed" in block, "nothing prevents the optimistic copy and the stored row both showing"


def test_the_api_hands_the_panel_the_operators_turns():
    """The endpoint filters by kind on the client side, so a row the API drops can never be drawn.
    Derived from the store's own vocabulary."""
    import inspect

    from openfactory.api import app

    src = inspect.getsource(app.channel_messages)
    assert "m.kind" in src and "for m in history" in src, (
        "the endpoint no longer forwards the store's rows verbatim")
    assert "told" in PANEL, "the panel never asks for a person's own turns"
