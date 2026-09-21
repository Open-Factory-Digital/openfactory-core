"""Proven by breaking it — a diff the sandbox could not read is not a change that touched nothing.

Both shipped rows ended `diff_paths` with `… if rc == 0 else []`, so a `git` that failed, a
missing base ref, a `docker exec` that never ran and a timeout all arrived as "no files". Three
questions in `_validate` read that as an answer — the risk assessment, the protected-path check
and the per-component gate selection — and all three reported nothing to find. A pull request
nobody could measure reached the merge gate looking cleaner than one that was measured.

FOUR CLAIMS:

  1. **`None` is the port's word for "could not read"**, and `[]` still means the change touched
     nothing — on both rows and on the Protocol they implement.
  2. **The machine records which of the two it got**, beside `floor_unreadable`, because the
     durable record must not say a change touched files, or touched none, on a read that never
     landed.
  3. **The merge gate refuses on the first and not on the second**, and the pull request says so
     where the person decides.
  4. **The hold keeps what it cannot prove is absent** — a failed read used to discard the
     agent's partial work and turn a resumable hold into a fresh restart.

The guard is `tests/test_a_diff_that_could_not_be_read_is_not_an_empty_diff.py`.
"""

TEST = "tests/test_a_diff_that_could_not_be_read_is_not_an_empty_diff.py"

PORT = "openfactory/adapters/sandbox/base.py"
WORKTREE = "openfactory/adapters/sandbox/worktree.py"
CONTAINER = "openfactory/adapters/sandbox/container.py"
MACHINE = "openfactory/orchestrator/machine.py"
POLICY = "openfactory/orchestrator/merge_policy.py"

MUTATIONS = [
    # ── claim 1: the port and both rows ───────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: the worktree row folds a failed read back into an empty diff", WORKTREE,
     "            return None\n        return [ln for ln in out.splitlines() if ln.strip()]",
     "            return []\n        return [ln for ln in out.splitlines() if ln.strip()]"),

    ("…and the container row, whose read can also fail because `docker exec` never ran",
     CONTAINER,
     "            return None\n        return [line for line in out.splitlines() if line.strip()]",
     "            return []\n        return [line for line in out.splitlines() if line.strip()]"),

    ("the Protocol goes back to promising a list, so a caller has no way to ask", PORT,
     "    def diff_paths(self, *, workspace: Workspace) -> list[str] | None:\n",
     "    def diff_paths(self, *, workspace: Workspace) -> list[str]:\n"),

    # ── claim 2: the machine records which it got ─────────────────────────────────────────────
    ("the machine never notices, so the record and the gate see a measured change", MACHINE,
     "        self._diff_unreadable = diff_paths is None\n",
     "        self._diff_unreadable = False\n"),

    ("…or notices and does not carry it into the result the merge gate reads", MACHINE,
     '        result.diff_unreadable = bool(getattr(self, "_diff_unreadable", False))\n',
     "        result.diff_unreadable = False\n"),

    # ── claim 3: the gate refuses, and the pull request says why ──────────────────────────────
    ("an attempt nobody could measure merges itself", POLICY,
     "    if result.diff_unreadable:\n        return False\n",
     "    if False:\n        return False\n"),

    ("…and every empty diff is held too, so an ordinary no-op change can never merge", POLICY,
     "    if result.diff_unreadable:\n",
     "    if not result.protected_hits:\n"),

    ("the pull request holds the merge and says nothing, which is a gate nobody can argue with",
     MACHINE,
     "        if result.diff_unreadable:\n            lines += [\"\", \"diff_unreadable — this "
     "build could not read which files this change \"\n",
     "        if False:\n            lines += [\"\", \"diff_unreadable — this "
     "build could not read which files this change \"\n",
     "tests/test_a_gate_that_holds_says_so_where_the_person_decides.py"),

    # ── claim 4: the hold keeps what it cannot prove is absent ────────────────────────────────
    ("a read that failed discards the agent's partial work, turning a resumable hold into a "
     "fresh restart", MACHINE,
     "            if written is not None and not written:\n",
     "            if not written:\n"),
]
