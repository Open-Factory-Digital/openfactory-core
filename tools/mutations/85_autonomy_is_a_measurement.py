"""Autonomy is a measurement read from the card's record (#85, hole 4), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py tools/mutations/85_autonomy_is_a_measurement.py

The claims, each cut below:

  · a repair-role pass costs a card its first try — every one of the five roles;
  · `parked`, `resumed` and `adjusted` between the promotion and the merge are somebody stepping
    in, and nothing else is: not a designed gate (`question_asked`), not what follows the merge;
  · a card whose record does not hold its promotion before its merge is BEFORE THE RECORD, named
    and never in a rate — and a merge only a job's row holds is named there too;
  · an effect's outcome row is never read as a transition;
  · with nothing measured the yield is `None`, never 0;
  · a park nobody can classify is `unknown`, never `transient`;
  · the planner's passes are not rework;
  · a ref that is not a number joins its passes to its record;
  · the window holds the cards merged in it;
  · the sentences arrive in the project's language — from the reading, the route and the CLI;
  · a store that will not answer is said as that — the CLI exits 2, the dashboard's block says
    it — never read as a record with nothing in it.

Every claim is measured over a real SQLite store with rows the real writers wrote.
"""

TEST = "tests/test_autonomy_is_read_from_the_record.py"

AUTONOMY = "openfactory/observability/autonomy.py"
RECORD = "openfactory/lifecycle/record.py"
VIEW = "openfactory/api/metrics_view.py"
APP = "openfactory/api/app.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    # ── what costs a card its first try ─────────────────────────────────────────────────────────
    ("a red CI's repair pass is not a repair, so B lands as if nothing had been redone", AUTONOMY,
     '"review_repair", "ci_repair",', '"review_repair",'),

    ("a park is not somebody stepping in", AUTONOMY,
     'INTERVENTIONS = frozenset({"parked", "resumed", "adjusted"})',
     'INTERVENTIONS = frozenset({"resumed", "adjusted"})'),

    ("a question the design asks is counted as a rescue", AUTONOMY,
     'INTERVENTIONS = frozenset({"parked", "resumed", "adjusted"})',
     'INTERVENTIONS = frozenset({"parked", "resumed", "adjusted", "question_asked"})'),

    ("a park after the merge is read as one on the road to it", AUTONOMY,
     "                         if promoted < r.seq < merged.seq)",
     "                         if promoted < r.seq)"),

    # ── which cards are measured ────────────────────────────────────────────────────────────────
    ("THE DEFECT: a card whose promotion the record does not hold is measured anyway", AUTONOMY,
     "        if promoted is None:\n            before.append(card)\n            continue",
     "        if promoted is None:\n            promoted = 0"),

    # RE-PINNED 2026-10-10 (reviews of #545 and #554): the states past the merge are the machine's
    # own, read off `JobState` from MERGED to DONE in `contracts/state.py`, not a copy here
    ("a merge only the job's row holds at Done is forgotten instead of named",
     "openfactory/contracts/state.py",
     "_ORDER[_ORDER.index(JobState.MERGED):_ORDER.index(JobState.DONE) + 1])",
     "_ORDER[_ORDER.index(JobState.MERGED):_ORDER.index(JobState.DONE)])"),

    ("an effect's outcome row is parsed as the transition it belongs to", RECORD,
     "        if len(parts) == 1:\n", "        if len(parts) in (1, 4):\n"),

    ("the window is ignored, so a card merged in August is counted for this week", AUTONOMY,
     "        if merged is None or not _within(merged.ts, start):",
     "        if merged is None:"),

    ("the passes join their card through its number, so DAR-12's repairs are nobody's", AUTONOMY,
     '        ticket = canonical_ref(row.get("ticket"))',
     '        ticket = str(__import__("openfactory.contracts.refs", fromlist=["ref_number"])'
     '.ref_number(row.get("ticket")) or "")'),

    # ── the numbers ─────────────────────────────────────────────────────────────────────────────
    ("nothing measured reads as every card failed", AUTONOMY,
     '"yield": round(clean / n, 4) if n else None,',
     '"yield": round(clean / n, 4) if n else 0.0,'),

    ("the planner's passes count as rework", AUTONOMY,
     "WRITES_CODE = frozenset({EXECUTOR, *REPAIR_ROLES})",
     'WRITES_CODE = frozenset({EXECUTOR, "planner", *REPAIR_ROLES})'),

    ("a note nobody can classify is bucketed as passing on its own", AUTONOMY,
     "reasons[classify(text, state=state).cause] += 1",
     'reasons[classify(text, state=state).cause.replace("unknown", "transient")] += 1'),

    # ── the language ────────────────────────────────────────────────────────────────────────────
    ("the reading ignores the project's language", AUTONOMY,
     "    return voice.say(voice.AUTONOMY, key, language, **params)",
     "    return voice.say(voice.AUTONOMY, key, None, **params)"),

    ("the route never asks the project's language", APP,
     "    return cost_dashboard(project=project, language_of=_project_language)",
     "    return cost_dashboard(project=project)"),

    ("the CLI never hands the project's language over", CLI,
     "    block = autonomy(records, project, since=since, language=language)",
     "    block = autonomy(records, project, since=since, language=None)"),

    # ── a store that will not answer ────────────────────────────────────────────────────────────
    ("THE DEFECT: the CLI reads an unreadable store as an empty one", CLI,
     "        raise typer.Exit(2) from None\n    since = datetime.now(UTC)",
     "        records = []\n    since = datetime.now(UTC)"),

    ("a sink that cannot be built is no store at all, even for the CLI", VIEW,
     "        found = _configured_sink(must_build=True)",
     "        found = _configured_sink()"),

    ("the dashboard's block reads a failed scan as an empty record", VIEW,
     '    payload["autonomy"] = (unread(chosen, failed, language=language) if failed is not None',
     '    payload["autonomy"] = (unread(chosen, failed, language=language) if False'),
]
