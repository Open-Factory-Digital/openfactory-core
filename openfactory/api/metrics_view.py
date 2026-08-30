"""Cost-dashboard bridge — read the metrics table (observability.metrics) and shape it for the
panel's PER-PROJECT cost dashboard: filterable rollups (period / model / harness / role) plus a
per-task table (with wall-clock time). Read-only + best-effort: any failure degrades to empty so
the panel still renders. Low volume (dozens of jobs/day) → a full Scan + in-process aggregation."""

from __future__ import annotations

import logging
import os
from collections import defaultdict

log = logging.getLogger("openfactory.metrics")


def _configured_sink():
    """The sink this deployment WRITES to, so a reader asks the same place (audit, 2026-08-02).

    Both readers used to open with `os.environ.get("OPENFACTORY_METRICS_TABLE")` and return `[]`
    when it
    was unset — which on a `docker compose` install is always, because the local answer is SQLite
    and that variable belongs to DynamoDB. So a perfectly configured local deployment wrote metrics
    to disk and every reader answered "nothing recorded": the cost dashboard, the tech-lead's
    memory of what it had already said, recurring-failure detection and the open-loop ledger, all
    silently blind. `SqliteMetricsSink` had the two matching read methods the whole time, tested,
    and called by nothing.

    Returns None when the sink cannot read, which every caller already treats as "no data" — and
    SAYS SO when that is a gap rather than a choice. The null sink dropped every record it was
    given, so "nothing to read" is its true answer; any other sink that is not a `ReadableSink`
    recorded rows nobody can read back, which is the cost dashboard, the tech-lead's memory and
    the open-loop ledger all silently blind, and that is logged as a WARNING rather than read as
    an empty store.

    THE CHECK IS ON THE PORT (`ReadableSink`), not `hasattr(sink, "scan")` — and the two readers no
    longer duck-type `table_name` as "this is DynamoDB". A third-party sink with an ordinary
    `table_name` attribute was starved to `[]` by one reader and routed to a vendor's client by
    the other (probes C/D, 2026-08-24).
    """
    from openfactory.observability.metrics import NullMetricsSink, ReadableSink
    from openfactory.observability.registry import build_metrics_sink, metrics_sink_kind

    kind = metrics_sink_kind()
    try:
        sink = build_metrics_sink(kind, path=os.environ.get("OPENFACTORY_METRICS_DB"))
    except Exception as exc:  # noqa: BLE001 — an unreadable store is empty, never a 500
        log.warning("metrics sink %r could not be built for reading (%s) — reporting no data",
                    kind, exc)
        return None
    if isinstance(sink, ReadableSink):
        return sink
    if not isinstance(sink, NullMetricsSink):
        log.warning("the configured metrics sink %r (%s) records and cannot be read back — the "
                    "dashboard and the agents' memory report nothing until a readable sink is "
                    "configured", kind, type(sink).__name__)
    return None


def _opt_int(value) -> int | None:
    """An int, or None when the value was never measured.

    NOT `int(x or 0)`, which is what every other numeric here does and is right for them: a cost of
    zero is a cost. A trajectory dimension of zero would say the agent called no tools, and the
    rows that carry None are the rows where nobody could read the stream at all. The two must not
    average together."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        # None and "" arrive here, and that is deliberate rather than lazy: an explicit
        # `if value is None` clause in front of this was DEAD — the mutation that removed it
        # changed nothing, because `float(None)` raises and lands in exactly this branch. One
        # spelling of "not a number", not two, one of which is never reached.
        return None


def scan_records(table_name: str | None = None, region: str | None = None) -> list[dict]:
    """Every metric item, numbers parsed back from their stored strings. [] on any trouble
    (table absent, no creds, scan error) — the dashboard shows 'no data yet', never an error.

    THE DEGRADING DOOR, and it stays that way. A cost dashboard that 500s because the store hiccuped
    is worse than one showing yesterday's shape; nobody decides anything from it in the next thirty
    seconds. `scan_all_or_raise` is the same read for callers that DO — see #126, where this
    function's `[]` reached the panel's human gates through three layers and told an operator their
    question had already been answered."""
    try:
        return scan_all_or_raise(table_name=table_name, region=region)
    except Exception as exc:  # noqa: BLE001 — the dashboard degrades to empty, never 500s
        log.warning("metrics scan failed for %s: %s", table_name or "the configured sink", exc)
        return []


def scan_all_or_raise(table_name: str | None = None, region: str | None = None) -> list[dict]:
    """`scan_records`, but an unreadable store RAISES rather than reading as an empty one.

    `[]` here means the store answered and had nothing, or that no readable store is configured —
    which is a supported deployment shape, not a failure.

    THE SINK THE REGISTRY BUILT IS THE ONLY DOOR. This used to fall through to
    `OPENFACTORY_METRICS_TABLE` whenever that sink could not read, so a deployment on any other
    sink with the table variable set reached for one vendor's client. An explicit `table_name` is
    the operator's override, and it is registry-shaped: the CONFIGURED sink's kind, pointed at that
    table (`configured_metrics_sink`) — never a vendor's kind spelled here. Each sink parses its
    own stored numbers — the DynamoDB one stringifies and parses back; nothing here knows that."""
    if table_name:
        from openfactory.observability.registry import configured_metrics_sink

        return configured_metrics_sink(table=table_name, region=region).scan()
    sink = _configured_sink()
    return [] if sink is None else sink.scan()


def _round_map(d: dict) -> dict:
    return {k: round(v, 4) for k, v in sorted(d.items(), key=lambda kv: -kv[1])}


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


#: tickets that ran before the arm was recorded. `knowledge_map` has defaulted to false for every
#: project since the field existed, so these demonstrably ran WITHOUT the map — they are a real
#: baseline, not a mystery. What they are not is a *controlled* arm: nobody chose them, and their
#: ticket mix is whatever the factory happened to do. Kept as their own bucket so the baseline is
#: visible without being silently merged into the deliberate `off` control.
PRE_OKF = "pre_okf"

#: the treatment arm — the only one where the agent actually received the map
TREATMENT = "injected"


def _stats(xs: list[float]) -> dict:
    """n / mean / median for one measure. Median matters as much as mean here: ticket sizes vary
    enormously, so one large ticket landing in a small arm moves the mean and proves nothing."""
    n = len(xs)
    return {
        "n": n,
        "avg": round(sum(xs) / n, 4) if n else None,
        "median": round(_median(xs) or 0.0, 4) if n else None,
    }


def _knowledge_ab(tasks: list[dict]) -> dict:
    """The Knowledge Layer's A/B readout (ADR-0017's gate), grouped by which arm each ticket ran
    in: `injected` (the agent had the module map), `off` (the project hasn't opted in),
    `unavailable` (opted in, but the map wasn't trustworthy for that checkout — those tickets ran
    WITHOUT it, so they are controls, not treatment), and `pre_okf` (see above).

    TOKENS ARE THE HEADLINE MEASURE, not cost. The claim being tested is that the map makes the
    agent read less to find the same code, and tokens measure that directly. Cost is a derived
    number that moves with per-model pricing and is simply absent for a harness that reports no
    price (Codex), so an experiment resting on cost alone would be unreadable the moment the arms
    ran on different engines.

    The `delta` is a plain arithmetic difference between the treatment and its control, NOT a
    verdict. Comparing arms is only valid if the ticket mix is comparable, and nothing here can
    know that — which is why every bucket reports its own n and the delta names the control it
    used. A human judges."""
    arms: dict[str, dict] = {}
    for t in tasks:
        arm = t.get("knowledge") or PRE_OKF
        # `pre_okf` is a BASELINE, not an arm, and it is kept out of the comparison entirely.
        # Those tickets predate the experiment AND predate changes to what the platform counts
        # (review-repair started being counted 2026-07-26), so putting them beside a chosen arm
        # invites exactly the comparison that would be wrong. Reported separately, below.
        a = arms.setdefault(arm, {"cost": [], "wall": [], "turns": [], "tokens": [],
                                  "input": [], "output": []})
        a["cost"].append(float(t.get("cost_usd") or 0.0))
        if t.get("wall_s"):
            a["wall"].append(float(t["wall_s"]))
        a["turns"].append(float(t.get("turns") or 0))
        if t.get("tokens"):
            a["tokens"].append(float(t["tokens"]))
            a["input"].append(float(t.get("input_tokens") or 0))
            a["output"].append(float(t.get("output_tokens") or 0))

    out: dict[str, dict] = {}
    for arm, a in arms.items():
        out[arm] = {
            "tasks": len(a["cost"]),
            "tokens": _stats(a["tokens"]),
            "input_tokens": _stats(a["input"]),
            "output_tokens": _stats(a["output"]),
            "cost_usd": _stats(a["cost"]),
            "wall_s": _stats(a["wall"]),
            "turns": _stats(a["turns"]),
        }
    experiment = {k: v for k, v in out.items() if k != PRE_OKF}
    return {"arms": experiment, "baseline": out.get(PRE_OKF), "delta": _delta(experiment)}


def _delta(arms: dict) -> dict | None:
    """Treatment vs its control, per measure, as a signed percentage. `None` until both exist —
    a one-arm readout has nothing to compare, and inventing a baseline is how a number that means
    nothing ends up in a slide."""
    t = arms.get(TREATMENT)
    # `pre_okf` is deliberately NOT a candidate control: it is history, measured under a different
    # platform, and a delta against it would be a before/after wearing an experiment's clothes.
    control_name = next((c for c in ("off", "unavailable") if arms.get(c)), None)
    if not t or not control_name:
        return None
    c = arms[control_name]
    out = {"control": control_name, "treatment": TREATMENT, "measures": {}}
    for m in ("tokens", "input_tokens", "output_tokens", "cost_usd", "wall_s", "turns"):
        base, got = c[m].get("median"), t[m].get("median")
        if base:  # a zero or missing baseline yields no percentage, not a division by zero
            out["measures"][m] = {
                "control_median": base, "treatment_median": got,
                "pct": round((got - base) / base * 100, 1) if got is not None else None,
            }
    return out


def dashboard(records: list[dict], project: str | None = None) -> dict:
    """The panel's dashboard payload. `projects` lists every project seen (for the selector);
    everything else is scoped to `project` (or the first project if none given). Cost breakdowns
    come from `agent_run` items (model/harness/role + cost); the per-task table joins each
    ticket's agent_runs (cost/turns/models/harnesses) with its `job` record (wall-clock, state)."""
    projects = sorted({str(r.get("pk") or r.get("project") or "") for r in records
                       if (r.get("pk") or r.get("project"))})
    project = project or (projects[0] if projects else "")

    scoped = [r for r in records if str(r.get("pk") or r.get("project") or "") == project]
    runs = [r for r in scoped if r.get("kind") == "agent_run"]
    jobs = {str(r.get("ticket")): r for r in scoped if r.get("kind") == "job"}

    def _sum_by(key: str) -> dict:
        out: dict[str, float] = defaultdict(float)
        for r in runs:
            out[str(r.get(key) or "unknown")] += r.get("cost_usd") or 0.0
        return _round_map(out)

    by_day: dict[str, float] = defaultdict(float)
    for r in runs:
        day = str(r.get("ts") or "")[:10]
        if day:
            by_day[day] += r.get("cost_usd") or 0.0

    # per-ticket rollup (the table). Group runs by ticket; join the job record for time/state.
    per: dict[str, dict] = defaultdict(lambda: {"cost": 0.0, "turns": 0, "models": set(),
                                                "harnesses": set(), "ts": "",
                                                "in_tok": 0, "out_tok": 0,
                                                "calls": 0, "repeats": 0, "refused": 0,
                                                "read": 0})
    for r in runs:
        tk = str(r.get("ticket"))
        p = per[tk]
        p["cost"] += r.get("cost_usd") or 0.0
        p["turns"] += int(r.get("num_turns") or 0)
        # tokens were recorded per invocation but never rolled up, so the measure the Knowledge
        # Layer exists to move was invisible on the dashboard that decides its fate
        p["in_tok"] += int(r.get("input_tokens") or 0)
        p["out_tok"] += int(r.get("output_tokens") or 0)
        # WHAT THE PASSES DID, summed across the ticket's invocations. `turns_to_first_edit` is
        # deliberately NOT here: it is a per-pass shape and adding two of them means nothing.
        # `read` counts the passes whose trajectory could be read at all, so a ticket whose
        # harness has no stream reader shows a dash rather than a confident zero.
        if r.get("tool_calls") is not None:
            p["read"] += 1
            p["calls"] += int(r.get("tool_calls") or 0)
            p["repeats"] += int(r.get("repeated_calls") or 0)
            p["refused"] += int(r.get("refused_calls") or 0)
        if r.get("model"):
            p["models"].add(str(r["model"]))
        if r.get("harness"):
            p["harnesses"].add(str(r["harness"]))
        p["ts"] = max(p["ts"], str(r.get("ts") or ""))
    tasks = []
    for tk, p in per.items():
        job = jobs.get(tk, {})
        tasks.append({
            "ticket": tk,
            "date": (p["ts"] or str(job.get("ts") or ""))[:10],
            "model": ", ".join(sorted(p["models"])) or "—",
            "harness": ", ".join(sorted(p["harnesses"])) or "—",
            "turns": p["turns"],
            "input_tokens": p["in_tok"],
            "output_tokens": p["out_tok"],
            "tokens": p["in_tok"] + p["out_tok"],
            "wall_s": job.get("wall_s"),
            "cost_usd": round(p["cost"], 4),
            # None, not 0, when no pass on this ticket had a readable stream — the panel renders a
            # dash, and an operator ranking tickets by waste is never handed a zero nobody measured.
            "tool_calls": p["calls"] if p["read"] else None,
            "repeated_calls": p["repeats"] if p["read"] else None,
            "refused_calls": p["refused"] if p["read"] else None,
            "state": job.get("state") or "",
            "title": job.get("title") or "",
            "knowledge": job.get("knowledge") or "",  # the A/B arm (ADR-0017)
        })
    tasks.sort(key=lambda t: (t["date"], t["ticket"]), reverse=True)

    total_cost = round(sum((r.get("cost_usd") or 0.0) for r in runs), 4)
    walls = [j.get("wall_s") for j in jobs.values() if j.get("wall_s")]
    n = len(per) or len(jobs)
    # raw per-invocation rows so the panel can filter + re-aggregate client-side (instant, no
    # round-trip per filter change). Small (dozens/day).
    runs_out = [{
        "ticket": str(r.get("ticket")), "ts": str(r.get("ts") or ""),
        "date": str(r.get("ts") or "")[:10], "role": str(r.get("role") or ""),
        "model": str(r.get("model") or ""), "harness": str(r.get("harness") or ""),
        "cost_usd": round(r.get("cost_usd") or 0.0, 4), "turns": int(r.get("num_turns") or 0),
        "input_tokens": int(r.get("input_tokens") or 0),
        "output_tokens": int(r.get("output_tokens") or 0),
        # Per invocation these stay None where they were not measured, for the same reason: the
        # client-side re-aggregation must be able to skip them rather than average in zeros.
        "tool_calls": _opt_int(r.get("tool_calls")),
        "repeated_calls": _opt_int(r.get("repeated_calls")),
        "refused_calls": _opt_int(r.get("refused_calls")),
        "turns_to_first_edit": _opt_int(r.get("turns_to_first_edit")),
    } for r in runs]
    return {
        "projects": projects,
        "project": project,
        "runs": runs_out,
        "knowledge_ab": _knowledge_ab(tasks),
        "by_day": {k: round(by_day[k], 4) for k in sorted(by_day)},
        "by_model": _sum_by("model"),
        "by_harness": _sum_by("harness"),
        "by_role": _sum_by("role"),
        "tasks": tasks,
        "totals": {
            "cost_usd": total_cost,
            "tokens": sum(t["tokens"] for t in tasks),
            "tasks": n,
            "avg_cost_per_task": round(total_cost / n, 4) if n else 0.0,
            "avg_wall_s": round(sum(walls) / len(walls), 1) if walls else 0.0,
            "agent_runs": len(runs),
        },
    }


def cost_dashboard(project: str | None = None, table_name: str | None = None) -> dict:
    """The full payload for GET /api/metrics — scan + per-project shape. Always returns a dict."""
    return dashboard(scan_records(table_name), project=project)
