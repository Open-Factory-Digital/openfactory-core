"""#170: a proposal carries what to change, and a person sees it before pressing.

The highest-authority step in the plan, so the reverses are the important half: the widening must
admit exactly one row, the instruction must be visible, and nothing may be performed by the model.
"""

TEST = "tests/test_a_proposal_can_carry_what_to_change.py"
REASONS = "tests/test_the_techlead_can_see_what_it_reasons_about.py"
STAGED = "tests/test_a_staged_decision_survives_a_refresh.py"
ACTIONS = "openfactory/actions/__init__.py"
MESSAGES = "openfactory/memory/messages.py"
CATALOG = "openfactory/actions/catalog.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
CONV = "openfactory/techlead/conversation.py"

MUTATIONS = [
    # ── the widening, both directions ───────────────────────────────────────────────────────────
    ("`adjust` is dropped again — the role can propose discarding and not changing", ACTIONS,
     '_ADDRESSABLE = frozenset({"project", "issue", "instruction"})',
     '_ADDRESSABLE = frozenset({"project", "issue"})', REASONS),

    # NOT "the filter stops filtering" — inert against today's catalogue, since every typeable
    # row is addressable anyway. The claim that bites is what the widened set may NEVER admit.
    ("…and the reverse: a proposal may carry a secret, through a store and onto a button", ACTIONS,
     '_ADDRESSABLE = frozenset({"project", "issue", "instruction"})',
     '_ADDRESSABLE = frozenset({"project", "issue", "instruction", "password"})'),

    ("the asker's own credential stops filtering — a scoped one is offered floor rows", ACTIONS,
     "        if not by.may_enter(found.scope):\n            continue",
     "        if False:\n            continue"),

    ("the admin check stops filtering", ACTIONS,
     "        if found.needs_admin and not by.admin:\n            continue",
     "        if False:\n            continue"),

    ("the typed-grammar filter stops filtering — every catalogue row becomes proposable", ACTIONS,
     "        if name not in typeable:\n            continue",
     "        if False:\n            continue"),

    # ── the instruction survives ────────────────────────────────────────────────────────────────
    ("the staged payload stops carrying params — an approval that does nothing", MESSAGES,
     "            raw = body.get(\"params\")", "            raw = None"),

    ("a nested value reaches `perform(**params)` from the store", MESSAGES,
     '            params = ({k: v for k, v in raw.items() if isinstance(k, str) '
     'and isinstance(v, str)}\n                      if isinstance(raw, dict) else {})',
     "            params = raw if isinstance(raw, dict) else {}"),

    ("`run_staged` drops the instruction on the floor", CATALOG,
     "    outcome = await actions.perform(action, by=by, project=project, issue=ref, **params)",
     "    outcome = await actions.perform(action, by=by, project=project, issue=ref)"),

    ("the writer stages a proposal without the instruction it composed", CATALOG,
     '            payload = json.dumps({"suggestion": list(suggestion[:2]),\n'
     '                                  "params": dict(params or {})})',
     '            payload = json.dumps({"suggestion": list(suggestion[:2])})'),

    ("the endpoint stops serving them, so the panel cannot render what it does not have", APP,
     '        "params": proposal[2],\n', "", STAGED),

    # ── a person sees what they approve ─────────────────────────────────────────────────────────
    ("the button is painted without what it will do — a blank cheque", PANEL,
     '`<div class="opts">${detail}<button class="btn sm" data-act="approveSuggestion"',
     '`<div class="opts"><button class="btn sm" data-act="approveSuggestion"'),

    # ── the sweeper ─────────────────────────────────────────────────────────────────────────────
    ("a multi-line tag is posted to a human as raw plumbing", CONV,
     r'_ANY_TAG_RE = re.compile(r"\[\[(?:(?!\]\])[^\n]|\n(?!\n)){0,600}\]\]")',
     r'_ANY_TAG_RE = re.compile(r"\[\[(?:(?!\]\])[^\n])*\]\]")'),

    ("…and the reverse: the sweeper is unbounded and eats the answer between two tags", CONV,
     r'_ANY_TAG_RE = re.compile(r"\[\[(?:(?!\]\])[^\n]|\n(?!\n)){0,600}\]\]")',
     r'_ANY_TAG_RE = re.compile(r"\[\[[\s\S]*\]\]")'),
]
