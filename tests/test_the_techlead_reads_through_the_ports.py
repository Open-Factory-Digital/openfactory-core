"""The tech-lead reads the world through the PORTS, not through `gh` (#91).

WHY THIS CARD EXISTED AT ALL. `techlead/conversation.py` opens by declaring itself the capability
with no channel in it — it was extracted from the Slack bot for exactly that reason. Taking Slack
out left the other half untouched: `github_issue_index` shelled out to `gh issue list`, the
checkout was an f-string ending in `@github.com/<repo>.git`, and both carried the FORGE's
process-wide credential to whatever host the TRACKER happens to live on.

THE SYMPTOM IS A POORER ANSWER, WHICH IS THE SHAPE NOBODY REPORTS. `answer()` never raises, on
purpose, and every evidence read is best-effort, also on purpose. So on the Azure Boards + Azure
Repos deployment that went end-to-end today the tech-lead answered every question with no ticket
state, no fresh titles and no code — confidently, in the same voice, with nothing in any log that
anybody was watching. There is no failing test that shape can produce; only a guard that the read
goes somewhere a second vendor can answer.

TWO KINDS OF TEST HERE, and the second kind is the one that would have caught this:

    behaviour       the port is asked, and what comes back reaches the snapshot
    reachability    no `gh` and no `github.com` survives in these two modules, and the functions
                    that resolve a URL or an index are actually CALLED by the ones that answer

Each guard below was verified by MUTATION — the defect put back, the named test watched to fail,
the defect removed again. A guard seen only green proves the code is green today.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess

import pytest

from openfactory.adapters.tracker.base import TicketComment
from openfactory.contracts import Ticket
from openfactory.contracts.project import Project, ProviderRef
from openfactory.techlead import conversation, diagnosis

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULES = [ROOT / "openfactory" / "techlead" / "conversation.py",
           ROOT / "openfactory" / "techlead" / "diagnosis.py"]


def _github_project(**tracker_options) -> Project:
    return Project(
        name="books", repo_path="/tmp/books",
        tracker=ProviderRef(kind="github", repo="o/r", options=tracker_options),
    )


def _azure_project(*, names_its_credential: bool = True) -> Project:
    """The deployment the card is about: Azure Boards + Azure Repos, zero GitHub.

    `names_its_credential=False` is the row that does NOT set `token_env` — deliberately supported,
    because `forge_token_for` then hands back the DEPLOYMENT's own token, which is right for the
    six GitHub projects that exist and is a github.com PAT here. That is the case where the adapter
    mints its own credential and the caller never holds it."""
    creds = {"token_env": "AZURE_DEVOPS_PAT"} if names_its_credential else {}
    return Project(
        name="fx-ado", repo_path="/tmp/fx-ado",
        tracker=ProviderRef(kind="azure_devops", repo="factory",
                            options={"organization": "acme-ai", **creds}),
        forge=ProviderRef(kind="azure_devops", repo="fx-ado",
                          options={"organization": "acme-ai",
                                   "project": "factory", **creds}),
    )


class _Tracker:
    """A TrackerAdapter double that answers the REAL contract: `get_ticket` returns a `Ticket`,
    `comments` returns `list[TicketComment] | None`.

    It invents no field. `Ticket.state` is the contract's own — added because a `getattr(ticket,
    "state", "open")` guard read its default for ever while every double in the suite made the
    attribute up, which is the trap this class is written to stay out of.

    THE COMMENT SIDE MODELS ALL THREE ANSWERS, because collapsing two of them is the defect the
    consumer is being guarded against and a double that cannot produce the distinction cannot test
    it: `threads={"69": [...]}` is a thread, `threads={"70": None}` is the provider itself saying
    it could not read, `refuse_comments={"71"}` is the call blowing up, and a ref absent from
    `threads` is `[]` — read, and nobody has commented."""

    def __init__(self, tickets: dict[str, tuple[str | None, str]],
                 refuse: set[str] | None = None,
                 threads: dict[str, list | None] | None = None,
                 refuse_comments: set[str] | None = None) -> None:
        self._tickets = tickets
        self._refuse = refuse or set()
        self._threads = threads or {}
        self._refuse_comments = refuse_comments or set()
        self.asked: list[str] = []
        #: `(ref, limit)` per call — the limit matters as much as the ref: a consumer that asked
        #: for everything on a ticket a person has been arguing about for a week pastes a month of
        #: thread into a prompt somebody is waiting on.
        self.comments_asked: list[tuple[str, int]] = []

    def get_ticket(self, ref: str) -> Ticket:
        self.asked.append(ref)
        if ref in self._refuse:
            raise RuntimeError(f"the tracker refused {ref}")
        state, title = self._tickets[ref]
        t = Ticket(id=ref, title=title, objective="o", repo="o/r")
        t.state = state  # `str | None` — None is the contract's "the provider was not asked"
        return t

    def comments(self, ref: str, *, limit: int = 0) -> list[TicketComment] | None:
        self.comments_asked.append((ref, limit))
        if ref in self._refuse_comments:
            raise RuntimeError(f"the tracker refused the comments of {ref}")
        found = self._threads.get(ref, [])
        if found is None:
            return None
        # The port's own promise, reproduced rather than assumed: the most recent N, still
        # OLDEST FIRST. A double that handed back the first N would let a consumer that reads the
        # wrong end of a thread pass.
        return found[-limit:] if limit > 0 else list(found)


def _said(author: str, body: str, when: str) -> TicketComment:
    return TicketComment(author=author, body=body, created_at=when)


# ── the ticket index goes through TrackerAdapter ────────────────────────────────────────────────

def test_the_index_reads_the_tracker_port_and_keeps_the_providers_own_ref():
    """`get_ticket`, not `gh issue list`. The key is the ref the caller ASKED with, so a Jira
    deployment (`CONT-412`) indexes at all — the `gh` version keyed by an issue NUMBER, which is
    the one shape a Jira board cannot produce (C-05)."""
    tracker = _Tracker({"69": ("closed", "Plan 88.1 — Spreadsheet import"),
                        "CONT-412": ("open", "Importar planilha")})

    index = conversation.ticket_index(_github_project(), ["69", "CONT-412"], tracker=tracker)

    assert index["69"] == {"state": "closed", "title": "Plan 88.1 — Spreadsheet import"}
    assert index["CONT-412"] == {"state": "open", "title": "Importar planilha"}
    assert sorted(tracker.asked) == ["69", "CONT-412"]


def test_a_ticket_the_tracker_refused_is_ABSENT_never_reported_as_open():
    """THE INVARIANT THE CARD NAMES. A read that failed must not read as an answer: if a refused
    ticket landed in the index as `open`, the snapshot would print a state nobody read, and the
    ORPHANED/resolved rules downstream branch on exactly that word."""
    tracker = _Tracker({"69": ("closed", "done thing")}, refuse={"70"})

    index = conversation.ticket_index(_github_project(), ["69", "70"], tracker=tracker)

    assert "70" not in index
    assert index["69"]["state"] == "closed"


def test_one_ticket_is_read_once_however_many_jobs_carry_it():
    """Several runs of the same ticket are several jobs. Against the old bulk call that cost
    nothing; against a per-ticket port it is one request per duplicate, on every question."""
    tracker = _Tracker({"69": ("open", "t")})

    conversation.ticket_index(_github_project(), ["69", "69", "69", "", None], tracker=tracker)

    assert tracker.asked == ["69"]


def test_the_read_is_capped_and_the_cap_is_said_out_loud(caplog):
    """Past the cap a job renders as UNREADABLE rather than as open — so the bound has to be
    visible, both in the log and (via `ticket_unread`) in the text the model reads."""
    refs = [str(n) for n in range(200)]
    tracker = _Tracker({r: ("open", f"t{r}") for r in refs})

    with caplog.at_level("WARNING"):
        index = conversation.ticket_index(_github_project(), refs, tracker=tracker)

    assert len(index) == conversation._TICKET_READ_CAP
    assert "UNREADABLE" in caplog.text


def test_no_refs_asks_the_tracker_nothing(monkeypatch):
    """An empty floor must not build a tracker, resolve a credential or mint a token. The builder
    is poisoned rather than counted, so the assertion is about the early return and not about a
    spy that could be satisfied by the call simply moving."""
    def _boom(_project):
        raise AssertionError("a tracker was built for a floor with no jobs on it")

    monkeypatch.setattr(conversation, "tracker_for", _boom)

    assert conversation.ticket_index(_github_project(), []) == {}
    assert conversation.ticket_index(_github_project(), ["", None]) == {}


def test_the_tracker_is_built_with_the_TRACKER_axis_credential(monkeypatch):
    """The two axes are independent (ADR-0001). The code this replaced sent `forge_token()` — a
    github.com PAT — at whatever host the tracker lives on, which on Azure DevOps comes back as a
    401 that reads like a revoked credential rather than like the configuration mistake it is."""
    monkeypatch.setenv("OPENFACTORY_TRACKER_TOKEN", "the-tracker-token")
    monkeypatch.setenv("OPENFACTORY_FORGE_TOKEN", "the-forge-token")
    seen: dict = {}

    def _build(project, *, token=None, token_provider=None):
        seen["token"] = token
        return _Tracker({})

    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker", _build)

    assert conversation.tracker_for(_github_project()) is not None
    assert seen["token"] == "the-tracker-token"


def test_a_tracker_that_cannot_be_built_is_a_thinner_answer_not_an_exception(caplog):
    """`answer()` promises never to reply with a traceback, and this is on its hottest read."""
    broken = Project(name="x", repo_path="/tmp/x", tracker=ProviderRef(kind="pivotal-tracker"))

    with caplog.at_level("WARNING"):
        assert conversation.tracker_for(broken) is None

    assert "no tracker for x" in caplog.text


# ── and what could not be read is SAID, not left as a hole ──────────────────────────────────────

def test_an_unreadable_ticket_prints_UNREADABLE_and_triggers_no_verdict():
    """A job with no ticket state must not silently become one the agent reads as open. It must
    also reach NEITHER the ORPHANED nor the 'likely resolved' branch — both are gated on the word
    `closed` precisely so an unknown state cannot fall into them."""
    snap = conversation.state_snapshot([
        {"issue": "70", "state": "failed", "title": "importer", "ticket_unread": True,
         "attention": True},
    ])

    assert "UNREADABLE" in snap and "not 'open'" in snap
    assert "ORPHANED" not in snap and "likely resolved" not in snap


def test_an_unreadable_board_prints_UNREADABLE_rather_than_no_column():
    """`BoardAdapter.columns()` separates 'could not read' from 'nothing on it' and names the three
    bugs that came from collapsing them. `board_index` collapsed it again one layer up while its
    own comment claimed *the caller renders 'board unknown'* — which the caller could not do,
    having been handed `{}`."""
    snap = conversation.state_snapshot([
        {"issue": "416", "state": "needs_refinement", "title": "t", "board_unread": True},
    ])

    assert "board: UNREADABLE" in snap


def test_a_board_that_could_not_be_read_is_None_and_an_absent_board_is_empty(monkeypatch):
    """The two answers a caller must be able to tell apart, from the function that answers them."""
    monkeypatch.setattr("openfactory.adapters.board.build_board", lambda project, **kw: None)
    assert conversation.board_index(_github_project()) == {}, "no board configured is not a failure"

    class _Board:
        def columns(self):
            return None

    monkeypatch.setattr("openfactory.adapters.board.build_board", lambda project, **kw: _Board())
    assert conversation.board_index(_github_project()) is None

    class _Empty:
        def columns(self):
            return {}

    monkeypatch.setattr("openfactory.adapters.board.build_board", lambda project, **kw: _Empty())
    assert conversation.board_index(_github_project()) == {}


# ── the enrichment, end to end, with no Temporal and no network ─────────────────────────────────

@pytest.fixture
def floor(monkeypatch):
    """`gather_jobs` over a stubbed Temporal, so the enrichment below is the real code path."""
    def _use(rows: list[dict]):
        async def _connect():
            return object()

        async def _list_jobs(client, ns, *, limit=50):
            return list(rows)

        monkeypatch.setattr("openfactory.runtime.temporal.view.connect", _connect)
        monkeypatch.setattr("openfactory.runtime.temporal.view.list_jobs", _list_jobs)
        monkeypatch.setattr("openfactory.runtime.temporal.connection.namespace", lambda: "ns")

    return _use


def test_gather_jobs_enriches_from_the_ports_and_marks_what_it_could_not_read(floor, monkeypatch):
    """The whole card in one assertion: the ticket state on each job came from `TrackerAdapter`,
    and the ticket that could not be read says so instead of inheriting a default."""
    floor([{"project": "books", "issue": "69", "state": "failed"},
           {"project": "books", "issue": "70", "state": "running"},
           {"project": "outra", "issue": "99", "state": "running"}])
    tracker = _Tracker({"69": ("closed", "Plan 88.1 — Spreadsheet import")}, refuse={"70"})
    monkeypatch.setattr(conversation, "tracker_for", lambda project: tracker)
    monkeypatch.setattr(conversation, "board_index", lambda project: {"69": "Done"})

    jobs = conversation.gather_jobs(_github_project())

    assert [j["issue"] for j in jobs] == ["69", "70"], "another project's jobs leaked in"
    assert jobs[0]["ticket_state"] == "closed"
    assert jobs[0]["title"] == "Plan 88.1 — Spreadsheet import"
    assert jobs[0]["board"] == "Done"
    assert jobs[1].get("ticket_state") is None and jobs[1]["ticket_unread"] is True
    assert "ORPHANED" in conversation.state_snapshot(jobs)


def test_a_ticket_that_came_back_WITHOUT_a_state_is_unread_too(floor, monkeypatch):
    """`Ticket.state` is `str | None`, and None is the contract's "the provider was not asked".
    The three trackers that exist all fill it, so keying on "did the read succeed" would be right
    today and silently wrong for the fourth — which is the exact history that field's own docstring
    records: a `getattr(ticket, "state", "open")` that answered open for ever. The TITLE still
    lands, because it was read fine."""
    floor([{"project": "books", "issue": "69", "state": "failed"}])
    monkeypatch.setattr(conversation, "tracker_for",
                        lambda project: _Tracker({"69": (None, "a titled ticket")}))
    monkeypatch.setattr(conversation, "board_index", lambda project: {})

    jobs = conversation.gather_jobs(_github_project())

    assert jobs[0]["ticket_unread"] is True
    assert jobs[0]["title"] == "a titled ticket"
    assert "UNREADABLE" in conversation.state_snapshot(jobs)


def test_an_unreadable_board_marks_every_job(floor, monkeypatch):
    floor([{"project": "books", "issue": "69", "state": "failed"}])
    monkeypatch.setattr(conversation, "tracker_for", lambda project: _Tracker({}, refuse={"69"}))
    monkeypatch.setattr(conversation, "board_index", lambda project: None)

    jobs = conversation.gather_jobs(_github_project())

    assert jobs[0]["board_unread"] is True
    assert "board: UNREADABLE" in conversation.state_snapshot(jobs)


def test_enrichment_blowing_up_still_returns_the_jobs(floor, monkeypatch, caplog):
    """`answer()` calls `gather_jobs` OUTSIDE the try that catches agent trouble, so anything
    escaping here answers a person's question with a traceback."""
    floor([{"project": "books", "issue": "69", "state": "failed"}])

    def _boom(project):
        raise RuntimeError("the registry is on fire")

    monkeypatch.setattr(conversation, "tracker_for", _boom)

    with caplog.at_level("WARNING"):
        jobs = conversation.gather_jobs(_github_project())

    assert [j["issue"] for j in jobs] == ["69"]
    assert "answering from Temporal alone" in caplog.text


def test_an_enrichment_that_BLEW_UP_still_says_UNREADABLE_on_every_line(floor, monkeypatch):
    """THE GUARD ABOVE HAD NO OPINION ABOUT WHAT THE MODEL IS THEN TOLD, and that is where the
    hole was: the marking loop sat inside the same try as the reads, so anything escaping either
    of them skipped it and every job rendered with no `ticket:` and no `board:` segment — the exact
    absence this module was rewritten to stop producing, one layer above the two functions that
    were carefully taught not to produce it.

    Reachable rather than theoretical: `board_index` catches only ValueError, on purpose, so a
    `build_board` that raises anything else lands here. Asserted on the SNAPSHOT, because the
    snapshot is the whole of what the model gets to see."""
    floor([{"project": "books", "issue": "69", "state": "failed", "title": "importer"}])

    def _boom(project):
        raise RuntimeError("the registry is on fire")

    monkeypatch.setattr(conversation, "tracker_for", _boom)

    snap = conversation.state_snapshot(conversation.gather_jobs(_github_project()))

    assert "ticket: UNREADABLE" in snap, "a ticket nobody could read rendered as no ticket at all"
    assert "board: UNREADABLE" in snap, "a board nobody could read rendered as no column at all"


def test_a_board_that_EXPLODES_does_not_take_the_ticket_states_with_it(floor, monkeypatch):
    """The board is read AFTER the tickets, so the states already in hand must survive it.

    `board_index` promises `None` for unreadable, but it only converts ValueError; every other
    exception escapes it. Before this, that escape discarded a perfectly good ticket index that had
    already been paid for — N provider round trips thrown away because a different provider
    answered badly."""
    floor([{"project": "books", "issue": "69", "state": "failed"}])
    monkeypatch.setattr(conversation, "tracker_for",
                        lambda project: _Tracker({"69": ("closed", "Plan 88.1")}))

    def _boom(project):
        raise RuntimeError("the board client would not even construct")

    monkeypatch.setattr(conversation, "board_index", _boom)

    jobs = conversation.gather_jobs(_github_project())

    assert jobs[0]["ticket_state"] == "closed", "the ticket read was thrown away by a board failure"
    assert jobs[0]["title"] == "Plan 88.1"
    assert jobs[0]["board_unread"] is True


# ── the comment history, which the port could not answer until #97 ──────────────────────────────

def test_only_PARKED_tickets_cost_a_comment_read():
    """COST, DELIBERATELY BOUNDED. `comments()` is one request per ticket and `answer()` runs with
    a person waiting on the reply, on the credential the poller and every running job share. A
    running job's thread answers a question nobody asked; a parked one is the job somebody is
    asking about. Deduplicated for the same reason the ticket index is — several runs of one
    ticket are several jobs — and asked for exactly `_COMMENTS_PER_TICKET`, because a consumer that
    asks for everything pastes a month of argument into a prompt."""
    tracker = _Tracker({})
    jobs = [{"issue": "69", "state": "failed"},          # parked by state
            {"issue": "70", "state": "running"},         # working — not asked about
            {"issue": "71", "state": "running", "attention": True},  # parked by the flag
            {"issue": "69", "state": "on_hold"},         # the same ticket, a second run
            {"issue": "", "state": "failed"}]            # no ref at all

    threads = conversation.comments_for(_github_project(), jobs, tracker=tracker)

    assert [ref for ref, _ in tracker.comments_asked] == ["69", "71"]
    assert {limit for _, limit in tracker.comments_asked} == {conversation._COMMENTS_PER_TICKET}
    assert set(threads) == {"69", "71"}


def test_a_floor_with_nothing_parked_spends_nothing(monkeypatch):
    """The early return, poisoned rather than counted: on a healthy floor this whole capability
    must cost zero requests and zero credential resolutions."""
    def _boom(_project):
        raise AssertionError("a tracker was built for a floor with nothing parked on it")

    monkeypatch.setattr(conversation, "tracker_for", _boom)

    assert conversation.comments_for(_github_project(), [{"issue": "69", "state": "running"}]) == {}
    assert conversation.comments_for(_github_project(), []) == {}


def test_a_thread_that_could_not_be_read_is_None_and_an_empty_one_is_a_list():
    """THE RULE THAT DECIDES EVERY BRANCH DOWNSTREAM. `None` = I could not read; `[]` = I read, and
    nobody has commented. Three ways to fail — the port answering None, the call raising, and an
    adapter answering some shape this consumer does not recognise — all of which must be None here
    and none of which may become an empty thread."""
    tracker = _Tracker({}, threads={"69": None, "72": "not a list at all"},
                       refuse_comments={"70"})
    jobs = [{"issue": ref, "state": "failed"} for ref in ("69", "70", "71", "72")]

    threads = conversation.comments_for(_github_project(), jobs, tracker=tracker)

    assert threads["69"] is None, "the provider said it could not read; the caller was told empty"
    assert threads["70"] is None, "a refused read became a ticket nobody has commented on"
    assert threads["72"] is None, "an unrecognised shape became an empty thread"
    assert threads["71"] == [], "a ticket that genuinely has no comments lost its fact"


def test_a_project_whose_TRACKER_CANNOT_BE_BUILT_says_UNREADABLE_not_empty(floor, caplog):
    """THE TWIN `diagnosis` GOT AND `conversation` DID NOT.

    `test_a_diagnosis_with_no_tracker_at_all_still_produces_a_situation` covers exactly this shape
    on the other module. Here nothing did: every guard above reaches `comments_for` with a tracker
    (a double, or a `tracker_for` that RAISES), and `tracker_for` never raises in production — it
    catches and answers `None`, which is a different branch and the only one a bad registry row
    actually takes.

    Verified by mutation, because that is the whole point of a twin: `comments_for`'s
    `if tracker is None: return {}` swapped for `return dict.fromkeys(wanted, [])` — a project with
    an unimplementable tracker telling the model that nobody has commented on any of its parked
    tickets — left all 82 guards green. The real `tracker_for` runs here, un-patched, for the same
    reason: patching it away is what hid the branch."""
    floor([{"project": "x", "issue": "69", "state": "failed", "title": "importer"}])
    unbuildable = Project(name="x", repo_path="/tmp/x",
                          tracker=ProviderRef(kind="pivotal-tracker"))

    with caplog.at_level("WARNING"):
        digest = conversation.comment_digest(conversation.gather_jobs(unbuildable))

    assert "UNREADABLE" in digest
    assert "has NO comments" not in digest, (
        "a tracker that could not be BUILT was reported as a ticket nobody has commented on"
    )
    assert "no tracker for x" in caplog.text


def test_the_comment_read_is_capped_and_the_ones_past_it_say_so(caplog):
    """A cap is our decision, so it is the one 'could not read' this module owes an explanation
    for — and the tickets past it are marked UNREAD rather than dropped. Dropped, they would be
    absent from the digest, and a parked ticket the model is shown no thread for is one it reads as
    quiet."""
    jobs = [{"issue": str(n), "state": "failed"} for n in range(20)]
    tracker = _Tracker({})

    with caplog.at_level("WARNING"):
        threads = conversation.comments_for(_github_project(), jobs, tracker=tracker)

    assert len(tracker.comments_asked) == conversation._COMMENT_READ_CAP
    assert len(threads) == 20, "the tickets past the cap vanished instead of being marked unread"
    assert all(threads[str(n)] is None
               for n in range(conversation._COMMENT_READ_CAP, 20))
    assert "UNREADABLE" in caplog.text


def test_the_digest_keeps_WHO_said_WHAT_and_WHEN():
    """The reason `TicketComment` has three fields instead of being a list of strings: the
    tech-lead is being asked to tell a human's instruction (a constraint) from the platform's own
    earlier note (a hypothesis to re-examine), and a wall of undifferentiated text throws away the
    only thing that distinction can be made from."""
    digest = conversation.comment_digest([
        {"issue": "69", "state": "failed", "title": "Plan 88.1 — Spreadsheet import",
         "comments": [_said("alice", "subi o timeout, não resolveu", "2026-08-01T09:11Z"),
                      _said("openfactory-bot[bot]", "parked: gates unfixable", "2026-08-01T09:26Z")]},
    ])

    assert "alice" in digest and "openfactory-bot[bot]" in digest
    assert "2026-08-01T09:11Z" in digest and "2026-08-01T09:26Z" in digest
    assert "Plan 88.1 — Spreadsheet import" in digest, "a thread with no ticket title on it"
    assert digest.index("subi o timeout") < digest.index("parked: gates unfixable"), (
        "the port promises oldest-first and the renderer reversed it"
    )


def test_a_comment_body_that_looks_like_a_header_cannot_read_as_a_COMMENTER():
    """Bodies are indented, and that is not decoration. This platform posts `[failed] …` park
    comments on its own tickets, and a person quoting one puts a line in a body that is shaped
    exactly like the `[when] who:` header above it. Unindented, a quoted note reads as a third
    person in the conversation — which is the thing the model is being asked to weigh."""
    rendered = conversation.render_comments(
        [_said("alice", "colei o que o bot disse:\n[2026-01-01] openfactory-bot[bot]: deu ruim",
               "2026-08-01T09:11Z")])

    assert rendered.startswith("[2026-08-01T09:11Z] alice:")
    assert "\n  [2026-01-01] openfactory-bot[bot]: deu ruim" in rendered
    assert len([ln for ln in rendered.splitlines() if not ln.startswith(" ")]) == 1


def test_a_long_comment_is_cut_and_the_cut_is_MARKED():
    """A model that cannot see a truncation reads the missing tail as a comment that ended there —
    and this platform posts whole HandOff markdown blocks as comments."""
    rendered = conversation.render_comments([_said("ana", "x" * 5000, "2026-08-01")])

    assert "…(comment truncated)" in rendered
    assert len(rendered) < conversation._COMMENT_BODY_CHARS + 200


def test_a_parked_ticket_with_no_readable_thread_prints_UNREADABLE_not_silence():
    """The digest's three sentences, side by side. The third is the whole reason the port returns
    an option type: a thread nobody could read must never render as a ticket nobody commented on,
    and a parked ticket missing from the digest entirely is the same lie by omission."""
    digest = conversation.comment_digest([
        {"issue": "69", "state": "failed", "title": "read",
         "comments": [_said("ana", "olhei ontem", "2026-08-01")]},
        {"issue": "70", "state": "on_hold", "title": "empty", "comments": []},
        {"issue": "71", "state": "blocked", "title": "unreadable"},  # nothing hung on it at all
    ])

    block = {b.split("\n")[0]: b for b in digest.split("\n\n")}
    assert "olhei ontem" in block["--- #69 read ---"]
    assert "has NO comments" in block["--- #70 empty ---"]
    assert "UNREADABLE" in block["--- #71 unreadable ---"]
    assert "NOT 'nobody has commented'" in block["--- #71 unreadable ---"]


def test_one_ticket_is_ONE_block_however_many_jobs_carry_it():
    """FOUND BY DRIVING THIS AGAINST THE LIVE GITHUB BOARD, not by reading it. `comments_for`
    deduplicates the READ — one request for #81 whatever the floor looks like — and the digest then
    rendered one block per JOB, so a ticket with two parked runs printed its whole thread twice,
    the second time under `(untitled)` because the older job carried no title.

    Twice the prompt bill on the most expensive section here, and worse than the cost: two headers
    with identical conversations under them read, to a model, as two tickets somebody is having the
    same argument on. The fields merge because the runs of one ticket do not all carry the same
    ones — the title has to survive from whichever job HAS it."""
    read = {"issue": "81", "state": "failed",
            "comments": [_said("ana", "olhei ontem", "2026-08-01")]}
    titled = {"issue": "81", "state": "on_hold", "title": "C-38 — OpenCode no eixo do harness"}

    # BOTH ORDERS, because either job may come first out of Temporal and a merge that is really
    # first-wins or last-wins passes on exactly one of them. Mutation caught this: dropping the
    # merge left the version below green while the live shape — the titled run FIRST — lost its
    # title to an untitled second run.
    for jobs in ([read, titled], [titled, read]):
        digest = conversation.comment_digest(jobs)

        assert digest.count("--- #81") == 1, "one ticket, two parked runs, two identical blocks"
        assert digest.count("olhei ontem") == 1
        assert "C-38 — OpenCode no eixo do harness" in digest, "the title was lost to the other run"
        assert "(untitled)" not in digest


def test_the_digest_says_that_a_ticket_it_does_not_list_was_never_ASKED():
    """A NEGATIVE GUARD NEEDS A POSITIVE TWIN, and absence is what this section is made of. Only
    parked tickets are read, so every other ticket is missing from the digest — and a reader
    resolves a missing section exactly the way it resolves an empty one unless it is told."""
    digest = conversation.comment_digest([{"issue": "69", "state": "failed", "title": "t"},
                                          {"issue": "70", "state": "running", "title": "u"}])

    assert "#70" not in digest, "a running job cost a read after all"
    assert "NOT asked about" in digest

    idle = conversation.comment_digest([{"issue": "70", "state": "running"}])
    assert "nothing in the job list above is parked" in idle
    assert "none were asked" in idle
    # AND IT MAKES NO CLAIM ABOUT THE FLOOR, which is not a thing this function read. `gather_jobs`
    # answers `[]` both for a project with nothing running and for a Temporal it could not reach,
    # so a flat "no job is parked" here contradicted `_answer`'s own "(Note: live job state may be
    # incomplete…)" in the very next paragraph — this card's rule broken one layer above the two
    # functions taught to keep it.
    assert "no job is parked" not in idle, "an unreadable floor was asserted to be an idle one"


def test_a_job_parked_by_the_ATTENTION_FLAG_ALONE_is_read_AND_rendered():
    """THE TWO READERS OF `parked()` MUST AGREE, and until now only one of them was watched.

    `parked()` says so in its own docstring — "two spellings would mean a job the snapshot calls
    parked whose thread was never fetched" — and nothing asserted it: every digest test above uses
    a state that is IN `_PARKED_STATES`, so a second spelling inside `comment_digest` that dropped
    the `attention` flag passed all of them. Verified by mutation: replacing the digest's filter
    with `j["state"] in _PARKED_STATES` left the whole file green.

    Not theoretical. `view.ATTENTION_STATES` is the wider set — `paused`,
    `awaiting_prod_approval`, `awaiting_your_merge` are all attention-flagged and NONE of them is
    in `_PARKED_STATES`. Under that mutation a job waiting on the operator's merge still COSTS its
    provider round trip and then vanishes from the digest, under a header that tells the model *a
    ticket absent from this list was NOT asked about* — which would be false: we asked, we paid,
    and we dropped the answer."""
    waiting_on_a_person = {"issue": "88", "state": "awaiting_your_merge", "attention": True,
                           "title": "the PR nobody merged"}
    tracker = _Tracker({}, threads={"88": [_said("ana", "esperando o merge", "2026-08-01")]})

    threads = conversation.comments_for(_github_project(), [dict(waiting_on_a_person)],
                                        tracker=tracker)
    assert [ref for ref, _ in tracker.comments_asked] == ["88"], "the read side ignored the flag"

    digest = conversation.comment_digest([{**waiting_on_a_person, "comments": threads["88"]}])
    assert "--- #88" in digest, "a ticket we asked about and PAID for never reached the prompt"
    assert "esperando o merge" in digest


def test_gather_jobs_hangs_the_thread_on_the_job_and_only_a_LIST_travels(floor, monkeypatch):
    """END TO END THROUGH THE REAL PATH, which is the guard that matters for a capability nothing
    consumes: Temporal → `comments_for` → the job dict → the digest the model reads. `None` is left
    ABSENT on the job on purpose — the digest renders absence on a parked job as UNREADABLE, so the
    failure mode of that line is "we said we did not look", never "we showed a quiet ticket"."""
    floor([{"project": "books", "issue": "69", "state": "failed"},
           {"project": "books", "issue": "70", "state": "on_hold"}])
    tracker = _Tracker({"69": ("open", "importer"), "70": ("open", "exporter")},
                       threads={"69": [_said("ana", "já tentei o retry", "2026-08-01")],
                                "70": None})
    monkeypatch.setattr(conversation, "tracker_for", lambda project: tracker)
    monkeypatch.setattr(conversation, "board_index", lambda project: {})

    jobs = conversation.gather_jobs(_github_project())
    digest = conversation.comment_digest(jobs)

    assert [c.author for c in jobs[0]["comments"]] == ["ana"]
    assert "comments" not in jobs[1], "an unreadable thread was hung on the job as a value"
    assert "já tentei o retry" in digest
    assert "UNREADABLE" in digest.split("--- #70")[1]


def test_a_comment_read_that_EXPLODES_costs_the_thread_and_nothing_else(floor, monkeypatch):
    """The most expensive of the three reads must be the one that pays for itself. It runs last so
    a thread that blows up cannot discard the ticket states and columns already in hand — and
    `answer()` still cannot raise, which is why this asserts through `gather_jobs`, the function it
    calls outside the try that guards the agent."""
    floor([{"project": "books", "issue": "69", "state": "failed"}])
    monkeypatch.setattr(conversation, "tracker_for",
                        lambda project: _Tracker({"69": ("closed", "Plan 88.1")}))
    monkeypatch.setattr(conversation, "board_index", lambda project: {"69": "Done"})

    def _boom(project, jobs, *, tracker=None):
        raise RuntimeError("the comment endpoint is on fire")

    monkeypatch.setattr(conversation, "comments_for", _boom)

    jobs = conversation.gather_jobs(_github_project())

    assert jobs[0]["ticket_state"] == "closed", "a comment failure threw away the ticket read"
    assert jobs[0]["board"] == "Done", "a comment failure threw away the board read"
    assert "UNREADABLE" in conversation.comment_digest(jobs)


# ── and it reaches the prompt, which is the only place it counts ─────────────────────────────────

@pytest.fixture
def prompt(monkeypatch):
    """Run the REAL `answer()` under a stubbed harness and hand back the prompt the model got.

    Occurrence #21 of this codebase's signature defect is what this fixture exists to prevent: the
    port's read side is implemented and proven against three live APIs, and none of that is worth
    anything if the text a model reads never changes."""
    seen: dict = {}

    class _Harness:
        def ask(self, **kw):
            seen.update(kw)
            return type("_R", (), {"summary": "ok", "raw_output": ""})()

    from openfactory.adapters.agent import registry as harnesses
    monkeypatch.setitem(harnesses.HARNESSES, "claude_code", lambda **kw: _Harness())
    monkeypatch.setattr(conversation, "clone_repo",
                        lambda project: (pathlib.Path("/tmp/does-not-matter"), False))

    def _ask(question: str = "e aí?") -> str:
        conversation.answer(_github_project(), question)
        # `prompt`, because that is the kwarg `HarnessTechLead._ask` hands the harness — patching a
        # name the code under test does not use is how three monkeypatches went inert this week.
        return seen["prompt"]

    return _ask


def test_the_prompt_carries_the_thread_and_no_longer_APOLOGISES_for_it(prompt, floor, monkeypatch):
    """WHAT THIS FILE USED TO ASSERT WAS THE OPPOSITE. Both modules carried *"comment history is
    NOT available to you — do not conclude from its absence that nobody has commented"*, which was
    honest while the port had no read side and is false now. Left in place it would be worse than
    useless: it tells the model to disregard the thread printed a few lines above it."""
    floor([{"project": "books", "issue": "69", "state": "failed", "title": "importer"}])
    monkeypatch.setattr(conversation, "tracker_for", lambda project: _Tracker(
        {"69": ("open", "importer")},
        threads={"69": [_said("alice", "subi o timeout, não resolveu", "2026-08-01T09:11Z"),
                        _said("openfactory-bot[bot]", "parked: gates unfixable", "2026-08-01T09:26Z")]}))
    monkeypatch.setattr(conversation, "board_index", lambda project: {})

    text = prompt()

    assert "NOT available" not in text, "the apology outlived the capability it stood in for"
    assert "subi o timeout" in text and "alice" in text
    assert "2026-08-01T09:11Z" in text
    assert "VERIFY" in text, "the model was shown a thread and not told what to do with it"


def _ticket_block(prompt_text: str, ref: str) -> str:
    """The digest block for one ticket, cut out of the whole prompt.

    ASSERTING ON THE WHOLE PROMPT WAS A HOLLOW GUARD, and mutation is how it surfaced: the standing
    instruction quotes the phrase *'Comments UNREADABLE'* to tell the model what it means, so
    `assert "Comments UNREADABLE" in text` passed while the digest below it rendered an unreadable
    thread as a ticket nobody had commented on. A guard has to read the sentence produced by the
    code under test, not one that happens to share its vocabulary."""
    assert f"--- #{ref}" in prompt_text, "the digest never reached the prompt at all"
    return prompt_text.split(f"--- #{ref}")[1].split("\n\n")[0]


def test_the_prompt_says_UNREADABLE_when_the_tracker_would_not_answer(prompt, floor, monkeypatch):
    """The same path, failing. The model must be told it could not look — never shown a silence it
    will read as one."""
    floor([{"project": "books", "issue": "69", "state": "failed", "title": "importer"}])
    monkeypatch.setattr(conversation, "tracker_for",
                        lambda project: _Tracker({"69": ("open", "importer")},
                                                 refuse_comments={"69"}))
    monkeypatch.setattr(conversation, "board_index", lambda project: {})

    block = _ticket_block(prompt(), "69")

    assert "UNREADABLE" in block
    assert "NOT 'nobody has commented'" in block
    assert "has NO comments" not in block, "a refused read was reported as an empty ticket"


def test_answer_still_never_raises_when_the_whole_comment_read_falls_over(prompt, floor,
                                                                          monkeypatch):
    """NON-NEGOTIABLE: a tech-lead that answers with a traceback has not answered. The digest is
    rendered outside the try that catches agent trouble, so it has to be total over whatever the
    enrichment left on the job dicts — including nothing at all."""
    floor([{"project": "books", "issue": "69", "state": "failed"}])

    def _boom(project):
        raise RuntimeError("the registry is on fire")

    monkeypatch.setattr(conversation, "tracker_for", _boom)

    block = _ticket_block(prompt(), "69")

    assert "UNREADABLE" in block
    assert "has NO comments" not in block


# ── the checkout goes through the forge registry ────────────────────────────────────────────────

def _clone_urls(monkeypatch, module) -> list[list[str]]:
    """Record every git command `module` runs instead of running it."""
    calls: list[list[str]] = []

    def _run(cmd, **kw):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", _run)
    return calls


def test_an_azure_project_is_cloned_from_dev_azure_com(monkeypatch):
    """THE DEFECT, DIRECTLY. The literal this replaced sent every deployment to github.com, where
    an Azure Repos project is a 404 for a repository that exists — and Azure nests one level
    deeper (`/{project}/_git/`), so no host swap would have fixed it."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "azure-pat")
    calls = _clone_urls(monkeypatch, conversation)

    tmp, cloned = conversation.clone_repo(_azure_project())

    assert cloned is True
    url = calls[0][calls[0].index("--depth") + 2]
    assert url == "https://openfactory:azure-pat@dev.azure.com/acme-ai/factory/_git/fx-ado"
    assert "github.com" not in url
    tmp.rmdir()


def test_the_remote_is_rewritten_from_the_url_WE_USED_not_rebuilt_token_free(monkeypatch):
    """The credential in .git/config is readable by the read-only chat agent, so it is stripped
    after the clone. It cannot be stripped by asking the registry for a token-free URL: the Azure
    row mints its credential from a PROVIDER and signs the URL whatever the caller passes — which
    this asserts, so a future 'simplification' back to a rebuild is caught."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "azure-pat")
    from openfactory.adapters.forge.registry import clone_url_for

    assert "azure-pat" in clone_url_for(_azure_project(), "fx-ado", token=None), (
        "the premise of the rewrite below no longer holds"
    )

    calls = _clone_urls(monkeypatch, conversation)
    tmp, _ = conversation.clone_repo(_azure_project())

    rewritten = calls[1][-1]
    assert rewritten == "https://dev.azure.com/acme-ai/factory/_git/fx-ado"
    assert "azure-pat" not in rewritten
    tmp.rmdir()


def test_a_github_project_still_clones_exactly_as_it_did(monkeypatch):
    """The migration's whole cost: the six GitHub projects that exist must not move a byte."""
    monkeypatch.setenv("OPENFACTORY_FORGE_TOKEN", "ghs_tok")
    calls = _clone_urls(monkeypatch, conversation)

    tmp, cloned = conversation.clone_repo(_github_project())

    assert cloned is True
    assert calls[0][calls[0].index("--depth") + 2] == \
        "https://x-access-token:ghs_tok@github.com/o/r.git"
    assert calls[1][-1] == "https://github.com/o/r.git"
    tmp.rmdir()


def test_an_unknown_forge_kind_is_a_missing_checkout_never_an_exception(caplog):
    """`clone_url_for` RAISES on a kind it does not know — correctly, because a clone aimed at the
    wrong host reads as a permissions problem. The tech-lead must still answer."""
    unknown = Project(name="x", repo_path="/tmp/x",
                      tracker=ProviderRef(kind="bitbucket", repo="o/r"))

    with caplog.at_level("WARNING"):
        tmp, cloned = conversation.clone_repo(unknown)
        tmp2, cloned2 = diagnosis._checkout(unknown, "#1")

    assert cloned is False and cloned2 is False
    assert "unknown forge" in caplog.text
    tmp.rmdir()
    tmp2.rmdir()


def test_the_diagnosis_checkout_uses_the_same_seam(monkeypatch):
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "azure-pat")
    calls = _clone_urls(monkeypatch, diagnosis)

    tmp, cloned = diagnosis._checkout(_azure_project(), "#412")

    assert cloned is True
    assert "dev.azure.com" in calls[0][calls[0].index("--depth") + 2]
    assert calls[1][-1] == "https://dev.azure.com/acme-ai/factory/_git/fx-ado"
    tmp.rmdir()


def test_a_failed_clone_redacts_a_credential_this_module_never_HELD(monkeypatch, caplog):
    """`scrubbed(exc, token)` can only replace a secret the caller HAS, and here it does not.

    The mismatch this used to get for free — `forge_token_for` handing back the deployment's
    GitHub PAT while the Azure adapter signed the URL from `AZURE_DEVOPS_PAT` — was a RESOLVER
    DEFECT and is fixed (2026-08-09: the vendor's default variable resolves between `token_env`
    and the generic pair), so the mismatch is now CONSTRUCTED at the seam instead. The regex is
    not made redundant by that fix: a credential rotated after the URL was signed, or a caller
    handed a stale token, reproduces exactly this shape, and value-scrubbing would replace the
    token that is not in the text while publishing the one that is."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "azure-pat-never-seen-here")
    import openfactory.credentials as credentials
    monkeypatch.setattr(credentials, "forge_token_for",
                        lambda project: "the-deployments-github-pat")
    project = _azure_project(names_its_credential=False)

    def _fail(cmd, **kw):
        raise subprocess.CalledProcessError(128, cmd)

    monkeypatch.setattr(conversation.subprocess, "run", _fail)

    with caplog.at_level("WARNING"):
        tmp, cloned = conversation.clone_repo(project)

    assert cloned is False
    assert "azure-pat-never-seen-here" not in caplog.text, "a live credential reached the log"
    assert "***" in caplog.text, "the failure lost its trace along with the token"
    tmp.rmdir()


def test_the_diagnosis_checkout_redacts_a_credential_IT_never_HELD(monkeypatch, caplog):
    """THE TWIN THE OTHER MODULE GOT AND THIS ONE DID NOT.

    `test_a_failed_clone_redacts_a_credential_this_module_never_HELD` above exists because the
    author's first version of it passed under value-only scrubbing. The identical line in
    `diagnosis._checkout` was left guarded only by `test_the_diagnosis_checkout_is_scrubbed_the_
    same_way`, which uses a GITHUB project — where `forge_token_for` returns exactly the secret the
    adapter signs the URL with, so `scrubbed(exc, token)` alone is enough and the regex is proved
    by nothing. Verified by mutation: dropping the `_URL_CREDENTIAL` sub from this module left
    every guard green while `AZURE_DEVOPS_PAT` went into the worker's log.

    Same lesson, restated once because it keeps costing: a redaction test written against a fixture
    whose two credentials are the same value cannot tell redaction from luck. (The resolver no
    longer produces the mismatch on its own — fixed 2026-08-09, vendor defaults — so it is
    constructed at the seam, modelling a token rotated after the URL was signed.)"""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "azure-pat-the-diagnosis-never-saw")
    import openfactory.credentials as credentials
    monkeypatch.setattr(credentials, "forge_token_for",
                        lambda project: "the-deployments-github-pat")
    project = _azure_project(names_its_credential=False)

    def _fail(cmd, **kw):
        raise subprocess.CalledProcessError(128, cmd)

    monkeypatch.setattr(diagnosis.subprocess, "run", _fail)

    with caplog.at_level("WARNING"):
        tmp, cloned = diagnosis._checkout(project, "#412")

    assert cloned is False
    assert "azure-pat-the-diagnosis-never-saw" not in caplog.text, "a live credential reached the log"
    assert "***" in caplog.text, "the failure lost its trace along with the token"
    tmp.rmdir()


# ── the diagnosis asks the tracker WITH a credential ────────────────────────────────────────────

def test_the_diagnosis_builds_ONE_tracker_with_the_projects_credential(monkeypatch):
    """It was `build_tracker(project)` — no token — and the worker has no ambient tracker auth, so
    the read failed every time on the one path that does not pass a tracker in (the operator asking
    `diagnose` from the panel). Its own `except` logged and produced a HandOff anyway.

    ONE, and asserted through `_situation` rather than through the helper, because there are two
    reads now. Building a client per read resolves the credential twice and, on a GitHub App
    deployment, mints two installation tokens for one diagnosis — the cost `conversation.
    tracker_for` already carries a paragraph about."""
    monkeypatch.setenv("OPENFACTORY_TRACKER_TOKEN", "the-tracker-token")
    built: list[str | None] = []

    def _build(project, *, token=None, token_provider=None):
        built.append(token)
        return _Tracker({"412": ("open", "the importer breaks")},
                        threads={"412": [_said("ana", "o parser morre no csv", "2026-08-01")]})

    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker", _build)

    situation = diagnosis._situation(_github_project(), issue="412", state="failed", note="boom")

    assert built == ["the-tracker-token"], "one diagnosis built a tracker per read"
    assert "the importer breaks" in situation
    assert "o parser morre no csv" in situation


def test_the_situation_carries_the_comment_history_and_no_longer_apologises_for_it(monkeypatch):
    """WHAT CAME BACK (#97). This asserted the opposite: the comments were read through `gh`, the
    port had no read side, so the capability was deleted and the prompt was handed the sentence
    *"the ticket's comment history is NOT available to you"*. It was honest then and it is false
    now — and left in place it would tell the model to ignore the thread printed above it."""
    tracker = _Tracker(
        {"412": ("open", "the importer breaks")},
        threads={"412": [_said("alice", "subi o timeout, não resolveu", "2026-08-01T09:11Z"),
                         _said("openfactory-bot[bot]", "parked: gates unfixable", "2026-08-01T09:26Z")]})

    situation = diagnosis._situation(_github_project(), issue="412", state="failed", note="boom",
                                     tracker=tracker)

    assert "NOT available" not in situation, "the apology outlived the capability it stood in for"
    # WHO said it and WHEN survive — the whole reason `TicketComment` is not a list of strings.
    assert "alice" in situation and "2026-08-01T09:11Z" in situation
    assert "openfactory-bot[bot]" in situation
    assert situation.index("subi o timeout") < situation.index("parked: gates unfixable"), (
        "the thread reached the prompt newest-first; an argument read backwards is a different "
        "argument"
    )
    assert "VERIFY" in situation, "the instruction that made the history worth reading is gone"
    assert tracker.comments_asked == [("412", diagnosis._COMMENTS_READ)]


def test_a_thread_the_tracker_could_not_read_is_SAID_not_rendered_as_silence():
    """`None` = could not read. An unreadable thread and an empty one produce the same silence in
    a prompt, and the model resolves both the same way: nobody has looked at this, so my answer is
    new. Both shapes of failure — the port answering None, and the call blowing up."""
    for tracker in (_Tracker({"412": ("open", "t")}, threads={"412": None}),
                    _Tracker({"412": ("open", "t")}, refuse_comments={"412"})):
        situation = diagnosis._situation(_github_project(), issue="412", state="failed",
                                         note="boom", tracker=tracker)

        assert "could NOT be read" in situation
        assert "NOT the same as nobody having commented" in situation
        assert "has NO comments" not in situation, "an unread thread was reported as an empty one"


def test_an_empty_thread_is_a_FACT_the_diagnosis_may_state():
    """The other half of the rule, and the reason it is not enough to always say "I could not
    read": `[]` is the tracker answering, and "nobody has commented" is then a true and useful
    sentence — it tells the model no prior fix is recorded."""
    situation = diagnosis._situation(_github_project(), issue="412", state="failed", note="boom",
                                     tracker=_Tracker({"412": ("open", "t")}))

    assert "has NO comments" in situation
    assert "could NOT be read" not in situation


def test_a_diagnosis_with_no_tracker_at_all_still_produces_a_situation(caplog):
    """Every input here is optional by design — and the one that is missing must still be named.
    A registry row naming a tracker nobody implements makes the answer thinner, never fatal."""
    broken = Project(name="x", repo_path="/tmp/x", tracker=ProviderRef(kind="pivotal-tracker"))

    with caplog.at_level("WARNING"):
        situation = diagnosis._situation(broken, issue="412", state="failed", note="boom")

    assert "boom" in situation
    assert "could NOT be read" in situation, "no tracker rendered as a ticket nobody has commented on"
    assert "no tracker for x" in caplog.text


# ── reachability: no vendor survives in these two modules ───────────────────────────────────────

def _shell_words(path: pathlib.Path) -> list[str]:
    """Every string that is the FIRST element of a list literal passed to a `run(...)` call — i.e.
    the program each subprocess in this module launches.

    From the AST, not the text: both modules explain the rule by naming `gh` in prose, and this
    codebase's house style is to explain a decision by naming the vendor that taught it. A grep
    would match the explanation and a guard that fights the house style is one somebody deletes."""
    out: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call)
                and (getattr(node.func, "attr", None) or getattr(node.func, "id", None)) == "run"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.List) and arg.elts:
                first = arg.elts[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    out.append(first.value)
    return out


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_the_techlead_shells_out_to_no_vendor_cli(path):
    """`git` is a protocol, not a provider — `gh` is the provider, and it is what made this role
    answer a question about an Azure deployment out of an empty index."""
    assert set(_shell_words(path)) <= {"git"}, (
        f"{path.name} launches a vendor CLI again: {_shell_words(path)}"
    )


def test_that_guard_can_actually_SEE_an_offender(tmp_path):
    """A scanner that matched nothing — a renamed call, a wrong node type — would pass the test
    above for ever while proving nothing."""
    (tmp_path / "x.py").write_text(
        'import subprocess\nsubprocess.run(["gh", "issue", "list"])\n', encoding="utf-8")

    assert _shell_words(tmp_path / "x.py") == ["gh"]


def _non_prose_strings(path: pathlib.Path) -> list[tuple[int, str]]:
    """`(lineno, value)` for every string constant in the module that is NOT a docstring.

    DOCSTRINGS ARE EXEMPT ON PURPOSE, and that is not a loophole: this codebase's house style is to
    explain a decision by naming the vendor that taught it, because a claim without its measurement
    is a claim the next reader has to re-earn. What the rule governs is what the code REACHES FOR,
    not what a sentence explains, and both modules under test carry paragraphs quoting the very
    literals they no longer contain — a
    github.com clone URL, and the sentence apologising for a comment history nobody had ported. A
    guard that fought the house style is a guard somebody deletes.

    Shared by the two scanners below because they need exactly the same exemption, and a second
    copy of it would be the one that goes stale."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prose = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [(node.lineno, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in prose]


def _hand_built_urls(path: pathlib.Path) -> list[str]:
    """Every non-docstring string constant that starts to spell out a URL — `https://` followed by
    a host or an interpolation.

    The pattern is tight on purpose: `(https://)[^@/\\s]+@` is a REDACTION expression, the opposite
    of a hand-built URL, and it must not read as one."""
    return [f"{path.name}:{lineno}" for lineno, value in _non_prose_strings(path)
            if re.search(r"https://[\w{]", value)]


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_url_in_these_modules_names_a_host(path):
    """A clone URL's host, credential shape and path layout are the ADAPTER's knowledge. Any
    `https://…` built here is a second opinion about a question only the forge can answer."""
    assert not _hand_built_urls(path), (
        f"a URL is being built by hand again at {_hand_built_urls(path)}"
    )


def test_that_url_guard_can_actually_SEE_an_offender(tmp_path):
    """The exact line this card deleted, fed back to the scanner. Without this the docstring
    exemption plus a tight pattern could between them exempt everything."""
    (tmp_path / "y.py").write_text(
        '"""A docstring may say https://x@github.com/o/r.git — prose is exempt."""\n'
        'def clone(repo, token):\n'
        '    return f"https://x-access-token:{token}@github.com/{repo}.git"\n',
        encoding="utf-8")

    assert _hand_built_urls(tmp_path / "y.py") == ["y.py:3"]


def _calls_in(path: pathlib.Path, func: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func), None)
    assert fn is not None, f"{func} vanished from {path.name} — this guard now guards nothing"
    return {getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            for n in ast.walk(fn) if isinstance(n, ast.Call)}


@pytest.mark.parametrize(("path", "func"), [
    (MODULES[0], "clone_repo"),
    (MODULES[1], "_checkout"),
])
def test_the_checkout_resolves_its_url_through_the_registry(path, func):
    """REACHABILITY, which is this codebase's signature defect — ~20 things built, tested and
    called by nothing. `clone_url_for` existing is worth nothing if the tech-lead still writes its
    own URL."""
    assert "clone_url_for" in _calls_in(path, func)


def test_the_answer_path_actually_reaches_the_ticket_index():
    """Same rule one level up: `ticket_index` is only a capability if `gather_jobs` calls it, and
    `gather_jobs` is only reached if `_answer` calls THAT."""
    assert "ticket_index" in _calls_in(MODULES[0], "gather_jobs")
    assert "gather_jobs" in _calls_in(MODULES[0], "_answer")


def test_the_answer_path_actually_reaches_the_COMMENT_read():
    """OCCURRENCE #21 OF THE SIGNATURE DEFECT IS WHAT THIS GUARDS. `TrackerAdapter.comments()` is
    implemented by three vendors and proven against three live APIs, and every one of those tests
    stays green if nothing ever calls it — which is exactly how the last twenty of these shipped.
    The chain has to hold end to end: `_answer` renders the digest, `gather_jobs` performs the
    read, and the two modules share one renderer so the author cannot be lost from one of them."""
    assert "comments_for" in _calls_in(MODULES[0], "gather_jobs")
    assert "comment_digest" in _calls_in(MODULES[0], "_answer")
    assert "comments" in _calls_in(MODULES[0], "comments_for"), (
        "comments_for does not ask the port for comments"
    )
    assert "comments" in _calls_in(MODULES[1], "_comment_history")
    assert "_comment_history" in _calls_in(MODULES[1], "_situation")
    for path, func in ((MODULES[0], "comment_digest"), (MODULES[1], "_comment_history")):
        assert "render_comments" in _calls_in(path, func), (
            f"{path.name}::{func} spells 'who said what' its own way; two spellings is how one of "
            f"them quietly loses the author"
        )


def _apologies(path: pathlib.Path) -> list[str]:
    """Every non-docstring string that still tells a model this capability does not exist."""
    return [f"{path.name}:{lineno}" for lineno, value in _non_prose_strings(path)
            if "NOT available to you" in value]


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_neither_module_still_tells_the_model_the_history_is_UNAVAILABLE(path):
    """The apology, swept from what these modules SAY rather than from one prompt I remembered to
    check. It was true for as long as the port had no read side; carried forward it is worse than
    stale — it instructs the model to disregard the thread printed directly above it. And this
    codebase's own history is that the sentence outlives the condition: `board_index` carried a
    paragraph describing a fix the code beneath it had stopped applying."""
    assert not _apologies(path), f"{path.name} still apologises at {_apologies(path)}"


def test_that_apology_guard_can_actually_SEE_an_offender(tmp_path):
    """The deleted line fed back to the scanner, because a guard whose docstring exemption swallows
    everything passes for ever while proving nothing — the same self-test the URL scanner carries,
    for the same reason."""
    (tmp_path / "z.py").write_text(
        '"""A docstring may quote *"is NOT available to you"* — prose is exempt."""\n'
        'PROMPT = ("(The ticket\'s comment history is NOT available to you — do not conclude "\n'
        '          "from its absence that nobody has commented.)")\n',
        encoding="utf-8")

    assert _apologies(tmp_path / "z.py") == ["z.py:2"]


def test_the_credential_asked_for_is_the_per_project_one():
    """`forge_token()` is process-wide; one deployment now hosts two forges. Asserted per function
    because a sweep would be satisfied by the call site being deleted."""
    for path, func in ((MODULES[0], "clone_repo"), (MODULES[1], "_checkout")):
        called = _calls_in(path, func)
        assert "forge_token_for" in called, f"{path.name}::{func} does not ask which project"
        assert "forge_token" not in called, f"{path.name}::{func} reads the process-wide token"
    assert "tracker_token_for" in _calls_in(MODULES[0], "tracker_for")


def test_the_board_is_read_with_the_TRACKER_axis_credential_too():
    """`board_index` says in prose that *"THE BOARD IS A TRACKER OBJECT, so it takes the TRACKER's
    credential — this read the forge's"*, and nothing asserted it. Swapping that one line back to
    `forge_token_for` — the very defect the paragraph describes, on the axis-split deployment this
    card exists for — left all 57 guards green.

    A comment recording a fix is not the fix staying fixed. Both directions, because the positive
    alone is satisfied by a function that asks BOTH axes and hands over whichever answers."""
    called = _calls_in(MODULES[0], "board_index")

    assert "tracker_token_for" in called, "the board is not asking the tracker axis for its token"
    assert not {"forge_token_for", "forge_token"} & called, (
        "board_index sends a FORGE credential to the board; on an Azure Boards + GitHub Repos "
        "project that is a github.com token presented to dev.azure.com, and the 401 reads like a "
        "revoked credential rather than like the configuration mistake it is"
    )
