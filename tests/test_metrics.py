"""observability.metrics — the cost/effort telemetry sink (per-invocation + job records).

Covers the record shape/key, the shipped sinks and the dashboard's shape — the GENERIC half. The
DynamoDB sink's own tests live in `tests/test_dynamo_metrics_sink.py`, because that module is an
add-on the core never imports: a generic test file that imported it died with the vendor half."""

from __future__ import annotations

from openfactory.api.metrics_view import dashboard
from openfactory.observability.metrics import (
    InMemoryMetricsSink,
    MetricRecord,
    NullMetricsSink,
)


def test_dynamo_key_is_time_sortable_within_project():
    r = MetricRecord(project="books", ticket="426", ts="2026-07-23T10:00:00+00:00",
                     kind="agent_run", role="executor")
    key = r.dynamo_key()
    assert key["pk"] == "books"
    assert key["sk"] == "2026-07-23T10:00:00+00:00#426#executor"
    # `kind_ts` backs the `by_kind` index the agents' memory is read by (ADR-0021). Without it,
    # "what am I still waiting on?" can only be answered by scanning the whole table.
    assert key["kind_ts"] == "agent_run#2026-07-23T10:00:00+00:00#426"


def test_job_record_key_falls_back_to_kind_when_no_role():
    r = MetricRecord(project="p", ticket="1", ts="T", kind="job")
    assert r.dynamo_key()["sk"] == "T#1#job"


def test_null_sink_is_a_noop():
    NullMetricsSink().record(MetricRecord(project="p", ticket="1", ts="T", kind="job"))  # no raise


def test_inmemory_sink_collects():
    s = InMemoryMetricsSink()
    s.record(MetricRecord(project="p", ticket="1", ts="T", kind="job"))
    assert len(s.records) == 1


# ── the per-project dashboard shape (pure, no AWS) ──────────────────────────────────────────────

_RECS = [
    {"kind": "agent_run", "pk": "books", "ticket": "1", "ts": "2026-07-23T10:00:00+00:00",
     "role": "planner", "model": "sonnet", "harness": "claude_code", "cost_usd": 1.0,
     "num_turns": 3},
    {"kind": "agent_run", "pk": "books", "ticket": "1", "ts": "2026-07-23T10:05:00+00:00",
     "role": "executor", "model": "opus", "harness": "claude_code", "cost_usd": 5.0,
     "num_turns": 20},
    {"kind": "agent_run", "pk": "books", "ticket": "2", "ts": "2026-07-24T09:00:00+00:00",
     "role": "executor", "model": "opus", "harness": "claude_code", "cost_usd": 3.0,
     "num_turns": 12},
    {"kind": "job", "pk": "books", "ticket": "1", "ts": "2026-07-23T10:06:00+00:00",
     "state": "merged", "title": "add health route", "wall_s": 600.0, "total_cost_usd": 6.0},
    {"kind": "job", "pk": "books", "ticket": "2", "ts": "2026-07-24T09:10:00+00:00",
     "state": "merged", "wall_s": 400.0, "total_cost_usd": 3.0},
    # a DIFFERENT project — must be excluded when scoped to books
    {"kind": "agent_run", "pk": "fink", "ticket": "9", "ts": "2026-07-25T00:00:00+00:00",
     "role": "executor", "model": "haiku", "harness": "codex", "cost_usd": 2.0},
]


def test_dashboard_scopes_to_one_project_and_lists_all():
    from openfactory.api.metrics_view import dashboard

    d = dashboard(_RECS, project="books")
    assert d["projects"] == ["books", "fink"]  # selector sees both
    assert d["project"] == "books"
    assert d["by_model"] == {"opus": 8.0, "sonnet": 1.0}  # fink's haiku excluded
    assert d["by_harness"] == {"claude_code": 9.0}        # fink's codex excluded
    assert d["by_role"] == {"executor": 8.0, "planner": 1.0}
    assert d["by_day"] == {"2026-07-23": 6.0, "2026-07-24": 3.0}
    assert d["totals"]["cost_usd"] == 9.0
    assert d["totals"]["tasks"] == 2
    assert d["totals"]["avg_cost_per_task"] == 4.5
    assert d["totals"]["avg_wall_s"] == 500.0  # (600+400)/2


def test_dashboard_per_task_table_joins_runs_and_job():
    from openfactory.api.metrics_view import dashboard

    d = dashboard(_RECS, project="books")
    by_ticket = {t["ticket"]: t for t in d["tasks"]}
    t1 = by_ticket["1"]
    assert t1["cost_usd"] == 6.0 and t1["turns"] == 23          # summed across its 2 runs
    assert t1["model"] == "opus, sonnet" and t1["harness"] == "claude_code"
    assert t1["wall_s"] == 600.0 and t1["title"] == "add health route"  # from the job record
    assert d["tasks"][0]["date"] >= d["tasks"][-1]["date"]      # newest first


def test_dashboard_defaults_to_first_project_and_empty_is_safe():
    from openfactory.api.metrics_view import dashboard

    assert dashboard(_RECS)["project"] == "books"  # first project when none given
    e = dashboard([])
    assert e["totals"]["cost_usd"] == 0.0 and e["totals"]["tasks"] == 0
    assert e["by_model"] == {} and e["tasks"] == [] and e["projects"] == []


# ── the Knowledge Layer's A/B readout (ADR-0017's gate) ──────────────────────────────────────────

def _job(ticket, cost, wall, knowledge, turns=10, tok=(90000, 10000)):
    """One ticket's worth of records: an agent_run carrying the cost/tokens + a job summary
    carrying the arm (that split mirrors how the sink actually writes them)."""
    return [
        {"pk": "p", "kind": "agent_run", "ticket": ticket, "ts": "2026-07-26T10:00:00",
         "role": "executor", "model": "claude-opus-5", "harness": "claude_code",
         "cost_usd": cost, "num_turns": turns,
         "input_tokens": tok[0], "output_tokens": tok[1]},
        {"pk": "p", "kind": "job", "ticket": ticket, "ts": "2026-07-26T10:00:00",
         "state": "merged", "wall_s": wall, "knowledge": knowledge},
    ]


def test_ab_groups_by_arm_with_n_mean_and_median():
    records = (_job("1", 1.0, 100, "injected") + _job("2", 3.0, 300, "injected")
               + _job("3", 2.0, 200, "off") + _job("4", 40.0, 4000, "off"))
    arms = dashboard(records)["knowledge_ab"]["arms"]

    assert arms["injected"]["tasks"] == 2 and arms["off"]["tasks"] == 2
    assert arms["injected"]["cost_usd"]["avg"] == 2.0
    # the median is why this isn't mean-only: one huge ticket makes `off` look 10x worse on the
    # mean while the medians tell a different story
    assert arms["off"]["cost_usd"]["avg"] == 21.0
    assert arms["off"]["cost_usd"]["median"] == 21.0
    assert arms["injected"]["cost_usd"]["median"] == 2.0
    assert arms["injected"]["wall_s"]["avg"] == 200.0


def test_TOKENS_are_reported_per_arm_because_that_is_the_claim():
    """The hypothesis is that the map makes the agent READ LESS to find the same code. Cost is a
    derived number that moves with per-model pricing and is simply absent for a harness that
    reports no price, so an experiment resting on cost alone becomes unreadable the moment the
    arms run on different engines. Tokens measure the claim directly."""
    records = (_job("1", 1.0, 100, "injected", tok=(50_000, 8_000))
               + _job("2", 2.0, 200, "off", tok=(90_000, 10_000)))
    arms = dashboard(records)["knowledge_ab"]["arms"]

    assert arms["injected"]["tokens"]["median"] == 58_000
    assert arms["off"]["tokens"]["median"] == 100_000
    assert arms["injected"]["input_tokens"]["median"] == 50_000
    assert arms["injected"]["output_tokens"]["median"] == 8_000


def test_tokens_roll_up_per_ticket_across_every_invocation():
    """They were recorded per invocation and never summed, so the one measure the Knowledge Layer
    exists to move was invisible on the dashboard that decides its fate."""
    records = _job("1", 1.0, 100, "off", tok=(10_000, 1_000))
    records.append({"pk": "p", "kind": "agent_run", "ticket": "1", "ts": "2026-07-26T11:00:00",
                    "role": "repair", "model": "m", "harness": "claude_code", "cost_usd": 0.1,
                    "num_turns": 2, "input_tokens": 5_000, "output_tokens": 500})
    task = dashboard(records)["tasks"][0]
    assert task["input_tokens"] == 15_000 and task["output_tokens"] == 1_500
    assert task["tokens"] == 16_500


def test_pre_instrumentation_is_its_OWN_baseline_never_merged_into_the_control():
    """Everything the factory did before the arm was recorded ran WITHOUT the map — the flag has
    defaulted to false since it existed — so it is a real baseline and worth seeing. What it is
    not is a CHOSEN control: nobody selected those tickets and their mix is whatever came up. So
    it gets its own bucket, visible but never silently padding `off`."""
    records = _job("1", 1.0, 100, "injected") + _job("2", 5.0, 500, "") + _job("3", 4.0, 400, "off")
    ab = dashboard(records)["knowledge_ab"]
    assert set(ab["arms"]) == {"injected", "off"}       # the experiment, and only the experiment
    assert ab["arms"]["off"]["tasks"] == 1              # NOT 2 — history did not land in the control
    assert ab["baseline"]["tasks"] == 1                 # …it is reported on its own


def test_unavailable_is_its_own_arm_not_lumped_with_injected():
    """Opted in but the map wasn't trustworthy → the agent ran WITHOUT it. Counting that as
    treatment would dilute the measured effect with controls."""
    records = _job("1", 1.0, 100, "injected") + _job("2", 2.0, 200, "unavailable")
    arms = dashboard(records)["knowledge_ab"]["arms"]
    assert set(arms) == {"injected", "unavailable"}
    assert arms["unavailable"]["tasks"] == 1


def test_the_arm_reaches_the_per_task_table():
    tasks = dashboard(_job("7", 1.5, 90, "injected"))["tasks"]
    assert tasks[0]["ticket"] == "7" and tasks[0]["knowledge"] == "injected"


def test_the_delta_names_its_control_and_is_signed():
    records = (_job("1", 1.0, 100, "injected", tok=(50_000, 8_000))
               + _job("2", 2.0, 200, "off", tok=(90_000, 10_000)))
    delta = dashboard(records)["knowledge_ab"]["delta"]
    assert delta["control"] == "off" and delta["treatment"] == "injected"
    # 58k vs 100k → -42%: a SAVING reads negative, so the sign is meaningful on its own
    assert delta["measures"]["tokens"]["pct"] == -42.0


def test_there_is_no_delta_until_something_exists_to_compare():
    """A one-arm readout has nothing to compare, and inventing a baseline is how a number that
    means nothing ends up in a slide."""
    assert dashboard(_job("1", 1.0, 100, "off"))["knowledge_ab"]["delta"] is None


def test_the_baseline_alone_still_reports_itself():
    """Before the experiment starts there are no arms at all, but the history must still be
    visible — seeing what the factory costs today is the whole point of looking beforehand."""
    ab = dashboard(_job("1", 1.0, 100, ""))["knowledge_ab"]
    assert ab["arms"] == {}
    assert ab["baseline"]["tasks"] == 1
    assert ab["delta"] is None


def test_the_delta_NEVER_compares_against_history():
    """A delta against tickets measured under a different platform is a before/after wearing an
    experiment's clothes. The historical bucket predates the review-repair invocation being counted
    at all, so it looks cheaper than it was."""
    records = _job("1", 1.0, 100, "injected") + _job("2", 9.0, 900, "")
    assert dashboard(records)["knowledge_ab"]["delta"] is None
