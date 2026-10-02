"""What the product role waits for from a person survives the process that asked (#452).

Run:  .venv/bin/python tools/mutate.py tools/mutations/452_what_the_role_waits_for_survives_a_restart.py

The guard asks in this process and answers in a fresh interpreter, on the real SQLite store.

Rows 1-7 are the held card question: kept in the asking process alone (today's defect), read only
from this process's copy, left open when answered, closed before the redraft that a killed worker
never finishes, believed from a stale copy, aged by no written deadline, and missing from the one
reader of what waits. Rows 8-12 are the staged proposal's copy and record: the copy believed over
the store (today's defect on a second worker), the same staging told by its token, a decided copy
kept, a copy whose own row did not land lost, the store's open ask never thawed. Rows 13-16 are the
expiry notice: kept in memory alone (today's defect), not read by the late yes, said to every yes,
left owed past a fresh proposal. Rows 17-19 are the store's folds and the record's payload.
"""

TEST = "tests/test_what_the_role_waits_for_survives_a_restart.py"

CARDS = "openfactory/product/cards.py"
ENGINE = "openfactory/product/engine.py"
STAGING = "openfactory/product/staging.py"
WAITING = "openfactory/product/waiting.py"
MESSAGES = "openfactory/memory/messages.py"

MUTATIONS = [
    # ── the held card question ────────────────────────────────────────────────────────────────
    ("TODAY'S DEFECT: the card question is held in the asking process alone", CARDS,
     "    _OPEN[key] = held\n    if project is None:\n        return\n",
     "    _OPEN[key] = held\n    return\n"),

    ("the answer reads only this process's copy of the question", CARDS,
     "    stored = _from_the_store(key, project, local)\n",
     "    stored = _NOT_ASKED\n"),

    ("an answered or declined question's record is left open, so another process answers it "
     "again", CARDS,
     '    messages.release(getattr(project, "name", "") or "", token=question_token(key), '
     "answer=TAKEN)\n",
     ""),

    ("the question is closed when it is read, so a worker killed in the redraft loses it", ENGINE,
     "    held = cards.held_question(ex.key, project=ex.project)\n",
     "    held = cards.held_question(ex.key, project=ex.project)\n"
     "    cards.close_question(ex.key, project=ex.project)\n"),

    ("a copy this process kept is believed after another process took the question", CARDS,
     "        # TAKEN OR AGED OUT ELSEWHERE — a copy this process kept is that same question, "
     "stale\n        return None\n",
     "        return _NOT_ASKED\n"),

    ("a question's written deadline is not read", CARDS,
     "    if past(row.expires, time.time()):\n",
     "    if False:\n"),

    ("the held question is missing from what a conversation is listed as waiting for", WAITING,
     "        if m is not None and not past(m.expires, clock):\n",
     "        if False:\n"),

    # ── the staged proposal: the copy and the record ──────────────────────────────────────────
    ("TODAY'S DEFECT ON A SECOND WORKER: this process's copy is believed over the store", STAGING,
     "    if stored is _UNREAD or stored is None:\n        return local\n",
     "    if stored is _UNREAD or stored is None or local is not None:\n        return local\n"),

    ("the same staging is told by its token, and every card under one key shares it", STAGING,
     "        if staged is not None and staged == _moment(row) and proposal_token(thread,\n",
     "        if staged is not None and proposal_token(thread,\n"),

    ("a copy the store says was answered is still the proposal", STAGING,
     "            return local if settled is None else None\n",
     "            return local\n"),

    ("a copy whose own row did not land loses to the older row", STAGING,
     "        if _newer(local, row):\n            return local\n",
     ""),

    ("the store's open ask is never thawed, so a fresh process finds nothing staged", STAGING,
     "    return _thaw_row(row)\n",
     "    return None\n"),

    # ── the expiry notice ─────────────────────────────────────────────────────────────────────
    ("TODAY'S DEFECT: the expiry notice lives in this process's memory alone", STAGING,
     "    _hold_notice(thread, entry, project)\n",
     ""),

    ("the late yes reads only this process's tombstones", STAGING,
     '    told = _spend_notices(project, keys, "told")\n',
     "    told = False\n"),

    ("the written notice is said to every later yes", STAGING,
     "        for token in owed:\n"
     "            _panel_store.release(name, token=token, answer=answer)\n",
     ""),

    ("a fresh proposal leaves the older one's notice owed", STAGING,
     '        _spend_notices(project, (thread, where), "superseded")\n',
     ""),

    # ── the folds and the record ──────────────────────────────────────────────────────────────
    ("a hold's closing row is not read, so a taken question stays open", MESSAGES,
     "        if m.answer:\n            closed[m.token] = at\n",
     "        if m.answer:\n            continue\n"),

    ("a hold is drawn with Approve / Reject like a question with buttons", MESSAGES,
     "        if m.kind == ASKED and m.token:\n",
     "        if m.kind in (ASKED, HELD) and m.token:\n"),

    ("the held draft does not travel with the record", CARDS,
     "        draft = CardDraft(**{k: v for k, v in dict(raw[\"draft\"]).items() if k in names})\n",
     "        draft = CardDraft(title=\"?\", description=\"?\")\n"),
]
