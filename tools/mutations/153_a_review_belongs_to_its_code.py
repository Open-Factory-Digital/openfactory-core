"""#153: a verdict about a rewritten diff is not evidence, and a decision said politely is one.

Both measured on the pilot in the same minute: he typed `pode dar o merge`, it fell through as
conversation, and what came back quoted a two-hour-old rejection and offered to discard the work
that had answered it.
"""

TEST = "tests/test_a_review_belongs_to_the_code_it_read.py"
INTENTS_TEST = "tests/test_a_typed_instruction_reaches_the_same_row_as_the_button.py"
CONV = "openfactory/techlead/conversation.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
INTENTS = "openfactory/actions/floor_intents.py"

MUTATIONS = [
    # ── the verdict outliving its code ──────────────────────────────────────────────────────────
    ("a rewritten diff leaves the verdict standing — the original defect", CONV,
     '    if v.get("stale"):', "    if False:"),

    ("the caveat moves BELOW the rejection, where a reader who stops early never meets it", CONV,
     '''    if v.get("stale"):
        parts.append(f"review: OUT OF DATE — {v['stale']}, and nothing re-ran the reviewer. What "
                     f"follows judged the diff BEFORE that and describes code that is gone; it is "
                     f"not evidence about what is on the pull request now")
    if v.get("decision"):
        score = v.get("score")
        parts.append(f"review: {v['decision']}"
                     + (f" (score {score})" if score is not None else ""))''',
     '''    if v.get("decision"):
        score = v.get("score")
        parts.append(f"review: {v['decision']}"
                     + (f" (score {score})" if score is not None else ""))
    if v.get("stale"):
        parts.append(f"review: OUT OF DATE — {v['stale']}, and nothing re-ran the reviewer. What "
                     f"follows judged the diff BEFORE that and describes code that is gone; it is "
                     f"not evidence about what is on the pull request now")'''),

    ("…and the reverse: a FRESH verdict starts hedging, so a good review stops being evidence",
     CONV, '    if v.get("stale"):', "    if True:"),

    ("the caveat deletes the findings instead of dating them", CONV,
     '''    if v.get("decision"):
        score = v.get("score")''',
     '''    if v.get("stale"):
        return " · ".join(parts)
    if v.get("decision"):
        score = v.get("score")'''),

    ("the tech-lead is no longer told what an out-of-date review may not be used for", CONV,
     '"\'review: OUT OF DATE\' means the diff was REWRITTEN after the reviewer read it, '
     'and EVERY "', '"" '),

    # ── the engine marking it ───────────────────────────────────────────────────────────────────
    ("an adjust pass rewrites the pull request and says nothing about the review", WORKFLOW,
     '        self._the_reviewed_code_is_gone(f"{who} asked for a change and a pass rewrote the '
     'pull "\n                                        f"request")\n', ""),

    ("a CI-repair pass rewrites it and says nothing", WORKFLOW,
     '                self._the_reviewed_code_is_gone(\n'
     '                    f"a CI-repair pass rewrote the pull request (attempt {attempts})")\n',
     ""),

    ("the mark lands AFTER the push, so a worker that dies between leaves a confident verdict",
     WORKFLOW,
     '        self._the_reviewed_code_is_gone(f"{who} asked for a change and a pass rewrote the '
     'pull "\n                                        f"request")\n'
     '        await workflow.execute_activity(\n            adjust_pr,',
     '        await workflow.execute_activity(\n            adjust_pr,'),

    ("marking invents a verdict where the review never ran", WORKFLOW,
     "        if self._verdict:\n            self._verdict = {**self._verdict, \"stale\": why}",
     "        self._verdict = {**(self._verdict or {}), \"stale\": why}"),

    # ── the decision said politely ──────────────────────────────────────────────────────────────
    ("the polite verb list narrows back to `fazer` — the pilot's own sentence", INTENTS,
     r"(?:pode|podes|poderia)\s+(?:fazer|dar|mandar|subir|integrar)?\s*(?:o\s+)?merge",
     r"(?:pode|podes|poderia)\s+(?:fazer\s+)?(?:o\s+)?merge", INTENTS_TEST),

    ("the bare verb keeps its own narrower politeness prefix again", INTENTS,
     '        r"^\\s*" + _LEAD + r"merge(?:ia|ar|a)?" + _REF + r"\\s*[.!]?\\s*$", re.I)),',
     '        r"^\\s*(?:ok[,.!]?\\s*)?merge(?:ia|ar|a)?" + _REF + r"\\s*[.!]?\\s*$", re.I)),',
     INTENTS_TEST),

    ("…and the reverse: no politeness is allowed at all, so the button's own word stops working",
     INTENTS, r'_LEAD = rf"(?:(?:{_LEADER_WORDS})\b[,.!]?\s*)*"', '_LEAD = ""', INTENTS_TEST),

    # THE CUT THAT HUNG PYTEST FOR TWELVE MINUTES, kept as a mutation because that is exactly what
    # it proves: the leader loop with `\s*` at both ends walks 2^n paths before reporting failure,
    # and the termination guard is the only thing in the suite that can see it.
    ("the leader loop becomes ambiguous again — 2^n paths on a web-facing text path", INTENTS,
     r'_LEAD = rf"(?:(?:{_LEADER_WORDS})\b[,.!]?\s*)*"',
     r'_LEAD = rf"(?:\s*(?:{_LEADER_WORDS})\b[,.!]?\s*)*"', INTENTS_TEST),
    # ── #154: the caveat in the SHAPE, not only in the prose ────────────────────────────────────
    ("the stale sub-facts stop being stamped — the tech-lead reads them as current", CONV,
     '    if v.get("stale") and len(parts) > 1:', "    if False:"),

    ("…and the reverse: a FRESH verdict arrives in the past tense", CONV,
     '    if v.get("stale") and len(parts) > 1:', "    if len(parts) > 1:"),

    ("the caveat itself gets stamped, so the warning reads as something that WAS true", CONV,
     '        parts = parts[:1] + [f"was: {p}" for p in parts[1:]]',
     '        parts = [f"was: {p}" for p in parts]'),

    ("the tech-lead may send people after a re-review the platform cannot do", CONV,
     '"- NEVER SEND SOMEBODY TO ASK FOR SOMETHING THIS PLATFORM CANNOT DO. Nothing here re-runs '
     'the "', '"" '),
]
