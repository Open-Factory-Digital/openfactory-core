"""The client's board writes must carry a live token, tell the truth, and leave a trace.

The board is the client's authoritative view of the factory. Four ways it silently stopped
matching reality, each pinned here through the PRODUCTION subprocess path (a fake runner —
local `gh` shares the production GitHub App rate limit and must never be spawned by a test):

  1. the App installation token (~1h) was frozen into the board at tracker construction, so
     every board move in a job that outlived the token failed silently;
  2. `set_state` discarded `set_status`'s bool — no log, no label fallback, no trace;
  3. `_ensure_meta` assigned its early-return key before the field-list fetch, so one
     rate-limit blip poisoned the instance into returning False forever;
  4. `add_item` swallowed the exit code, so "issue created but never added to the board"
     was unreachable and cards vanished without a line of log.
  5. the ISSUE writes did the same: `close_ticket`, `comment` and `update_body` called `gh`,
     ignored the exit code and returned None, so a write that never happened was
     indistinguishable — to every caller and every guard above them — from one that landed.
     The last section pins the whole family, not the three that were caught.
"""

from __future__ import annotations

import json
import logging
import subprocess

import pytest

from openfactory.adapters.tracker.github import GitHubIssuesTracker
from openfactory.adapters.tracker.github_project import GitHubProjectBoard
from openfactory.contracts import JobState

_GRAPHQL_ITEMS = json.dumps({
    "data": {"organization": {"projectV2": {"items": {
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "nodes": [{"id": "ITEM7", "content": {"number": 7},
                   "fieldValueByName": {"name": "Backlog"}}],
    }}}}
})

_FIELDS = json.dumps({"fields": [
    {"name": "Title", "id": "F0"},
    {"name": "Status", "id": "FID", "options": [
        {"name": "Backlog", "id": "OPT_BACKLOG"},
        {"name": "TO-DO", "id": "OPT_TODO"},
        {"name": "In progress", "id": "OPT_PROG"},
        {"name": "In review", "id": "OPT_REVIEW"},
        {"name": "Done", "id": "OPT_DONE"},
    ]},
]})

#: most specific marker first — "field-list" must win over any looser match, and every GraphQL
#: DOCUMENT must win over the bare "api graphql" that reads the board. The writes stopped being
#: `gh project item-edit` / `item-add` when a personal-account board proved unable to use them
#: (they type the `--owner` login and demand `read:org`), so the markers are the mutations' own
#: names — which is also what the assertions below match on.
_SCRIPT = [
    ("field-list", _FIELDS),
    ("project view", json.dumps({"id": "PID"})),
    ("repository(owner:",
     json.dumps({"data": {"repository": {"issue": {"id": "ISSUE_NODE_7"}}}})),
    ("addProjectV2ItemById",
     json.dumps({"data": {"addProjectV2ItemById": {"item": {"id": "ITEM7"}}}})),
    ("updateProjectV2ItemFieldValue",
     json.dumps({"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "ITEM7"}}}})),
    ("api graphql", _GRAPHQL_ITEMS),
    ("issue view", json.dumps({"labels": []})),
    ("issue create", "https://github.com/o/r/issues/12\n"),
]


class FakeGH:
    """Answers `subprocess.run(["gh", ...])` from a script, recording argv + env per call.
    Failure markers exit 1 with a non-rate-limit stderr (so `_gh`'s backoff never sleeps)."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.envs: list[dict] = []
        self.stdins: list[str | None] = []
        self.fail: set[str] = set()

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        self.envs.append(dict(kw.get("env") or {}))
        self.stdins.append(kw.get("input"))
        joined = " ".join(argv)
        for marker in self.fail:
            if marker in joined:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr=f"boom: {marker}")
        for marker, stdout in _SCRIPT:
            if marker in joined:
                return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def matching(self, *needles: str) -> list[tuple[list[str], dict]]:
        return [(argv, env) for argv, env in zip(self.calls, self.envs, strict=True)
                if all(n in " ".join(argv) for n in needles)]


@pytest.fixture
def gh(monkeypatch) -> FakeGH:
    fake = FakeGH()
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


def _tracker(**kw) -> GitHubIssuesTracker:
    return GitHubIssuesTracker("o/r", board_owner="org", board_number="6", **kw)


# ── 1. the token is resolved when the write happens, not when the tracker was built ─────────


def test_board_writes_use_the_token_minted_at_call_time_not_at_construction(gh):
    """A multi-pass job routinely outlives the ~1h App token. The provider re-mints; the board
    must ask it at every gh call — a token string frozen at construction means every board move
    after expiry runs with dead credentials and fails silently."""
    current = {"tok": "tok-old"}
    tracker = _tracker(token_provider=lambda: current["tok"])
    current["tok"] = "tok-fresh"  # the provider re-minted after the 1h expiry

    tracker.set_state("#7", JobState.REVIEWING)

    edits = gh.matching("updateProjectV2ItemFieldValue")
    assert edits, f"no board move was attempted; calls: {[c[:3] for c in gh.calls]}"
    stale = [argv[:3] for argv, env in zip(gh.calls, gh.envs, strict=True)
             if env.get("GH_TOKEN") == "tok-old"]
    assert not stale, f"these gh calls ran with the construction-time token: {stale}"
    assert all(env.get("GH_TOKEN") == "tok-fresh" for _, env in edits)


def test_the_board_never_invokes_the_provider_at_construction(gh):
    """Construction must not spend a mint: the freshness guarantee is structural (resolve at
    use), not a lucky early call."""
    calls = {"n": 0}

    def provider():
        calls["n"] += 1
        return "tok"

    _tracker(token_provider=provider)
    assert calls["n"] == 0, "the tracker evaluated the token provider at construction"


# ── 2. a refused move is logged and the openfactory:<state> label carries the truth ────────────────


def test_a_refused_board_move_is_logged_and_falls_back_to_the_state_label(gh, caplog):
    """A ticket that silently never moves is indistinguishable from a poller that stopped.
    When the configured board refuses the write, set_state must say so (stable SDLC_ line)
    and reflect the state as the openfactory:<state> label instead of discarding the bool."""
    gh.fail.add("updateProjectV2ItemFieldValue")
    tracker = _tracker(token="t")

    with caplog.at_level(logging.ERROR):
        tracker.set_state("#7", JobState.REVIEWING)

    assert "OPENFACTORY_BOARD_MOVE_FAILED" in caplog.text
    label = f"openfactory:{JobState.REVIEWING.value}"
    fallback = gh.matching("issue edit", "--add-label", label)
    assert fallback, f"the {label} label fallback never ran; calls: {[c[:4] for c in gh.calls]}"


def test_a_successful_move_stays_quiet_and_needs_no_label(gh, caplog):
    tracker = _tracker(token="t")
    with caplog.at_level(logging.WARNING):
        tracker.set_state("#7", JobState.REVIEWING)
    assert "OPENFACTORY_BOARD_MOVE_FAILED" not in caplog.text
    assert not gh.matching("issue edit", "--add-label", "openfactory:")
    edits = gh.matching("updateProjectV2ItemFieldValue")
    assert edits and "OPT_REVIEW" in " ".join(edits[0][0])  # the real ids reached the mutation


# ── 3. one failed meta fetch must not poison the instance forever ───────────────────────────


def test_a_failed_meta_fetch_does_not_poison_the_board_for_later_calls(gh, caplog):
    """`_project_id` assigned before the field-list fetch meant one rate-limit blip left the
    instance permanently half-initialised: every later set_column returned False with no
    re-fetch. The split loop and promote share ONE instance across a batch — children 2..N
    must recover the moment GitHub does."""
    board = GitHubProjectBoard("org", "6", token="t")

    gh.fail.add("field-list")
    with pytest.raises(RuntimeError):
        board.set_column(issue="7", issue_url="https://github.com/o/r/issues/7",
                         name="TO-DO")

    gh.fail.clear()  # the secondary limit cleared seconds later
    with caplog.at_level(logging.ERROR):
        moved = board.set_column(issue="7", issue_url="https://github.com/o/r/issues/7",
                                 name="TO-DO")
    assert moved is True, "the instance stayed poisoned after the meta fetch recovered"
    edits = gh.matching("updateProjectV2ItemFieldValue")
    # the REAL ids reached the mutation — they travel as `-f project=PID` now, so the check is
    # on the argv as a whole rather than on bare elements
    argv = " ".join(edits[-1][0]) if edits else ""
    assert edits and all(f"={i}" in argv for i in ("PID", "FID", "OPT_TODO"))


def test_a_move_refused_for_a_missing_column_says_so(gh, caplog):
    """Every False out of set_column carries a WHY in the log — a bare False upstream told
    nobody anything."""
    board = GitHubProjectBoard("org", "6", token="t")
    with caplog.at_level(logging.ERROR):
        moved = board.set_column(issue="7", issue_url="https://github.com/o/r/issues/7",
                                 name="No Such Column")
    assert moved is False
    assert "OPENFACTORY_BOARD_MOVE_FAILED" in caplog.text


# ── 4. a card that never reached the board is a reported failure, not a silence ─────────────


def test_add_item_raises_on_a_nonzero_exit_instead_of_swallowing_it(gh):
    """For split children with split_to_todo:false this add is the ONLY board write — the
    human is told 'in Backlog, drag when ready' and the card must actually be there."""
    board = GitHubProjectBoard("org", "6", token="t")
    gh.fail.add("addProjectV2ItemById")
    with pytest.raises(RuntimeError, match="failed"):
        board.add_item(issue_url="https://github.com/o/r/issues/12")


def test_create_ticket_reports_a_card_that_never_reached_the_board(gh, caplog):
    """The issue still exists (the ref is returned), but the failure is loud: the warning path
    in create_ticket was dead code while add_item swallowed the exit code."""
    tracker = _tracker(token="t")
    gh.fail.add("addProjectV2ItemById")
    with caplog.at_level(logging.ERROR):
        ref = tracker.create_ticket(title="t", body="b")
    assert ref == "#12"
    assert "OPENFACTORY_BOARD_ADD_FAILED" in caplog.text


# ── 5. no write on this adapter may return quietly having done nothing ──────────────────────

#: EVERY method that changes something, not the three the review named. `gh` reports failure in
#: its exit code and nowhere else, so a method that forgets to read it answers `None` to a write
#: that never happened — and `None` is this contract's word for "it landed". The table is the
#: audit: a write added later and left out of it is a write nobody checked.
_WRITES = [
    ("comment", lambda t: t.comment("#7", "o time foi avisado"), "issue comment"),
    ("update_body", lambda t: t.update_body("#7", "corpo novo"), "issue edit"),
    ("close_ticket", lambda t: t.close_ticket("#7", "fechado em favor do #288"), "issue close"),
    ("set_assignees", lambda t: t.set_assignees("#7", ["alguem"]), "issue edit"),
    ("add_label", lambda t: t.add_label("#7", "sdlc:working"), "issue edit"),
    ("remove_label", lambda t: t.remove_label("#7", "sdlc:working"), "issue edit"),
    ("create_ticket", lambda t: t.create_ticket(title="t", body="b"), "issue create"),
]


@pytest.mark.parametrize(("name", "call", "marker"), _WRITES, ids=[w[0] for w in _WRITES])
def test_a_write_the_forge_refused_never_returns_as_if_it_had_landed(gh, name, call, marker):
    """The one that shipped: `close_ticket` swallowed the exit code, so `_WatchedWrites` saw a
    clean write, the client was told "fechei o #511 em favor do #288" while #511 was still open,
    and the "uma escrita falhou" impediment was closed by the write that never happened."""
    gh.fail.add(marker)
    tracker = _tracker(token="t")

    with pytest.raises(RuntimeError):
        call(tracker)


def test_a_search_that_could_not_run_is_not_the_answer_no_such_ticket(gh):
    """GitHub's search carries its own, much lower limit than issue creation, so this failing
    while `issue create` still works is the ordinary case. Answering None to it makes every
    caller that asks "does this already exist?" file the duplicate it was asking about."""
    gh.fail.add("issue list")
    tracker = _tracker(token="t")

    with pytest.raises(RuntimeError):
        tracker.find_ticket(title="Conferência de notas de entrada")


def test_a_read_of_the_assignees_that_failed_is_not_an_unassigned_ticket(gh):
    """`[]` decides who a parked ticket goes back to — and "nobody" is exactly the state that
    leaves it with no owner, which is the silent forever-wait this platform exists to end."""
    gh.fail.add("issue view")
    tracker = _tracker(token="t")

    with pytest.raises(RuntimeError):
        tracker.assignees("#7")


def test_the_state_label_fallback_creates_the_label_before_it_needs_it(gh):
    """`gh issue edit --add-label` fails outright on a label the repo has never seen — which is
    every repo the first time a job transitions. The carrier of truth for a board that could not
    carry it may not fail the way the board just did."""
    tracker = GitHubIssuesTracker("o/r")   # no board: the label IS the state

    tracker.set_state("#7", JobState.REVIEWING)

    created = gh.matching("label create", f"openfactory:{JobState.REVIEWING.value}")
    edited = gh.matching("issue edit", "--add-label", f"openfactory:{JobState.REVIEWING.value}")
    assert created and edited, f"calls: {[c[:4] for c in gh.calls]}"
    assert gh.calls.index(created[0][0]) < gh.calls.index(edited[0][0])


def test_the_state_label_sweep_keeps_exactly_one_of_OURS(gh, monkeypatch):
    """The label IS the state when there is no board, so a stale `openfactory:<state>` left from
    an earlier transition is precisely the false-state confusion the label exists to remove. The
    sweep removes every state label of ours that is not the current one — and nothing that is
    not ours."""
    import sys
    stale_view = json.dumps({"labels": [{"name": "openfactory:implementing"},
                                        {"name": "openfactory:planning"},
                                        {"name": "enhancement"}]})
    monkeypatch.setattr(sys.modules[__name__], "_SCRIPT",
                        [("issue view", stale_view), *_SCRIPT])
    tracker = GitHubIssuesTracker("o/r")   # no board: the label IS the state

    tracker.set_state("#7", JobState.REVIEWING)

    edit = gh.matching("issue edit", "--add-label", f"openfactory:{JobState.REVIEWING.value}")
    assert edit, f"calls: {[c[:4] for c in gh.calls]}"
    argv = " ".join(edit[0][0])
    assert "--remove-label openfactory:implementing" in argv, argv
    assert "--remove-label openfactory:planning" in argv, argv
    assert "--remove-label enhancement" not in argv, (
        "the sweep may only touch OUR labels — a client's own label is not ours to remove")


def test_a_state_the_tracker_refused_to_record_is_never_reported_as_recorded(gh):
    """A job that believes a ticket moved while nothing on it says so is a card the poller can
    pick up twice — the state has to be somewhere, or the caller has to hear about it."""
    gh.fail.add("issue edit")
    tracker = GitHubIssuesTracker("o/r")

    with pytest.raises(RuntimeError):
        tracker.set_state("#7", JobState.REVIEWING)


def test_the_body_still_goes_over_stdin_and_through_the_rate_limit_retry(gh):
    """A requirement runs to thousands of characters with quotes, backticks and newlines: on the
    command line it gets truncated at the first surprising byte, or read as a flag. It was also
    the one destructive write bypassing `_gh`, so it alone had no secondary-limit backoff."""
    tracker = _tracker(token="t")
    body = "## Objective\n\n`crase` e \"aspas\" — e uma --flag\n"

    tracker.update_body("#7", body)

    sent = [(argv, stdin) for argv, stdin in zip(gh.calls, gh.stdins, strict=True)
            if "--body-file" in argv]
    assert sent and sent[0][1] == body
    assert body not in " ".join(sent[0][0]), "the body was passed as an argument"


# ── a courtesy comment must never undo the act it describes ──────────────────────────────────────

def test_a_refused_comment_never_aborts_the_park():
    """THE REGRESSION THE SECOND REVIEW CAUGHT, minutes after the fix that caused it.

    Making the tracker RAISE on a refused write is right — a write that did not happen must not
    look like one that did. But `_hold` opens by commenting the reason, and `_hold` is this
    platform's no-silent-wait exit: it returns the ticket to its owner, sets the state and raises
    the alarm. With `comment` raising and the call bare, a forge that refused one comment stopped
    a job from parking at all — the ticket never went back to anybody, and nothing said so.

    The act stands and the loss is loud. Losing the comment costs an audit line; losing the park
    costs a job nobody knows is stuck.
    """
    import logging

    from openfactory.orchestrator.machine import JobRunner

    said: list[str] = []

    class _Refuses:
        def comment(self, ref, body):
            said.append(body)
            raise RuntimeError("the forge refused the comment")

    runner = JobRunner.__new__(JobRunner)
    runner.tracker = _Refuses()

    logger = logging.getLogger("openfactory.orchestrator")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logger.addHandler(handler)
    try:
        runner._say_on_ticket("#412", "🤖 on hold — validations failed")
    finally:
        logger.removeHandler(handler)

    assert said, "the comment was never attempted"
    assert any("OPENFACTORY_TICKET_COMMENT_LOST" in r.getMessage() for r in records), (
        "the audit line vanished with no trace — a tracker refusing every comment for a week "
        "would look exactly like a quiet week")


# ── and a lookup that raises must not turn a half-done split into a finished one ────────────────

class _HalfSplit:
    """The forge one pass after an interruption: two of the four children exist and are linked.

    The shape a throttled `find_ticket` leaves behind — it raises (above), the activity dies
    mid-loop, and Temporal retries with the parent already carrying part of its set."""

    def __init__(self, *, already: int, of: int) -> None:
        from openfactory.runtime.temporal.activities import _child_title

        self.created: list[str] = []
        self.closed: tuple[str, str] | None = None
        self.linked: list[tuple[str, str]] = []
        self.parent_title = "Plan 92 — hardening"
        self._by_title = {_child_title(self.parent_title, i, "#37"): f"#{101 + i}"
                          for i in range(already)}
        self._children = [f"#{101 + i}" for i in range(already)]
        self._of = of

    def get_ticket(self, ref):
        from openfactory.contracts import Ticket

        return Ticket(id=ref, title=self.parent_title, objective="x", repo="o/app")

    def find_ticket(self, *, title):
        return self._by_title.get(title)

    def create_ticket(self, *, title, body):
        ref = f"#{101 + len(self._by_title)}"
        self._by_title[title] = ref
        self.created.append(ref)
        return ref

    def set_state(self, ref, state, reason=None, *, needs_person=None):
        pass

    def close_ticket(self, ref, reason, *, delivered=True):
        self.closed = (ref, reason)

    def link_child(self, parent_ref, child_ref):
        self.linked.append((parent_ref, child_ref))
        if child_ref not in self._children:
            self._children.append(child_ref)

    def children_of(self, parent_ref):
        return list(self._children)


def _split(monkeypatch, tracker, children: int):
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import SplitInput

    monkeypatch.setattr(acts, "_tracker_for", lambda project: tracker)
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: object())
    import openfactory.loader
    monkeypatch.setattr(openfactory.loader, "load_manifest",
                        lambda project: type("M", (), {"split_to_todo": True})())
    return acts._do_split(SplitInput(
        project="p", issue="37", reasons="two features",
        children=[{"title": f"part {i}", "objective": "o", "criteria": ["c"]}
                  for i in range(children)]))


def test_a_split_that_stopped_halfway_is_finished_rather_than_reported_done(monkeypatch, caplog):
    """THE COST OF THE FIX ABOVE, one layer up. `find_ticket` raising is right — a search that
    never ran is not the answer "no such ticket" — but the split's decision-idempotency asked "does
    the parent have ANY native child?" and read yes as "the split was taken". So the retry after a
    throttled search returned `already split into #101, #102`, marked the panel done, and left
    children three and four uncreated and the parent open, for ever: work that vanishes behind a
    success. The record is compared against the DECISION, not against zero."""
    fake = _HalfSplit(already=2, of=4)

    with caplog.at_level(logging.WARNING):
        out = _split(monkeypatch, fake, children=4)

    assert fake.created == ["#103", "#104"], "the interrupted split was never finished"
    assert out == "split into #101, #102, #103, #104", out
    assert fake.closed is not None and fake.closed[0] == "#37", "the parent stayed open"
    assert "OPENFACTORY_SPLIT_RESUMED" in caplog.text


def test_a_split_whose_children_all_exist_still_creates_nothing(monkeypatch):
    """The other half of the same comparison: a complete set is the decision already taken, and
    re-running it must not file a second one nor comment on the parent twice."""
    fake = _HalfSplit(already=2, of=2)

    out = _split(monkeypatch, fake, children=2)

    assert fake.created == [] and fake.closed is None
    assert out == "already split into #101, #102"


def test_a_forge_that_refuses_EVERYTHING_still_lets_a_job_park():
    """THE INVARIANT, replacing an AST guard of mine that had a hole in it.

    My first attempt walked the source for bare `tracker.comment` calls and counted anything inside
    a `try` as safe — including a `try/finally`, which swallows nothing. It also could not see the
    write one layer down: `tracker.set_state(..., reason=…)` ENDS by commenting, so guarding
    `_hold`'s own comment left the park aborting three lines later, and the guard reported zero.

    Structure was the wrong thing to assert. What has to be true is behavioural and cannot be
    gamed: `_hold` is this platform's no-silent-wait exit, and on a forge refusing every single
    write the job must still reach ON_HOLD and a human must still be told. Everything else on that
    path — the explanation, the handover, the label — is a courtesy that may be lost loudly.
    """
    from openfactory.contracts import JobState, Ticket
    from openfactory.orchestrator.machine import JobRunner

    class _RefusesEverything:
        """Not a stub: every method a forge exposes, all of them failing, which is what a revoked
        token or an exhausted primary rate limit actually looks like."""

        def __getattr__(self, name):
            def _boom(*a, **kw):
                raise RuntimeError(f"the forge refused {name}")
            return _boom

    told: list[tuple[str, str]] = []

    class _Notifier:
        def notify(self, *, message, level="info"):
            told.append((level, message))

    runner = JobRunner.__new__(JobRunner)
    runner.tracker = _RefusesEverything()
    runner.notifier = _Notifier()
    runner.bot = type("B", (), {"login": "bot"})()
    runner.events = type("E", (), {"emit": lambda self, ev: None})()
    runner._agent_runs = []

    ticket = Ticket(id="#412", title="validações do fecho", objective="que o mês feche",
                    repo="AcmeCorp/acme-books")
    result = runner._hold(ticket, "alice", "validations failed", JobState.ON_HOLD)

    assert result.state is JobState.ON_HOLD, "the job did not park on a forge that refuses writes"
    assert result.ticket_id == "#412"
    assert any(level == "action_required" for level, _ in told), (
        "nobody was told — a job stuck with the panel still showing it running is the exact "
        "silent wait this exit exists to prevent")


def test_no_comment_in_the_orchestrator_can_abort_what_it_describes():
    """A GUARD, not a case. Four bare calls in the job machine and four in the promotion runner
    became able to abort their own act the moment the adapter learned to raise — and the fix's
    own justification ("every caller that wants it already writes the try") was false. The next
    `comment` somebody adds must go through the helper or its own try, and this is what says so."""
    import ast
    from pathlib import Path

    bare: list[str] = []
    for path in (Path("openfactory/orchestrator/machine.py"), Path("openfactory/orchestrator/promotion.py")):
        tree = ast.parse(path.read_text())
        # ONLY a `try` that actually HANDLES the failure counts. The first version accepted any
        # `ast.Try` ancestor, so a `try/finally` — which swallows nothing — read as protected, and
        # the guard reported zero while the park was still aborting.
        guarded = {inner.lineno for node in ast.walk(tree) if isinstance(node, ast.Try)
                   and node.handlers
                   for inner in node.body
                   for inner2 in ast.walk(inner)
                   if isinstance(inner2, ast.Call)
                   and getattr(inner2.func, "attr", "") == "comment"
                   for inner in [inner2]}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "comment" \
                    and node.lineno not in guarded:
                bare.append(f"{path.name}:{node.lineno}")

    assert not bare, (
        "these comments can abort the act they describe — route them through `_say_on_ticket` or "
        "give them their own `try`:\n  " + "\n  ".join(bare))
