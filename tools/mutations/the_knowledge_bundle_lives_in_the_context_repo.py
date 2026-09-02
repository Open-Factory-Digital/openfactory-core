"""The knowledge bundle moves from an orphan branch to the context repository.

D-2/D-3 (OKF-PORT-PLAN.md): the bundle lives at `.okf/repos/<owner>--<name>/` inside the project's
context repository, on that repository's own default branch, alongside the onboarding docs already
there — never on a dedicated orphan branch inside the client's own source repo.

ROW 1 is the fix this whole change turned on: guessing a branch name to clone (the way the old
`KNOWLEDGE_BRANCH` constant let `fetch_published_bundle` do) treats "the branch exists under a
different name" identically to "nothing published yet" — caught by
`test_the_branch_is_DISCOVERED_not_a_guess`, the one test in the suite whose context repository's
real branch is deliberately not `main`.

ROW 2 is D-2 itself: one folder per source. Without the source-name flattening, two source repos
in one multirepo project silently clobber each other's bundle.

ROW 3 is the disk-fill regression this change's own design doc called out by name: a fixed hop
count (`bundle_dir.parent.parent`) stopped matching the day the relocation added two more path
segments, so the safety guard would silently do nothing and leak one temp directory per job.

ROW 4 is `activities.py`'s new gate: a project with no context repository must degrade to
`"no-context"`, never crash and never silently publish to a URL built from an empty string.

ROW 5 is the property `publish_bundle`'s docstring promises: a rejected push (someone else
committed to the shared branch first) is retried once, not silently dropped.

ROWS 6-10 ARE THE REFRESH GOING BACK TO WAITING FOR A MERGE. The bundle describes the BASE BRANCH
(`KnowledgeRefreshInput` says so itself), and until this change one thing refreshed it: the
`JobState.MERGED` branch. On `merge_policy: human` — the default — a job ends at `PR_OPEN` and the
map ages for as long as nobody merges. Every row here produces a deployment where the schedule
exists on paper and refreshes nothing: never reconciled at boot (6), starting a workflow type the
worker does not register (7) — the failure that repeats every tick for ever and reads on the panel
as a quiet repository rather than a broken watcher — the cheapest trigger dropped because a
schedule now exists (8), the orphan left firing for a project the deployment no longer has (9),
and overlapping ticks queuing into a backlog on the one repository slow enough to overrun its own
interval (10).

TWO ROWS WERE WRITTEN AND CUT, DELIBERATELY NOT KEPT — a row this suite cannot kill is decoration,
not a guard, the same principle `a_project_declares_what_it_is.py` states for its own plan.
Unscoped `git add -A` in `_stage_bundle` has no observable effect in any reachable scenario: the
only content ever present in `pub` between clone and commit is exactly what this function itself
wrote, so scoped and unscoped staging produce byte-identical diffs — the scoping is defence in
depth against a future change to this function, not a testable property of the current one. The
reintroduced manual `git init` orphan fallback only actually diverges from the fixed `checkout -B`
path when `current_branch` misreports a NON-empty clone as empty — a failure mode specific to a
raw git server that does not track a repository's default branch before its first commit, which
none of the three forges this platform supports (GitHub, Azure Repos, GitLab) exhibits; the fixed
code is still strictly better (it reuses the clone instead of discarding it), it just has no
failing scenario this suite can construct without simulating a forge-behaviour bug that is not
this platform's to guard against.
"""

TEST = "tests/test_knowledge_pipeline.py"

MUTATIONS = [
    ("the fetch guesses a branch name again, so a context repo whose default branch isn't the "
     "guess reads as 'nothing published' — and the next publish tries to push disconnected "
     "history onto the real branch, rejected forever",
     "openfactory/knowledge/pipeline.py",
     '    rc, out = _git("clone", "--depth", "1", remote_url, str(pub))\n'
     "    if rc != 0:\n"
     '        _log.info("knowledge: could not clone the context repository (%s)", '
     "out.strip()[:200])",
     '    rc, out = _git("clone", "--depth", "1", "--branch", "main", remote_url, str(pub))\n'
     "    if rc != 0:\n"
     '        _log.info("knowledge: could not clone the context repository (%s)", '
     "out.strip()[:200])"),

    ("the source-name flattening is dropped, so two source repos in one multirepo project "
     "collide on the same .okf/repos/ folder and clobber each other's bundle",
     "openfactory/knowledge/pipeline.py",
     '    flat = (source_repo or "unknown").strip().strip("/").replace("/", "--")\n'
     "    return Path(OKF_DIRNAME) / OKF_REPOS_DIRNAME / flat",
     '    return Path(OKF_DIRNAME) / OKF_REPOS_DIRNAME / "shared"'),

    ("discard reverts to a fixed hop count, so it silently stops matching the fetched bundle's "
     "deeper subpath and leaks one temp directory per job — a disk-fill regression, not a crash",
     "openfactory/knowledge/pipeline.py",
     "    if bundle_dir is None:\n"
     "        return\n"
     "    for ancestor in (bundle_dir, *bundle_dir.parents):\n"
     '        if ancestor.name.startswith("openfactory-knowledge"):  # only rmtree OUR OWN\n'
     "            shutil.rmtree(ancestor, ignore_errors=True)\n"
     "            return",
     "    if bundle_dir is None:\n"
     "        return\n"
     "    root = bundle_dir.parent.parent\n"
     '    if root.name.startswith("openfactory-knowledge"):\n'
     "        shutil.rmtree(root, ignore_errors=True)"),

    ("the activity's no-context gate is removed, so a project with no context repository either "
     "crashes or silently publishes to a URL built from an empty repo name",
     "openfactory/runtime/temporal/activities.py",
     '    docs_repo = (getattr(getattr(project, "product", None), "docs_repo", "") or "").strip()\n'
     "    if not docs_repo:\n"
     '        return "no-context"',
     '    docs_repo = "owner/does-not-matter"'),

    ("a rejected push is never retried, so two publishers racing on the shared branch silently "
     "drop the loser's map instead of re-cloning the new tip and re-applying once",
     "openfactory/knowledge/pipeline.py",
     "        for attempt in (1, 2):",
     "        for attempt in (1,):"),

    # ── the refresh goes back to waiting for a merge ─────────────────────────────────────────────
    ("the refresh schedule is never reconciled at boot, so it exists in the source and in no "
     "deployment — the exact defect `ensure_all` was written for, one schedule later",
     "openfactory/runtime/temporal/schedule.py",
     "    out += await ensure_okf_refresh()\n",
     "",
     "tests/test_schedules_are_reachable.py"),

    ("the schedule starts a workflow type the worker does not register, so every tick fails with "
     "an unregistered type — for ever, and on the panel it reads as a quiet repository rather "
     "than a watcher that cannot run",
     "openfactory/runtime/temporal/worker.py",
     "                   KnowledgeRefreshWorkflow],",
     "                   ],",
     "tests/test_the_map_does_not_wait_for_a_merge.py"),

    ("the merge-time refresh is dropped because a schedule now exists, costing every project its "
     "freshest trigger — the one moment the worktree is already there and the map is already "
     "known to be behind",
     "openfactory/runtime/temporal/workflow.py",
     "            await self._refresh_knowledge(params)",
     "            pass",
     "tests/test_the_map_does_not_wait_for_a_merge.py"),

    ("the new per-project prefix is left out of the orphan retirement, so a removed project keeps "
     "a refresh firing every six hours against a registry that does not have it — the live defect "
     "`retire_orphan_schedules` exists for, reintroduced by adding a third schedule",
     "openfactory/runtime/temporal/schedule.py",
     "    for prefix in (WATCH_SCHEDULE_PREFIX, PRODUCT_SCHEDULE_PREFIX, OKF_SCHEDULE_PREFIX):",
     "    for prefix in (WATCH_SCHEDULE_PREFIX, PRODUCT_SCHEDULE_PREFIX):",
     "tests/test_the_map_does_not_wait_for_a_merge.py"),

    ("overlapping ticks queue instead of being dropped, so the one repository slow enough to "
     "outlast its own interval turns a refresh into a backlog that never drains",
     "openfactory/runtime/temporal/schedule.py",
     "            execution_timeout=timedelta(minutes=15),\n"
     "        ),\n"
     "        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec("
     "every=timedelta(hours=every_hours))]),\n"
     "        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),\n"
     "    )\n"
     "\n"
     "\n"
     "async def ensure_okf_refresh",
     "            execution_timeout=timedelta(minutes=15),\n"
     "        ),\n"
     "        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec("
     "every=timedelta(hours=every_hours))]),\n"
     "        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),\n"
     "    )\n"
     "\n"
     "\n"
     "async def ensure_okf_refresh",
     "tests/test_the_map_does_not_wait_for_a_merge.py"),
]
