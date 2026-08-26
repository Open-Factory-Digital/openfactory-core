"""The adjust loop has a closing half: the reviewer can be asked to read it again (#181).

MEASURED ON THE PILOT, at the gate of podbeam #97. The review rejected the pull request with one
specific, correct critical finding. An `adjust` pass fixed exactly that finding. The gate re-opened
and said, honestly:

    gate word : Review out of date
    clause    : … a pass rewrote the pull request, and nothing re-ran the reviewer —
                what it found was …
       · was: critical: … the LLM prompt still carries the raw style card's promise

That sentence is true and it left the operator with no move. The change had been made to answer a
finding, and there was no way to ask whether it did. The tech-lead's own guidance said so out loud
— *"nothing here re-runs the reviewer on demand — that capability does not exist"* — which is the
right thing to say and is not a capability.

    review rejects  →  adjust fixes it  →  ???  →  merge

The remaining options were to merge on your own reading of the diff — the work an independent
review exists to remove — or to merge against a verdict about code that is gone.

WHAT THIS FILE PINS, and the last two are the ones that keep the capability from becoming a tax:

  · it reads and writes NOTHING — no agent, no `setup:`, no commit, no push;
  · the fresh verdict REPLACES the stale one and never sits beside it (#149's ambiguity);
  · it is never automatic: a person asks, once per ask, bounded;
  · it is never OFFERED where it cannot run — the platform's own rule about advice nobody can take
    binds its buttons too.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
from pathlib import Path

import pytest
import test_walking_skeleton as spine

from openfactory.contracts import (
    AgentRunResult,
    Finding,
    JobState,
    Manifest,
    ReviewResult,
)
from openfactory.runtime.temporal.io import JobParams
from openfactory.runtime.temporal.workflow import JobWorkflow

repo = spine.repo

REJECTED = {"decision": "rejected", "score": 42,
            "findings": [{"severity": "critical", "description": "the prompt still promises it"}],
            "stale": "somebody asked for a change and a pass rewrote the pull request"}


def _job(*, verdict: dict | None = None, passes: int = 0) -> JobWorkflow:
    job = JobWorkflow.__new__(JobWorkflow)
    job._verdict = verdict
    job._review_passes = passes
    return job


def _params(**kw) -> JobParams:
    return JobParams(project="podbeam", issue="97", **kw)


# ── the verb exists, everywhere a person can reach it ────────────────────────────────────────────

def test_the_gate_takes_a_fourth_answer():
    """The signal is the narrow end of every surface: panel button, API route, typed sentence.
    A verb the signal drops is a verb that works everywhere except where it acts."""
    job = _job()
    job._merge_wait = {"pr_url": "https://forge/pr/1", "auto": False}
    job._gate = None

    import asyncio
    asyncio.run(job.human_merge_gate("review", "", "operator-1"))

    assert job._gate == {"answer": "review", "instruction": "", "by": "operator-1"}


def test_the_client_side_refuses_a_verb_the_workflow_would_drop():
    """`answer_merge_gate` validates before it signals, and a signal is fire-and-forget: a verb it
    lets through and the workflow ignores is an answer that reports success and does nothing."""
    from openfactory.runtime.temporal import view

    src = inspect.getsource(view.answer_merge_gate)
    accepted = next(node for node in ast.walk(ast.parse(inspect.cleandoc("\n" + src)))
                    if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.NotIn))
    words = {c.value for c in accepted.comparators[0].elts}

    assert words == {"merge", "adjust", "discard", "review"}, (
        f"the client and the signal disagree about what can be answered: {sorted(words)}")


def test_the_action_layer_carries_the_verb_with_its_price_named():
    """A row in the catalogue is what makes it reachable from the panel, the API and the
    tech-lead's own proposals — and `choose_when` is what stops it being offered as a refresh
    button on a verdict that is already current."""
    import openfactory.actions as actions

    spec = actions.CATALOG["review"]

    assert spec.required == ("project", "issue")
    assert "instruction" not in (spec.optional or ()), (
        "a re-review takes no words — it reads what is there")
    assert "model pass" in spec.choose_when, "it does not say the ask costs money"
    assert "current" in spec.choose_when, "nothing tells it not to spend one on a fresh verdict"


@pytest.mark.parametrize("said", [
    "review it again", "re-review it", "you can re-review it", "re-run the review",
    "revisa de novo", "pode revisar de novo", "nova revisão", "roda a revisão de novo",
])
def test_a_person_can_ask_in_words_in_either_language(said: str):
    from openfactory.actions.floor_intents import match_floor_intent

    hit = match_floor_intent(said)

    assert hit and hit[0] == "review", f"{said!r} did not read as an ask for a re-review: {hit}"


@pytest.mark.parametrize("said", [
    "the review rejected it",
    "a revisão está vencida",
    "the review is out of date, what do you think?",
    "posso pedir uma nova revisão?",
    "não revisa de novo",
    "a nova revisão encontrou dois problemas",
])
def test_talking_ABOUT_a_review_never_buys_one(said: str):
    """The twin, and the one that decides whether this verb is safe: these channels are full of
    sentences about reviews — this platform prints `review: OUT OF DATE` itself — and a loose
    matcher reads every one of them as an order to spend a model pass."""
    from openfactory.actions.floor_intents import match_floor_intent

    hit = match_floor_intent(said)

    assert not (hit and hit[0] == "review"), f"{said!r} was read as an order: {hit}"


# ── it is offered only where it is real ──────────────────────────────────────────────────────────

def test_a_job_with_a_verdict_and_room_can_be_asked():
    assert _job(verdict=REJECTED)._re_review_refusal(_params()) == ""


@pytest.mark.parametrize("job,params,says", [
    (_job(verdict=REJECTED), _params(review=False), "review turned off"),
    (_job(verdict=None), _params(), "nothing has reviewed"),
    (_job(verdict={"gates": [{"name": "test", "passed": True}]}), _params(), "nothing has reviewed"),
    (_job(verdict=REJECTED, passes=JobWorkflow._REVIEW_MAX), _params(), "already spent"),
])
def test_it_is_refused_where_it_cannot_run(job, params, says):
    """Each of these is a way to offer a button that would be refused — which is the platform's own
    rule about advice nobody can take, applied to its own chrome."""
    refusal = job._re_review_refusal(params)

    assert says in refusal, f"expected a refusal naming {says!r}, got {refusal!r}"


def test_the_refusal_and_the_button_are_the_SAME_test():
    """Not two tests that agree today. The gate publishes `can_review` and the handler refuses in
    words; computed twice they drift, and #164 is the card about what that costs."""
    gate = inspect.getsource(JobWorkflow._ci_merge_loop)
    handler = inspect.getsource(JobWorkflow._answer_merge_gate)

    for name, src in (("the gate's flag", gate), ("the handler's refusal", handler)):
        calls = [n for n in ast.walk(ast.parse(inspect.cleandoc("\n" + src)))
                 if isinstance(n, ast.Attribute) and n.attr == "_re_review_refusal"]
        assert calls, f"{name} decides for itself whether a re-review is possible"


# ── what the pass does, and what it must never do ────────────────────────────────────────────────

class _Reviewer:
    def __init__(self, decision="approved", score=91):
        self.calls = 0
        self._out = ReviewResult(
            decision=decision, score=score, summary="the finding is answered",
            findings=[Finding(severity="low", description="a nit", file="app.py")])

    def review(self, *, sandbox, workspace, review_input):
        self.calls += 1
        self.diff = review_input.diff
        return self._out


class _NeverAgent:
    """The pass must not run one. Every method here is a tripwire."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        raise AssertionError("a re-review ran the executor")

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        raise AssertionError("a re-review ran a repair pass")


def _open_pr(repo: Path, name: str = "openfactory/9") -> str:
    spine._git(["checkout", "-b", name], repo)
    (repo / "feature.py").write_text("VALUE = 1\n")
    spine._git(["add", "-A"], repo)
    spine._git(["commit", "-m", "the work"], repo)
    spine._git(["push", "-u", "origin", name], repo)
    spine._git(["checkout", "main"], repo)
    spine._git(["branch", "-D", name], repo)
    return name


def _head_of(repo: Path, branch: str) -> str:
    spine._git(["fetch", "origin"], repo)
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", f"origin/{branch}"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_the_pass_publishes_a_verdict_about_the_diff_in_hand(repo: Path, tmp_path: Path):
    branch = _open_pr(repo)
    reviewer = _Reviewer()
    tracker = spine.FakeTracker(spine._sizing_ticket_id("#9"))
    runner = spine._runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                           reviewer=reviewer, agent=_NeverAgent())

    result = runner.review_pr("#9", pr_url="https://forge/pr/1")

    assert reviewer.calls == 1
    assert result.review is not None and result.review.decision == "approved"
    assert result.state is JobState.PR_OPEN
    assert "feature.py" in reviewer.diff, (
        "the reviewer was handed something other than this pull request's own diff")
    assert _head_of(repo, branch) == _head_of(repo, branch), "sanity"


def test_the_pass_leaves_the_pull_request_exactly_where_it_found_it(repo: Path, tmp_path: Path):
    """The sentence that separates this verb from its two neighbours. `adjust` and the CI repair
    both push; this one may not, or "ask for a reading" becomes "spend a pass and hope"."""
    branch = _open_pr(repo)
    before = _head_of(repo, branch)
    tracker = spine.FakeTracker(spine._sizing_ticket_id("#9"))
    runner = spine._runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                           reviewer=_Reviewer(), agent=_NeverAgent())

    result = runner.review_pr("#9", pr_url="https://forge/pr/1")

    assert result.code_changed is False
    assert _head_of(repo, branch) == before, "a read pushed to the branch it was reading"


def test_no_setup_is_run_for_a_read(repo: Path, tmp_path: Path):
    """A review reads a diff; it does not need the project to build. Running `setup:` would make
    an honest reading cost what a repair costs, on a gate somebody is standing at."""
    _open_pr(repo)
    tracker = spine.FakeTracker(spine._sizing_ticket_id("#9"))
    manifest = Manifest(validate={"test": "true"}, setup=["exit 7  # setup must not run"])
    runner = spine._runner(repo, tracker, manifest, tmp_path,
                           reviewer=_Reviewer(), agent=_NeverAgent())

    result = runner.review_pr("#9", pr_url="https://forge/pr/1")

    assert result.review is not None, "the pass died in a setup step it had no reason to run"


def test_a_deployment_with_no_reviewer_says_so_instead_of_pretending(repo: Path, tmp_path: Path):
    """`can_review` exists so nobody gets here. If they do — a misconfigured box, a manifest with
    review off — the answer is a sentence, never a silent return to the same stale reading."""
    _open_pr(repo)
    tracker = spine.FakeTracker(spine._sizing_ticket_id("#9"))
    runner = spine._runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                           reviewer=None, agent=_NeverAgent())

    result = runner.review_pr("#9", pr_url="https://forge/pr/1")

    assert result.review is None
    assert "no reviewer" in (result.note or ""), result.note


def test_the_box_dispatches_a_READ_and_never_a_repair():
    """The reachability half, and the expensive direction: the review variant reaching the repair
    branch would run an agent and push on a pull request whose owner asked only to have it read."""
    from openfactory.runtime import boxed_job

    src = inspect.getsource(boxed_job.main)
    tree = ast.parse(inspect.cleandoc("\n" + src))
    read = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and n.value == "OPENFACTORY_REVIEW_PASS"]
    repair = [n.lineno for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and n.value == "OPENFACTORY_CI_REPAIR"]

    assert read, "the box cannot be asked for a review pass at all"
    assert repair, "this guard is measuring nothing — the repair branch has moved"
    assert min(read) < min(repair), (
        "the review variant is tested after the repair one, so a box carrying both flags runs an "
        "agent on a pull request nobody asked to have rewritten")


# ── the fresh verdict replaces the stale one, and the ask is never automatic ─────────────────────

def test_the_fresh_verdict_replaces_the_stale_one():
    """Never beside it: two verdicts about two diffs on one screen is the ambiguity #149 exists to
    kill, and the person reading is the one deciding whether the change lands."""
    class _Read:
        review = ReviewResult(decision="approved", score=91, summary="answered", findings=[])
        validations = ()
        added_suppressions = ()

    job = _job(verdict=dict(REJECTED))

    assert job._reviewed_again(_Read()) is True
    assert "stale" not in job._verdict
    assert job._verdict["decision"] == "approved"
    assert not job._verdict["findings"], "the old findings survived into a reading that is not theirs"


def _review_branch() -> ast.If:
    """The `answer == "review"` branch of the gate handler, and nothing else.

    SCOPED, BECAUSE THE METHOD'S OTHER BRANCHES ANSWER THE SAME QUESTIONS. Counted across the
    whole handler, `_reviewed_again` is satisfied by the ADJUST branch's call — so a re-review
    that took a reading and dropped it on the floor passed the first version of this guard, which
    is the survivor that rewrote it.
    """
    tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(JobWorkflow._answer_merge_gate)))
    return next(node for node in ast.walk(tree)
                if isinstance(node, ast.If)
                and any(isinstance(c, ast.Constant) and c.value == "review"
                        for c in ast.walk(node.test)))


def test_the_handler_asks_for_the_read_and_then_publishes_it():
    """Reachability, in order: the pass is launched, and the verdict it brings back is published
    AFTER it. Published before, the gate would re-open with the reading it already had."""
    branch = ast.Module(body=_review_branch().body, type_ignores=[])
    reads = [n.lineno for n in ast.walk(branch) if isinstance(n, ast.Name) and n.id == "review_pr"]
    publishes = [n.lineno for n in ast.walk(branch)
                 if isinstance(n, ast.Attribute) and n.attr == "_reviewed_again"]

    assert reads, "the gate cannot ask for a re-review — the verb reaches no activity"
    assert publishes, "the reading is taken and dropped on the floor"
    assert min(publishes) > min(reads), (
        "the verdict is published before the pass that produces it has run")


def test_the_re_review_branch_never_reaches_a_repair():
    """The two neighbours share a handler and a gate dict, and only one of them may push. A
    re-review wired into `adjust_pr` would rewrite a pull request whose owner asked to have it
    read — and every behaviour test in this file would still pass, because the fake would still
    return a verdict."""
    branch = ast.Module(body=_review_branch().body, type_ignores=[])
    names = {n.id for n in ast.walk(branch) if isinstance(n, ast.Name)}

    assert "review_pr" in names
    assert "adjust_pr" not in names and "repair_ci" not in names, (
        "the read branch can start a pass that writes")


def test_the_ask_is_bounded_and_the_bound_is_not_the_repair_cap():
    """It writes nothing, so it cannot loop the work — and it is a paid model pass, so a button
    that can be pressed for ever is a bill with no ceiling. The two caps are separate numbers
    because they bound different things."""
    assert JobWorkflow._REVIEW_MAX >= JobWorkflow._ADJUST_MAX
    job = _job(verdict=REJECTED, passes=JobWorkflow._REVIEW_MAX - 1)

    assert job._re_review_refusal(_params()) == "", "the last one within the cap was refused"
    job._review_passes += 1
    assert "already spent" in job._re_review_refusal(_params())


def test_nothing_asks_for_a_re_review_on_its_own():
    """The card is explicit: a repair that changes a comment does not need a new verdict, and
    paying for one after every pass is how a useful capability becomes a tax. The only thing that
    starts one is an answer at the gate."""
    src = inspect.getsource(JobWorkflow)
    tree = ast.parse(inspect.cleandoc("\n" + src))
    launches = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "review_pr"]

    assert len(launches) == 1, (
        f"{len(launches)} places start a re-review — it must be exactly the human answer")


# ── the panel offers it only where the server said it exists ─────────────────────────────────────

PANEL = Path("openfactory/api/panel.html").read_text()


def test_the_panel_asks_the_server_which_answers_exist():
    """#164's rule on the surface this card touches: the inbox renders the options the API
    published rather than a list kept by hand — the hand-kept copy had already lost two states."""
    # SCOPED TO THE FUNCTION THAT BUILDS THE BUTTONS. `it.kind=="merge"` also appears in the
    # sentence-builder above it, and a guard that reads the first match is a guard about prose.
    block = PANEL[PANEL.index("function inboxOptions("):]
    block = block[:block.index('if(it.kind=="approval")')]

    assert "it.options" in block, "the inbox still keeps its own list of what a gate accepts"
    assert 'data-k="${esc(o.key)}"' in block, "the buttons are not built from the published keys"
    # THE NEGATIVE TWIN. A hand-kept list can come back as a fallback that is always taken, and
    # the tell is a literal answer key in the markup: every key here must be interpolated from
    # what the server published.
    for verb in ("merge", "adjust", "discard", "review"):
        assert f'data-k="{verb}"' not in block, (
            f"the inbox hard-codes the {verb} button again — the list the server publishes is "
            f"then decoration, and the next answer this platform learns will not appear here")


def test_the_project_card_offers_a_re_review_only_when_the_job_says_so():
    assert 'a.can_review?' in PANEL, (
        "the project card offers a re-review on its own authority, or not at all")
    assert 'data-k="review"' in PANEL, "there is no way to press it"
    assert "costs a model pass" in PANEL, "the button does not say the ask is paid for"


def test_the_API_publishes_the_option_only_when_the_job_says_it_is_real():
    """The server's half of the same rule. The panel renders what `/api/inbox` publishes, so an
    option added unconditionally here reaches every surface at once — including the deployments
    where a re-review would be refused the moment somebody pressed it."""
    from openfactory.api import app

    tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(app.inbox)))
    guarded = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and any(isinstance(c, ast.Constant) and c.value == "can_review" for c in ast.walk(node.test))
        and any(isinstance(c, ast.Attribute) and c.attr == "insert" for c in ast.walk(ast.Module(
            body=node.body, type_ignores=[])))
    ]

    assert guarded, (
        "the re-review option is published without asking the job whether it can be answered")


def test_the_launcher_asks_the_box_to_READ_and_nothing_else():
    """The variant and its flag travel together. A review pass launched with the repair flag runs
    an agent and pushes — the one outcome this verb promises cannot happen."""
    from openfactory.runtime.temporal import activities

    tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(activities._run_review_pass)))
    env = next(node for node in ast.walk(tree)
               if isinstance(node, ast.Dict)
               and any(isinstance(k, ast.Constant) and str(k.value).startswith("OPENFACTORY_")
                       for k in node.keys))
    keys = {k.value for k in env.keys if isinstance(k, ast.Constant)}

    assert keys == {"OPENFACTORY_PR", "OPENFACTORY_REVIEW_PASS"}, (
        f"the read pass is launched with {sorted(keys)} — anything that puts it on the repair "
        f"path spends an agent on a pull request nobody asked to have rewritten")
