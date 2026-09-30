"""Proven by breaking it — the model's prose and the code's frame agree on the next step (#430).

A person reported controls cut off at smaller window heights. The product role wrote "I'm not
proposing a requirement … say the word and I'll draft it" and ended with `[[DEFEITO]]`; the code
appended "This breaks something we already promised — I will register this problem to fix, exactly
as below:" and the whole card. One message offered, then did, then asked twice, and claimed a
promise the role had just said nobody wrote.

TWO CLAIMS:

  1. **Every marker that stages something tells the model the platform prepares it after the
     reply and asks its own question** — one shared phrase, carried by each of the five staging
     markers' instructions, so the prose neither offers nor asks.
  2. **A defect's frame claims no more than its marker carried** — a broken promise only with a
     requirement number, "not working as it should" without one, in either language; and the
     requirement is named in the conversation's language.

The guard is `tests/test_the_frame_and_the_prose_agree_on_the_next_step.py`.
"""

TEST = "tests/test_the_frame_and_the_prose_agree_on_the_next_step.py"

ROLE = "openfactory/product/role.py"
VOICE = "openfactory/product/voice.py"

MUTATIONS = [
    # ── claim 1: every staging marker says what comes after the reply ────────────────────────
    ("THE DEFECT ITSELF: the defect marker's instruction no longer says a card follows",
     ROLE,
     '            f"design. {STAGED_AFTER_YOUR_REPLY}\\n\\n"\n',
     '            "design.\\n\\n"\n'),

    ("the request marker's instruction loses the phrase",
     ROLE,
     '            f"marker {REQUEST_MARKER} on its own line. {STAGED_AFTER_YOUR_REPLY} If they "\n',
     '            f"marker {REQUEST_MARKER} on its own line. If they "\n'),

    ("the ticket marker's instruction loses the phrase",
     ROLE,
     '            f"{STAGED_AFTER_YOUR_REPLY} A card is not a promise: "\n',
     '            "A card is not a promise: "\n'),

    ("the order marker's instruction loses the phrase",
     ROLE,
     '            f"top first, exactly as they said them. {STAGED_AFTER_YOUR_REPLY} Writing the "\n',
     '            "top first, exactly as they said them. Writing the "\n'),

    ("the queue marker's instruction loses the phrase",
     ROLE,
     '            f"{STAGED_AFTER_YOUR_REPLY} "\n            "The marker is what puts',
     '            "The marker is what puts'),

    ("the scope shrinks: a staging marker is dropped from the list the guard walks",
     ROLE,
     "STAGING_MARKERS = (REQUEST_MARKER, DEFECT_MARKER, TICKET_MARKER, ORDER_MARKER, QUEUE_MARKER)\n",
     "STAGING_MARKERS = (REQUEST_MARKER, TICKET_MARKER, ORDER_MARKER, QUEUE_MARKER)\n"),

    ("the phrase stops forbidding the offer",
     ROLE,
     '    "Before the marker, say in your reply what you understood; do NOT offer to write it up or "\n',
     '    "Before the marker, say in your reply what you understood; you may offer to write it up or "\n'),

    # ── claim 2: the frame claims no more than the marker carried ────────────────────────────
    ("the short frame claims a promise whether or not the marker named one",
     VOICE,
     "        said = _DEFECT_CONFIRM if violates else _DEFECT_CONFIRM_UNWRITTEN\n",
     "        said = _DEFECT_CONFIRM\n"),

    ("the card frame claims a promise whether or not the marker named one — the live message",
     VOICE,
     "    said = _DEFECT_CARD_CONFIRM if violates else _DEFECT_CARD_CONFIRM_UNWRITTEN\n",
     "    said = _DEFECT_CARD_CONFIRM\n"),

    ("the unwritten English card frame goes back to the sentence the person read",
     VOICE,
     '    "en": "This is not working as it should — I will register this problem to fix, not as a new "\n',
     '    "en": "This breaks something we already promised — I will register this problem to fix, not as a new "\n'),

    ("the requirement is named in Portuguese whatever the conversation's language",
     VOICE,
     '                        "en": ", against requirement {violates}"}\n',
     '                        "en": ", contra o requisito {violates}"}\n'),
]
