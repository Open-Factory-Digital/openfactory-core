"""#184: the reviewer's per-criterion map reaches the gate and the round."""

TEST = "tests/test_the_acceptance_map_reaches_a_person.py"
V = "openfactory/review/verdict.py"

MUTATIONS = [
    ("the map stops reaching the gate at all", V,
     "    points: list[str] = list(_criteria_points(verdict))",
     "    points: list[str] = []"),

    ("…and the round's line loses it too", V,
     '        parts.append(clause)', "        pass"),

    ("the unmet criterion stops being NAMED, only counted", V,
     '    out = [f"criterion NOT met: {str(c.get(\'criterion\') or \'?\')[:160]}"\n'
     '           for c in tally["unmet"][:_CRITERIA_SHOWN]]',
     "    out = []"),

    ("findings lead again, so what the ticket asked for comes second", V,
     "    points: list[str] = list(_criteria_points(verdict))\n"
     "    if verdict.get(\"suppressions\"):",
     "    points: list[str] = []\n"
     "    if verdict.get(\"suppressions\"):"),

    ("`unknown` folds into passed", V,
     '        if status not in tally:\n            status = "unknown"',
     '        if status not in tally:\n            status = "passed"'),

    ("…and an invented status vanishes from the tally entirely", V,
     '        if status not in tally:\n            status = "unknown"\n        tally[status] += 1',
     '        if status not in tally:\n            continue\n        tally[status] += 1'),

    ("a review that mapped nothing starts adding a line about nothing", V,
     '    if not tally["total"]:\n        return []', "    if False:\n        return []"),

    ("the contradiction is swallowed", V,
     '    if not tally["failed"] and str(verdict.get("decision") or "").lower().startswith('
     '"reject"):', "    if False:"),

    ("the gate lists every unmet criterion, phone or not", V,
     "_CRITERIA_SHOWN = 2", "_CRITERIA_SHOWN = 99"),

    ("…and stops saying how many it left out", V,
     '    if len(tally["unmet"]) > _CRITERIA_SHOWN:\n'
     '        out.append(f"…and {len(tally[\'unmet\']) - _CRITERIA_SHOWN} more unmet")',
     "    pass"),

    ("a stale verdict presents its criteria as current", V,
     '                "points": [f"was: {p}" for p in points], "criteria": tally}',
     '                "points": points, "criteria": tally}'),

    ("`criteria` stops being on every shape of the answer", V,
     "    tally = criteria(verdict if isinstance(verdict, dict) else {})",
     "    tally = {}"),
]

WF = "openfactory/runtime/temporal/workflow.py"

MUTATIONS += [
    # ── the seam that actually broke it on the pilot ─────────────────────────────────────────────
    ("the verdict query drops the map again, so the gate renders nothing", WF,
     '            "acceptance": [{"criterion": (c.criterion or "")[:200], "status": c.status}\n'
     '                           for c in (getattr(review, "acceptance", None) or [])[:12]],\n',
     ""),

    ("…and it crosses the wire untrimmed", WF,
     '"criterion": (c.criterion or "")[:200]', '"criterion": (c.criterion or "")'),

    ("…and unbounded", WF,
     '(getattr(review, "acceptance", None) or [])[:12]',
     '(getattr(review, "acceptance", None) or [])'),

    ("the evidence prose is published on every panel refresh", WF,
     '{"criterion": (c.criterion or "")[:200], "status": c.status}',
     '{"criterion": (c.criterion or "")[:200], "status": c.status, "evidence": c.evidence}'),
]
