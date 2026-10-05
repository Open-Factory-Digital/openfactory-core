"""A change whose acceptance criteria nothing executed is not announced as approved (#447)."""

TEST = "tests/test_a_change_nothing_executed_is_not_approved.py"
EVIDENCE = "openfactory/review/evidence.py"
VERDICT = "openfactory/review/verdict.py"
POLICY = "openfactory/orchestrator/merge_policy.py"
MACHINE = "openfactory/orchestrator/machine.py"
VOICE = "openfactory/product/voice.py"
HARNESS = "openfactory/adapters/reviewer/harness.py"

MUTATIONS = [
    # ── the platform decides what executed ─────────────────────────────────────────────────────
    ("the reviewer's own `executed_by` is trusted", EVIDENCE,
     "        name = next((passed[g] for g in cited(check.evidence) if g in passed), None)\n",
     "        name = check.executed_by or next((passed[g] for g in cited(check.evidence)\n"
     "                                          if g in passed), None)\n"),
    ("a gate that failed counts as having executed the evidence", EVIDENCE,
     "              if v.passed and not v.unrunnable}\n",
     "              if not v.unrunnable}\n"),
    ("a bare gate name in prose counts as a citation", EVIDENCE,
     'CITATION = re.compile(r"\\bgate:\\s*`?([A-Za-z0-9_.\\-]+)`?", re.IGNORECASE)\n',
     'CITATION = re.compile(r"\\b(?:gate:\\s*)?`?([A-Za-z0-9_.\\-]+)`?", re.IGNORECASE)\n'),
    ("a passed criterion counts as verified whatever executed it", VERDICT,
     '        if status == "passed" and str(check.get("executed_by") or "").strip():\n',
     '        if status == "passed":\n'),
    # ── the stance is computed ─────────────────────────────────────────────────────────────────
    ("the reviewer's decision word decides again", VERDICT,
     "    if not_verified(verdict):\n",
     "    if False:\n"),
    ("a failed criterion under an approval stays an approval", VERDICT,
     '    if tally["checked"] and tally["failed"]:\n',
     "    if False:\n"),
    ("a review that mapped no criterion counts as verified", VERDICT,
     '    return tally["total"] == 0 or tally["unverified"] > 0\n',
     '    return tally["unverified"] > 0\n'),
    ("a verdict made before the check is judged by data it never carried", VERDICT,
     '    if not tally["checked"] or tally["failed"]:\n',
     '    if tally["failed"]:\n'),
    # ── every surface ──────────────────────────────────────────────────────────────────────────
    ("a change nobody verified merges by itself", POLICY,
     "    if result.review is not None and _not_verified(result.review):\n",
     "    if False:\n"),
    ("a review bypasses the evidence check", MACHINE,
     "        return settle(review, review_input.validations)\n",
     "        return review\n"),
    ("the pull request heads with the reviewer's word over no evidence", MACHINE,
     "        unverified = not unread and _verdict.not_verified(r.model_dump())\n",
     "        unverified = False\n"),
    ("the requester has no sentence for an unverified change", VOICE,
     '    "not_verified": {"pt-BR": " — a revisão automática não conseguiu verificar: nada '
     'executou o "\n',
     '    "_not_verified": {"pt-BR": " — a revisão automática não conseguiu verificar: nada '
     'executou o "\n'),
    # re-pinned 2026-10-04: the verdict query's projection is `verdict.of_result` (#414)
    ("the verdict query drops whether the evidence was checked", VERDICT,
     '        "evidence_checked": bool(getattr(review, "evidence_checked", False)),\n',
     '        "evidence_checked": False,\n'),
    ("the reviewer is never told how to cite a gate", HARNESS,
     '        _INSTRUCTIONS + " " + EVIDENCE_RULE,\n',
     "        _INSTRUCTIONS,\n"),
]
