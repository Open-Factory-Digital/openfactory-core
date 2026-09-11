"""The board does not move under the person reading it — proven by breaking it.

Reported by using it (2026-09-11): *"I scroll the screen to look at everything in Done and,
without me touching it, it goes back to the start."* `paintBoard` replaced the view's whole
`innerHTML` on every `poll_seconds` tick — 3 seconds on the local board — so every column list was
destroyed, rebuilt, and scrolled back to the top.

FOUR CLAIMS:

  1. **A tick that changed nothing paints nothing**, judged on the whole payload rather than on a
     list of fields somebody has to keep in step.
  2. **A tick that changed something still paints** — a board that stopped repainting would lie,
     which is worse than one that fidgets.
  3. **A repaint that has to happen keeps the reader's place**: each column's scroll, the strip's
     horizontal scroll, and the focused card.
  4. **Nothing repaints while a card is in somebody's hand**, and the drop that ends the drag is
     not swallowed by that rule.

The guard under test is `tests/test_the_board_keeps_your_place.py`.
"""

TEST = "tests/test_the_board_keeps_your_place.py"

PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── 1. the tick that should do nothing ─────────────────────────────────────────────────────
    ("every tick repaints again, and the board moves under whoever is reading it", PANEL,
     "  if(_bd.dragging || (_bd.sig !== null && sig === _bd.sig)){",
     "  if(false){", TEST),

    ("the signature stops covering the payload, so a change nobody listed goes unpainted", PANEL,
     '  const sig = d === null ? "null" : JSON.stringify(d);',
     '  const sig = d === null ? "null" : JSON.stringify((d.cards||[]).map(c=>c.ref));', TEST),

    ("the first tick is skipped, so the board never appears at all", PANEL,
     "  if(_bd.dragging || (_bd.sig !== null && sig === _bd.sig)){",
     "  if(_bd.dragging || sig === _bd.sig || true){", TEST),

    # ── 3. the reader's place ──────────────────────────────────────────────────────────────────
    ("the place is read and never put back", PANEL,
     "  _breplace(where);\n  _bwire();", "  _bwire();", TEST),

    ("each column's scroll is dropped, which is the half the report was about", PANEL,
     "    if(was) l.scrollTop = was;", "    if(false) l.scrollTop = was;", TEST),

    ("the strip of columns scrolls back to the first one", PANEL,
     "  if(cols && where.x) cols.scrollLeft = where.x;", "  if(false) cols.scrollLeft = where.x;",
     TEST),

    ("the keyboard's place is lost, so a card reached by tabbing is let go", PANEL,
     "    if(card) card.focus({preventScroll:true});", "    if(false) card.focus();", TEST),

    ("the place is taken after the repaint, when there is nothing left to read it from", PANEL,
     "  const where = _bplace();\n  el.innerHTML = head + `<div class=\"cols\">`",
     "  el.innerHTML = head + `<div class=\"cols\">`", TEST),

    # ── 4. a card in somebody's hand ───────────────────────────────────────────────────────────
    ("a tick rebuilds the DOM mid-drag and drops the card being dragged", PANEL,
     "      _bd.dragging = true; });", "      _bd.dragging = false; });", TEST),

    ("the drop clears no flag, so the move it just made is not painted", PANEL,
     "      _bd.dragging = false;\n      boardMove(e.dataTransfer.getData(\"text/plain\"), "
     "list.dataset.col);",
     "      boardMove(e.dataTransfer.getData(\"text/plain\"), list.dataset.col);", TEST),
]
