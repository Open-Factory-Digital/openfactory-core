"""A Jira project IS the board — the pickup queue for a deployment with no GitHub Projects (F-02).

`JiraTracker` has covered tickets for months and none of it gets a ticket PICKED UP: the poller
asks `build_board(project)`, `BOARD_KINDS` listed only `github`, and a Jira project resolved to
`None` — which `scan_todo` reports as *"no board configured — the pickup queue is empty by
configuration, not because nothing is waiting"*. Truthful, and total: the factory would sit idle
beside a full Jira backlog. The client's first day looks like a factory that does not work.

Proven live against a real Jira on 2026-08-05 (project DAR), which is how the tests below know
what to assert: the search endpoint this was first written against **no longer exists**.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.board.jira import JiraProjectBoard
from openfactory.contracts import JobState

STATUS_MAP = {"todo": "TO-DO", "in_progress": "Em andamento", "in_review": "Em análise",
              "needs_action": "Needs Action", "done": "Donee"}


class _FakeJira:
    """Stands in for `JiraTracker`, recording the REST calls the board makes."""

    project_key = "DAR"

    def __init__(self, replies=None, status_map=None, fail=()):
        self.calls: list[tuple[str, str]] = []
        self.replies = replies or {}
        self.status_map = STATUS_MAP if status_map is None else status_map
        self.fail = fail

    def _call(self, method: str, path: str, payload=None):
        self.calls.append((method, path))
        for marker in self.fail:
            if marker in path:
                raise RuntimeError(f"jira {method} {path} failed: 500")
        for marker, reply in self.replies.items():
            if marker in path:
                return reply
        return {}


def _issues(*pairs):
    return {"isLast": True,
            "issues": [{"key": k, "fields": {"status": {"name": s}}} for k, s in pairs]}


# ── the endpoint the live Jira actually has ─────────────────────────────────────────────────────

def test_the_search_goes_to_the_endpoint_that_still_EXISTS():
    """`/rest/api/3/search` is GONE — Atlassian removed it, and a live call answers 410 with
    *"Migre para a API /rest/api/3/search/jql"*. Found the first time this board met a real Jira;
    no fake would ever have said it. This guard is here so nobody "simplifies" the path back."""
    jira = _FakeJira({"search/jql": _issues(("DAR-1", "TO-DO"))})

    JiraProjectBoard(jira).items_in_status("TO-DO")

    paths = [p for _, p in jira.calls]
    assert any(p.startswith("search/jql?") for p in paths), paths
    assert not any(p.startswith("search?") for p in paths), "the removed endpoint is back"


def test_the_queue_follows_the_backlogs_own_RANK():
    """The protocol says board order, and a Jira backlog IS ranked by the humans who groomed it.
    Key order would hand the factory whatever was created first."""
    jira = _FakeJira({"search/jql": _issues(("DAR-9", "TO-DO"), ("DAR-2", "TO-DO"))})

    refs = JiraProjectBoard(jira).items_in_status("TO-DO")

    assert refs == ["DAR-9", "DAR-2"], "the board re-sorted what the humans had ranked"
    assert "ORDER+BY+Rank" in jira.calls[0][1]


def test_the_status_is_QUOTED_into_the_jql():
    jira = _FakeJira({"search/jql": _issues()})

    JiraProjectBoard(jira).items_in_status("Em análise")

    assert "status" in jira.calls[0][1]


# ── unreadable is never empty ───────────────────────────────────────────────────────────────────

def test_columns_returns_NONE_when_jira_could_not_be_read():
    """The protocol's hardest rule, and the one three separate bugs in this codebase came from
    breaking: an unreachable tracker read as "nothing is queued"."""
    board = JiraProjectBoard(_FakeJira(fail=("search/jql",)))

    assert board.columns() is None


def test_columns_returns_EMPTY_when_the_project_genuinely_has_nothing():
    board = JiraProjectBoard(_FakeJira({"search/jql": _issues()}))

    assert board.columns() == {}


def test_column_names_returns_NONE_when_unreadable_not_an_empty_list():
    """Reporting an unreadable project as "it defines no columns" sends somebody to rename
    columns they are looking straight at."""
    board = JiraProjectBoard(_FakeJira(fail=("statuses",)))

    assert board.column_names() is None


def test_column_names_are_the_projects_own_statuses_deduplicated():
    """Asked of the PROJECT, not derived from the cards: a status nothing currently sits in still
    exists, and `sdlc doctor` asking "is there a TO-DO?" must not be answered by an empty backlog.
    Jira repeats the same statuses per issue type, so they are collapsed in board order."""
    jira = _FakeJira({"statuses": [
        {"name": "Tarefa", "statuses": [{"name": "TO-DO"}, {"name": "Donee"}]},
        {"name": "Bug", "statuses": [{"name": "TO-DO"}, {"name": "Needs Action"}]},
    ]})

    assert JiraProjectBoard(jira).column_names() == ["TO-DO", "Donee", "Needs Action"]


def test_an_unreadable_queue_is_empty_but_LOUD(caplog):
    """`items_in_status` returns `[]` because it is the poller's hottest read and an exception
    there would take the whole tick down — so the warning is the only thing that distinguishes
    "nothing waiting" from "I could not ask"."""
    board = JiraProjectBoard(_FakeJira(fail=("search/jql",)))

    with caplog.at_level("WARNING"):
        assert board.items_in_status("TO-DO") == []

    assert "UNREADABLE" in caplog.text


def test_a_truncated_page_says_so(caplog):
    """The replacement endpoint carries no `total`, so completeness is `isLast` — and a missing
    `isLast` must read as "there may be more", never as "that was everything". A queue quietly
    missing its tail looks exactly like a queue that is done."""
    jira = _FakeJira({"search/jql": {"issues": [{"key": "DAR-1", "fields": {}}]}})

    with caplog.at_level("WARNING"):
        refs = JiraProjectBoard(jira).items_in_status("TO-DO")

    assert refs == ["DAR-1"], "the page it DID get must still be usable"
    assert "may be missing items" in caplog.text


# ── moving a card is a workflow transition, never a forced write ────────────────────────────────

def test_a_move_uses_the_projects_OWN_transition():
    jira = _FakeJira({"transitions": {"transitions": [
        {"id": "31", "name": "Iniciar", "to": {"name": "Em andamento"}}]}})

    ok = JiraProjectBoard(jira).set_status(issue="DAR-1", issue_url="",
                                           state=JobState.IMPLEMENTING)

    assert ok
    assert ("POST", "issue/DAR-1/transitions") in jira.calls


def test_a_transition_the_workflow_does_not_offer_is_REFUSED_not_forced(caplog):
    """Every Jira project has its own workflow. Forcing one either fails or moves the card
    somewhere nobody expects — and a False must always leave a why behind it."""
    jira = _FakeJira({"transitions": {"transitions": [
        {"id": "11", "name": "Parar", "to": {"name": "Backlog"}}]}})

    with caplog.at_level("ERROR"):
        ok = JiraProjectBoard(jira).set_status(issue="DAR-1", issue_url="", state=JobState.DONE)

    assert ok is False
    assert "OPENFACTORY_BOARD_MOVE_FAILED" in caplog.text


def test_an_UNMAPPED_state_is_refused_with_a_reason_never_guessed(caplog):
    """C-14: the client's vocabulary belongs to the client, so an unmapped state has no column
    this platform is entitled to invent."""
    jira = _FakeJira(status_map={"todo": "TO-DO"})  # nothing mapped for `done`

    with caplog.at_level("WARNING"):
        ok = JiraProjectBoard(jira).set_status(issue="DAR-1", issue_url="", state=JobState.DONE)

    assert ok is False
    assert "status_map" in caplog.text


def test_the_board_and_the_state_machine_share_ONE_status_map():
    """The map is the tracker's, so the two cannot disagree about what "done" is called here."""
    jira = _FakeJira({"transitions": {"transitions": [
        {"id": "41", "name": "Concluir", "to": {"name": "Donee"}}]}})

    assert JiraProjectBoard(jira).set_status(issue="DAR-1", issue_url="", state=JobState.DONE)


def test_add_item_is_a_no_op_because_an_issue_is_already_on_its_project():
    """Kept explicit rather than omitted: a caller must not have to know which board shape it
    holds. A Projects v2 card must be ATTACHED; a Jira issue simply is."""
    jira = _FakeJira()

    JiraProjectBoard(jira).add_item(issue_url="https://x/DAR-1")

    assert jira.calls == [], "adding an issue to its own project made a REST call"


# ── the factory hands a Jira project this board, with no coordinates to invent ──────────────────

def test_a_jira_project_now_RESOLVES_to_a_board(monkeypatch):
    """The gap that made F-02 impossible: `build_board` returned None, and the poller reported an
    empty queue beside a full backlog."""
    import json as _json

    from openfactory.adapters.board import build_board
    from openfactory.contracts.project import Project, ProviderRef

    project = Project(name="fx-jira", repo_path="unused",
                      tracker=ProviderRef(kind="jira", repo="DAR", options={
                          "site": "https://x.atlassian.net", "project_key": "DAR",
                          "email": "a@b.c", "status_map": _json.dumps(STATUS_MAP)}))

    board = build_board(project, token="t")

    assert isinstance(board, JiraProjectBoard)
    assert board.project_key == "DAR"


def test_a_jira_project_needs_NO_board_owner_or_number():
    """The absence is the design: a Jira project's workflow status IS its column, so there is no
    second object to point at. Demanding coordinates would invent configuration a Jira deployment
    cannot supply."""
    import json as _json

    from openfactory.adapters.board import build_board
    from openfactory.contracts.project import Project, ProviderRef

    project = Project(name="fx-jira", repo_path="unused",
                      tracker=ProviderRef(kind="jira", repo="DAR", options={
                          "site": "https://x.atlassian.net", "project_key": "DAR",
                          "email": "a@b.c", "status_map": _json.dumps(STATUS_MAP)}))

    assert build_board(project, token="t") is not None


def test_an_unknown_tracker_kind_still_RAISES_rather_than_defaulting():
    from openfactory.adapters.board import build_board
    from openfactory.contracts.project import Project, ProviderRef

    project = Project(name="p", repo_path="unused",
                      tracker=ProviderRef(kind="linear", repo="X", options={
                          "board_owner": "acme", "board_number": "1"}))

    with pytest.raises(ValueError, match="no board provider"):
        build_board(project)


# ── one deployment, N projects, and they do NOT share a tracker credential ──────────────────────

def test_a_project_names_its_OWN_tracker_credential(monkeypatch):
    """FOUND LIVE on fx-jira (F-02, 2026-08-05). `tracker_token()` is a single process-wide value,
    so a worker serving a GitHub project and a Jira project authenticated both with whichever one
    the environment happened to carry. The board resolved, the search ran, the backlog had a
    ticket in TO-DO — and the pickup queue came back `[]`.

    THE REGISTRY NAMES THE VARIABLE, IT NEVER HOLDS THE SECRET: `deploy/registry.yaml` is baked
    into the worker image, so a token written there is a token in an image layer. Same shape
    ADR-0015 already uses for the per-workspace Slack token."""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.credentials import tracker_token_for

    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "the-github-app-token")
    monkeypatch.setenv("JIRA_API_TOKEN", "the-jira-token")
    jira = Project(name="fx-jira", repo_path="unused",
                   tracker=ProviderRef(kind="jira", repo="DAR",
                                       options={"token_env": "JIRA_API_TOKEN"}))
    github = Project(name="fx-mono", repo_path="unused",
                     tracker=ProviderRef(kind="github", repo="acme/x"))

    assert tracker_token_for(jira) == "the-jira-token"
    assert tracker_token_for(github) == "the-github-app-token", (
        "a project that names nothing must reach the deployment's own, byte for byte")


def test_a_named_variable_that_is_EMPTY_is_said_out_loud(monkeypatch, caplog):
    """Falling back silently would authenticate a Jira project with a GitHub token and report an
    empty queue — the exact failure, wearing the fix."""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.credentials import tracker_token_for

    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "the-github-app-token")
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    project = Project(name="fx-jira", repo_path="unused",
                      tracker=ProviderRef(kind="jira", repo="DAR",
                                          options={"token_env": "JIRA_API_TOKEN"}))

    with caplog.at_level("WARNING"):
        tracker_token_for(project)

    assert "JIRA_API_TOKEN" in caplog.text and "wrong system" in caplog.text


def test_the_poller_SCANS_a_jira_project_at_all(monkeypatch):
    """The last gap, and the quietest: `scan_projects` filtered on `board_owner`/`board_number`
    — GitHub Projects coordinates a Jira project does not have and should not invent. So a Jira
    deployment was never in the poller's work list: box proven, credential wired, DAR-2 sitting
    in TO-DO, and nothing ever looked (F-02, found live 2026-08-05).

    Having a board is a question for `build_board`, which is the one place that knows what each
    provider needs — not a pattern match on one vendor's configuration."""
    import asyncio
    import json as _json

    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import activities

    jira = Project(name="fx-jira", repo_path="unused",
                   tracker=ProviderRef(kind="jira", repo="DAR", options={
                       "site": "https://x.atlassian.net", "project_key": "DAR",
                       "email": "a@b.c", "status_map": _json.dumps(STATUS_MAP)}))
    tickets_only = Project(name="fx-plain", repo_path="unused",
                           tracker=ProviderRef(kind="github", repo="acme/x"))
    monkeypatch.setattr(ProjectRegistry, "list", lambda self: [jira, tickets_only])

    scanned = asyncio.run(activities.scan_projects())

    names = [row["project"] for row in scanned]
    assert "fx-jira" in names, "a Jira project is never even looked at"
    assert "fx-plain" not in names, (
        "a project with no board configured at all must still be skipped — tickets-only is a "
        "legitimate configuration, not a queue")


def test_a_board_WITHOUT_coordinates_does_not_break_the_whole_poll_tick(monkeypatch):
    """MY OWN REGRESSION, caught by the live stack within minutes (2026-08-05). Adding Jira to
    the work list emitted `board_owner: None`, `ScanInput` types it `str`, and validation failed
    INSIDE the workflow — so the poll tick died. Not one broken project: every project, every
    tick, until the worker was rolled back.

    A row this activity emits is a WORKFLOW INPUT, and its contract is checked where there is no
    person to tell."""
    import asyncio
    import json as _json

    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal.activities import scan_projects
    from openfactory.runtime.temporal.io import ScanInput

    jira = Project(name="fx-jira", repo_path="unused",
                   tracker=ProviderRef(kind="jira", repo="DAR", options={
                       "site": "https://x.atlassian.net", "project_key": "DAR",
                       "email": "a@b.c", "status_map": _json.dumps(STATUS_MAP)}))
    monkeypatch.setattr(ProjectRegistry, "list", lambda self: [jira])

    rows = asyncio.run(scan_projects())

    assert rows, "the Jira project fell out of the work list"
    for row in rows:  # the workflow does exactly this, and used to raise
        ScanInput(**row)


# ── the platform's own vocabulary, in the shape each provider accepts ───────────────────────────

def test_the_working_label_is_reshaped_for_jira():
    """FOUND LIVE on DAR-2, the first Jira ticket this platform ever ran. Jira labels cannot
    contain spaces and the marker is `🤖 sdlc-working` — GitHub-shaped, because GitHub is where it
    was written. Jira answered 400, the caller swallowed it (labelling is best-effort by design),
    and the "the bot is working this" marker simply never appeared on a Jira board."""
    from openfactory.adapters.tracker.jira import JiraTracker

    assert JiraTracker.jira_label("🤖 sdlc-working") == "🤖-sdlc-working"
    assert JiraTracker.jira_label("sdlc:in_progress") == "sdlc:in_progress"
    assert JiraTracker.jira_label("  ") == "openfactory", "an empty label must not be sent as empty"


def test_adding_and_removing_use_the_SAME_shape():
    """Reshaping only on the way in would leave a label nothing can ever remove."""
    from openfactory.adapters.tracker.jira import JiraTracker

    t = JiraTracker(site="https://x", project_key="DAR", email="a@b.c", token="t")
    sent: list[dict] = []
    t._call = lambda method, path, payload=None: sent.append(payload) or {}

    t.add_label("DAR-1", "🤖 sdlc-working")
    t.remove_label("DAR-1", "🤖 sdlc-working")

    added = sent[0]["update"]["labels"][0]["add"]
    removed = sent[1]["update"]["labels"][0]["remove"]
    assert added == removed == "🤖-sdlc-working"
