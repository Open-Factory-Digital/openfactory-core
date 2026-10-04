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
    verified = 0
    would_verify: list[str] = []
    for check in checks:
        status = str(check.get("status") or "unknown").lower()
        if status not in tally:
            status = "unknown"
        tally[status] += 1
        if status == "failed":
            unmet.append(check)
        # EXECUTED, NOT CLAIMED (#447): `executed_by` is the platform's, set only when the gate
        # the reviewer cited ran and passed (`review/evidence.py`)
        if status == "passed" and str(check.get("executed_by") or "").strip():
            verified += 1
        pointer = str(check.get("would_verify") or "").strip()
        if pointer and pointer not in would_verify:
            would_verify.append(pointer)
    return {**tally, "unmet": unmet, "total": len(checks),
            "checked": bool(verdict.get("evidence_checked")), "verified": verified,
            "unverified": len(checks) - verified - tally["failed"],
            "would_verify": would_verify}


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
        if tally["checked"]:
            # WHAT A GATE EXECUTED, beside what the reviewer claimed (#447)
            clause += f" ({tally['verified']} of {tally['total']} executed by a gate)"
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


#: WHAT THE REVIEW SAID, AS ONE WORD A SENTENCE IN ANOTHER LANGUAGE CAN BE CHOSEN BY (#401).
#: `level` colours a card and cannot tell a rejection from an approval with flags (both `warn`);
#: `word` is English prose. The product role tells the requester what the review said in their own
#: language, and choosing its sentence by matching `word` — or by re-reading `decision` against a
#: second copy of the rejected spellings — is how two surfaces come to describe one verdict
#: differently. So `headline` says it once, on every shape of its answer: approved, approved with
#: flags, rejected, or not read (absent, unreadable, or about code that is gone).
APPROVED, FLAGGED, REJECTED, UNREAD = "approved", "flagged", "rejected", "unread"
#: THE STANCE THE REVIEWER'S OWN WORD COULD NOT EXPRESS (#447): it approved, and nothing executed
#: what the card asked for. Computed from the evidence, and never read as an approval anywhere —
#: not on the card, not in the requester's message, not by the merge policy.
NOT_VERIFIED = "not_verified"


def not_verified(verdict: dict | None) -> bool:
    """Whether `verdict` says the change was not verified: the platform checked the evidence
    (`evidence_checked`), nothing failed, and at least one acceptance criterion — or all of them,
    when the review mapped none — passed on no executed evidence. False on a verdict the platform
    never checked, which keeps every verdict written before #447 reading as it did."""
    tally = criteria(verdict) if isinstance(verdict, dict) else criteria({})
    if not tally["checked"] or tally["failed"]:
        return False
    return tally["total"] == 0 or tally["unverified"] > 0


def still_admits_the_merge(verdict: dict | None, *, judged: str = "") -> bool:
    """Whether the reading standing NOW still admits a merge nobody presses (#448 slice 3).

    THE MACHINE JUDGED THE FIRST READING, AND A PASS MAY HAVE REPLACED IT. `should_auto_merge`
    decided "the look is the only hold" when the pull request opened, on that review (`judged`, its
    decision). A pass the requester asked for since rewrote the change and handed back its own
    reading, which nothing re-judged — so the factory merging on their acceptance must not ride
    over what that reading says:

        stale        a pass pushed and no reviewer read what it pushed
        not verified nothing executed what the card asks for (#447) — `should_auto_merge` refuses
                     it in any review mode
        rejected     the reviewer now rejects a change it did not reject when the machine judged
                     it. In advisory mode a rejection never held the first judgement, so one that
                     was rejected then is not a new hold now

    PURE, on the shape the `verdict` query returns: the workflow asks it while it builds its merge
    wait, which is state, never a command. No verdict at all is a project that runs no review, and
    `should_auto_merge` already admitted that."""
    v = verdict if isinstance(verdict, dict) else {}
    if v.get("stale") or not_verified(v):
        return False
    return v.get("decision") != "rejected" or judged == "rejected"


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
        return {"level": "unknown", "stance": UNREAD, "word": "Review unreadable",
                "clause": "the engine did not answer — this is not the same as unreviewed",
                "points": [], "criteria": tally}
    if not isinstance(verdict, dict) or not verdict:
        return {"level": "unknown", "stance": UNREAD, "word": "No review",
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
        return {"level": "unknown", "stance": UNREAD, "word": "Review out of date",
                "clause": f"{verdict['stale']}, and nothing re-ran the reviewer — what it found "
                          f"was about the diff before that",
                "points": [f"was: {p}" for p in points], "criteria": tally}

    decision = str(verdict.get("decision") or "").lower()
    score = verdict.get("score")
    scored = f" (score {score})" if score is not None else ""
    if decision in ("rejected", "reject", "changes_requested"):
        return {"level": "warn", "stance": REJECTED, "word": "Review rejected it",
                "clause": f"this platform's own reviewer rejected the change{scored}",
                "points": points, "criteria": tally}
    # THE STANCE IS COMPUTED FROM THE EVIDENCE WHEN THE PLATFORM CHECKED IT (#447), the way a
    # card's verdict is (ADR-0054): the reviewer's decision word said "approved" over its own
    # caveat that nothing had executed the criteria, and the requester was told it was approved.
    if tally["checked"] and tally["failed"]:
        return {"level": "warn", "stance": REJECTED, "word": "Review rejected it",
                "clause": f"{tally['failed']} of {tally['total']} acceptance criteria are not "
                          f"met{scored}",
                "points": points, "criteria": tally}
    if not_verified(verdict):
        pointers = [f"wire `{p[:120]}` into a gate (`validate`) and the platform can verify "
                    f"this kind of change" for p in tally["would_verify"][:2]]
        if tally["total"]:
            clause = (f"{tally['unverified']} of {tally['total']} acceptance criteria were "
                      f"checked only by reading the code — nothing executed them{scored}")
        else:
            clause = (f"the review mapped no acceptance criterion to evidence — nothing executed "
                      f"what the card asked for{scored}")
        return {"level": "warn", "stance": NOT_VERIFIED, "word": "Review could not verify it",
                "clause": clause, "points": pointers + points, "criteria": tally}
    if points:
        return {"level": "warn", "stance": FLAGGED, "word": "Review approved it, with flags",
                "clause": f"the reviewer approved the change{scored}, and left things a person "
                          f"should confirm",
                "points": points, "criteria": tally}
    if decision:
        return {"level": "ok", "stance": APPROVED, "word": "Review approved it",
                "clause": f"this platform's own reviewer read the whole diff and approved it"
                          f"{scored}",
                "points": [], "criteria": tally}
    return {"level": "unknown", "stance": UNREAD, "word": "No review",
            "clause": "nothing reviewed this change — the gates are all there is",
            "points": [], "criteria": tally}


def of_result(result) -> dict | None:
    """The verdict a job's result carries, in the shape this module reads (see the module) — `None`
    when nothing was measured, which says nothing rather than an empty verdict.

    ONE PROJECTION FOR EVERY READER (#414): the workflow keeps it for the `verdict` query
    (`JobWorkflow._remember_verdict`), and the worker that applies a pull request the box handed
    back tells its requester the review's word from it (`lifecycle/handed_back.py`). Two hand-listed
    copies would come to disagree, and the requester would hear a stance the gate does not show.

    TRIMMED HERE, not by the reader: a query response crosses the wire on every panel refresh that
    asks for it, and a reviewer's `summary` plus a dozen findings is prose measured in kilobytes.
    PURE, like the rest of this module — no command, so the workflow replays it unchanged."""
    review = getattr(result, "review", None)
    gates = [{"name": v.name, "passed": bool(v.passed), "advisory": bool(v.advisory)}
             for v in (result.validations or [])]
    # SUPPRESSIONS TRAVEL AS THEIR KINDS. They are the single commonest reason a green PR is
    # handed to a person (`_why` says so in as many words), so a merge gate that did not
    # mention them would be answering the question with the one fact left out.
    kinds = sorted({str(k) for k in (result.added_suppressions or [])})
    if review is None and not gates and not kinds:
        return None
    return {
        "decision": getattr(review, "decision", "") or "",
        "score": getattr(review, "score", None),
        "summary": (getattr(review, "summary", "") or "")[:600],
        "findings": [{"severity": f.severity, "description": (f.description or "")[:300],
                      "file": f.file or ""}
                     for f in (getattr(review, "findings", None) or [])[:8]],
        "gates": gates,
        "suppressions": kinds,
        # WHAT THE REVIEWER SAID ABOUT EACH CRITERION (#184). This projection is hand-listed,
        # and the field was simply never added to it — so the map reached the tech-lead's
        # channel, which reads the whole `ReviewResult`, and died at the merge gate, which
        # reads this query. #184 taught the renderer to show it and the data never arrived:
        # the fix worked on one surface and was invisible on the one where somebody decides.
        #
        # TRIMMED LIKE ITS NEIGHBOURS, for the reason the docstring above gives — this crosses
        # the wire on every panel refresh. The criterion text is what identifies it to a
        # reader; the evidence is prose and belongs to the closed job's result.
        #
        # AND WHAT EXECUTED IT (#447): `executed_by` is the gate the platform confirmed ran the
        # evidence, `would_verify` the check no gate runs, `evidence_checked` whether the
        # platform looked at all — the three the stance is computed from. Fields, not a
        # command: replay-safe, as the docstring says.
        "acceptance": [{"criterion": (c.criterion or "")[:200], "status": c.status,
                        "executed_by": getattr(c, "executed_by", None) or "",
                        "would_verify": (getattr(c, "would_verify", None) or "")[:160]}
                       for c in (getattr(review, "acceptance", None) or [])[:12]],
        "evidence_checked": bool(getattr(review, "evidence_checked", False)),
    }
