"""#156, proven by breaking it — the product owner corrects a card the product role opened.

#150 decided that a card the product role opened is the product owner's: the board refuses to edit,
close or reopen it. A requirement card already had a way to change (the requirement, then
`align_card`). A card opened from a request or a defect had none, so one written down wrong could
only be closed and asked for again, losing its number and its thread.

FOUR CLAIMS:

  1. **Only the product owner's own kinds of card, and only before pickup.** A request or a defect
     card is corrected; a requirement card changes through its requirement, a board card through
     the board, and a card in a column that means work has started, or in one nobody mapped, is
     left alone.
  2. **The card keeps what it said, and loses what was derived from it.** The old text goes into a
     comment; the criteria `refine` wrote from it are removed, and the reply offers new ones. A
     correction that changes nothing writes nothing.
  3. **Two writes, two outcomes.** A note that failed never undoes the correction that landed, a
     body the forge refused changes nothing, and a title that failed after the text landed is said.
  4. **The conversation asks first, and a button means one correction.** Nothing is written before
     the confirmation; the colon is what makes it an instruction; two wordings are two buttons.

The guards are `tests/test_card_maintenance.py`, `tests/test_card_maintenance_channel.py` and
`tests/test_the_product_role_lives_outside_slack.py`.
"""

TEST = "tests/test_card_maintenance.py"
CHANNEL_TESTS = "tests/test_card_maintenance_channel.py"
OUTSIDE_SLACK = "tests/test_the_product_role_lives_outside_slack.py"

MODULE = "openfactory/product/module.py"
CONFIRM = "openfactory/product/confirm.py"
CHANNEL = "openfactory/product/channel.py"
ENGINE = "openfactory/product/engine.py"
INTENTS = "openfactory/product/intents.py"
STAGING = "openfactory/product/staging.py"
VOICE = "openfactory/product/voice.py"
CATALOG = "openfactory/actions/catalog.py"

MUTATIONS = [
    # ── 1. whose card, and when ────────────────────────────────────────────────────────────────
    ("THE DECISION ITSELF: a requirement card, or one written on the board, is rewritten by the "
     "product role", MODULE,
     "        if kind not in _WHAT_WAS_ASKED:\n",
     "        if False:\n"),

    ("a card the factory has taken up is corrected under the agent working from it", MODULE,
     "            if not key or has_started(key):\n",
     "            if False:\n"),

    ("a column nobody mapped is read as not started", MODULE,
     "            if not key or has_started(key):\n",
     "            if key and has_started(key):\n"),

    ("the gate is skipped, so anybody corrects somebody else's request", MODULE,
     "        if not may_act(self.project, actor, via=self._via):\n"
     "            return WriteResult(ok=False, detail=unauthorized_message(self.project))\n\n"
     "        tickets, error = self._read_board()\n"
     "        if error:\n"
     '            return _could_not(_BOARD_UNREADABLE, act=f"correct #{number}", cause=error)',
     "        if False:\n"
     "            return WriteResult(ok=False, detail=unauthorized_message(self.project))\n\n"
     "        tickets, error = self._read_board()\n"
     "        if error:\n"
     '            return _could_not(_BOARD_UNREADABLE, act=f"correct #{number}", cause=error)'),

    # ── 2. what the card keeps and loses ───────────────────────────────────────────────────────
    ("the criteria written from the old text stay, describing a request that no longer exists",
     MODULE,
     "            after = _without_section(after, section)\n",
     "            after = after\n"),

    ("the card loses what it said before", MODULE,
     '                kind=kind, actor=f"<@{actor}>", old_text=old_text, '
     'old_title=card.title or "",',
     '                kind=kind, actor=f"<@{actor}>", old_text="", '
     'old_title=card.title or "",'),

    ("a correction that says what the card already says rewrites it anyway", MODULE,
     "        if not text_changed and not title_changed:\n",
     "        if False:\n"),

    ("the reply never learns the criteria went, so nobody is offered new ones", CONFIRM,
     '    measured = bool(_A_MEASURE.fullmatch((getattr(result, "detail", "") or "").strip()))',
     "    measured = False",
     CHANNEL_TESTS),

    # ── 3. two writes, two outcomes ────────────────────────────────────────────────────────────
    ("a note that failed is reported as a failed correction, though the card was corrected",
     MODULE,
     '        if residue:\n'
     '            return WriteResult(ok=True, ref=f"#{number}", detail=residue)',
     '        if residue:\n'
     '            return WriteResult(ok=False, ref=f"#{number}", detail=residue)'),

    ("a body the forge refused goes on to rename the card and tell it about a correction", MODULE,
     '                return _could_not(failed, act=f"correct #{number}", cause=exc, '
     'ref=f"#{number}")',
     "                pass"),

    ("a title that failed after the text landed is claimed by the note anyway", MODULE,
     "                title_changed = False\n",
     "                pass\n"),

    ("a tracker that cannot rename has the text corrected under a title it could not change",
     MODULE,
     "        if title and rename is None:\n",
     "        if False:\n"),

    # ── 4. the conversation ────────────────────────────────────────────────────────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("the confirmation stages no text, so the yes writes an empty correction", ENGINE,
     '        body = remember(thread, {"kind": "correct", "number": number, "text": text,',
     '        body = remember(thread, {"kind": "correct", "number": number, "text": "",',
     CHANNEL_TESTS),

    ("the colon is optional, so a sentence that only mentions correcting a card stages a write",
     INTENTS,
     '        + r"\\s*:\\s*(?P<text>\\S.{2,1999})$",',
     '        + r"\\s*:?\\s*(?P<text>\\S.{2,1999})$",',
     CHANNEL_TESTS),

    ("two corrections of one card to different words share a button", STAGING,
     '                         ("texto", entry.get("body", "") or entry.get("restated", "")\n'
     '                          or entry.get("text", "")),',
     '                         ("texto", entry.get("body", "") or entry.get("restated", "")),',
     CHANNEL_TESTS),

    ("two renames of one card to different titles share a button", STAGING,
     '                         ("novo título", entry.get("new_title", "") or ""),\n',
     "",
     CHANNEL_TESTS),

    ("a correction claimed in the reply is invisible to the false-claim detector", VOICE,
     '    r"corrigido|corrigida|corrigi|corrigimos|"\n',
     "",
     CHANNEL_TESTS),

    ("the row corrects a card with nobody saying yes", CATALOG,
     "    if not _said_yes(yes):\n"
     '        return refused(INVALID, f"nothing was corrected:',
     "    if False:\n"
     '        return refused(INVALID, f"nothing was corrected:',
     OUTSIDE_SLACK),
]
