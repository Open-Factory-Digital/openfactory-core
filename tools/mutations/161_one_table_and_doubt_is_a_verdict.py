"""#161: one assent table for three surfaces, and a token that cannot decide says so.

The reverses carry most of the weight here. A vocabulary that refuses everything passes every
"must not sign off" test and makes the channels useless; an ambiguity rule that fires on every
message turns the fast path off and sends the whole conversation to a model.
"""

TEST = "tests/test_a_yes_is_an_answer.py"
CHANNEL = "tests/test_product_channel.py"
MONEY = "tests/test_sweep_client_surface.py"
ASSENT = "openfactory/language/assent.py"
FOLLOWUP = "openfactory/product/followup.py"
STAGING = "openfactory/product/staging.py"
BOT = "openfactory/runtime/slack/bot.py"
INTENTS = "openfactory/actions/floor_intents.py"

MUTATIONS = [
    # ── doubt is a verdict ──────────────────────────────────────────────────────────────────────
    ("an ambiguous token is dropped again — the Spanish complaint signs off the delivery",
     FOLLOWUP,
     "    doubt = _CANNOT_DECIDE.search(body)\n"
     "    if doubt and doubt.start() < positive.start():\n        return \"\"",
     "    if False:\n        return \"\""),

    ("the doubt list empties, so `no funciona` decides alone", FOLLOWUP,
     r'    r"\b(no|nada|ni|sin|pas|nicht|niet|non)\b",', r'    r"\b(zzzz)\b",'),

    ("…and the reverse: a temporal adverb carries doubt, deferring real acceptances", FOLLOWUP,
     r'    r"\b(no|nada|ni|sin|pas|nicht|niet|non)\b",',
     r'    r"\b(no|nada|ni|sin|pas|nicht|niet|non|ya|todav[ií]a)\b",'),

    ("POSITION stops deciding, so the Portuguese locative defers every real acceptance", FOLLOWUP,
     "    if doubt and doubt.start() < positive.start():",
     "    if doubt:"),

    ("the denial stops being checked first, so a denial carrying a positive word signs off",
     FOLLOWUP,
     '    if _DID_NOT_WORK.search(body):\n        return "did-not-work"\n',
     ""),

    # ── one table, three surfaces ───────────────────────────────────────────────────────────────
    ("the product channel goes back to its own vocabulary — `certo` asserts again", STAGING,
     "    from openfactory.language import assent\n\n    return assent.asserts_assent(text)",
     "    return True if (text or '').strip().lower() in {'certo', 'sim', 'ok'} else False",
     CHANNEL),

    ("the operator channel goes back to its own", BOT,
     "    from openfactory.language import assent\n\n    return assent.asserts_assent(text)",
     "    return bool((text or '').strip())"),  # noqa: E501

    ("phrase-only words leak into the word tier — a queue is promoted the judge never saw",
     ASSENT,
     '"também", "tambem", "tá", "ta"),',
     '"também", "tambem", "tá", "ta", "mandar", "seguir", "bom"),',
     MONEY),

    ("`certo` is promoted back to asserting, on the surface that spends money", ASSENT,
     '    "pt-br": ("certo", "correto", "mesmo",', '    "pt-br": ("correto", "mesmo",'),

    ("…and the reverse: `certo` stops being allowed at all, so real confirmations break", ASSENT,
     '    "pt-br": ("certo", "correto", "mesmo", "registrar",',
     '    "pt-br": ("correto", "mesmo", "registrar",'),

    # ── the floor keeps its stricter bar ────────────────────────────────────────────────────────
    ("the floor drops to the channel's bar, so `sim, pode registrar` presses a MERGE", INTENTS,
     "    if not body or not assent.is_bare_assent(body):",
     "    if not body or not assent.asserts_assent(body):"),

    ("a whole-message phrase stops being an assent, so `pode seguir` presses nothing", ASSENT,
     "    return normalised in core_words() or normalised in core_phrases()",
     "    return normalised in core_words()"),
]
