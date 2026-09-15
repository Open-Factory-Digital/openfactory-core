"""#142, proven by breaking it — a proposal whose base moved still lands on the local forge.

THREE CLAIMS:

  1. **In the installation's bare repository, a proposal the base moved under is rebased and
     lands.** The rebase is committed as the bot, and the branch moves only if it is still where
     the rebase started. Merging used to refuse it `non-fast-forward` for ever.
  2. **A conflict refuses by name and moves nothing**, and leaves no scratch tree behind on the
     disk or in the repository's own list.
  3. **Only the bare repository is rebased.** A merge in the person's repository is still a
     fast-forward and nothing else.

The guard is `tests/test_a_proposal_whose_base_moved_still_lands_on_the_local_forge.py`: real git,
the bare repository `create_repository` makes, and no ambient git identity.

WHAT IS DELIBERATELY NOT CUT: the refusal when `worktree add` itself fails. Both callers have
already made sure the head exists, so no input reaches that branch without breaking git itself. It
is there so that such a failure is reported in git's own words, not as a rebase in a directory
that does not exist.
"""

TEST = "tests/test_a_proposal_whose_base_moved_still_lands_on_the_local_forge.py"

FORGE = "openfactory/adapters/forge/local.py"

MUTATIONS = [
    # ── 1. it lands ────────────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: `merge_pr` never rebases, and the stuck baseline is refused "
     "`non-fast-forward` again", FORGE,
     "        if (self._bare(where) and self._sha(head, where)",
     "        if (False and self._bare(where) and self._sha(head, where)"),

    ("a bare repository is never recognised, so neither the merge nor `update_branch` rebases "
     "there", FORGE,
     '        return self._out("rev-parse", "--is-bare-repository", cwd=where) == "true"',
     "        return False"),

    ("the rebase carries no identity, and git refuses to write its commits on a machine with none",
     FORGE,
     '            p = self._git("-c", f"user.name={bot.name}", "-c", f"user.email={bot.email}",\n'
     '                          "rebase", base, cwd=tree)',
     '            p = self._git("rebase", base, cwd=tree)'),

    ("the rebase is thrown away: the branch is never moved, so the fast-forward is refused anyway",
     FORGE,
     '            moved = self._git("update-ref", f"refs/heads/{head}", self._sha("HEAD", tree), '
     "started,",
     '            moved = self._git("update-ref", f"refs/heads/{head}", started, started,'),

    ("the branch is moved without asking where it was, so a proposal pushed again during the "
     "rebase is overwritten by a rebase of the older text", FORGE,
     '            moved = self._git("update-ref", f"refs/heads/{head}", self._sha("HEAD", tree), '
     "started,\n                              cwd=where)",
     '            moved = self._git("update-ref", f"refs/heads/{head}", self._sha("HEAD", tree),\n'
     "                              cwd=where)"),

    ("`update_branch` answers False on a bare repository again, as before the fix", FORGE,
     "        if self._bare(where):\n"
     "            if refused := self._rebase_in_a_scratch_tree(base, head, where):\n"
     '                log.warning("could not rebase %s onto %s — %s", head, base, refused)\n'
     "                return False\n",
     "        if self._bare(where):\n            return False\n"),

    ("a base that does not exist yet is read as `behind`, and the rebase refuses `invalid upstream` "
     "where the fast-forward used to create it", FORGE,
     "self._sha(head, where) and self._sha(base, where)",
     "self._sha(head, where)"),

    # ── 2. a conflict refuses by name ──────────────────────────────────────────────────────────
    ("the conflict's refusal names no file, which is all the person could act on", FORGE,
     '                files = "\\n  ".join(conflicted.splitlines()[:20])',
     '                files = "(some files)"'),

    ("the conflict is not recorded on the pull request, so the page has nothing to show", FORGE,
     "            if refused := self._rebase_in_a_scratch_tree(base, head, where):\n"
     "                self._refuse(pr, refused)\n",
     "            if refused := self._rebase_in_a_scratch_tree(base, head, where):\n"),

    ("the merge carries on past a refused rebase, and git's `! [rejected]` overwrites the sentence "
     "that named the file", FORGE,
     "                self._refuse(pr, refused)\n                raise RuntimeError(refused)",
     "                self._refuse(pr, refused)"),

    ("the scratch directory is left in the temp directory, and still registered because prune "
     "only drops trees whose directory is gone", FORGE,
     "            shutil.rmtree(scratch, ignore_errors=True)\n",
     ""),

    ("the scratch tree's registration is never pruned, so the repository lists a worktree that "
     "does not exist", FORGE,
     '            self._git("worktree", "prune", cwd=where)\n',
     ""),

    # ── 3. only the bare repository ───────────────────────────────────────────────────────────
    ("the merge rebases in the PERSON'S repository too, rewriting a job branch nobody asked to "
     "rewrite", FORGE,
     "        if (self._bare(where) and self._sha(head, where)",
     "        if (self._sha(head, where)"),
]
