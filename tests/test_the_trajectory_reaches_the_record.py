"""The trajectory travels from the stream to the durable row and out to the panel.

`observability/trajectory.py` shipped the measurement and nothing read it. This is the wiring:
`AgentRunResult.raw_output` already carries the harness stream, so the numbers are computable at
the exact moment the metric is built, and the two questions an operator asks about a factory — is
it fast, is it cheap — stop having no instrument at all.

THE GUARD THAT MATTERS MOST, and it is the one this whole file is arranged around:

    `raw_output` defaults to `""`. `pulses_of(harness, "")` answers `[]` — "read it, it held no
    events" — which summarises to a perfectly READABLE trajectory of zero tool calls. Recorded,
    that row says the agent called no tools. What actually happened is that nobody captured its
    output.

A pass whose stream was never captured and a pass that genuinely did nothing must not land in the
same row, must not average together, and must not render alike. Every layer here keeps them apart:
the metric leaves the dimension absent, the row carries None, and the panel prints a dash.

`turns_to_first_edit` is never summed. It is a per-pass shape and two of them added together mean
nothing — the rollup carries the three that do sum and omits the one that does not.
"""

from __future__ import annotations

import json

from openfactory.api.metrics_view import _opt_int, dashboard
from openfactory.contracts.run import AgentRunResult
from openfactory.orchestrator.machine import JobRunner


def _stream(*calls: tuple[str, dict]) -> str:
    lines = [json.dumps({"type": "assistant",
                         "message": {"content": [{"type": "tool_use", "name": n, "input": i}]}})
             for n, i in calls]
    lines.append(json.dumps({"type": "result", "subtype": "success", "total_cost_usd": 0.1}))
    return "\n".join(lines)


def _res(**kw) -> AgentRunResult:
    kw.setdefault("ok", True)
    kw.setdefault("harness", "claude_code")
    return AgentRunResult(**kw)


# ── the measurement reaches the metric ───────────────────────────────────────────────────────────

def test_a_pass_records_what_it_did_and_not_only_what_it_cost() -> None:
    """The control. The stream is already on the result; nothing had ever read it."""
    res = _res(raw_output=_stream(("Read", {"file_path": "a.py"}),
                                  ("Read", {"file_path": "a.py"}),
                                  ("Edit", {"file_path": "a.py"})))

    dims = JobRunner._trajectory_of(res)

    assert dims["tool_calls"] == 3
    assert dims["repeated_calls"] == 1
    assert dims["turns_to_first_edit"] == 3


def test_the_metric_carries_the_dimensions(monkeypatch) -> None:
    """`_count` is what the workflow later persists. If the numbers stop here they are computed
    per pass and thrown away exactly as before."""
    # A bare holder, not a real machine: `_count` is reached on flows that do not go through
    # `run()` at all (the CI-repair path lazily initialises `_agent_runs` for exactly that reason),
    # so it must not depend on the instance carrying anything but that list.
    holder = type("_H", (), {})()
    JobRunner._count(holder, _res(raw_output=_stream(("Edit", {"file_path": "a.py"})),
                                  num_turns=1), role="executor")

    metric = holder._agent_runs[0]
    assert metric.tool_calls == 1
    assert metric.refused_calls == 0


# ── the zero nobody measured ─────────────────────────────────────────────────────────────────────

def test_an_uncaptured_stream_records_NOTHING_rather_than_zero() -> None:
    """THE GUARD THIS FILE IS ARRANGED AROUND. `raw_output` defaults to `""` and `pulses_of` reads
    that as "no events", which summarises to a readable zero. A row saying the agent called no
    tools is a measurement; a row for a pass nobody captured is not, and they must not be the
    same row."""
    assert JobRunner._trajectory_of(_res(raw_output="")) == {}
    assert JobRunner._trajectory_of(_res(raw_output="   \n ")) == {}


def test_a_harness_with_no_stream_reader_records_nothing() -> None:
    """The other way the same distinction is lost. `pulses_of` answers None for a harness it
    cannot read, and that is not a pass that did nothing."""
    assert JobRunner._trajectory_of(_res(harness="no-such-harness",
                                         raw_output=_stream(("Edit", {"file_path": "a.py"})))) == {}


def test_a_pass_that_really_did_nothing_IS_recorded_as_zero() -> None:
    """The positive twin, and it is load-bearing: without it a version that returned `{}` for
    everything would pass every guard above and the measurement would never exist."""
    dims = JobRunner._trajectory_of(_res(raw_output=json.dumps(
        {"type": "result", "subtype": "success", "total_cost_usd": 0.1})))

    assert dims["tool_calls"] == 0, "read, and it held no calls — a measurement"


def test_a_broken_reader_costs_the_number_and_not_the_job(monkeypatch) -> None:
    """Every caller is on the path of a pass that already happened. Telemetry that took a job down
    would be worse than telemetry that is absent."""
    def _boom(*a, **k):
        raise RuntimeError("the reader broke")

    monkeypatch.setattr("openfactory.adapters.agent.stream.pulses_of", _boom)

    assert JobRunner._trajectory_of(_res(raw_output=_stream(("Edit", {"file_path": "a.py"})))) == {}


# ── it survives the trip to the panel ────────────────────────────────────────────────────────────

def _rows(**run) -> list[dict]:
    base = {"kind": "agent_run", "project": "p", "ticket": "7", "ts": "2026-08-30T10:00:00Z",
            "role": "executor", "model": "sonnet", "harness": "claude_code", "cost_usd": 0.1}
    return [{**base, **run},
            {"kind": "job", "project": "p", "ticket": "7", "ts": "2026-08-30T10:00:00Z",
             "state": "merged", "title": "t", "wall_s": 12.0}]


def test_the_dashboard_sums_the_three_that_sum() -> None:
    board = dashboard(_rows(tool_calls=10, repeated_calls=2, refused_calls=1)
                      + _rows(tool_calls=5, repeated_calls=1, refused_calls=0)[:1])
    task = next(t for t in board["tasks"] if t["ticket"] == "7")

    assert task["tool_calls"] == 15
    assert task["repeated_calls"] == 3
    assert task["refused_calls"] == 1


def test_the_dashboard_does_not_sum_the_one_that_does_not_sum() -> None:
    """`turns_to_first_edit` is a per-pass shape. Two of them added together is a number with no
    meaning, and a table column with no meaning is worse than a missing one."""
    board = dashboard(_rows(tool_calls=3, turns_to_first_edit=2))
    task = next(t for t in board["tasks"] if t["ticket"] == "7")

    assert "turns_to_first_edit" not in task


def test_a_ticket_no_pass_could_be_read_for_shows_nothing_not_zero() -> None:
    """The distinction, all the way out to what a person looks at. An operator ranking tickets by
    wasted calls must never be handed a zero nobody measured."""
    board = dashboard(_rows())
    task = next(t for t in board["tasks"] if t["ticket"] == "7")

    assert task["tool_calls"] is None
    assert task["repeated_calls"] is None


def test_the_per_invocation_rows_keep_the_distinction_too() -> None:
    """The panel re-aggregates these client-side, so a None that became 0 here would average a
    pass nobody could read into every filter the operator applies."""
    board = dashboard(_rows(tool_calls=4, turns_to_first_edit=None))

    assert board["runs"][0]["tool_calls"] == 4
    assert board["runs"][0]["turns_to_first_edit"] is None


def test_opt_int_reads_a_string_and_refuses_to_invent_a_zero() -> None:
    """The DynamoDB backend stores numbers as strings, so the reader has to parse them — and the
    same function must not turn an absent value into 0, which is what every other numeric read on
    this page deliberately does (`int(x or 0)`) because for a cost, zero is a cost."""
    assert _opt_int("7") == 7
    assert _opt_int(0) == 0, "a measured zero survives"
    assert _opt_int(None) is None
    assert _opt_int("") is None
    assert _opt_int("not a number") is None


# ── the middle of the pipe, which nothing was testing ────────────────────────────────────────────
#
# The two guards above jump from the metric straight to the dashboard, so the ACTIVITY that maps
# one onto the other was never exercised — and two mutations that gutted it survived their first
# run for exactly that reason. It is the layer where the numbers cross a process boundary, and the
# layer where an absent dimension is most easily turned into a zero.

def _recorded(runs: list[dict]) -> list:
    """Run the real metrics activity against a sink that only remembers."""
    from openfactory.runtime.temporal import activities as act
    from openfactory.runtime.temporal.io import JobMetricsInput

    class _Sink:
        def __init__(self):
            self.rows = []

        def record(self, rec):
            self.rows.append(rec)

    sink = _Sink()
    inp = JobMetricsInput(project="p", issue="7", ts="2026-08-30T10:00:00Z", agent_runs=runs)
    original = act._metrics_sink
    act._metrics_sink = lambda: sink
    try:
        import asyncio

        asyncio.run(act.record_job_metrics(inp))
    finally:
        act._metrics_sink = original
    return [r for r in sink.rows if r.kind == "agent_run"]


def test_the_activity_carries_the_dimensions_to_the_row() -> None:
    """The numbers cross a process boundary here. If the mapping drops them they exist for the
    length of one function call and nowhere else — and every guard above still passes."""
    row = _recorded([{"role": "executor", "tool_calls": 9, "repeated_calls": 2,
                      "refused_calls": 1, "turns_to_first_edit": 4}])[0]

    assert row.tool_calls == 9
    assert row.repeated_calls == 2
    assert row.refused_calls == 1
    assert row.turns_to_first_edit == 4


def test_the_activity_keeps_an_absent_dimension_absent() -> None:
    """The distinction survives the metric and is most easily lost right here — one `or 0` away.
    A pass nobody could read must not reach the durable row as a pass that did nothing."""
    row = _recorded([{"role": "executor", "cost_usd": 0.1}])[0]

    assert row.tool_calls is None
    assert row.repeated_calls is None
    assert row.turns_to_first_edit is None
