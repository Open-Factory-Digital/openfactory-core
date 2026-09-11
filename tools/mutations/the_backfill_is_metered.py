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

    # THE ROW MOVED (review of #109): `box prove`'s single question is a pass outside a job too,
    # so the row shape is `observability/job_record.record_one_pass` and what stays here is this
    # door's own — the role a backfill is grouped under and the repository its ticket names.
    ("the row carries no role, so the dashboard cannot group it",
     "openfactory/onboarding/spend.py",
     '    record_one_pass(project=project, ticket=f"backfill:{repo}", role=BACKFILL_ROLE, '
     'result=result)',
     '    record_one_pass(project=project, ticket=f"backfill:{repo}", role="", result=result)'),

    ("the row drops the cost the harness reported",
     "openfactory/observability/job_record.py",
     '            cost_usd=getattr(result, "cost_usd", None),\n'
     '            num_turns=getattr(result, "num_turns", None),\n'
     '            input_tokens=getattr(result, "input_tokens", None),\n'
     '            output_tokens=getattr(result, "output_tokens", None)))',
     '            cost_usd=None,\n'
     '            num_turns=getattr(result, "num_turns", None),\n'
     '            input_tokens=getattr(result, "input_tokens", None),\n'
     '            output_tokens=getattr(result, "output_tokens", None)))'),

    ("semantic_pass_for builds the recorder and binds nothing",
     "openfactory/onboarding/onboard.py",
     "            on_run=meter.note)\n",
     "            on_run=None)\n"),

    # re-pinned 2026-09-07: #76 moved the sentence into the per-source loop and this row went
    # unmatched — the plan was refused whole, and nothing here ran until it was noticed
    ("the backfill sums the spend and never says it",
     "openfactory/onboarding/onboard.py",
     '            said[repo] = (f"{repo}: " if several else "") + spend.said(mode)\n',
     '            said[repo] = (f"{repo}: " if several else "") + mode\n'),

    ("a recorder that raises takes the pass with it",
     "openfactory/onboarding/context.py",
     '                log.warning("agent pass: the recorder failed — the pass is kept", '
     'exc_info=True)\n',
     '                raise\n'),
]
