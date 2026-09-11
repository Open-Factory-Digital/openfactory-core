"""ADR-0049 slice 3d, proven by breaking it — a resume on a refused merge goes back to the merge.

FOUR CLAIMS:

  1. **A resume on a merge refusal re-enters the MERGE**, and the agent does not run again. The
     count of `run_job` calls is the assertion, because the agent pass is the thing being charged
     for: the work is already committed on the branch and already in an open pull request.
  2. **The decision is a FIELD.** `merge_refused` is what the resume path reads; the note beside
     it is prose in the forge's own words, and a card about wording must not be able to turn a
     free resume into a paid one.
  3. **The watch is re-entered with the PULL REQUEST, not with the park.** The hold has a note and
     a URL; the branch and the manifest facts live on the result the watch was holding.
  4. **The wait belongs to the watch.** A park inside it clears `_merge_wait`, or the panel says a
     merge is being watched on a job that is waiting for a person.

WHAT IS NOT A ROW HERE, AND WHY IT IS NOT ONE. Removing `workflow.patched("hold-resumes-into-merge")`
cannot be shown red by anything in this repository: the marker changes only what a REPLAY of a
pre-patch history does — a job parked on the old build with the worker upgraded underneath — and
every engine the suite starts, ephemeral or not, begins from an empty history. It is written here
rather than added as a cut that would quietly survive, and rather than declared
`PROVED_ONLY_WHERE`: that marker is for a row another TREE proves (an add-on the export excludes),
and no tree proves this one.

The guard under test is `tests/test_a_resume_re_enters_the_merge.py`.
"""

TEST = "tests/test_a_resume_re_enters_the_merge.py"

SLICE = "tests/test_a_resume_re_enters_the_merge.py"

WORKFLOW = "openfactory/runtime/temporal/workflow.py"
RUN = "openfactory/contracts/run.py"

MUTATIONS = [
    # ── 1. the resume goes back to the merge ───────────────────────────────────────────────────
    ("the resume falls through to the agent again — the pull request is open, the work is on the "
     "branch, and a person who cleared their tree pays for a full pass before the merge is "
     "re-tried", WORKFLOW,
     "                    if (parked.merge_refused and self._refused_merge is not None\n"
     '                            and workflow.patched("hold-resumes-into-merge")):\n'
     "                        resume_into_merge, self._refused_merge = self._refused_merge, None\n"
     "                        result = None\n                        continue\n",
     "", SLICE),

    ("the loop never consumes what the resume left it, so the merge is entered on every "
     "iteration and the agent never runs at all", WORKFLOW,
     "                    pr_again, resume_into_merge = resume_into_merge, None",
     "                    pr_again = resume_into_merge", SLICE),

    # ── 2. the mark, and not the prose under it ────────────────────────────────────────────────
    ("the refusal stops marking the hold, so the field the resume reads is never true", WORKFLOW,
     "                merge_refused=True,", "                merge_refused=False,", SLICE),

    ("the mark defaults to true, so every hold in the platform claims a merge was refused",
     RUN, "    merge_refused: bool = False", "    merge_refused: bool = True", SLICE),

    ("the decision is read off the note's wording instead of the mark — one translation card away "
     "from sending every refused merge through a full agent pass", WORKFLOW,
     "                    if (parked.merge_refused and self._refused_merge is not None\n"
     '                            and workflow.patched("hold-resumes-into-merge")):',
     '                    if ("refused it" in (parked.note or "")\n'
     "                            and self._refused_merge is not None\n"
     '                            and workflow.patched("hold-resumes-into-merge")):', SLICE),

    # ── 3. re-entered with the pull request ────────────────────────────────────────────────────
    ("the watch is re-entered with the PARK — the merge lands and the tail that watches, promotes "
     "and settles has no branch to work from", WORKFLOW,
     "            self._refused_merge = result\n",
     "            self._refused_merge = RunResult(ticket_id=result.ticket_id,\n"
     "                                            state=JobState.PR_OPEN, pr_url=pr_url)\n",
     SLICE),

    # ── 4. the wait belongs to the watch ───────────────────────────────────────────────────────
    ("the merge wait outlives the watch, so a job parked for a person still tells the panel it is "
     "being merged", WORKFLOW,
     "        try:\n            return await self._ci_merge_loop(params, result)\n"
     "        finally:\n            self._merge_wait = None",
     "        return await self._ci_merge_loop(params, result)", SLICE),
]
