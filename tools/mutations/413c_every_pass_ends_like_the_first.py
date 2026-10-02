"""#413 part 3 (#448 slice 2), proven by breaking it — an adjust pass ends the way the first did.

MEASURED ON A LIVE RUN (#448, card #1000007): the adjust pass rewrote the pull request, and when it
ended nothing rebuilt the preview and nobody told the requester (`ready_for_you` is keyed on the card
and the pull request, which a second pass does not change). Found while building this: `link_for`
reads the project's NAME, and its callers handed it the project, so "try it here" never carried the
preview's link.
"""

TEST = "tests/test_an_adjust_pass_ends_like_the_first.py"
LIFE = "tests/test_the_life_of_a_card.py"
TABLE_TEST = "tests/test_the_card_lifecycle_does_what_its_table_says.py"

WORKFLOW = "openfactory/runtime/temporal/workflow.py"
TABLE = "openfactory/lifecycle/table.py"
EVENTS = "openfactory/product/events.py"

MUTATIONS = [
    ("a pass that rewrote the pull request is never said to be ready", WORKFLOW,
     '        if passed.code_changed is True and workflow.patched("an-adjust-pass-ends-like-the-first"):\n',
     '        if False and workflow.patched("an-adjust-pass-ends-like-the-first"):\n'),

    ("a pass that changed nothing is announced as ready", WORKFLOW,
     '        if passed.code_changed is True and workflow.patched("an-adjust-pass-ends-like-the-first"):\n',
     '        if workflow.patched("an-adjust-pass-ends-like-the-first"):\n'),

    ("the new command runs whatever history the job recorded, so a job in flight diverges", WORKFLOW,
     '        if passed.code_changed is True and workflow.patched("an-adjust-pass-ends-like-the-first"):\n',
     '        if passed.code_changed is True and (workflow.patched("an-adjust-pass-ends-like-the-first") or True):\n'),

    ("the requester is never told a pass is ready", TABLE,
     '        return (Comment(), Preview("rebuild"), Tell(PASS_READY), Forget())\n',
     '        return (Comment(), Preview("rebuild"), Forget())\n',
     LIFE),

    ("the preview goes on showing the pass before", TABLE,
     '        return (Comment(), Preview("rebuild"), Tell(PASS_READY), Forget())\n',
     '        return (Comment(), Tell(PASS_READY), Forget())\n',
     TABLE_TEST),

    ("the pass's message says nowhere to try it", EVENTS,
     '                                                      link=_where_to_try(project, card)\n',
     '                                                      link=""\n',
     LIFE),

    ("the preview's link is asked for with the project instead of its name, and is never found",
     EVENTS,
     '        return link_for(getattr(project, "name", "") or "", str(card)) or _card_url(project, card)\n',
     '        return link_for(project, str(card)) or _card_url(project, card)\n',
     LIFE),
]
