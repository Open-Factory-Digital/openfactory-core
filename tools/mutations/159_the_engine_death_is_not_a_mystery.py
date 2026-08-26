"""#159: a worker dying under a job self-heals, the dictated reply executes, no channel is named.

The reverses carry the replay safety: an in-flight job parked under the old verdict must keep
replaying the old verdict, or the fix wedges the exact job it was written about.
"""

TEST = "tests/test_the_engine_dying_under_a_job_is_not_a_mystery.py"
CLASSIFY = "openfactory/techlead/classify.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
DECISION = "openfactory/contracts/decision.py"
INTENTS = "openfactory/actions/floor_intents.py"
CATALOG = "openfactory/actions/catalog.py"

MUTATIONS = [
    # ── the class is known ──────────────────────────────────────────────────────────────────────
    ("the engine death goes back to being a mystery — the original defect", CLASSIFY,
     "    if engine and _ENGINE_RE.search(text):", "    if False:"),

    ("the rule narrows to one wording, so the heartbeat shape stays unknown", CLASSIFY,
     '_ENGINE_RE = re.compile(r"activity task timed out|heartbeat timed? ?out", re.I)',
     '_ENGINE_RE = re.compile(r"activity task timed out", re.I)'),

    # ── replay safety ───────────────────────────────────────────────────────────────────────────
    ("the gate is ignored, so a replayed park computes a new verdict (TMPRL1100)", CLASSIFY,
     "def classify(note: str, *, state: str = \"\", engine: bool = True) -> Verdict:",
     "def classify(note: str, *, state: str = \"\", engine: bool = True) -> Verdict:\n"
     "    engine = True"),

    ("the workflow stops passing patched(), so every in-flight park replays the new rule",
     WORKFLOW,
     'engine=workflow.patched("classify-engine-interrupted"))',
     "engine=True)"),

    # ── the dictated reply executes ─────────────────────────────────────────────────────────────
    ("`resume #NN` stops being an intent — the platform dictates it and cannot run it", INTENTS,
     '    ("resume", re.compile(\n'
     '        r"(?<![\\w-])(?:resume|retom[ae]|retomar)\\s+(?:o\\s+|a\\s+|the\\s+)?"\n'
     '        r"(?:job\\s+|ticket\\s+|card\\s+)?" + _REF_REQUIRED,\n'
     "        re.I)),\n", ""),

    ("the ref stops being required, so a bare noun acts on a parked job", INTENTS,
     '        r"(?<![\\w-])(?:skip|pul[ae]|pular)\\s+(?:o\\s+|a\\s+|the\\s+)?"\n'
     '        r"(?:job\\s+|ticket\\s+|card\\s+)?" + _REF_REQUIRED,',
     '        r"(?<![\\w-])(?:skip|pul[ae]|pular)\\s*(?:o\\s+|a\\s+|the\\s+)?"\n'
     '        r"(?:job\\s+|ticket\\s+|card\\s+)?" + _REF,'),

    ("the branch performs `stop` whatever word was typed", CATALOG,
     "        outcome = await actions.perform(FLOOR_ROWS[intent], by=by, project=project, "
     "issue=ref)",
     '        outcome = await actions.perform("stop", by=by, project=project, issue=ref)'),

    # ── no channel is named ─────────────────────────────────────────────────────────────────────
    ("the ticket sends the reader to one vendor's channel again", DECISION,
     '        parts.append(f"**To resolve.** Reply `{ho.suggested_command}` — the tech-lead '
     'executes "\n                     "it (gated + watched). The button on the panel does the '
     'same.")',
     '        parts.append(f"**To resolve.** Reply `{ho.suggested_command}` in Slack — the '
     'tech-lead "\n                     "executes it (gated + watched); no need to touch the '
     'panel.")'),

    ("the plain scaffold goes back to hardcoded Portuguese", DECISION,
     '        parts.append(f"→ *To resolve, reply:* `{ho.suggested_command}` — I execute it "\n'
     '                     "(gated + watched); the panel\'s button does the same.")',
     '        parts.append(f"→ *Pra eu resolver, me diga:* `{ho.suggested_command}`")'),
]
