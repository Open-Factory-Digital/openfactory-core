"""A turn run again after its worker died records the person's message once, under the moment it
was said, and keeps one answer — the one the person was shown (#394).

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/394_a_retried_turn_records_the_message_once.py

Row 1 is the defect as it shipped: the row's key was the moment of the WRITE, so a retried turn
wrote the person's message a second time. Rows 2-8 each break one hop the arrival moment travels —
the message's stamp, the door, the workflow's turn input (dropped, or taken from the wrong message
of a coalesced turn), the worker's rebuild of the message, the engine's two paths, the room's keep.
Rows 9-11 are the answer: a retry that is never told it is one, and a withdrawal that reaches past
its own message or withdraws nothing. Rows 12-13 are the intake's facts appended again, or keyed by
the words instead of the message. Row 14 reads a stamp without a zone in the worker's local time.
"""

TEST = "tests/test_a_retried_turn_records_the_message_once.py"

TRANSCRIPT = "openfactory/memory/transcript.py"
ENGINE = "openfactory/product/engine.py"
DOOR = "openfactory/product/door.py"
FLOW = "openfactory/runtime/temporal/conversation.py"
WORKER = "openfactory/runtime/temporal/activities.py"
CASE = "openfactory/product/case.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the row is keyed by the moment of the write, so a retry is a second row",
     TRANSCRIPT,
     "        now = _said_at(at) or datetime.now(UTC)\n",
     "        now = datetime.now(UTC)\n"),

    ("a message is not stamped with when it arrived", ENGINE,
     "    at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())\n",
     '    at: str = ""\n'),

    ("the door does not carry the stamp onto the conversation", DOOR,
     "kind=kind, at=message.at)", "kind=kind)"),

    ("the workflow's turn input drops the stamp", FLOW,
     "            at=last.at)", '            at="")'),

    ("a coalesced turn is keyed by its first message, not the one its id names", FLOW,
     "            at=last.at)", "            at=arrivals[0].at)"),

    ("the worker rebuilds the message on its own clock", WORKER,
     '    return {"at": inp.at} if getattr(inp, "at", "") else {}',
     "    return {}"),

    ("the turn records the person's line without the stamp", ENGINE,
     "                                       in_reply_to=message.in_reply_to, at=message.at,\n",
     "                                       in_reply_to=message.in_reply_to,\n"),

    ("the read-only path records the person's line without the stamp", ENGINE,
     "in_reply_to=message.in_reply_to, at=message.at, **_files_of(message))",
     "in_reply_to=message.in_reply_to, **_files_of(message))"),

    ("a message kept for the room is recorded without the stamp", WORKER,
     "        addressed=False, at=inp.at)", "        addressed=False)"),

    ("the worker never tells the engine a turn is a retry, so its answer is added to the first's",
     WORKER,
     "        return activity.info().attempt > 1\n", "        return False\n"),

    ("the withdrawal reaches every answer in the conversation, not the one to this message",
     TRANSCRIPT,
     '                    or str(extra.get("in_reply_to", "")) != answering\n', "\n"),

    ("the withdrawal writes the answer back as it was, withdrawing nothing", TRANSCRIPT,
     '            kept = {SUPERSEDED_MARK: True, "text": "", "in_reply_to": answering}\n',
     '            kept = {**extra, SUPERSEDED_MARK: True}\n'),

    ("the intake notes a message it already noted", CASE,
     "            if seen is not None:\n                return seen\n",
     "            if seen is not None:\n                pass\n"),

    ("the intake is keyed by the words, so a person who says it again is not heard", CASE,
     "            seen = next((c for c in mine if message_id in c.noted), None)\n",
     "            seen = next((c for c in mine if (text or '').strip() in c.facts), None)\n"),

    ("a stamp without a zone is read in the worker's local time", TRANSCRIPT,
     "    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)\n",
     "    return when\n"),
]
