"""The verdict, read — for a model and for a person (#149).

PURE. No IO, no vendor, no Temporal: it is handed the dict the `verdict` query returns and says
what is in it. The shape is `{decision, score, summary, findings: [{severity, description, file}],
gates: [{name, passed, advisory}], suppressions: [kinds], stale?, gates_note?}`.
"""

from __future__ import annotations

#: The severities that stop a person rather than inform them.
BLOCKING = ("critical", "high")


def _bad(verdict: dict) -> list[dict]:
    findings = [f for f in (verdict.get("findings") or []) if isinstance(f, dict)]
    return [f for f in findings if str(f.get("severity", "")).lower() in BLOCKING]


#: How many unmet criteria a gate names before it starts counting them. The gate item is read on
#: a phone; the whole map belongs on the card.
_CRITERIA_SHOWN = 2


def criteria(verdict: dict) -> dict:
    """What the reviewer said about each acceptance criterion — `{passed, failed, unknown, unmet}`.

    THE REVIEWER HAS ALWAYS PRODUCED THIS AND NOTHING READ IT (#184). `ReviewResult.acceptance`
    is in the schema the model is asked to fill, it is parsed into a field, and a grep for
    `.acceptance` outside the contract and the adapter returned nothing: asked for, paid for in
    tokens, read by no one.

    WHAT IT COST, measured on the pilot. PR #118 was rejected at score 30. What a person saw was
    a decision, a score and four findings. What was also true: four of six criteria were
    delivered, both hard constraints held, and the change killed a false alarm that had fired on
    every panorama episode ever generated. Reconstructing that took four agents an evening. A
    rejection reads as "this is wrong"; the honest sentence was "this does most of what it
    promised — keep it and finish it", and only the per-criterion map can say which.

    `unknown` IS ITS OWN ANSWER and never folds into either side: a criterion the reviewer could
    not evaluate is not a criterion it passed, and it is not one it failed. Same Option-type rule
    the floor and `disabled_ci_paths` are built on.
    """
    checks = [c for c in (verdict.get("acceptance") or []) if isinstance(c, dict)]
    tally = {"passed": 0, "failed": 0, "unknown": 0}
    unmet: list[dict] = []
    for check in checks:
        status = str(check.get("status") or "unknown").lower()
        if status not in tally:
            status = "unknown"
        tally[status] += 1
        if status == "failed":
            unmet.append(check)
    return {**tally, "unmet": unmet, "total": len(checks)}


def _criteria_points(verdict: dict) -> list[str]:
    """The criteria clauses a gate shows, unmet ones first — or `[]` when there is no map."""
    tally = criteria(verdict)
    if not tally["total"]:
        return []
    out = [f"criterion NOT met: {str(c.get('criterion') or '?')[:160]}"
           for c in tally["unmet"][:_CRITERIA_SHOWN]]
    if len(tally["unmet"]) > _CRITERIA_SHOWN:
        out.append(f"…and {len(tally['unmet']) - _CRITERIA_SHOWN} more unmet")
    counted = ", ".join(f"{tally[k]} {k}" for k in ("passed", "failed", "unknown") if tally[k])
    out.append(f"acceptance criteria: {counted}")
    # A CONTRADICTION IS WORTH SAYING OUT LOUD rather than hiding behind whichever half the
    # reader happens to look at. "Rejected" while every criterion it mapped is met means the
    # reviewer refused on something the ticket never asked for — which may be right, and the
    # person deciding is the one who should weigh it, not the renderer.
    if not tally["failed"] and str(verdict.get("decision") or "").lower().startswith("reject"):
        out.append("every criterion it mapped is met, and it still rejected — the reason is in "
                   "the findings, not in the ticket")
    return out


def line(verdict: dict, *, unread: bool = False) -> str:
    """The dense one-liner the tech-lead reads. Every clause after an out-of-date warning is
    stamped `was:` — see `headline` for why that is in the shape rather than in the prose."""
    if unread:
        return "review: UNREADABLE (the engine did not answer — not 'unreviewed')"
    if not isinstance(verdict, dict) or not verdict:
        return ""
    parts: list[str] = []
    tally = criteria(verdict)

    if verdict.get("stale"):
        parts.append(f"review: OUT OF DATE — {verdict['stale']}, and nothing re-ran the reviewer. "
                     f"What follows judged the diff BEFORE that and describes code that is gone; "
                     f"it is not evidence about what is on the pull request now")
    if verdict.get("decision"):
        score = verdict.get("score")
        parts.append(f"review: {verdict['decision']}"
                     + (f" (score {score})" if score is not None else ""))
    # THE ROUND SAYS IT TOO (#184), and in its own register: the tech-lead's line is what reaches
    # a channel, where "rejected (30)" alone is the sentence that makes somebody discard a branch
    # that did four of six things. Named criteria, not a score.
    if tally["total"]:
        counted = ", ".join(f"{tally[k]} {k}" for k in ("passed", "failed", "unknown") if tally[k])
        clause = f"criteria: {counted}"
        if tally["unmet"]:
            clause += " — not met: " + "; ".join(
                str(c.get("criterion") or "?")[:120] for c in tally["unmet"][:2])
        parts.append(clause)
    gates = [g for g in (verdict.get("gates") or []) if isinstance(g, dict)]
    if not gates and verdict.get("gates_note"):
        parts.append(f"gates: not re-run — {verdict['gates_note']}")
    if gates:
        parts.append("gates: " + ", ".join(
            f"{g.get('name') or '?'} {'PASSED' if g.get('passed') else 'FAILED'}"
            + (" (advisory)" if g.get("advisory") else "") for g in gates))
    if verdict.get("suppressions"):
        parts.append("the diff ADDS gate-suppressions [" + ", ".join(verdict["suppressions"])
                     + "] — a human must confirm they are legitimate")
    bad = _bad(verdict)
    findings = [f for f in (verdict.get("findings") or []) if isinstance(f, dict)]
    if bad:
        parts.append("findings: " + "; ".join(
            f"{f.get('severity')}: {f.get('description', '')}"
            + (f" [{f['file']}]" if f.get("file") else "") for f in bad[:3]))
    elif findings:
        parts.append(f"{len(findings)} review finding(s), none high or critical")
    if verdict.get("summary") and not bad:
        parts.append(f"the reviewer said: {verdict['summary'][:200]}")
    if verdict.get("stale") and len(parts) > 1:
        parts = parts[:1] + [f"was: {p}" for p in parts[1:]]
    return " · ".join(parts)


def headline(verdict: dict | None, *, unread: bool = False) -> dict:
    """What somebody about to press Merge needs in one glance.

    `{level, word, clause, points: [...]}` — `level` is the panel's own vocabulary (`ok` / `warn`
    / `unknown`), so the card can be coloured without re-deciding anything.

    THE ABSENT CASE IS A LEVEL, NOT A BLANK. A gate with no verdict rendered exactly like a gate
    with a clean one, which is the defect this module exists for: "no review was run" and "the
    review approved it" are opposite facts and were the same pixels.

    `criteria` IS ON EVERY SHAPE OF THIS ANSWER (#184), including the absent ones — a caller that
    has to check whether the key is there is a caller that will forget, and the empty tally reads
    correctly as "this review mapped nothing".
    """
    tally = criteria(verdict if isinstance(verdict, dict) else {})

    if unread:
        return {"level": "unknown", "word": "Review unreadable",
                "clause": "the engine did not answer — this is not the same as unreviewed",
                "points": [], "criteria": tally}
    if not isinstance(verdict, dict) or not verdict:
        return {"level": "unknown", "word": "No review",
                "clause": "nothing reviewed this change — the gates are all there is",
                "points": [], "criteria": tally}

    # UNMET CRITERIA LEAD (#184). What the ticket ASKED FOR outranks what the reviewer noticed on
    # its own: a person at a gate decides whether the change does its job, and a finding is
    # evidence towards that question rather than the question itself.
    points: list[str] = list(_criteria_points(verdict))
    if verdict.get("suppressions"):
        points.append("the diff adds gate-suppressions ["
                      + ", ".join(verdict["suppressions"])
                      + "] — confirm they are legitimate")
    for f in _bad(verdict)[:3]:
        where = f" [{f['file']}]" if f.get("file") else ""
        points.append(f"{f.get('severity')}: {(f.get('description') or '')[:220]}{where}")
    failed = [g.get("name") or "?" for g in (verdict.get("gates") or [])
              if isinstance(g, dict) and not g.get("passed")]
    if failed:
        points.append("gates failed: " + ", ".join(failed))
    elif not verdict.get("gates") and verdict.get("gates_note"):
        points.append(f"the sandbox gates were not re-run — {verdict['gates_note']}")

    if verdict.get("stale"):
        # STALE OUTRANKS THE DECISION, because a decision about code that is gone is not one.
        return {"level": "unknown", "word": "Review out of date",
                "clause": f"{verdict['stale']}, and nothing re-ran the reviewer — what it found "
                          f"was about the diff before that",
                "points": [f"was: {p}" for p in points], "criteria": tally}

    decision = str(verdict.get("decision") or "").lower()
    score = verdict.get("score")
    scored = f" (score {score})" if score is not None else ""
    if decision in ("rejected", "reject", "changes_requested"):
        return {"level": "warn", "word": "Review rejected it",
                "clause": f"this platform's own reviewer rejected the change{scored}",
                "points": points, "criteria": tally}
    if points:
        return {"level": "warn", "word": "Review approved it, with flags",
                "clause": f"the reviewer approved the change{scored}, and left things a person "
                          f"should confirm",
                "points": points, "criteria": tally}
    if decision:
        return {"level": "ok", "word": "Review approved it",
                "clause": f"this platform's own reviewer read the whole diff and approved it"
                          f"{scored}",
                "points": [], "criteria": tally}
    return {"level": "unknown", "word": "No review",
            "clause": "nothing reviewed this change — the gates are all there is",
            "points": [], "criteria": tally}
