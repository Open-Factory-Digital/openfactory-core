"""The delivery is not done until the CLIENT says it is — ADR-0025.

WHAT THIS REPLACES. `delivered()` closed a loop when the BOARD closed the issues, announced it,
and moved on. That is the factory agreeing with itself: it says the tickets are shut, and nothing
at all about whether the person who asked got what they wanted. A product owner whose definition
of done is "the tickets are closed" is precisely the product owner nobody wants, and this platform
is sold on replacing that role rather than imitating its worst habit.

So the announcement now OPENS an acceptance loop and only the client's own answer closes it —
`worked` or `did-not-work`, in their words. Never by time: an unanswered acceptance stays visibly
open, because silence is not acceptance.

The tests are ordered by how easy each is to get wrong:

  1. the verdict reader, where a complaint containing "resolveu" must never read as success;
  2. the sweep, which must OPEN the loop while announcing (production orchestration, not helpers);
  3. the conversation, which must CLOSE it from a real message through `handle()`;
  4. and the negative space — silence, ambiguity, and a pending draft that outranks it.
"""

from __future__ import annotations

import pytest

import openfactory.adapters.channel as channel_pkg
import openfactory.memory.store as loop_store
import openfactory.runtime.temporal.activities as activities_mod
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.memory.ledger import ACCEPTANCE, DELIVERY, fold, open_loop, waiting
from openfactory.product import followup
from openfactory.product.triage import Ticket, TriageReport
from openfactory.runtime.temporal.activities import _product_followup


def _project():
    return Project(name="books", repo_path="/t",
                   # THE CLIENT THIS SUITE IS ABOUT IS BRAZILIAN (#160). It was implicit
                   # while every composer wrote pt-BR unconditionally; now that they take
                   # the project's language, saying so is what proves the wiring — an
                   # unset language answers in English, which is the product's default.
                   language="pt-BR",
                   tracker=ProviderRef(kind="github", repo="a/b"),
                   forge=ProviderRef(kind="github", repo="a/b"),
                   product=ProductConfig(docs_repo="a/docs", channel_id="C0PROD",
                                         admins=["U1"], agent_name="Nina"))


class _Channel:
    def __init__(self):
        self.posts: list[str] = []

    def say(self, *, project, channel, text):
        self.posts.append(text)
        return True

    def mention(self, person, **kw):
        return person

    def client(self, project):
        return None


class _Sink:
    def __init__(self):
        self.rows: list = []

    def record(self, rec):
        self.rows.append(rec)


class _Module:
    def __init__(self, tickets=None):
        self._board_tickets = tickets or []
        self.token = None


@pytest.fixture(autouse=True)
def _clean_pending():
    """`pc._PENDING` is module state shared with every other file in the run; a leaked draft from
    a neighbouring file used to break two tests here purely by ordering."""
    import openfactory.product.channel as pc

    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


@pytest.fixture()
def wired(monkeypatch):
    """The ledger as a list — append-only like the real one — plus the channel and sink.

    `land_open_proposals` is faked at the SAME seam production routes through: the sweep's step 7
    calls it on every pass, and it reaches a real forge otherwise — live API calls against the
    shared App rate limit, from a unit test. It used to be `authoring._gh` that was faked, one
    layer down; the sweep speaks to the port now (#95) and the port IS the seam."""
    import openfactory.product.authoring as authoring

    channel, sink, rows = _Channel(), _Sink(), []
    channel.sweep_calls = []
    monkeypatch.setattr(channel_pkg, "build_channel", lambda p=None: channel)
    monkeypatch.setattr(activities_mod, "_metrics_sink", lambda *a, **k: sink)
    monkeypatch.setattr(loop_store, "read", lambda project: list(rows))
    monkeypatch.setattr(loop_store, "write", lambda project, loops: rows.extend(loops))
    monkeypatch.setattr(authoring, "land_open_proposals",
                        lambda **kw: channel.sweep_calls.append(kw) or [])
    return channel, rows


# ── 1. the verdict reader ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("text", "expected"), [
    ("sim", "worked"),
    ("sim, resolveu", "worked"),
    ("funcionou perfeitamente", "worked"),
    ("beleza, resolvido", "worked"),
    # "ok" is NOT an acceptance. It used to be, and "ok, entendi" therefore closed a delivery as
    # signed off — a false accept, the expensive direction. It now reaches the model judge
    # (ADR-0029) rather than being decided by a word list.
    ("ok", ""),
    ("beleza", ""),
    ("conferi", ""),
    ("testei", ""),          # says somebody tested; says NOTHING about the outcome
    # a complaint that CONTAINS a working word — the failure that must never happen
    ("não resolveu", "did-not-work"),
    ("funcionou mas ainda trava", "did-not-work"),
    ("ainda acontece", "did-not-work"),
    ("continua duplicando", "did-not-work"),
    # not an answer at all
    ("e o prazo?", ""),
    ("tudo bom?", ""),
    ("obrigado", ""),
    ("não sei se isso funciona bem para o nosso caso porque o time ainda não migrou", ""),
    ("", ""),
])
def test_the_verdict_is_read_from_the_clients_own_words(text, expected):
    assert followup.acceptance_verdict(text) == expected, text


# ── 2. the sweep opens it ──────────────────────────────────────────────────────────────────────
def test_announcing_a_delivery_OPENS_an_acceptance_loop(wired):
    """Driven through `_product_followup`, not the helper: the whole defect class in this repo is
    a capability that works in isolation and is wired to nothing."""
    channel, rows = wired
    rows.append(open_loop(DELIVERY, "7", owner="product", ts="2026-07-28T10:00:00+00:00",
                          context={"issues": "500", "person": "rob"}))
    module = _Module([Ticket(number=500, title="a", state="closed", column="Done", body="")])

    result = _product_followup(_project(), module, TriageReport(), _project().product)

    assert "accepting:1" in result, result
    opened = [x for x in waiting(fold(rows), owner="product") if x.kind == ACCEPTANCE]
    assert len(opened) == 1, [x.kind for x in fold(rows)]
    assert opened[0].subject == "7"
    assert opened[0].about == "C0PROD", "the acceptance must remember which room it was asked in"


def test_the_announcement_ASKS_rather_than_declaring_victory(wired):
    """The sentence is the product. 'está pronto' alone trains a client to ignore delivery notes;
    a question with a stated exit is what a colleague sends."""
    channel, rows = wired
    rows.append(open_loop(DELIVERY, "7", owner="product", ts="2026-07-28T10:00:00+00:00",
                          context={"issues": "500"}))

    _product_followup(_project(), _Module(
        [Ticket(number=500, title="a", state="closed", column="Done", body="")]),
        TriageReport(), _project().product)

    said = "\n".join(channel.posts)
    assert "conferir" in said, said
    assert "não quero dar como resolvido" in said, "no exit offered — that is a chase, not a check"


def test_the_delivery_loop_still_closes_so_it_is_never_announced_twice(wired):
    channel, rows = wired
    rows.append(open_loop(DELIVERY, "7", owner="product", ts="2026-07-28T10:00:00+00:00",
                          context={"issues": "500"}))
    module = _Module([Ticket(number=500, title="a", state="closed", column="Done", body="")])
    project = _project()

    _product_followup(project, module, TriageReport(), project.product)
    first = len(channel.posts)
    _product_followup(project, module, TriageReport(), project.product)

    delivered_again = [p for p in channel.posts[first:] if "está pronto" in p]
    assert not delivered_again, f"announced the same delivery twice: {channel.posts[first:]}"


# ── 3. the conversation closes it ──────────────────────────────────────────────────────────────
def _module_with_ledger(rows):
    from openfactory.product.module import ProductModule

    class _M(ProductModule):
        def __init__(self):
            self.project = _project()

    return _M()


def test_a_client_saying_it_worked_CLOSES_the_loop_through_handle(wired, monkeypatch):
    """End to end from a real message: `handle()` → `settle_acceptance` → ledger row."""
    import openfactory.product.channel as pc

    channel, rows = wired
    rows.append(open_loop(ACCEPTANCE, "7", owner="product", about="C0PROD",
                          ts="2026-07-28T10:00:00+00:00", context={"asked_by": "rob"}))

    reply = pc.handle(_project(), text="sim, resolveu", user="U1", thread="C0PROD",
                      channel="C0PROD", module=_module_with_ledger(rows))

    assert reply and "encerrado" in reply, reply
    closed = [x for x in fold(rows) if x.kind == ACCEPTANCE and x.state == "closed"]
    assert closed and closed[0].outcome == "worked", [(x.state, x.outcome) for x in fold(rows)]


def test_a_client_saying_it_did_NOT_work_closes_it_as_rejected_and_invites_the_defect(wired):
    """The half that matters commercially: 'não resolveu' must NOT leave the delivery counted as
    accepted, and must route the person towards filing what is still wrong."""
    import openfactory.product.channel as pc

    channel, rows = wired
    rows.append(open_loop(ACCEPTANCE, "7", owner="product", about="C0PROD",
                          ts="2026-07-28T10:00:00+00:00"))

    reply = pc.handle(_project(), text="não, continua duplicando", user="U1", thread="C0PROD",
                      channel="C0PROD", module=_module_with_ledger(rows))

    assert reply and "NÃO está resolvido" in reply, reply
    assert "defeito" in reply, "the person was not told how the complaint gets recorded"
    closed = [x for x in fold(rows) if x.kind == ACCEPTANCE and x.state == "closed"]
    assert closed and closed[0].outcome == "did-not-work", closed


# ── 4. the negative space ──────────────────────────────────────────────────────────────────────
def test_an_ambiguous_message_does_NOT_close_it(wired):
    """Silence and ambiguity are not acceptance. A loop closed on a guess is a claim of success
    made on the client's behalf — the exact thing ADR-0021 forbids."""
    import openfactory.product.channel as pc

    channel, rows = wired
    rows.append(open_loop(ACCEPTANCE, "7", owner="product", about="C0PROD",
                          ts="2026-07-28T10:00:00+00:00"))

    pc.handle(_project(), text="e quando sai o próximo?", user="U1", thread="C0PROD",
              channel="C0PROD", module=_module_with_ledger(rows))

    still = [x for x in waiting(fold(rows), owner="product") if x.kind == ACCEPTANCE]
    assert still, "an unrelated question closed a delivery"


def test_a_yes_on_a_PENDING_DRAFT_still_confirms_the_draft(wired, monkeypatch):
    """Ordering contract: a staged proposal is a question just asked and outranks an acceptance
    from days ago. Getting this backwards would silently swallow every confirmation."""
    import openfactory.product.channel as pc

    channel, rows = wired
    rows.append(open_loop(ACCEPTANCE, "7", owner="product", about="C0PROD",
                          ts="2026-07-28T10:00:00+00:00"))
    noted: list = []

    class _M:
        def settle_acceptance(self, text):
            raise AssertionError("the acceptance path must not run while a draft is pending")

        def note_fact(self, *, term, body, said_by, where=""):
            noted.append(term)
            from types import SimpleNamespace
            return SimpleNamespace(ok=True, existed=False, detail="", ref="")

    pc.remember("C0PROD", {"kind": "fact", "term": "erp", "body": "usa Primavera", "said_by": "U1"})
    pc.handle(_project(), text="sim", user="U1", thread="C0PROD", channel="C0PROD", module=_M())

    assert noted == ["erp"], "the pending draft lost its confirmation to the acceptance path"


def test_an_unanswered_acceptance_is_chased_once_and_never_auto_closed(wired):
    """It stays open until a person answers. Time closing it would turn 'nobody replied' into
    'the client accepted', which is the most expensive lie this system could tell."""
    channel, rows = wired
    rows.append(open_loop(ACCEPTANCE, "7", owner="product", about="C0PROD",
                          ts="2020-01-01T00:00:00+00:00", context={"asked_by": "rob"}))
    project = _project()

    _product_followup(project, _Module(), TriageReport(), project.product)
    chases = [p for p in channel.posts if "chegou a conferir" in p]
    _product_followup(project, _Module(), TriageReport(), project.product)
    chases_after = [p for p in channel.posts if "chegou a conferir" in p]

    assert len(chases) == 1, f"chased {len(chases)} times in one pass"
    assert len(chases_after) == 1, "chased again — a reminder loop the client cannot escape"
    still = [x for x in waiting(fold(rows), owner="product") if x.kind == ACCEPTANCE]
    assert still, "time closed an acceptance nobody gave"


# ── 5. ambiguity goes to a model, not to a word list ───────────────────────────────────────────
#: The false accepts that shipped. Each closed a delivery as SIGNED OFF on the strength of a word
#: that does not say the thing works — "ok, entendi" is an acknowledgement, and "testei" says
#: somebody tested while saying nothing at all about the outcome. A false accept is the expensive
#: direction: the record then claims the client approved something they never confirmed.
_WAS_A_FALSE_ACCEPT = ["ok", "ok, entendi", "beleza", "conferi", "testei", "isso"]


@pytest.mark.parametrize("text", _WAS_A_FALSE_ACCEPT)
def test_an_acknowledgement_is_no_longer_a_signed_off_delivery(text):
    assert followup.acceptance_verdict(text) == "", f"{text!r} still closes a delivery by itself"


def test_an_ambiguous_reply_is_JUDGED_when_something_is_awaiting_acceptance(wired, monkeypatch):
    """It is not "no answer" — it goes to a model. Driven through `settle_acceptance`, which is what
    the channel calls, so the wiring is part of the assertion."""
    channel, rows = wired
    rows.append(open_loop(ACCEPTANCE, "7", owner="product", about="C0PROD",
                          ts="2026-07-29T10:00:00+00:00"))
    mod = _module_with_ledger(rows)
    seen: dict = {}

    def _judge(text):
        seen["text"] = text
        return "worked"

    monkeypatch.setattr(mod, "_judge_acceptance", _judge)
    settled = mod.settle_acceptance("ok, entendi")

    assert seen.get("text") == "ok, entendi", "the ambiguous reply never reached the judge"
    assert settled and settled[0] == "worked"


def test_NOTHING_awaiting_acceptance_costs_no_model_call(wired, monkeypatch):
    """An ordinary message must not pay for a judgment. The ledger is read first, and with no open
    acceptance there is nothing to judge."""
    channel, rows = wired          # empty ledger
    mod = _module_with_ledger(rows)
    called: list = []
    monkeypatch.setattr(mod, "_role", lambda **kw: called.append(1))

    assert mod.settle_acceptance("ok, entendi") is None
    assert not called, "a model was asked about an acceptance nobody is waiting for"


def test_a_FAILED_judgment_leaves_the_delivery_open(wired, monkeypatch):
    """The safe direction, and it is asymmetric on purpose: an open acceptance costs one reminder,
    a wrong `worked` records a sign-off the client never gave."""
    channel, rows = wired
    rows.append(open_loop(ACCEPTANCE, "7", owner="product", about="C0PROD",
                          ts="2026-07-29T10:00:00+00:00"))
    mod = _module_with_ledger(rows)

    def _boom(text):
        raise RuntimeError("harness down")

    monkeypatch.setattr(mod, "_judge_acceptance", _boom)
    with pytest.raises(RuntimeError):
        mod.settle_acceptance("ok")
    still = [x for x in waiting(fold(rows), owner="product") if x.kind == ACCEPTANCE]
    assert still, "a broken judge closed a delivery"


def test_the_judge_reads_did_not_work_before_worked():
    """"did-not-work" CONTAINS "work". A naive scan of the model's one-word answer would read a
    rejection as an acceptance — the one direction that must never fail."""
    import inspect

    from openfactory.product.role import ProductRole

    src = inspect.getsource(ProductRole.judge_acceptance)
    order = src.index('"did-not-work", "worked"')
    assert order > 0, "the verdict scan does not put did-not-work first"


# ── 5b. the sweep must not spend the production rate limit from a test ────────────────────────
def test_the_sweep_reaches_the_landing_step_through_the_faked_seam(wired):
    """Reach-proofing the fixture itself. The sweep's proposal-landing step runs on every pass; if
    it stops routing through `authoring.land_open_proposals` (or the fixture stops patching it),
    this goes red — instead of the suite silently going back to live forge calls."""
    channel, rows = wired

    _product_followup(_project(), _Module(), TriageReport(), _project().product)

    assert channel.sweep_calls, "step 7 never reached the landing seam — a live forge would be used"
    assert all("docs_repo" in call for call in channel.sweep_calls), channel.sweep_calls


# ── 6. closed is not delivered ─────────────────────────────────────────────────────────────────
def test_work_closed_as_NOT_PLANNED_is_never_announced_as_delivered(wired):
    """The sweep read `state != "open"`, so an issue closed as a duplicate or as not-planned counted
    as a delivery and the client was told "o que foi pedido no requisito N está pronto" about work
    that was CANCELLED. Eleven cards were closed as not_planned on 2026-07-29 in one sitting — this
    was one sweep away from happening for real."""
    from openfactory.runtime.temporal.activities import _closed_issue_numbers

    channel, rows = wired
    rows.append(open_loop(DELIVERY, "7", owner="product", ts="2026-07-28T10:00:00+00:00",
                          context={"issues": "500"}))
    module = _Module([Ticket(number=500, title="a", state="closed", state_reason="not_planned",
                             column="Done", body="")])

    assert _closed_issue_numbers(module) == set(), "cancelled work counts as delivered"
    _product_followup(_project(), module, TriageReport(), _project().product)
    assert not [p for p in channel.posts if "está pronto" in p], channel.posts


def test_work_closed_as_COMPLETED_is_still_announced(wired):
    from openfactory.runtime.temporal.activities import _closed_issue_numbers

    channel, rows = wired
    rows.append(open_loop(DELIVERY, "7", owner="product", ts="2026-07-28T10:00:00+00:00",
                          context={"issues": "500"}))
    module = _Module([Ticket(number=500, title="a", state="closed", state_reason="completed",
                             column="Done", body="")])

    assert _closed_issue_numbers(module) == {"500"}
    _product_followup(_project(), module, TriageReport(), _project().product)
    assert [p for p in channel.posts if "está pronto" in p], channel.posts


def test_a_tracker_that_reports_NO_reason_still_delivers():
    """Excluded by NAME rather than requiring "completed", deliberately: a tracker that omits the
    field (or a provider with no such concept) must keep announcing real deliveries. Requiring the
    positive signal would trade a false delivery for a LOST one, which is the worse trade — a
    delivery nobody announces is work the client never learns about."""
    from openfactory.runtime.temporal.activities import _closed_issue_numbers

    module = _Module([Ticket(number=500, title="a", state="closed", column="Done", body="")])
    assert _closed_issue_numbers(module) == {"500"}


def test_the_board_actually_ASKS_for_the_close_reason():
    """Reach: the rule is worthless if the close reason is never fetched — the field would be "" on
    every ticket and every cancelled card would look completed again.

    ASSERTED AS BEHAVIOUR NOW, NOT AS THE TEXT `stateReason`. That literal was the GitHub CLI's
    field name in `product/board.py`'s own query; the tickets arrive through
    `TrackerAdapter.list_tickets` since #97, where the field is `state_reason` and each provider
    folds its own spelling into the port's vocabulary. Counting a vendor's JSON key in a file that
    no longer speaks to a vendor would be a guard that passes for the wrong reason — so this drives
    the reader with a summary that carries the reason and checks it comes out the other side."""
    from openfactory.adapters.tracker.base import TicketSummary
    from openfactory.product import board

    class _Tracker:
        def list_tickets(self, *, state="all", updated_since="", limit=0):
            return [TicketSummary(ref="500", title="a", state="closed",
                                  state_reason="not_planned", updated_at="2026-07-29T00:00:00Z")]

    class _Project:
        name = "reason"

        class tracker:
            kind = "github"
            repo = "o/r"
            options: dict = {}

        forge = None

    board.forget_board()
    try:
        tickets, error = board.read_board(_Project(), tracker=_Tracker())
    finally:
        board.forget_board()

    assert error == "" and len(tickets) == 1
    assert tickets[0].state_reason == "not_planned", "the board dropped the close reason"
    assert tickets[0].delivered is False, "a card closed as not-planned read as delivered work"
