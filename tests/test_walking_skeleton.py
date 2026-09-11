"""End-to-end proof of the walking-skeleton spine (ADR-0001 slice 1).

Uses the real WorktreeSandbox against a temp git repo, with fake tracker/forge/agent
so the deterministic orchestrator is exercised without GitHub/claude/Docker.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.adapters.agent.base import AgentContext
from openfactory.adapters.sandbox import WorktreeSandbox
from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.adapters.tracker.parse import parse_ticket_body
from openfactory.contracts import (
    AcceptanceCriterion,
    AgentRunResult,
    Component,
    Finding,
    JobState,
    Manifest,
    ReviewResult,
    Ticket,
)
from openfactory.observability import InMemoryEventSink, NullEventSink
from openfactory.orchestrator import JobRunner
from openfactory.orchestrator.machine import _BOT_WORKING_LABEL


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    # a bare "origin" so publish_branch (git push origin) is exercised for real
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True
    )

    r = tmp_path / "repo"
    r.mkdir()
    _git(["init", "-b", "main"], r)
    _git(["config", "user.email", "t@t.dev"], r)
    _git(["config", "user.name", "t"], r)
    _git(["remote", "add", "origin", str(origin)], r)
    (r / "README.md").write_text("# app\n")
    _git(["add", "-A"], r)
    _git(["commit", "-m", "init"], r)
    _git(["push", "-u", "origin", "main"], r)
    return r


class FakeTracker:
    def __init__(self, ticket: Ticket, assignees: list[str] | None = None) -> None:
        self.ticket = ticket
        self.states: list[JobState] = []
        self.comments: list[str] = []
        self._assignees = assignees or []
        self.assign_history: list[list[str]] = []
        self.labels: set[str] = set()

    def get_ticket(self, ref: str) -> Ticket:
        return self.ticket

    def set_state(self, ref: str, state: JobState, reason: str | None = None, *,
                  needs_person: bool | None = None) -> None:
        self.states.append(state)

    def comment(self, ref: str, body: str) -> None:
        self.comments.append(body)

    def assignees(self, ref: str) -> list[str]:
        return self._assignees

    def set_assignees(self, ref: str, logins: list[str]) -> None:
        self._assignees = list(logins)
        self.assign_history.append(list(logins))

    def add_label(self, ref: str, label: str) -> None:
        self.labels.add(label)

    def remove_label(self, ref: str, label: str) -> None:
        self.labels.discard(label)


class FakeForge:
    def __init__(self, merge_fails: int = 0, arm_only: bool = False) -> None:
        self.opened: dict | None = None
        self.reviews: list[dict] = []
        self.requested: list[str] = []
        self.merged = False
        self._merge_fails = merge_fails  # raise "not mergeable" this many times first
        self._arm_only = arm_only  # merge_pr succeeds but the PR stays unmerged (--auto pending CI)
        self.merge_calls = 0
        self.auto_merge_disabled = False

    def push_remote(self) -> str | None:
        return None  # tests push to the bare origin

    def open_pr(self, *, head: str, base: str, title: str, body: str) -> str:
        self.opened = {"head": head, "base": base, "title": title, "body": body}
        return "https://forge/pr/1"

    def review_pr(self, *, pr: str, event: str, body: str) -> None:
        self.reviews.append({"event": event, "body": body})

    def request_reviewers(self, *, pr: str, reviewers: list[str]) -> None:
        self.requested = reviewers

    def merge_pr(self, *, pr: str) -> None:
        self.merge_calls += 1
        if self.merge_calls <= self._merge_fails:
            raise RuntimeError("not mergeable: the merge commit cannot be cleanly created")
        if not self._arm_only:  # arm_only = --auto armed but not merged yet (CI pending)
            self.merged = True

    def pr_merged(self, *, pr: str) -> bool:
        return self.merged

    def pr_status(self, *, pr: str) -> str:
        return "merged" if self.merged else "open"

    def disable_auto_merge(self, *, pr: str) -> None:
        self.auto_merge_disabled = True

    # #187 — the pull request's own description is a surface the platform writes AND reads back.
    # A fake that cannot answer them makes every pass that re-dates a review fail here rather
    # than on the vendor, which is the point of keeping the fake honest to the contract.
    def pr_body(self, *, pr: str, repo: str = "") -> str | None:
        return (self.opened or {}).get("body")

    def set_pr_body(self, *, pr: str, body: str, repo: str = "") -> bool:
        self.opened = {**(self.opened or {}), "body": body}
        return True


class FakeAgent:
    """Simulates an executor: writes a file into the workspace."""

    def execute(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext
    ) -> AgentRunResult:
        (workspace.path / "feature.py").write_text("VALUE = 42\n")
        return AgentRunResult(
            ok=True, summary="added feature.py", cost_usd=0.01,
            actions=["Edit: feature.py"],
        )

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=True)


class FakeReviewer:
    def review(self, *, sandbox, workspace, review_input) -> ReviewResult:
        return ReviewResult(
            decision="approved_with_findings",
            score=88,
            findings=[Finding(severity="low", description="minor nit")],
            summary="looks correct against the criteria",
        )


class FakeRepairAgent:
    """Fails the first validation (no fixed.txt), then repairs by creating it."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        (workspace.path / "feature.py").write_text("x\n")
        return AgentRunResult(ok=True, cost_usd=0.01, actions=["Edit: feature.py"])

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        (workspace.path / "fixed.txt").write_text("fixed\n")
        return AgentRunResult(ok=True, cost_usd=0.02, actions=["Write: fixed.txt"])


def _runner(
    repo: Path, tracker: FakeTracker, manifest: Manifest, tmp_path: Path,
    reviewer=None, events=None, agent=None, forge=None, sandbox=None, bot=None,
) -> JobRunner:
    # `bot` defaults to None — i.e. `BotIdentity()` with `login=None` — which for a long time was
    # every test AND the only live deployment, because its `.env` sets no `OPENFACTORY_BOT_LOGIN`. The
    # claim branch below was therefore dead in both places at once, and the first deployment to
    # set the variable crashed on its first ticket. See the three tests at the end of this file.
    kwargs = {"bot": bot} if bot is not None else {}
    return JobRunner(
        tracker=tracker,
        forge=forge or FakeForge(),
        agent=agent or FakeAgent(),
        sandbox=sandbox or WorktreeSandbox(root=tmp_path / "wt"),
        manifest=manifest,
        repo_path=repo,
        reviewer=reviewer,
        events=events or NullEventSink(),
        **kwargs,
    )


def test_full_spine_opens_pr(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#1", title="add feature", objective="add a feature", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")],
    )
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true", "security": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path)

    result = runner.run("#1")

    assert result.state is JobState.PR_OPEN
    assert result.pr_url == "https://forge/pr/1"
    assert result.all_passed
    assert result.total_cost_usd == 0.01
    assert runner.forge.opened["base"] == "main"
    # the state machine walked the expected states
    assert JobState.SPEC_VALIDATION in tracker.states
    assert JobState.IMPLEMENTING in tracker.states
    assert JobState.VALIDATING in tracker.states
    assert tracker.states[-1] is JobState.PR_OPEN


def test_reviewer_verdict_is_attached_and_state_walked(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#4", title="add feature", objective="add a feature", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")],
    )
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true", "security": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path, reviewer=FakeReviewer())

    result = runner.run("#4")

    assert result.state is JobState.PR_OPEN
    assert result.review is not None
    assert result.review.score == 88
    assert JobState.REVIEWING in tracker.states
    assert "Review — approved_with_findings" in runner.forge.opened["body"]


def test_journal_captures_states_actions_and_validations(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#7", title="add feature", objective="add a feature", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")],
    )
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true", "security": "true"})
    sink = InMemoryEventSink()
    runner = _runner(repo, tracker, manifest, tmp_path, events=sink)

    runner.run("#7")

    kinds = {e.kind for e in sink.events}
    assert {"state", "agent_action", "validation", "pr"} <= kinds
    # the agent's action is journaled — "exactly what happened inside the agent"
    assert any(e.kind == "agent_action" and "feature.py" in e.message for e in sink.events)
    assert any(e.kind == "validation" and "PASS" in e.message for e in sink.events)
    assert any(e.kind == "state" and e.message == "pr_open" for e in sink.events)


def test_human_path_posts_review_requests_reviewers_and_does_not_merge(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#8", title="add feature", objective="add a feature", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")],
    )
    tracker = FakeTracker(ticket)
    manifest = Manifest(  # default merge_policy=human
        validate={"test": "true", "security": "true"}, reviewers=["alice", "bob"]
    )
    runner = _runner(repo, tracker, manifest, tmp_path, reviewer=FakeReviewer())

    result = runner.run("#8")

    assert result.state is JobState.PR_OPEN
    assert len(runner.forge.reviews) == 1  # reviewer verdict posted as a PR review
    assert runner.forge.reviews[0]["event"] == "comment"  # approved_with_findings -> comment
    assert runner.forge.requested == ["alice", "bob"]  # human reviewers requested
    assert runner.forge.merged is False  # never auto-merges by default
    assert any("ready for review" in c for c in tracker.comments)


def test_auto_policy_merges_when_safe(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#9", title="add feature", objective="add a feature", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")],
    )
    tracker = FakeTracker(ticket)
    manifest = Manifest(merge_policy="auto", validate={"test": "true", "security": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path, reviewer=FakeReviewer())

    result = runner.run("#9")

    assert result.state is JobState.MERGED
    assert runner.forge.merged is True
    assert tracker.states[-1] is JobState.MERGED


# --- suppression-repair loop (ADR-0011): the sandbox resolves pragmas, not the human ---

class _PragmaRemovableAgent:
    """Executor adds a coverage pragma; the suppression-repair pass REMOVES it."""
    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        (workspace.path / "feature.py").write_text("VALUE = 42  # pragma: no cover\n")
        return AgentRunResult(ok=True, summary="added (pragma'd)", cost_usd=0.01, actions=["Edit"])

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        assert "pragma" in failure_log.lower() or "suppress" in failure_log.lower()
        (workspace.path / "feature.py").write_text("VALUE = 42\n")  # made testable → pragma gone
        return AgentRunResult(ok=True, summary="removed the pragma", cost_usd=0.02,
                              actions=["Edit"])


class _PragmaKeepAgent:
    """Executor adds a legit wiring pragma; the suppression-repair pass KEEPS it."""
    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        (workspace.path / "feature.py").write_text(
            "VALUE = 42  # pragma: no cover - thin wiring\n")
        return AgentRunResult(ok=True, summary="added wiring", cost_usd=0.01, actions=["Edit"])

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=True, summary="kept legit wiring pragma", cost_usd=0.02,
                              actions=[])


class _NoqaKeepAgent:
    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        (workspace.path / "feature.py").write_text("import os  # noqa\nVALUE = 42\n")
        return AgentRunResult(ok=True, summary="added (noqa)", cost_usd=0.01, actions=["Edit"])

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=True, summary="kept the noqa", cost_usd=0.02, actions=[])


def _supp_ticket(n: str) -> Ticket:
    return Ticket(id=n, title="add value", objective="add VALUE", repo="o/app",
                  acceptance_criteria=[AcceptanceCriterion(text="VALUE exists")])


def test_suppression_repair_removes_pragma_then_auto_merges(repo: Path, tmp_path: Path):
    # the executor pragma'd a line; the suppression-repair pass makes it testable and removes
    # the pragma → clean diff → auto-merge, no human needed (this is the #69 pain, gone).
    tracker = FakeTracker(_supp_ticket("#50"))
    manifest = Manifest(merge_policy="auto", validate={"test": "true", "security": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path, agent=_PragmaRemovableAgent())
    result = runner.run("#50")
    assert result.added_suppressions == []       # resolved in the sandbox
    assert result.state is JobState.MERGED and runner.forge.merged is True


def test_suppression_repair_keeps_legit_pragma_reviewer_vets(repo: Path, tmp_path: Path):
    # the pragma is genuine wiring (can't be removed); the independent reviewer vets it
    # (approved) → auto-merge. No human merge by hand.
    tracker = FakeTracker(_supp_ticket("#51"))
    manifest = Manifest(merge_policy="auto", validate={"test": "true", "security": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path,
                     agent=_PragmaKeepAgent(), reviewer=FakeReviewer())
    result = runner.run("#51")
    assert "pragma: no cover" in result.added_suppressions   # survived (legit)
    assert result.state is JobState.MERGED and runner.forge.merged is True


def test_hard_suppression_still_goes_to_human(repo: Path, tmp_path: Path):
    # noqa silences a real lint error — it stays human-gated even when the reviewer approves.
    tracker = FakeTracker(_supp_ticket("#52"))
    manifest = Manifest(merge_policy="auto", validate={"test": "true", "security": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path,
                     agent=_NoqaKeepAgent(), reviewer=FakeReviewer())
    result = runner.run("#52")
    assert "noqa" in result.added_suppressions
    assert result.state is JobState.PR_OPEN and runner.forge.merged is False


class FakeStuckAgent:
    """Simulates an agent that hits an impediment it can't resolve."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        return AgentRunResult(ok=False, summary="blocked: needs an API key I don't have")

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=False)


class FakePausedAgent:
    def __init__(self, reason: str, retry_at=None) -> None:
        self.reason, self.retry_at = reason, retry_at

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        return AgentRunResult(ok=False, pause_reason=self.reason, retry_at=self.retry_at)

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=False, pause_reason=self.reason)


def test_usage_limit_pauses_not_fails(repo: Path, tmp_path: Path):
    ticket = Ticket(id="#20", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                     agent=FakePausedAgent("rate_limit", retry_at="15:00"))

    result = runner.run("#20")

    assert result.state is JobState.PAUSED  # not FAILED / ON_HOLD
    assert runner.forge.opened is None
    assert any("usage limit" in c and "15:00" in c for c in tracker.comments)
    # B: the reset the agent reported round-trips on the result so the workflow can pace resume
    assert result.retry_at == "15:00"
    # agnostic: the pause message must NOT name a specific vendor (Claude/Codex/…)
    assert not any("Claude" in c for c in tracker.comments)


def test_credential_is_surfaced_as_a_panel_event(repo: Path, tmp_path: Path):
    # A (partner-requested visibility): when the agent reports which credential it used, the
    # runner emits a note event so the panel can show "credential 1/2" and prove rotation.
    class CredAgent(FakeAgent):
        def execute(self, *, sandbox, workspace, context):
            r = super().execute(sandbox=sandbox, workspace=workspace, context=context)
            r.credential = {"index": 2, "total": 3, "id": "b", "rotated": True}
            return r

    ticket = Ticket(id="#22", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    sink = InMemoryEventSink()
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                     agent=CredAgent(), events=sink)

    runner.run("#22")

    cred = [e for e in sink.events if e.kind == "note" and "credential 2/3" in e.message]
    assert cred, "expected a credential note event on the panel feed"
    assert "rotated" in cred[0].message  # failover is visible


def test_agent_auth_failure_holds_with_fix_message(repo: Path, tmp_path: Path):
    # auth is human-fixable only — ON_HOLD, never PAUSED, so the durable resume loop
    # doesn't burn ~48 futile relaunches against a dead token (R9).
    ticket = Ticket(id="#21", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    runner = _runner(repo, tmp_path=tmp_path, tracker=tracker,
                     manifest=Manifest(validate={"test": "true"}),
                     agent=FakePausedAgent("auth"))

    result = runner.run("#21")

    assert result.state is JobState.ON_HOLD
    assert any("authenticate" in c for c in tracker.comments)


class PartialThenPauseAgent:
    """Writes a partial file, then pauses (rate limit) mid-execute, reporting a resume handle —
    exactly the C2 scenario: the work-so-far must be preserved and the handle round-tripped."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        (workspace.path / "partial.py").write_text("HALF_DONE = 1\n")
        return AgentRunResult(ok=False, pause_reason="rate_limit", retry_at="16:00",
                              resume_handle="sess-abc")

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=True)


def test_pause_preserves_partial_work_and_carries_resume_handle(repo: Path, tmp_path: Path):
    # C2: a rate-limit pause must PUSH the partial branch (so a fresh container can restore it)
    # and carry the agent's opaque resume_handle on the result (so the workflow resumes, not
    # restarts). Uses the real WorktreeSandbox + bare origin, so the push happens for real.
    ticket = Ticket(id="#40", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    sink = InMemoryEventSink()
    runner = _runner(repo, tmp_path=tmp_path, tracker=tracker,
                     manifest=Manifest(validate={"test": "true"}),
                     agent=PartialThenPauseAgent(), events=sink)

    result = runner.run("#40")

    assert result.state is JobState.PAUSED
    assert result.resume_handle == "sess-abc"  # round-tripped for the durable resume
    assert result.retry_at == "16:00"
    # the partial branch was actually pushed to origin (so a fresh container can check it out)
    origin = tmp_path / "origin.git"
    branches = subprocess.run(["git", "branch", "--list", "openfactory/40"], cwd=origin,
                              capture_output=True, text=True).stdout
    assert "openfactory/40" in branches
    assert any("partial work pushed" in e.message for e in sink.events)


def test_resume_restores_branch_and_hands_handle_to_agent(repo: Path, tmp_path: Path):
    # C2 resume: given a resume_handle, the run must check out the EXISTING (pushed) branch and
    # hand the handle to the agent via the context — proof the resume continues, not restarts.
    seen = {}

    class ResumeSpyAgent:
        def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
            seen["handle"] = context.resume_handle
            # the partial from the paused attempt must already be present (restored from branch)
            seen["partial_restored"] = (workspace.path / "partial.py").exists()
            (workspace.path / "feature.py").write_text("done\n")
            return AgentRunResult(ok=True, summary="continued", cost_usd=0.01)

        def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
            return AgentRunResult(ok=True)

    # first, create + push the branch a prior pause would have left behind
    _git(["checkout", "-b", "openfactory/41"], repo)
    (repo / "partial.py").write_text("HALF = 1\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "wip"], repo)
    _git(["push", "-u", "origin", "openfactory/41"], repo)
    _git(["checkout", "main"], repo)

    ticket = Ticket(id="#41", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    runner = _runner(repo, tmp_path=tmp_path, tracker=tracker,
                     manifest=Manifest(validate={"test": "true"}), agent=ResumeSpyAgent())

    result = runner.run("#41", resume_handle="sess-abc")

    assert seen["handle"] == "sess-abc"  # the agent received the opaque token
    assert seen["partial_restored"] is True  # the paused attempt's code was restored, not lost
    assert result.state is JobState.PR_OPEN  # the resumed run completed to a PR


class PartialThenStopAgent:
    """Writes real work then STOPS unfinished (turn cap / error) — NOT a rate-limit pause.
    ADR-0013 D1: this must preserve the work and make the hold resumable."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        (workspace.path / "halfway.py").write_text("DONE = 0.8\n")
        return AgentRunResult(ok=False, summary="reached the 120-turn safety cap",
                              resume_handle='{"v": 1, "phase": "execute", "session": "s9", '
                                            '"state_key": ""}')

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=True)


def test_agent_stop_preserves_work_and_hold_is_resumable(repo: Path, tmp_path: Path):
    # #37 regression: the executor stopped at the turn cap and the ephemeral tree DISCARDED
    # $14 of work. Now: branch pushed + the hold carries the handle (resumable hold).
    ticket = Ticket(id="#50", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    sink = InMemoryEventSink()
    runner = _runner(repo, tmp_path=tmp_path, tracker=tracker,
                     manifest=Manifest(validate={"test": "true"}, recovery_max_attempts=0),
                     agent=PartialThenStopAgent(), events=sink)

    result = runner.run("#50")

    assert result.state is JobState.ON_HOLD
    assert result.resume_handle  # resumable hold — Resume continues, not redoes
    origin = tmp_path / "origin.git"
    branches = subprocess.run(["git", "branch", "--list", "openfactory/50"], cwd=origin,
                              capture_output=True, text=True).stdout
    assert "openfactory/50" in branches  # the partial work is on the remote
    assert any("partial work pushed" in e.message for e in sink.events)


def test_agent_stop_with_no_work_holds_without_handle(repo: Path, tmp_path: Path):
    # A stop that wrote NOTHING must stay a plain hold (fresh restart) — a bogus handle would
    # make Resume "continue" nothing and skip a clean replan.
    class NoWorkStopAgent:
        def execute(self, *, sandbox, workspace, context):
            return AgentRunResult(ok=False, summary="stopped before writing anything")

        def repair(self, *, sandbox, workspace, context, failure_log):
            return AgentRunResult(ok=True)

    ticket = Ticket(id="#51", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    runner = _runner(repo, tmp_path=tmp_path, tracker=tracker,
                     manifest=Manifest(validate={"test": "true"}, recovery_max_attempts=0),
                     agent=NoWorkStopAgent())

    result = runner.run("#51")

    assert result.state is JobState.ON_HOLD
    assert not result.resume_handle  # plain hold → fresh restart semantics


class StopThenRecoverAgent:
    """Executor stops at the turn cap; the recovery ladder's rung 1 (continue_execute)
    finishes the job — the dark-factory path: no human involved (ADR-0013 D5)."""

    def __init__(self):
        self.calls: list[str] = []

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        self.calls.append("execute")
        (workspace.path / "halfway.py").write_text("DONE = 0.8\n")
        return AgentRunResult(ok=False, summary="reached the turn cap", num_turns=120,
                              resume_handle='{"v": 1, "phase": "execute", "session": "s1", '
                                            '"state_key": ""}')

    def continue_execute(self, *, sandbox, workspace, context, handle, brief) -> AgentRunResult:
        self.calls.append(f"continue:{handle[:20]}")
        (workspace.path / "done.py").write_text("DONE = 1\n")
        return AgentRunResult(ok=True, summary="finished the remaining 20%", num_turns=30)

    def recover(self, *, sandbox, workspace, context, brief) -> AgentRunResult:
        self.calls.append("recover")
        return AgentRunResult(ok=True, summary="recovered")

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=True)


def test_recovery_ladder_continues_and_lands_the_pr(repo: Path, tmp_path: Path):
    ticket = Ticket(id="#60", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    agent = StopThenRecoverAgent()
    runner = _runner(repo, tmp_path=tmp_path, tracker=tracker,
                     manifest=Manifest(validate={"test": "true"}), agent=agent)

    result = runner.run("#60")

    assert result.state is JobState.PR_OPEN  # recovered autonomously, no human
    assert agent.calls[0] == "execute"
    assert agent.calls[1].startswith("continue:")  # rung 1: the same session continued
    assert result.spent_turns == 150  # 120 + 30 — the effort was accounted


def test_effort_budget_breach_preserves_and_holds_with_decision(repo: Path, tmp_path: Path):
    # ADR-0013 D4: the TICKET-wide budget governs. Prior attempts spent 390; this execute
    # spends 120 more → over 400 → NO recovery is attempted, work preserved, and the hold's
    # message is DECISION-shaped (split or raise budget), never "go read the code".
    ticket = Ticket(id="#61", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    agent = StopThenRecoverAgent()
    runner = _runner(repo, tmp_path=tmp_path, tracker=tracker,
                     manifest=Manifest(validate={"test": "true"}), agent=agent)

    result = runner.run("#61", spent_turns=390)

    assert result.state is JobState.ON_HOLD
    assert "effort budget exhausted" in (result.note or "")
    assert "split" in (result.note or "")  # decision-shaped
    assert result.resume_handle  # the partial is preserved → resumable
    assert result.spent_turns == 510  # 390 carried + 120 this attempt
    assert agent.calls == ["execute"]  # no recovery rungs ran — budget said stop


def test_recovery_disabled_reproduces_the_plain_hold(repo: Path, tmp_path: Path):
    ticket = Ticket(id="#62", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    agent = StopThenRecoverAgent()
    runner = _runner(repo, tmp_path=tmp_path, tracker=tracker,
                     manifest=Manifest(validate={"test": "true"}, recovery_max_attempts=0),
                     agent=agent)

    result = runner.run("#62")

    assert result.state is JobState.ON_HOLD
    assert agent.calls == ["execute"]  # ladder off → straight to the (resumable) hold
    assert result.resume_handle


def test_resume_with_missing_branch_degrades_to_fresh_run(repo: Path, tmp_path: Path):
    # Audit HIGH: a resume whose preserved branch is GONE (deleted by a human/cleanup) must
    # degrade to a fresh run off base — prepare() falling back — never crash the job into a
    # park. (The old prepare raised "worktree add failed" on the missing origin ref.)
    ticket = Ticket(id="#42", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    runner = _runner(repo, tmp_path=tmp_path, tracker=tracker,
                     manifest=Manifest(validate={"test": "true"}), agent=FakeAgent())

    # NO branch openfactory/42 was ever pushed — the handle is stale
    result = runner.run("#42", resume_handle="sess-stale")

    assert result.state is JobState.PR_OPEN  # fresh run completed; no crash


def test_resume_skips_the_plan_gate(repo: Path, tmp_path: Path):
    # Audit MED: the sizing gate already passed on the FIRST run; re-applying it on a resume
    # lets a nondeterministic fresh "SPLIT" verdict discard a half-done, resumable job.
    class SplitPlannerAgent(FakeAgent):
        def plan(self, *, sandbox, workspace, context):
            return AgentRunResult(ok=True, summary="SPLIT NEEDED: this looks too big now")

    ticket = Ticket(id="#43", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    runner = _runner(repo, tmp_path=tmp_path, tracker=tracker,
                     manifest=Manifest(validate={"test": "true"}, planner_stage=True),
                     agent=SplitPlannerAgent())

    fresh = runner.run("#43")
    assert fresh.state is JobState.NEEDS_REFINEMENT  # first run: the gate applies

    tracker2 = FakeTracker(Ticket(id="#43", title="x", objective="x", repo="o/app",
                                  acceptance_criteria=[AcceptanceCriterion(text="c")]))
    runner2 = _runner(repo, tmp_path=tmp_path, tracker=tracker2,
                      manifest=Manifest(validate={"test": "true"}, planner_stage=True),
                      agent=SplitPlannerAgent())
    resumed = runner2.run("#43", resume_handle="sess-x")
    assert resumed.state is JobState.PR_OPEN  # resume: gate skipped, the work continues


def test_impediment_holds_and_returns_to_owner(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#12", title="x", objective="x", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="c")],
    )
    tracker = FakeTracker(ticket, assignees=["alice"])  # alice is the OWNER
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                     agent=FakeStuckAgent())

    result = runner.run("#12")

    assert result.state is JobState.ON_HOLD  # impediment → hold, not blocked
    assert runner.forge.opened is None  # never opened a PR
    assert any("@alice" in c and "on hold" in c for c in tracker.comments)  # returned to owner


def test_impediment_routes_to_creator_when_no_assignee_and_clears_working_label(
    repo: Path, tmp_path: Path,
):
    # Lights-out: no human assignee (the bot is a GitHub App, not a user). On pickup the ticket
    # gets the "🤖 working" label; an impediment routes back to the CREATOR and drops the label.
    ticket = Ticket(id="#81", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")], author="carol")
    tracker = FakeTracker(ticket)  # NO assignees
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                     agent=FakeStuckAgent())

    result = runner.run("#81")

    assert result.state is JobState.ON_HOLD
    assert any("@carol" in c for c in tracker.comments)  # routed to the creator, not silence
    assert _BOT_WORKING_LABEL not in tracker.labels  # working label cleared on park


def test_pickup_makes_bot_the_assignee(repo: Path, tmp_path: Path):
    from openfactory.contracts.bot import BotIdentity

    ticket = Ticket(
        id="#13", title="add feature", objective="add a feature", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")],
    )
    tracker = FakeTracker(ticket)  # unassigned
    manifest = Manifest(validate={"test": "true", "security": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path)
    runner.bot = BotIdentity(login="openfactory-bot")

    result = runner.run("#13")

    assert ["openfactory-bot"] in tracker.assign_history  # bot became the assignee on pickup
    assert result.state is JobState.PR_OPEN


def test_impediment_restores_the_previous_owner(repo: Path, tmp_path: Path):
    from openfactory.contracts.bot import BotIdentity

    ticket = Ticket(
        id="#14", title="x", objective="x", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="c")],
    )
    tracker = FakeTracker(ticket, assignees=["alice"])  # alice owns it
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                     agent=FakeStuckAgent())
    runner.bot = BotIdentity(login="openfactory-bot")

    result = runner.run("#14")

    assert result.state is JobState.ON_HOLD
    assert tracker.assign_history[0] == ["openfactory-bot"]  # took it
    assert tracker._assignees == ["alice"]  # returned to the owner
    assert any("@alice" in c for c in tracker.comments)


def test_repair_loop_fixes_failing_validation_then_opens_pr(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#10", title="add feature", objective="add a feature", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="works")],
    )
    tracker = FakeTracker(ticket)
    # `test` passes only once fixed.txt exists — the repair creates it.
    manifest = Manifest(
        validate={"test": "test -f fixed.txt", "security": "true"}, repair_max_attempts=2
    )
    runner = _runner(repo, tracker, manifest, tmp_path, agent=FakeRepairAgent())

    result = runner.run("#10")

    assert result.state is JobState.PR_OPEN
    assert result.repair_attempts == 1
    assert result.all_passed
    assert result.total_cost_usd == 0.03  # execute 0.01 + one repair 0.02
    assert JobState.REPAIRING in tracker.states


def test_repair_gives_up_after_max_attempts(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#11", title="x", objective="x", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="c")],
    )
    tracker = FakeTracker(ticket)
    # `false` never passes; repair (creating fixed.txt) can't fix it -> give up.
    manifest = Manifest(validate={"test": "false", "security": "true"}, repair_max_attempts=2)
    runner = _runner(repo, tracker, manifest, tmp_path, agent=FakeRepairAgent())

    result = runner.run("#11")

    assert result.state is JobState.ON_HOLD  # couldn't fix → returned to owner
    assert result.repair_attempts == 2
    assert runner.forge.opened is None


def test_failing_validation_does_not_open_pr(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#2", title="x", objective="x", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="c")],
    )
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "false", "security": "true"})  # `false` exits 1
    runner = _runner(repo, tracker, manifest, tmp_path)

    result = runner.run("#2")

    assert result.state is JobState.ON_HOLD  # unfixable validation → held for the owner
    assert result.pr_url is None
    assert runner.forge.opened is None


def test_spec_validation_sends_bad_ticket_to_refinement(repo: Path, tmp_path: Path):
    ticket = Ticket(id="#3", title="x", objective="x", repo="o/app")  # no acceptance criteria
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true", "security": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path)

    result = runner.run("#3")

    assert result.state is JobState.NEEDS_REFINEMENT
    assert "acceptance criteria" in (result.note or "")
    assert tracker.states[-1] is JobState.NEEDS_REFINEMENT


def test_ticket_parser():
    body = """---
depends_on: ["#10"]
base_branch: develop
---
## Objective
Do the thing.

## Acceptance criteria
- it works
- it is tested

## Out of scope
- unrelated cleanup
"""
    t = parse_ticket_body(id="#5", title="T", body=body, repo="o/app")
    assert t.objective == "Do the thing."
    assert [c.text for c in t.acceptance_criteria] == ["it works", "it is tested"]
    assert t.out_of_scope == ["unrelated cleanup"]
    assert t.depends_on == ["#10"]
    assert t.base_branch == "develop"


# --- Task-sizing gate + cost ceiling (ADR-0002) ---
class TwoStageAgent:
    """A plan→execute agent whose plan text and costs are set per test, so the sizing
    gate and cost ceiling can be exercised deterministically."""

    def __init__(self, plan: str, *, plan_cost: float = 0.0, exec_cost: float = 0.0) -> None:
        self._plan, self._plan_cost, self._exec_cost = plan, plan_cost, exec_cost
        self.executed = False

    def plan(self, *, sandbox, workspace, context) -> AgentRunResult:
        return AgentRunResult(ok=True, summary=self._plan, cost_usd=self._plan_cost,
                              actions=["Read: app.py"])

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        self.executed = True
        (workspace.path / "feature.py").write_text("VALUE = 1\n")
        return AgentRunResult(ok=True, summary="done", cost_usd=self._exec_cost,
                              actions=["Edit: feature.py"])

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=True)


def _sizing_ticket() -> Ticket:
    return Ticket(
        id="#40", title="feature", objective="add a feature", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")],
    )


def test_plan_gate_ignores_file_count(repo: Path, tmp_path: Path):
    # ADR-0013 (owner decision): file COUNT is NOT a sizing criterion. A plan that touches many
    # files but is one cohesive change (no SPLIT verdict) must NOT be gated — it runs.
    ticket = _sizing_ticket()
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true"}, max_plan_files=8, max_plan_steps=12)
    agent = TwoStageAgent("## Estimate\n- files: 20\n- steps: 6\n", exec_cost=0.02)
    runner = _runner(repo, tracker, manifest, tmp_path, agent=agent)

    result = runner.run("#40")

    assert agent.executed  # 20 files but cohesive → NOT gated on count
    assert result.state is JobState.PR_OPEN


def test_plan_gate_refines_on_split_verdict(repo: Path, tmp_path: Path):
    ticket = _sizing_ticket()
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true"}, planner_stage=True)  # verdict still honoured
    agent = TwoStageAgent("SPLIT NEEDED: spans backend + widget + migration\n- a\n- b\n")
    runner = _runner(repo, tracker, manifest, tmp_path, agent=agent)

    result = runner.run("#40")

    assert result.state is JobState.NEEDS_REFINEMENT
    assert not agent.executed
    assert "too large" in result.note


def test_plan_within_budget_proceeds_to_executor(repo: Path, tmp_path: Path):
    ticket = _sizing_ticket()
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true"}, max_plan_files=8, max_plan_steps=12)
    agent = TwoStageAgent("## Estimate\n- files: 3\n- steps: 5\n", exec_cost=0.02)
    runner = _runner(repo, tracker, manifest, tmp_path, agent=agent)

    result = runner.run("#40")

    assert agent.executed
    assert result.state is JobState.PR_OPEN


# --- D-6's post-diff scope-explosion catch (F-03, #28) ---
#
# `max_touched_components`/`max_diff_lines` sat on the manifest since before ADR-0013's
# transitional plan-gate rewrite, commented "abort to refinement past this" — and nothing ever
# read them. These prove the catch is real, END TO END: a real git repo, a real diff, the
# executor's OWN branch that never spent money on repair or review it should not have.

class _TwoComponentAgent:
    """Writes into two different component directories — the shape a component-count cap must
    catch: a ticket that quietly spread across more of the codebase than one outcome should."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        (workspace.path / "services" / "api").mkdir(parents=True, exist_ok=True)
        (workspace.path / "services" / "worker").mkdir(parents=True, exist_ok=True)
        (workspace.path / "services" / "api" / "routes.py").write_text("ROUTES = 1\n")
        (workspace.path / "services" / "worker" / "queue.py").write_text("QUEUE = 1\n")
        return AgentRunResult(
            ok=True, summary="touched two components", cost_usd=0.01,
            actions=["Edit: services/api/routes.py", "Edit: services/worker/queue.py"],
        )

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        raise AssertionError("repair ran on a diff that only needed refinement, not a fix")


class _CountingReviewer:
    """A reviewer that records whether it was ever asked — the cost proof. The scope-explosion
    catch's whole point is to hold BEFORE review spends anything on a ticket that already needs a
    human's judgment about size, not a verdict on what it built."""

    def __init__(self) -> None:
        self.calls = 0

    def review(self, *, sandbox, workspace, review_input) -> ReviewResult:
        self.calls += 1
        return ReviewResult(decision="approved", score=100, findings=[], summary="ok")


def _component_ticket() -> Ticket:
    return Ticket(
        id="#41", title="feature", objective="add a feature", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")],
    )


#: What a gate in this file may run. `true` is in `coreutils` and is a shell builtin besides —
#: there is no machine that resolves it differently.
_HOST_INDEPENDENT = {"true", "false"}


def _two_component_manifest(**over) -> Manifest:
    """The two-`stack: python` manifest the scope caps below act on — with every gate named, so
    that none of them is a tool this machine may or may not have.

    THE PRESET IS THE TRAP, AND IT COST WEEKS OF BEING CALLED AN INTERMITTENT FLAKE. A component
    declaring `stack: python` inherits `openfactory/presets/python.yaml` — `ruff check .`,
    `bandit -r . -ll -q`, `mypy .` — and the walking skeleton runs its gates for real, in a
    WorktreeSandbox on the HOST. Those commands therefore resolve against the PATH of whoever
    launched pytest: present under `source .venv/bin/activate`, absent under `.venv/bin/python -m
    pytest`, where `/bin/sh` answers 127. A non-zero gate is a FAILED gate, so the run went into
    `agent.repair` — which the two guards below assert never happens. Same commit, two launchers,
    two results, and the failure log said `ruff: not found` in a traceback nobody read past the
    assertion message.

    Naming the roles here is what fixes it: `applicable_validations` resolves preset → repo-wide →
    per-component, so a role placed repo-wide beats the same role in a touched component's preset.
    These tests are about the caps they are named for, and a gate they never meant to run must not
    decide their outcome.
    """
    fields = {
        "validate": {"test": "true", "lint": "true", "security": "true", "type": "true"},
        "components": {
            "api": Component(path="services/api", stack="python"),
            "worker": Component(path="services/worker", stack="python"),
        },
    }
    fields.update(over)
    return Manifest(**fields)


def test_the_gates_these_guards_run_are_not_this_machine_s_tools():
    """The property, pinned where it can be checked instead of remembered.

    A guard that asserts a fact about the machine running it is not a guard, and this file had two
    for weeks. The check resolves the gates exactly as the runner does and requires each command
    to be one that cannot be missing — so re-introducing a host tool fails HERE, naming the cause,
    rather than three hundred lines below as a repair that should not have run.
    """
    from openfactory.orchestrator.validation import applicable_validations, as_gate

    resolved = applicable_validations(["api", "worker"], _two_component_manifest())

    assert {"lint", "security", "type", "test"} <= set(resolved), (
        "a preset role stopped resolving, so this check no longer sees what actually runs")
    for role, gate in resolved.items():
        assert as_gate(gate).command in _HOST_INDEPENDENT, (
            f"the `{role}` gate runs `{as_gate(gate).command}` — a tool that must be installed on "
            f"whatever machine runs this suite. When it is missing the shell answers 127, the "
            f"gate reads as failed, and the run goes to repair: these tests then pass or fail "
            f"with the launcher instead of with the code")


def test_touching_more_components_than_the_manifest_allows_refines_not_repairs(
    repo: Path, tmp_path: Path,
):
    tracker = FakeTracker(_component_ticket())
    manifest = _two_component_manifest(max_touched_components=1)
    reviewer = _CountingReviewer()
    runner = _runner(repo, tracker, manifest, tmp_path, agent=_TwoComponentAgent(),
                     reviewer=reviewer)

    result = runner.run("#41")

    assert result.state is JobState.NEEDS_REFINEMENT
    assert "2 components" in (result.note or "")
    assert reviewer.calls == 0, "the diff was reviewed before the scope catch had a chance to run"
    assert not runner.forge.opened, "a diff refused for scope must never reach a PR"
    assert tracker.states[-1] is JobState.NEEDS_REFINEMENT


class _BigDiffAgent:
    """One component, no rename, no rippling change — just a function nobody split. The line-count
    cap exists because the component-count cap cannot see this shape at all."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        body = "\n".join(f"x{n} = {n}" for n in range(120))
        (workspace.path / "feature.py").write_text(body + "\n")
        return AgentRunResult(ok=True, summary="one big file", cost_usd=0.01,
                              actions=["Edit: feature.py"])

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        raise AssertionError("repair ran on a diff that only needed refinement, not a fix")


def test_a_diff_past_the_line_cap_refines_even_in_one_component(repo: Path, tmp_path: Path):
    tracker = FakeTracker(_component_ticket())
    manifest = Manifest(validate={"test": "true"}, max_diff_lines=50)
    reviewer = _CountingReviewer()
    runner = _runner(repo, tracker, manifest, tmp_path, agent=_BigDiffAgent(), reviewer=reviewer)

    result = runner.run("#41")

    assert result.state is JobState.NEEDS_REFINEMENT
    assert "lines" in (result.note or "")
    assert reviewer.calls == 0


def test_an_ordinary_ticket_under_both_caps_is_never_refused(repo: Path, tmp_path: Path):
    """The positive twin. A guard that can only refuse has never been proven to also let a normal
    ticket through — the cap must not fire on the common case just because it exists."""
    tracker = FakeTracker(_component_ticket())
    manifest = _two_component_manifest(max_touched_components=5, max_diff_lines=5_000)
    runner = _runner(repo, tracker, manifest, tmp_path, agent=_TwoComponentAgent())

    result = runner.run("#41")

    assert result.state is JobState.PR_OPEN


def test_cost_ceiling_holds_the_job(repo: Path, tmp_path: Path):
    ticket = _sizing_ticket()
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true"}, max_cost_usd=0.50)
    agent = TwoStageAgent("## Estimate\n- files: 1\n- steps: 1\n", plan_cost=0.1, exec_cost=0.9)
    runner = _runner(repo, tracker, manifest, tmp_path, agent=agent)

    result = runner.run("#40")  # plan+exec = 1.0 > 0.50

    assert result.state is JobState.ON_HOLD
    assert "cost ceiling" in result.note
    assert runner.forge.opened is None  # never reached the PR


# --- Merge on the current base: proactive rebase + re-validate; never crash (ADR-0002) ---
class _RebasedSandbox(WorktreeSandbox):
    """Reports that the base moved and the branch was rebased onto it."""

    def rebase_onto_base(self, *, workspace, base, remote_url=None) -> str:
        return "rebased"


class _ConflictSandbox(WorktreeSandbox):
    """Reports an unresolvable textual conflict against the latest base."""

    def rebase_onto_base(self, *, workspace, base, remote_url=None) -> str:
        return "conflict"


def _sizing_ticket_id(tid: str) -> Ticket:
    return Ticket(
        id=tid, title="add feature", objective="add a feature", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")],
    )


def test_auto_merge_up_to_date_merges(repo: Path, tmp_path: Path):
    # base hasn't moved → rebase is a no-op ("up_to_date") → merge straight through.
    tracker = FakeTracker(_sizing_ticket_id("#30"))
    manifest = Manifest(merge_policy="auto", validate={"test": "true", "security": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path)

    result = runner.run("#30")

    assert result.state is JobState.MERGED and runner.forge.merged


def test_auto_merge_revalidates_when_base_moved(repo: Path, tmp_path: Path):
    # base advanced during the run → rebase + re-validate + re-push, then merge (no human).
    tracker = FakeTracker(_sizing_ticket_id("#32"))
    manifest = Manifest(merge_policy="auto", validate={"test": "true", "security": "true"})
    sandbox = _RebasedSandbox(root=tmp_path / "wt")
    runner = _runner(repo, tracker, manifest, tmp_path, sandbox=sandbox)

    result = runner.run("#32")

    assert result.state is JobState.MERGED and runner.forge.merged
    # the pipeline re-validated after the rebase (VALIDATING revisited before MERGED)
    assert tracker.states.count(JobState.VALIDATING) >= 2


def test_auto_merge_holds_on_conflict(repo: Path, tmp_path: Path):
    # a real textual conflict against base → hold for a human, never crash, PR preserved.
    tracker = FakeTracker(_sizing_ticket_id("#31"))
    manifest = Manifest(merge_policy="auto", validate={"test": "true", "security": "true"})
    sandbox = _ConflictSandbox(root=tmp_path / "wt")
    runner = _runner(repo, tracker, manifest, tmp_path, sandbox=sandbox)

    result = runner.run("#31")  # must not raise

    assert result.state is JobState.ON_HOLD
    assert "conflicts with main" in result.note
    assert not runner.forge.merged
    assert runner.forge.opened is not None  # PR stays open for the human


def test_auto_merge_holds_when_merge_fails(repo: Path, tmp_path: Path):
    # up-to-date, but the forge rejects the merge → hold, never crash.
    tracker = FakeTracker(_sizing_ticket_id("#33"))
    manifest = Manifest(merge_policy="auto", validate={"test": "true", "security": "true"})
    forge = FakeForge(merge_fails=99)
    runner = _runner(repo, tracker, manifest, tmp_path, forge=forge)

    result = runner.run("#33")  # must not raise

    assert result.state is JobState.ON_HOLD
    assert "could not be merged" in result.note
    assert forge.opened is not None  # the PR stays open for the human


# --- CI-aware auto-merge + CI-repair (ADR-0004) ---
def test_auto_merge_armed_hands_off_to_workflow(repo: Path, tmp_path: Path):
    # required CI pending → --auto ARMED but not merged → PR_OPEN + auto_merge=True so the
    # durable workflow owns the CI-watch/repair/merge loop (does not falsely claim MERGED).
    tracker = FakeTracker(_sizing_ticket_id("#34"))
    manifest = Manifest(merge_policy="auto", validate={"test": "true", "security": "true"})
    forge = FakeForge(arm_only=True)
    runner = _runner(repo, tracker, manifest, tmp_path, forge=forge)

    result = runner.run("#34")

    assert result.state is JobState.PR_OPEN
    assert result.auto_merge is True
    assert not forge.merged  # armed, not actually merged


class _FixAgent:
    """Repairs by writing a fix file into the (checked-out existing) branch."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        return AgentRunResult(ok=True)

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        assert "CI" in failure_log  # the CI logs are threaded in as the repair input
        (workspace.path / "ci_fix.py").write_text("FIXED = True\n")
        return AgentRunResult(ok=True, summary="fixed the CI", cost_usd=0.02,
                              actions=["Edit: ci_fix.py"])


def test_repair_ci_fixes_the_open_branch_and_repushes(repo: Path, tmp_path: Path):
    # an open PR branch openfactory/9 already pushed to origin
    _git(["checkout", "-b", "openfactory/9"], repo)
    (repo / "broken.py").write_text("x\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "wip"], repo)
    _git(["push", "-u", "origin", "openfactory/9"], repo)
    _git(["checkout", "main"], repo)
    _git(["branch", "-D", "openfactory/9"], repo)  # simulate a fresh clone (no local branch)

    tracker = FakeTracker(_sizing_ticket_id("#9"))
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                     agent=_FixAgent())

    result = runner.repair_ci("#9", "CI failed: test_x broke")

    assert result.state is JobState.PR_OPEN and result.auto_merge is True
    # the fix landed on the pushed branch (origin/openfactory/9), on top of the PR's own commit
    _git(["fetch", "origin"], repo)
    exists = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", "origin/openfactory/9:ci_fix.py"],
        capture_output=True,
    ).returncode
    assert exists == 0  # ci_fix.py is on the re-pushed branch
    # and it kept the PR's original commit (worked on the existing branch, not a fresh one)
    kept = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", "origin/openfactory/9:broken.py"],
        capture_output=True,
    ).returncode
    assert kept == 0


class _SuppressingRepairAgent:
    """A CI-repair that makes CI green the WRONG way — by silencing a gate (# noqa)."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        return AgentRunResult(ok=True)

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        (workspace.path / "ci_fix.py").write_text("import os  # noqa\nFIXED = True\n")
        return AgentRunResult(ok=True, summary="silenced the lint gate", cost_usd=0.02,
                              actions=["Edit: ci_fix.py"])


def test_repair_ci_that_silences_a_gate_disarms_auto_merge_and_holds(repo: Path, tmp_path: Path):
    # engineering.md #12 on the CI-repair path: a fix that ADDS a gate suppression must NOT
    # ride --auto onto main — it disarms auto-merge and hands the PR to a human.
    _git(["checkout", "-b", "openfactory/8"], repo)
    (repo / "broken.py").write_text("x\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "wip"], repo)
    _git(["push", "-u", "origin", "openfactory/8"], repo)
    _git(["checkout", "main"], repo)
    _git(["branch", "-D", "openfactory/8"], repo)

    tracker = FakeTracker(_sizing_ticket_id("#8"))
    forge = FakeForge()
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                     agent=_SuppressingRepairAgent(), forge=forge)

    result = runner.repair_ci("#8", "CI failed: lint broke", pr_url="https://forge/pr/1")

    assert result.state is JobState.ON_HOLD
    assert result.auto_merge is not True  # the armed auto-merge must NOT stay claimed
    assert forge.auto_merge_disabled is True  # and it was actively disarmed on the PR
    assert "noqa" in (result.note or "")


# --- review-repair loop (ADR-0006) ------------------------------------------------

class ReviewFixAgent:
    """Executor whose repair edits a file (so the re-commit is non-empty)."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        (workspace.path / "feature.py").write_text("VALUE = 42\n")
        return AgentRunResult(ok=True, summary="feature", cost_usd=0.01,
                              actions=["Edit: feature.py"])

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        (workspace.path / "feature.py").write_text("VALUE = 43  # per review\n")
        return AgentRunResult(ok=True, summary="fixed the review finding", cost_usd=0.05,
                              actions=["Edit: feature.py"])


class _ScriptedReviewer:
    """Returns each scripted verdict in turn (holding the last)."""

    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.calls = 0

    def review(self, *, sandbox, workspace, review_input) -> ReviewResult:
        v = self.verdicts[min(self.calls, len(self.verdicts) - 1)]
        self.calls += 1
        return v


def _rejected(finding=True):
    return ReviewResult(
        decision="rejected", score=40,
        findings=[Finding(severity="critical", description="the test asserts the wrong bundle",
                          file="t.tsx", line=1)] if finding else [],
        summary="not done as submitted",
    )


def _approved():
    return ReviewResult(decision="approved", score=95, summary="fixed")


def test_review_repair_fixes_a_rejection_then_approves(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#70", title="widget copy", objective="add copy", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="renders")],
    )
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true", "security": "true"},
                        review_mode="blocking", review_repair_max_attempts=1)
    reviewer = _ScriptedReviewer([_rejected(), _approved()])
    runner = _runner(repo, tracker, manifest, tmp_path, reviewer=reviewer,
                     agent=ReviewFixAgent())

    result = runner.run("#70")

    assert reviewer.calls == 2  # reviewed → rejected → repaired → re-reviewed
    assert result.review.decision == "approved"  # the final verdict is the fixed one
    assert result.state is JobState.PR_OPEN  # proceeded past the rejection
    assert result.total_cost_usd == pytest.approx(0.06)  # execute 0.01 + one review-repair 0.05
    assert JobState.REPAIRING in tracker.states  # the repair actually ran


def test_review_repair_bounded_still_rejected_goes_to_human(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#71", title="widget copy", objective="add copy", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="renders")],
    )
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true", "security": "true"},
                        review_mode="blocking", review_repair_max_attempts=1,
                        reviewers=["alice"])
    reviewer = _ScriptedReviewer([_rejected(), _rejected()])  # never satisfied
    runner = _runner(repo, tracker, manifest, tmp_path, reviewer=reviewer,
                     agent=ReviewFixAgent())

    result = runner.run("#71")

    assert reviewer.calls == 2  # exactly ONE repair attempt (default cap), then stop
    assert result.review.decision == "rejected"
    assert result.state is JobState.PR_OPEN  # handed to a human, not merged
    assert runner.forge.requested == ["alice"]  # human reviewers requested


def test_advisory_review_posts_comment_and_never_repairs(repo: Path, tmp_path: Path):
    # ADR-0014 default: the review is ADVISORY — it runs once, its verdict is posted to the PR as
    # a COMMENT, and a rejection never triggers the repair loop nor blocks the PR.
    ticket = Ticket(
        id="#72", title="widget copy", objective="add copy", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="renders")],
    )
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true", "security": "true"})  # review_mode → advisory
    reviewer = _ScriptedReviewer([_rejected()])  # would loop forever under blocking
    runner = _runner(repo, tracker, manifest, tmp_path, reviewer=reviewer, agent=ReviewFixAgent())

    result = runner.run("#72")

    assert reviewer.calls == 1  # ran ONCE — no repair, no re-review
    assert JobState.REPAIRING not in tracker.states  # the repair loop never ran
    assert result.state is JobState.PR_OPEN  # a rejection never blocks the PR
    assert runner.forge.reviews and runner.forge.reviews[0]["event"] == "comment"  # advisory


def test_single_agent_skips_the_planner_by_default(repo: Path, tmp_path: Path):
    # ADR-0014 default: no separate planner. An adapter that HAS plan() is still run single-agent
    # unless the manifest opts in (planner_stage), so plan() must not be called.
    class PlanSpyAgent(FakeAgent):
        def __init__(self) -> None:
            self.planned = False

        def plan(self, *, sandbox, workspace, context) -> AgentRunResult:
            self.planned = True
            return AgentRunResult(ok=True, summary="a plan the default must skip")

    ticket = Ticket(id="#73", title="x", objective="x", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    tracker = FakeTracker(ticket)
    agent = PlanSpyAgent()
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path, agent=agent)

    result = runner.run("#73")

    assert agent.planned is False  # planner_stage defaults False → single agent
    assert JobState.PLANNING not in tracker.states  # never entered the planning stage
    assert result.state is JobState.PR_OPEN


def test_rejection_without_findings_is_not_repaired(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#72", title="widget copy", objective="add copy", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="renders")],
    )
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true", "security": "true"},
                        review_repair_max_attempts=1)
    reviewer = _ScriptedReviewer([_rejected(finding=False)])  # vague verdict, no findings
    runner = _runner(repo, tracker, manifest, tmp_path, reviewer=reviewer,
                     agent=ReviewFixAgent())

    result = runner.run("#72")

    assert reviewer.calls == 1  # no actionable findings → no repair, straight to human
    assert result.review.decision == "rejected"
    assert JobState.REPAIRING not in tracker.states


def test_review_repair_disabled_when_max_attempts_zero(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#73", title="widget copy", objective="add copy", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="renders")],
    )
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true", "security": "true"},
                        review_repair_max_attempts=0)
    reviewer = _ScriptedReviewer([_rejected(), _approved()])
    runner = _runner(repo, tracker, manifest, tmp_path, reviewer=reviewer,
                     agent=ReviewFixAgent())

    result = runner.run("#73")

    assert reviewer.calls == 1  # disabled → no repair, the rejection stands
    assert result.review.decision == "rejected"


# --- on-demand e2e ticket (ADR-0008) ----------------------------------------------

class _E2EForge:
    """Records the dispatch and returns a completed run — no PR path is touched."""

    def __init__(self, conclusion="success"):
        self.dispatched = None
        self._conclusion = conclusion

    def dispatch_workflow(self, *, workflow, ref):
        self.dispatched = (workflow, ref)

    def latest_run(self, *, workflow):
        # Before dispatch there is no run yet (the platform pins this as the "prev" run);
        # after dispatch OUR run appears with a fresh id. This models the real ordering the
        # id-pinning watch relies on (F3) — the run we wait for is the NEW one, not a stale one.
        if self.dispatched is None:
            return None
        return {"id": 1, "status": "completed", "conclusion": self._conclusion,
                "url": "https://gh/run/1", "created_at": "2099-01-01T00:00:00Z"}

    def push_remote(self):
        return None


def _e2e_runner(repo, tracker, manifest, tmp_path, forge):
    return JobRunner(
        tracker=tracker, forge=forge, agent=FakeAgent(),
        sandbox=WorktreeSandbox(root=tmp_path / "wt"), manifest=manifest,
        repo_path=repo, reviewer=None, events=NullEventSink(),
    )


def test_e2e_ticket_dispatches_and_reports_pass(repo: Path, tmp_path: Path, monkeypatch):
    import openfactory.orchestrator.machine as m
    monkeypatch.setattr(m, "_E2E_POLL", 0)  # no real sleep
    ticket = Ticket(id="#80", title="run e2e", objective="run the e2e suite", repo="o/app",
                    labels=["e2e"])
    tracker = FakeTracker(ticket)
    manifest = Manifest(e2e_workflow="e2e.yml", e2e_label="e2e")
    forge = _E2EForge(conclusion="success")
    result = _e2e_runner(repo, tracker, manifest, tmp_path, forge).run("#80")

    assert forge.dispatched == ("e2e.yml", "main")  # dispatched the workflow on the base
    assert result.state is JobState.DONE  # e2e passed
    assert result.pr_url == "https://gh/run/1"  # links to the run
    # it never entered the implement pipeline
    assert JobState.PLANNING not in tracker.states
    assert JobState.IMPLEMENTING not in tracker.states


def test_e2e_ticket_reports_fail_as_on_hold(repo: Path, tmp_path: Path, monkeypatch):
    import openfactory.orchestrator.machine as m
    monkeypatch.setattr(m, "_E2E_POLL", 0)
    ticket = Ticket(id="#81", title="run e2e", objective="run the e2e suite", repo="o/app",
                    labels=["e2e"])
    tracker = FakeTracker(ticket)
    manifest = Manifest(e2e_workflow="e2e.yml", e2e_label="e2e")
    forge = _E2EForge(conclusion="failure")
    result = _e2e_runner(repo, tracker, manifest, tmp_path, forge).run("#81")

    assert result.state is JobState.ON_HOLD  # a red e2e is returned to the owner
    assert "red" in (result.note or "").lower()


def test_e2e_label_ignored_without_workflow(repo: Path, tmp_path: Path):
    # the label alone does nothing unless the manifest declares the workflow (opt-in) — the
    # ticket then runs the normal pipeline (uses the full FakeForge, incl. open_pr).
    ticket = Ticket(id="#82", title="feature", objective="add a feature", repo="o/app",
                    labels=["e2e"],
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true", "security": "true"})  # no e2e_workflow
    result = _runner(repo, tracker, manifest, tmp_path).run("#82")

    assert result.state is JobState.PR_OPEN  # ran the normal pipeline, not the e2e path
    assert JobState.IMPLEMENTING in tracker.states


# ── claiming the ticket must never be able to lose it ───────────────────────────────────────────
#
# Found on the FIRST real run of a fresh deployment (2026-08-02). `machine.py` claims the ticket by
# making the bot its sole assignee:
#
#     if self.bot.login:
#         self.tracker.set_assignees(ticket.id, [self.bot.login])
#
# GitHub answers `'factory-fixtures-bot[bot]' not found` — an App is not an assignable user —
# the adapter turns a non-zero `gh` exit into RuntimeError, and it escaped `run()` as a traceback.
# The ticket was left in TO-DO with no comment, no label and no state: a stall with nothing said,
# which is the one outcome this platform promises never to produce.
#
# TWO THINGS MAKE IT WORSE THAN A MISSING GUARD. The comment on the very next line already says
# "a GitHub App can't be an issue assignee", and `add_label` eight lines below — a strictly less
# important courtesy — is wrapped with "a labelling hiccup must never derail the job". Both facts
# were known and written down; the line between them was bare.
#
# It never fired at the pilot because that deployment sets no `OPENFACTORY_BOT_LOGIN`, so `login` is None
# and the branch is skipped — and `_runner` above mirrored that, so the suite could not see it
# either. A branch that is dead in production and dead in the tests is not covered by 2878 of them.

class _RefusingTracker(FakeTracker):
    """A tracker that refuses the claim, the way GitHub really does."""

    def set_assignees(self, ref: str, logins: list[str]) -> None:
        raise RuntimeError(
            "gh issue edit failed (1): failed to update .../issues/1: 'the-bot[bot]' not found"
        )


def test_a_refused_claim_does_not_lose_the_ticket(repo: Path, tmp_path: Path):
    """THE defect. Whatever the tracker says about assignees, the work must still happen — the
    claim is bookkeeping, and the PR is the point."""
    from openfactory.contracts.bot import BotIdentity

    ticket = Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    tracker = _RefusingTracker(ticket)
    forge = FakeForge()
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                     forge=forge, bot=BotIdentity(login="octocat"))

    result = runner.run("#1")

    assert forge.opened is not None, "the PR was never opened — a courtesy took the job down"
    assert result.state in (JobState.PR_OPEN, JobState.DONE, JobState.MERGED), result.state


def test_an_app_login_is_not_even_attempted(repo: Path, tmp_path: Path):
    """A `name[bot]` login CANNOT be an assignee on GitHub, so trying spends an API call to be
    told so, on every single pickup, and logs a warning that trains people to ignore warnings.

    The try/except above is the guard — provider-neutral and always right. This is the
    optimisation: do not ask a question whose answer is already known."""
    from openfactory.contracts.bot import BotIdentity

    ticket = Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    tracker = FakeTracker(ticket)
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                     bot=BotIdentity(login="factory-fixtures-bot[bot]"))

    runner.run("#1")

    assert tracker.assign_history == [], (
        "an App login was sent to the tracker as an assignee; GitHub can only answer 'not found'"
    )


def test_a_human_bot_login_is_still_claimed(repo: Path, tmp_path: Path):
    """The feature must not be defanged into never assigning. A deployment whose bot is a real
    user account — a PAT-based one, or a GitLab/Jira bot — still claims its ticket."""
    from openfactory.contracts.bot import BotIdentity

    ticket = Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    tracker = FakeTracker(ticket, assignees=["a-human"])
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                     bot=BotIdentity(login="openfactory-bot"))

    runner.run("#1")

    assert tracker.assign_history == [["openfactory-bot"]]


class _BlindTracker(FakeTracker):
    """A tracker that cannot say who a ticket belongs to — a permissions gap or a rate limit."""

    def assignees(self, ref: str) -> list[str]:
        raise RuntimeError("gh api rate limit exceeded")


def test_not_knowing_the_owner_does_not_lose_the_ticket(repo: Path, tmp_path: Path):
    """The same class as the claim, swept rather than patched. Reading the assignees exists ONLY
    to remember whom to route an impediment back to, and `ticket.author` is already the fallback
    three lines below. A read that can fail on a rate limit must not decide whether the delivery
    happens."""
    ticket = Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    tracker = _BlindTracker(ticket)
    forge = FakeForge()
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path, forge=forge)

    result = runner.run("#1")

    assert forge.opened is not None
    assert result.state in (JobState.PR_OPEN, JobState.DONE, JobState.MERGED), result.state


# --- C-34 (#71): the executor can raise a decision, not only fail ---
#
# The DecisionRequest construct, the BLOCKED park and the options UI all existed — and the only
# thing able to raise one was the planner, which is OFF by default (ADR-0014). The executor's
# genuine "I need you to choose" arrived as a generic ON_HOLD: plain text, no options,
# indistinguishable from a crash. These drive the REAL pipeline with an agent that stops on a
# question, and prove the question is treated as a question.

_DECISION_BLOCK = """I found two materially different ways to satisfy the criteria.

```json
{"question": "arredondar para cima ou para baixo nos centavos?",
 "context": "o ticket não diz, e as duas escolhas mudam o extrato do cliente",
 "options": [
   {"key": "floor", "label": "Para baixo", "consequence": "sobra vai ao primeiro", "recommended": true},
   {"key": "ceil", "label": "Para cima", "consequence": "falta sai do último"}]}
```"""


class _AsksAgent:
    """Stops on a judgment call. `repair` is armed to explode: a question is not a failure, and
    the recovery ladder spending agent passes on it was half the defect."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        (workspace.path / "half.py").write_text("# partial work\n")
        return AgentRunResult(ok=False, summary="preciso de uma decisão",
                              raw_output=_DECISION_BLOCK, cost_usd=0.01)

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        raise AssertionError("the recovery ladder ran on a QUESTION")

    recover = repair


def test_an_executor_question_parks_as_a_DECISION_not_a_crash(repo: Path, tmp_path: Path):
    ticket = Ticket(
        id="#7", title="split cents", objective="split", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="cents conserved")],
    )
    tracker = FakeTracker(ticket)
    manifest = Manifest(validate={"test": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path, agent=_AsksAgent())

    result = runner.run("#7")

    assert result.state is JobState.BLOCKED, result.note
    assert result.decision is not None
    assert result.decision.question.startswith("arredondar")
    assert [o.key for o in result.decision.options] == ["floor", "ceil"]
    # the question + options are DURABLE on the ticket, answerable from any channel
    assert any("Decision needed" in c for c in tracker.comments)
    assert any("floor" in c and "ceil" in c for c in tracker.comments)


def test_an_executor_stop_WITHOUT_a_question_keeps_the_recovery_ladder(repo: Path, tmp_path: Path):
    """The positive twin: a plain unfinished stop is still a failure, still recovered, and still
    holds as ON_HOLD when recovery cannot finish — nothing about the old path moved."""

    class _JustStops:
        def __init__(self):
            self.recoveries = 0

        def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
            return AgentRunResult(ok=False, summary="ran out of turns mid-edit")

        def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
            self.recoveries += 1
            return AgentRunResult(ok=False, summary="still stuck")

    agent = _JustStops()
    ticket = Ticket(
        id="#8", title="x", objective="x", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="y")],
    )
    runner = _runner(repo, FakeTracker(ticket), Manifest(validate={"test": "true"}),
                     tmp_path, agent=agent)

    result = runner.run("#8")

    assert result.state is JobState.ON_HOLD
    assert result.decision is None
    assert agent.recoveries > 0, "the ladder stopped running for ordinary failures"


def test_a_finished_run_containing_a_stray_block_is_judged_by_its_diff(repo: Path, tmp_path: Path):
    """ok=True with a fenced block in the output — perhaps quoted from a file it read — must NOT
    park: the work is done and the gates decide."""

    class _FinishesNoisily:
        def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
            (workspace.path / "feature.py").write_text("VALUE = 42\n")
            return AgentRunResult(ok=True, summary="done", raw_output=_DECISION_BLOCK,
                                  cost_usd=0.01, actions=["Edit: feature.py"])

        def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
            return AgentRunResult(ok=True)

    ticket = Ticket(
        id="#9", title="f", objective="f", repo="o/app",
        acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")],
    )
    runner = _runner(repo, FakeTracker(ticket), Manifest(validate={"test": "true"}),
                     tmp_path, agent=_FinishesNoisily())

    result = runner.run("#9")

    assert result.state is JobState.PR_OPEN
    assert result.decision is None


# ── the quality floor REFUSES, and this is the behavioural half ─────────────────────────────────

def test_a_project_with_no_gates_never_reaches_the_agent(repo: Path, tmp_path: Path,
                                                         monkeypatch):
    """The floor holds the ticket BEFORE any agent pass. Measured on a real `run`, not on the AST.

    WHY THIS TEST EXISTS AND WHY IT IS HERE. The refusal used to sit behind `OPENFACTORY_ENFORCE_FLOOR`,
    off by default; removing that switch is only worth anything if something notices when the
    refusal itself goes away. It did not: deleting `return self._hold(...)` from `JobRunner.run`
    — turning the floor back into a warning — left seventy-four floor and readiness tests green,
    because every one of them checked what `floor_reason` SAYS and none checked what the runner
    DOES with it. That is this repository's signature defect, in the guard written against it.

    `no_gates` is genuinely gateless: `_inherit_the_deployment_floor` gives every real project a
    `security` command, so a manifest that violates the floor has to be built with the deployment
    default silenced. That is not a hypothetical world — it is exactly a build that cannot read
    `org_defaults/floor.yaml`, and it is the state every project was in before that file existed.
    """
    monkeypatch.setattr("openfactory.policy.presets.org_default_validation", lambda: {})

    ticket = Ticket(id="#9", title="anything", objective="anything at all", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="a file exists")])
    tracker = FakeTracker(ticket, assignees=["someone"])
    agent = FakeAgent()
    runner = _runner(repo, tracker, Manifest(validate={}), tmp_path, agent=agent)

    result = runner.run("#9")

    assert result.state is JobState.ON_HOLD, (
        f"a project declaring no gates ran anyway and ended {result.state} — `all([])` is True, so "
        f"it would have reported green having proven nothing"
    )
    assert getattr(agent, "calls", None) in (None, 0, []) or not agent.calls, (
        "the agent was paid before the floor was checked; the refusal exists to spend nothing"
    )
    # THE SENTENCE, NOT THE PHRASE. My first version looked for the literal "quality floor" and
    # failed on a comment that is better than that: the words "quality floor" are in the EVENT
    # note, while what lands on the ticket names the missing roles and how to declare each. What
    # must never regress is that a human reading the card can act — a silent hold is the one thing
    # this platform refuses everywhere else.
    said = "\n".join(tracker.comments)
    for expected in ("`security`", "`test`", ".openfactory/project.yaml", "Nothing was run"):
        assert expected in said, (
            f"the hold does not tell the client {expected} — a hold nobody can act on is a stall "
            f"wearing an answer's clothes. Comments: {tracker.comments}"
        )


def test_a_project_WITH_gates_still_runs(repo: Path, tmp_path: Path, monkeypatch):
    """The positive twin, and the one that would catch an over-eager floor.

    A refusal that fired on every project would pass the test above while stopping the whole
    fleet — which is precisely the outage that kept `OPENFACTORY_ENFORCE_FLOOR` switched off for months.
    """
    monkeypatch.setattr("openfactory.policy.presets.org_default_validation", lambda: {})

    ticket = Ticket(id="#10", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    tracker = FakeTracker(ticket)
    runner = _runner(repo, tracker, Manifest(validate={"test": "true", "security": "true"}),
                     tmp_path)

    assert runner.run("#10").state is JobState.PR_OPEN


def test_the_INHERITED_gate_is_enough_to_pass_the_floor(repo: Path, tmp_path: Path):
    """And the reason removing the switch is safe: a client declaring only `test` still runs.

    No monkeypatch here — this is the real deployment default, read from the packaged
    `org_defaults/floor.yaml`. If that file ever stops shipping (it did once, absent from a built
    wheel), this test fails rather than the client's first ticket.
    """
    ticket = Ticket(id="#11", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    tracker = FakeTracker(ticket)
    runner = _runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path)

    assert runner.run("#11").state is JobState.PR_OPEN, (
        "a project declaring only `test` was refused — the inherited `security` gate is not "
        "reaching the manifest, and every new client would be held on their first ticket"
    )
