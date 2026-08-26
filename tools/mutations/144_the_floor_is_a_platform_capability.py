"""#144: the floor's answer belongs to the platform, not to one screen.

The first cuts restore the ladder's own defects, now in Python. The middle ones attack the API-first
property itself — a route that derives, a CLI that computes, a second definition of a word. The last
group goes the other way: a cheap call that becomes a lie, an unread input rendered as fine, a
census invented from a list nobody could read.

None of these could be written before this card. The ladder ran in a browser, so every claim about
it was a claim about a string in a file.
"""

TEST = "tests/test_the_floor_is_a_platform_capability.py"
LADDER = "openfactory/floor/ladder.py"
READING = "openfactory/floor/reading.py"
APP = "openfactory/api/app.py"
CLI = "openfactory/cli.py"
ARMED = "tests/test_a_disabled_project_does_not_look_armed.py"

MUTATIONS = [
    # ── the ladder's own rules ──────────────────────────────────────────────────────────────────
    ("a poller that stopped firing is called Armed again", LADDER,
     '    if ago > late:\n        return {"verdict": "late",',
     '    if False:\n        return {"verdict": "late",'),

    ("a poller with no next tick is called Armed", LADDER,
     '    if nxt is None or nxt <= 0 or ago > dead:', '    if ago > dead:'),

    ("an unreadable intake is treated as running", LADDER,
     '    if not intake or intake.get("known") is not True:',
     '    if not intake:'),

    ("a fresh deployment reads as broken for its first three minutes", LADDER,
     '        if intake.get("num_actions") == 0 and born is not None and born <= late \\\n'
     '                and nxt is not None and nxt > 0:\n'
     '            return {"verdict": "starting", "next_at": intake.get("next_at")}\n', ""),

    ("the late rule stops scaling with the schedule's own interval", LADDER,
     "    late = every * LATE_TICKS + TICK_GRACE_S", "    late = 360.0"),

    ("the project's own switch is masked by a healthy deployment schedule", LADDER,
     '        if p.get("enabled") is False:', '        if False:'),

    ("a park is promoted off the vendor string the engine refuses to obey", LADDER,
     '    wake = _parse(act.get("wakes_at"))', '    wake = _parse(act.get("retry_at"))'),

    ("the raw exception is put on the headline", LADDER,
     '                             "the engine did not answer, so this cannot say what the floor '
     'is "\n                             "doing", kind="unknown", detail=inputs.engine_error))',
     '                             "the engine did not answer: " + inputs.engine_error,\n'
     '                             kind="unknown"))'),

    ("a disagreeing build stops outranking everything", LADDER,
     '        out.append(Cause(1, "builds_disagree",',
     '        out.append(Cause(9, "builds_disagree",'),

    ("a paused review round takes the headline from Armed", LADDER,
     '            out.append(Cause(10, "watcher_dark",\n'
     '                             f"the {who} round is paused',
     '            out.append(Cause(4, "watcher_dark",\n'
     '                             f"the {who} round is paused'),

    ("one failure is reported as three", LADDER,
     "    rest = [c for c in found[1:] if c.cause not in DOWNSTREAM.get(win.cause, ())]",
     "    rest = list(found[1:])"),

    ("the cap eats a Stopped row", LADDER,
     "    pinned = [c for c in rest if c.pinned]\n"
     "    plain = [c for c in rest if not c.pinned]\n"
     "    also = pinned + plain[:ALSO_CAP]",
     "    also = rest[:ALSO_CAP]"),

    ("the census prints its empty buckets", LADDER,
     '    return " ".join(f"· {census[k]} {label[k]}" for k in order if census.get(k))',
     '    return " ".join(f"· {census[k]} {label[k]}" for k in order)'),

    ("a 503 from the inbox is read as 'nothing needs you'", LADDER,
     "    if inputs.inbox is not None:", "    if True:"),

    ("a census is invented from a list nobody could read", LADDER,
     "    if not project and inputs.projects is not None:", "    if not project:"),

    ("the per-project verdicts and the census stop coming from one walk", LADDER,
     "        per[name] = {\"word\": one.word, \"short\": one.short, \"level\": one.level,",
     "        per[name] = {\"word\": \"Armed\", \"short\": one.short, \"level\": one.level,"),

    # ── the API-first property itself ───────────────────────────────────────────────────────────
    ("the route derives its own answer again", APP,
     "    inputs = await floor.gather(want=floor.EVERYTHING)\n"
     "    return floor.state(inputs, project).as_dict()",
     '    return {"word": "Armed", "rung": 9, "clause": "looks fine", "line": "Armed",\n'
     '            "short": "Armed", "level": "ok", "cause": "armed", "scope": project,\n'
     '            "detail": "", "cmd": "", "meta": "", "actions": [], "also": [],\n'
     '            "also_more": 0, "census": None, "census_line": "", "per_project": None,\n'
     '            "ok": True}'),

    ("the CLI computes instead of asking", CLI,
     "    got = floor.state(asyncio.run(floor.gather(want=floor.EVERYTHING)), project)",
     '    got = type("X", (), {"line": "Armed", "meta": "", "detail": "", "cmd": "",\n'
     '                         "also": [], "also_more": 0, "census_line": "",\n'
     '                         "as_dict": lambda self: {}})()'),

    ("the web layer keeps its own set of attention states again", APP,
     "    from openfactory.runtime.temporal.view import ATTENTION_STATES\n\n"
     '    return [j for j in list_jobs() if j.get("state") in ATTENTION_STATES]',
     '    _ATTENTION = {"on_hold", "needs_refinement", "paused", "blocked", "failed"}\n'
     '    return [j for j in list_jobs() if j.get("state") in _ATTENTION]'),

    ("the wire shape is generated, so a private field widens somebody else's payload", LADDER,
     '        return {"scope": self.scope, "word": self.word,',
     '        from dataclasses import asdict\n\n        return {**asdict(self), "ok": self.ok,\n'
     '                "_x": {"scope": self.scope, "word": self.word,'),

    # ── the gathering half: a cheap call must not become a lie ──────────────────────────────────
    ("an unknown field is silently unread instead of refused", READING,
     "    if unknown:", "    if False:"),

    ("the poller's own rate floor is replaced by a second number", READING,
     "        return int(_RATE_FLOOR)", "        return 200"),

    ("an unread budget is cached, so a hiccup stays on screen for a minute", READING,
     '    if got.get("state") != "unread":\n        _budget_memo = (stamp, got)',
     "    _budget_memo = (stamp, got)"),

    ("an unreadable registry becomes an empty one, which is a claim", READING,
     '        log.warning("floor: could not read the project list (%s)", str(exc)[:160])\n'
     "        return None", "        return []"),

    # ── the guard file that used to own these claims still owns them ────────────────────────────
    ("an unknown pickup is reported as armed", LADDER,
     '        if p.get("enabled") is None:\n'
     '            unread.append(f"whether {name} takes cards")\n', "", ARMED),
]
