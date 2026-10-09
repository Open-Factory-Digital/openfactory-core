"""The outcome aggregates: what a deployment's factory did over a window, read from its journals and
its metrics store, and carried into the evidence pack (#356, second slice, part B).

Run:  .venv/bin/python tools/mutate.py tools/mutations/356_outcomes.py

The claims, each a row below that must go RED:

  THE ENDING IS READ, NEVER INFERRED — a job ends at the journal's ending line (`record_outcome`'s,
  or a stop's), never at the box's last progress mark; the deploy watch's later line is the card's,
  not another job; a job is in the window where it ended; an ending nobody defined carries no word
  of its own.

  UNMEASURED IS NULL, NEVER ZERO — no store, an unreadable store, an unreadable journal, no
  journal directory, a median of nothing: each is `None` with its reason; a pass with no price
  makes its ticket's cost unknown, never cheaper.

  THE MEASURES — the p90 is a cost somebody paid; a merged ticket's cost is every pass on its card
  and only its project's; repair passes are the repair roles' passes inside the job's span;
  rejections are the reviews that said no; pickup to pull request ends at `pr_open`; parks are read
  into the tech-lead's classes from the card record, and only where the record covers the window;
  Needs Action ages from the move that began the wait; versions come from the job rows' stamps,
  and `record_job` stamps them; re-proofs are the prove passes in the window.

  THE PACK — `certify deployment` fills `outcomes` from this function.
"""

TEST = "tests/test_the_outcomes_are_read_never_inferred.py"

QUERY = "openfactory/observability/query.py"
JOB_RECORD = "openfactory/observability/job_record.py"
PACK = "openfactory/certify/pack.py"

T = TEST + "::"

MUTATIONS = [
    # ── the ending is read, never inferred ──────────────────────────────────────────────────────
    ("the box's own progress lines are read as endings", QUERY,
     '    return event.get("kind") == "state" and isinstance(event.get("data"), dict) \\\n'
     '        and "by" in event["data"]',
     '    return event.get("kind") == "state"',
     T + "test_a_jobs_ending_is_the_line_the_workflow_wrote_never_its_last_progress_mark"),

    ("a job with no ending line is closed at its last progress mark", QUERY,
     "    if current is not None:\n        jobs.append(current)\n    return jobs",
     "    if current is not None:\n        current.end, current.state = current.last, "
     "\"pr_open\"\n        jobs.append(current)\n    return jobs",
     T + "test_a_jobs_ending_is_the_line_the_workflow_wrote_never_its_last_progress_mark"),

    ("the deploy watch's later ending is counted as another job", QUERY,
     "            if current is not None:\n"
     "                current.end, current.state = when, str(event.get(\"message\") or \"\").strip()\n"
     "                jobs.append(current)\n"
     "                current = None\n"
     "            continue",
     "            if current is None:\n"
     "                current = _Job(project=project, ticket=\"\", start=when, last=when)\n"
     "            current.end, current.state = when, str(event.get(\"message\") or \"\").strip()\n"
     "            jobs.append(current)\n"
     "            current = None\n"
     "            continue",
     T + "test_the_deploy_watchs_later_ending_is_not_another_job"),

    ("a job is in the window where it began, not where it ended", QUERY,
     "    closed = [j for j in jobs if j.end is not None and inside(j.end)]",
     "    closed = [j for j in jobs if j.end is not None and inside(j.start)]",
     T + "test_a_job_is_in_the_window_where_it_ended"),

    ("an ending nobody defined is counted under its own word", QUERY,
     '            word = j.state if j.state in known else "unrecognised"',
     "            word = j.state",
     T + "test_a_stop_is_an_ending_and_an_ending_nobody_defined_names_no_word_of_its_own"),

    # ── unmeasured is null, never zero ──────────────────────────────────────────────────────────
    ("no readable store reads as an empty one", QUERY,
     "        if sink is None:\n            return None, _NO_STORE",
     "        if sink is None:\n            return [], \"\"",
     T + "test_nothing_to_read_is_null_with_a_reason_for_every_measure"),

    ("an unreadable store reads as an empty one", QUERY,
     "        return None, _UNREADABLE",
     "        return [], \"\"",
     T + "test_an_unreadable_store_is_not_an_empty_one"),

    ("an unreadable journal is skipped", QUERY,
     "                unread += 1\n    if unread:",
     "                unread += 0\n    if unread:",
     T + "test_an_unreadable_journal_is_not_an_empty_one"),

    ("no journal directory anywhere reads as no job", QUERY,
     "    if names and not found:",
     "    if False:",
     T + "test_nothing_to_read_is_null_with_a_reason_for_every_measure"),

    ("a median of nothing is zero", QUERY,
     "        if waits:\n",
     "        if True:\n            waits = waits or [0.0]\n",
     T + "test_a_median_of_nothing_is_null_not_zero"),

    ("a pass with no price counts as free", QUERY,
     "            if costs and all(isinstance(x, int | float) and not isinstance(x, bool)\n"
     "                             for x in costs):\n"
     "                priced.append(float(sum(costs)))",
     "            if costs:\n"
     "                priced.append(float(sum(x or 0 for x in costs)))",
     T + "test_a_merged_tickets_cost_is_every_pass_on_its_card_and_an_unpriced_pass_is_unknown"),

    # ── the measures ────────────────────────────────────────────────────────────────────────────
    ("the p90 is interpolated", QUERY,
     "    return float(ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)])",
     "    return float(statistics.quantiles(ordered, n=10)[-1]) if len(ordered) > 1 "
     "else float(ordered[0])",
     T + "test_the_p90_is_a_cost_somebody_paid"),

    ("a pass is joined across projects by its ref alone", QUERY,
     "            passes.setdefault((owner, canonical_ref(row.get(\"ticket\"))), []).append(",
     "            passes.setdefault((\"acme\", canonical_ref(row.get(\"ticket\"))), []).append(",
     T + "test_a_merged_tickets_cost_is_every_pass_on_its_card_and_an_unpriced_pass_is_unknown"),

    ("a merged ticket's cost is only its last pass", QUERY,
     "            costs = [cost for _, _, cost in passes.get(key, [])]",
     "            costs = [cost for _, _, cost in passes.get(key, [])][-1:]",
     T + "test_a_merged_tickets_cost_is_every_pass_on_its_card_and_an_unpriced_pass_is_unknown"),

    ("every pass counts as a repair", QUERY,
     "                repairs.append(sum(1 for role in mine if role in REPAIR_ROLES))",
     "                repairs.append(len(mine))",
     T + "test_review_rejections_and_repair_passes_are_counted_per_job"),

    ("a pass outside the job's span is counted against it", QUERY,
     "                    if when is not None and j.start <= when <= j.end]",
     "                    if when is not None]",
     T + "test_review_rejections_and_repair_passes_are_counted_per_job"),

    ("an approving review counts as a rejection", QUERY,
     '        str(event.get("message") or "").strip().lower().startswith("rejected")',
     "        True",
     T + "test_review_rejections_and_repair_passes_are_counted_per_job"),

    ("pickup to pull request runs to the job's ending", QUERY,
     "        waits = [(j.pr_open - j.start).total_seconds() for j in closed if j.pr_open is not None]",
     "        waits = [(j.end - j.start).total_seconds() for j in closed if j.pr_open is not None]",
     T + "test_pickup_to_pull_request_is_the_jobs_first_line_to_its_pr_open"),

    ("a park's note is not read: every park is unknown", QUERY,
     "                cause = classify(text, state=state).cause",
     '                cause = "unknown"',
     T + "test_parks_are_read_into_the_tech_leads_classes_from_the_card_record"),

    ("a park outside the window is counted", QUERY,
     '            if row.event == "parked" and inside(_moment(row.ts)):',
     '            if row.event == "parked":',
     T + "test_parks_are_read_into_the_tech_leads_classes_from_the_card_record"),

    ("the record is read even where it began after a job in the window", QUERY,
     "    if cover:\n        gaps[\"parks\"] = gaps[\"needs_action\"] = cover\n        return",
     "    if False:\n        return",
     T + "test_parks_are_null_where_the_card_record_began_after_a_job_in_the_window"),

    ("a record that began before the window is not trusted to cover it", QUERY,
     "        if began is not None and began <= start:\n            before = []",
     "",
     T + "test_a_card_record_that_began_before_the_window_covers_it"),

    ("a question asked of a parked card restarts its clock", QUERY,
     "            if r.after != waiting:\n                break\n            began_waiting = t",
     "            break",
     T + "test_needs_action_is_the_oldest_wait_at_the_windows_end"),

    ("a card that left Needs Action is still counted", QUERY,
     "        if not moves or moves[-1][0].after != waiting:",
     "        if not moves or not any(r.after == waiting for r, _ in moves):",
     T + "test_needs_action_is_the_oldest_wait_at_the_windows_end"),

    ("an unstamped job row is counted as some version", QUERY,
     "            if _VERSION.fullmatch(version) and _BUILD.fullmatch(build):",
     "            if True:",
     T + "test_the_versions_seen_are_the_job_rows_stamps_and_an_old_row_is_unstamped"),

    ("a job row is not stamped with the platform that ran it", JOB_RECORD,
     '            pr_url=pr_url, knowledge=knowledge, extra={"platform": platform_stamp()}))',
     "            pr_url=pr_url, knowledge=knowledge))",
     T + "test_every_job_row_carries_the_platform_that_ran_it"),

    ("every prove pass ever made is a re-proof in the window", QUERY,
     "                reproofs += 1 if inside(when) else 0",
     "                reproofs += 1",
     T + "test_reproofs_are_the_prove_passes_in_the_window"),

    # ── the pack ────────────────────────────────────────────────────────────────────────────────
    ("certify deployment never binds the outcomes' reader", PACK,
     "    reading.outcomes = _outcomes_of([p.name for p in rows])",
     "    reading.outcomes = None",
     T + "test_certify_deployment_fills_its_outcomes_from_the_journals_and_the_store"),
]
