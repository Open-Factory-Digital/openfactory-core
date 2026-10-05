"""The ready-for-you message waits for a preview that starts itself, instead of asking for it (#437)."""

TEST = "tests/test_the_requester_hears_the_change_is_theirs_to_try.py"
EVENTS = "openfactory/product/events.py"
VOICE = "openfactory/product/voice.py"

MUTATIONS = [
    # re-pinned 2026-10-04: the telling is the card door's port's (`ready_to_try`, #414)
    ("the event never asks whether previews start themselves", EVENTS,
     "                                preview_starts_itself=_preview_starts_itself(project)))):\n",
     "                                preview_starts_itself=False))):\n"),
    ("the policy's auto_start is not asked", EVENTS,
     '        return bool(getattr(policy, "auto_start", True)) and bool(kind) and kind != "none"\n',
     '        return bool(kind) and kind != "none"\n'),
    ("a deployment with no runtime is said to start previews itself", EVENTS,
     '        return bool(getattr(policy, "auto_start", True)) and bool(kind) and kind != "none"\n',
     '        return bool(getattr(policy, "auto_start", True))\n'),
    ("the message ignores a preview that starts itself", VOICE,
     "    elif preview and preview_starts_itself:\n",
     "    elif False:\n"),
    ("a card with nothing offered is still told to wait for a preview", VOICE,
     "    elif preview and preview_starts_itself:\n",
     "    elif preview_starts_itself:\n"),
]
