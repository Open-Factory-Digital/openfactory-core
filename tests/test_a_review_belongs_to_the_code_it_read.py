"""A verdict about a diff that has been rewritten is not evidence about the diff (#153).

MEASURED ON THE PILOT, and it nearly cost the work. The review rejected #101 at 16:45 with one
high finding: the ticket's deliverable was not reachable from stored data, because `finish_reason`
was logged at provider level with no `episode_id`. Two repair passes then rewrote the pull request
— the second adding exactly the migration that finding asked for. At 18:09 the operator typed
`pode dar o merge` ("you can merge"), and the tech-lead answered — translated from its own pt-BR:

    this platform's review REJECTED the PR (score 58) … `finish_reason` is only captured in a
    provider-level log line, with no `episode_id` … my recommendation is not to merge as it
    stands … the way forward is to discard the PR

    ▶ discard #101

Every word of that was in the store, and none of it was still true. The button offered would have
closed a pull request that had already fixed what the button's own reason complained about.

NOTHING RE-RAN THE REVIEWER — when this card was written — so the honest move was the one this
platform makes everywhere else: stop asserting. An answer it can no longer support becomes UNREAD
rather than staying confident; `verdict_line` already says exactly that about `review: UNREADABLE`,
and a stale verdict is the same class of fact.

#181 LATER MADE THE RE-REVIEW AN ACTION, and none of the above stopped being true: the marker is
still what an unre-read diff deserves, and it is still the fallback for a pass that produced no
verdict. What changed is that a person standing at the gate now has a way out of it.
"""

from __future__ import annotations

import ast
import inspect

from openfactory.techlead.conversation import verdict_line

FRESH = {"decision": "rejected", "score": 58,
         "findings": [{"severity": "high", "description": "the deliverable is not reachable",
                       "file": "src/providers/openai.py"}],
         "gates": [{"name": "test", "passed": True}]}


def test_a_fresh_verdict_reads_exactly_as_before():
    """The twin first: a review of the code in hand is the tech-lead's best evidence, and this
    whole card must not make it hedge about a verdict that is perfectly good."""
    line = verdict_line({"verdict": FRESH})

    assert "review: rejected (score 58)" in line
    assert "OUT OF DATE" not in line
    assert "the deliverable is not reachable" in line


def test_a_rewritten_diff_makes_the_verdict_say_so_FIRST():
    line = verdict_line({"verdict": {**FRESH, "stale": "a pass rewrote the pull request"}})

    assert line.startswith("review: OUT OF DATE"), (
        f"the caveat is not the first thing a reader meets: {line[:120]}")
    assert "a pass rewrote the pull request" in line, "it does not say WHAT happened"
    assert "not evidence" in line


def test_the_old_findings_are_still_CARRIED_not_deleted():
    """Deleting them would be the opposite mistake. The reviewer's reasoning is what tells a human
    where to look in the new diff — it just may not be presented as current."""
    line = verdict_line({"verdict": {**FRESH, "stale": "a pass rewrote it"}})

    assert "the deliverable is not reachable" in line
    assert "review: rejected (score 58)" in line


def test_the_tech_lead_is_TOLD_what_an_out_of_date_review_may_not_be_used_for():
    """The line above is data; this is the instruction that stops it being read as a live finding.
    Without it the model has a caveat and a rejection in the same paragraph and picks the louder
    one — which is what it did on the pilot."""
    from openfactory.techlead import conversation

    src = inspect.getsource(conversation)
    prompt = "".join(node.value for node in ast.walk(ast.parse(src))
                     if isinstance(node, ast.Constant) and isinstance(node.value, str)
                     and "OUT OF DATE" in node.value)

    assert prompt, "nothing in the prompt mentions an out-of-date review"
    assert "discard" in prompt, "it does not forbid the recommendation the pilot was given"
    assert "another pass" in prompt or "diff" in prompt, "it names no alternative"


def test_the_ENGINE_marks_it_wherever_it_rewrites_a_reviewed_PULL_REQUEST():
    """The reachability half. Everything above states what the tech-lead does with `stale`;
    nothing above proves anybody sets it. Both places that push an agent's work onto a reviewed
    pull request must — `repair_ci` and `adjust_pr` — and the marking must come BEFORE the push,
    since a worker that dies mid-activity must not leave a confident stale verdict behind."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    for method, activity in ((JobWorkflow._ci_merge_loop, "repair_ci"),
                             (JobWorkflow._answer_merge_gate, "adjust_pr")):
        tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(method)))
        pushes = [n.lineno for n in ast.walk(tree)
                  if isinstance(n, ast.Name) and n.id == activity]
        marks = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and n.attr == "_the_reviewed_code_is_gone"]
        assert pushes, f"{method.__name__} no longer launches {activity} — this guard measures nothing"
        assert marks, f"{method.__name__} rewrites the reviewed diff and leaves the verdict standing"
        assert min(marks) < min(pushes), (
            f"{method.__name__} marks the verdict stale only AFTER {activity} pushes — a worker "
            f"that dies in between leaves a confident verdict about code that is gone")


def test_marking_an_ABSENT_verdict_invents_nothing():
    """A job whose review never ran has no verdict, and "the review is out of date" about a review
    that does not exist is a worse answer than silence."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    job = JobWorkflow.__new__(JobWorkflow)
    job._verdict = None
    job._the_reviewed_code_is_gone("a pass rewrote it")
    assert job._verdict is None

    job._verdict = dict(FRESH)
    job._the_reviewed_code_is_gone("a pass rewrote it")
    assert job._verdict["stale"] == "a pass rewrote it"
    assert job._verdict["decision"] == "rejected", "it overwrote what it was annotating"


# ── the caveat has to be in the SHAPE, not only in the prose (#154) ─────────────────────────────
#
# Leading with it was not enough. Reading the very next answer after #153 shipped, the tech-lead
# hedged the FINDINGS correctly and then reported the suppressions as a live fact — "the diff adds
# `type: ignore`, which a human must confirm" — about a diff that by then added none (grepped: 0).
# One sentence of warning has to be re-applied by the reader to every clause after it, and a reader
# applies it to the clause it was standing next to.

def test_every_clause_after_the_caveat_is_STAMPED():
    line = verdict_line({"verdict": {**FRESH, "suppressions": ["type: ignore"],
                                     "stale": "a pass rewrote it"}})
    head, *rest = line.split(" · ")

    assert head.startswith("review: OUT OF DATE")
    assert rest, "there is nothing after the caveat — this guard measures nothing"
    unstamped = [p for p in rest if not p.startswith("was: ")]
    assert not unstamped, (
        f"these read as facts about the pull request as it stands: {unstamped}")


def test_a_FRESH_verdict_is_stamped_nowhere():
    """The twin. A review of the code in hand is the tech-lead's best evidence and must not arrive
    wearing a past tense."""
    line = verdict_line({"verdict": {**FRESH, "suppressions": ["type: ignore"]}})

    assert "was:" not in line, line
    assert line.startswith("review: rejected")


def test_a_lone_caveat_is_not_stamped_into_nonsense():
    """A stale verdict carrying nothing else must not render `was:` against its own warning."""
    line = verdict_line({"verdict": {"stale": "a pass rewrote it"}})
    assert line.startswith("review: OUT OF DATE")
    assert "was:" not in line


def test_the_tech_lead_is_told_not_to_send_people_after_a_capability_that_does_not_exist():
    """MEASURED ON THE PILOT. Told the review was stale, it recommended *"asking for a new review
    pass on the current PR"* — and there was no such action in the catalogue, on any deployment.
    That is the defect this repository names by number: a message dictating a command nobody can
    run is worse than no advice, because the operator does what they were told and nothing happens.

    THE RULE OUTLIVED THE FACT (#181). The answer then was to forbid the advice; the answer now is
    that the capability exists — `review` is a row, so the sentence forbidding it became the new
    version of the same defect, a platform hiding a verb from the person who needs it. What this
    guard pins is the RULE: whatever the prompt says about a stale reading, every option it names
    must be one the catalogue can perform.
    """
    import openfactory.actions as actions
    from openfactory.techlead import conversation

    assert "review" in actions.CATALOG, (
        "the re-review row is gone — then the prompt below is sending people after a capability "
        "that does not exist, which is the defect this test is named for")

    src = inspect.getsource(conversation)
    prompt = "".join(node.value for node in ast.walk(ast.parse(src))
                     if isinstance(node, ast.Constant) and isinstance(node.value, str)
                     and "CANNOT DO" in node.value)
    assert prompt, "the rule about not sending people after what the platform cannot do is gone"
    # EVERY OPTION IT OFFERS IS ONE OF OURS. The two that are actions are named as verbs; the
    # third — a person reading the diff — is the one option that needs no capability at all.
    assert "`review`" in prompt, "the capability exists and the guidance still hides it"
    assert "a person reading the diff" in prompt, (
        "it names no option a person can take without spending")
    assert "paid model pass" in prompt, (
        "it offers a re-review without saying it costs — which is how a capability becomes a tax")


# ── the pass reviews what it produced (#155) ────────────────────────────────────────────────────
#
# #153 taught a verdict to declare itself out of date, which stopped the platform asserting
# something it could not support — and left the person at the merge gate with NO reading of the
# code in hand, and no way to ask for one. On the pilot the tech-lead then correctly recommended a
# re-review that does not exist as an action anywhere. The stale marker is the fallback; a fresh
# verdict is the answer.

class _Review:
    decision, score, summary, findings = "approved", 88, "reads well now", ()


class _Passed:
    """What a repair pass hands back."""

    review = _Review()
    validations = ()
    added_suppressions = ()


def _job():
    from openfactory.runtime.temporal.workflow import JobWorkflow

    job = JobWorkflow.__new__(JobWorkflow)
    job._verdict = None
    return job


def test_a_repair_pass_that_reviewed_REPLACES_the_old_verdict():
    job = _job()
    job._verdict = {"decision": "rejected", "score": 58,
                    "findings": [{"severity": "high", "description": "not reachable"}],
                    "stale": "a pass rewrote it"}

    assert job._reviewed_again(_Passed()) is True
    assert job._verdict["decision"] == "approved"
    assert job._verdict["score"] == 88
    assert "stale" not in job._verdict, (
        "the fresh verdict still carries the out-of-date marker — it IS the code in hand now")
    assert not job._verdict["findings"], "the old findings survived into a reading that is not theirs"


def test_a_pass_that_could_NOT_review_leaves_the_honest_marker():
    """`review_mode: off`, or a deployment with no reviewer. Falling through to silence would put
    back the confident stale verdict this whole pair of cards exists to remove."""
    class _NoReview:
        review = None

    job = _job()
    job._verdict = {"decision": "rejected", "stale": "a pass rewrote it"}

    assert job._reviewed_again(_NoReview()) is False
    assert job._verdict["stale"] == "a pass rewrote it"
    assert job._verdict["decision"] == "rejected"


def test_the_fresh_verdict_says_the_GATES_were_not_re_run():
    """A repair pass runs one agent and pushes; it does not re-run the sandbox gates. `gates: []`
    renders as nothing, and nothing is how a reader concludes there were none — on the one clause
    a merge decision leans on hardest."""
    from openfactory.techlead.conversation import verdict_line

    job = _job()
    job._reviewed_again(_Passed())

    assert job._verdict["gates_note"]
    line = verdict_line({"verdict": job._verdict})
    assert "gates: not re-run" in line, line
    assert "PASSED" not in line


def test_BOTH_repair_paths_publish_what_they_reviewed():
    """The reachability half, and it is the one that mattered: the previous card's marker was set
    in two places and this must be too, or one of the paths keeps the dead end."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    for method, activity in ((JobWorkflow._ci_merge_loop, "repair_ci"),
                             (JobWorkflow._answer_merge_gate, "adjust_pr")):
        tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(method)))
        pushes = [n.lineno for n in ast.walk(tree)
                  if isinstance(n, ast.Name) and n.id == activity]
        fresh = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and n.attr == "_reviewed_again"]
        assert pushes, f"{method.__name__} no longer launches {activity}"
        assert fresh, f"{method.__name__} pushes a rewritten diff and never re-reads it"
        assert max(fresh) > min(pushes), (
            f"{method.__name__} publishes a verdict BEFORE the pass has produced one")


def test_the_MACHINE_reviews_the_diff_it_just_pushed():
    """And the half above it: the workflow can only publish what the pass hands back. `repair_ci`
    has the checkout, the sandbox and the diff in hand — asking for this anywhere else would mean
    a fresh clone, which is why the capability lives here rather than as a row somebody calls."""
    from openfactory.orchestrator import machine

    # Sliced from the module rather than from a class attribute, so the guard does not encode
    # which class holds it — the claim is about the pass, not about where it is bound.
    whole = inspect.getsource(machine)
    start = whole.index("    def repair_ci(")
    src = whole[start:whole.index("\n    def ", start + 10)]
    assert "self._commit(ws, ticket)" in src, "this is not the repair pass — the slice has drifted"

    assert "self.reviewer.review(" in src, (
        "the pass pushes a rewritten pull request and never reads it back")
    assert "review=review" in src, "the reading is taken and then dropped on the floor"
    assert 'review_mode != "off"' in src, "it reviews even where the deployment turned review off"
