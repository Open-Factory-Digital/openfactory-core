"""A job run from the terminal is measured like one the engine ran — proven by breaking it.

Found by walking the one-machine door (2026-09-11): a real card ran to Done and the deployment's
metrics database held one row — a channel message. The cost rows were the durable path's alone,
and on that runtime the durable path is optional.

FOUR CLAIMS:

  1. **The attended driver records the job** — one `job` row per attempt, with what the attempt
     did on it.
  2. **And every agent pass**, because the dashboard slices by model and harness.
  3. **Both attended commands go through one place**, so neither can forget.
  4. **Telemetry never touches the job** — a sink that cannot be built changes nothing.

The guard under test is `tests/test_the_attended_driver_records_what_it_spent.py`.
"""

TEST = "tests/test_the_attended_driver_records_what_it_spent.py"

CLI = "openfactory/cli.py"
REC = "openfactory/observability/job_record.py"

MUTATIONS = [
    # ── 1 & 2. the rows ────────────────────────────────────────────────────────────────────────
    ("the attended driver records nothing again, and the one-machine door measures nothing", CLI,
     "    record_job(project=view.name, issue=str(issue),",
     "    _ = lambda **kw: None; _(project=view.name, issue=str(issue),", TEST),

    ("the job summary is dropped, so an attempt leaves passes nothing ties together", REC,
     '        sink.record(MetricRecord(\n'
     '            project=project, ticket=issue, ts=ts, kind="job", role="_job_",',
     '        _ = lambda *a, **k: None\n        _(MetricRecord(\n'
     '            project=project, ticket=issue, ts=ts, kind="job", role="_job_",', TEST),

    ("the per-pass rows are dropped, and spend by model or harness cannot be read", REC,
     "        for entry in agent_runs:", "        for entry in ():", TEST),

    ("the attempt stops saying how it ended", CLI,
     '               state=getattr(result.state, "value", str(result.state)),',
     '               state="",', TEST),

    ("nothing is timed, so a job that took an hour looks like one that took a second", CLI,
     "               wall_s=round(time.monotonic() - started, 1),", "               wall_s=None,",
     TEST),

    ("the pull request the job opened is left off its row", CLI,
     '               total_cost_usd=result.total_cost_usd, pr_url=result.pr_url or "",',
     "               total_cost_usd=result.total_cost_usd,", TEST),

    # ── 3. one place, both commands ────────────────────────────────────────────────────────────
    ("`poll` goes back to driving the job itself, past the record", CLI,
     "        result = _drive_one(project, str(num), sandbox=box, image=resolved)",
     "        result = build_runner(project, str(num), sandbox=box, image=resolved,\n"
     "                              review=True).run(str(num))", TEST),

    ("`run` goes back to driving the job itself, past the record", CLI,
     "    result = _drive_one(view, issue, sandbox=box, image=resolved, review=review)",
     "    result = build_runner(view, issue, sandbox=box, image=resolved,\n"
     "                          review=review).run(issue)", TEST),

    # ── 4. additive, always ────────────────────────────────────────────────────────────────────
    ("a sink that cannot be built takes the job down with it", REC,
     "    except Exception as exc:  # noqa: BLE001 — telemetry is additive; never fail the job\n"
     "        log.info(\"job telemetry for %s#%s was not recorded (%s)\", project, issue, "
     "str(exc)[:160])",
     "    except ValueError as exc:\n"
     "        log.info(\"job telemetry for %s#%s was not recorded (%s)\", project, issue, "
     "str(exc)[:160])", TEST),
]
