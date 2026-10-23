"""#788, criterion 1: a Kimi planner that writes to the job's workspace holds the job before its
edit reaches a commit, a pause or a push.

The guard is `tests/test_a_kimi_planner_that_writes_holds_the_job_before_its_edit_reaches_a_commit
.py` (T1). It drives the real `JobRunner` through the box's own `run` over a repository with a
bare origin. The check lives in three places: the scope constant in `adapters/agent/base.py`, the
fingerprint in `orchestrator/read_only_pass.py`, and the check in `JobRunner.run`. One cut per
property, each aimed at the row that holds it:

  1. **The scope.** Only a harness whose planner is read-only by instruction only is measured.
     S1 empties `PLANNERS_READ_ONLY_BY_INSTRUCTION`, and every row that needs the check goes red.
     S2 widens the gate to `codex`, and the reverse row 1g goes red (Q2's default, pinned).
  2. **The fingerprint sees every way in.** F1 `git add -A` -> `git add -u`: a new file is not
     seen. F2 HEAD not read (the mark carries the tree twice): a planner that commits a file and
     deletes it leaves the tree equal and goes unseen. F3 the tree replaced by a hash of
     `git status --porcelain`: an append to a file setup left untracked (`?? build.log` before
     and after) goes unseen.
  3. **Could not see is never clean** (engineering lesson 2). U1 the exit code ignored, so a
     walled answer whose last two lines are hashes reads as a mark. U2 an unreadable workspace
     before the pass no longer stops the job before the pass is run and paid for. U3 and U4 an
     unreadable workspace after the pass: the branch deleted, or the answer read as the
     before-mark. U5 the fingerprint goes on after git's first refusal (`|| exit` dropped), and
     the hold says git's refusal three times under `exit 1`.
  4. **The hold wins, names what was written, and pushes nothing.** H1 the check asked after the
     pause, so `_paused` -> `_preserve_partial` pushes the edit. H2 the hold is said and not
     returned, so the job goes on. H3 and H4 the paths dropped from the hold's sentence, or from
     the journal warning. H5 `_preserve_for_hold` called before the hold, so the edit is pushed.
     H6 the before-mark taken above `_run_setup`, so what setup left is charged to the planner.
  5. **Each hold says what it is** (review round 1 on e2b57dd1). The workflow classifies a hold
     that declares no cause by its prose, and the planner-wrote hold's prose carries the paths:
     `src/rate_limit.py` read as ('transient', 'throttled'). C1 drops `hold_cause=UNKNOWN` from
     that hold; C2 drops `hold_cause=ENVIRONMENT` from the hold before the pass. C3, which
     dropped it from the hold after the pass, moved to
     `981_a_planner_that_makes_the_workspace_unreadable_is_held_as_its_doing.py` (#981): that
     hold is the planner's doing and declares `unknown` now, and `_HOLD_AFTER` is re-pinned to it.
     C1's anchor carries the line above it since #981: the after-pass hold's
     `JobState.ON_HOLD, branch=branch, hold_cause=UNKNOWN)` would match it a second time.
  6. **The remedy names a role that exists** (review round 1 on e2b57dd1, point 3). The planner
     runs on the executor's harness and `harness_kind(None, "planner")` raises, so R1 puts back
     "Give the planner another harness", the sentence 6db1677c held with.
  7. **The fingerprint keeps its own promises** (review round 1 on e2b57dd1, not blocking: five
     cuts of `read_only_pass.py` left all 19 rows green). P1 drops `GIT_INDEX_FILE`, so the real
     index is written and setup's leftover reads `A  build.log` to the planner. P2 drops
     `rm -f "$t"`, so the index copy stays in the git dir. P3 makes `_diff_names` answer `[]`
     when git names no path, so a changed tree reads as nothing written. P4 drops the `SHOWN`
     bound, so 25 paths are named with no "and 5 more". P5 drops `--no-renames`, so a `git mv`
     names only the path it came to.
  8. **What is measured is what is pushed** (review round 2 on dc0efac4, point 2: `publish_branch`
     pushes the job's branch by name, and a planner that moved it alone was not held). B1 reads no
     ref HEAD is on, so a planner that checks out `elsewhere` is not held. B2 reads no job branch,
     so the reviewer's double (HEAD detached where it stood, the branch moved to a commit carrying
     `planted.txt`) is held by the ref alone and names no path. B3 tells the fingerprint no branch
     name, with the same effect. B4 and B5 drop the moved ref's entry, and the moved branch's, from
     what `written` names.
  9. **The reviewer's surviving cuts** (review round 2 on dc0efac4, point 3). K7 leaves top-level
     dot paths out of the fingerprint's add (`git add -A -- . ":(exclude).*"`): on dc0efac4 it left
     T1 and the documents guard green, 46 passed and 4 skipped, because no row wrote a dot path.
     The row whose planner writes `.openfactory/project.yaml` goes red under it.
     K9 (#967) drops ", or turn `planner_stage` off in its `.openfactory/project.yaml`" from the
     hold's remedy, which left every row green on dc0efac4; `_assert_held_naming` now asks for it.

HOW THE CUTS DIFFER FROM THE PLAN'S SKETCH (task 17), because the code differs from it:
  - `fingerprint` returns `Mark | Unreadable`, not `Mark | None`. U1 removes `rc == 0` from the
    condition that reads the hashes. Every non-zero exit of `FINGERPRINT` itself ends in git's
    prose, so no existing row could see that cut; the row it aims at answers the box's own wall
    (`timeout_result`) over the real fingerprint's output.
  - "Drop `git rev-parse HEAD`, reading the head as `''`" is F2 instead. Dropping the line leaves
    one line of output, so every mark is `Unreadable` and every row goes red for that reason, not
    for the commit. `written` refuses `''` with `ValueError`. And the existing commit row is
    caught by the tree alone, because the committed file is in the tree `git add -A` would commit.
    F2 keeps the mark well-formed, with the tree in place of HEAD, and is aimed at a row where only
    HEAD moved: a planner that commits a file and then deletes it. Since round 2 the job's branch
    moves with HEAD there and still holds the job under F2; the row goes red because the hold no
    longer says "a commit made during the pass" (a branch that moves with HEAD is said by HEAD).
  - F3 hashes the porcelain rather than printing it raw, so the mark stays two hashes. Raw
    porcelain would make every mark `Unreadable`, not unseen.
  - U2, U3, U4 and U5 are not in the sketch. U2 and U3/U4 hold the two `Unreadable` branches the
    check grew in task 13 (the hold before the pass, the hold after it). U5 holds task 16's fix.
  - H5 calls the `_preserve_for_hold(ticket, ws, resume_handle)` that exists, and H6 moves the
    whole block between `_run_setup` and the before-mark, because a cut is one replacement.
"""

TEST = "tests/test_a_kimi_planner_that_writes_holds_the_job_before_its_edit_reaches_a_commit.py"

CREATE = TEST + "::test_a_planner_that_creates_a_file_holds_the_job_and_names_it"
COMMIT_AND_DELETE = TEST + ("::test_a_planner_that_commits_a_file_and_deletes_it_holds_the_job"
                            "_naming_it")
REWRITE_SETUP = TEST + "::test_a_planner_that_rewrites_what_setup_left_holds_the_job"
PAUSE = TEST + "::test_a_planner_that_writes_and_then_pauses_pushes_nothing"
UNASKABLE = TEST + ("::test_a_workspace_that_cannot_be_asked_holds_the_job_rather_than_reading_as"
                    "_clean")
UNASKABLE_AFTER = TEST + "::test_a_workspace_that_cannot_be_asked_after_the_pass_holds_the_job"
WALLED = TEST + "::test_a_fingerprint_the_box_walled_is_not_read_even_with_both_hashes_printed"
GIT_REFUSES = TEST + ("::test_a_workspace_git_refuses_holds_the_job_with_gits_exit_and_its_words"
                      "_once")
SETUP_NOT_CHARGED = TEST + "::test_what_setup_leaves_in_the_tree_is_not_charged_to_the_planner"
SCOPE = TEST + "::test_a_harness_whose_planner_cannot_write_is_not_asked"
THROTTLING = TEST + "::test_a_planner_hold_is_not_read_as_throttling_whatever_the_path"
REAL_INDEX = TEST + "::test_the_fingerprint_leaves_the_real_index_and_no_copy_behind"
NO_NAMES = TEST + "::test_a_tree_that_changed_holds_even_when_git_names_no_path"
MANY = TEST + "::test_a_planner_that_writes_many_files_is_named_up_to_the_bound"
RENAME = TEST + "::test_a_planner_that_renames_a_file_holds_the_job_naming_both_paths"
MOVES_BRANCH = TEST + "::test_a_planner_that_moves_the_job_branch_holds_the_job_naming_it[{}]"
OTHER_BRANCH = TEST + ("::test_a_planner_that_puts_head_on_another_branch_holds_the_job_naming_it"
                       "[{}]")
DOT_PATH = TEST + ("::test_a_planner_that_writes_the_project_manifest_holds_the_job_naming_it"
                   "[{}]")
AS_ENVIRONMENT = TEST + "::test_a_workspace_that_cannot_be_asked_is_held_as_the_environment[{}]"

BASE = "openfactory/adapters/agent/base.py"
PASS = "openfactory/orchestrator/read_only_pass.py"
MACHINE = "openfactory/orchestrator/machine.py"

_GATE = ('                measured = getattr(self.agent, "name", "") in '
         'PLANNERS_READ_ONLY_BY_INSTRUCTION\n')
_BEFORE = '                before = fingerprint(self.sandbox, ws) if measured else None\n'
_HOLD_BEFORE = (
    '                if isinstance(before, Unreadable):\n'
    '                    # decided before the pass is paid for: a pass '
    'nobody can check is not run\n'
    '                    return self._hold(ticket, owner, self._unaskable(before, "before the '
    'planner "\n'
    '                                      "ran"), JobState.ON_HOLD, branch=branch,\n'
    '                                      hold_cause=ENVIRONMENT)\n'
)
_HOLD_AFTER = (
    '                    if isinstance(after, Unreadable):\n'
    "                        # THE PLANNER'S DOING, NOT THE BOX'S (#981): the before-mark was read, "
    'so\n'
    '                        # git was usable here when the pass began. A planner that runs `git '
    'init\n'
    '                        # sub` makes `git add -A` exit 128, and "Make git usable in the box" '
    'named\n'
    '                        # the wrong party. It declares what the planner-wrote hold declares.\n'
    '                        return self._hold(ticket, owner, '
    'self._unreadable_after_planner(after),\n'
    '                                          JobState.ON_HOLD, branch=branch, '
    'hold_cause=UNKNOWN)\n'
)
_CHECK = '                if before is not None:\n                    after = fingerprint('
_WROTE_HOLD = (
    '                        return self._hold(\n'
    '                            ticket, owner,\n'
    '                            f"the planner wrote to the workspace it must only read ({paths}). '
    'The "\n'
)
_I = " " * 28  # the indent of the hold's sentence in `machine.py`
_REMEDY = (
    _I + 'f"the workspace is discarded. The planner runs on the executor\'s "\n'
    + _I + 'f"harness: run this project\'s executor on another harness (the "\n'
    + _I + 'f"`executor` entry of its `harness` setting in the deployment\'s "\n'
    + _I + 'f"project registry), or turn `planner_stage` off in its "\n'
    + _I + 'f"`.openfactory/project.yaml`.",\n'
)
_WARNING = '                                   f"only read: {paths}", role="planner")\n'

# From `_run_setup` down to the before-mark, verbatim: H6 moves the mark above setup, and a cut is
# one replacement, so the anchor carries the lines between them.
_SETUP_TO_BEFORE = (
    '                self._run_setup(ticket, ws, at_base=not resuming)\n'
    '            except SetupFailed as exc:\n'
    '                # FAILED, not NEEDS_REFINEMENT: the ticket is fine, the environment is not. '
    'Sending\n'
    '                # this back as a spec problem would ask somebody to rewrite a perfectly good '
    'ticket.\n'
    '                return self._hold(ticket, owner, str(exc), JobState.FAILED, branch=branch)\n'
    '\n'
    '            ctx = self._build_context(ticket, ws)\n'
    '            ctx.resume_handle = resume_handle or ""  # the agent '
    'resumes its session if it can\n'
    '            ctx.decision = self._decision  # a resolved human choice, '
    'injected into the agents\n'
    '            ctx.another_pass = self._another_pass  # what the last change still got wrong '
    '(#448)\n'
    '\n'
    '            # PLAN → the planner investigates (read-only) and drafts a testable plan. '
    'Optional:\n'
    "            # an adapter that doesn't split roles simply has no plan() and we go straight to\n"
    '            # execute (single-agent, as before).\n'
    '            plan_cost = 0.0\n'
    '            # ADR-0014: single-agent by default. The dedicated read-only planner runs ONLY '
    'when\n'
    '            # the manifest opts in (planner_stage) AND the adapter exposes plan(). Otherwise '
    'the\n'
    '            # executor investigates + plans + implements in one warm context (no handoff '
    'tax).\n'
    '            if self.manifest.planner_stage and hasattr(self.agent, "plan"):\n'
    '                self._set_state(ticket, JobState.PLANNING)\n'
    '                # A PLANNER READ-ONLY BY INSTRUCTION ONLY IS MEASURED '
    '(#788): it runs on THIS\n'
    '                # tree, the one the executor continues from and `_commit` sweeps with `git '
    'add -A`,\n'
    "                # so on 620bb577 (2026-10-20) a Kimi planner's "
    '`planted.txt` reached the pull\n'
    "                # request. The mark is taken HERE, after `_run_setup` and a resume's restore, "
    "so\n"
    '                # what they left is not charged to the planner; and it is the tree `git add '
    '-A`\n'
    '                # would commit plus HEAD, not porcelain: measured on '
    'git 2.43.0 the same day,\n'
    '                # `?? u` read the same before and after a planner appended to it while the '
    'tree\n'
    '                # hashes differed, and a planner `git commit` left porcelain clean with HEAD '
    'moved.\n'
    "                # It also reads the ref HEAD is on and the job's branch, which "
    '`publish_branch`\n'
    '                # pushes by name: on dc0efac4 a planner that moved that branch alone was not '
    'held.\n'
    + _GATE + _BEFORE
)

MUTATIONS = [
    # ── 1. the scope ─────────────────────────────────────────────────────────────────────────────
    ("S1 no harness is measured: the scope constant is empty", BASE,
     'PLANNERS_READ_ONLY_BY_INSTRUCTION = frozenset({"kimi"})\n',
     "PLANNERS_READ_ONLY_BY_INSTRUCTION = frozenset()\n"),
    ("S2 the gate widens to a harness whose CLI holds its planner read-only (codex)", MACHINE,
     _GATE,
     '                measured = getattr(self.agent, "name", "") in ("kimi", "codex")\n',
     SCOPE),

    # ── 2. the fingerprint sees every way in ─────────────────────────────────────────────────────
    ("F1 a new file is not seen: `git add -A` becomes `git add -u`", PASS,
     """'GIT_INDEX_FILE="$t" git add -A && """,
     """'GIT_INDEX_FILE="$t" git add -u && """,
     CREATE),
    ("F2 HEAD is not read: the mark carries the tree in its place", PASS,
     "        mark = Mark(tree=lines[-4], head=lines[-3], head_ref=lines[-2], branch=lines[-1])\n",
     "        mark = Mark(tree=lines[-4], head=lines[-4], head_ref=lines[-2], branch=lines[-1])\n",
     COMMIT_AND_DELETE),
    ("F3 the mark is the porcelain, hashed, not the tree `git add -A` would commit", PASS,
     """'GIT_INDEX_FILE="$t" git add -A && GIT_INDEX_FILE="$t" git write-tree; rc=$?; '""",
     """'git status --porcelain | git hash-object --stdin; rc=$?; '""",
     REWRITE_SETUP),

    # ── 3. could not see is never clean ──────────────────────────────────────────────────────────
    ("U1 the exit code is ignored: a walled answer ending in two hashes reads as a mark", PASS,
     "    if rc == 0 and len(lines) >= 4:\n",
     "    if len(lines) >= 4:\n",
     WALLED),
    ("U2 an unreadable workspace before the pass no longer stops it being run", MACHINE,
     _HOLD_BEFORE, "",
     UNASKABLE),
    ("U3 the after-pass Unreadable branch is deleted", MACHINE,
     _HOLD_AFTER, "",
     UNASKABLE_AFTER),
    ("U4 an unreadable workspace after the pass is read as the before-mark (as clean)", MACHINE,
     _HOLD_AFTER,
     '                    if isinstance(after, Unreadable):\n'
     '                        after = before\n',
     UNASKABLE_AFTER),
    ("U5 the fingerprint goes on after git's first refusal (`|| exit` dropped)", PASS,
     """'idx="$(git rev-parse --git-path index)" || exit; t=""",
     """'idx="$(git rev-parse --git-path index)"; t=""",
     GIT_REFUSES),

    # ── 4. the hold wins, names what was written, and pushes nothing ────────────────────────────
    ("H1 the pause is asked before the check, so `_preserve_partial` pushes the edit", MACHINE,
     _CHECK,
     '                if plan_result.pause_reason:\n'
     '                    return self._paused(\n'
     '                        ticket, plan_result.pause_reason, plan_result.retry_at, '
     'branch=branch,\n'
     '                        ws=ws, resume_handle=plan_result.resume_handle,\n'
     '                    )\n'
     + _CHECK,
     PAUSE),
    ("H2 the hold is said and not returned: the job goes on", MACHINE,
     _WROTE_HOLD,
     _WROTE_HOLD.replace("return self._hold(", "self._hold(")),
    ("H3 the paths are dropped from the hold's sentence", MACHINE,
     _WROTE_HOLD,
     _WROTE_HOLD.replace(" ({paths})", ""),
     CREATE),
    ("H4 the paths are dropped from the journal warning", MACHINE,
     _WARNING,
     '                                   f"only read", role="planner")\n',
     CREATE),
    ("H5 `_preserve_for_hold` is called before the hold, which pushes the edit", MACHINE,
     _WROTE_HOLD,
     "                        self._preserve_for_hold(ticket, ws, plan_result.resume_handle)\n"
     + _WROTE_HOLD,
     CREATE),
    ("H6 the before-mark is taken above `_run_setup`: what setup left is charged to the planner",
     MACHINE,
     _SETUP_TO_BEFORE,
     "                _early = fingerprint(self.sandbox, ws)\n"
     + _SETUP_TO_BEFORE.replace(_BEFORE, "                before = _early if measured else None\n"),
     SETUP_NOT_CHARGED),

    # ── 5. each hold declares its cause, so its prose is never classified (review round 1) ───────
    ("C1 the planner-wrote hold declares no cause: `src/rate_limit.py` reads as throttling",
     MACHINE,
     _I + 'f"`.openfactory/project.yaml`.",\n'
     + _I + 'JobState.ON_HOLD, branch=branch, hold_cause=UNKNOWN)\n',
     _I + 'f"`.openfactory/project.yaml`.",\n'
     + _I + 'JobState.ON_HOLD, branch=branch)\n',
     THROTTLING),
    ("C2 the hold before the pass declares no cause: git's refusal is left to `classify`",
     MACHINE,
     _HOLD_BEFORE,
     _HOLD_BEFORE.replace(',\n                                      hold_cause=ENVIRONMENT)', ')'),
     AS_ENVIRONMENT.format("before-the-pass")),

    # ── 6. the remedy names the executor, whose harness the planner runs on (review round 1) ────
    ("R1 the remedy says \"Give the planner another harness\", a role that does not exist",
     MACHINE,
     _REMEDY,
     _I + 'f"the workspace is discarded. Give the planner another harness, "\n'
     + _I + 'f"or turn `planner_stage` off for this project.",\n',
     CREATE),

    # ── 7. the fingerprint keeps its own promises (review round 1, not blocking) ────────────────
    ("P1 the fingerprint writes the real index: `GIT_INDEX_FILE` dropped", PASS,
     """'GIT_INDEX_FILE="$t" git add -A && GIT_INDEX_FILE="$t" git write-tree; rc=$?; '""",
     """'git add -A && git write-tree; rc=$?; '""",
     REAL_INDEX),
    ("P2 the index copy is left in the git dir: `rm -f \"$t\"` dropped", PASS,
     """'rm -f "$t"; git rev-parse HEAD || rc=1; '""",
     """'git rev-parse HEAD || rc=1; '""",
     REAL_INDEX),
    ("P3 a changed tree git names no path for reads as nothing written", PASS,
     '        return [f"{what}, and git named no path ({said})"]\n',
     "        return []\n",
     NO_NAMES),
    ("P4 the `SHOWN` bound is dropped: every path is named, with no \"and N more\"", PASS,
     "    if len(unique) > SHOWN:\n",
     "    if False:\n",
     MANY),
    ("P5 `--no-renames` is dropped: a rename names only the path it came to", PASS,
     '(f"git -c core.quotePath=false diff --no-renames --name-only "',
     '(f"git -c core.quotePath=false diff --name-only "',
     RENAME),

    # ── 8. what is measured is what is pushed (review round 2 on dc0efac4, point 2) ─────────────
    ("B1 the ref HEAD is on is not read: every mark says detached", PASS,
     "head_ref=lines[-2], branch=lines[-1])\n",
     "head_ref=DETACHED, branch=lines[-1])\n",
     OTHER_BRANCH.format("worktree")),
    ("B2 the job branch's commit is not read: every mark says absent", PASS,
     "head_ref=lines[-2], branch=lines[-1])\n",
     "head_ref=lines[-2], branch=ABSENT)\n",
     MOVES_BRANCH.format("worktree")),
    ("B3 the fingerprint is not told the job's branch: `$b` is empty", PASS,
     '    command = f"b={shlex.quote(ws.branch)}; {FINGERPRINT}"\n',
     "    command = FINGERPRINT\n",
     MOVES_BRANCH.format("worktree")),
    ("B4 the ref HEAD moved to is not named in the hold", PASS,
     "    if before.head_ref != after.head_ref:\n"
     '        names.append(f"HEAD moved during the pass from {_on(before.head_ref)} to "\n'
     '                     f"{_on(after.head_ref)}")\n',
     "    if before.head_ref != after.head_ref:\n"
     "        pass\n",
     OTHER_BRANCH.format("worktree")),
    ("B5 the moved job branch is not named in the hold, only the paths its commit carries", PASS,
     '        names.append(f"the job\'s branch {ws.branch} (the one pushed) moved during the '
     'pass "\n'
     '                     f"from {before.branch[:12]} to {after.branch[:12]}")\n',
     "",
     MOVES_BRANCH.format("worktree")),

    # ── 9. the reviewer's surviving cuts (review round 2 on dc0efac4, point 3) ──────────────────
    ("K7 the fingerprint's add leaves out top-level dot paths: `.openfactory/project.yaml` unseen",
     PASS,
     """'GIT_INDEX_FILE="$t" git add -A && """,
     """'GIT_INDEX_FILE="$t" git add -A -- . ":(exclude).*" && """,
     DOT_PATH.format("worktree")),
    ("K9 the remedy drops \", or turn `planner_stage` off\": only another harness is offered",
     MACHINE,
     _REMEDY,
     _REMEDY.replace(_I + 'f"project registry), or turn `planner_stage` off in its "\n'
                     + _I + 'f"`.openfactory/project.yaml`.",\n',
                     _I + 'f"project registry).",\n'),
     CREATE),
]
