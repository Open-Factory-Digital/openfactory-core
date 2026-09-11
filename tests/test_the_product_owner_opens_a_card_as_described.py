"""The product owner opens a card as the person described it — #33's first verb at the frontier.

THE FRONTIER IS THREE VERBS: create a ticket, reorder the backlog, move to `To Do` — and stop.
`promote` existed; `file_defect` created a card for ONE shape (a broken promise citing the
requirement it violates); `breakdown` filed work from a matched gesture. There was no *"describe it
to me and I will open it"*. This is that verb, end to end: the model marks the message
(`[[TICKET: <title>]]`), the channel stages a `ticket` draft and asks, a yes opens it through
`ProductModule.file_ticket`, and the reply carries the URL — which is what #33 asks of every one
of the three.

THE FIXTURES ARE THE EXISTING ONES. The channel is driven through `pc.handle` with the same
boundary fake `test_confirmation_by_click.py` uses; the module is built the way
`test_card_maintenance.py` builds it, with a tracker and a board recording what was asked of them.
Nothing between the seams is faked.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import openfactory.product.channel as pc
from openfactory.actions import catalog
from openfactory.actions.base import PRODUCT, Actor
from openfactory.product import confirm as confirm_module
from openfactory.product.authoring import ticket_body
from openfactory.product.config import ProductLink
from openfactory.product.loader import ProductContext
from openfactory.product.module import ProductModule
from openfactory.product.role import _TICKET_RE, TICKET_MARKER, ProductAnswer
from openfactory.product.voice import ticket_confirmation, ticket_filed
from tests.test_card_maintenance import COMMIT, DOCS, REQUIREMENTS_DIR, _corpus, _Harness
from tests.test_card_maintenance import _project as _module_project
from tests.test_confirmation_by_click import ADMIN, KEY, _project

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


# ── the marker ──────────────────────────────────────────────────────────────────────────────────

def test_the_marker_carries_the_title_in_the_persons_words():
    m = _TICKET_RE.search("Certo, abro.\n[[TICKET: Exportar relatório em CSV]]")

    assert m and m.group("title") == "Exportar relatório em CSV"
    assert _TICKET_RE.search("[[TICKET]]").group("title") is None
    assert TICKET_MARKER.startswith("[[TICKET")


def test_the_answer_model_has_the_two_fields_and_they_default_off():
    a = ProductAnswer(text="x")

    assert (a.is_ticket, a.ticket_title) == (False, "")


def test_the_prompt_teaches_the_marker_beside_the_defect_one():
    """The marker is DECLARED by the model, so the prompt is where the verb is born. Read out of
    the source: the paragraph that teaches `[[DEFEITO` is immediately followed by the one that
    teaches `[[TICKET: <title>]]`, and it says what a card is NOT — a promise, a wish."""
    src = (ROOT / "openfactory" / "product" / "role.py").read_text(encoding="utf-8")
    defect_at = src.index("do NOT use the defect marker for a wish")
    ticket_at = src.index("[[TICKET: <title>]]", defect_at)  # the PROMPT's, not the constant's comment

    assert 0 < ticket_at - defect_at < 400, "the ticket paragraph does not follow the defect one"
    assert "A card is not a promise" in src


def test_the_marker_is_parsed_into_the_answer_and_stripped_from_the_text(tmp_path):
    """Through `ProductModule.answer` and the real parser, with a harness that says the marker —
    the module built exactly as `test_product_module.py` builds one that answers."""
    from tests.test_product_module import _module as _answering_module

    mod, _harness = _answering_module(tmp_path, answer="Abro sim.\n[[TICKET: Exportar CSV]]")

    answer = mod.answer("abre um card para exportar o relatório em CSV")

    assert answer.is_ticket and answer.ticket_title == "Exportar CSV"
    assert "[[TICKET" not in answer.text and answer.text.strip() == "Abro sim."


# ── the channel: staged, asked, confirmed ───────────────────────────────────────────────────────

class _World:
    """The boundary fake `test_confirmation_by_click.py` uses, plus the one verb under test."""

    def __init__(self, *, title: str = "Exportar CSV", says: str = "Certo, abro um card."):
        self.title, self.says = title, says
        self.filed: list[dict] = []

    def settle_acceptance(self, text):
        return None

    def close_decisions_answered(self, *, channel=""):
        return 0

    def confirmed(self, reply, *, proposal):
        return "neither"

    def context(self):
        return SimpleNamespace(available=True, reason="")

    def answer(self, question, *, context="", conversation="", **_):
        return SimpleNamespace(ok=True, is_ticket=True, ticket_title=self.title,
                               is_defect=False, is_request=False, decisions=[], gesture="",
                               text=self.says, violates=None)

    def file_ticket(self, **kw):
        self.filed.append(kw)
        return SimpleNamespace(ok=True, ref="#77", url="https://forge/x/77", detail="",
                               existed=False)


def test_the_channel_stages_a_ticket_draft_and_asks_with_the_title():
    world = _World()

    reply = pc.handle(_project(), text="abre um card para exportar o relatório em CSV",
                      user=ADMIN, thread=KEY, module=world)

    staged = pc.pending_for(KEY)
    assert staged and staged["kind"] == "ticket"
    assert staged["title"] == "Exportar CSV"
    assert "exportar o relatório" in staged["described"]
    assert staged["reported_by"] == f"<@{ADMIN}>"
    assert world.filed == [], "nothing is opened before the yes"
    assert reply and "Exportar CSV" in str(reply) and "Confirma" in str(reply)


def test_with_no_title_from_the_model_the_persons_words_become_the_title():
    world = _World(title="")

    pc.handle(_project(), text="cria uma tarefa: revisar o cadastro de clientes",
              user=ADMIN, thread=KEY, module=world)

    assert pc.pending_for(KEY)["title"] == "cria uma tarefa: revisar o cadastro de clientes"


def test_a_yes_opens_it_through_the_module_and_the_reply_carries_the_url():
    world = _World()
    pc.handle(_project(), text="abre um card para exportar CSV", user=ADMIN, thread=KEY,
              module=world)

    reply = pc.handle(_project(), text="sim", user=ADMIN, thread=KEY, module=world)

    [call] = world.filed
    assert call["title"] == "Exportar CSV" and "exportar CSV" in call["described"]
    assert call["reported_by"] == f"<@{ADMIN}>"
    assert "https://forge/x/77" in str(reply), reply
    assert pc.pending_for(KEY) is None, "the draft was consumed"


def test_the_ticket_kind_is_registered_beside_the_others():
    assert confirm_module._EXECUTORS["ticket"] is confirm_module._confirm_ticket
    assert "defect" in confirm_module._EXECUTORS  # the sibling it mirrors


def test_a_module_that_could_not_open_it_answers_with_its_own_sentence():
    class _Broken:
        def file_ticket(self, **kw):
            return SimpleNamespace(ok=False, ref="", url="", detail="não consegui abrir o cartão "
                                   "agora.", existed=False)

    reply = confirm_module._confirm_ticket(
        _project(), {"title": "X", "described": "y"}, module=_Broken(), user=ADMIN, lang="pt-BR")

    assert "não consegui" in reply


# ── the module: the pen ─────────────────────────────────────────────────────────────────────────

class _Tracker:
    def __init__(self, *, existing: str | None = None, breaks: bool = False):
        self.existing, self.breaks = existing, breaks
        self.created: list[tuple[str, str]] = []

    def find_ticket(self, *, title: str):
        return self.existing

    def create_ticket(self, *, title: str, body: str) -> str:
        if self.breaks:
            raise RuntimeError("forge down")
        self.created.append((title, body))
        return "#700"

    def ticket_url(self, ref: str) -> str:
        return f"https://forge/a/b/issues/{ref.lstrip('#')}"


class _Board:
    def __init__(self, *, refuses: bool = False):
        self.refuses = refuses
        self.placed: list[tuple[str, str]] = []

    def add_item(self, *, issue_url):
        return True

    def set_column(self, *, issue, issue_url, name):
        if self.refuses:
            return False
        self.placed.append((issue, name))
        return True


def _module(tmp_path, tracker: _Tracker) -> ProductModule:
    ctx = ProductContext(link=ProductLink(active=True, docs_repo=DOCS, kind="ok", reason="fine"),
                         corpus=_corpus(), docs_path=str(tmp_path), docs_commit=COMMIT,
                         requirements_dir=REQUIREMENTS_DIR)
    return ProductModule(_module_project(), context=ctx, agent=_Harness("{}"), tracker=tracker)


def test_the_module_opens_the_card_as_described_places_it_and_answers_with_the_url(tmp_path):
    tracker, board = _Tracker(), _Board()

    result = _module(tmp_path, tracker).file_ticket(
        title="Exportar CSV.", described="o relatório mensal em CSV, com totais",
        reported_by="<@U1>", source="#produto", tracker=tracker, board=board)

    assert result.ok and result.ref == "#700"
    assert result.url == "https://forge/a/b/issues/700"
    [(title, body)] = tracker.created
    assert title == "Exportar CSV"                      # the trailing dot is not a title
    assert "sem requisito por trás" in body and "o relatório mensal em CSV" in body
    assert "<@U1>" in body and "#produto" in body
    assert "REQ-" not in body, "a card nobody argued into a requirement must not pretend to cite one"
    assert board.placed == [("700", ProductModule.FILING_COLUMN)]


def test_the_same_title_twice_is_one_card_and_the_reply_says_so(tmp_path):
    tracker = _Tracker(existing="#42")

    result = _module(tmp_path, tracker).file_ticket(
        title="Exportar CSV", described="x", reported_by="<@U1>", tracker=tracker, board=_Board())

    assert result.ok and result.existed and result.ref == "#42"
    assert result.url.endswith("/42")
    assert tracker.created == []


def test_an_empty_title_opens_nothing(tmp_path):
    tracker = _Tracker()

    result = _module(tmp_path, tracker).file_ticket(
        title="   ", described="x", reported_by="<@U1>", tracker=tracker, board=_Board())

    assert not result.ok and "título" in result.detail
    assert tracker.created == []


def test_a_forge_that_is_down_costs_the_card_and_never_the_listener(tmp_path):
    tracker = _Tracker(breaks=True)

    result = _module(tmp_path, tracker).file_ticket(
        title="X", described="y", reported_by="<@U1>", tracker=tracker, board=_Board())

    assert not result.ok and "não consegui abrir" in result.detail


def test_a_board_that_refuses_the_placement_is_said_out_loud(tmp_path, caplog):
    """A card with no column is invisible to the queue for ever while the reply said "opened".
    `False` from the board is the placement not happening (ADR-0030)."""
    tracker, board = _Tracker(), _Board(refuses=True)

    with caplog.at_level("WARNING"):
        result = _module(tmp_path, tracker).file_ticket(
            title="X", described="y", reported_by="<@U1>", tracker=tracker, board=board)

    assert result.ok and "posicion" in result.detail
    assert "OPENFACTORY_PRODUCT_TICKET_NOT_PLACED" in caplog.text


# ── the action row: the same verb from the panel and the API ──────────────────────────────────

def _actor() -> Actor:
    return Actor(id="ana", display="Ana", via="panel", admin=True, scopes=frozenset({PRODUCT}))


@pytest.mark.asyncio
async def test_the_row_refuses_without_yes_and_opens_with_it(monkeypatch):
    world = _World()
    monkeypatch.setattr(catalog, "_product_module",
                        lambda project, by: (world, SimpleNamespace(name=project), None))

    refused = await catalog._product_file_ticket(project="books", title="Exportar CSV",
                                                 body="o relatório", by=_actor())
    assert not refused.ok and "yes" in refused.message and world.filed == []

    opened = await catalog._product_file_ticket(project="books", title="Exportar CSV",
                                                body="o relatório", by=_actor(), yes=True)
    assert opened.ok and opened.data["url"] == "https://forge/x/77"
    [call] = world.filed
    assert (call["title"], call["described"], call["reported_by"]) == ("Exportar CSV",
                                                                       "o relatório", "ana")


@pytest.mark.asyncio
async def test_the_row_refuses_an_empty_title(monkeypatch):
    world = _World()
    monkeypatch.setattr(catalog, "_product_module",
                        lambda project, by: (world, SimpleNamespace(name=project), None))

    outcome = await catalog._product_file_ticket(project="books", title=" ", by=_actor(), yes=True)

    assert not outcome.ok and world.filed == []


def test_the_row_is_declared_in_the_product_area_with_the_title_required():
    src = (ROOT / "openfactory" / "actions" / "catalog.py").read_text(encoding="utf-8")
    block = src[src.index('name="product_file_ticket"'):][:400]

    assert "scope=PRODUCT" in block
    assert re.search(r'required=\("project", "title"\)', block)
    assert "run=_product_file_ticket" in block


# ── the voice and the body ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lang", ["pt-BR", "en"])
def test_the_confirmation_names_the_title_and_says_it_is_not_a_requirement(lang):
    text = ticket_confirmation(title="Exportar CSV", language=lang)

    assert "Exportar CSV" in text
    assert "requisito" in text or "requirement" in text


def test_the_filed_sentence_carries_the_url_and_is_honest_about_the_backlog():
    text = ticket_filed(ref="#77", url="https://forge/x/77", language="pt-BR")

    assert "https://forge/x/77" in text and "Backlog" in text
    assert "Já existia" in ticket_filed(ref="#77", url="", language="pt-BR", existed=True)
    assert "#77" in ticket_filed(ref="#77", url="", language="en")


def test_the_body_says_it_has_no_requirement_behind_it():
    body = ticket_body(described="o relatório em CSV", reported_by="<@U1>", source="#produto",
                      docs_repo="a/docs")

    assert "sem requisito por trás" in body
    assert "o relatório em CSV" in body and "<@U1>" in body and "#produto" in body
    assert "a/docs" in body
    assert "REQ-" not in body
