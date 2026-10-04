"""The product role tells the person who asked for a card that its change is now theirs to try,
once, in their conversation — and the agenda speaks their language (#401).

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/401_the_requester_hears_the_change_is_theirs_to_try.py

Row 1 is the defect as it shipped: the merge watch tells nobody. Rows 2-3 widen who hears it (an
armed auto-merge, the room for a card nobody asked for). Rows 4-5 break the event's identity: a
fresh id per telling says it on every poll, an id without the pull request never tells a second
one. Row 6 drops the round's catch-all, which is what reaches a job already in the watch. Rows 7-8
break the preview's two forms (the live address the seam carries, and a button promised on a card
with none). Rows 9-11 break the review line: the verdict not handed over, flags read as a clean
approval, an unknown verdict read as "no review". Rows 12-13 are the activity reaching nothing and
the worker not knowing it. Rows 14-17 are the agenda: the language dropped in the lines, in the
action, and the panel ignoring the server's chip and its sentence about what the tab is.
"""

TEST = "tests/test_the_requester_hears_the_change_is_theirs_to_try.py"

WF = "openfactory/runtime/temporal/workflow.py"
EV = "openfactory/product/events.py"
VO = "openfactory/product/voice.py"
ACT = "openfactory/runtime/temporal/activities.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the merge watch tells the requester nothing", WF,
     "            await self._tell_the_requester(params, result)\n",
     "            pass\n"),

    ("an armed auto-merge, waiting on a build, tells the requester it is theirs", WF,
     'if not result.auto_merge and workflow.patched("the-requester-hears-it-is-theirs"):',
     'if workflow.patched("the-requester-hears-it-is-theirs"):'),

    ("a card nobody asked for in a conversation is announced to the room", EV,
     "    where = requester_conversation(project, card)\n    if not where:\n        return False\n",
     "    where = conversation_for(project, card)\n    if not where:\n        return False\n"),

    ("every telling is a new event, so each poll says it again", EV,
     "_event_id(READY_FOR_YOU, project, card, pr_url)",
     "_event_id(READY_FOR_YOU, project, card, str(time.time()))"),

    ("the event is keyed by the card alone, so a second pull request is never told", EV,
     "_event_id(READY_FOR_YOU, project, card, pr_url)",
     "_event_id(READY_FOR_YOU, project, card)"),

    ("the tech-lead's round no longer tells a gate the watch never did", ACT,
     "        events.ready_at_the_gate(project, gates)\n",
     ""),

    ("a preview that is already up is left out of the message", VO,
     '    if str(preview_url or "").strip():\n        try_it',
     '    if False:\n        try_it'),

    ("the message sends them to a preview button on a card that offers none", EV,
     "preview=not preview_url and _preview_offered(project, card),",
     "preview=not preview_url,"),

    ("the watch does not hand the reviewer's verdict to the telling", WF,
     "verdict=dict(self._verdict) if self._verdict else None),",
     "verdict=None),"),

    ("an approval with flags reads as a clean approval", "openfactory/review/verdict.py",
     '"stance": FLAGGED,',
     '"stance": APPROVED,'),

    ("a verdict the round never saw is said as 'no automatic review read this version'", EV,
     '    if verdict is None:\n        return ""\n    from openfactory.review.verdict import '
     'headline',
     '    if verdict is None:\n        verdict = {}\n    from openfactory.review.verdict import '
     'headline'),

    ("the activity reaches nothing", ACT,
     "            return events.ready_for_you(project, card=inp.issue, pr_url=inp.pr_url,",
     "            return False and events.ready_for_you(project, card=inp.issue, pr_url=inp.pr_url,"),

    ("the worker does not register the activity, so every telling fails unknown",
     "openfactory/runtime/temporal/worker.py",
     "    # #401 — the requester told the change is theirs to try, from the merge watch\n"
     "    tell_the_requester,\n",
     ""),

    ("the agenda's lines ignore the project's language", "openfactory/product/agenda.py",
     "direction, said = _said(loop, yours=yours, language=language)",
     "direction, said = _said(loop, yours=yours, language=None)"),

    ("the panel's agenda action does not pass the project's language",
     "openfactory/actions/catalog.py",
     '    language = getattr(proj, "language", None)\n    found = agenda.pending(',
     '    language = None\n    found = agenda.pending('),

    ("the panel draws its own English chip instead of the server's words",
     "openfactory/api/panel.html",
     "const chip=esc(String(i.chip||",
     "const chip=esc(String("),

    ("the panel never draws the server's sentence saying what the tab is",
     "openfactory/api/panel.html",
     'if(about&&_prod.agendaAbout)about.textContent=_prod.agendaAbout;',
     ""),
]
