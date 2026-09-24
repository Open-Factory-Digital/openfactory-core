"""Proven by breaking it — a ticket whose pull request is open is never run again, and its branch is
never rebuilt (#302).

An activity timed out while the attempt under it went on and finished: gates green, review
approved, pull request opened, `pr_open` journalled. The workflow parked the timeout as
self-healing, and its timer resumed the job by default. The runner took the resume for a first run
— `resume_handle` was None, because the park a timeout makes carries none — so `sandbox.prepare`
recreated `openfactory/<n>` from the base, deleting the delivered commit, and the agent did the
whole ticket again at full price.

FOUR CLAIMS:

  1. **Delivered is read from the forge**, before anything moves: an open pull request from the
     ticket's branch sends the run back to the merge with no agent pass and the branch untouched,
     as a person's gate, with the card saying so and the journal saying why.
  2. **Open is delivered, and nothing else is.** A closed or merged pull request is not gone back
     to.
  3. **Could not look is not "there is none."** A lookup that answers None, or a state read that
     raises, holds the run having run nothing.
  4. **The self-heal carries the parked attempt's handle**, as the other two resuming parks do, so
     a hold that pushed its partial work is continued rather than rebuilt.

The guard is `tests/test_a_finished_job_is_never_restarted_from_the_base.py`.
"""

TEST = "tests/test_a_finished_job_is_never_restarted_from_the_base.py"

MACHINE = "openfactory/orchestrator/machine.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"

MUTATIONS = [
    # ── claim 1: delivered is read, and handed back to the merge ─────────────────────────────
    ("THE DEFECT ITSELF: nothing asks the forge, so a resume after a delivered attempt runs the "
     "ticket again over a branch rebuilt from the base",
     MACHINE,
     "        delivered = self._already_delivered(ticket, owner, branch)\n",
     "        delivered = None\n"),

    ("the delivered pull request is handed back as armed for auto-merge — a merge nobody gated, "
     "on gates and a review that are not in hand",
     MACHINE,
     "            ticket_id=ticket.id, state=JobState.PR_OPEN, branch=branch, pr_url=pr,\n",
     "            ticket_id=ticket.id, state=JobState.PR_OPEN, branch=branch, pr_url=pr,\n"
     "            auto_merge=True,\n"),

    ("the card is left where the run found it — the board does not say a person is needed",
     MACHINE,
     "        self._set_state(ticket, JobState.PR_OPEN, needs_person=True)\n"
     "        return self._charged(RunResult(\n",
     "        return self._charged(RunResult(\n"),

    ("the journal never says why this run did nothing",
     MACHINE,
     "                   f\"▶ {pr} is already open from `{branch}` — the attempt that opened it "
     "delivered \"\n",
     "                   f\"▶ {branch} \"\n"),

    # ── claim 2: open is delivered, and nothing else is ──────────────────────────────────────
    ("a closed or merged pull request is taken for delivered work, so a card that comes back is "
     "refused without a word",
     MACHINE,
     "        if status != \"open\":\n            return None\n",
     "        if status not in (\"open\", \"closed\", \"merged\"):\n            return None\n"),

    # ── claim 3: could not look is not "there is none" ───────────────────────────────────────
    ("a lookup that could not read is taken for 'no pull request', and the run goes on",
     MACHINE,
     "        if pr is None:\n            why = ",
     "        if pr is None:\n            return None\n            why = "),

    ("a state read that raised is taken for 'no pull request', and the run goes on",
     MACHINE,
     "            pr, status = None, str(exc)[:200]\n",
     "            pr, status = \"\", \"\"\n"),

    # ── claim 4: the self-heal carries the handle ─────────────────────────────────────────────
    ("the self-heal drops the parked attempt's handle, so preserved work is rebuilt from the base",
     WORKFLOW,
     "                            resume_handle = parked.resume_handle\n"
     "                            result = None\n"
     "                            continue\n"
     "                        if act == \"skip\":\n",
     "                            result = None\n"
     "                            continue\n"
     "                        if act == \"skip\":\n"),
]
