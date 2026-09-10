"""ADR-0049 slice 3b, proven by breaking it — the loop and the surfaces, outside the workflow body.

FOUR CLAIMS:

  1. **A resume keeps the work.** The box deleted the job branch and then asked a remote that IS
     this repository whether it still had it — and read "couldn't find remote ref" as *the branch
     is gone*. The runner then force-pushes the fresh start over the open pull request.
  2. **Nothing watches this project's code, and every answer says so.** `[]`, `"none"`, `False` —
     none of them `None`, because this row is not failing to look.
  3. **What git refuses, the person reads.** Its own sentences had no cause and no way out; the
     hold truncated the file name away and named no pull request.
  4. **One refusal, asked by every door.** A gate one door carries is a gate, and the other two
     are the doors an unattended factory actually uses.

THE FIRST CLAIM IS A DATA-LOSS DEFECT, MEASURED RATHER THAN REASONED. Driving a publish and then a
resume against a local repository dropped the agent's implemented commit and logged
`OPENFACTORY_BRANCH_GONE` about a branch that repository was holding.

ONE CUT IS RETIRED WITH ITS REASON, the second time in this slice pair: `_is_this_repo`'s early
return for a URL is behaviourally equivalent to letting `Path.resolve()` answer, so no case can
prove it. The lesson generalises — a defensive check that only restates what the code below it
already does is a claim no mutation can reach, and saying so beats leaving a green row in the plan.

The guard under test is `tests/test_what_git_refuses_the_person_reads.py`, whose git is real.
"""

TEST = "tests/test_what_git_refuses_the_person_reads.py"

SLICE = "tests/test_what_git_refuses_the_person_reads.py"

BOX = "openfactory/adapters/sandbox/worktree.py"
NONE = "openfactory/adapters/environment/none.py"
ENV = "openfactory/adapters/environment/registry.py"
CLASSIFY = "openfactory/techlead/classify.py"
MACHINE = "openfactory/orchestrator/machine.py"
BOXES = "openfactory/adapters/sandbox/registry.py"
CATALOG = "openfactory/actions/catalog.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
VIEW = "openfactory/runtime/temporal/view.py"
COMPOSE = "docker-compose.yml"

MUTATIONS = [
    # ── 1. a resume keeps the work ─────────────────────────────────────────────────────────────
    ("THE DATA-LOSS DEFECT, PUT BACK: the job branch is deleted before a resume that has nowhere "
     "to fetch it from, so the agent's implemented work is dropped and force-pushed over", BOX,
     "        keep = checkout_existing and _is_this_repo(remote_url, repo_path)\n"
     "        if not keep:\n",
     "        keep = False\n        if True:\n", SLICE),

    ("the resume fetches from a remote that is this repository, inventing "
     "`refs/remotes/origin/...` for a remote that does not exist", BOX,
     "        if keep:\n", "        if False:\n", SLICE),

    # RETIRED 2026-09-09, and it is the SECOND instance of one lesson this slice pair keeps
    # teaching: a guard cannot see a difference that is not observable. Dropping the `"://"` and
    # `git@` early return leaves `Path("https://github.com/o/r.git").resolve()`, which is not the
    # repository's path, so the answer is False either way — for every URL that exists.
    #
    # The check stays because it SAYS what it means: a URL names somewhere else by construction,
    # and a reader should not have to reason about `Path` semantics to know that. The claim it
    # protects — a hosted deployment keeps today's fetch path exactly — is held by the rows above
    # and below it, which ARE observable.

    ("a resume on a branch that really is gone crashes instead of degrading to a fresh start",
     BOX,
     "            if not _branch_exists(repo_path, branch):\n",
     "            if False:\n", SLICE),

    ("the worktree is created with `-b` even when the branch is already here, so the resume fails "
     "on 'branch already exists'", BOX,
     '        add = (["worktree", "add", str(wt), branch] if keep\n'
     '               else ["worktree", "add", "-b", branch, str(wt), start])',
     '        add = ["worktree", "add", "-b", branch, str(wt), start]', SLICE),

    ("an unreachable remote reads as an absent branch again — 'could not ask' becoming 'it is not "
     "there', which is the audit finding this path carries", BOX,
     "            elif _remote_has_no_such_branch(out):",
     "            elif True:", SLICE),

    # ── 2. nothing watches this project's code ─────────────────────────────────────────────────
    ("the observer answers `None` for its checks — *I could not look* — which sends a caller "
     "hunting for a credential that does not exist", NONE,
     "        return []\n\n    def deploy_status", "        return None\n\n    def deploy_status",
     SLICE),

    ("a probe nobody made reports a healthy service", NONE,
     "        return False\n", "        return True\n", SLICE),

    ("a project whose forge is this machine has no observer at all, so `build_observer` refuses "
     "and every job dies at the CI read", ENV,
     '    "none": _none,\n    "local": _none,\n', '    "none": _none,\n', SLICE),

    ("an unknown CI stops being refused, so a deployment observes the wrong system for ever and "
     "the symptom is a release that hangs in 'verifying'", ENV,
     "    added = plugins.builder(AXIS, kind, builtin=OBSERVERS)",
     "    return _none(project, token=None)\n    added = plugins.builder(AXIS, kind, "
     "builtin=OBSERVERS)", SLICE),

    # ── 3. what git refuses, the person reads ──────────────────────────────────────────────────
    ("git's own refusals go back to `unknown`, whose remedy is 'I could not identify the cause' — "
     "said to somebody standing in the repository one command from the fix", CLASSIFY,
     "    (TREE, re.compile(\n"
     '        r"your local changes to the following files would be overwritten|"',
     "    (UNKNOWN, re.compile(\n"
     '        r"your local changes to the following files would be overwritten|"', SLICE),

    ("a half-done tree reads as something else, so the person is not told to finish or abort it",
     CLASSIFY,
     "    (TREE, re.compile(\n"
     '        r"(?:merge|rebase|cherry-pick|revert) in progress|"',
     "    (CODE, re.compile(\n"
     '        r"(?:merge|rebase|cherry-pick|revert) in progress|"', SLICE),

    ("the remedy stops saying what to do and falls back to the generic escalation", CLASSIFY,
     "    if cause == TREE:", "    if False:", SLICE),

    ("the sentence loses the two commands that are the whole remedy",
     "openfactory/techlead/voice.py",
     '        "en": "your own working copy is in the way — commit or stash what is there, or '
     'finish the "\n              "merge you have open, and nothing of yours is lost either way",',
     '        "en": "the working copy is in the way",', SLICE),

    ("the auto hold truncates git's sentence again, cutting off the file name it exists to carry",
     MACHINE,
     'f"PR {pr} could not be merged — needs a human:\\n{exc}",',
     'f"PR {pr} could not be merged ({str(exc)[:150]}) — needs a human",', SLICE),

    ("the hold names no pull request, so the person is told one could not be merged with no way "
     "to open it", MACHINE,
     'f"PR {pr} could not be merged — needs a human:\\n{exc}",\n'
     "                JobState.ON_HOLD, branch=branch, pr_url=pr,",
     'f"PR {pr} could not be merged — needs a human:\\n{exc}",\n'
     "                JobState.ON_HOLD, branch=branch,", SLICE),

    # ── 4. one refusal, every door ─────────────────────────────────────────────────────────────
    ("a box that bounds nothing runs durable jobs after all", BOXES,
     "    if traits.isolates_resources:\n        return \"\"",
     "    if True:\n        return \"\"", SLICE),

    # RE-PINNED 2026-09-10 (ADR-0049 D9): the sentence gained a second way out — the declaration
    # a person makes about their OWN machine — so the anchor ends at `own_work.THE_WAY_OUT`
    # instead of at the full stop. The claim is the same one: the remedy is NAMED.
    ("the remedy stops being named, so an operator is sent to read the box registry", BOXES,
     '            f"an agent on the worker itself, unattended. Set OPENFACTORY_SANDBOX=container '
     '(or "\n            f"pass --sandbox container) to bound the work. " + own_work.THE_WAY_OUT)',
     '            f"an agent on the worker itself. Use a box that bounds the work.")', SLICE),

    ("the panel's scan row starts durable jobs in a box that bounds nothing, which is how it was "
     "before — exempted by omission rather than by design", CATALOG,
     "    if why := durable_refusal(scan_sandbox):\n"
     "        return refused(INVALID, why, started=[], skipped=todo, todo=todo, running=running)\n",
     "", SLICE),

    ("the poller — the door an unattended factory actually uses — stops asking", ACTIVITIES,
     "    if why := durable_refusal(inp.sandbox):\n"
     '        activity.logger.warning("no job was started for %s — %s", inp.project, why)\n'
     "        raise ApplicationError(why, non_retryable=True)\n",
     "", SLICE),

    # ── the heading and the fetcher name the same system ───────────────────────────────────────
    ("the CI heading reads the forge again, so it names one system over checks fetched from "
     "another", VIEW,
     "        from openfactory.adapters.environment.registry import observer_kind\n"
     "        from openfactory.registry import ProjectRegistry",
     "        from openfactory.adapters.forge.registry import forge_kind as observer_kind\n"
     "        from openfactory.registry import ProjectRegistry", SLICE),

    ("a board nothing watches shows a vendor's name instead of saying so", VIEW,
     '                 "none": "nothing is watched", "local": "nothing is watched"}',
     "                 }", SLICE),

    # ── both halves reach the repositories ─────────────────────────────────────────────────────
    ("only the worker mounts the person's repositories, so the pull-request page cannot read the "
     "diff it exists to show", COMPOSE,
     "      # The same directory the worker mounts, and for the panel's own reason: the pull-request\n"
     "      # page reads the diff out of the person's repository (ADR-0049 D3/D4).\n"
     "      - ${OPENFACTORY_REPOS_DIR:-${HOME}/openfactory/repos}:${OPENFACTORY_REPOS_DIR:-${HOME}/openfactory/repos}\n",
     "", SLICE),

    ("the mount stops being identity-mapped, so a path the worker names is a path the daemon "
     "cannot resolve", COMPOSE,
     "      - ${OPENFACTORY_REPOS_DIR:-${HOME}/openfactory/repos}:${OPENFACTORY_REPOS_DIR:-${HOME}/openfactory/repos}\n"
     "      # DOCKER-OUT-OF-DOCKER",
     "      - ${OPENFACTORY_REPOS_DIR:-${HOME}/openfactory/repos}:/var/lib/openfactory-repos\n"
     "      # DOCKER-OUT-OF-DOCKER", SLICE),
]
