"""#140, proven by breaking it — a pull request on the local forge is read and merged where it is.

THREE CLAIMS:

  1. **The pull request records its repository, and takes its shas there.** Read in the project's
     repository, a context-repository pull request was written with `base_sha` and `patch_id`
     both empty.
  2. **Every git command about it runs in that repository, with only the number in hand.** The
     panel, the activities and the merge button pass `pr=` and nothing else, so the answer has to
     come from the row — `_where`.
  3. **A `board.db` that was already running gains the column**, and only a lost race to add it
     is forgiven.

The guard is `tests/test_a_pull_request_is_read_and_merged_in_its_own_repository.py`, which opens
every pull request against a SECOND repository — the bare context repository this row creates.
Nothing before it could have caught the defect: every older test opened against the project's own
repository, where `cwd or self.repo_path` happens to be right.

WHAT IS DELIBERATELY NOT CUT, because the cut cannot be told apart on this row and a plan row that
survives by construction is noise. `_overlap`'s and `_blocked`'s foreign-worktree comparison, and
`update_branch`'s rebase, all answer the same in either repository when the second repository is
BARE — nobody has anything out of it, and git refuses a rebase there outright. That is the decision
`_worktree_of` and `update_branch` write down; the only second repository this row ever makes is
bare, so there is no input that reaches the difference.
"""

TEST = "tests/test_a_pull_request_is_read_and_merged_in_its_own_repository.py"

FORGE = "openfactory/adapters/forge/local.py"
DB = "openfactory/adapters/board_db.py"

MUTATIONS = [
    # ── 1. what the pull request records ───────────────────────────────────────────────────────
    ("`open_pr` records nothing about the repository, so the row reads as the project's and the "
     "diff and the merge go back to the person's code", FORGE,
     '                (self.project, number, key, branch, onto, (title or "").strip(), body or "",',
     '                (self.project, number, "", branch, onto, (title or "").strip(), body or "",'),

    ("the shas are taken in the project's repository again, so a context pull request is written "
     "with both empty", FORGE,
     "                 self._sha(onto, where), self._patch_id(onto, branch, where), when, when))",
     "                 self._sha(onto, self.repo_path), self._patch_id(onto, branch, "
     "self.repo_path),\n                 when, when))"),

    ("the project's own repository is recorded under whatever spelling the caller used, so a retry "
     "spelled the other way files a duplicate", FORGE,
     '        return "" if self.clone_url(name) == self.repo_path else name',
     "        return name"),

    ("`pr_for_head` looks across every repository again, and hands the sweep the other "
     "repository's pull request to merge", FORGE,
     '                    "SELECT number FROM pull_requests WHERE project = ? AND repo = ? AND '
     'head = ? "\n                    "ORDER BY number DESC LIMIT 1",\n'
     '                    (self.project, key, (head or "").strip())).fetchone()',
     '                    "SELECT number FROM pull_requests WHERE project = ? AND head = ? "\n'
     '                    "ORDER BY number DESC LIMIT 1",\n'
     '                    (self.project, (head or "").strip())).fetchone()'),

    ("the reuse check answers any repository's open pull request, so a proposal in one repository "
     "is handed the other's number", FORGE,
     '                "SELECT number FROM pull_requests WHERE project = ? AND repo = ? AND head = ? '
     '"\n'
     "                \"AND state = 'open' ORDER BY number DESC LIMIT 1\",\n"
     "                (self.project, key, branch)).fetchone()",
     '                "SELECT number FROM pull_requests WHERE project = ? AND head = ? "\n'
     "                \"AND state = 'open' ORDER BY number DESC LIMIT 1\",\n"
     "                (self.project, branch)).fetchone()"),

    # ── 2. every command runs where the pull request is ────────────────────────────────────────
    ("THE DEFECT ITSELF: `_where` ignores the row and answers the project's repository, which "
     "every reader then falls back to", FORGE,
     '        return self.clone_url(str(row.get("repo") or ""))',
     "        return self.repo_path"),

    ("the diff is taken in the project's repository — `pr_diff() answered None`", FORGE,
     "        p = self._git(\"diff\", f\"{row['base']}...{row['head']}\", cwd=where)",
     "        p = self._git(\"diff\", f\"{row['base']}...{row['head']}\")"),

    ("the merge's head is looked for in the project's repository — `the branch is gone from this "
     "repository — nothing to merge`", FORGE,
     "        head_sha = self._sha(head, where)",
     "        head_sha = self._sha(head, self.repo_path)"),

    ("the fast-forward runs in the project's repository, where the proposal's refs do not exist",
     FORGE,
     '            p = self._git("fetch", ".", f"{head}:{base}", cwd=where)',
     '            p = self._git("fetch", ".", f"{head}:{base}")'),

    ("`mergeable_state` looks for the head in the project's repository, and the page says `dirty` "
     "for a proposal that would merge", FORGE,
     "            if not self._sha(head, where):",
     "            if not self._sha(head, self.repo_path):"),

    ("the ancestry is read in the project's repository, so every proposal reads as `behind` and "
     "the loop spends its update attempts on it", FORGE,
     '            if self._git("merge-base", "--is-ancestor", base, head, cwd=where).returncode '
     "!= 0:",
     '            if self._git("merge-base", "--is-ancestor", base, head).returncode != 0:'),

    ("a merge in progress in the PERSON'S repository blocks a proposal in another one", FORGE,
     "            if state and (Path(where) / state / marker).exists():",
     '            if state and (Path(self.repo_path) / ".git" / marker).exists():'),

    ("who has the base out is asked of the person's repository, so their own `main` refuses a "
     "proposal in a repository nobody has out", FORGE,
     '        p = self._git("worktree", "list", "--porcelain", cwd=where)',
     '        p = self._git("worktree", "list", "--porcelain")'),

    # ── 3. the file that was already running ───────────────────────────────────────────────────
    ("the column is never added to a file that already exists, so every running deployment's "
     "first proposal fails with `no column named repo`", DB,
     "        _add_columns(conn)\n",
     ""),

    ("a LOST race to add the column raises out of `connect`, taking down whichever of the worker "
     "and the panel opened second", DB,
     "        except sqlite3.OperationalError:\n"
     "            if column not in _columns(conn, table):\n                raise",
     "        except sqlite3.OperationalError:\n            raise"),

    ("any refusal to add a column is forgiven, and a file without it is handed out as ready", DB,
     "        except sqlite3.OperationalError:\n"
     "            if column not in _columns(conn, table):\n                raise",
     "        except sqlite3.OperationalError:\n            pass"),
]
