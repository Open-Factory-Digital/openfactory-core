"""The backfill is metered — the cuts that put the first live onboarding's silence back.

ROW 1 IS THE MEASURED SHAPE: `agent_ask` keeps the text and drops the result, and six passes
leave no row.

ROWS 2-4 ARE THE ROW ITSELF: nothing written; written under no role (the dashboard cannot group
it); written with the cost dropped (a row that averages as free).

ROW 5 IS THE SEAM: `semantic_pass_for` builds the recorder and binds nothing.

ROW 6 IS THE SENTENCE: the sum is computed and never said.

ROW 7 IS THE GUARD: a recorder that raises takes the pass with it — the client loses a document
to telemetry.
"""

TEST = "tests/test_the_backfill_is_metered.py"

MUTATIONS = [
    ("agent_ask keeps the text and drops the result — the 2026-09-06 shape",
     "openfactory/onboarding/context.py",
     "        if on_run is not None:\n            try:\n                on_run(result)\n",
     "        if False:\n            try:\n                on_run(result)\n"),

    ("Spend.note counts the pass and writes no row",
     "openfactory/onboarding/spend.py",
     "        record_backfill_run(self.project, self.repo, result)\n",
     "        pass\n"),

    ("the row carries no role, so the dashboard cannot group it",
     "openfactory/onboarding/spend.py",
     '        kind="agent_run", role=BACKFILL_ROLE,\n',
     '        kind="agent_run", role="",\n'),

    ("the row drops the cost the harness reported",
     "openfactory/onboarding/spend.py",
     '        cost_usd=getattr(result, "cost_usd", None),\n',
     '        cost_usd=None,\n'),

    ("semantic_pass_for builds the recorder and binds nothing",
     "openfactory/onboarding/onboard.py",
     "            on_run=meter.note)\n",
     "            on_run=None)\n"),

    ("the backfill sums the spend and never says it",
     "openfactory/onboarding/onboard.py",
     "        return spend.said(mode), wrote\n",
     "        return mode, wrote\n"),

    ("a recorder that raises takes the pass with it",
     "openfactory/onboarding/context.py",
     '                log.warning("agent pass: the recorder failed — the pass is kept", '
     'exc_info=True)\n',
     '                raise\n'),
]
