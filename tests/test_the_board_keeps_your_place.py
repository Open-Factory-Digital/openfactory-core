"""The board does not move under the person reading it (reported 2026-09-11, by using it).

*"I scroll the screen to look at everything in Done and, without me touching it, it goes back to
the start."* `paintBoard` replaced the whole view's `innerHTML` on every `poll_seconds` tick — 3
seconds on the local board — so every column list was destroyed and rebuilt and each one's
`scrollTop` went back to 0. A page that repaints while you are reading it is a page you cannot
read, and the cheapest fix is not to repaint: the board's payload carries no clock, so a
byte-identical answer means nothing moved.

WHAT IS PROVEN HERE, by RUNNING the page's own function under node rather than reading it:

  · a tick whose payload is identical paints nothing at all;
  · a tick that really moved a card does paint;
  · the first tick always paints, and so does the one after a failed read;
  · a repaint that has to happen keeps the reader's place — each column's scroll, the strip's
    horizontal scroll, and the focused card;
  · nothing repaints while a card is in somebody's hand, and the drop that ends the drag is not
    swallowed by that rule.
"""

from __future__ import annotations

import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from openfactory.api import app as api

PANEL = (Path(inspect.getfile(api)).parent / "panel.html").read_text(encoding="utf-8")
CODE = "\n".join(ln for ln in PANEL.splitlines() if not ln.lstrip().startswith("//"))

#: One board, the shape `/api/board/{project}` really answers (see `app.board_view`).
BOARD = {"project": "myapp", "columns": ["TO-DO", "In progress", "Done"],
         "cards": [{"ref": "1", "column": "Done", "title": "Close and reopen a ticket",
                    "labels": [], "updated_at": "2026-09-11"}],
         "poll_seconds": 3, "board": True, "card": None, "pr": None}


def _function(name: str) -> str:
    """One function's source, read out of the page — with its comments, which are the argument."""
    start = CODE.index(f"function {name}(")
    # `async` IS PART OF THE FUNCTION, and slicing from the word `function` drops it — node then
    # refuses the body with *await is only valid in async functions*, which is a fact about this
    # helper and not about the page.
    if CODE[max(0, start - 6):start] == "async ":
        start -= 6
    body = CODE[start:]
    return body[:body.index("\n}\n") + 3]


def _run(script: str) -> dict:
    """Run a fragment of the page's own JavaScript with a stub DOM and report what it did."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the source-level guard below still runs")
    got = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr[:800]
    return json.loads(got.stdout)


def _ticks(*payloads, dragging: bool = False) -> dict:
    """Feed `refreshBoard` a sequence of API answers and count the repaints.

    EXECUTED, NOT READ. This file's whole subject is what a tick DOES to a rendered page, and the
    defect it is about was invisible to every source-level assertion anybody could have written:
    `paintBoard` was called, correctly, on data that had not changed."""
    fetches = "".join(f"_queue.push({json.dumps(p)});" for p in payloads)
    script = f"""
const _queue = [];
{fetches}
let painted = 0, cards = 0, prs = 0;
const _bd = {{project:"myapp", data:null, card:null, pr:null, timer:1, sig:null,
              dragging:{str(dragging).lower()}}};
globalThis._bd = _bd;
function $(sel){{ return {{classList:{{contains:()=>true}}}}; }}
async function api(){{ const next = _queue.shift(); if(next === "boom") throw new Error("no");
                       return next; }}
function paintBoard(){{ painted++; }}
function paintCard(){{ cards++; }}
function paintPR(){{ prs++; }}
function _bwatch(){{}}
{_function("refreshBoard")}
(async () => {{
  for(let i = 0; i < {len(payloads)}; i++) await refreshBoard();
  console.log(JSON.stringify({{painted, cards, prs, sig: _bd.sig !== null}}));
}})();
"""
    return _run(script)


# ── the tick that should do nothing ─────────────────────────────────────────────────────────────

def test_a_tick_that_changed_NOTHING_paints_nothing():
    """THE DEFECT, in one assertion. Three identical answers used to be three full repaints, and
    the third one is the moment somebody loses their place in the Done column."""
    out = _ticks(BOARD, BOARD, BOARD)

    assert out["painted"] == 1, (
        f"{out['painted']} repaints for three identical answers — the board moves under the "
        f"person reading it every {BOARD['poll_seconds']} seconds")


def test_a_tick_that_MOVED_a_card_paints():
    """The positive twin, and the one that matters more: a board that stopped repainting would be
    a board that lies, which is worse than one that fidgets."""
    moved = json.loads(json.dumps(BOARD))
    moved["cards"][0]["column"] = "In progress"

    assert _ticks(BOARD, moved)["painted"] == 2, "a card moved and the screen did not say so"


def test_every_field_of_the_payload_counts_not_a_list_somebody_maintains():
    """A signature built from a hand-written list of fields is a signature that stops noticing
    whatever is added next. A new column, a new label and a new title each have to repaint."""
    for change in ({"columns": ["TO-DO", "Doing", "Done"]},
                   {"poll_seconds": 10},
                   {"cards": [{**BOARD["cards"][0], "labels": ["urgent"]}]},
                   {"cards": [{**BOARD["cards"][0], "title": "Renamed by somebody"}]}):
        after = {**BOARD, **change}
        assert _ticks(BOARD, after)["painted"] == 2, change


def test_the_FIRST_tick_always_paints():
    assert _ticks(BOARD)["painted"] == 1


def test_a_read_that_FAILED_paints_its_refusal_once():
    """`null` is the page's "could not be read" panel. It has to arrive — and then stop flickering
    while the board stays unreachable."""
    assert _ticks("boom", "boom")["painted"] == 1


def test_a_board_that_comes_BACK_paints_again():
    assert _ticks("boom", BOARD)["painted"] == 2


def test_nothing_repaints_while_a_card_is_in_somebody_s_hand():
    """Rebuilding the DOM mid-drag drops the card being dragged."""
    assert _ticks(BOARD, dragging=True)["painted"] == 0


def test_the_drag_that_STARTS_is_what_sets_the_flag():
    """The other end of the same rule, and the one a stub cannot show: the test above hands
    `refreshBoard` a state that says a drag is in progress, so it never runs the handler that puts
    it there. A mutation proved exactly that — `_bd.dragging = true` cut to `false` and the suite
    stayed green (2026-09-11)."""
    wire = _function("_bwire")
    start = wire[wire.index('addEventListener("dragstart"'):]
    start = start[:start.index('addEventListener("dragend"')]

    assert "_bd.dragging = true" in start, (
        "a drag starting sets nothing, so the next tick rebuilds the DOM under the card being "
        "dragged and the drag is lost")
    ends = wire[wire.index('addEventListener("dragend"'):]
    assert "_bd.dragging = false" in ends[:ends.index("\n")+200], (
        "an abandoned drag never clears the flag, and the board stops refreshing for good")


def test_the_drop_that_ENDS_a_drag_is_not_swallowed_by_that_rule():
    """`drop` and `dragend` land in that order and `boardMove` refreshes in between, so a flag
    cleared only on `dragend` would hide the move until the next tick."""
    drop = _function("_bwire")
    drop = drop[drop.index('addEventListener("drop"'):]

    assert "_bd.dragging = false" in drop[:drop.index("boardMove(")], (
        "the drop clears no flag, so the repaint that shows the card in its new column is skipped")


# ── and when it does have to paint, the reader keeps their place ────────────────────────────────

def test_a_repaint_restores_each_column_scroll_the_strip_and_the_focus():
    """One card moving must not throw everybody's eye back to the top of a column they were half
    way down. Executed against a stub DOM: `_bplace` reads, `_breplace` writes."""
    script = f"""
const lists = [{{dataset:{{col:"Done"}}, scrollTop: 420}},
               {{dataset:{{col:"TO-DO"}}, scrollTop: 0}}];
const cols = {{scrollLeft: 300}};
let focused = null;
const view = {{
  querySelector: sel => sel === ".cols" ? cols
      : {{focus: () => {{ focused = sel; }}}},
  querySelectorAll: () => lists,
}};
function $(){{ return view; }}
globalThis.document = {{activeElement: {{classList:{{contains:()=>true}}, dataset:{{ref:"7"}}}}}};
globalThis.CSS = {{escape: s => s}};
const _bd = {{}};
{_function("_bplace")}
{_function("_breplace")}
const where = _bplace();
lists.forEach(l => l.scrollTop = 0); cols.scrollLeft = 0;   // the repaint
_breplace(where);
console.log(JSON.stringify({{done: lists[0].scrollTop, todo: lists[1].scrollTop,
                             x: cols.scrollLeft, focused, where}}));
"""
    out = _run(script)

    assert out["where"]["focus"] == "7", "the focused card was not noticed before the repaint"
    assert out["done"] == 420, "the column somebody was reading went back to the top"
    assert out["x"] == 300, "the strip of columns scrolled back to the first one"
    assert out["focused"] == '.k[data-ref="7"]', "the keyboard's place was lost"


def test_the_place_is_taken_BEFORE_the_innerHTML_and_put_back_after():
    """Order is the whole behaviour here, and it is the one thing a stub cannot show."""
    paint = _function("paintBoard")
    # THE COLUMNS' OWN LINE, not the first `innerHTML` in the function: the refusal branch above
    # it writes one too and returns, and a guard that matched that one compared the wrong pair.
    took, wrote, put = (paint.index("_bplace()"),
                        paint.index('el.innerHTML = head + `<div class="cols">` + (d.columns'),
                        paint.index("_breplace(where)"))

    assert took < wrote < put, "the reader's place is read or restored at the wrong moment"


def test_the_signature_is_not_a_field_list_in_the_page():
    """Read the source for this one: the property is what the signature is MADE of, and a page
    that hashed five named fields would pass every behavioural test above while going blind to
    the sixth."""
    refresh = _function("refreshBoard")

    assert re.search(r"JSON\.stringify\(d\)", refresh), (
        "the signature is built from something narrower than the payload the page renders")
