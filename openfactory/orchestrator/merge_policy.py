"""PR merge policy (ADR-0001 D-12). Default is human-on-PR; `auto` merges only when
the review is not rejected, all validations pass, and nothing high-risk was touched.
Pure logic — the orchestrator applies the decision via the forge/tracker."""

from __future__ import annotations

from openfactory.adapters.forge.base import ReviewEvent
from openfactory.contracts import Manifest, ReviewResult, RunResult
from openfactory.policy.profiles import ResolvedProfile

_EVENT: dict[str, ReviewEvent] = {
    "approved": "approve",
    "approved_with_findings": "comment",
    "rejected": "request-changes",
}


def review_event(review: ReviewResult | None, mode: str = "blocking") -> ReviewEvent:
    # ADR-0014: an ADVISORY review is INFORMATIONAL — always a plain PR comment, never a
    # request-changes that would block the merge (or an approve that reads as a gate passing).
    if mode != "blocking":
        return "comment"
    return _EVENT.get(review.decision, "comment") if review else "comment"


# Coverage pragmas are the codebase's convention for genuinely-untestable wiring (a 100%-cov
# repo has hundreds of them). The others — noqa / type: ignore / nosec — SILENCE a real lint /
# type / security error and are rare + suspicious. So they are treated differently at merge (#12,
# ADR-0011): a surviving coverage pragma may auto-merge once an independent review vets it; a hard
# suppression always stays human-gated.
_COVERAGE_SUPPRESSIONS = {"pragma: no cover", "nocov"}


def _hard_suppressions(kinds: list[str]) -> list[str]:
    """The suppressions that silence a real error (lint/type/security) — never auto-mergeable."""
    return sorted({k for k in kinds if k not in _COVERAGE_SUPPRESSIONS})


#: EVERY FACT THAT CAN HOLD A MERGE, AND THEREFORE EVERY FACT THE PULL REQUEST BODY MUST SAY.
#:
#: THIS EXISTS BECAUSE THE SAME DEFECT ARRIVED FOUR TIMES IN ONE REVIEW ROUND. `protected.reason`
#: and `census.reason` were written, tested, and called by nothing; a profile that could not be
#: resolved returned `False` here with no log and no message; and a surviving suppression still
#: says nothing. In every case `should_auto_merge` refused, the job took the ordinary
#: `request_reviewers` branch, and a human opened a pull request that looked exactly like one that
#: was simply ready for review. `policy/protected.py` names the cost in its own words — *"a gate
#: that refuses without naming what it refused is a gate nobody can argue with"* — and then shipped
#: one.
#:
#: A checklist item would have been the WEAK form of this rule, which is the form this platform
#: exists to distrust. So it is a declaration a guard reads:
#: `tests/test_a_gate_that_holds_says_so_where_the_person_decides.py` fails if a branch here holds
#: a merge on a fact that is not named below, and fails if a fact named below never reaches
#: `_pr_body`. Adding a gate now costs one line here and one line there, and forgetting either is
#: red rather than silent.
#: Read as: the fact on the LEFT can hold a merge in this function, and the name on the RIGHT is
#: what `_pr_body` must read in order to SAY so. Both halves are checked mechanically, so neither
#: is prose that can quietly stop being true.
#:
#: SCOPE, NAMED SO IT IS NOT ASSUMED WIDER THAN IT IS (review, #21): this declaration covers
#: `should_auto_merge` only. `machine.py`'s CI-repair path disarms an already-armed auto-merge on
#: its own (the "auto-merge disarmed, forcing human review" branch) — a second place that holds a
#: merge, invisible to the guard below.
HOLDS_THE_MERGE: dict[str, str] = {
    #  what gates here      what `_pr_body` must read to say it
    "all_passed":           "validations",
    "review":               "review",
    "added_suppressions":   "added_suppressions",
    "needs_a_human":        "risk_of_attempt",
    "protected_hits":       "protected_hits",
    "floor_unreadable":     "floor_unreadable",
    "test_census_before":   "test_census_before",
    "profile":              "profile",
}

#: The one condition here that holds a merge and owes the reader NOTHING, with the reason, because
#: an exemption nobody wrote down is indistinguishable from a gate somebody forgot.
SAYS_NOTHING_AND_WHY: dict[str, str] = {
    "merge_policy": "not a hold. `merge_policy: human` is the project's own standing decision, "
                    "made in its manifest before this ticket existed; announcing it on every "
                    "pull request would be the platform explaining the client's configuration "
                    "back to them, on every pull request, for ever.",
}

#: THE SECOND HALF OF A FACT THAT IS ALREADY DECLARED ABOVE — a qualifier a branch's condition
#: reads alongside the fact it belongs to, not a new thing `_pr_body` has to say on its own.
#:
#: EXISTS BECAUSE THE DECLARATION CHECK IS AN ALL-TEST, NOT AN ANY-TEST (review, #21). A branch
#: whose condition names two facts — one declared, one not — used to pass because only ONE name
#: needed to match: `if result.review is not None and result.deploy_window_closed: return False`
#: would have been accepted as `review`, silently promoting an undeclared `deploy_window_closed`
#: to a merge gate nobody is ever told about. Tightened to require every `result`/`manifest` fact
#: a branch's OWN condition reads to be accounted for — declared, exempt, or, for the names below,
#: the second half of something that already is. A name with no home here is indistinguishable
#: from a gate somebody forgot, the same reasoning `SAYS_NOTHING_AND_WHY` already states above.
PART_OF_ANOTHER_FACT: dict[str, str] = {
    "review_mode": "qualifies `review`, not a fact of its own. It selects WHETHER a rejected "
                   "review blocks at all (ADR-0014: advisory is informational, blocking gates) — "
                   "the reader is told the review's verdict, and that selection is not a second "
                   "thing owed separately from the verdict itself.",
    "decision": "qualifies `review`, not a fact of its own. `result.review.decision` is the same "
               "review the `review` row already covers; `_pr_body`'s review section already "
               "reads the decision when it renders the verdict, under that row's name.",
    "test_census_after": "qualifies `test_census_before`, not a fact of its own. The two are one "
                         "comparison — before against after — and `_pr_body`'s census line "
                         "already reads both to render the delta a person sees.",
}


def should_auto_merge(manifest: Manifest, result: RunResult, *,
                     profile: ResolvedProfile | None = None) -> bool:
    if manifest.merge_policy != "auto":
        return False
    if not result.all_passed:
        return False
    # ADR-0014: only a BLOCKING review gates the merge. An advisory review informs a human via a
    # PR comment; the deterministic gates (validations, below) are the real merge floor.
    if (manifest.review_mode == "blocking"
            and result.review is not None and result.review.decision == "rejected"):
        return False
    # Suppressions that SURVIVED the suppression-repair loop (ADR-0011). A HARD suppression
    # (noqa / type: ignore / nosec) always goes to a human. A coverage pragma may auto-merge —
    # but ONLY when an INDEPENDENT review has vetted it (the reviewer caught #207 and passed
    # #69's legit wiring); with no reviewer, ANY surviving suppression stays human-gated (#12).
    if result.added_suppressions:
        if _hard_suppressions(result.added_suppressions):
            return False
        if result.review is None:
            return False
    # RISK IS ASKED IN ONE PLACE NOW, and that place answers a wider question than this loop did.
    # The loop walked the components the diff MATCHED and looked for `high` — so a change matching
    # NO component walked an empty list, found nothing, and merged. A path the manifest never
    # described is the one this platform knows least about; reading the gate as "no component, no
    # objection" inverts it. `needs_a_human` keeps `high` exactly as it was and adds that case. A
    # project that declares no components at all is untouched: it has not failed to declare
    # anything, and gating it would be the fix doing more damage than the defect (`risk.py`).
    from openfactory.orchestrator.risk import of_attempt

    assessment = of_attempt(manifest, result)
    if assessment.needs_a_human:
        return False
    # THE THING BEING MEASURED CANNOT ALSO MOVE THE RULER. A change that edited the manifest naming
    # its own gates, the profile saying what the project is, or the CI configuration is human-gated
    # by definition — not refused, and nothing is lost: it is exactly the ticket a person signs off.
    # `roles/executor.md` asked for this in prose, which is the weak form of a rule.
    if result.protected_hits:
        return False
    # AND THE OTHER HALF OF THE SAME QUESTION, WHICH IS NOT A FINDING ABOUT THIS CHANGE. A build
    # that cannot read its own protected-path floor cannot say which paths were protected, and the
    # honest answer to "may this merge by itself" is no. Read as its own field rather than smuggled
    # in as a list of paths: the record a human is shown must not claim the client's change touched
    # files it did not touch. `policy/protected.floor_unreadable` carries the reasoning.
    if result.floor_unreadable:
        return False
    # THE CENSUS. A suite that stopped COLLECTING tests exits 0 exactly as convincingly as one that
    # passed them, and only the exit code was ever read (`policy/census.py`).
    #
    # THE THREE STATES ARE READ AS THREE. `before is None` is no census — the project declares no
    # inventory command, or it could not be read on the clean tree — and that gates nothing, or
    # every project on earth would be human-gated for a feature it never adopted. A census that
    # existed before the change and could not be taken after it is the agent having broken
    # enumeration, which is one of the failures this exists to catch, so it holds.
    before = result.test_census_before
    after = result.test_census_after
    if before is not None and (after is None or after < before):
        return False
    # THE PROJECT'S CLASS MAY STRENGTHEN THIS GATE AND MAY NEVER WEAKEN IT. A profile declares
    # what a risk level COSTS in this kind of project — a regulated client sends `high` to a
    # person even where the manifest says `auto` — so it is asked after the checks above and can
    # only subtract from the answer, never add to it.
    if manifest.profile and profile is None:
        # A MANIFEST THAT NAMES A CLASS AND A CALLER THAT DID NOT RESOLVE IT IS A HOLD. Reading
        # the unresolved profile as "no extra opinion" would auto-merge a regulated project under
        # generic rules precisely when the wiring is wrong, which is the failure that must not be
        # silent. The direction is closed, the same way the floor's is.
        return False
    if profile is not None and profile.requires_human(assessment.level):
        return False
    return True


def format_review(review: ReviewResult) -> str:
    lines = [f"**{review.decision}** — score {review.score}", "", review.summary]
    for f in review.findings:
        loc = f" (`{f.file}:{f.line}`)" if f.file else ""
        lines.append(f"- **{f.severity}**{loc}: {f.description}")
    return "\n".join(lines)
