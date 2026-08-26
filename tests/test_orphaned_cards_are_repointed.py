"""A card citing a requirement that was retired, repaired without anybody asking — and said once.

THE LIVE STATE THIS EXISTS FOR: thirteen cards cite REQ-0004, pinned to a file and a commit, under
a printed rule saying nothing in the issue may go beyond that requirement. REQ-0004 was superseded
by REQ-0006 — the client's single accepted promise — and every one of those cards is something the
floor can pick up and build against within the hour.

So the repair rides the HOURLY tech-lead round, not the weekly product sweep, and the tests that
matter are about restraint rather than capability: a round with nothing to repair must cost
nothing and say nothing, the repair must reach the client exactly once, in their words, and a
message the channel never delivered must not be remembered as delivered.

The weekly sweep is here too, at the end, because it keeps its memory in the same table by the same
mechanism — and because the rule this repair wrote down to justify leaving its siblings alone ("a
snapshot is safe, those facts are re-derived from live state") is false for the sweep's row, which
is the only copy of "I have already introduced myself to this client".

Boundary fakes only — the channel, the telemetry table, the product module's board operations.
Everything between is the production orchestration in activities.py. No live calls.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

import openfactory.adapters.channel as channel_pkg
import openfactory.api.metrics_view as metrics_view
import openfactory.product.module as product_module
import openfactory.runtime.temporal.activities as acts
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.product.authoring import WriteResult
from openfactory.product.triage import TriageReport
from openfactory.product.voice import jargon_in

ACTIVITY_LOG = "temporalio.activity"


class _Channel:
    """A channel whose delivery can be turned off — `say` returns False, never raises (base.py)."""

    def __init__(self):
        self.deliver = True
        self.posts: list[str] = []      # what the client actually received
        self.attempts: list[str] = []   # what the round tried to say

    def say(self, *, project, channel, text):
        self.attempts.append(text)
        if self.deliver:
            self.posts.append(text)
        return self.deliver


class _Module:
    """The board's two orphan operations, in the shape module.py actually returns them.

    ONE RESULT PER CARD WRITTEN — a card whose citation already read correctly is skipped without
    one, so the result list is neither the same length as the orphan list nor in step with it.

    `repoint_orphans` is IDEMPOTENT the way the real one is: a repaired card stops being an orphan,
    which is exactly why the announcement cannot be rediscovered from the board on a later round."""

    def __init__(self, orphans=(), refuses=(), unchanged=()):
        self.orphans = list(orphans)      # (card, requirement cited, successor)
        self.refuses = set(refuses)       # cards whose write comes back ok=False
        self.unchanged = set(unchanged)   # cards that needed no write, so produce no result at all
        self.reads = 0
        self.writes = 0
        self.token = "tok"

    def orphaned_cards(self):
        self.reads += 1
        # THE REF IS A STRING, because `Ticket.number` is (C-05) — and this fake used to accept
        # whatever a test handed it. Every test in this file passed integers, so `card in written`
        # compared a str to a set of ints and was FALSE on every board; the guards below asserted
        # the round's summary line and it read "clean" for the same reason the production one did.
        # Refusing here is what stops the fixture from modelling a shape the module cannot return.
        bad = [c for c, _cited, _succ in self.orphans if not isinstance(c, str)]
        assert not bad, f"a card ref is the provider's own string, never {bad!r}"
        return list(self.orphans)

    def repoint_orphans(self, *, actor: str = ""):
        self.writes += 1
        results, done = [], []
        for card, _cited, successor in self.orphans:
            if card in self.unchanged:
                continue
            ok = card not in self.refuses
            results.append(WriteResult(
                ok=ok, ref=f"#{card}",
                detail=f"passou a executar o requisito {successor}" if ok
                else f"não consegui atualizar o #{card}"))
            if ok:
                done.append(card)
        self.orphans = [o for o in self.orphans if o[0] not in done]
        return results


class _Table:
    """The telemetry table both hourly memories live in — written as `DynamoMetricsSink` writes it
    and read back as `scan_records` returns it, so the round trip under test is the real one."""

    def __init__(self):
        self.items: list[dict] = []

    def record(self, rec):
        item = {**rec.dynamo_key()}
        for key, value in rec.model_dump().items():
            if value is None or value == "" or value == {}:
                continue
            item[key] = str(value) if isinstance(value, (int, float)) else value
        self.items.append(item)

    def scan(self, *a, **kw):
        return list(self.items)


def _project():
    return Project(name="books", repo_path="/t", language="pt-BR",
                   tracker=ProviderRef(kind="github", repo="a/b"),
                   forge=ProviderRef(kind="github", repo="a/b"),
                   product=ProductConfig(docs_repo="a/b", channel_id="C0PROD",
                                         agent_name="Nina"))


@pytest.fixture()
def wired(monkeypatch):
    """The seams the repair crosses: the channel, the telemetry table, the product module."""
    channel, table, built = _Channel(), _Table(), []

    def _build(project=None):
        built.append(getattr(project, "name", ""))
        return channel

    monkeypatch.setattr(channel_pkg, "build_channel", _build)
    monkeypatch.setattr(acts, "_metrics_sink", lambda: table)
    monkeypatch.setattr(metrics_view, "scan_records", table.scan)
    monkeypatch.setattr("openfactory.memory.transcript.record", lambda *a, **k: "")
    return channel, table, built


def _with(monkeypatch, module):
    monkeypatch.setattr(product_module, "ProductModule", lambda project, **kw: module)
    return module


# ── the quiet round: almost every round ────────────────────────────────────────────────────────

def test_a_round_with_no_orphans_says_nothing_logs_nothing_and_writes_nothing(
        wired, monkeypatch, caplog):
    """Expected to find nothing almost every hour it runs. A repair that reports a clean board on
    the hour is wallpaper by the second day, and then it is invisible on the day it repairs
    something. The board WRITE is what must not happen — the read is the question itself."""
    channel, table, built = wired
    module = _with(monkeypatch, _Module())

    with caplog.at_level(logging.DEBUG, logger=ACTIVITY_LOG):
        assert acts._repoint_product_orphans(_project()) == "clean"

    assert module.writes == 0, "reached for the write operation with nothing to repair"
    assert channel.attempts == [] and built == [], "built a channel with nothing to say"
    assert [r.getMessage() for r in caplog.records if r.name == ACTIVITY_LOG] == []
    assert table.items == [], "an hourly repair with nothing to repair still wrote a memory row"


def test_a_project_without_a_requirements_repo_is_left_alone(wired, monkeypatch):
    """The rounds run for every project with a floor; this repair belongs to the ones whose cards
    cite a requirement at all. Nothing to read means nothing to repair."""
    channel, _table, _built = wired
    module = _with(monkeypatch, _Module(orphans=[("510", 4, 6)]))
    project = _project()
    project.product.docs_repo = ""

    assert acts._repoint_product_orphans(project) == "off"
    assert module.reads == 0 and channel.attempts == []


def test_a_project_with_nobody_to_tell_is_still_repaired_and_told_when_there_is(wired, monkeypatch):
    """A project can have a docs repo and a board and no product channel — a second deployment
    onboarded before its channel exists, or a channel removed. Gated on the channel, the CARDS were
    left citing the retired text for ever and the floor kept building the old promise: what a
    project without somebody to tell loses is the message, not the repair. The debt outlives the
    silence, so the day there is a channel the client hears it."""
    channel, _table, built = wired
    module = _with(monkeypatch, _Module(orphans=[("510", 4, 6)]))
    silent = _project()
    silent.product.channel_id = ""

    assert acts._repoint_product_orphans(silent) == "repointed:1 unannounced:1"
    assert module.orphans == [], "the card was left citing a requirement that no longer holds"
    assert channel.attempts == [] and built == [], "posted to a project with no product channel"

    assert acts._repoint_product_orphans(_project()) == "announced:1"
    assert "#510" in channel.posts[0], channel.posts[0]


# ── the repair, and the one message it earns ───────────────────────────────────────────────────

def test_orphans_are_repointed_announced_once_and_the_next_round_is_silent(
        wired, monkeypatch, caplog):
    """The criteria on those cards were written against a text that is no longer the promise, so
    the person who accepted the new one is told before work starts — and told once. A repair that
    re-announces itself every hour is the same wallpaper by a different route."""
    channel, _table, _built = wired
    module = _with(monkeypatch, _Module(orphans=[("510", 4, 6), ("512", 4, 6), ("513", 4, 6)]))

    with caplog.at_level(logging.DEBUG, logger=ACTIVITY_LOG):
        assert acts._repoint_product_orphans(_project()) == "repointed:3 announced:3"

    assert module.writes == 1
    assert len(channel.posts) == 1, channel.posts
    said = channel.posts[0]
    assert "requisito 6" in said and "#510, #512, #513" in said, said

    # ONE operator line, naming how many and which requirement they now cite
    lines = [r.getMessage() for r in caplog.records
             if "OPENFACTORY_PRODUCT_ORPHANS_REPOINTED" in r.getMessage()]
    assert len(lines) == 1, lines
    assert "#510,#512,#513" in lines[0] and "REQ-6" in lines[0], lines[0]

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=ACTIVITY_LOG):
        assert acts._repoint_product_orphans(_project()) == "clean"
    assert len(channel.posts) == 1, "the same repair was announced twice"
    assert [r.getMessage() for r in caplog.records if r.name == ACTIVITY_LOG] == []


def test_the_announcement_is_business_language_and_carries_no_machinery(wired, monkeypatch):
    """A file, a commit, a branch, a repository or the name of a status field in this channel is a
    person being handed something they were promised they would never have to operate."""
    channel, _table, _built = wired
    _with(monkeypatch, _Module(orphans=[("510", 4, 6), ("512", 4, 6)]))

    acts._repoint_product_orphans(_project())
    said = channel.posts[0]

    assert jargon_in(said) == [], said
    for machinery in ("REQ-", ".md", "requirements/", "req/", "main", "/", "0004", "0006",
                      "superseded", "Backlog", "TO-DO", "Done", "state", "column"):
        assert machinery not in said, f"{machinery!r} reached the client channel: {said}"
    assert said.startswith("Nina: ")


def test_the_client_hears_the_cards_the_writes_were_actually_about(wired, monkeypatch):
    """`repoint_orphans` returns one result per card WRITTEN, so a card that needed no write drops
    out of the list and everything after it shifts. Paired by position, the client is told about a
    card nobody touched while the repaired ones are never announced at all."""
    channel, _table, _built = wired
    _with(monkeypatch, _Module(orphans=[("510", 4, 6), ("512", 4, 6), ("513", 4, 6)],
                               unchanged={"510"}))

    assert acts._repoint_product_orphans(_project()) == "repointed:2 announced:2"
    assert "#512, #513" in channel.posts[0] and "#510" not in channel.posts[0], channel.posts[0]


def test_only_the_cards_the_board_actually_accepted_are_announced(wired, monkeypatch):
    """Claiming a repair that did not happen would tell the client that a card is on the live
    promise while it still cites the retired text — and the card would never be mentioned again."""
    channel, _table, _built = wired
    module = _with(monkeypatch, _Module(orphans=[("510", 4, 6), ("512", 4, 6)], refuses={"512"}))

    assert acts._repoint_product_orphans(_project()) == "repointed:1 refused:1 announced:1"
    assert "#510" in channel.posts[0] and "#512" not in channel.posts[0], channel.posts[0]

    # the refused card is still an orphan, so the next round tries it again
    module.refuses = set()
    assert acts._repoint_product_orphans(_project()) == "repointed:1 announced:1"
    assert "#512" in channel.posts[1], channel.posts[1]


def test_a_round_that_repaired_nothing_is_never_reported_as_clean(wired, monkeypatch, caplog):
    """THE COMMON FAILURE, not the rare one. Every one of these writes goes through one credential
    to one repository, so the ordinary shape is all of them refused at once — the exhausted quota
    of 2026-07-27, a rotated token, a permission removed. With no repair to log, no fact to
    remember and no sentence to send, the round used to pass in complete silence and report itself
    clean: thirteen cards citing a retired promise, hourly, indistinguishable in the activity's own
    output from a board with nothing wrong with it."""
    channel, table, _built = wired
    module = _with(monkeypatch, _Module(orphans=[("510", 4, 6), ("512", 4, 6), ("513", 4, 6)],
                                        refuses={"510", "512", "513"}))

    with caplog.at_level(logging.DEBUG, logger=ACTIVITY_LOG):
        assert acts._repoint_product_orphans(_project()) == "refused:3"

    lines = [r.getMessage() for r in caplog.records
             if "OPENFACTORY_PRODUCT_ORPHANS_REFUSED" in r.getMessage()]
    assert len(lines) == 1, caplog.text
    assert "#510,#512,#513" in lines[0] and "of=3" in lines[0], lines[0]

    assert module.orphans and channel.attempts == [], "claimed a repair the board refused"
    assert table.items == [], "remembered a repair that never happened"


def test_the_cards_the_board_would_not_take_are_named_even_when_others_were_repaired(
        wired, monkeypatch, caplog):
    """A partial refusal is the same silence wearing a success: the round reports what it repaired,
    and the cards it could not are named nowhere an operator will look."""
    channel, _table, _built = wired
    _with(monkeypatch, _Module(orphans=[("510", 4, 6), ("512", 4, 6), ("513", 4, 6)],
                               refuses={"512", "513"}))

    with caplog.at_level(logging.DEBUG, logger=ACTIVITY_LOG):
        assert acts._repoint_product_orphans(_project()) == "repointed:1 refused:2 announced:1"

    refused = [r.getMessage() for r in caplog.records
               if "OPENFACTORY_PRODUCT_ORPHANS_REFUSED" in r.getMessage()]
    assert len(refused) == 1 and "#512,#513" in refused[0] and "#510" not in refused[0], refused
    assert "#510" in channel.posts[0] and "#512" not in channel.posts[0], channel.posts[0]


# ── the other repair on the same round, and the same discipline ────────────────────────────────

def test_a_rescue_that_cannot_run_says_what_broke_it_and_what_the_client_will_hear(
        wired, monkeypatch, caplog):
    """The proposal rescue rides the same hourly round as the repair above, one call earlier, and
    fails the same ways: a rotated token, a renamed docs repo, a worker image without `gh`. Broken,
    the product role denies its own requirement to the client within ONE message — and the whole
    operator signal was a bare warning with no marker and no cause, which is neither greppable nor
    actionable. The lesson was learned three hundred lines below and not carried up."""
    import openfactory.product.authoring as authoring

    _channel, _table, _built = wired

    def _boom(**kw):
        raise RuntimeError("gh: command not found")

    monkeypatch.setattr(authoring, "land_open_proposals", _boom)

    with caplog.at_level(logging.DEBUG, logger=ACTIVITY_LOG):
        assert acts._land_product_proposals(_project(), token="tok") == []

    lines = [r.getMessage() for r in caplog.records
             if "OPENFACTORY_PRODUCT_PROPOSAL_LAND_FAILED" in r.getMessage()]
    assert len(lines) == 1, caplog.text
    assert "gh: command not found" in lines[0], lines[0]


def test_two_retired_chains_repaired_together_are_two_true_sentences(wired, monkeypatch):
    """Chains are independent — REQ-0003→REQ-0005 and REQ-0004→REQ-0006 retire on their own — and
    the debt also accumulates across rounds whose post was dropped, so one round covering two of
    them is ordinary. Joined into the sentence written for one, it reads "o requisito 5, 6, que é a
    promessa em vigor": ungrammatical, and false of every card it names, in the one sentence whose
    whole job is to say which promise a card now rests on."""
    channel, _table, _built = wired
    _with(monkeypatch, _Module(orphans=[("510", 4, 6), ("512", 4, 6), ("530", 3, 5)]))

    assert acts._repoint_product_orphans(_project()) == "repointed:3 announced:3"
    assert len(channel.posts) == 2, channel.posts

    five = next(p for p in channel.posts if "#530" in p)
    six = next(p for p in channel.posts if "#510" in p)
    assert "requisito 5" in five and "requisito 6" not in five and "#510" not in five, five
    assert "requisito 6" in six and "requisito 5" not in six and "#530" not in six, six
    assert "#510, #512" in six, six

    assert acts._repoint_product_orphans(_project()) == "clean"


def test_a_card_repaired_after_the_round_read_the_board_is_never_written_silently(
        wired, monkeypatch, caplog):
    """The board is asked once and written once, and it changes in between: the second read is a
    live one that merges whatever was edited since. A card whose citation moves onto the retired
    text inside that window is written to the client's board and dropped from the pairing — and it
    is not an orphan for a later round to rediscover. The sentence cannot be written truthfully
    from here (a write result carries no successor), so the write is at least loud."""
    channel, _table, _built = wired

    class _Racing(_Module):
        def repoint_orphans(self, *, actor: str = ""):
            self.orphans = [*self.orphans, ("530", 4, 6)]   # edited between the two reads
            return super().repoint_orphans(actor=actor)

    _with(monkeypatch, _Racing(orphans=[("510", 4, 6)]))

    with caplog.at_level(logging.DEBUG, logger=ACTIVITY_LOG):
        assert acts._repoint_product_orphans(_project()) == "repointed:1 announced:1"

    lines = [r.getMessage() for r in caplog.records
             if "OPENFACTORY_PRODUCT_ORPHANS_UNPAIRED" in r.getMessage()]
    assert len(lines) == 1 and "#530" in lines[0], caplog.text
    assert "#530" not in channel.posts[0], channel.posts[0]


# ── the ledger believes only what the channel confirmed (ADR-0021) ─────────────────────────────

def test_a_dropped_announcement_is_not_recorded_as_said(wired, monkeypatch):
    """The repair is IDEMPOTENT, so a repaired card stops being an orphan the moment it is fixed:
    a dropped post that had been recorded as announced could never be rediscovered from the board,
    and the client would simply never learn that the promise under their cards had changed."""
    channel, _table, _built = wired
    channel.deliver = False
    module = _with(monkeypatch, _Module(orphans=[("510", 4, 6), ("512", 4, 6), ("513", 4, 6)]))

    assert acts._repoint_product_orphans(_project()) == "repointed:3 announce-dropped:3"
    assert module.orphans == [], "the board write did not happen"
    assert channel.attempts and channel.posts == []

    # the channel comes back. The cards are no longer orphans — the debt is the memory's, not the
    # board's — and the SAME round pays it.
    channel.deliver = True
    assert acts._repoint_product_orphans(_project()) == "announced:3"
    assert len(channel.posts) == 1 and "#510, #512, #513" in channel.posts[0]

    assert acts._repoint_product_orphans(_project()) == "clean"
    assert len(channel.posts) == 1


def test_the_repair_memory_is_not_read_as_the_watchers_memory(wired):
    """Both hourly memories are `techlead_watch` rows. Read by kind alone, the repair's row is the
    newest one on every round after a repair, carries no `said`, and the watcher concludes it has
    never mentioned anything — restating every standing park on the hour."""
    _channel, _table, _built = wired
    acts._remember_watch("books", {"stuck:478": 18.0})
    acts._remember_repoint("books", {"510": 6}, {("510", 6)})

    assert acts._watch_history("books") == {"stuck:478": 18.0}
    assert acts._repoint_memory("books") == ({"510": 6}, {("510", 6)})


# ── what the memory is ABOUT: a card citing a requirement, not a card ───────────────────────────

def test_the_same_card_superseded_a_second_time_is_announced_a_second_time(wired, monkeypatch):
    """SUPERSESSION RECURS — this client's chain already ran 0002→0004→0006, three replacements in
    one day — so a card being repointed again is next week, not an edge case. Remembered as "this
    card was mentioned once", the second repair is silent: the cards execute a promise the client
    has never heard named, with criteria written against a text two supersessions old."""
    channel, _table, _built = wired
    module = _with(monkeypatch, _Module(orphans=[("510", 4, 6), ("512", 4, 6)]))
    assert acts._repoint_product_orphans(_project()) == "repointed:2 announced:2"

    # REQ-0006 is itself replaced; the same two cards are orphans again, onto a different promise
    module.orphans = [("510", 6, 8), ("512", 6, 8)]
    assert acts._repoint_product_orphans(_project()) == "repointed:2 announced:2"
    assert len(channel.posts) == 2, channel.posts
    assert "requisito 8" in channel.posts[1] and "#510, #512" in channel.posts[1]

    assert acts._repoint_product_orphans(_project()) == "clean"
    assert len(channel.posts) == 2, "the second repair was announced twice"


def test_a_memory_read_that_comes_back_empty_never_erases_an_unpaid_debt(wired, monkeypatch):
    """`scan_records` swallows its own failures — a throttled scan of a table that holds every
    agent run, job and message returns `[]`, exactly like a memory that has never been written.

    Read as the newest row and written as a snapshot, the next repair REPLACES the row recording
    thirteen cards nobody has been told about, and nothing can rediscover them: they stopped being
    orphans the moment they were repaired. Forgetting may cost a round and a repeated sentence. It
    may never cost a fact."""
    channel, table, _built = wired
    channel.deliver = False
    module = _with(monkeypatch, _Module(orphans=[("510", 4, 6), ("512", 4, 6), ("513", 4, 6)]))
    assert acts._repoint_product_orphans(_project()) == "repointed:3 announce-dropped:3"

    # the hour the scan is throttled, and the hour a new orphan appears
    blind = {"on": True}
    monkeypatch.setattr(metrics_view, "scan_records",
                        lambda *a, **k: [] if blind["on"] else table.scan())
    channel.deliver = True
    module.orphans = [("530", 4, 6)]
    assert acts._repoint_product_orphans(_project()) == "repointed:1 announced:1"
    assert "#530" in channel.posts[0] and "#510" not in channel.posts[0], channel.posts[0]

    blind["on"] = False
    assert acts._repoint_product_orphans(_project()) == "announced:3"
    assert "#510, #512, #513" in channel.posts[1], channel.posts[1]
    assert acts._repoint_product_orphans(_project()) == "clean"


def test_a_memory_written_before_the_pair_was_the_key_is_not_re_announced(wired, monkeypatch):
    """Rows in the older shape are in the live table: `announced` there is bare card numbers, and
    the requirement each was announced at is the one the same row recorded as repaired. Read as
    unnamed, every one of them is owed again and the client hears the whole repair a second time."""
    from datetime import UTC, datetime

    from openfactory.observability.metrics import MetricRecord

    channel, table, _built = wired
    table.record(MetricRecord(
        project="books", ticket=acts._REPOINT_ROLE, ts=datetime.now(UTC).isoformat(),
        kind=acts._WATCH_KIND, role=acts._REPOINT_ROLE,
        extra={"repaired": "510:6|512:6", "announced": "510|512"}))
    _with(monkeypatch, _Module())

    assert acts._repoint_product_orphans(_project()) == "clean"
    assert channel.attempts == []


# ── reached by the round, upstream of everything that can fail it ───────────────────────────────

def test_the_hourly_round_repoints_before_it_touches_temporal(wired, monkeypatch):
    """Built, tested and reached by nothing has happened fourteen times in this codebase. The
    repair also has to outlive a Temporal outage: a card citing a retired promise is not less
    dangerous on the day the floor cannot be queried."""
    import openfactory.runtime.temporal.connection as connection

    _channel, _table, _built = wired
    module = _with(monkeypatch, _Module(orphans=[("510", 4, 6)]))
    monkeypatch.setattr(acts, "ProjectRegistry",
                        lambda: type("R", (), {"get": lambda self, name: _project()})())
    monkeypatch.setattr(acts, "_land_product_proposals", lambda project, **kw: [])

    async def _down():
        raise RuntimeError("temporal unreachable")

    monkeypatch.setattr(connection, "connect", _down)

    with pytest.raises(RuntimeError):
        asyncio.run(acts.techlead_watch("books"))

    assert module.writes == 1, "the rounds never ran the repair"


def test_a_repair_that_raises_never_breaks_the_round(wired, monkeypatch):
    """Nothing this repair does may cost the round its report, or a client their answer."""
    channel, _table, _built = wired

    class _Broken(_Module):
        def orphaned_cards(self):
            raise RuntimeError("the board is unreadable")

    _with(monkeypatch, _Broken())

    assert acts._repoint_product_orphans(_project()) == "error"
    assert channel.attempts == []


def test_a_repair_that_raises_says_what_broke_it_where_an_operator_will_find_it(
        wired, monkeypatch, caplog):
    """A rotated Slack token or a bad registry entry makes this dead EVERY hour, with cards citing
    a retired requirement the whole time. Without the cause and a marker to alert on, that is one
    unattributable warning an hour and nothing anybody can act on."""
    _channel, _table, _built = wired

    class _Broken(_Module):
        def orphaned_cards(self):
            raise RuntimeError("slack token missing from the worker environment")

    _with(monkeypatch, _Broken())

    with caplog.at_level(logging.DEBUG, logger=ACTIVITY_LOG):
        assert acts._repoint_product_orphans(_project()) == "error"

    lines = [r.getMessage() for r in caplog.records
             if "OPENFACTORY_PRODUCT_ORPHANS_FAILED" in r.getMessage()]
    assert len(lines) == 1, caplog.text
    assert "slack token missing from the worker environment" in lines[0], lines[0]


# ── the third memory on this table, whose row is the only copy of a fact ────────────────────────
#
# The repair above accumulates deltas because its facts exist nowhere else once the board is fixed.
# The sweep's row is the only copy of something with no source at all: that this role has already
# introduced itself to this client. `scan_records` degrades to `[]` on a throttled scan of a table
# holding every agent run, job and message — the same shape as a store nobody has written — and the
# sweep read that absence as "we have never met".

class _SweepModule:
    """The board operations `product_sweep` reaches, with nothing wrong on the board."""

    def __init__(self, project=None, **kw):
        self._board_tickets: list = []
        self.token = "tok"

    def introduce(self):
        return "Oi! Sou a Nina, vou acompanhar o que vocês pedirem por aqui."

    def triage_board(self):
        return TriageReport(), None


@pytest.fixture()
def sweeping(wired, monkeypatch):
    """The weekly sweep over the same table, with the follow-through stubbed at its own seam."""
    monkeypatch.setattr(acts, "ProjectRegistry",
                        lambda: type("R", (), {"get": lambda self, name: _project()})())
    monkeypatch.setattr(product_module, "ProductModule", _SweepModule)
    monkeypatch.setattr(acts, "_product_followup", lambda *a, **k: "followed")
    return wired


def test_a_memory_that_answered_nothing_never_greets_a_client_it_has_already_met(
        sweeping, monkeypatch, caplog):
    """A client who has been working with Nina for weeks receives her arrival message again because
    a DynamoDB scan was throttled for one round. That absence is not the repetition the other
    memories on this table can afford: nothing on the board and nothing in the corpus says whether
    this role has ever spoken to this client, so the row is the fact itself."""
    channel, table, _built = sweeping
    acts._remember_sweep("books", ["1:no-criteria"], "2026-07-01T00:00:00+00:00", backlog=1)
    known = len(table.items)

    monkeypatch.setattr(metrics_view, "scan_records", lambda *a, **k: [])   # the throttled round
    with caplog.at_level(logging.DEBUG, logger=ACTIVITY_LOG):
        assert asyncio.run(acts.product_sweep("books")) == "memory-unproven"

    assert channel.attempts == [], "greeted a client the store could not vouch for"
    lines = [r.getMessage() for r in caplog.records
             if "OPENFACTORY_PRODUCT_SWEEP_MEMORY_UNPROVEN" in r.getMessage()]
    assert len(lines) == 1, caplog.text

    # the scan comes back: the sweep reads its own memory again and stays on the triage path
    monkeypatch.setattr(metrics_view, "scan_records", table.scan)
    assert asyncio.run(acts.product_sweep("books")).startswith("nothing-new")
    assert channel.attempts == [], "introduced itself to a client it had already met"
    assert len(table.items) > known, "the blind round left nothing for the next one to read"


def test_a_client_the_store_has_never_heard_of_is_still_greeted_a_round_later(sweeping):
    """The guard above must not cost the arrival itself. A store that answers nothing looks the
    same whether it is empty or unreachable, so the first round leaves a row saying only that the
    write landed — and the next round, reading it, has a store that has proved it can answer and no
    sweep recorded in it. That is the whole price: one cadence, never a stranger greeted twice."""
    channel, table, _built = sweeping

    assert asyncio.run(acts.product_sweep("books")) == "memory-unproven"
    assert channel.attempts == [], "greeted on an answer the store never gave"
    assert table.items, "left nothing behind, so this state would never end"

    assert asyncio.run(acts.product_sweep("books")) == "introduced"
    assert "Nina" in channel.posts[0], channel.posts[0]

    # and the arrival is remembered as one: the probe row is not a sweep that happened
    assert asyncio.run(acts.product_sweep("books")).startswith("clean")
    assert len(channel.posts) == 1, "introduced itself twice"


def test_an_arrival_the_store_would_not_record_is_said_where_an_operator_will_find_it(
        sweeping, monkeypatch, caplog):
    """The row is written after the introduction lands, and it is the only copy. Lost, the next
    sweep meets the client for the first time again — so a failed write is an ERROR with a marker,
    not a shrug, and it must never raise into the round that just posted."""
    channel, _table, _built = sweeping

    class _Full:
        def record(self, rec):
            raise RuntimeError("ProvisionedThroughputExceededException")

    monkeypatch.setattr(acts, "_metrics_sink", lambda: _Full())
    monkeypatch.setattr(metrics_view, "scan_records",
                        lambda *a, **k: [{"kind": "job", "pk": "other"}])   # store readable, empty

    with caplog.at_level(logging.DEBUG, logger=ACTIVITY_LOG):
        assert asyncio.run(acts.product_sweep("books")) == "introduced"

    assert len(channel.posts) == 1
    lines = [r.getMessage() for r in caplog.records
             if "OPENFACTORY_PRODUCT_SWEEP_UNREMEMBERED" in r.getMessage()]
    assert len(lines) == 1, caplog.text
    assert "ProvisionedThroughputExceededException" in lines[0], lines[0]
