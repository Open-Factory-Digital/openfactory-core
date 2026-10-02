"""The requester is told "it is starting itself" exactly where the factory starts it (review of #439).

Run:  .venv/bin/python tools/mutate.py tools/mutations/the_sentence_and_the_start_agree.py

Row 1 is the drift the review measured: `should_start` gains a refusal (on `preview.required`)
and `_preview_starts_itself` does not follow — green before the agreement test existed. Rows 2-3
break the sentence's own copy of the two conditions it shares with the start.
"""

TEST = "tests/test_the_requester_hears_the_change_is_theirs_to_try.py"

LIVE = "openfactory/preview/live.py"
EVENTS = "openfactory/product/events.py"

MUTATIONS = [
    ("THE DRIFT: the start gains a refusal the sentence does not know", LIVE,
     '    if not getattr(policy, "auto_start", True):\n        return False, ""\n',
     '    if not getattr(policy, "auto_start", True) or getattr(policy, "required", False):\n'
     '        return False, ""\n'),

    ("the sentence forgets the operator's `auto_start: false`", EVENTS,
     '        return bool(getattr(policy, "auto_start", True)) and bool(kind) and kind != "none"',
     '        return bool(kind) and kind != "none"'),

    ("the sentence reads a runtime named `none` as one that starts", EVENTS,
     '        return bool(getattr(policy, "auto_start", True)) and bool(kind) and kind != "none"',
     '        return bool(getattr(policy, "auto_start", True)) and bool(kind)'),
]
