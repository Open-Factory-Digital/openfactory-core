"""#187 — the pull request must not present a stale review as current.

Both directions, as the card asked: a review whose diff was rewritten has to say so ON THE PULL
REQUEST, and a review that is still current must not be marked — otherwise the marker stops
meaning anything and the finding a person came to read is stamped as past while it still applies.
"""

TEST = "tests/test_the_pull_request_says_what_the_card_says.py"

MUTATIONS = [
    # ── the amendment has to happen at all, and only where it is true ───────────────────────────
    ("a pass rewrites the pull request and its body still reads as current",
     "openfactory/orchestrator/machine.py",
     "            if pushed or review is not None:\n"
     "                self._republish_review(pr_url, review=review)",
     "            if False:\n"
     "                self._republish_review(pr_url, review=review)"),

    ("a pass that changed nothing dates a review that is still perfectly good",
     "openfactory/orchestrator/machine.py",
     "            if pushed or review is not None:",
     "            if True:"),

    ("the fresh reading is thrown away and the old one is merely dated",
     "openfactory/orchestrator/machine.py",
     "            if pushed or review is not None:\n"
     "                self._republish_review(pr_url, review=review)\n"
     "            self._emit(ticket, \"pr\", \"ci-repair pushed — CI re-running\", url=\"\")",
     "            if pushed or review is not None:\n"
     "                self._republish_review(pr_url, review=None)\n"
     "            self._emit(ticket, \"pr\", \"ci-repair pushed — CI re-running\", url=\"\")"),

    ("a re-review leaves the out-of-date marker standing on the pull request",
     "openfactory/orchestrator/machine.py",
     "            self._republish_review(pr_url, review=review)\n"
     "            # THE PERSON IS STILL THE ONE DECIDING.",
     "            # THE PERSON IS STILL THE ONE DECIDING."),

    # ── what the amendment says ─────────────────────────────────────────────────────────────────
    ("the caveat goes up and the clauses under it still read as current facts",
     "openfactory/orchestrator/machine.py",
     "        stamped = [row if (not row.strip() or row.lstrip().startswith(\">\") "
     "or row.startswith(was))\n"
     "                   else f\"{was}{row}\" if not row.startswith(\"- \")\n"
     "                   else f\"- {was}{row[2:]}\" for row in rest]",
     "        stamped = list(rest)"),

    ("a second pass stacks a second caveat on the same section",
     "openfactory/orchestrator/machine.py",
     "        if any(row.strip() == caveat.strip() for row in section):\n"
     "            return None",
     "        if False:\n"
     "            return None"),

    ("the reviewer's own verdict is deleted instead of dated",
     "openfactory/orchestrator/machine.py",
     "        return [head, \"\", caveat, \"\"] + stamped",
     "        return [caveat] + stamped"),

    ("the caveat is welded English on a client's pull request",
     "openfactory/orchestrator/machine.py",
     '        caveat = self._say("pr.review.out-of-date")',
     '        caveat = "> **Review out of date** — a pass rewrote this pull request."'),

    ("the stamp is welded English beside a translated caveat",
     "openfactory/orchestrator/machine.py",
     '        was = self._say("pr.review.was")',
     '        was = "was: "'),

    ("this surface invents its own word for what the panel already calls it",
     "openfactory/techlead/voice.py",
     '        "en": "> **Review out of date** — a pass rewrote this pull request after the reviewer "',
     '        "en": "> **Review stale** — a pass rewrote this pull request after the reviewer "'),

    # ── the reader and the writer, and the read that failed ─────────────────────────────────────
    ("the reader looks for a heading the writer does not write",
     "openfactory/orchestrator/machine.py",
     "                      if row.startswith(_REVIEW_HEADING)), None)",
     '                      if row.startswith("## Review: ")), None)'),

    ("a body that could not be read is overwritten with one built from nothing",
     "openfactory/orchestrator/machine.py",
     "        if body is None:",
     "        if body is None and False:"),

    # ── the port ────────────────────────────────────────────────────────────────────────────────
    ("a failed read is handed back as an empty description",
     "openfactory/adapters/forge/github.py",
     '        got = self._gh(["pr", "view", pr, "--repo", repo or self.repo, "--json", "body",\n'
     '                        "-q", ".body"])\n'
     "        if got.returncode != 0:",
     '        got = self._gh(["pr", "view", pr, "--repo", repo or self.repo, "--json", "body",\n'
     '                        "-q", ".body"])\n'
     "        if False:"),

    ("a refused write reports success, so the caller believes the pull request was re-dated",
     "openfactory/adapters/forge/github.py",
     '        done = self._gh(["pr", "edit", pr, "--repo", repo or self.repo, "--body", body])\n'
     "        if done.returncode != 0:",
     '        done = self._gh(["pr", "edit", pr, "--repo", repo or self.repo, "--body", body])\n'
     "        if False:"),

    ("the second vendor's write is aimed at nothing and reports success anyway",
     "openfactory/adapters/forge/azure_devops.py",
     '            client.call("PATCH", f"git/repositories/{target}/pullrequests/{pr_id}",\n'
     '                        body={"description": body})\n'
     "            return True",
     "            return True"),

    ("the second vendor cuts to its ceiling and then appends past it — a 400 every time",
     "openfactory/adapters/forge/azure_devops.py",
     "            body = body[: self._DESCRIPTION_MAX - len(note)] + note",
     "            body = body[: self._DESCRIPTION_MAX] + note"),

    ("the second vendor loses an absent description behind 'could not read'",
     "openfactory/adapters/forge/azure_devops.py",
     '            return str(self._pr(pr, repo=repo).get("description") or "")',
     '            return self._pr(pr, repo=repo).get("description")'),
]
