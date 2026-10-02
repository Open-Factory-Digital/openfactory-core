"""#330 — what people wrote on the pull request reaches the adjust pass, without being retyped.

THE GAP. People read the pull request and comment on it, attached to the lines they are about.
Nothing could read those comments: `adjust` carried a person's own typing, capped at 2,000
characters, so the supported way to act on a thread was to read it, compress it into a paragraph,
and paste it back into the platform that is already connected to the forge the thread lives in.

WHAT IS PROVEN HERE:

  the forge     `review_comments_of` answers a list or a reason, never an empty list for "could
                not look"; the GitHub and Azure DevOps rows list only what still stands and never
                the platform's own; a row that keeps no comments is refused by name
  the brief     the comments, in order, as data, bounded, with what was left out counted
  the pass      the worker reads them when the pass starts, says on the pull request which ones it
                took, and launches nothing when none stands
  the verb      `address` reads the pull request before it answers the gate, and refuses by name
  the job       `address` is the adjust pass, on the real `JobWorkflow`, with its words from the
                forge and the same budget
  the surfaces  offered where the forge row can list comments, and nowhere else
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_the_merge_gate_is_heard_on_every_path as gate
from gate_answers import answer_merge_gate
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from openfactory.adapters.forge.base import CommentsNotListed, ReviewComment, review_comments_of
from openfactory.contracts import JobState, RunResult
from openfactory.review import threads
from openfactory.runtime.temporal.io import REVIEW_THREAD, AdjustInput
from openfactory.runtime.temporal.workflow import JobWorkflow

ROOT = Path(__file__).resolve().parents[1]
PR = "https://github.com/acme/shop/pull/7"


# ═══ the forge: a list, or why not ══════════════════════════════════════════════════════════════

def test_a_row_that_keeps_no_comments_is_answered_by_name_not_with_an_empty_list():
    said = review_comments_of(object(), PR)
    assert isinstance(said, CommentsNotListed) and "keeps no review comments" in str(said)


def test_a_read_that_failed_is_not_an_empty_listing():
    class _Down:
        def review_comments(self, *, pr):
            raise OSError("connection reset")

    said = review_comments_of(_Down(), PR)
    assert isinstance(said, CommentsNotListed) and "connection reset" in str(said)


def test_a_row_that_knows_why_is_handed_on_and_a_double_is_not_an_answer():
    class _Knows:
        def review_comments(self, *, pr):
            raise CommentsNotListed("this vendor hides threads from the bot")

    class _Double:
        def review_comments(self, *, pr):
            return SimpleNamespace()

    assert str(review_comments_of(_Knows(), PR)) == "this vendor hides threads from the bot"
    assert isinstance(review_comments_of(_Double(), PR), CommentsNotListed)


def test_the_local_forge_keeps_no_comments_from_people(tmp_path):
    from openfactory.adapters.forge.local import LocalForge

    forge = LocalForge("p", str(tmp_path), db_path=str(tmp_path / "board.db"))
    assert isinstance(review_comments_of(forge, "1"), CommentsNotListed)


# ── GitHub ──────────────────────────────────────────────────────────────────────────────────────

def _thread(*comments, resolved=False, path="app/cart.py", line=12):
    return {"isResolved": resolved, "path": path, "line": line,
            "comments": {"nodes": list(comments)}}


def _c(who, body, *, mine=False, url=""):
    return {"author": {"login": who}, "body": body, "url": url or f"{PR}#{who}",
            "viewerDidAuthor": mine}


def _review(who, state, body="", *, mine=False):
    return {"author": {"login": who}, "body": body, "state": state, "url": f"{PR}#r-{who}",
            "viewerDidAuthor": mine}


def _github(monkeypatch, threads_, reviews, *, rc=0):
    from openfactory.adapters.forge.github import GitHubForge

    forge = GitHubForge("acme/shop", token="t")
    calls: list[list[str]] = []

    def gh(args, timeout=120):
        calls.append(args)
        doc = {"data": {"repository": {"pullRequest": {
            "reviewThreads": {"nodes": threads_}, "reviews": {"nodes": reviews}}}}}
        return SimpleNamespace(returncode=rc, stdout=json.dumps(doc) if rc == 0 else "",
                               stderr="" if rc == 0 else "HTTP 403: Resource not accessible")

    monkeypatch.setattr(forge, "_gh", gh)
    forge.calls = calls
    return forge


def test_github_lists_the_unresolved_threads_and_never_the_platforms_own(monkeypatch):
    forge = _github(monkeypatch, [
        _thread(_c("ana", "rename `total` to `subtotal`"), _c("bot", "noted", mine=True)),
        _thread(_c("rui", "already fixed"), resolved=True),
        _thread(_c("ana", "   ")),
    ], [])

    got = forge.review_comments(pr=PR)

    assert got == [ReviewComment(author="ana", body="rename `total` to `subtotal`",
                                 path="app/cart.py", line=12, url=f"{PR}#ana")]
    (args,) = forge.calls
    assert args[:2] == ["api", "graphql"] and "number=7" in args and "owner=acme" in args


def test_github_carries_a_request_for_changes_until_the_same_person_withdraws_it(monkeypatch):
    standing = _github(monkeypatch, [], [
        _review("ana", "CHANGES_REQUESTED", "the empty cart is not handled"),
        _review("rui", "CHANGES_REQUESTED", "needs a test"),
        _review("rui", "APPROVED"),                        # rui withdrew theirs
        _review("eva", "COMMENTED", "nice"),               # no state says it was answered
        _review("bot", "CHANGES_REQUESTED", "x", mine=True),
    ])
    assert [(c.author, c.body, c.path) for c in standing.review_comments(pr=PR)] == [
        ("ana", "the empty cart is not handled", "")]


def test_github_that_cannot_answer_is_said_with_its_own_words(monkeypatch):
    forge = _github(monkeypatch, [], [], rc=1)
    with pytest.raises(CommentsNotListed, match="403"):
        forge.review_comments(pr=PR)


# ── Azure DevOps ────────────────────────────────────────────────────────────────────────────────

class _AzureThreads:
    def __init__(self, threads_):
        self.threads = threads_

    def call(self, method, path, body=None, **_kw):
        if path == "connectionData":
            return {"authenticatedUser": {"id": "the-factory"}}
        if path == "git/pullrequests/7":
            return {"pullRequestId": 7, "repository": {"name": "shop-api"}}
        if path == "git/repositories/shop-api/pullrequests/7/threads":
            return {"value": self.threads}
        raise AssertionError(f"not recorded: {method} {path}")


def _ado(id_, status, *comments, path="/src/cart.ts", line=40):
    return {"id": id_, "status": status, "isDeleted": False,
            "threadContext": {"filePath": path, "rightFileStart": {"line": line}},
            "comments": list(comments)}


def _say(who, text, kind="text"):
    return {"author": {"id": who, "uniqueName": f"{who}@acme.dev"}, "content": text,
            "commentType": kind, "isDeleted": False}


def test_azure_lists_the_active_threads_and_never_the_platforms_own():
    from openfactory.adapters.forge.azure_devops import AzureReposForge

    forge = AzureReposForge("shop-api", organization="acme", project="Shop", token="t")
    forge._client = lambda: _AzureThreads([
        _ado(1, "active", _say("ana", "guard the empty cart"), _say("the-factory", "on it")),
        _ado(2, "fixed", _say("rui", "done already")),
        _ado(3, "pending", _say("eva", "pushed a new iteration", kind="system"),
             _say("eva", "and the totals")),
    ])

    got = forge.review_comments(pr="7")

    assert [(c.author, c.body, c.path, c.line) for c in got] == [
        ("ana@acme.dev", "guard the empty cart", "src/cart.ts", 40),
        ("eva@acme.dev", "and the totals", "src/cart.ts", 40)]
    assert got[0].url.endswith("/pullrequest/7?discussionId=1")


# ═══ the brief: data, in order, bounded ═════════════════════════════════════════════════════════

def _comments(n, size=40):
    return [ReviewComment(author=f"p{i}", body="x" * size, path="a.py", line=i)
            for i in range(1, n + 1)]


def test_the_brief_carries_each_comment_with_who_and_where():
    carried = threads.brief_of([
        ReviewComment(author="ana", body="rename it", path="app/cart.py", line=12),
        ReviewComment(author="rui", body="needs a test"),
    ])
    assert carried.left_out == 0 and len(carried.carried) == 2
    assert "Comment 1, by ana on app/cart.py line 12:\nrename it" in carried.words
    assert "Comment 2, by rui on the pull request:\nneeds a test" in carried.words


def test_the_brief_stops_where_one_pass_stops_and_counts_the_rest():
    carried = threads.brief_of(_comments(threads.MAX_COMMENTS + 5))
    assert len(carried.carried) == threads.MAX_COMMENTS and carried.left_out == 5
    assert "5 more were not carried" in carried.words

    by_size = threads.brief_of(_comments(10, size=threads.MAX_ONE))
    assert len(by_size.words) <= threads.MAX_CHARS + 200 and by_size.left_out > 0


def test_one_long_comment_cannot_crowd_out_the_others():
    carried = threads.brief_of([ReviewComment(author="log", body="y" * 50000),
                                ReviewComment(author="ana", body="the real request")])
    assert [c.author for c in carried.carried] == ["log", "ana"]
    assert "cut here" in carried.words


def test_the_note_on_the_pull_request_says_what_the_pass_took():
    carried = threads.brief_of(_comments(threads.MAX_COMMENTS + 2))
    note = threads.what_was_carried(carried, by="ana", pass_number=2)
    assert "ana asked for the review comments to be addressed. Adjust pass 2 carries 30" in note
    assert "- p1 on a.py line 1" in note and "2 more were not carried" in note
    assert "written after this note is not in this pass" in note


# ═══ the pass: read when it starts, said on the pull request ════════════════════════════════════

class _Forge:
    def __init__(self, found):
        self.found, self.said = found, []

    def review_comments(self, *, pr):
        if isinstance(self.found, Exception):
            raise self.found
        return self.found

    def review_pr(self, *, pr, event, body):
        self.said.append((pr, event, body))


def _the_pass(monkeypatch, found):
    from openfactory.runtime.temporal import activities as acts

    forge = _Forge(found)
    ran: list[str] = []
    monkeypatch.setattr(acts, "_forge_for", lambda project: forge)
    monkeypatch.setattr(acts, "ProjectRegistry", lambda: SimpleNamespace(get=lambda name: name))
    monkeypatch.setattr(acts, "_run_ci_repair", lambda inp, run_id=None, ci_log=None: (
        ran.append(ci_log), RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN))[1])
    got = acts._run_adjust(AdjustInput(project="shop", issue="7", pr_url=PR, attempt=2,
                                       source=REVIEW_THREAD, by="ana"))
    return got, forge, ran


def test_the_pass_hands_the_agent_the_comments_and_says_first_which_it_took(monkeypatch):
    got, forge, ran = _the_pass(monkeypatch, [
        ReviewComment(author="rui", body="guard the empty cart", path="cart.py", line=9)])

    (words,) = ran
    assert "guard the empty cart" in words and "by rui on cart.py line 9" in words
    ((pr, event, note),) = forge.said
    assert (pr, event) == (PR, "comment") and "Adjust pass 2 carries 1" in note
    assert got.state is JobState.PR_OPEN


@pytest.mark.parametrize("found, why", [
    ([], "every thread is resolved"),
    (CommentsNotListed("this vendor hides threads"), "this vendor hides threads"),
])
def test_nothing_standing_launches_nothing_and_says_so_on_the_pull_request(monkeypatch, found,
                                                                           why):
    got, forge, ran = _the_pass(monkeypatch, found)

    assert ran == [], "an agent was launched with nothing to act on"
    assert got.state is JobState.ON_HOLD and got.merge_refused and got.code_changed is False
    assert why in got.note
    ((_, _, note),) = forge.said
    assert "Adjust pass 2 did not run" in note and why in note


def test_a_persons_own_words_still_take_the_old_road(monkeypatch):
    from openfactory.runtime.temporal import activities as acts

    ran: list[str] = []
    monkeypatch.setattr(acts, "_forge_for", lambda project: pytest.fail("the forge was read"))
    monkeypatch.setattr(acts, "_run_ci_repair", lambda inp, run_id=None, ci_log=None: (
        ran.append(ci_log), RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN))[1])
    acts._run_adjust(AdjustInput(project="shop", issue="7", pr_url=PR, instruction=" blue "))
    assert ran == ["blue"]


# ═══ the verb: reads the pull request before it answers ═════════════════════════════════════════

def _the_row(monkeypatch, *, waiting, found):
    from openfactory.actions import catalog
    from openfactory.runtime.temporal import view as tv

    answered: list[str] = []

    async def merge_gate_of(client, project, issue):
        return waiting

    async def answer_gate(*, project, issue, by, answer, instruction=""):
        answered.append(answer)
        return {"pr_url": PR}, None

    async def connected():
        return object(), None

    monkeypatch.setattr(catalog, "_project", lambda name: (SimpleNamespace(name=name), None))
    monkeypatch.setattr(catalog, "_connected", connected)
    monkeypatch.setattr(tv, "merge_gate_of", merge_gate_of)
    monkeypatch.setattr(catalog, "_forge_and_manifest", lambda name: (None, None, _Forge(found)))
    monkeypatch.setattr(catalog, "_answer_gate", answer_gate)
    out = asyncio.run(catalog._address(project="shop", issue="7", by="ana"))
    return out, answered


def test_the_verb_answers_the_gate_when_comments_stand(monkeypatch):
    out, answered = _the_row(monkeypatch, waiting={"pr_url": PR},
                             found=[ReviewComment(author="rui", body="x")])
    assert answered == ["address"] and out.ok and "1 review comment standing" in out.message


@pytest.mark.parametrize("waiting, found, said", [
    (None, [], "is not waiting on a merge"),
    ({"pr_url": PR}, [], "nothing people wrote on the pull request still stands"),
    ({"pr_url": PR}, CommentsNotListed("this vendor hides threads"), "this vendor hides threads"),
])
def test_the_verb_refuses_by_name_before_a_pass_is_spent(monkeypatch, waiting, found, said):
    out, answered = _the_row(monkeypatch, waiting=waiting, found=found)
    assert answered == [] and not out.ok and said in out.message


def test_the_engine_hears_address_as_a_merge_gate_answer():
    from openfactory.runtime.temporal import view as tv

    src = (ROOT / "openfactory/runtime/temporal/view.py").read_text()
    assert '("merge", "adjust", "address", "discard", "review")' in src
    with pytest.raises(ValueError):
        asyncio.run(tv.answer_merge_gate(None, "p", "1", answer="addres"))


# ═══ the job: `address` is the adjust pass, with its words from the forge ═══════════════════════

@pytest.fixture
async def env():
    """This file's own ephemeral engine (`test_the_suite_cannot_reach_a_live_engine`)."""
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


_PASSES: list[AdjustInput] = []


@activity.defn(name="adjust_pr")
async def mock_adjust(inp: AdjustInput) -> RunResult:
    _PASSES.append(inp)
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=inp.pr_url,
                     code_changed=True)


@pytest.fixture
def _fresh_gate():
    gate._REPAIRS.clear(), gate._CLOSED.clear(), gate._MERGED.clear()
    gate._HOLD_REPAIR.clear(), gate._HOLD_READ.clear()
    gate._READS[0] = 0
    gate._CI[0], gate._MSTATE[0] = gate.RED, "blocked"
    gate._UPDATES.clear(), gate._AT.clear(), gate._FORCED.clear()
    gate._AUTO[0] = False
    _PASSES.clear()


@pytest.mark.owns_its_engine
async def test_address_is_one_adjust_pass_with_its_words_from_the_forge(env, _fresh_gate):
    async with Worker(env.client, task_queue=gate.TQ, workflows=[JobWorkflow],
                      activities=[*gate.MOCKS, mock_adjust]):
        h = await gate._start(env.client)
        await gate._napping_after_a_repair(h)
        await answer_merge_gate(h, "address", "", "ana")

        async def passed_and_resting():
            g = await h.query(JobWorkflow.awaiting_merge)
            return g if (g and not g.get("working") and _PASSES) else None

        await gate._until("the address pass over and the gate back", passed_and_resting)
        await answer_merge_gate(h, "discard", "", "ana")
        await h.result()

    (one,) = _PASSES
    assert (one.source, one.instruction, one.by, one.attempt) == (REVIEW_THREAD, "", "ana", 1)


# ═══ the surfaces: offered where the forge can list, and nowhere else ═══════════════════════════

def test_only_a_forge_row_that_lists_comments_is_offered_the_verb(tmp_path):
    from openfactory.adapters.forge.registry import lists_review_comments

    github = SimpleNamespace(name="shop", repo_path=str(tmp_path),
                             forge=SimpleNamespace(kind="github", repo="acme/shop", options={}),
                             tracker=SimpleNamespace(kind="github", repo="acme/shop"))
    local = SimpleNamespace(name="shop", repo_path=str(tmp_path),
                            forge=SimpleNamespace(kind="local", repo="", options={}),
                            tracker=SimpleNamespace(kind="local", repo=""))
    assert lists_review_comments(github) is True
    assert lists_review_comments(local) is False
    assert lists_review_comments(SimpleNamespace(forge=None, tracker=None)) is False


def test_the_inbox_and_the_floor_offer_it_only_where_the_server_says():
    app = (ROOT / "openfactory/api/app.py").read_text()
    panel = (ROOT / "openfactory/api/panel.html").read_text()
    view = (ROOT / "openfactory/runtime/temporal/view.py").read_text()
    assert 'if act.get("can_address"):' in app
    assert "a.can_address?" in panel and 'data-k="address"' in panel
    assert '"can_address": _lists_review_comments(' in view
