"""#180, the second half, proven by breaking it — a card is closed when its pull request MERGES,
never when a merge was only asked for, and the tracker does not repeat the forge's closing word.

#195 made the GitHub tracker row close the issue at Done, wherever it lives. That made Done a
CLOSE — and the human merge gate wrote Done on a merge that was only TRIGGERED: `merge_pr` arms
`--auto` on GitHub and auto-complete on Azure DevOps, the port says so, and the gate took the call
for the merge. A card whose pull request was still open on checks that could fail was closed as
delivered. The machine's self-merge took `force_merge`'s answer for the merge the same way.

THREE CLAIMS:

  1. **A merge a person asked for is Done only once the forge reads it merged** — on the GitHub
     row and the Azure DevOps row, driven through the real merge and status activities; one that
     is closed instead is never Done; and the wait is shown as the forge's, not the person's.
  2. **The machine's self-merge is read back** before it is claimed.
  3. **The tracker row reads the issue first**, and writes nothing to one the forge's closing word
     already closed; one closed after a refused close is not reported as left open.

The guard is `tests/test_a_card_is_closed_only_when_its_work_merges.py`.
"""

TEST = "tests/test_a_card_is_closed_only_when_its_work_merges.py"

WORKFLOW = "openfactory/runtime/temporal/workflow.py"
TRACKER = "openfactory/adapters/tracker/github.py"

MUTATIONS = [
    # ── claim 1: the person's merge ───────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: a merge a person asked for is claimed as merged, and the card closed",
     WORKFLOW,
     '                if workflow.patched("a-merge-asked-for-is-not-a-merge"):\n',
     "                if False:\n"),

    ("the approved merge stays on the person's path, so the watch asks them for it again",
     WORKFLOW,
     "                    result.auto_merge = True\n"
     "                    self._merge_wait = {\"pr_url\": pr_url, \"auto\": True,\n",
     "                    self._merge_wait = {\"pr_url\": pr_url, \"auto\": True,\n"),

    # ── claim 2: the self-merge ───────────────────────────────────────────────────────────────
    ("THE DEFECT ON THE SELF-MERGE: an accepted self-merge is claimed without reading it back",
     WORKFLOW,
     '                                      or await self._pr_status(params, pr_url) == "merged"):\n',
     "                                      or True):\n"),

    ("the self-merge's read-back is the old path's, so nothing is read back", WORKFLOW,
     '                    if merged_ok and (not workflow.patched("a-self-merge-is-read-back")\n',
     "                    if merged_ok and (True\n"),

    # ── claim 3: the tracker row ──────────────────────────────────────────────────────────────
    ("THE DUPLICATE: the row closes an issue the forge's closing word already closed", TRACKER,
     "        repo, num = self._locate(ref)\n"
     "        if self._reads_closed(repo, num):\n"
     "            return\n"
     "        try:\n",
     "        repo, num = self._locate(ref)\n"
     "        try:\n"),

    ("the re-read after a refused close is dropped, so a card closed meanwhile is reported open",
     TRACKER,
     "            why = str(exc) or type(exc).__name__\n"
     "        if self._reads_closed(repo, num):\n"
     "            return\n",
     "            why = str(exc) or type(exc).__name__\n"),

    ("a state that cannot be read counts as CLOSED, so a delivered card nobody could read stays "
     "open and nobody is told", TRACKER,
     '            log.debug("could not read the state of %s#%s: %s", repo, num, exc)\n'
     "            return False\n",
     '            log.debug("could not read the state of %s#%s: %s", repo, num, exc)\n'
     "            return True\n",
     "tests/test_a_delivered_card_is_closed_by_its_tracker.py"),

    ("an open issue reads as closed, so no delivered card is ever closed", TRACKER,
     '            return seen.returncode == 0 and (seen.stdout or "").strip().upper() == "CLOSED"\n',
     '            return seen.returncode == 0\n'),
]
