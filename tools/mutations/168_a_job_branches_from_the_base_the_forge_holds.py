"""#168, proven by breaking it — a job on the worktree box starts from the base the forge holds.

The worktree box cut every new job's branch from the LOCAL base of `repo_path`, and nothing fetched
it first. On a hosted forge, a project registered by path points at somebody's clone, and the
deployment that reported this measured that clone a merge behind the forge's `main` on its first
day: cards were planned, written, validated and reviewed against code no longer on the base.

THREE CLAIMS:

  1. **The start.** A new job is cut from the base read from the forge, into the worktree's own
     `FETCH_HEAD`; nothing else in the person's repository moves; a forge that cannot be asked
     stops the job by name, leaving no half-made branch or worktree behind.
  2. **The diff.** What the job is judged on — the reviewer's input, the suppression scan and its
     two re-reads, the protected-path gate, the "changed nothing" hold, `_pr_diff`/`_pr_diff_paths`
     — is measured from the commit the box started from, not from the stale local branch. A
     reopened pull request is measured from where it left the base (`merge-base`).
  3. **Where there is no forge to be behind**, nothing is fetched: a local forge's URL is the
     repository itself, and a caller that names no forge (the box proof, the first-run rehearsal)
     is not sent to `origin`.

The guard is `tests/test_a_job_branches_from_the_base_the_forge_holds.py`.
"""

TEST = "tests/test_a_job_branches_from_the_base_the_forge_holds.py"

BOX = "openfactory/adapters/sandbox/worktree.py"
WS = "openfactory/adapters/sandbox/base.py"
MACHINE = "openfactory/orchestrator/machine.py"

MUTATIONS = [
    ("THE DEFECT ITSELF: a new job is cut from the local base and the forge is never asked", BOX,
     "        if not keep and remote_url and not _is_this_repo(remote_url, repo_path):\n",
     "        if False:\n"),

    ("the base is fetched but a new job is not moved onto it", BOX,
     "        if rc == 0 and from_base:\n",
     "        if False:\n"),

    ("a forge that could not be asked silently leaves the job on the stale base", BOX,
     "        if rc != 0:\n            _run([\"git\", \"-C\", str(repo_path), \"worktree\", "
     "\"remove\", \"--force\", wp])\n",
     "        if False:\n            _run([\"git\", \"-C\", str(repo_path), \"worktree\", "
     "\"remove\", \"--force\", wp])\n"),

    ("a refused job leaves its half-made branch behind", BOX,
     "            _run([\"git\", \"-C\", str(repo_path), \"branch\", \"-D\", branch])\n"
     "            raise RuntimeError(\n",
     "            raise RuntimeError(\n"),

    ("a reopened pull request is measured from the forge's current base, not where it left it",
     BOX,
     "        rc, out = _run([\"git\", \"-C\", wp, \"merge-base\", \"FETCH_HEAD\", \"HEAD\"])\n",
     "        rc, out = _run([\"git\", \"-C\", wp, \"rev-parse\", \"FETCH_HEAD\"])\n"),

    ("a caller that names no forge is sent to `origin`", BOX,
     "        if not keep and remote_url and not _is_this_repo(remote_url, repo_path):\n"
     "            base_commit = self._read_the_forges_base(\n"
     "                repo_path=repo_path, wt=wt, base_branch=base_branch, branch=branch,\n"
     "                remote_url=remote_url,",
     "        if not keep and not _is_this_repo(remote_url, repo_path):\n"
     "            base_commit = self._read_the_forges_base(\n"
     "                repo_path=repo_path, wt=wt, base_branch=base_branch, branch=branch,\n"
     "                remote_url=remote_url or \"origin\","),

    ("THE HALF FIX: the start moves and every diff still reads the stale local branch", WS,
     "        return self.base_commit or self.base_branch\n",
     "        return self.base_branch\n"),

    ("the orchestrator's diffs ignore where the box started", MACHINE,
     "    return getattr(ws, \"base_commit\", None) or base\n",
     "    return base\n"),

    ("the first read of the job's diff — the \"changed nothing\" hold — reads the stale base",
     MACHINE,
     "            _, diff = self.sandbox.run(\n"
     "                workspace=ws, command=f\"git diff {_measured_from(ws, base)}..HEAD\", "
     "timeout=120\n",
     "            _, diff = self.sandbox.run(\n"
     "                workspace=ws, command=f\"git diff {base}..HEAD\", timeout=120\n"),

    ("the suppression re-read after a suppression repair reads the stale base", MACHINE,
     "                _, diff = self.sandbox.run(\n"
     "                    workspace=ws, command=f\"git diff {_measured_from(ws, base)}..HEAD\",\n",
     "                _, diff = self.sandbox.run(\n"
     "                    workspace=ws, command=f\"git diff {base}..HEAD\",\n"),

    ("the re-review after a review repair reads the stale base", MACHINE,
     "                    _, diff = self.sandbox.run(  # fresh diff for the guard + re-review\n"
     "                        workspace=ws, command=f\"git diff {_measured_from(ws, base)}..HEAD\","
     "\n",
     "                    _, diff = self.sandbox.run(  # fresh diff for the guard + re-review\n"
     "                        workspace=ws, command=f\"git diff {base}..HEAD\",\n"),

    ("`_pr_diff` reads the stale base", MACHINE,
     "        rc, out = self.sandbox.run(\n"
     "            workspace=ws, command=f\"git diff {_measured_from(ws, base)}..HEAD\", "
     "timeout=120\n",
     "        rc, out = self.sandbox.run(\n"
     "            workspace=ws, command=f\"git diff {base}..HEAD\", timeout=120\n"),

    ("`_pr_diff_paths` reads the stale base", MACHINE,
     "            workspace=ws, command=f\"git diff --name-only {_measured_from(ws, base)}..HEAD\",\n",
     "            workspace=ws, command=f\"git diff --name-only {base}..HEAD\",\n"),
]
