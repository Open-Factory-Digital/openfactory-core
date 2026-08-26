"""The ledger believes only what the channel confirmed (ADR-0021) — never the sweep's self-report.

`say` returns False by contract instead of raising, so a rotated token / archived channel turned
every proactive post into a silent drop while three sites recorded questions-as-asked,
deliveries-as-announced and findings-as-reported anyway. The dedup layers (to_open, since,
chase state) then suppressed every retry: the client heard nothing, ever, behind a green memory.
Same disease on the split: children were announced "in TO-DO" on a board move whose bool was
discarded.

Boundary fakes only (channel, ledger store, board module, tracker); everything between is the
production orchestration in activities.py / schedule.py. No live calls: the gh-backed rescue and
the token mint are stubbed at their module seams.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

import openfactory.adapters.channel as channel_pkg
import openfactory.memory.store as loop_store
import openfactory.product.authoring as authoring
import openfactory.product.module as product_module
import openfactory.runtime.temporal.activities as acts
from openfactory.contracts import JobState
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.memory.ledger import ACCEPTANCE, CHASED, DELIVERY, QUESTION, open_loop
from openfactory.product.triage import Observation, Ticket, TriageReport
from openfactory.runtime.temporal.activities import _do_split, _product_followup
from openfactory.runtime.temporal.io import SplitInput


class _Channel:
    """A channel whose delivery can be turned off — `say` returns False, never raises (base.py)."""

    def __init__(self):
        self.deliver = True
        self.posts: list[str] = []      # what the client actually received
        self.attempts: list[str] = []   # what the sweep tried to say

    def say(self, *, project, channel, text):
        self.attempts.append(text)
        if self.deliver:
            self.posts.append(text)
        return self.deliver

    def mention(self, person, **kw):
        return person

    def client(self, project):
        return None

    def start_listeners(self):
        return []


class _Store:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def read(self, project):
        return list(self.rows)

    def write(self, project, loops):
        self.rows.extend(loops)
        return len(loops)


class _Module:
    def __init__(self, tickets):
        self._board_tickets = tickets
        self.token = None


def _project():
    return Project(name="books", repo_path="/t",
                   # THE CLIENT THIS SUITE IS ABOUT IS BRAZILIAN (#160). It was implicit
                   # while every composer wrote pt-BR unconditionally; now that they take
                   # the project's language, saying so is what proves the wiring — an
                   # unset language answers in English, which is the product's default.
                   language="pt-BR",
                   tracker=ProviderRef(kind="github", repo="a/b"),
                   forge=ProviderRef(kind="github", repo="a/b"),
                   product=ProductConfig(docs_repo="a/b", channel_id="C0PROD",
                                         agent_name="Nina"))


@pytest.fixture()
def wired(monkeypatch):
    channel = _Channel()
    store = _Store()
    monkeypatch.setattr(channel_pkg, "build_channel", lambda p=None: channel)
    monkeypatch.setattr(loop_store, "read", store.read)
    monkeypatch.setattr(loop_store, "write", store.write)
    # the ADR-0032 rescue shells out to gh — a boundary this file never crosses
    monkeypatch.setattr(acts, "_land_product_proposals", lambda project, **kw: [])
    return channel, store


# ── the class: asked / announced / chased must mean DELIVERED ──────────────────────────────────

def test_a_dropped_announcement_leaves_the_delivery_open_for_the_next_sweep(wired):
    """Recorded first, a dropped "está pronto" was never re-sent, and the 72h acceptance chase
    became the client's FIRST message about that delivery — referencing one that never existed."""
    channel, store = wired
    channel.deliver = False
    store.rows = [open_loop(DELIVERY, "7", owner="product", ts="2026-07-28T10:00:00+00:00",
                            context={"issues": "500"})]
    done = [Ticket(number=500, title="a", state="closed", column="Done", body="")]

    result = _product_followup(_project(), _Module(done), TriageReport(), _project().product)

    assert "closed:0" in result and "accepting:0" in result, result
    assert all(x.state != "closed" for x in store.rows), "closed on a post nobody received"
    assert not [x for x in store.rows if x.kind == ACCEPTANCE], \
        "an acceptance question opened for an announcement that never went out"

    # the channel comes back → the SAME sweep logic announces and only then closes
    channel.deliver = True
    result = _product_followup(_project(), _Module(done), TriageReport(), _project().product)
    assert "closed:1" in result and "accepting:1" in result, result
    assert any("requisito 7" in p for p in channel.posts), channel.posts
    assert [x for x in store.rows if x.kind == ACCEPTANCE and x.state == "open"]


def test_a_dropped_ask_is_not_remembered_as_asked(wired):
    """to_open dedupes fresh questions against open QUESTION loops — a row for a never-delivered
    ask suppresses that question for ever."""
    channel, store = wired
    channel.deliver = False
    findings = [Observation(ticket=400, kind="no-criteria", detail="x")]
    tickets = [Ticket(number=400, title="Card 400", state="open", column="Backlog", body="")]

    result = _product_followup(_project(), _Module(tickets),
                               TriageReport(observations=findings), _project().product)

    assert "asked:0" in result, result
    assert not [x for x in store.rows if x.kind == QUESTION], \
        "a question nobody received was remembered as asked"

    channel.deliver = True
    result = _product_followup(_project(), _Module(tickets),
                               TriageReport(observations=findings), _project().product)
    assert "asked:1" in result, result
    assert any("sobre o #400" in p for p in channel.posts), channel.posts


def test_a_dropped_chase_does_not_spend_the_one_chase(wired):
    """Each question gets exactly one chase. Spent on a post nobody received, the question goes
    quiet for ever; a dropped chase must leave the loop OPEN for the next sweep."""
    channel, store = wired
    channel.deliver = False
    store.rows = [open_loop(QUESTION, "135", owner="product", about="no-criteria",
                            ts="2026-07-20T10:00:00+00:00", context={"asked": "x", "person": ""})]
    findings = [Observation(ticket=135, kind="no-criteria", detail="x")]  # still live → stays open

    result = _product_followup(_project(), _Module([]), TriageReport(observations=findings),
                               _project().product)

    assert "chased:0" in result, result
    assert not [x for x in store.rows if x.state == CHASED]

    channel.deliver = True
    result = _product_followup(_project(), _Module([]), TriageReport(observations=findings),
                               _project().product)
    assert "chased:1" in result, result
    assert [x for x in store.rows if x.state == CHASED]


def test_a_board_resolution_still_closes_with_the_channel_down(wired):
    """The boundary of the fix: closes driven by OBSERVATION of the board need no post and must
    not be coupled to the channel's health."""
    channel, store = wired
    channel.deliver = False
    store.rows = [open_loop(QUESTION, "412", owner="product", about="no-criteria",
                            ts="2026-07-28T10:00:00+00:00", context={"asked": "x"})]

    result = _product_followup(_project(), _Module([]), TriageReport(observations=[]),
                               _project().product)

    assert "closed:1" in result, result


def test_no_transcript_row_for_a_message_nobody_received(wired, monkeypatch):
    """Her memory of the conversation must hold what was SAID, not what was attempted — a
    transcript of a dropped post is the same self-report disease one layer down."""
    import openfactory.memory.transcript as transcript

    recorded: list = []
    monkeypatch.setattr(transcript, "record", lambda *a, **k: recorded.append(k))
    channel, store = wired
    channel.deliver = False
    store.rows = [open_loop(DELIVERY, "7", owner="product", ts="2026-07-28T10:00:00+00:00",
                            context={"issues": "500"})]

    _product_followup(_project(), _Module([Ticket(number=500, title="a", state="closed",
                                                  column="Done", body="")]),
                      TriageReport(), _project().product)

    assert recorded == [], "a post that returned False was written into the transcript"


# ── the sweep's own memory: intro marker and report keys commit AFTER the post ─────────────────

class _SweepModule:
    def __init__(self, project, **kw):
        self._board_tickets = []

    def introduce(self):
        return "oi, eu sou a Nina"

    def triage_board(self):
        return TriageReport(observations=[Observation(ticket=1, kind="no-criteria",
                                                      detail="x")]), None


@pytest.fixture()
def swept(monkeypatch):
    channel = _Channel()
    remembered: list = []
    monkeypatch.setattr(channel_pkg, "build_channel", lambda p=None: channel)
    monkeypatch.setattr(acts, "ProjectRegistry",
                        lambda: type("R", (), {"get": lambda self, name: _project()})())
    monkeypatch.setattr(acts, "_remember_sweep",
                        lambda name, keys, ts, backlog=0: remembered.append(list(keys)))
    monkeypatch.setattr(acts, "_product_followup", lambda *a, **k: "followed")
    monkeypatch.setattr(product_module, "ProductModule", _SweepModule)
    return channel, remembered


def test_the_intro_marker_commits_only_after_the_intro_lands(swept, monkeypatch):
    """A non-empty history routes every later sweep to the triage path — committed before a
    dropped intro, the client's first-ever message becomes a bare board report a cadence later."""
    channel, remembered = swept
    monkeypatch.setattr(acts, "_sweep_history", lambda name: {})

    channel.deliver = False
    assert asyncio.run(acts.product_sweep("books")) == "intro-dropped"
    assert remembered == [], "a dropped intro was committed as met"

    channel.deliver = True
    assert asyncio.run(acts.product_sweep("books")) == "introduced"
    assert remembered == [[]]
    assert any("Nina" in p for p in channel.posts)


def test_report_keys_commit_only_after_the_report_lands(swept, monkeypatch):
    """Committed first, a dropped report turns every fresh finding into "standing" for the next
    sweep — itemised to nobody, ever, with the weekly loop blinded by its own memory."""
    channel, remembered = swept
    monkeypatch.setattr(acts, "_sweep_history", lambda name: {"ts": "2026-07-01"})
    monkeypatch.setattr(acts, "_last_sweep_keys", lambda name: [])

    channel.deliver = False
    out = asyncio.run(acts.product_sweep("books"))
    assert out.startswith("report-dropped:1"), out
    assert remembered == [], "keys committed for a report nobody received"

    channel.deliver = True
    out = asyncio.run(acts.product_sweep("books"))
    assert out.startswith("reported:1"), out
    assert remembered == [["1:no-criteria"]]


# ── the ADR-0032 rescue rides the HOURLY rounds, not only the weekly sweep ─────────────────────

def test_the_hourly_rounds_land_orphan_proposals_before_touching_temporal(monkeypatch):
    """An unmerged proposal makes the role deny its own requirement within ONE client message;
    its only healer rode a weekly sweep that is skipped whenever the board is unreadable. The
    rounds must run the rescue first, decoupled from Temporal and the board both."""
    import openfactory.runtime.temporal.connection as connection

    landed: list = []
    monkeypatch.setattr(acts, "ProjectRegistry",
                        lambda: type("R", (), {"get": lambda self, name: _project()})())
    monkeypatch.setattr(product_module, "ProductModule",
                        lambda project, **kw: type("M", (), {"token": "tok"})())
    monkeypatch.setattr(authoring, "land_open_proposals",
                        lambda **kw: (landed.append(kw), ["req/0007-x"])[1])

    async def _down():
        raise RuntimeError("temporal unreachable")

    monkeypatch.setattr(connection, "connect", _down)

    with pytest.raises(RuntimeError):
        asyncio.run(acts.techlead_watch("books"))

    assert landed, "the rounds never ran the rescue"
    assert landed[0]["docs_repo"] == "a/b" and landed[0]["token"] == "tok"


def test_the_weekly_followup_still_lands_proposals(wired, monkeypatch):
    calls: list = []
    monkeypatch.setattr(acts, "_land_product_proposals",
                        lambda project, **kw: calls.append(project.name) or [])

    _product_followup(_project(), _Module([]), TriageReport(), _project().product)

    assert calls == ["books"]


# ── the split claims only the queue positions the board accepted ───────────────────────────────

class _Board:
    def __init__(self, ok_for=None):
        self.ok_for = ok_for   # issue numbers whose move succeeds; None = all
        self.moves: list = []

    def set_status(self, *, issue, issue_url, state, needs_person=None):
        self.moves.append((issue, state))
        return self.ok_for is None or issue in self.ok_for


class _SplitTracker:
    repo = "o/app"

    def __init__(self, board):
        self.board = board
        self.created: list = []
        self.closed = None

    def get_ticket(self, ref):
        from openfactory.contracts import Ticket
        return Ticket(id=ref, title="Plan 92 — hardening + rate limits",
                      objective="x", repo="o/app")

    def find_ticket(self, *, title):
        return None

    def create_ticket(self, *, title, body):
        self.created.append(title)
        return f"#{100 + len(self.created)}"

    def set_state(self, ref, state, reason=None, *, needs_person=None):
        raise AssertionError("with a board present the split must read the board's own verdict, "
                             "not set_state's silence")

    def close_ticket(self, ref, reason, *, delivered=True):
        self.closed = (ref, reason)

    def link_child(self, parent_ref, child_ref):
        pass

    def children_of(self, parent_ref):
        return []


class _Notifier:
    def __init__(self):
        self.sent: list = []

    def notify(self, *, message, level="info"):
        self.sent.append({"message": message, "level": level})


def _patch_split(monkeypatch, board):

    tracker = _SplitTracker(board)
    notifier = _Notifier()
    monkeypatch.setattr(acts, "_tracker_for", lambda project: tracker)
    monkeypatch.setattr(acts, "ProjectRegistry",
                        lambda: type("R", (), {"get": lambda self, name: object()})())
    import openfactory.factory
    import openfactory.loader
    monkeypatch.setattr(openfactory.loader, "load_manifest",
                        lambda project: type("M", (), {"split_to_todo": True})())
    monkeypatch.setattr(openfactory.factory, "notifier_for_project", lambda p=None: notifier)
    return tracker, notifier


def test_a_failed_board_move_is_never_claimed_as_queued(monkeypatch):
    """set_state swallows the board's bool, so a rate-limited item-edit left a child column-less
    — invisible to the poller's exact-match TO-DO scan — while the parent's close comment and the
    Slack announcement both said it was queued. Work vanishing behind a false confirmation."""
    tracker, notifier = _patch_split(monkeypatch, _Board(ok_for={"101"}))

    out = _do_split(SplitInput(project="p", issue="37", reasons="r", children=[
        {"title": "a", "objective": "o", "criteria": ["c"]},
        {"title": "b", "objective": "o2", "criteria": ["c2"]}]))

    assert "not queued: #102" in out, out
    ref, reason = tracker.closed
    assert ref == "#37"
    assert "except #102" in reason, f"the close comment claims a queue the board refused: {reason}"
    slack = notifier.sent[0]
    # THE FACT, NOT THE WORDING (#160 moved this sentence into the per-language catalogue). What
    # must survive is that the message NAMES the child the board refused and says it was not
    # moved — asserting the Portuguese literal is what made this guard fail the day the
    # announcement started obeying the project's configured language.
    from openfactory.techlead import voice

    assert "#102" in slack["message"]
    stem = voice.NARRATION["split.stragglers"]["en"].split("{")[0]
    assert stem in slack["message"], slack["message"]
    assert "mandei pra" not in slack["message"], "still claims the children were queued"
    assert slack["level"] == "warning"


def test_children_the_board_accepted_are_claimed_in_order(monkeypatch):
    tracker, notifier = _patch_split(monkeypatch, _Board())

    out = _do_split(SplitInput(project="p", issue="37", reasons="r", children=[
        {"title": "a", "objective": "o", "criteria": ["c"]},
        {"title": "b", "objective": "o2", "criteria": ["c2"]}]))

    assert out == "split into #101, #102"
    assert tracker.board.moves == [("101", JobState.TODO), ("102", JobState.TODO)]
    assert "in TO-DO — they will run one at a time" in tracker.closed[1]
    from openfactory.techlead import voice

    said = notifier.sent[0]["message"]
    # THE HEAD TOO, and it is the half no structural guard can see: it is composed into a local
    # and the notifier is handed `head + body`, so the walk in
    # `test_nothing_speaks_before_it_asks_the_language.py` reads a Name and finds no string at all.
    # Measured — welding the Portuguese head back survived that guard untouched.
    assert voice.NARRATION["split.head"]["en"].split("{")[0] in said, said
    assert voice.NARRATION["split.created"]["en"].split("{")[0] in said
    assert voice.NARRATION["split.to-todo"]["en"] in said
    assert notifier.sent[0]["level"] == "info"


# ── one stuck run must never stop the schedules for ever ───────────────────────────────────────

def test_sweep_and_watch_runs_are_bounded_below_their_tick():
    """Overlap policy is SKIP, and Temporal's default execution timeout is unlimited: one run
    whose workflow task cannot complete (unregistered type after a bad deploy, TMPRL1100) would
    drop every future tick — a permanent stop indistinguishable from a quiet floor. Each workflow
    is one activity (start_to_close 10m, no retry), so the bound sits just above that."""
    from temporalio.client import ScheduleOverlapPolicy

    from openfactory.runtime.temporal.schedule import _product_schedule, _watch_schedule

    for sched in (_product_schedule("books", 24 * 7), _watch_schedule("books", 1)):
        assert sched.policy.overlap == ScheduleOverlapPolicy.SKIP  # the premise of the bound
        cap = sched.action.execution_timeout
        assert cap is not None, "an unbounded run + SKIP = every future tick dropped, silently"
        assert timedelta(minutes=10) < cap <= timedelta(hours=1), cap


# ── the announcement a person has to act on (#104 on the pilot) ─────────────────────────────────
#
# Everything above proves the split HAPPENED and the record is honest. These prove the sentence
# the operator receives can be acted on — measured after podbeam #104 was split into three with
# one child the board refused, and the message said "drag them" under a list of three identical
# titles, none of them marked, above a reason cut mid-word.

def _split_message(monkeypatch, board, reasons="r", children=3):
    tracker, notifier = _patch_split(monkeypatch, board)
    _do_split(SplitInput(project="p", issue="37", reasons=reasons, children=[
        {"title": chr(97 + n), "objective": "o", "criteria": ["c"]} for n in range(children)]))
    return notifier.sent[0]["message"]


def test_ONE_stuck_child_is_not_asked_for_in_the_plural(monkeypatch):
    """The half the reader acts on. With three cards listed and one refused, "drag them" leaves
    them unable to tell whether to move one card or all three."""
    said = _split_message(monkeypatch, _Board(ok_for={"101", "102"}))

    assert "drag that one" in said, said
    assert "drag those" not in said


def test_but_SEVERAL_are(monkeypatch):
    said = _split_message(monkeypatch, _Board(ok_for={"101"}))

    assert "drag those" in said, said
    assert "drag that one" not in said


def test_the_stuck_child_is_marked_ON_ITS_OWN_LINE(monkeypatch):
    """The sentence names a ref and the list repeated near-identical titles under it, so finding
    the card to move meant cross-referencing a number against them."""
    said = _split_message(monkeypatch, _Board(ok_for={"101", "102"}))

    # THE LIST LINES ONLY. The head names the ref too ("could not move #103 to TO-DO"), so a
    # search for the ref across the whole message finds the sentence rather than the list entry —
    # and the guard then passes or fails for the wrong reason.
    listed = [ln for ln in said.splitlines() if ln.startswith("  ")]
    stuck = [ln for ln in listed if "#103" in ln]

    assert stuck and "NOT QUEUED" in stuck[0], said
    assert all("NOT QUEUED" not in ln for ln in listed if "#101" in ln), (
        "a queued child is marked as stuck — a marker on every line marks nothing")
    # THE BULLET IS PART OF THE MARK, and it is the half a reader sees first when skimming a
    # list. Measured: a cut that gave every line the warning bullet left the suffix correct and
    # the list uniformly alarming, and a guard reading only the suffix stayed green.
    assert stuck[0].lstrip().startswith("⚠"), stuck[0]
    assert all(ln.lstrip().startswith("•") for ln in listed if "#101" in ln or "#102" in ln), (
        "a queued child carries the warning bullet")


def test_and_the_REASON_ends_where_a_reader_can_follow_it(monkeypatch):
    """The pilot's own reason, verbatim: a hard slice left `…quota conflict) to).`"""
    real = ("Fails Small/Independent: bundles a novel, high-risk scheduling/quota engine change "
            "(single→dual episode generation, with an unaddressed 1/day quota conflict) together "
            "with a UI split")

    said = _split_message(monkeypatch, _Board(), reasons=real)

    head = said.split(":")[0] + ":" if ":" in said else said
    assert " to…" not in said and "to)." not in said, said[:300]
    assert "…" in said, "a reason that was cut says nothing about being cut"
    assert head
