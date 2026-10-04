"""#414 part C (ADR-0055 slice 3, its last writer), proven by breaking it — a requirement's promise
goes through each of its cards' doors as `promised`, and the list that may only shrink is empty.

MEASURED on the stack's head (#509, `9a76361`) before this part:

  - the breakdown opened a requirement's delivery loop beside every door
    (`followup.deliveries_to_open` → `loop_store.write`, from `module._open_delivery`): no card's
    record held it, and the hourly round had nothing to open again when the ledger did not take it;
  - a REUSED card — an open card the requirement verified on the board — joined the promise through
    no transition of its own, and an all-reused requirement went through no door at all;
  - the closed event set had no event for "a card joins a requirement's promise", so the guard's
    exemption list held one entry, and D9's "slice 3 ends with it empty" could not hold.

THE CLAIMS, one or more rows each:

  1. the promise goes through the door: opened beside it again, or the old writer named on the list
     again, or the ceiling raised, fails the guard;
  2. EVERY card of the breakdown is promised — the reused ones too — and each carries the whole
     promise, so the one it opens names every card, in the conversation it was asked in;
  3. ONE promise, once: the ledger keeps one per subject, and a retried breakdown is answered from
     each card's record;
  4. the door refuses to promise a card that is done or gone, and that refusal stops none of the
     other cards from opening the promise;
  5. a promise MOVES NOTHING: it writes nothing to the card, leaves its state as it was, reads no
     board — and the record's word on where a card is is its latest MOVE, so the sweep still
     places a filing a promise followed, an observed change is judged against the last move, and
     a card whose work stopped still says so once a requirement reused it.
"""

TEST = "tests/test_the_life_of_a_card.py"
TABLE_TEST = "tests/test_the_card_lifecycle_does_what_its_table_says.py"
GUARD_TEST = "tests/test_the_card_lifecycle_has_one_door.py"

TABLE = "openfactory/lifecycle/table.py"
CARD = "openfactory/lifecycle/card.py"
EXECUTOR = "openfactory/lifecycle/executor.py"
OBSERVED = "openfactory/lifecycle/observed.py"
LOOPS = "openfactory/lifecycle/loops.py"
MODULE = "openfactory/product/module.py"
LIST = "tests/card_writers_outside_the_door.py"

MUTATIONS = [
    # ── 1. the promise goes through the door ────────────────────────────────────────────────────
    ("a requirement's promise is opened beside the door again", MODULE,
     "            ports = Ports(self.project, tracker=tracker, columns={})\n",
     "            ports = Ports(self.project, tracker=tracker, columns={})\n"
     "            from openfactory.memory import store as loop_store\n"
     "            from openfactory.memory.ledger import DELIVERY, open_loop\n"
     "            loop_store.write(self.project.name, [open_loop(\n"
     "                DELIVERY, str(requirement.number), owner=\"product\", ts=\"now\")])\n",
     GUARD_TEST),

    ("the list names the old writer again, as though it had not moved", LIST,
     "OUTSIDE_THE_DOOR: dict[tuple[str, str, str], tuple[str, str]] = {}\n",
     "OUTSIDE_THE_DOOR: dict[tuple[str, str, str], tuple[str, str]] = {\n"
     "    (\"openfactory/product/followup.py\", \"deliveries_to_open\", \"open_loop\"):\n"
     "        (\"the delivery a requirement's cards are owed, over several cards\", \"3\"),\n"
     "}\n",
     GUARD_TEST),

    ("the exemption ceiling is raised, so the list can grow again", GUARD_TEST,
     "CEILING = 0\n",
     "CEILING = 1\n",
     GUARD_TEST),

    # ── 2. every card of the breakdown, reused ones too, carries the whole promise ──────────────
    ("a reused card is not promised, and an all-reused requirement opens no promise", MODULE,
     "            landed = [r.ref for r in results if r.ok and r.ref]\n",
     "            landed = [r.ref for r in results if r.ok and r.ref and not r.existed]\n"),

    ("each card carries a promise of the first card alone, so it names one card of three", MODULE,
     "            owed = self._track_requirement(requirement.number, numbers,\n",
     "            owed = self._track_requirement(requirement.number, numbers[:1],\n"),

    ("the promise forgets where it was asked and who asked", MODULE,
     "            owed = self._track_requirement(requirement.number, numbers,\n"
     "                                           conversation=conversation, requester=requester)\n",
     "            owed = self._track_requirement(requirement.number, numbers)\n"),

    # ── 3. one promise, once ────────────────────────────────────────────────────────────────────
    ("every card of a breakdown opens a promise of its own", LOOPS,
     "    if subject in {x.subject for x in waiting(loop_store.read(name)) "
     "if x.kind == DELIVERY}:\n",
     "    if False:\n"),

    ("a retried breakdown is decided again on every card, and each is promised twice", MODULE,
     "                                   event_id=_promised_id(name, ref, owed), ports=ports)\n",
     "                                   event_id=\"\", ports=ports)\n"),

    # ── 4. the door refuses a card done or gone, and the refusal stops nobody else ──────────────
    ("a card closed as not delivered is promised a requirement's delivery", TABLE,
     "                                   State.WAITING_ON_A_PERSON, State.MERGED, "
     "State.STAGED}),\n",
     "                                   State.WAITING_ON_A_PERSON, State.MERGED, "
     "State.STAGED,\n"
     "                                   State.CLOSED}),\n"),

    ("a card the door refuses stops the requirement's other cards from opening its promise",
     MODULE,
     "            if moved.refused:\n"
     "                log.info(\"REQ-%s: #%s was not promised — %s\", requirement.number,\n",
     "            if moved.refused:\n"
     "                break\n"
     "                log.info(\"REQ-%s: #%s was not promised — %s\", requirement.number,\n"),

    # ── 5. a promise moves nothing ──────────────────────────────────────────────────────────────
    ("a promise writes the card, moving it back to the backlog", TABLE,
     "        return (Loops(\"open\"),)\n",
     "        return (Column(\"backlog\"), Loops(\"open\"), Forget())\n"),

    ("a promise leaves the card in the backlog, wherever it found it", TABLE,
     "        return State(before) if before else None\n",
     "        return State.BACKLOG\n"),

    ("a promise reads the board, so a board that cannot be read costs a promise", MODULE,
     "            ports = Ports(self.project, tracker=tracker, columns={})\n",
     "            ports = Ports(self.project, tracker=tracker, board=self._board())\n"),

    ("a promise is taken for a move by everything that reads where a card is", TABLE,
     "MOVES_NOTHING: frozenset[CardEvent] = frozenset({CardEvent.PROMISED})\n",
     "MOVES_NOTHING: frozenset[CardEvent] = frozenset()\n",
     TABLE_TEST),

    ("the sweep takes a promise for the card's latest move, and strands the filing's placement",
     EXECUTOR,
     "        moved = history.latest_move\n",
     "        moved = history.latest\n",
     TABLE_TEST),

    ("an observed change is judged against where the last promise left the card", CARD,
     "            latest = history.latest_move\n",
     "            latest = history.latest\n",
     TABLE_TEST),

    ("the board sweep holds a card where its last promise left it", OBSERVED,
     "            latest = history.latest_move\n",
     "            latest = history.latest\n",
     TABLE_TEST),

    ("a card whose work stopped no longer says so once a requirement reused it", CARD,
     "                             canonical_ref(card)).latest_move\n",
     "                             canonical_ref(card)).latest\n"),
]
