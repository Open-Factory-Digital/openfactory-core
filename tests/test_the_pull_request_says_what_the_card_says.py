"""A pull request must not present a stale review as current (#187).

MEASURED ON THE PILOT, 2026-08-21. podbeam #119 was reviewed and rejected (score 58). An adjust
was sent, the agent repaired four of the findings, and the job returned to the merge gate. At that
moment the two surfaces a person can look at said different things about one pull request.

The panel's gate item — correct, and exactly what #181 built on:

    **Review out of date** — somebody with the panel token asked for a change and a pass rewrote
    the pull request, and nothing re-ran the reviewer — what it found was about the diff before
    that
    - **was:** high: InsufficientCreditError in the second track silently discards …

The pull request's own body — unchanged since the first review:

    ## Review — rejected (score 58)
    The core of the ticket is implemented well … Two acceptance criteria are not met …

No "was", no marker, no date. A person who opens the PR — which is where a reviewer naturally goes,
and the only surface a collaborator without the panel token has — reads a verdict about code that
no longer exists as if it were current. Every finding in it may already be fixed; four of them
were, by the very pass that invalidated the review.

This is #164 in a second surface: one question, answered in two places, one of them silently wrong.
The staleness was already computed. The pull request simply never asked.

THE TWIN IS THE HALF THAT KEEPS THE MARKER MEANING SOMETHING: a review that is still current must
not be marked, and a re-review (#181) must CLEAR the marker rather than add a second one.
"""

from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

import pytest
import test_walking_skeleton as spine

from openfactory.adapters.forge.base import ForgeAdapter
from openfactory.contracts import AgentRunResult, Finding, Manifest, ReviewResult
from openfactory.orchestrator.machine import _REVIEW_HEADING, _review_lines
from openfactory.review.verdict import headline
from openfactory.techlead.voice import NARRATION, say

repo = spine.repo

REJECTED = ReviewResult(
    decision="rejected", score=58, summary="Two acceptance criteria are not met.",
    findings=[Finding(severity="high", description="the second track discards the error",
                      file="src/tracks.py")])
APPROVED = ReviewResult(decision="approved", score=91, summary="the finding is answered",
                        findings=[])


def _body_with_review(review: ReviewResult = REJECTED) -> str:
    """A pull request body shaped exactly as this platform writes one — the review section
    composed by the WRITER, so a guard about the reader cannot pass against a hand-typed heading
    the writer would never produce."""
    return "\n".join([
        "Automated by OpenFactory for #9.", "", "Closes #9", "",
        "## Objective", "ship it", "",
        "## Validations", "- ✅ `test`: `true` (exit 0)", "",
        *_review_lines(review), "",
        "Touched components: api",
    ])


class _Writer:
    """A repair pass that actually rewrites the pull request.

    A DIFFERENT FILE EVERY PASS, and that is not decoration. Writing the same content twice makes
    the SECOND pass a no-op — nothing is pushed, nothing is re-dated — so a guard about what two
    passes do would measure one. That is exactly how the double-caveat mutation survived its first
    round: the second pass never reached the code the guard was about.
    """

    def __init__(self) -> None:
        self.passes = 0

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        return AgentRunResult(ok=True)

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        self.passes += 1
        (workspace.path / f"repair{self.passes}.py").write_text(f"FIXED = {self.passes}\n")
        return AgentRunResult(ok=True, summary="repaired it", cost_usd=0.02)


class _Idle:
    """A pass that ran and changed nothing (#179's case)."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        return AgentRunResult(ok=True)

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=True, summary="nothing to do", cost_usd=0.01)


class _Reviewer:
    def __init__(self, out: ReviewResult = APPROVED) -> None:
        self._out = out

    def review(self, *, sandbox, workspace, review_input):
        return self._out


def _pr_branch(repo: Path, name: str = "openfactory/9") -> None:
    spine._git(["checkout", "-b", name], repo)
    (repo / "work.py").write_text("x = 1\n")
    spine._git(["add", "-A"], repo)
    spine._git(["commit", "-m", "wip"], repo)
    spine._git(["push", "-u", "origin", name], repo)
    spine._git(["checkout", "main"], repo)
    spine._git(["branch", "-D", name], repo)


def _runner_with_body(repo: Path, tmp_path: Path, *, agent, reviewer=None,
                      body: str | None = None, language: str = ""):
    forge = spine.FakeForge()
    forge.opened = {"body": body if body is not None else _body_with_review()}
    tracker = spine.FakeTracker(spine._sizing_ticket_id("#9"))
    runner = spine._runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                           agent=agent, reviewer=reviewer, forge=forge)
    if language:
        runner.project = type("_P", (), {"language": language})()
    return runner, forge


CAVEAT = say(NARRATION, "pr.review.out-of-date", "en")
WAS = say(NARRATION, "pr.review.was", "en")


# ── the pull request catches up with the card ────────────────────────────────────────────────────

def test_a_pass_that_rewrote_the_diff_dates_the_review_on_the_PULL_REQUEST(
        repo: Path, tmp_path: Path):
    _pr_branch(repo)
    runner, forge = _runner_with_body(repo, tmp_path, agent=_Writer())

    runner.repair_ci("#9", "CI failed", pr_url="https://forge/pr/1")

    body = forge.opened["body"]
    assert CAVEAT in body, (
        "the pull request still opens with a verdict about code that no longer exists")
    section = body[body.index(_REVIEW_HEADING):]
    assert section.index(CAVEAT) < section.index("the second track discards the error"), (
        "the caveat is not the first thing a reader of that section meets")


def test_every_clause_under_the_caveat_is_stamped_as_past(repo: Path, tmp_path: Path):
    """#154's rule, on the second surface: a reader applies a warning to the clause it was
    standing next to, so the finding six lines down has to carry it too."""
    _pr_branch(repo)
    runner, forge = _runner_with_body(repo, tmp_path, agent=_Writer())

    runner.repair_ci("#9", "CI failed", pr_url="https://forge/pr/1")

    section = forge.opened["body"].split(_REVIEW_HEADING, 1)[1]
    clauses = [row for row in section.splitlines()[1:]
               if row.strip() and not row.lstrip().startswith(">")]
    unstamped = [c for c in clauses if WAS not in c]
    assert clauses, "there is nothing under the caveat — this guard is measuring nothing"
    assert not unstamped, f"these read as facts about the diff as it stands: {unstamped}"


def test_what_the_reviewer_SAID_is_dated_and_never_deleted(repo: Path, tmp_path: Path):
    """Identity is not rewritten. The score and the decision are what the reviewer concluded, and
    its reasoning is what tells a person where to look in the new diff."""
    _pr_branch(repo)
    runner, forge = _runner_with_body(repo, tmp_path, agent=_Writer())

    runner.repair_ci("#9", "CI failed", pr_url="https://forge/pr/1")

    body = forge.opened["body"]
    assert f"{_REVIEW_HEADING}rejected (score 58)" in body, "the verdict's identity was rewritten"
    assert "the second track discards the error" in body, "the finding was deleted, not dated"
    assert "## Objective" in body and "Touched components: api" in body, (
        "the amendment ate the rest of the description")


def test_a_second_pass_does_not_stack_a_second_caveat(repo: Path, tmp_path: Path):
    _pr_branch(repo)
    agent = _Writer()
    runner, forge = _runner_with_body(repo, tmp_path, agent=agent)

    runner.repair_ci("#9", "CI failed", pr_url="https://forge/pr/1")
    runner.repair_ci("#9", "CI failed again", pr_url="https://forge/pr/1")

    assert agent.passes == 2, "the second pass never ran — this guard is measuring one"

    assert forge.opened["body"].count(CAVEAT) == 1
    assert forge.opened["body"].count(f"{WAS}{WAS}") == 0, "the clauses were stamped twice"


# ── the twin: a reading that is current is never marked ──────────────────────────────────────────

def test_a_pass_that_re_reviewed_publishes_the_FRESH_verdict_unmarked(repo: Path, tmp_path: Path):
    """#155's pass reads what it wrote. What it produces is about the diff as it stands, so the
    section is REPLACED — a caveat over a current reading is the same lie in the other direction."""
    _pr_branch(repo)
    runner, forge = _runner_with_body(repo, tmp_path, agent=_Writer(), reviewer=_Reviewer())

    runner.repair_ci("#9", "CI failed", pr_url="https://forge/pr/1")

    body = forge.opened["body"]
    assert f"{_REVIEW_HEADING}approved (score 91)" in body
    assert CAVEAT not in body, "a fresh reading was published wearing an out-of-date marker"
    assert WAS not in body
    assert "the second track discards the error" not in body, (
        "the old finding survived into a reading that is not its own")


def test_a_pass_that_changed_nothing_leaves_the_pull_request_alone(repo: Path, tmp_path: Path):
    """#179's case on this surface: a pass that pushed nothing has invalidated nothing, and
    marking the review would take the finding off the one screen a collaborator can see."""
    _pr_branch(repo)
    original = _body_with_review()
    runner, forge = _runner_with_body(repo, tmp_path, agent=_Idle(), body=original)

    runner.repair_ci("#9", "CI failed", pr_url="https://forge/pr/1")

    assert forge.opened["body"] == original


def test_a_re_review_CLEARS_the_marker_rather_than_adding_to_it(repo: Path, tmp_path: Path):
    """The closing half of #181, on this surface. The operator asked for the pull request to be
    read again; what comes back is about the diff in hand, so the marker goes."""
    _pr_branch(repo)
    dated = _body_with_review()
    runner, forge = _runner_with_body(repo, tmp_path, agent=_Writer())
    runner.repair_ci("#9", "CI failed", pr_url="https://forge/pr/1")
    assert CAVEAT in forge.opened["body"], "the marker was never put up — nothing to clear"

    runner.reviewer = _Reviewer()
    runner.review_pr("#9", pr_url="https://forge/pr/1")

    body = forge.opened["body"]
    assert CAVEAT not in body, "the re-review left the out-of-date marker standing"
    assert f"{_REVIEW_HEADING}approved (score 91)" in body
    assert dated  # the original is unused beyond its shape; kept for the reader


# ── it says it in the project's language, in the panel's words ──────────────────────────────────

def test_the_caveat_is_written_in_the_projects_language(repo: Path, tmp_path: Path):
    _pr_branch(repo)
    runner, forge = _runner_with_body(repo, tmp_path, agent=_Writer(), language="pt-BR")

    runner.repair_ci("#9", "CI failed", pr_url="https://forge/pr/1")

    body = forge.opened["body"]
    assert say(NARRATION, "pr.review.out-of-date", "pt-BR") in body
    assert CAVEAT not in body
    assert say(NARRATION, "pr.review.was", "pt-BR") in body


def test_the_two_surfaces_use_the_SAME_words_for_the_same_fact():
    """#164's rule: one question answered in two places must not become two vocabularies. The
    panel composes its wording in `review.verdict`; this row is the other surface's, and a guard
    is the only thing that keeps them from drifting apart one edit at a time."""
    panel = headline({"decision": "rejected", "score": 58,
                      "stale": "a pass rewrote the pull request"})

    assert panel["word"] in NARRATION["pr.review.out-of-date"]["en"], (
        f"the panel says {panel['word']!r} and the pull request says something else")
    assert "was: " == NARRATION["pr.review.was"]["en"], (
        "the panel stamps 'was: ' and this surface stamps something else")
    for language in ("en", "pt-BR"):
        assert NARRATION["pr.review.out-of-date"][language]
        assert NARRATION["pr.review.was"][language]


def test_the_writer_and_the_reader_agree_on_where_the_section_starts():
    """The heading is one constant. Two spellings agree until one is edited, and then the
    amendment simply never lands — silently, on the surface nobody is watching."""
    src = inspect.getsource(_review_lines)

    assert "_REVIEW_HEADING" in src, "the writer spells the heading out again"
    assert re.search(r"row\.startswith\(_REVIEW_HEADING\)",
                     inspect.getsource(importlib.import_module(
                         "openfactory.orchestrator.machine")))


# ── the port, and both vendors ──────────────────────────────────────────────────────────────────

def test_the_neutral_contract_declares_both_halves():
    for row in ("pr_body", "set_pr_body"):
        assert hasattr(ForgeAdapter, row), f"the port cannot {row}"
    doc = inspect.getdoc(ForgeAdapter.pr_body) or ""
    assert "None" in doc and '""' in doc, (
        "the option type is the whole meaning of a read on this port and the contract omits it")


def test_every_registered_forge_can_read_AND_write_the_description():
    """WALKED FROM THE REGISTRY, like #171's: a fifth forge added without these rows must fail the
    suite rather than degrade into a pull request nobody re-dates."""
    from openfactory.adapters.forge.registry import FORGES

    missing = []
    for kind, builder in FORGES.items():
        found = re.search(r"from (openfactory\.adapters\.forge\.\w+) import (\w+)",
                          inspect.getsource(builder))
        assert found, f"cannot tell which adapter the {kind!r} row builds"
        cls = getattr(importlib.import_module(found.group(1)), found.group(2))
        for row in ("pr_body", "set_pr_body"):
            if not callable(getattr(cls, row, None)):
                missing.append(f"{kind}.{row}")

    assert not missing, f"these forges cannot re-date a review on the pull request: {missing}"


class _Gh:
    """Stands in for `gh`, which is how the GitHub adapter reads and writes everything."""

    def __init__(self, code: int = 0, out: str = "") -> None:
        self.code, self.out, self.calls = code, out, []

    def __call__(self, args):
        self.calls.append(args)
        return type("_P", (), {"returncode": self.code, "stdout": self.out, "stderr": "boom"})()


def _github(gh: _Gh):
    from openfactory.adapters.forge.github import GitHubForge

    forge = GitHubForge.__new__(GitHubForge)
    forge.repo = "o/app"
    forge._gh = gh
    return forge


@pytest.mark.parametrize("code,out,expected", [
    (0, "a body\n", "a body"),
    (0, "\n", ""),          # a description that is genuinely empty
    (1, "", None),          # could not look
])
def test_could_not_look_and_nothing_there_stay_different_answers(code, out, expected):
    assert _github(_Gh(code, out)).pr_body(pr="https://github.com/o/app/pull/7") == expected


def test_a_refused_write_is_reported_rather_than_assumed():
    """False, not an exception and not a shrug: the caller is annotating a fact somewhere else and
    must not fail the pass — but a caller told nothing would leave a body that reads as current."""
    assert _github(_Gh(1)).set_pr_body(pr="p", body="x") is False
    assert _github(_Gh(0)).set_pr_body(pr="p", body="x") is True


def test_a_body_that_could_not_be_read_is_never_overwritten(repo: Path, tmp_path: Path):
    """The most expensive failure available here: amending from a failed read would publish a
    description assembled out of nothing over whatever the pull request really says."""
    _pr_branch(repo)
    runner, forge = _runner_with_body(repo, tmp_path, agent=_Writer())
    forge.pr_body = lambda *, pr, repo="": None
    wrote = []
    forge.set_pr_body = lambda *, pr, body, repo="": wrote.append(body) or True

    runner.repair_ci("#9", "CI failed", pr_url="https://forge/pr/1")

    assert not wrote, "it published a body built from a read that failed"


# ── the second vendor, driven rather than declared ──────────────────────────────────────────────

def test_azure_devops_reads_and_writes_the_description():
    """DRIVEN, not merely present. `ForgeAdapter` is a Protocol with `...` bodies, so a method an
    adapter forgets to write does not fail — it inherits a silent `return None`, which here is
    "this pull request has no description" about every pull request on the vendor."""
    import test_the_ado_forge as ado

    pr = {"pullRequestId": 7, "status": "active", "repository": ado.FX_ADO_REPO,
          "description": "## Review — rejected (score 58)"}
    f = ado.forge({"GET git/pullrequests/7": pr,
                   "PATCH git/repositories/fx-ado/pullrequests/7": {}})

    assert f.pr_body(pr="7") == "## Review — rejected (score 58)"
    assert f.set_pr_body(pr="7", body="dated") is True
    assert f.fake.body_for("PATCH", "git/repositories/fx-ado/pullrequests/7") == {
        "description": "dated"}


def test_azure_devops_keeps_the_option_type_and_never_raises_at_the_caller():
    """A pull request opened with no description is EMPTY, not unreadable — this vendor simply
    omits the key. And a refused write reports False rather than taking down the pass that was
    doing the real work."""
    import test_the_ado_forge as ado

    bare = {"pullRequestId": 8, "status": "active", "repository": ado.FX_ADO_REPO}
    assert ado.forge({"GET git/pullrequests/8": bare}).pr_body(pr="8") == ""

    from openfactory.adapters.azure_devops import AzureDevOpsError

    blind = ado.forge({}, raises={"GET git/pullrequests/9": AzureDevOpsError("403")})
    assert blind.pr_body(pr="9") is None
    assert blind.set_pr_body(pr="9", body="x") is False


def test_azure_devops_truncates_to_its_own_ceiling_instead_of_losing_the_annotation():
    """The bound lives on the vendor that has it: Azure DevOps refuses a description over 4000
    characters outright, and losing the out-of-date marker because a body is long is the worse of
    the two outcomes. `truncated` says in the text that it stopped."""
    import test_the_ado_forge as ado

    pr = {"pullRequestId": 7, "status": "active", "repository": ado.FX_ADO_REPO,
          "description": "x"}
    f = ado.forge({"GET git/pullrequests/7": pr,
                   "PATCH git/repositories/fx-ado/pullrequests/7": {}})

    assert f.set_pr_body(pr="7", body="y" * 9000) is True
    sent = f.fake.body_for("PATCH", "git/repositories/fx-ado/pullrequests/7")["description"]
    assert len(sent) <= 4000, (
        "it cut to the limit and then appended a note ON TOP of it — which is the one shape that "
        "turns a long description into the 400 this bound exists to avoid")
    assert "cut" in sent, "it cut the body without saying it had cut anything"

# ── the vendor's own ceiling, on EVERY path that writes a description ────────────────────────────

def test_azure_caps_a_pull_request_description_on_the_create_path_too():
    """Azure DevOps refuses a description over 4000 characters outright — a 400, not a truncation.

    THIS SHIPPED CAPPED IN ONE OF THE TWO PLACES. `set_pr_body` (the UPDATE) cut correctly and
    `open_pr` (the CREATE) sent the body verbatim, so the vendor's rule — written down and
    enforced on the same class — was missing from the one path that runs on EVERY job before any
    other can. Found live on the first Azure DevOps ticket to reach the PR station: SPEC, PREP,
    CODE, TEST and REVIEW all green, then `400 Bad Request … must not be longer than 4000
    characters`, and a job that had done all of its work could not hand it in.

    Asserted through the ONE method both paths now call, because two call sites agreeing today is
    what agreeing looked like before."""
    from openfactory.adapters.forge.azure_devops import AzureReposForge

    fits = "x" * AzureReposForge._DESCRIPTION_MAX
    assert AzureReposForge._fit_description(fits) == fits, "a body at the ceiling must be untouched"

    over = "y" * (AzureReposForge._DESCRIPTION_MAX + 5000)
    cut = AzureReposForge._fit_description(over)
    assert len(cut) <= AzureReposForge._DESCRIPTION_MAX, (
        f"the cut body is {len(cut)} characters — this vendor answers 400, it does not truncate")
    assert cut.endswith(AzureReposForge._CUT_NOTE), (
        "a description that stops mid-sentence with no marker reads as one that ends there")


def test_neither_azure_description_path_writes_a_body_it_did_not_measure():
    """The guard above proves the METHOD. This one proves both callers reach it — which is the
    half that was broken, and the half a unit test of the helper would never have caught."""
    import ast
    import inspect
    import textwrap

    from openfactory.adapters.forge.azure_devops import AzureReposForge

    for name in ("open_pr", "set_pr_body"):
        # THE CODE, NOT THE PROSE. The first cut read `inspect.getsource` as text and passed
        # against a reverted `open_pr`, because the COMMENT beside the call still said
        # "see `_fit_description`" — a guard satisfied by the sentence explaining it.
        # `ast.unparse` drops comments and the docstring goes with body[0].
        fn = ast.parse(textwrap.dedent(inspect.getsource(getattr(AzureReposForge, name)))).body[0]
        body = fn.body[1:] if ast.get_docstring(fn) else fn.body
        code = "\n".join(ast.unparse(node) for node in body)
        assert "_fit_description" in code, (
            f"AzureReposForge.{name} writes a description without the vendor's ceiling — "
            "the create path shipped that way and every job died at the PR station")
