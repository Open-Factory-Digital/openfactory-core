"""Tickets must live wherever the client keeps them — Jira as readily as GitHub.

The product owner, 2026-07-28: *"the scope is not bigger, that was a premise from way back — the
pilot client is Python with GitHub, but I am going to sell this to many clients with completely
different structures… just like the harness, we have to be BORN with Claude Code, Codex and
Kimi."*

That is the standard: an axis is not agnostic because it has a Protocol, it is agnostic when it is
BORN with more than one implementation and a seam that dispatches between them. The harness has had
three since it shipped. The tracker had a Protocol and exactly one implementation, constructed by
name in a dozen places — agnostic on paper, GitHub-only in the composition root.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from openfactory.adapters.tracker.base import TrackerAdapter
from openfactory.adapters.tracker.registry import TRACKERS, build_tracker
from openfactory.contracts import JobState
from openfactory.contracts.project import Project, ProviderRef

_JIRA_OPTS = {"site": "https://x.atlassian.net", "project_key": "CONT", "email": "a@b.c"}


def _project(kind="github", **options):
    return Project(name="x", repo_path="/t",
                   tracker=ProviderRef(kind=kind, repo="CONT", options=options),
                   forge=ProviderRef(kind="github", repo="a/b"))


def test_the_platform_is_BORN_with_more_than_one_tracker():
    """One implementation behind a Protocol is a promise; two is an architecture."""
    assert {"github", "jira"} <= set(TRACKERS), (
        f"the tracker axis ships only {sorted(TRACKERS)} — the premise is Jira OR GitHub")


@pytest.mark.parametrize("kind,options", [("github", {"board_owner": "A", "board_number": "6"}),
                                          ("jira", _JIRA_OPTS)])
def test_every_tracker_satisfies_the_SAME_contract(kind, options):
    """Checked at runtime, not asserted in prose. The board protocol caught its own implementation
    this way — `isinstance` said False until `columns()` existed."""
    assert isinstance(build_tracker(_project(kind, **options)), TrackerAdapter)


def test_an_unknown_tracker_RAISES_rather_than_defaulting_to_github():
    """A deployment whose tickets live elsewhere would otherwise have this one silently writing
    into a repository nobody reads — the failure worse than an unsupported tracker."""
    with pytest.raises(ValueError, match="unknown tracker"):
        build_tracker(_project("linear"))


def test_jira_never_invents_a_workflow_transition():
    """Every Jira project has its own statuses. An unmapped state is a no-op with a warning; a
    guessed transition either fails or moves the card somewhere nobody expects."""
    from openfactory.adapters.tracker.jira import JiraTracker

    calls = []
    tracker = JiraTracker(site="https://x", project_key="CONT", email="a@b.c")
    tracker._call = lambda *a, **k: calls.append(a) or {}  # noqa: SLF001 — the point of the test
    tracker.set_state("CONT-1", JobState.IMPLEMENTING)
    assert calls == [], "it transitioned an issue with no status_map configured"


def test_jiras_state_buckets_mirror_the_github_boards():
    """An operator configuring Jira answers the SAME four questions a GitHub board answers with its
    columns — not a second vocabulary. And a JobState added to the contract must land unmapped
    (no-op + warning) rather than silently transitioning somewhere wrong."""
    from openfactory.adapters.tracker.base import STATE_KEYS, column_key

    # ASKED OF THE CONTRACT'S RESOLVER, not of a table the adapter holds. Jira used to import the
    # table itself; it resolves through `column_key` now, because a state alone cannot say whether
    # a person is the blocker (#166) and neither could a table lookup.
    answers = {column_key(state) for state in STATE_KEYS}
    assert answers == set(STATE_KEYS.values()), (
        "Jira has grown a vocabulary of its own — an operator configuring it would answer "
        "different questions from the one configuring a board")
    for state in (JobState.ON_HOLD, JobState.BLOCKED, JobState.NEEDS_REFINEMENT, JobState.FAILED):
        assert column_key(state) == "needs_action", (
            f"{state} no longer routes to the column a human watches")


def test_jira_reads_a_description_written_with_rich_formatting():
    """Jira stores rich text as ADF. A description written with panels or tables coming back empty
    would be judged by the sizing gate as a ticket that says nothing."""
    from openfactory.adapters.tracker.jira import JiraTracker

    adf = {"type": "doc", "content": [
        {"type": "panel", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "must be true"}]}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "second line"}]}]}
    assert JiraTracker._text(adf) == "must be true\nsecond line"


def test_jira_escapes_a_title_before_putting_it_in_a_query():
    """The splitter's idempotency runs through find_ticket. A title with a quote must not break the
    query — or, worse, match a different issue and make a re-run reuse the wrong child."""
    from openfactory.adapters.tracker.jira import JiraTracker

    seen = {}
    tracker = JiraTracker(site="https://x", project_key="CONT", email="a@b.c")
    tracker._call = lambda m, p, payload=None: seen.update(payload or {}) or {"issues": []}  # noqa: SLF001
    tracker.find_ticket(title='Corrigir "extrato" conciliado')
    assert '\\"extrato\\"' in seen["jql"], f"unescaped title reached the query: {seen['jql']}"


def test_no_core_module_names_a_concrete_tracker():
    """The seam's whole claim: adding a provider is one row in the registry, not a sweep through
    the composition root."""
    allowed = {"openfactory/adapters/tracker/registry.py", "openfactory/adapters/tracker/github.py",
               "openfactory/adapters/tracker/jira.py", "openfactory/adapters/tracker/__init__.py",
               "openfactory/factory.py"}
    stray = set()
    scanned = 0
    vendors = {"GitHubIssuesTracker", "JiraTracker"}
    for path in Path("openfactory").rglob("*.py"):
        scanned += 1
        if str(path) in allowed:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            named = (isinstance(node, ast.Call)
                     and (getattr(node.func, "id", "") in vendors
                          or getattr(node.func, "attr", "") in vendors))
            imported = (isinstance(node, ast.ImportFrom)
                        and any(a.name in vendors for a in node.names))
            if named or imported:
                stray.add(str(path))
    assert scanned > 80, f"scanned only {scanned} files — run from the repo root, or fix the scan"
    assert not stray, (
        f"these construct a tracker by name: {sorted(stray)}. Use build_tracker(project) — a Jira "
        f"client must not need any of them changed."
    )


# ── the column LABELS are the client's; only the states are closed (C-14) ───────────────────────

def test_the_lifecycle_table_is_the_contract_s_not_a_copy():
    """Two adapters, one bucketing. Jira imported the contract's table by identity; it now calls
    the contract's RESOLVER, which is the same property one step further along — the bucketing and
    the person/machine reading of it both live in one place."""
    import inspect

    from openfactory.adapters.tracker import jira
    from openfactory.adapters.tracker.base import column_key

    assert jira._column_key is column_key
    # PROSE STRIPPED FIRST: the paragraph explaining this rule names the very symbol
    # it forbids, which is how a guard comes to fail on its own explanation.
    from conftest import code_only

    assert "STATE_KEYS" not in code_only(inspect.getsource(jira)), (
        "Jira reads the table directly again — the `needs_person` reading lives in `column_key`, "
        "so a lookup that goes around it cannot see a human merge gate")


def test_a_portuguese_board_drives_a_ticket_with_no_rename(monkeypatch):
    """The card's own sentence. The client's board says "A Fazer"/"Fazendo"; a state change must
    land on THEIR column — the tax today is renaming the board to the platform's English."""
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard
    from openfactory.contracts import JobState

    board = GitHubProjectBoard("o", "1", token="t", columns={
        "todo": "A Fazer", "in_progress": "Fazendo", "needs_action": "Precisa de Ação",
        "done": "Feito", "backlog": "Ideias"})
    moved: list[str] = []
    monkeypatch.setattr(GitHubProjectBoard, "_board_items",
                        lambda self: [{"number": 7, "status": "A Fazer", "id": "item-1"}])
    monkeypatch.setattr(GitHubProjectBoard, "_ensure_meta", lambda self: None)
    board._option_ids = {"Fazendo": "opt-f", "Ideias": "opt-i"}
    board._status_field_id = "field-1"
    board._project_id = "proj-1"
    monkeypatch.setattr(GitHubProjectBoard, "_set_option",
                        lambda self, item, opt: moved.append(opt) or True) \
        if hasattr(GitHubProjectBoard, "_set_option") else None
    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", lambda *a, **k: type("_P", (), {"returncode": 0})())

    assert board.set_status(issue="7", issue_url="https://x/7", state=JobState.IMPLEMENTING), \
        "the move to the client's own column name failed"


def test_the_needs_action_fallback_speaks_the_configured_names(monkeypatch):
    """The old fallback was literal: "Needs Action" missing → "Backlog". On a renamed board both
    literals miss and a parked ticket stays painted as in-progress — the exact harm the fallback
    exists to prevent."""
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard
    from openfactory.contracts import JobState

    board = GitHubProjectBoard("o", "1", token="t", columns={
        "needs_action": "Precisa de Ação", "backlog": "Ideias"})
    monkeypatch.setattr(GitHubProjectBoard, "_board_items",
                        lambda self: [{"number": 7, "status": "Fazendo", "id": "item-1"}])
    monkeypatch.setattr(GitHubProjectBoard, "_ensure_meta", lambda self: None)
    # the board has NO "Precisa de Ação" column — only the renamed backlog
    board._option_ids = {"Ideias": "opt-i"}
    board._status_field_id = "field-1"
    board._project_id = "proj-1"
    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", lambda *a, **k: type("_P", (), {"returncode": 0})())

    assert board.set_status(issue="7", issue_url="https://x/7", state=JobState.ON_HOLD), \
        "the fallback still looks for the English literals on a renamed board"


def test_an_unconfigured_board_behaves_exactly_as_before():
    """The defaults ARE the old literals — zero-config deployments must not move."""
    from openfactory.adapters.tracker.base import STATE_KEYS
    from openfactory.adapters.tracker.github_project import DEFAULT_COLUMNS, STATUS_MAP

    for state, column in STATUS_MAP.items():
        assert DEFAULT_COLUMNS[STATE_KEYS[state]] == column, (
            f"{state}: the derived default disagrees with the canonical STATUS_MAP")


def test_the_registry_row_reaches_the_board(monkeypatch):
    """Wiring, not behaviour: `columns:` in the tracker options must arrive at the constructor —
    a mapping configured and read by nothing is this house's signature defect."""
    from openfactory.adapters.board.factory import build_board

    class _Ref:
        kind = "github"
        repo = "o/r"
        options = {"board_owner": "o", "board_number": "1",
                   "columns": {"todo": "A Fazer"}}

    class _P:
        tracker = _Ref()

    board = build_board(_P(), token="t")

    assert board._columns["todo"] == "A Fazer"
    assert board._columns["done"] == "Done", "an override wiped the defaults instead of layering"


def test_the_pickup_column_follows_the_clients_todo_name(monkeypatch):
    """scan_projects' pickup default must speak the same map: a Portuguese board with
    `columns.todo: A Fazer` and no explicit pickup_status polls "A Fazer", not "TO-DO"."""
    import asyncio

    import openfactory.runtime.temporal.activities as acts

    class _Ref:
        kind = "github"
        repo = "o/r"
        options = {"board_owner": "o", "board_number": "1",
                   "columns": {"todo": "A Fazer"}}

    class _P:
        name = "acme"
        enabled = True
        tracker = _Ref()

    class _Reg:
        def list(self):
            return [_P()]

    monkeypatch.setattr(acts, "ProjectRegistry", lambda: _Reg())

    (row,) = asyncio.run(acts.scan_projects())

    assert row["pickup_status"] == "A Fazer"


# ── the board and the floor answer the same question (#166) ─────────────────────────────────────

def test_every_state_the_FLOOR_calls_needs_you_lands_in_the_board_column_that_says_so():
    """MEASURED ON THE PILOT. The panel said `Needs you — podbeam #103 — a pull request is
    waiting on your review` while the client's board showed the card in **In review** and its
    **Needs Action** column reading **0**. Two surfaces, one question, opposite answers — and the
    board is the surface the product owner lives on.

    `awaiting_prod_approval` was the unambiguous half: it is ALWAYS a person, both lists said so
    in their own words, and it sat in the review bucket anyway.
    """
    from openfactory.adapters.tracker.base import STATE_KEYS
    from openfactory.contracts.state import JobState
    from openfactory.runtime.temporal.view import ATTENTION_STATES

    wrong = {s.value: STATE_KEYS[s] for s in JobState
             if s.value in ATTENTION_STATES and s in STATE_KEYS
             and STATE_KEYS[s] != "needs_action"}
    assert not wrong, (
        f"the floor calls these 'needs you' and the board files them elsewhere: {wrong}. A person "
        f"reading the board is told nothing is waiting on them.")

    # WHAT THIS GUARD CANNOT SEE, said out loud rather than left to read as coverage. The case the
    # pilot actually photographed — a pull request waiting on a HUMAN merge — has no `JobState` of
    # its own: the engine writes `pr_open` for both merge paths and `view._domain_state` derives
    # `awaiting_your_merge` from `_merge_wait.auto`, which the board never sees. So `pr_open` maps
    # to `in_review`, correct for the armed auto-merge and wrong for the human gate, and no
    # assertion above can tell them apart. That half needs the port to carry the distinction.
    assert not any(s.value == "awaiting_your_merge" for s in JobState), (
        "a JobState for the human merge gate exists now — this guard can cover it, and should")


def test_and_the_machine_paths_that_need_NOBODY_stay_out_of_that_column():
    """The twin, and it is what keeps the column meaningful: a card in `Needs Action` must be one
    somebody has to touch. An armed auto-merge watching CI, a job coding, a merged change — none
    of those is a person's problem, and filing them there would make the column noise."""
    from openfactory.adapters.tracker.base import STATE_KEYS
    from openfactory.contracts.state import JobState

    for state in (JobState.IMPLEMENTING, JobState.REVIEWING, JobState.MERGED, JobState.DONE,
                  JobState.PROD_VERIFYING, JobState.STAGING_VERIFYING):
        assert STATE_KEYS[state] != "needs_action", (
            f"{state.value} files a card as needing a person while the machine is working on it")
