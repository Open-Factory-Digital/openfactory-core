"""Whether a CI repair has anything to repair — asked at the point of action, by every caller.

THE WORKER ASKED AND THE BOX DID NOT (#184). `_run_ci_repair` reads the pull request's checks
through the one table (`contracts/checks.py`) before it launches anything. But on a REMOTE box the
pass runs inside the task, and `boxed_job.run_ci_repair` fetched its own log and ran the agent
whatever came back — an empty log included — so the rule held on one door and not on the other,
and the brief the agent got was built from a second read that could differ from the one the
decision was made from. This is the gate both doors go through, and the log it hands back is the
one the decision was made from.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from openfactory.contracts import JobState, RunResult
from openfactory.contracts.checks import ASK, REPAIR, decide
from openfactory.contracts.checks import read as read_checks
from openfactory.techlead.classify import GATE


def what_to_repair(forge_of: Callable[[], object], issue: str,
                   pr_url: str) -> tuple[RunResult | None, str]:
    """`(the hold, "")` when no agent should run on this pull request, else `(None, the log)`.

    THE HOLD CARRIES `merge_refused`, the mark the resume path reads: the work is on the branch
    and the pull request is open, so a person who settles the check and resumes goes back to the
    MERGE watch — not through a full agent pass that re-does work that already exists.

    AN UNREADABLE FORGE IS HELD TOO, and says so. The alternative is what this replaces: launch
    the pass anyway and let it guess. One forge read is retried once, because a hold costs a
    person's attention and a blip should not.

    `forge_of` BUILDS the forge, inside the retry: a credential that fails to mint is the same
    answer as a forge that does not respond."""
    decision, failure = None, ""
    for attempt in (1, 2):
        try:
            decision = decide(read_checks(forge_of(), pr_url))
            break
        except Exception as exc:  # noqa: BLE001 — any forge failure is the same answer here
            failure = str(exc)[:160]
            if attempt == 1:
                time.sleep(2)
    if decision is not None and decision.action == REPAIR:
        return None, decision.evidence
    if decision is not None and decision.action != ASK:
        # The red check went green — or stopped blocking — between the watch's read and this one.
        # Nothing to repair and nobody to ask: the watch carries on, and the pull request is as
        # the reviewer read it (`code_changed=False` brings the stale marker back down, #179).
        return RunResult(ticket_id=issue, state=JobState.PR_OPEN, pr_url=pr_url,
                         code_changed=False,
                         note="no check that blocks this merge is failing — nothing to repair"), ""
    # THE HOLD SAYS WHAT IT IS, AND DOES NOT LEAVE IT TO ITS OWN PROSE. The note below carries a
    # check's NAME and the vendor's remedy — words a team or a forge chose — and the tech-lead's
    # classifier reads a hold's note to decide who acts. A blocking check called "rate-limit
    # tests" was read as throttling and auto-resumed three times at a full agent pass each
    # (measured 2026-09-19). `ASK` is a gate either way: a check no change to the code settles,
    # or one with no log to act on; both wait for a person on the forge.
    #
    # AND THE UNREADABLE FORGE DECLARES NOTHING, deliberately. All this branch knows is the
    # vendor's own error, which is the one case where the sentence IS the evidence — a 403 and a
    # throttle need different people, and the rules read that better than a guess made here.
    if decision is not None:
        note, hold_cause = decision.note, GATE
    else:
        note, hold_cause = (
            f"the checks on this pull request could not be read ({failure}), so no repair pass "
            f"was launched on a failure nobody saw — resume to read them again"), ""
    return RunResult(ticket_id=issue, state=JobState.ON_HOLD, pr_url=pr_url,
                     merge_refused=True, code_changed=False, note=note,
                     hold_cause=hold_cause), ""
