"""_product_followup executed END TO END — the function where the audit's only hard crash lived.

Every prior test drove the PURE halves (followup.py's functions, the voice texts) and none ever ran
the orchestration in activities.py. That gap is exactly where a two-part unpack over a three-part
key sat undetected: syntactically valid, green everywhere, and a guaranteed ValueError on the first
completed delivery — after which every future sweep died on the same line and Nina went permanently
mute. "Coverage" that never executes the wiring is how this repo's signature defect wears a test
suite.

The fakes here are BOUNDARY fakes only (channel, ledger store, board tickets); everything between —
close, announce, ask, cap, chase — is the production code.
"""

from __future__ import annotations

import pytest

import openfactory.adapters.channel as channel_pkg
import openfactory.memory.store as loop_store
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.memory.ledger import DELIVERY, QUESTION, open_loop
from openfactory.product.triage import Ticket, TriageReport
from openfactory.runtime.temporal.activities import _product_followup


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

    def start_listeners(self):
        return []


class _Store:
    """The ledger as a list — append-only like the real one."""

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
    return channel, store


def test_a_completed_defect_delivery_announces_THE_FIX_and_does_not_crash(wired):
    """The crash line, executed: a closed defect issue folds through delivered() (three-part
    keys), the announce loop unpacks it, and the client hears about their PROBLEM — never about
    'requisito defeito-88', a number they cannot recognise."""
    channel, store = wired
    store.rows = [open_loop(DELIVERY, "defeito-88", owner="product", ts="2026-07-28T10:00:00+00:00",
                            context={"issues": "88", "defect": "1"})]
    module = _Module([Ticket(number=88, title="Conciliação duplicada", state="closed",
                             column="Done", body="")])

    result = _product_followup(_project(), module, TriageReport(), _project().product)

    assert "closed:1" in result, result
    fix_posts = [p for p in channel.posts if "corrigido" in p]
    assert fix_posts, f"the fix was never announced: {channel.posts}"
    assert "requisito" not in fix_posts[0], fix_posts[0]
    assert "88" not in fix_posts[0], "an internal issue number leaked to the client"


def test_a_requirement_delivery_still_uses_the_requirement_sentence(wired):
    channel, store = wired
    store.rows = [open_loop(DELIVERY, "7", owner="product", ts="2026-07-28T10:00:00+00:00",
                            context={"issues": "500,501"})]
    module = _Module([Ticket(number=500, title="a", state="closed", column="Done", body=""),
                      Ticket(number=501, title="b", state="closed", column="Done", body="")])

    _product_followup(_project(), module, TriageReport(), _project().product)

    assert any("requisito 7" in p for p in channel.posts), channel.posts


def test_the_ask_pass_caps_and_names_the_ticket(wired):
    """Live board findings become at most MAX_QUESTIONS_PER_PASS questions, each naming the card
    by TITLE — 'sobre o #412' alone, to an audience that never opens the board, is a question
    nobody can even understand."""
    from openfactory.product.followup import MAX_QUESTIONS_PER_PASS
    from openfactory.product.triage import Observation

    channel, store = wired
    findings = [Observation(ticket=n, kind="no-criteria", detail="x") for n in range(400, 410)]
    tickets = [Ticket(number=n, title=f"Card {n}", state="open", column="Backlog", body="")
               for n in range(400, 410)]

    _product_followup(_project(), _Module(tickets), TriageReport(observations=findings),
                      _project().product)

    asks = [p for p in channel.posts if "sobre o #" in p]
    assert len(asks) == 1, f"a batch must be ONE message, got {len(asks)}: {channel.posts}"
    assert asks[0].count("sobre o #") == MAX_QUESTIONS_PER_PASS, asks[0]
    assert "(Card 400)" in asks[0], asks[0]


def test_the_chase_pass_wears_the_same_cap(wired):
    """Thirteen pre-cap questions went out in one real burst (2026-07-28). Uncapped, the 48h chase
    would replay all thirteen as one burst of reminders a week later — the flood arriving twice."""
    from openfactory.product.followup import MAX_QUESTIONS_PER_PASS

    channel, store = wired
    store.rows = [open_loop(QUESTION, str(n), owner="product", about="no-criteria",
                            ts="2026-07-20T10:00:00+00:00", context={"asked": "x", "person": ""})
                  for n in range(135, 148)]  # the actual thirteen
    # the findings are all still live, so nothing closes and everything is chase-eligible
    from openfactory.product.triage import Observation

    findings = [Observation(ticket=n, kind="no-criteria", detail="x") for n in range(135, 148)]

    _product_followup(_project(), _Module([]), TriageReport(observations=findings),
                      _project().product)

    chases = [p for p in channel.posts if "voltando no" in p]
    assert len(chases) == MAX_QUESTIONS_PER_PASS, f"{len(chases)} chases in one pass"
    assert "há 2 dias" not in chases[0], "the interval must be computed, never the old hardcode"


def test_a_resolved_finding_closes_its_question_without_a_word(wired):
    """The board fixed it → the loop closes as observed; nobody needs a message about it."""
    channel, store = wired
    store.rows = [open_loop(QUESTION, "412", owner="product", about="no-criteria",
                            ts="2026-07-28T10:00:00+00:00", context={"asked": "x"})]

    result = _product_followup(_project(), _Module([]), TriageReport(observations=[]),
                               _project().product)

    assert "closed:1" in result, result
    closed = [x for x in store.rows if x.state == "closed"]
    assert closed and closed[0].outcome == "resolved"
