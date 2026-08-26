"""#156: a yes reaches the button the factory put on the screen — and nothing else does.

The asymmetry is the sharpest in the codebase: a miss costs a rephrase, a false positive lands a
pull request on a sentence that was agreement with an opinion. So the reverses matter more than
the forwards here.
"""

TEST = "tests/test_a_yes_is_an_answer.py"
STAGED = "tests/test_a_staged_decision_survives_a_refresh.py"
INTENTS = "openfactory/actions/floor_intents.py"
CATALOG = "openfactory/actions/catalog.py"

MUTATIONS = [
    # ── the yes reaches the proposal ────────────────────────────────────────────────────────────
    ("a plain yes goes back to being a fresh question — the original defect", CATALOG,
     "    if is_affirmation(text):", "    if False:"),

    ("the yes is checked only after the agent has been paid", CATALOG,
     "    if is_affirmation(text):\n", "    if is_affirmation(text) and False:\n"),

    # ── and nothing else does ───────────────────────────────────────────────────────────────────
    # NOT `^` ALONE — `.match` anchors at the start anyway, so dropping it changes nothing and
    # the first version of this cut survived for that reason rather than for a guard's weakness.
    ("the affirmation stops being anchored, so `ok, but wait` presses the button", INTENTS,
     r'    return re.compile(rf"^\s*(?P<gesture>{alternatives})\s*[.!?]*\s*$", re.I)',
     r'    return re.compile(rf"^\s*(?P<gesture>{alternatives})", re.I)'),

    ("a question counts as an answer, so `pode?` merges", INTENTS,
     '    return not _asks_rather_than_tells(body, hit.end("gesture"))', "    return True"),

    ("the question mark is read past the whole message again, so the test cannot fire", INTENTS,
     '    return not _asks_rather_than_tells(body, hit.end("gesture"))',
     "    return not _asks_rather_than_tells(body, len(body))"),

    ("`pode ser` becomes a yes — agreeing with advice reads as ordering it", INTENTS,
     '"pode", "pode seguir", "pode ir",', '"pode", "pode ser", "pode seguir", "pode ir",'),

    ("…and the reverse: nothing counts as a yes, so the button is the only door again", INTENTS,
     r'    return re.compile(rf"^\s*(?P<gesture>{alternatives})\s*[.!?]*\s*$", re.I)',
     r'    return re.compile(rf"^\s*(?!)(?P<gesture>{alternatives})\s*[.!?]*\s*$", re.I)'),

    # ── it only fires when something is staged ──────────────────────────────────────────────────
    ("a yes runs the executor with nothing proposed", CATALOG,
     "        if live is not None:", "        if True:"),

    # ── one implementation, two doors ───────────────────────────────────────────────────────────
    ("a stale token is applied to whatever is staged now", CATALOG,
     "    if found is None or (token and found[0].token != token):",
     "    if found is None:", STAGED),

    ("the button is only retired when the action worked", CATALOG,
     '    channel.answer(project, token=message.token, answer="approve", '
     'by=str(by.id or by.display))',
     '    if outcome.ok:\n        channel.answer(project, token=message.token, answer="approve", '
     'by=str(by.id or by.display))', STAGED),

    ("an unreadable store reads as `the tech-lead is not proposing that`", CATALOG,
     "    except StoreUnreadable as exc:", "    except _NeverRaised as exc:"),

    ("a retired proposal answers with silence instead of saying which kind of late", CATALOG,
     "    if why:", "    if False:"),
]
