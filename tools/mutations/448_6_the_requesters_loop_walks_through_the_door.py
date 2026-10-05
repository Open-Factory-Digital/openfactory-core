"""The requester's loop walks through the card's door (#448 slice 6, behaviour 7; ADR-0055 amended
2026-10-05). The claims:

  · THE TABLE. `resumed`, `accepted`, `staged`, `stage_rejected` and `released` happen on a card the
    factory holds (running, waiting on a person, merged, staged), and `delivered` from a merged or
    staged card too; each does its row — a pass writes nothing beside its act, a yes at the merge
    gate is a comment, a yes at the last gate their word does not release closes their copy and
    tells the room, a yes that may release given when the job was gone closes every copy (#273),
    the job's merge telling tells and writes no column, the box's production gate is a column and
    nobody told, the round's asking opens the room's copy, tells them and opens theirs, a "not yet"
    closes every copy as not worked, a release every copy as worked — and lands where it says;
  · THE DOOR reads merged or staged from the record for the loop's events alone, only when the
    column cannot tell, and only those two states;
  · THE EXECUTOR AND THE PORTS hand each telling and the release question what the transition knew,
    and route each to its own teller and its own half of the ledger;
  · THE RELEASE QUESTION is asked once per asking, theirs once per run and only once they were told,
    and their yes closes theirs alone;
  · THE WRITERS go through the door: the merge telling (keyed by the pull request), the round's
    asking (its act the room's question), the release gate's verdicts, the acceptance (its record
    the act), the pass (its bar and its signal the act), a correction before pickup (`edited`),
    the floor's and the product role's release rows; the box's production gate is `staged`;
  · THE GUARD sees each new form — the loop's notices on `events` or by name, called or handed on;
    a card's text beside a door outside its act (and only beside a door: refine, align and repoint
    are no transition's, which a global form would find); a release question's loop or
    constructor; the acceptance outside an act — and admits a write inside a function or a lambda
    handed to a transition as `act=`;
  · THE SCENARIO, on real parts: every step recorded where it should be and told where they asked;
    the reading walks all seven steps; nothing is left for the converge; the delivery is announced
    once, with its "did it work?";
  · A CARD HELD MERGED OR STAGED CAN STILL BE ENDED (review of #524): a close or a deletion seen on
    the vendor's screen is judged on the record, and refusing it would strand the promise.
"""

TEST = "tests/test_the_requesters_loop_walks_through_the_door.py"
GUARD_TEST = "tests/test_the_card_lifecycle_has_one_door.py"
YES = "tests/test_the_requesters_yes_feeds_the_merge.py"
STAGING = "tests/test_staging_belongs_to_the_requester.py"
TABLE = "openfactory/lifecycle/table.py"
CARD = "openfactory/lifecycle/card.py"
EXECUTOR = "openfactory/lifecycle/executor.py"
PORTS = "openfactory/lifecycle/ports.py"
LOOPS = "openfactory/lifecycle/loops.py"
HANDED_BACK = "openfactory/lifecycle/handed_back.py"
READING = "openfactory/lifecycle/reading.py"
MODULE = "openfactory/product/module.py"
ENGINE = "openfactory/product/engine.py"
EVENTS = "openfactory/product/events.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
CATALOG = "openfactory/actions/catalog.py"

MUTATIONS = [
    # ── the table: where each event may happen ───────────────────────────────────────────────
    ("a pass is sent back from no gate", TABLE,
     "    CardEvent.RESUMED: HELD,\n", "    CardEvent.RESUMED: frozenset(),\n"),
    ("a yes is recorded on no card", TABLE,
     "    CardEvent.ACCEPTED: HELD,\n", "    CardEvent.ACCEPTED: frozenset(),\n"),
    ("no card is ever on a stage", TABLE,
     "    CardEvent.STAGED: HELD,\n", "    CardEvent.STAGED: frozenset(),\n"),
    ("a not-yet at a stage is refused", TABLE,
     "    CardEvent.STAGE_REJECTED: HELD,\n", "    CardEvent.STAGE_REJECTED: frozenset(),\n"),
    ("a release is refused", TABLE,
     "    CardEvent.RELEASED: HELD,\n", "    CardEvent.RELEASED: frozenset(),\n"),
    ("a merged or staged card is never delivered", TABLE,
     "    CardEvent.DELIVERED: HELD,\n",
     "    CardEvent.DELIVERED: frozenset({State.RUNNING, State.WAITING_ON_A_PERSON}),\n"),
    ("a card the factory holds is only one a job runs or a person decides", TABLE,
     "HELD = frozenset({State.RUNNING, State.WAITING_ON_A_PERSON, State.MERGED, State.STAGED})\n",
     "HELD = frozenset({State.RUNNING, State.WAITING_ON_A_PERSON})\n"),
    ("the loop's events are judged with no board as refused", TABLE,
     "    CardEvent.RESUMED, CardEvent.ACCEPTED, CardEvent.STAGED, CardEvent.STAGE_REJECTED,\n"
     "    CardEvent.RELEASED})\n",
     "    })\n"),

    # ── the table: what follows each ─────────────────────────────────────────────────────────
    ("the job's merge telling tells nobody", TABLE,
     "            return (Tell(MERGED_FOR_YOU), Forget())\n",
     "            return (Forget(),)\n"),
    ("the job's merge telling moves the card back In review", TABLE,
     "            return (Tell(MERGED_FOR_YOU), Forget())\n",
     '            return (Column("merged"), Tell(MERGED_FOR_YOU), Forget())\n'),
    ("a pass sent back writes a column beside the box's marks", TABLE,
     "        # ends it, so nothing else is written here\n        return (*_said(facts), Forget())\n",
     "        # ends it, so nothing else is written here\n"
     '        return (Column("in_progress"), *_said(facts), Forget())\n'),
    ("a yes at the merge gate says nothing on the card", TABLE,
     "        # the card says who, on which head, and whether it is going in\n"
     "        return (*_said(facts), Forget())\n",
     "        # the card says who, on which head, and whether it is going in\n"
     "        return (Forget(),)\n"),
    ("a yes the job did not take leaves the question to be chased (#273)", TABLE,
     "            return (Loops(RELEASE_WORKED), *_said(facts), Forget())\n",
     "            return (*_said(facts), Forget())\n"),
    ("the box's production gate is put in no column", TABLE,
     '        return (Column("awaiting_prod_approval"), *_said(facts), Forget())\n',
     "        return (*_said(facts), Forget())\n"),
    ("the requester hears of a stage before the room's question landed", TABLE,
     '        return (Column("awaiting_prod_approval"), *_said(facts), Forget())\n',
     '        return (Column("awaiting_prod_approval"), *_said(facts), Tell(STAGED_FOR_YOU), '
     'Forget())\n'),
    ("the round's asking opens no question in the room", TABLE,
     "            return (Loops(RELEASE_ASK), Tell(STAGED_FOR_YOU), Loops(RELEASE_ASK_THEIRS))\n",
     "            return (Tell(STAGED_FOR_YOU), Loops(RELEASE_ASK_THEIRS))\n"),
    ("a not-yet at a stage closes nothing", TABLE,
     "        return (*_said(facts), Loops(RELEASE_DID_NOT_WORK), Forget())\n",
     "        return (*_said(facts), Forget())\n"),
    ("a release closes its question as not worked", TABLE,
     "        return (*_said(facts), Loops(RELEASE_WORKED), Forget())\n",
     "        return (*_said(facts), Loops(RELEASE_DID_NOT_WORK), Forget())\n"),
    ("a not-yet takes the card off its stage", TABLE,
     "    if event in (CardEvent.RESUMED, CardEvent.RELEASED):\n",
     "    if event in (CardEvent.RESUMED, CardEvent.RELEASED, CardEvent.STAGE_REJECTED):\n"),
    ("a yes moves the card to a person's gate wherever it was", TABLE,
     '        return State(before) if before else (State.STAGED if facts.get("gate") == "last"\n',
     '        return State.WAITING_ON_A_PERSON if before else (State.STAGED if facts.get("gate") '
     '== "last"\n'),

    # ── the door reads merged or staged from the record ──────────────────────────────────────
    ("the door never reads the record for the loop", CARD,
     "        elif event in READ_FROM_THE_RECORD:\n"
     "            seen = replace(seen, state=_merged_or_staged(seen.state, history))\n",
     ""),
    ("the door reads the record for every event", CARD,
     "        elif event in READ_FROM_THE_RECORD:\n",
     "        elif True:\n"),
    ("the record overrides the column with any state it holds", CARD,
     "    return said if said in _ONLY_THE_RECORD_SAYS else state\n",
     "    return said or state\n"),
    ("the record overrides a column that can tell", CARD,
     "    if state not in _A_COLUMN_CANNOT_TELL or latest is None:\n",
     "    if latest is None:\n"),

    # ── the executor and the ports ───────────────────────────────────────────────────────────
    ("the merge telling never hears whether stages follow", EXECUTOR,
     '        return {"stages_follow": bool(facts.get("stages_follow"))}\n',
     "        return {}\n"),
    ("the stage's telling is handed no address and no run", EXECUTOR,
     '        return {"where": str(facts.get("where") or ""), "run": str(facts.get("run") or ""),\n',
     '        return {"where": "", "run": "",\n'),
    ("the release question is asked with nothing the round knew", EXECUTOR,
     "            return ports.loops(row.card, effect.action, release=_release_facts(facts))\n",
     "            return ports.loops(row.card, effect.action, release={})\n"),
    ("every effect's outcome is lost from the record", EXECUTOR,
     "            record.write_outcome(sink, ports.name, row, index, outcome)\n",
     "            pass\n"),
    ("the converge applies again what landed", EXECUTOR,
     "        if outcome.startswith(FAILED) or (not outcome and not recent):\n",
     "        if True:\n"),
    ("the merge telling is said as a card moved", PORTS,
     "        if notice == MERGED_FOR_YOU:\n", '        if notice == "nobody":\n'),
    ("the stage's telling is said as a card moved", PORTS,
     "        if notice == STAGED_FOR_YOU:\n", '        if notice == "nobody":\n'),
    ("the room's telling is said as a card moved", PORTS,
     "        if notice == TRIED:\n", '        if notice == "nobody":\n', STAGING),
    ("the release question is never asked through the door", PORTS,
     "        if action in RELEASE_ASKS:\n", "        if action in ():\n"),
    ("the release question is never answered through the door", PORTS,
     "        if action in RELEASE_CLOSES:\n", "        if action in ():\n"),

    # ── the release question on the ledger ───────────────────────────────────────────────────
    ("the room is asked twice by one asking", LOOPS,
     '        if any(x.ts == ts and not (x.context or {}).get("conversation") for x in mine):\n',
     "        if False:\n"),
    ("their copy is asked though they were never told", LOOPS,
     "        if not events.told_at_the_stage(project, card=issue, run=run):\n",
     "        if False:\n"),
    ("their copy is asked again in the same run", LOOPS,
     '            return "they were asked already for this run"\n',
     '            pass\n'),
    ("their yes closes the room's copy too", LOOPS,
     '    only_theirs = verdict == "theirs-worked"\n',
     "    only_theirs = False\n"),

    # ── the writers, through the door ────────────────────────────────────────────────────────
    ("a pass sent back is recorded and never sent", MODULE,
     "                           act=the_bar_and_the_pass, tracker=self._tracker())\n",
     "                           act=None, tracker=self._tracker())\n"),
    ("a pass sent back is recorded as an edit", MODULE,
     '        moved = transition(self.project, f"#{number}", CardEvent.RESUMED, by=actor,\n',
     '        moved = transition(self.project, f"#{number}", CardEvent.EDITED, by=actor,\n'),
    ("a yes is recorded on the card and not in the store", MODULE,
     "                           act=write, tracker=self._tracker())\n",
     "                           act=None, tracker=self._tracker())\n", YES),
    ("a correction before pickup is recorded as nothing", MODULE,
     '            moved = transition(self.project, f"#{number}", CardEvent.EDITED, by=actor,\n',
     '            moved = transition(self.project, f"#{number}", CardEvent.PROMISED, by=actor,\n'),
    ("a not-yet at a stage is recorded as their yes", ENGINE,
     "        _at_the_last_gate(project, loop, CardEvent.STAGE_REJECTED, user=user,\n",
     "        _at_the_last_gate(project, loop, CardEvent.ACCEPTED, user=user,\n"),
    ("a release is recorded as a yes that released nothing", ENGINE,
     "    moved = _at_the_last_gate(project, loop, CardEvent.RELEASED, user=user,\n",
     "    moved = _at_the_last_gate(project, loop, CardEvent.ACCEPTED, user=user,\n"),
    ("a release is recorded and never sent", ENGINE,
     "        ok, why = release(project, issue, approver=user,\n"
     "                          comment=engine_said(whose, language=lang))\n",
     '        ok, why = True, ""\n'),
    ("their yes is recorded as a not-yet", ENGINE,
     "    moved = _at_the_last_gate(project, loop, CardEvent.ACCEPTED, user=user,\n"
     '                              facts={"who": _name_of(user), "note": ""})\n',
     "    moved = _at_the_last_gate(project, loop, CardEvent.STAGE_REJECTED, user=user,\n"
     '                              facts={"who": _name_of(user), "note": ""})\n', STAGING),
    ("the round's question is never asked", ACTIVITIES,
     "                act=ask, tracker=tracker))\n",
     "                act=None, tracker=tracker))\n"),
    ("the merge telling never says whether stages follow", ACTIVITIES,
     '                               facts={"pr_url": inp.pr_url, "stages_follow": '
     'inp.stages_follow,\n',
     '                               facts={"pr_url": inp.pr_url,\n'),
    ("a retried merge telling is a second transition", ACTIVITIES,
     '                               event_id=merged_event(inp.pr_url) if inp.pr_url else "")\n',
     '                               event_id="")\n', YES),
    ("an operator's approval is recorded as a yes", CATALOG,
     "    moved = await _through_the_door(found, issue, CardEvent.RELEASED, by=by, why=comment,\n",
     "    moved = await _through_the_door(found, issue, CardEvent.ACCEPTED, by=by, why=comment,\n"),
    ("a product admin's release is recorded as a yes", CATALOG,
     "    moved = await _through_the_door(proj, ref, CardEvent.RELEASED, by=by,\n",
     "    moved = await _through_the_door(proj, ref, CardEvent.ACCEPTED, by=by,\n"),
    ("the box's production gate is a park again", HANDED_BACK,
     "    JobState.AWAITING_PROD_APPROVAL: CardEvent.STAGED,\n",
     "    JobState.AWAITING_PROD_APPROVAL: CardEvent.PARKED,\n"),
    ("the stage is recorded without its name", HANDED_BACK,
     '            facts.update(stage=str(getattr(result, "look_stage", "") or ""),\n',
     '            facts.update(stage="",\n'),
    ("a merge with stages ahead is said by a delivery that has not come", EVENTS,
     "    if not stages_follow and _the_delivery_says_it(project, card, rows):\n",
     "    if _the_delivery_says_it(project, card, rows):\n"),

    # ── the reading ──────────────────────────────────────────────────────────────────────────
    ("a pass sent back reads as ready to try", READING,
     '    "resumed": ADJUSTING,\n', '    "resumed": PREVIEW_READY,\n'),
    ("a not-yet reads as still in staging", READING,
     '    "stage_rejected": ADJUSTING,\n', '    "stage_rejected": IN_STAGING,\n'),
    ("an armed merge reads as ready for a person", READING,
     '        return PREVIEW_READY if facts.get("needs_person") else None\n',
     "        return PREVIEW_READY\n"),
    ("a card that left the loop stays at its step", READING,
     '    if event in _OUT_OF_THE_LOOP:\n        return ""\n', ""),
    ("a step walked again straight after is walked twice", READING,
     "        if said and (not walked or walked[-1] != said):\n", "        if said:\n"),

    # ── the scenario's end ───────────────────────────────────────────────────────────────────
    ("the last stage delivers and announces nothing", TABLE,
     '        return (Column("done"), *_said(facts), Loops("deliver"), Forget())\n',
     '        return (Column("done"), *_said(facts), Forget())\n'),

    # ── the guard's new forms ────────────────────────────────────────────────────────────────
    ("the walk stops seeing the loop's notices", GUARD_TEST,
     "                     # #448 slice 6: the requester's loop past the pull request\n"
     '                     "merged_for_you", "staged_for_you", "tried_and_right",\n'
     '                     "went_in", "to_try_at_the_stage", "tried_it_right"})\n',
     "                     })\n", GUARD_TEST),
    ("the walk stops seeing what a file imports by name", GUARD_TEST,
     "            functions.update({a.asname or a.name: a.name for a in node.names})\n",
     "            pass\n", GUARD_TEST),
    ("the walk stops seeing a notice handed on to a thread", GUARD_TEST,
     "            if isinstance(node, ast.Attribute | ast.Name) and _a_notice_handed_on(\n",
     "            if False and _a_notice_handed_on(\n", GUARD_TEST),
    ("the walk stops seeing a card's text written beside its door", GUARD_TEST,
     "                if beside_the_door and not in_an_act:\n", "                if False:\n",
     GUARD_TEST),
    ("the walk refuses a card's text written inside a transition's act", GUARD_TEST,
     "                in_an_act = id(node) in in_lambda_acts or any(f.name in acts for f in "
     "enclosing)\n",
     "                in_an_act = False\n", GUARD_TEST),
    ("the walk refuses a write inside a lambda handed as the act", GUARD_TEST,
     "                in_lambdas |= {id(sub) for sub in ast.walk(kw.value) if isinstance(sub, "
     "ast.Call)}\n",
     "                pass\n", GUARD_TEST),
    ("the text form reaches writers no transition carries (refine, align, repoint)", GUARD_TEST,
     "                beside_the_door = any(_named(f) & THE_DOOR for f in enclosing)\n",
     "                beside_the_door = True\n", GUARD_TEST),
    ("the walk stops seeing a release question answered beside the door", GUARD_TEST,
     "            elif name in LOOP_WRITES and fn is not None and _named(fn) & (CARD_LOOPS | "
     "RELEASES):\n",
     "            elif name in LOOP_WRITES and fn is not None and _named(fn) & CARD_LOOPS:\n",
     GUARD_TEST),
    ("the walk stops seeing a release question asked beside the door", GUARD_TEST,
     '                found.add((rel, here, "followup.release_of"))\n', "                pass\n",
     GUARD_TEST),
    ("the walk stops seeing the acceptance recorded beside the door", GUARD_TEST,
     '                    found.add((rel, here, "accept.record"))\n', "                    pass\n",
     GUARD_TEST),
    ("the walk refuses the acceptance recorded inside its transition's act", GUARD_TEST,
     "                if not (id(node) in in_lambda_acts\n"
     "                        or any(f.name in acts for f in around(node.lineno))):\n",
     "                if True:\n", GUARD_TEST),
    # ── the review of #524: a card the record holds merged or staged can still be ended ───────
    ("a merged or staged card closed on the vendor's screen is refused, and its promise stranded",
     TABLE,
     "                                 State.WAITING_ON_A_PERSON, State.MERGED, State.STAGED,\n"
     "                                 State.DELIVERED}),",
     "                                 State.WAITING_ON_A_PERSON,\n"
     "                                 State.DELIVERED}),",
     "tests/test_the_card_lifecycle_does_what_its_table_says.py"),
    ("a merged or staged card deleted on the vendor's screen is refused, and its promise stranded",
     TABLE,
     "    CardEvent.REMOVED: frozenset({State.BACKLOG, State.TODO, State.RUNNING,\n"
     "                                  State.WAITING_ON_A_PERSON, State.MERGED, State.STAGED}),",
     "    CardEvent.REMOVED: frozenset({State.BACKLOG, State.TODO, State.RUNNING,\n"
     "                                  State.WAITING_ON_A_PERSON}),",
     "tests/test_the_card_lifecycle_does_what_its_table_says.py"),
]
