"""ADR-0049 slice 3a, proven by breaking it — the person's repository is the forge.

FOUR CLAIMS:

  1. **The merge is a fast-forward, and it is refused rather than faked.** `merge_pr_now` reads
     success as *no exception*, so a refused merge that returned quietly would settle a job as
     MERGED over a base that never moved. Every refusal here is cut on purpose.
  2. **`mergeable_state` and `merge_pr` agree.** A page that offered a merge button which cannot
     work is the worst pair this row could give, and it is exactly what the first run produced.
  3. **The reads keep the port's three answers.** `None` could not look, `""`/`[]` looked and
     there is nothing — on `pr_for_head`, `pr_body`, `pr_diff` and `list_branches`.
  4. **Nothing is written into somebody's repository beyond the refs and the fast-forward.**

WHAT DRIVING IT AGAINST REAL GIT FOUND, and neither would have survived a review of the diff:

  · **`mergeable_state` said `clean` where `merge_pr` refused.** The dirty read went through a
    helper that STRIPS, and `git status --porcelain` puts two significant columns before the path
    — so every name shifted one character and no edit ever overlapped.
  · **A base checked out in a LINKED worktree was merged into the wrong tree.** "Checked out" was
    a boolean covering two different situations; with the job branch as HEAD, `git merge --ff-only`
    merged the head into itself. The question now answers WHICH worktree, and a base somebody else
    holds is refused.
  · and one ordering: a repository mid-merge answered `behind`, so the loop would have spent its
    bounded update attempts on a tree that refuses every one of them.

AND THREE THE FIRST RUN OF THIS PLAN FOUND, each a case no test reached: a diff with no merge base
(two roots), a REFUSED branch delete as opposed to an already-gone one, and the new conformance
rule, which needed a double that satisfies the whole port before it could be reached at all.

The guard under test is `tests/test_the_pull_request_lives_in_the_file.py` — this slice's own,
and every test in it runs real git.
"""

TEST = "tests/test_the_pull_request_lives_in_the_file.py"

SLICE = "tests/test_the_pull_request_lives_in_the_file.py"
CONFORM = "tests/test_adapter_conformance_suite.py"  # noqa: F841 — see the note below

FORGE = "openfactory/adapters/forge/local.py"
PORT = "openfactory/adapters/forge/base.py"
CHECK = "openfactory/conformance/adapters.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    # ── 1. a refusal is a refusal ──────────────────────────────────────────────────────────────
    ("`merge_pr` returns instead of raising when git refused — the workflow then settles the job "
     "as MERGED over a base that never moved, which is delivered work that was never delivered",
     FORGE,
     "        if p.returncode != 0:\n            sentence = self._sentence(p)\n"
     "            self._refuse(pr, sentence)\n            raise RuntimeError(sentence)",
     "        if p.returncode != 0:\n            sentence = self._sentence(p)\n"
     "            self._refuse(pr, sentence)\n            return", SLICE),

    ("a merge into a base somebody else has checked out is attempted anyway, writing a working "
     "tree nobody asked about", FORGE,
     "        if blocked := self._blocked(base):\n            self._refuse(pr, blocked)\n"
     "            raise RuntimeError(blocked)\n",
     "", SLICE),

    ("a branch that is gone merges as if it were there", FORGE,
     '        if not head_sha:\n            raise RuntimeError(f"the branch {head} is gone from '
     'this repository — nothing to merge")',
     "        if not head_sha:\n            pass", SLICE),

    ("the merge stops being idempotent, so a retried activity fails on work already done", FORGE,
     '        if row["state"] == "merged":\n            return  # idempotent: a retried activity '
     "must not fail on work already done",
     '        if row["state"] == "merged":\n            raise RuntimeError("already merged")',
     SLICE),

    # ── 2. the two answers agree ───────────────────────────────────────────────────────────────
    ("THE DEFECT THE FIRST RUN FOUND, put back: the dirty read goes through the helper that "
     "STRIPS, so every porcelain name shifts one character and no edit ever overlaps — the page "
     "offers a merge button that cannot work", FORGE,
     '        p = self._git("status", "--porcelain", "--untracked-files=all")\n'
     "        if p.returncode != 0:\n            return set()",
     '        p = self._git("status", "--porcelain", "--untracked-files=all")\n'
     "        if p.returncode != 0:\n            return set()\n"
     '        return {ln[3:].strip() for ln in self._out("status", "--porcelain",\n'
     '                                                   "--untracked-files=all").splitlines()}',
     SLICE),

    # RETIRED 2026-09-09, and the retirement is the finding. This cut SURVIVED, and running it is
    # what showed why: once `_blocked` refuses a base held by a FOREIGN worktree one step earlier,
    # `_same(self._worktree_of(base), self.repo_path)` and `self._checked_out(base)` agree on every
    # input that can still reach this line — our own HEAD (both true) and nobody at all (both
    # false). The difference is unreachable, so no case can prove it.
    #
    # The code keeps the longer expression because it SAYS what it means, and the defect it came
    # from is real: with the job branch as HEAD, the boolean sent `git merge --ff-only` into a tree
    # whose HEAD was the head, merging it into itself. That defect is now caught one line earlier,
    # by `test_a_base_checked_out_in_a_LINKED_WORKTREE_is_seen`, which is where the guard belongs.

    ("a repository mid-merge answers `behind`, so the loop spends its bounded update attempts on "
     "a tree that refuses every one of them", FORGE,
     "            if blocked := self._blocked(base):\n                return self._refuse(pr, "
     "blocked)\n            if self._git(\"merge-base\", \"--is-ancestor\", base, head).returncode "
     "!= 0:",
     '            if self._git("merge-base", "--is-ancestor", base, head).returncode != 0:',
     SLICE),

    ("`mergeable_state` raises instead of answering `unknown` — and the activity that calls it "
     "has no `try`, so the whole merge-watch goes down where every other row survives", FORGE,
     "        except Exception:  # noqa: BLE001 — see the docstring\n"
     '            log.warning("could not judge %s\'s mergeability", pr, exc_info=True)\n'
     '            return "unknown"',
     "        except Exception:  # noqa: BLE001\n            raise", SLICE),

    ("git's own sentence is replaced by this platform's paraphrase, and the file name is lost",
     FORGE,
     '        return ("your local changes to the following files would be overwritten by merge:\\n  "\n'
     '                + "\\n  ".join(overlap[:20]))',
     '        return "the working tree is dirty"', SLICE),

    ("the refusal is not written on the pull request, so the page and the hold have nothing to "
     "print", FORGE,
     '        number = _pr_number(pr)\n        if number:\n'
     "            with connect(self._db, write=True) as conn:\n"
     '                conn.execute("UPDATE pull_requests SET refused = ?, updated_at = ? "\n'
     '                             "WHERE project = ? AND number = ?",\n'
     "                             (sentence, now_iso(), self.project, number))\n"
     '        return "dirty"',
     '        return "dirty"', SLICE),

    # ── 3. the three answers ───────────────────────────────────────────────────────────────────
    ("a pull-request file that could not be read answers `\"\"` — *none was ever opened* — so the "
     "caller files a duplicate on a transient error", FORGE,
     "        except Exception:  # noqa: BLE001 — could not read is not \"there is none\"\n"
     '            log.warning("could not read %s\'s pull requests", self.project, exc_info=True)\n'
     "            return None",
     "        except Exception:  # noqa: BLE001\n            return \"\"", SLICE),

    ("`pr_status` guesses `open` instead of raising, which sends the sweep on to merge something "
     "already merged", FORGE,
     '        if row is None:\n            raise KeyError(f"no pull request {pr!r} on '
     '{self.project!r}")\n        return str(row["state"])',
     '        if row is None:\n            return "open"\n        return str(row["state"])', SLICE),

    ("a diff with no merge base reads as a pull request that changes nothing", FORGE,
     '        merge_base = self._out("merge-base", row["base"], row["head"])\n'
     "        if not merge_base:\n            return None",
     '        merge_base = self._out("merge-base", row["base"], row["head"])\n'
     '        if not merge_base:\n            return ""', SLICE),

    ("a truncated diff stops mid-hunk with no marker, reading as a change that ends there", FORGE,
     '        return text[:max_chars] + f"\\n… truncated at {max_chars} characters …\\n"',
     "        return text[:max_chars]", SLICE),

    ("an unreadable repository answers `[]` branches — *read fine, it has none*", FORGE,
     "        if p.returncode != 0:\n"
     '            log.warning("could not list %s\'s branches — %s", where, self._sentence(p))\n'
     "            return None",
     "        if p.returncode != 0:\n            return []", SLICE),

    ("a refused branch delete reports the branch as gone, so the convergence sweep stops looking "
     "at it for ever", FORGE,
     '        gone = "not found" in (p.stderr or "").lower()',
     "        gone = True", SLICE),

    # ── 4. what it writes, and the row's own shape ─────────────────────────────────────────────
    ("`push_remote` answers `None`, which means *use the ambient origin* — on a repository that "
     "has none", FORGE,
     "        return self.repo_path\n\n    def clone_url",
     "        return None\n\n    def clone_url", SLICE),

    # re-pinned 2026-09-09: aimed at the conformance SUITE's own file and survived — that file
    # predates this rule and has no case for it. The rule's own test lives with the row that
    # needed it, which is where a reader looking for "why does this rule exist" will be.
    ("conformance stops asking whether `push_remote` answers a remote at all", CHECK,
     "        remote = forge.push_remote()\n"
     "        if remote is not None and (not isinstance(remote, str) or not remote.strip()):",
     "        remote = forge.push_remote()\n        if False:", SLICE),

    ("a credential is spliced into somebody else's URL by a row that has none", FORGE,
     '        """Untouched. There is no credential to add, and adding one belonging to another '
     'system is\n        the failure this method exists to prevent everywhere else."""\n'
     "        return url",
     '        """Untouched."""\n        return url.replace("https://", "https://token@")', SLICE),

    ("a URL is rewritten into a local path, so a clone silently reads the wrong tree", FORGE,
     '        if "://" in name or name.startswith("git@"):\n            return name',
     "        if False:\n            return name", SLICE),

    ("the e2e dispatch reports a run that never happened instead of parking with the reason",
     FORGE,
     "        raise RuntimeError(\n"
     '            f"this project\'s forge is the repository on this machine and has no CI to '
     'dispatch, "',
     "        return\n        raise RuntimeError(\n"
     '            f"this project\'s forge is the repository on this machine and has no CI to '
     'dispatch, "', SLICE),

    ("the merge-watch's three leave the port again, so a row without them raises inside the "
     "durable watch after the agent has run", PORT,
     "    def mergeable_state(self, *, pr: str) -> str:\n"
     '        """Whether this pull request can be merged RIGHT NOW, in four words:',
     "    def _mergeable_state_retired(self, *, pr: str) -> str:\n"
     '        """Whether this pull request can be merged RIGHT NOW, in four words:', SLICE),

    ("the local row is dropped from the shipped-host table, so every URL on a local project is "
     "refused as foreign on its own host", CLI,
     '    return {"local": set(),\n            "github": github,',
     '    return {"github": github,', SLICE),
]
