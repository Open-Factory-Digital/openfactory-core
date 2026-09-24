"""#184, proven by breaking it — only a blocking build failure is broken code.

After the table landed, "nothing gates this merge" was still one word for two facts, and one log was
still attached to every red check a repair could be about. So a pull request nothing had looked at
was self-merged as if green, a required commit status was "repaired" from some other run's log,
Azure DevOps offered a red blocking policy to the self-heal as `unstable`, and an advisory failure
was said nowhere on the card.

FIVE CLAIMS:

  1. **The port has five words for four cases, and every row says them.** `none` is nothing ran
     (a skipped check did not run); `advisory` is checks that ran and gate nothing — from the
     table, from Azure DevOps, from GitHub, and from a row that only answers the aggregate.
  2. **The log is the red blocking build's own.** A typed forge's log is evidence about its `code`
     rows only; GitHub reads the run the red REQUIRED workflow check links to, in the pull
     request's own repository, and never a run a status's link points at.
  3. **A red blocking policy is never offered to the self-merge** on Azure DevOps.
  4. **Nothing ran is waited on, then said, and never merged by the machine**; an advisory failure
     is said on the card. Driven on the real `JobWorkflow`, on a real (time-skipping) engine.
  5. **A job already in the watch replays what it recorded.** The marker row is red through a REAL
     replay of a history recorded on the pre-marker arm.

The guard is `tests/test_only_a_blocking_build_failure_is_broken_code.py`.
"""

TEST = "tests/test_only_a_blocking_build_failure_is_broken_code.py"

CHECKS = "openfactory/contracts/checks.py"
ADO = "openfactory/adapters/forge/azure_devops.py"
GITHUB = "openfactory/adapters/forge/github.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"

MUTATIONS = [
    # ── claim 1: five words for four cases ────────────────────────────────────────────────────
    ("THE DEFECT ITSELF, IN THE TABLE: nothing ran and nothing gates are one word again", CHECKS,
     "            verdict = ADVISORY if any(c.bucket != SKIP for c in checks) else NOTHING_RAN\n",
     "            verdict = NOTHING_RAN\n"),

    ("a check the forge skipped counts as one that ran", CHECKS,
     "            verdict = ADVISORY if any(c.bucket != SKIP for c in checks) else NOTHING_RAN\n",
     "            verdict = ADVISORY if checks else NOTHING_RAN\n"),

    ("a row that only answers the aggregate says `advisory` and is read as an unreadable gate",
     CHECKS,
     "    if verdict == ADVISORY:\n",
     "    if False:\n"),

    ("Azure DevOps: optional policies alone read `none`, as if nothing had been evaluated", ADO,
     '        return "advisory" if ran else "none"\n',
     '        return "none"\n'),

    ("Azure DevOps: a policy that does not apply to the pull request counts as one that ran", ADO,
     "        ran = [e for e in evaluations\n"
     '               if _POLICY_BUCKET.get(str(e.get("status") or ""), "pending") != "skip"]\n',
     "        ran = list(evaluations)\n"),

    ("GitHub: workflows that ran and are not required read `none` (F-02's repository)", GITHUB,
     '        return "none" if ran == "none" else "advisory"\n',
     '        return "none"\n'),

    ("GitHub: an all-skipped set of checks reads as green", GITHUB,
     '    buckets = {(c.get("bucket") or "").lower() for c in checks} - {"skipping"}\n',
     '    buckets = {(c.get("bucket") or "").lower() for c in checks}\n'),

    # ── claim 2: the log is the red blocking build's own ──────────────────────────────────────
    ("THE BLIND REPAIR WITH A LOG IN HAND: a typed forge's build log is handed to an `unknown` "
     "check too — a required status, a CLA bot", CHECKS,
     "             and (c.kind == CODE if typed else c.kind != PROCESS)]\n",
     "             and c.kind != PROCESS]\n"),

    ("GitHub: the run of a red check nothing requires is read as the failure's log", GITHUB,
     '            if not (row["blocking"] and row["kind"] == "code"\n',
     '            if not (row["kind"] == "code"\n'),

    ("GitHub: a status's link to a workflow run is followed as if it were that run's check",
     GITHUB,
     '            if not (row["blocking"] and row["kind"] == "code"\n',
     '            if not (row["blocking"]\n'),

    ("GitHub: a run of another repository is read as this pull request's build (C-18)", GITHUB,
     "            if named and named.group(1).lower() == repo.lower():\n",
     "            if named:\n"),

    # ── claim 3: a red blocking policy is never offered to the self-merge ─────────────────────
    ("Azure DevOps: a red BLOCKING policy is not `blocked`, so the self-heal merges past it with "
     "`bypassPolicy`", ADO,
     '        if ci in ("pending", "failure"):\n',
     '        if ci in ("pending",):\n'),

    # ── claim 4: the watch ────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF, IN THE WATCH: the self-heal merges a pull request nothing verified",
     WORKFLOW,
     '                      and workflow.patched("merge-self-heal-clean") and not unverified):\n',
     '                      and workflow.patched("merge-self-heal-clean")):\n'),

    ("past the bound the merge is not handed to a person — the card still says the machine has it",
     WORKFLOW,
     "                    auto = bool(result.auto_merge) and not (\n"
     "                        unverified and quiet >= _NOTHING_RAN_GRACE)\n",
     "                    auto = bool(result.auto_merge)\n"),

    ("nothing ran is never said on the card", WORKFLOW,
     "                    if unverified:\n"
     "                        said.append(nothing_ran_note(quiet, _NOTHING_RAN_GRACE))\n",
     "                    if False:\n"
     "                        said.append(nothing_ran_note(quiet, _NOTHING_RAN_GRACE))\n"),

    ("the silence restarts at every read, so the bound is never reached and nothing is ever said",
     WORKFLOW,
     "            quiet_since = (quiet_since or workflow.now()) if unverified else None\n",
     "            quiet_since = workflow.now() if unverified else None\n"),

    ("there is no bound: a pull request a second old is told that nothing ran", WORKFLOW,
     "_NOTHING_RAN_GRACE = timedelta(minutes=10)\n",
     "_NOTHING_RAN_GRACE = timedelta(0)\n"),

    ("the waited-on sentence and the said one are the same, so the bound changes nothing on the "
     "card", CHECKS,
     "    if quiet < bound:\n",
     "    if True:\n"),

    ("an advisory failure is not said on the card", WORKFLOW,
     "                    if asked is not None and asked.advisory:\n",
     "                    if False:\n"),

    # ── claim 5: jobs already in the watch ────────────────────────────────────────────────────
    ("the new wait is not behind its marker, so a job already in the watch cannot replay",
     WORKFLOW,
     '                          and workflow.patched("nothing-ran-is-not-green"))\n',
     "                          and True)\n"),
]
