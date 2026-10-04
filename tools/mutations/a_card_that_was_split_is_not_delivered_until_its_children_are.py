"""A card the pre-flight split replaced with children is closed as NOT delivered, and counts as
delivered again exactly when every card split from it is (2026-09-19)."""

TEST = "tests/test_a_card_that_was_split_is_not_delivered_until_its_children_are.py"
LANGUAGE = "tests/test_nothing_speaks_before_it_asks_the_language.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
TRIAGE = "openfactory/product/triage.py"
REFS = "openfactory/contracts/refs.py"
AZURE = "openfactory/adapters/tracker/azure_devops.py"
REGISTRY = "openfactory/adapters/tracker/registry.py"
IMPEDIMENT = "openfactory/ops/impediment.py"
#: the card's door's ports — where a split's close and the impediment's reach the row since #414
PORTS = "openfactory/lifecycle/ports.py"
VOICE = "openfactory/techlead/voice.py"

MUTATIONS = [
    # ── the word the split closes with ──────────────────────────────────────────────────────────
    # re-pinned 2026-10-04: the split's close goes through the card's door (#414), and the word
    # it closes with is a fact of the transition
    ("THE DEFECT ITSELF: the parent is closed as delivered, so a card that shipped nothing counts "
     "as work the client got", ACTIVITIES,
     '        facts={"delivered": False, "split_into": links,',
     '        facts={"delivered": True, "split_into": links,'),

    # re-pinned 2026-10-04: the close reaches the row through the door's port since #414 — the
    # seam this row walks around is that port's
    ("the split closes on the row directly, walking around the port's seam", PORTS,
     "        close_ticket(self.tracker, card, note, delivered=delivered)\n",
     "        self.tracker.close_ticket(card, note)\n"),

    # ── what the sweep counts ───────────────────────────────────────────────────────────────────
    ("the delivery sweep asks the CARD, not the board, so a split parent is never followed",
     ACTIVITIES,
     "    return delivered_numbers(list(module._board_tickets or []))",
     "    return {t.number for t in (module._board_tickets or []) if t.delivered}"),

    ("a card that was split counts the moment it is closed, whatever its children are doing",
     TRIAGE,
     "    got = {t.number for t in tickets if t.delivered and t.number not in split}",
     "    got = {t.number for t in tickets if t.delivered}"),

    ("SOME of the children, not all: a requirement is announced on its first delivery", TRIAGE,
     "and all(p.delivered for p in parts):",
     "and any(p.delivered for p in parts):"),

    ("a split that never finished delivers its parent anyway", TRIAGE,
     "        if card is not None and card.state != \"open\" and all(",
     "        if card is not None and all("),

    ("a child's title no longer says which card it was split from", REFS,
     "    return canonical_ref(tail.partition(\"]\")[0]) if found else \"\"",
     "    return \"\""),

    ("the ref is read past the tag's own bracket, so it matches no card", REFS,
     "canonical_ref(tail.partition(\"]\")[0])",
     "canonical_ref(tail)"),

    ("the splitter writes a mark the sweep does not read — two spellings again", ACTIVITIES,
     "_SPLIT_CHILD_MARK = SPLIT_CHILD_MARK",
     "_SPLIT_CHILD_MARK = \"[auto-split of issue #\""),

    # ── what a person reads on the parent ───────────────────────────────────────────────────────
    # re-pinned 2026-10-04: the note is the close's fact through the card's door (#414)
    ("the note is written in English whatever the project speaks", ACTIVITIES,
     "\"split.parent.closed\", lang,",
     "\"split.parent.closed\", \"en\","),

    ("the note no longer says the card was SPLIT INTO the children", VOICE,
     "        \"en\": \"✂️ Split into {children} ({where}). This card was too large for one pass \"",
     "        \"en\": \"✂️ Closed ({where}). This card was too large for one pass \""),

    ("the note no longer says the card was not rejected, beside a vendor label reading "
     "'not planned'", VOICE,
     "              \"because nothing ships under this number — it was not rejected.\",",
     "              \"because nothing ships under this number.\","),

    ("the Portuguese row is the English one", VOICE,
     "        \"pt-BR\": \"✂️ Dividido em {children} ({where}). Este cartão era grande demais para "
     "uma \"",
     "        \"pt-BR\": \"✂️ Split into {children} ({where}). This card was too large for one \""),

    ("the note does not say where the children went", ACTIVITIES,
     "        where = tl_voice.say(tl_voice.NARRATION, \"split.parent.in-backlog\", lang)",
     "        where = \"\""),

    # ── the Azure Boards row's own sentence ─────────────────────────────────────────────────────
    ("the row composes its own English sentence again", AZURE,
     "            said = closed_not_delivered_note(status=f\"**{target}**\", "
     "language=self.language)\n"
     "            note = (note + \"\\n\\n\" if note else \"\") + f\"_{said}_\"",
     "            note = (note + \"\\n\\n\" if note else \"\") + (\n"
     "                f\"_Closed as NOT delivered. This process has no Removed state, so the \"\n"
     "                f\"card shows **{target}** — the work was not done._\")"),

    ("…and the language guard is what catches it now, through the variable that carries it: this "
     "is the shape the row had, and the shape it was invisible in", AZURE,
     "            said = closed_not_delivered_note(status=f\"**{target}**\", "
     "language=self.language)\n"
     "            note = (note + \"\\n\\n\" if note else \"\") + f\"_{said}_\"",
     "            note = (note + \"\\n\\n\" if note else \"\") + (\n"
     "                f\"_Closed as NOT delivered. This process has no Removed state, so the \"\n"
     "                f\"card shows **{target}** — the work was not done._\")",
     LANGUAGE),

    ("the row says its one sentence in English whatever the project speaks", AZURE,
     "status=f\"**{target}**\", language=self.language)",
     "status=f\"**{target}**\", language=None)"),

    ("the registry row never tells the Azure row which language the project speaks", REGISTRY,
     "        options=options,\n        # for the one note the row writes in its own name — see "
     "`AzureBoardsTracker.language`\n        language=getattr(project, \"language\", None),",
     "        options=options,"),

    # ── the other close that chose no word ──────────────────────────────────────────────────────
    # re-pinned 2026-10-04: the impediment's close goes through the card's door (#414)
    ("the impediment's close walks around the seam", IMPEDIMENT,
     "        moved = transition(_door_view(project), str(existing), CardEvent.CLOSED, "
     "by=\"the factory\",\n",
     "        trk.close_ticket(str(existing), note)\n"
     "        moved = transition(_door_view(project), str(existing), CardEvent.CLOSED, "
     "by=\"the factory\",\n"),

    ("a capability that works again is recorded as work nobody did", IMPEDIMENT,
     "facts={\"delivered\": True, \"note\": note}",
     "facts={\"delivered\": False, \"note\": note}"),

    # ── the guard that would have seen all of this ──────────────────────────────────────────────
    ("the language walk stops following a name back to what the function put in it", LANGUAGE,
     "            carried = _assigned(functions, arg.id) if isinstance(arg, ast.Name) else [arg]",
     "            carried = [arg]",
     LANGUAGE),

    ("a close's reason is not counted as words a person reads", LANGUAGE,
     "SURFACES = {\"notify\", \"_notify\", \"_say_on_ticket\", \"_coord_say\", \"comment\", "
     "\"close_ticket\"}",
     "SURFACES = {\"notify\", \"_notify\", \"_say_on_ticket\", \"_coord_say\", \"comment\"}",
     LANGUAGE),
]
