"""#164: one answer per question, across the floor, the inbox, the panel and the scheduler."""

TEST = "tests/test_the_floor_and_the_inbox_agree.py"
LADDER = "openfactory/floor/ladder.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
SCHED = "openfactory/scheduler.py"
ACT = "openfactory/runtime/temporal/activities.py"

MUTATIONS = [
    # ── whose problem is a machine-owned wait ───────────────────────────────────────────────────
    ("a fresh rate park is announced as a person's again", LADDER,
     "                 and not _machine_still_owns(j, now)]", "                 ]"),

    ("…and the reverse: a park PAST its wake-up is swallowed too", LADDER,
     "    return not wait_is_over(act.get(\"wakes_at\"), kind, now)", "    return True"),

    ("a wedged job counts as machine-owned", LADDER,
     '    if job.get("wedged") is True:\n        return False', "    pass"),

    ("an unarmed merge gate is swallowed — the floor cannot read who is needed", LADDER,
     '    if kind == "merge_wait" and not act.get("auto"):\n        return False', "    pass"),

    # ── one vocabulary ──────────────────────────────────────────────────────────────────────────
    ("the floor forgets `rate_limit` again", LADDER,
     '    if state == "paused" or act.get("kind") == "rate_limit":\n        return "rate_limit"',
     "    pass"),

    ("…and `wedged` outranks a decision again, as the two orders disagreed", LADDER,
     '    if act.get("decision"):\n        return "decision"',
     '    if job.get("wedged"):\n        return "wedged"\n'
     '    if act.get("decision"):\n        return "decision"'),

    ("the inbox writes its own word for a rate park", APP,
     '            out.append({**base, "kind": kind, "answer": {"method": "POST", "url": act_url,',
     '            out.append({**base, "kind": "rate_limit", "answer": {"method": "POST", '
     '"url": act_url,'),

    # ── the page stops keeping copies ───────────────────────────────────────────────────────────
    ("the attention states are hand-listed in the page again", PANEL,
     "const ALARM=new Set(VOCAB.alarm);",
     'const ALARM=new Set(["failed","needs_refinement","on_hold","blocked",'
     '"awaiting_your_merge"]);'),

    ("the rate floor is a hand copy again", PANEL,
     "const _RATE_FLOOR=VOCAB.rate_floor;   // the poller's own threshold (#164), not a copy of it",
     "const _RATE_FLOOR=200;"),

    ("the engine's merge sentence is copied into the page again", PANEL,
     "  merging:`Auto-merge armed — ${VOCAB.merge_wait.auto}`,",
     '  merging:"Auto-merge armed — waiting for CI / the merge",'),

    ("the page is served with its vocabulary unresolved", APP,
     '    return page.replace("__VOCABULARY__", json.dumps(_panel_vocabulary(), '
     "ensure_ascii=False))", "    return page"),

    ("the served vocabulary drops a state the engine names", APP,
     '        "alarm": sorted(ATTENTION_STATES),',
     '        "alarm": sorted(ATTENTION_STATES - {"paused"}),'),

    # ── the vendor's claim, and the rule with one home ──────────────────────────────────────────
    ("the resume sweep obeys the vendor's `retry_at` again", SCHED,
     '    return (_iso_epoch(paused_ts) or 0.0) + backoff_s',
     "    base = _iso_epoch(paused_ts) or 0.0\n    r = _iso_epoch(retry_at)\n"
     "    return r if (r and r > base) else base + backoff_s"),

    ("the tech-lead's round re-derives the wedged rule", ACT,
     '            if tv_view.is_wedged({"action": None, "start_time": wf.start_time}, live=True):',
     "            if hours_running >= LONG_RUNNING_HOURS:"),
]
