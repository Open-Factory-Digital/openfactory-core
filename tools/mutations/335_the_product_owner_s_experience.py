"""The product owner's page is a chat with sessions, and the role knows what day it is (#335).

ROWS 1-9 ARE THE OWNER RULE. A session is `person:ana~k3f9a2`, and everywhere a private key was
compared with the caller's own it is its OWNER that is compared now. Each row undoes one side of
that: a suffix cut off whatever it is (so `person:ana~Bruno` is Ana's), a session id that is free
text, the page's refusal of an id it cannot mint ignored, the list of conversations listing
everybody's, a title taken from the last message instead of the first, the agenda read by the
session instead of its owner, a decision sealed by the session so the owner's panel never shows
it, a decision answered only in the exact session it was asked in, and the socket and the memory
compared by key instead of owner.

ROWS 10-15 ARE THE CLOCK. Days counted in UTC whatever the product's zone, every gap said as
"yesterday" (the defect the product owner saw), the engine not telling the module when the turn
is, the conversation's lines left without their time, the module dropping the time on its way to
the role, and the role's prompt without its `## When`.

ROWS 16-20 ARE THE PAGE: a session id reaching a click handler in any shape, a forged id in the
list painted, a link of any scheme, markdown built on unescaped text, and the subscribe frame
without its session (every "new conversation" is the first one again).
"""

TEST = "tests/test_a_person_has_more_than_one_conversation.py"
CLOCK_TEST = "tests/test_the_role_knows_what_day_it_is.py"
PAGE_TEST = "tests/test_the_product_owner_s_page.py"

CONVERSATION = "openfactory/product/conversation.py"
CHAT = "openfactory/api/product_chat.py"
CATALOG = "openfactory/actions/catalog.py"
AGENDA = "openfactory/product/agenda.py"
MODULE = "openfactory/product/module.py"
RECALL = "openfactory/memory/recall.py"
CLOCK = "openfactory/product/clock.py"
ENGINE = "openfactory/product/engine.py"
ROLE = "openfactory/product/role.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── the owner rule ─────────────────────────────────────────────────────────────────────────
    ("any suffix after the separator is cut off, so `person:ana~Bruno Silva` is Ana's",
     CONVERSATION,
     "    return base if base and _SESSION.match(session) else key",
     "    return base if base else key"),

    ("a session id is free text", CONVERSATION,
     "    if not is_private(own) or not _SESSION.match(session):",
     "    if not is_private(own):"),

    ("the page's refusal of a session it cannot mint is ignored", CHAT,
     "        if not named:\n            return \"\", \"that is not a conversation of yours",
     "        if False:\n            return \"\", \"that is not a conversation of yours"),

    ("the list of conversations lists everybody's private ones", CATALOG,
     "        if not own or not is_private(key) or owner_of(key) != own:\n            continue",
     "        if not is_private(key):\n            continue"),

    ("a conversation's title is whatever the store handed back first, not the first thing asked",
     CATALOG,
     '    for row in sorted(found, key=lambda r: str(r.get("ts", "") or "")):',
     "    for row in found:"),

    ("the agenda reads a turn's session instead of its owner", AGENDA,
     "    return bool(viewer.own) and _sealed(owner_of(viewer.own)) == where.conversation",
     "    return bool(viewer.own) and _sealed(viewer.own) == where.conversation"),

    ("a decision asked in a session is sealed by the session, so its owner's panel never shows it",
     MODULE,
     '    return {"asked_of": who, "asked_in": sealed(owner_of(conversation))}',
     '    return {"asked_of": who, "asked_in": sealed(conversation)}'),

    ("a decision is answered only in the exact session it was asked in", MODULE,
     '            and scope["asked_in"] in {sealed(owner_of(w)) for w in where if w})',
     '            and scope["asked_in"] in {sealed(w) for w in where if w})'),

    ("a session's frames never reach its owner: the socket compares keys, not owners", CHAT,
     "        return bool(sub.own) and owner_of(conversation) == sub.own\n",
     "        return bool(sub.own) and conversation == sub.own\n"),

    ("what a person said in one session never informs their others", RECALL,
     "            and (not is_private(h.said.where) or owner_of(h.said.where) == owner_of(own))]",
     "            and (not is_private(h.said.where) or h.said.where == own)]"),

    # ── the clock ──────────────────────────────────────────────────────────────────────────────
    ("days are counted in UTC whatever the product's zone", CLOCK,
     "    return (later.astimezone(zone).date() - earlier.astimezone(zone).date()).days",
     "    return (later.astimezone(UTC).date() - earlier.astimezone(UTC).date()).days",
     CLOCK_TEST),

    ("every gap is said as yesterday — the defect the product owner saw", CLOCK,
     "    if days == 1:\n        return \"yesterday\"",
     "    if days >= 1:\n        return \"yesterday\"",
     CLOCK_TEST),

    ("the engine never tells the module when the turn is", ENGINE,
     '                           **({"now": now} if _accepts(module.answer, "now") else {}),',
     "                           **({}),",
     CLOCK_TEST),

    ("the conversation's lines are handed to the model without their time", ENGINE,
     "        stamp=lambda ts: clock.stamp(ts, zone))",
     "        stamp=None)",
     CLOCK_TEST),

    ("the module drops the time on its way to the role", MODULE,
     '            **({"now": now} if now else {}),',
     "            **({}),",
     CLOCK_TEST),

    ("the role's prompt carries no `## When`", ROLE,
     '            + (f"{now}\\n\\n" if now else "")',
     '            + ""',
     CLOCK_TEST),

    # ── the page ───────────────────────────────────────────────────────────────────────────────
    ("a session id of any shape reaches a click handler", PANEL,
     '  return /^[a-z0-9]{4,24}$/.test(s)?s:"";',
     "  return s;",
     PAGE_TEST),

    ("a forged session id in the list is painted", PANEL,
     "  const rest=all.filter(x=>pvSid(x.session)&&(!q",
     "  const rest=all.filter(x=>x.session&&(!q",
     PAGE_TEST),

    ("a link of any scheme is rendered — `javascript:` included", PANEL,
     "(https?:\\/\\/[^\\s)]+)\\)/g,'<a href=",
     "([^\\s)]+)\\)/g,'<a href=",
     PAGE_TEST),

    ("markdown is built on the text as typed, not escaped", PANEL,
     "    let h=esc(t);",
     "    let h=String(t);",
     PAGE_TEST),

    ("the subscribe frame drops the session: every new conversation is the first one again", PANEL,
     "session:(!_pc.room&&_pc.session)?_pc.session:undefined",
     "session:undefined",
     PAGE_TEST),
]
