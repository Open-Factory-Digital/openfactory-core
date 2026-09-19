"""#184 (the comment), proven by breaking it — a person's answer is heard on every path of the watch.

The gate is published as soon as the merge watch begins and the answer is stored on arrival, but
the only place that READ it sat in the branch the loop takes when the checks are NOT red. While
they were red: repair → sleep → re-check → repair → `CI still failing`, with a Discard or a Merge
accepted, confirmed and never acted on.

THREE CLAIMS:

  1. **An answer is consumed on every path, before anything is done about the checks** — it
     pre-empts a pending repair, including one whose read was already in flight, and every nap in
     the loop wakes for it.
  2. **While a repair pass rewrites the pull request the gate refuses**, and re-opens when the
     pass is over.
  3. **A job already in the loop replays what it recorded, and says it cannot hear.** The marker
     row is red through a REAL replay of a history that carries an unread answer — with nobody
     answering the two arms write the same history, measured, so only such a recording can tell.

The guard is `tests/test_the_merge_gate_is_heard_on_every_path.py`.
"""

TEST = "tests/test_the_merge_gate_is_heard_on_every_path.py"

WORKFLOW = "openfactory/runtime/temporal/workflow.py"
VIEW = "openfactory/runtime/temporal/view.py"

MUTATIONS = [
    # ── claim 1 ───────────────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: a stored answer is not read before the checks are acted on", WORKFLOW,
     "            if heard and self._gate is not None:\n",
     "            if False:\n"),

    ("the nap after a repair does not wake for an answer, so a click waits out the poll and the "
     "next repair's reads", WORKFLOW,
     "        with contextlib.suppress(TimeoutError):\n"
     "            await workflow.wait_condition(lambda: self._gate is not None, timeout=nap)\n",
     "        await workflow.sleep(nap)\n"),

    ("the nap after a branch update is a plain sleep again", WORKFLOW,
     "                    await self._rest(_CI_POLL, heard)  # let the update re-trigger CI\n",
     "                    await workflow.sleep(_CI_POLL)  # let the update re-trigger CI\n"),

    ("the nap after a refused self-merge is a plain sleep again", WORKFLOW,
     "                    await self._rest(_CI_POLL, heard)  # merge refused → re-poll and react\n",
     "                    await workflow.sleep(_CI_POLL)  # merge refused → re-poll and react\n"),

    # ── claim 2 ───────────────────────────────────────────────────────────────────────────────
    ("the gate stays answerable while a repair pass is rewriting the pull request", WORKFLOW,
     '                                    "working": True,\n'
     '                                    "note": f"a check that blocks the merge is failing — "\n',
     '                                    "note": f"a check that blocks the merge is failing — "\n'),

    ("the gate never re-opens after the pass", WORKFLOW,
     "                self._merge_wait = {\n"
     '                    "pr_url": pr_url, "auto": bool(result.auto_merge),\n'
     '                    "note": f"repair pass {attempts} is over',
     "                self._merge_wait = {\n"
     '                    "pr_url": pr_url, "auto": bool(result.auto_merge), "working": True,\n'
     '                    "note": f"repair pass {attempts} is over'),

    # ── claim 3 ───────────────────────────────────────────────────────────────────────────────
    ("the new consumption is not behind its marker, so a job already in the loop cannot replay",
     WORKFLOW,
     '            heard = (workflow.patched("the-gate-is-heard-on-every-path")\n',
     "            heard = (True\n"),

    ("a job that cannot hear publishes an answerable gate over the red path", WORKFLOW,
     '                    **({} if heard else {"cannot_hear": _DEAF_WHILE_RED}),\n',
     "                    **{},\n"),

    ("every job is told it cannot hear", WORKFLOW,
     '                    **({} if heard else {"cannot_hear": _DEAF_WHILE_RED}),\n',
     '                    **{"cannot_hear": _DEAF_WHILE_RED},\n'),

    ("the seam every surface answers through ignores what the job says about itself", VIEW,
     "    if isinstance(said, str) and said.strip():\n",
     "    if False:\n"),
]
