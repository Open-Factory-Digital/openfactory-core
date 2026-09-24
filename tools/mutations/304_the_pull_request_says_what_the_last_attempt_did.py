"""Proven by breaking it — the pull request says what the LAST attempt did, on every forge row
(#304).

A job ran a second attempt on the same head: new gates, a new review (80 against the first 85), a
new cost, and `open_pr` again. Every row answered the pull request already open from that head and
returned it without looking at what it had been handed, so the body a person approves the merge on
went on describing the first attempt's commit while the second attempt's merged. The local row's
`base_sha` stayed the first attempt's base as well.

FOUR CLAIMS:

  1. **The local row brings the open pull request up to date**: title, body, and both shas read
     again — the base the head was cut from and the change's identity.
  2. **GitHub does**, with one `gh pr edit` carrying both fields, in the repository the lookup
     searched.
  3. **Azure Repos does**, with one PATCH carrying both, the description fitted to the vendor's
     ceiling.
  4. **A refused update is said by name and never raised**: the pull request exists, the work is
     pushed, and the job must not fail over a description — nor leave it stale in silence.

The guard is `tests/test_the_pull_request_says_what_the_last_attempt_did.py`; its last test is the
filed sequence on the real workflow, runner, worktree box and local forge.
"""

TEST = "tests/test_the_pull_request_says_what_the_last_attempt_did.py"

LOCAL = "openfactory/adapters/forge/local.py"
GITHUB = "openfactory/adapters/forge/github.py"
AZURE = "openfactory/adapters/forge/azure_devops.py"

MUTATIONS = [
    # ── claim 1: the local row ────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF, on the row it was measured on: the open pull request is answered and "
     "left as the first attempt wrote it",
     LOCAL,
     "            if live:\n                conn.execute(\n",
     "            if live and False:\n                conn.execute(\n"),

    ("the body is left as it was and only the title moves", LOCAL,
     "\"UPDATE pull_requests SET title = ?, body = ?, base_sha = ?, patch_id = ?, \"",
     "\"UPDATE pull_requests SET title = ?, body = COALESCE(body, ?), base_sha = ?, "
     "patch_id = ?, \""),

    ("`base_sha` keeps the base the first attempt was opened on", LOCAL,
     "\"UPDATE pull_requests SET title = ?, body = ?, base_sha = ?, patch_id = ?, \"",
     "\"UPDATE pull_requests SET title = ?, body = ?, base_sha = COALESCE(base_sha, ?), "
     "patch_id = ?, \""),

    ("`patch_id` keeps the first attempt's change", LOCAL,
     "\"UPDATE pull_requests SET title = ?, body = ?, base_sha = ?, patch_id = ?, \"",
     "\"UPDATE pull_requests SET title = ?, body = ?, base_sha = ?, "
     "patch_id = COALESCE(patch_id, ?), \""),

    # ── claim 2: GitHub ───────────────────────────────────────────────────────────────────────
    ("GitHub answers the open pull request and edits nothing", GITHUB,
     "            self._bring_up_to_date(existing, repo=target, title=title, body=body)\n",
     ""),

    ("the edit carries the title and drops the body — the part a person approves on", GITHUB,
     "            done = self._gh([\"pr\", \"edit\", pr, \"--repo\", repo, \"--title\", title, "
     "\"--body\", body])\n",
     "            done = self._gh([\"pr\", \"edit\", pr, \"--repo\", repo, \"--title\", title])\n"),

    ("the edit is aimed at this adapter's own repository, not the one the lookup searched",
     GITHUB,
     "            done = self._gh([\"pr\", \"edit\", pr, \"--repo\", repo, \"--title\", title, ",
     "            done = self._gh([\"pr\", \"edit\", pr, \"--repo\", self.repo, \"--title\", "
     "title, "),

    # ── claim 3: Azure Repos ──────────────────────────────────────────────────────────────────
    ("Azure answers the open pull request and patches nothing", AZURE,
     "            self._bring_up_to_date(client, target, existing, title=title, body=body)\n",
     ""),

    ("the description goes out unfitted, and a long one is a 400 on the reuse path", AZURE,
     "                        body={\"title\": title, \"description\": fitted})\n",
     "                        body={\"title\": title, \"description\": body})\n"),

    ("the patch carries the description and not the title", AZURE,
     "                        body={\"title\": title, \"description\": fitted})\n",
     "                        body={\"description\": fitted})\n"),

    # ── claim 4: a refusal is said, and never raised ──────────────────────────────────────────
    ("GitHub's refusal is swallowed without a word", GITHUB,
     "        if done.returncode != 0:\n            log.warning(\"OPENFACTORY_PR_BODY_REFUSED",
     "        if done.returncode != 0 and False:\n            log.warning("
     "\"OPENFACTORY_PR_BODY_REFUSED"),

    ("Azure's refusal is raised, and a job that did its work fails over a description", AZURE,
     "        except (AzureDevOpsError, ValueError) as exc:\n"
     "            log.warning(\"OPENFACTORY_PR_BODY_REFUSED",
     "        except ValueError as exc:\n"
     "            log.warning(\"OPENFACTORY_PR_BODY_REFUSED"),
]
