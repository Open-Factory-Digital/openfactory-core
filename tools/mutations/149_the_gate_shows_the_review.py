"""#149: the gate shows what this platform's own reviewer found.

The forwards restore the blank card the pilot decided on. The reverses matter as much: an absence
must not be painted as a clean bill, and a card that flags everything flags nothing.
"""

TEST = "tests/test_the_gate_shows_what_the_review_found.py"
VERDICT = "openfactory/review/verdict.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
CONV = "openfactory/techlead/conversation.py"

MUTATIONS = [
    # ── the card carries it at all ──────────────────────────────────────────────────────────────
    ("the gate item drops the review again — the original defect", APP,
     '                "review": review,\n', ""),

    ("the panel stops painting it", PANEL, "      ${reviewHtml(it.review)}\n", ""),

    ("a query that fails renders as `no review` — nothing checked your diff", APP,
     "        return verdict_read.headline(None, unread=True)",
     "        return verdict_read.headline(None)"),

    # ── an absence is not an approval ───────────────────────────────────────────────────────────
    ("no verdict is painted with the colour of a clean one", VERDICT,
     '''    if not isinstance(verdict, dict) or not verdict:
        return {"level": "unknown", "word": "No review",''',
     '''    if not isinstance(verdict, dict) or not verdict:
        return {"level": "ok", "word": "No review",'''),

    ("an unreadable review reads as an unreviewed one", VERDICT,
     '''        return {"level": "unknown", "word": "Review unreadable",''',
     '''        return {"level": "unknown", "word": "No review",'''),

    # ── the flags a person must confirm ─────────────────────────────────────────────────────────
    ("a gate-suppression stops being a flag on an approved change", VERDICT,
     '    if verdict.get("suppressions"):\n'
     '        points.append("the diff adds gate-suppressions [',
     '    if False:\n        points.append("the diff adds gate-suppressions ['),

    ("a failed gate is not named", VERDICT,
     '    if failed:\n        points.append("gates failed: " + ", ".join(failed))',
     "    if False:\n        pass"),

    ("gates that were never re-run are reported as nothing at all", VERDICT,
     '    elif not verdict.get("gates") and verdict.get("gates_note"):', "    elif False:"),

    ("…and the reverse: every finding is repeated, so the serious one stops standing out", VERDICT,
     '    return [f for f in findings if str(f.get("severity", "")).lower() in BLOCKING]',
     "    return findings"),

    # ── out of date outranks the decision ───────────────────────────────────────────────────────
    ("an approval of code that is gone colours the card green", VERDICT,
     '    if verdict.get("stale"):\n        # STALE OUTRANKS THE DECISION',
     "    if False:\n        # STALE OUTRANKS THE DECISION"),

    ("the points under an out-of-date verdict stop being stamped", VERDICT,
     '                "points": [f"was: {p}" for p in points]}',
     '                "points": points}'),

    # ── one definition ──────────────────────────────────────────────────────────────────────────
    ("the tech-lead goes back to picking the dict apart itself", CONV,
     "    from openfactory.review import verdict as verdict_read\n", ""),

    ("the page decides for itself what a score means", PANEL,
     '  const tone={ok:"b-ok",warn:"b-warn",unknown:"b-dim"}[r.level]||"b-dim";',
     '  const tone=(r.score!=null&&r.score<70)?"b-warn":"b-ok";  // rejected below 70'),
]
