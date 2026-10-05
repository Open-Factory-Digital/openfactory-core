"""On Jira, every sentence names a card as Jira does, and the board's refusals speak the
conversation's language (#497).

`#` IS GITHUB'S PUNCTUATION. The sentences the product role says were written when every ref was a
number, so they put a `#` in front of whatever they held: `f"#{n}"` in an f-string, `*#{number}*`
in a catalogue. On a Jira board that is `#CONT-412` — a spelling nobody there writes and nobody can
paste back. `contracts.refs.ref_label` is the one answer to "how does a person read this ref"
(C-05): `#12` on a numbered board, as it always read, and `CONT-412` on Jira.

MEASURED ON `main` (755e489) WITH THIS FILE. A backlog order confirmed on the Jira row was read
back as "Ordem gravada no quadro: #DAR-10, #DAR-9"; a queue the board refused, on a project that
speaks English, answered "o quadro recusou a movimentação"; a reorder half refused answered in two
languages at once; the composers below said `#CONT-412` in every sentence that names a card; and
`ProductModule.promote` and `reorder` wrote their details as Portuguese literals.

WHAT IS DRIVEN HERE. The yes itself, through `confirm.confirm`, with the product role's real pen
holding the Jira row's real tracker and board, built by the registry against a fake at the one
place the adapter touches the network (`urllib.request.urlopen`) — as `test_a_jira_key_is_a_card_
ref.py` does. The failure that RAISES cannot be reached through Jira's adapter (it catches
everything and answers False), so that branch is driven with a board double that raises, holding
the same Jira tracker. Every composer that names a card is rendered twice — a numbered ref and a
Jira key — and the two must differ by the label and nothing else, which pins `#12` byte for byte
and forbids `#CONT-412` in one comparison.

THE GUARD. A scan of the product's sentence modules for a literal `#` placed straight before a
card's placeholder — an f-string's `#{…}`, a catalogue's `#{number}` or `*#{…}*`, a `"#" + ref`.
The catalogues are dict values, not f-strings, so they are read as format strings; docstrings are
not sentences and are skipped. What it may not see is said in `ALLOWED`, with the reason.

AND THE MODULE AND THE RELEASE (#513). #497 left `ProductModule`'s other verbs — refine, close,
remove, correct, align — and the release's refusal writing their details as Portuguese literals
naming the card `#{number}`, and `voice._listed` ending every cut list in "e mais". The guard
reads `module.py` and `release.py` too, where a `#` before a value is often not a sentence at all:
the ref handed to the tracker, the card's door or a result (`f"#{number}"`, no word around it),
the operator's log line, and a prompt to a model are told apart by WHERE the string goes, never by
an allowance per function. And no detail is composed in either file: every one comes from the
voice, in the conversation's language.
"""

from __future__ import annotations

import ast
import io
import json
import re
import urllib.error
import urllib.parse
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from openfactory.contracts.refs import ref_label
from openfactory.product import staging, voice
from tests.test_a_jira_key_is_a_card_ref import _Answer

ROOT = Path(__file__).resolve().parents[1]

KEY = "DAR"
BACKLOG, QUEUE, DOING, DONE = "Backlog", "TO-DO", "Em andamento", "Concluído"
ANA = "ana-requester-77"
AGENT, ROOM = "Nina", "acme"


# ── the label itself ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("ref", "label"), [
    ("12", "#12"), ("#12", "#12"), (12, "#12"), (" #12 ", "#12"),
    ("CONT-412", "CONT-412"), ("#CONT-412", "CONT-412"),
    ("acme/web#3", "acme/web#3"), ("", ""), (None, ""),
])
def test_a_ref_is_labelled_as_its_tracker_writes_it(ref, label):
    """`#CONT-412` is what a person types, and what `promote` answers (`f"#{number}"`): the same
    ticket, decorated. Its label is `CONT-412`, as a bare key's is."""
    assert ref_label(ref) == label


# ── every composer that names a card ─────────────────────────────────────────────────────────────

def _proposal(a, b):
    readiness = NS(wasting_capacity=True, needs_refinement=[a], blocked_by_refinement=False)
    proposal = NS(items=[NS(ticket=a, batch="", why="w"), NS(ticket=b, batch="", why="")],
                  held_back=[NS(ticket=b, why="h")], note="")
    return readiness, proposal


#: `name → (a, b, language) → what it says`. Each names the card `a` (and `b` where two are named).
COMPOSERS = {
    "card_withdrawn_result": lambda a, b, lang: [
        voice.card_withdrawn_result(ref=a, how=how, language=lang)
        for how in ("closed", "removed", "only_closed", "not_yours")],
    "defect_filed": lambda a, b, lang: voice.defect_filed(ref=a, violates=3, language=lang,
                                                          just_asked=True),
    "reorder_confirmation": lambda a, b, lang: voice.reorder_confirmation(numbers=[a, b],
                                                                          language=lang),
    "reordered": lambda a, b, lang: voice.reordered([a, b], language=lang, agent_name=AGENT),
    "ticket_filed": lambda a, b, lang: [voice.ticket_filed(ref=a, language=lang),
                                        voice.ticket_filed(ref=a, language=lang, just_asked=True)],
    "needs_action_report": lambda a, b, lang: voice.needs_action_report(
        NS(decisions=[1], mine=lambda: [NS(verdict=NS(ticket=a))],
           handed_back=lambda: [NS(verdict=NS(ticket=b))]), language=lang),
    "triage_report": lambda a, b, lang: voice.triage_report(
        NS(observations=[NS(kind="no_criteria", ticket=a), NS(kind="no_criteria", ticket=b)],
           skipped=[]), language=lang),
    "queue_proposal": lambda a, b, lang: voice.queue_proposal(*_proposal(a, b), titles={a: "Ta"},
                                                              language=lang),
    "_listed": lambda a, b, lang: [voice._listed([a, b], language=lang),
                                   voice._listed([a, b], limit=1, language=lang)],
    "close_confirmation": lambda a, b, lang: [
        voice.close_confirmation(number=a, language=lang),
        voice.close_confirmation(number=a, in_favour_of=b, reason="r", language=lang)],
    "card_closed": lambda a, b, lang: [
        voice.card_closed(number=a, in_favour_of=other, linked=linked, reasoned=reasoned,
                          language=lang)
        for other in (None, b) for linked in (True, False) for reasoned in (True, False)],
    "survivor_unclear": lambda a, b, lang: voice.survivor_unclear(number=a, other=b,
                                                                  language=lang),
    "correct_confirmation": lambda a, b, lang: voice.correct_confirmation(number=a, text="t",
                                                                          language=lang),
    "card_corrected": lambda a, b, lang: [
        voice.card_corrected(number=a, existed=existed, noted=noted, criteria_removed=removed,
                             language=lang)
        for existed in (True, False) for noted in (True, False) for removed in (True, False)],
    "correction_refused": lambda a, b, lang: [
        voice.correction_refused(reason, number=a, column="Doing", language=lang)
        for reason in voice._CORRECTION_REFUSED],
    "adjust_said": lambda a, b, lang: [
        voice.adjust_said(reason, ref=a, passes=2, length=9, limit=8, language=lang)
        for reason in voice._ADJUST_SAID],
    "adjust_sent": lambda a, b, lang: voice.adjust_sent(ref=a, instruction="i", number=1,
                                                        passes=2, language=lang),
    "adjust_confirmation": lambda a, b, lang: [
        voice.adjust_confirmation(number=a, instruction="i", criteria=["c"], language=lang),
        *[voice.adjust_confirmation(number=a, instruction="i", keeps=keeps, language=lang)
          for keeps in ("requirement", "board")]],
    "align": lambda a, b, lang: [
        voice.align_confirmation(number=a, requirement=4, title="T", language=lang),
        voice.card_aligned(number=a, requirement=4, language=lang),
        voice.card_aligned(number=a, requirement=4, noted=False, language=lang),
        voice.align_refused(number=a, requirement=4, successor=6, language=lang),
        voice.align_refused(number=a, requirement=4, language=lang),
        voice.align_refused(number=a, requirement=4, replaced=True, language=lang),
        voice.align_to_unagreed(number=a, requirement=4, successor=6, language=lang),
        voice.align_to_dropped_replacement(number=a, requirement=4, successor=6, language=lang)],
    "refine": lambda a, b, lang: [
        voice.refine_refused(number=a, language=lang),
        voice.refine_would_be_ignored(number=a, language=lang),
        voice.criteria_written(number=a, measure="3 c", language=lang),
        voice.criteria_written(number=a, noted=False, language=lang)],
    "still_waiting": lambda a, b, lang: voice.still_waiting(questions=[a, b], deliveries=1,
                                                            language=lang),
    "events": lambda a, b, lang: [
        voice.ci_went_red(ref=a, title="T", language=lang),
        voice.pull_request_waiting(ref=a, language=lang),
        voice.preview_up(ref=a, url="https://books.example/", language=lang),
        voice.card_withdrawn(ref=a, removed=True, language=lang),
        voice.ready_for_you(ref=a, title="T", language=lang)],
    "card_moved": lambda a, b, lang: [voice.card_moved(notice, ref=a, title="T", language=lang,
                                                       pass_number=2, link="https://books.example/")
                                      for notice in ("stopped_work", "back", "pass_ready")],
    "card_refused": lambda a, b, lang: [
        voice.card_refused("closed", state="running", ref=a, language=lang),
        voice.card_raced(ref=a, language=lang)],
    "agenda_said": lambda a, b, lang: [
        voice.agenda_said("release", yours=True, issue=a, language=lang),
        voice.agenda_said("question", yours=False, subject=a, language=lang)],
    "named_cards": lambda a, b, lang: [
        voice.cards_opened_awaiting(cards=[a], number=5, language=lang),
        voice.acceptance_stamped(cards=[a, b], language=lang)],
    "board_move_said": lambda a, b, lang: [
        voice.board_move_said(reason, ref=a, language=lang)
        for reason in ("queue_failed", "order_failed")],
    # ── the module's and the release's own details (#513) ──
    "card_said": lambda a, b, lang: [
        voice.card_said(reason, number=a, other=b, requirement=4, language=lang)
        for reason in voice._CARD_SAID],
    "breakdown_said": lambda a, b, lang: [
        voice.breakdown_said(reason, ref=a, title="T", why="w", number=4, default="acme/web",
                             target="evil/api", home="acme/api", language=lang)
        for reason in voice._BREAKDOWN_SAID],
    "queue_said": lambda a, b, lang: voice.queue_said("left_for_later", cards=[a, b],
                                                      language=lang),
    "release_said": lambda a, b, lang: [voice.release_said(reason, ref=a, language=lang)
                                        for reason in voice._RELEASE_SAID],
}


def _said(name, a, b, lang) -> list[str]:
    out = COMPOSERS[name](a, b, lang)
    return out if isinstance(out, list) else [out]


@pytest.mark.parametrize("lang", ["pt-BR", "en"])
@pytest.mark.parametrize("name", sorted(COMPOSERS))
def test_a_jira_key_is_named_as_jira_names_it_and_a_number_as_it_always_was(name, lang):
    """Rendered with `12`/`31` and with `CONT-412`/`CONT-431`, a sentence differs by the label and
    by nothing else — so the numbered one says `#12` where it always did, and the Jira one says
    `CONT-412` there, never `#CONT-412`."""
    numbered = _said(name, "12", "31", lang)
    keyed = _said(name, "CONT-412", "CONT-431", lang)

    assert any("#12" in s for s in numbered), numbered
    assert all("#CONT" not in s for s in keyed), keyed
    assert keyed == [s.replace("#12", "CONT-412").replace("#31", "CONT-431") for s in numbered]


@pytest.mark.parametrize("name", sorted(COMPOSERS))
def test_a_decorated_ref_is_the_same_card(name):
    """`#12` and `12`, `#CONT-412` and `CONT-412`: a ref a person typed with its `#` names the same
    card in the same words. Every `f"#{ref}"` here said `##12` for the first."""
    assert _said(name, "#12", "#31", "en") == _said(name, "12", "31", "en")
    assert _said(name, "#CONT-412", "#CONT-431", "en") == _said(name, "CONT-412", "CONT-431", "en")


#: What `main` said for a numbered card, byte for byte — the sentences the issue names.
NUMBERED_AS_BEFORE = [
    (lambda: voice.reorder_confirmation(numbers=["12", "31"], language="pt-BR"),
     "Coloco o backlog nesta ordem, de cima para baixo: #12, #31. Isso só grava a ordem — nada "
     "começa agora; a próxima leva segue ela. Confirma?"),
    (lambda: voice.reordered(["12", "31"], language="en", agent_name=AGENT),
     "Nina: Order recorded on the board: #12, #31. The next batch follows it."),
    (lambda: voice.ticket_filed(ref="12", language="pt-BR"),
     "Aberto: #12. Fica na coluna Backlog até o time aprovar a próxima leva — e quando sair, eu aviso "
     "aqui."),
    (lambda: voice.defect_filed(ref="12", violates=3, language="en", just_asked=True),
     "This has just been asked for — the card already exists: #12. I did not open another for the "
     "same thing."),
    (lambda: voice.queue_proposal(*_proposal("12", "31"), titles={"12": "Ta"}, language="pt-BR"),
     "A fábrica está parada e tem trabalho pronto esperando — isso é capacidade indo embora. Minha "
     "sugestão de por onde seguir, nesta ordem:\n\n1. **#12** — Ta\n   _w_\n2. **#31**\n\nDeixei de "
     "fora por enquanto:\n• #31 — h\n\n(1 outros no backlog ainda não dizem quando estariam "
     "prontos.)\n\nAprovo? Responda *sim* e eu coloco na fila nessa ordem."),
    (lambda: voice.card_closed(number="12", in_favour_of="31", language="pt-BR",
                               agent_name=AGENT),
     "Nina: Encerrado o *#12* em favor do *#31*. Escrevi nos dois: no que saiu, para onde o assunto "
     "foi; no que fica, que ele responde pelos dois agora. Nada começou por causa disso."),
    (lambda: voice.still_waiting(questions=["12", "31"], deliveries=1, language="en"),
     "waiting on an answer about #12, #31 · following the delivery of 1 request"),
    # the module's and the release's details, moved to the voice by #513, say in pt-BR what the
    # literals said
    (lambda: voice.card_said("survivor_missing", number="12", other="31", language="pt-BR"),
     "não encontrei o #31 no quadro, então não fechei o #12: mandar quem ler procurar um cartão "
     "que não existe é pior do que deixar os dois abertos."),
    (lambda: voice.card_said("close_unlinked", number="12", other="31", language="pt-BR"),
     "fechei o #12, mas não consegui deixar o registro disso no #31. O time foi avisado."),
    (lambda: voice.release_said("not_waiting", ref="512", language="pt-BR"),
     "o #512 não está mais esperando essa liberação — ou já subiu, ou a janela de espera fechou. "
     "Não mexi em nada; me diga e eu verifico em que pé está."),
    (lambda: voice.queue_said("left_for_later", cards=["12", "31"], language="pt-BR"),
     "Deixei para a próxima rodada o que não cabia inteiro agora: #12, #31."),
    (lambda: voice._listed(["1", "2", "3"], limit=2, language="pt-BR"), "#1, #2 e mais 1"),
]


@pytest.mark.parametrize(("say", "said"), NUMBERED_AS_BEFORE)
def test_a_numbered_card_reads_byte_for_byte_as_before(say, said):
    assert say() == said


def test_the_conversation_follow_ups_name_the_card_as_its_tracker_does():
    """The question and its one reminder (`followup`), said to a person about a stalled card."""
    from openfactory.memory.ledger import QUESTION, Loop
    from openfactory.product import followup

    def ask(subject):
        loop = Loop(kind=QUESTION, subject=subject, context={"title": "Exportar", "asked": "?"})
        return [followup.ask_text(loop, language="pt-BR"),
                followup.chase_text(loop, language="en")]

    numbered, keyed = ask("12"), ask("CONT-412")
    assert all("#12 (Exportar)" in s for s in numbered), numbered
    assert keyed == [s.replace("#12", "CONT-412") for s in numbered]


def test_the_releases_waiting_are_named_as_their_tracker_does(monkeypatch):
    """"funcionou" with two releases waiting asks which — and names them so they can be typed back."""
    from openfactory.memory.ledger import ACCEPTANCE, Loop
    from openfactory.product import engine

    monkeypatch.setattr(engine, "_waiting_release_refs", lambda project: ["CONT-412", "12"])
    loop = Loop(kind=ACCEPTANCE, subject="4", context={"release_issue": "CONT-412"})

    said = engine._maybe_release(NS(name=ROOM), None, loop, "worked", ANA, AGENT, "en",
                                 ambiguous=True)

    assert "(CONT-412, #12)" in said and "#CONT" not in said, said


# ── promote and reorder: their own details, in both languages ────────────────────────────────────

class _Site:
    """A Jira site whose cards wait in `Backlog`. Its workflow offers the move into the queue
    unless the card is one it `refuses` to move — and then it offers no move at all, so the board
    has nothing to match whatever name it asks for. Its rank endpoint answers 400 for a card in
    `unranked`.

    THE CARD'S DOOR READS THE CARD, AND THE BOARD, BEFORE IT QUEUES ONE (ADR-0055, #414): a card in
    `unread` answers 500, and a site that is `blind` answers 500 to every search. The tracker lists
    its cards too, for the verbs that must find theirs first (#513)."""

    def __init__(self, *cards: str) -> None:
        self.status = dict.fromkeys(cards, BACKLOG)
        self.refuses: set[str] = set()
        self.unranked: set[str] = set()
        self.unread: set[str] = set()
        self.blind = False
        self.ranked: list[dict] = []

    @staticmethod
    def _refused(url: str):
        return urllib.error.HTTPError(url, 500, "down", {}, io.BytesIO(b"{}"))

    def urlopen(self, req, timeout=0):  # noqa: ARG002 — urllib's own signature
        method, url = req.get_method(), req.full_url
        body = json.loads(req.data) if req.data else None
        if url.endswith("/rest/agile/1.0/issue/rank") and method == "PUT":
            if set(body["issues"]) & self.unranked:
                raise urllib.error.HTTPError(url, 400, "rank refused", {}, io.BytesIO(b"{}"))
            self.ranked.append(body)
            return _Answer(None)
        path = url.split("/rest/api/3/", 1)[1]
        if method == "POST" and path == "search/jql":     # the tracker's list of cards (#513)
            return _Answer({"isLast": True, "issues": [
                {"key": k, "fields": {"summary": "Exportar CSV", "status": {
                    "name": s, "statusCategory": {"key": "new"}}}}
                for k, s in self.status.items()]})
        if method == "GET" and path.startswith("search/jql?"):    # the board's own read
            if self.blind:
                raise self._refused(url)
            jql = urllib.parse.parse_qs(path.split("?", 1)[1])["jql"][0]
            status = re.search(r'status = "([^"]+)"', jql)
            return _Answer({"isLast": True, "issues": [
                {"key": k, "fields": {"status": {"name": s}}} for k, s in self.status.items()
                if status is None or s == status.group(1)]})
        read = re.fullmatch(rf"issue/({KEY}-\d+)", path)
        if read and method == "GET":
            if read.group(1) in self.unread:
                raise self._refused(url)
            return _Answer({"key": read.group(1), "fields": {
                "summary": "Exportar CSV", "description": None, "reporter": None,
                "status": {"name": self.status[read.group(1)], "statusCategory": {"key": "new"}}}})
        moved = re.fullmatch(rf"issue/({KEY}-\d+)/transitions", path)
        if moved and method == "GET":
            card = moved.group(1)
            offers = [] if card in self.refuses else [QUEUE]
            return _Answer({"transitions": [{"id": "11", "name": f"Mover para {to}",
                                             "to": {"name": to}} for to in offers]})
        if moved and method == "POST":
            self.status[moved.group(1)] = QUEUE
            return _Answer(None)
        raise AssertionError(f"the adapter called {method} {path}, a route this site never had")


@pytest.fixture(autouse=True)
def _clean():
    staging._PENDING.clear()
    yield
    staging._PENDING.clear()


def _jira(monkeypatch, tmp_path, *, language: str, board=None, ranks: bool = False):
    """A Jira project as the registry holds one, two cards in its Backlog, and the pen holding the
    row's real tracker — and its real board, unless the test hands it another.

    `ranks` hands `reorder` the board AS IT IS. The pen wraps its board in `_WatchedWrites`, which
    delegates through `__getattr__`, and since Python 3.12 `isinstance(…, Rankable)` reads a
    protocol's methods with `inspect.getattr_static`: the wrapped board is never `Rankable`, so
    every order written through the pen's own board is refused as "this board does not take a new
    order". That is a defect of its own, outside this card; here the words are under test."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule
    from tests.test_card_maintenance import COMMIT, REQUIREMENTS_DIR, _corpus, _Harness

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    site = _Site("DAR-9", "DAR-10")
    monkeypatch.setattr("urllib.request.urlopen", site.urlopen)
    options = {"site": "https://acme-team.atlassian.net", "email": "alice@acme.ai",
               "status_map": json.dumps({"todo": QUEUE, "in_progress": DOING, "done": DONE})}
    project = Project(name=ROOM, repo_path=str(tmp_path), language=language,
                      tracker=ProviderRef(kind="jira", repo=KEY, options=options),
                      product=ProductConfig(docs_repo="acme/acme-docs", admins=[ANA],
                                            agent_name=AGENT))
    tracker = build_tracker(project, token="t")
    board = board if board is not None else build_board(project, token="t")
    assert type(tracker).__name__ == "JiraTracker"
    ctx = ProductContext(link=ProductLink(active=True, docs_repo="acme/acme-docs", kind="ok",
                                          reason="fine"),
                         corpus=_corpus(), docs_path=str(tmp_path), docs_commit=COMMIT,
                         requirements_dir=REQUIREMENTS_DIR)
    module = ProductModule(project, context=ctx, agent=_Harness("{}"), tracker=tracker,
                           board=board)
    if ranks:
        monkeypatch.setattr(module, "_board", lambda: board)
    return project, site, module


def _yes(project, module, kind: str, numbers: list[str]) -> str:
    """`numbers` is staged for Ana as `kind`, as the conversation stages it, and Ana says yes."""
    from openfactory.product.confirm import confirm

    lang = project.language
    staging.remember(ROOM, {"kind": kind, "channel": ROOM, "numbers": list(numbers)},
                     lang=lang, project=project, person=ANA)
    key, waiting = staging.find_waiting(ROOM, ROOM, project=project, person=ANA)
    assert waiting is not None and waiting["kind"] == kind, "nothing is staged"
    return confirm(project, key=key, entry=waiting, module=module, user=ANA, lang=lang)


def test_an_order_confirmed_on_jira_is_read_back_as_jira_names_the_cards(monkeypatch, tmp_path):
    """`_confirm_reorder` held the keys bare and `reordered` put GitHub's `#` back on each."""
    project, site, module = _jira(monkeypatch, tmp_path, language="pt-BR", ranks=True)

    said = _yes(project, module, "reorder", ["DAR-10", "DAR-9"])

    assert [r["issues"] for r in site.ranked] == [["DAR-10"], ["DAR-9"]]
    assert site.ranked[1]["rankAfterIssue"] == "DAR-10"
    assert said == "Nina: Ordem gravada no quadro: DAR-10, DAR-9. A próxima leva segue ela.", said


def test_an_order_half_refused_on_jira_is_said_in_the_conversations_language(monkeypatch,
                                                                              tmp_path):
    project, site, module = _jira(monkeypatch, tmp_path, language="en", ranks=True)
    site.unranked = {"DAR-9"}

    said = _yes(project, module, "reorder", ["DAR-10", "DAR-9"])

    assert said == ("Nina: Order recorded on the board: DAR-10. The next batch follows it."
                    "\n\n1 did not go into the order: the board refused the new order"), said


def test_a_queue_the_board_refused_on_jira_is_said_in_the_conversations_language(monkeypatch,
                                                                                tmp_path):
    """The partial line was English and the detail under it Portuguese; with every card refused,
    the detail is the whole reply. Through the card's door (ADR-0055, #414) a refused placement is
    a promotion RECORDED, which the hourly round applies again — and the sentence says so."""
    project, site, module = _jira(monkeypatch, tmp_path, language="en")
    site.refuses = {"DAR-9", "DAR-10"}

    said = _yes(project, module, "queue", ["DAR-9", "DAR-10"])

    assert site.status == {"DAR-9": BACKLOG, "DAR-10": BACKLOG}
    assert said == ("I could not put DAR-9 in the queue just now — it is noted, and I try again "
                    "within the hour."), said


@pytest.mark.parametrize(("broken", "said"), [
    ("card", "DAR-9 could not be read ("),
    ("board", "acme's board could not be read, so there is no way to tell where DAR-9 is."),
    ("column", "DAR-9 is in 'Arquivado', which is not a column this platform maps"),
])
def test_a_card_the_door_cannot_place_is_named_as_jira_names_it(monkeypatch, tmp_path, broken,
                                                                 said):
    """`promote` answers with the door's refusal (#414), and the door wrote `#{card}`: a card it
    could not read, on a board it could not read, or in a column nobody mapped, was `#DAR-9`."""
    _project, site, module = _jira(monkeypatch, tmp_path, language="en")
    site.unread = {"DAR-9"} if broken == "card" else set()
    site.blind = broken == "board"
    if broken == "column":
        site.status["DAR-9"] = "Arquivado"

    [refused] = module.promote(["DAR-9"], actor=ANA)

    assert not refused.ok and said in refused.detail, refused.detail
    assert "#DAR" not in refused.detail, refused.detail


class _Down:
    """A board that is there and raises on every move — the branch Jira's adapter never reaches,
    since it answers False for everything that goes wrong. It reads where its cards are: the card's
    door asks before it queues one (ADR-0055, #414)."""

    def columns(self):
        return {"DAR-9": BACKLOG}

    def add_item(self, *, issue_url):
        return None

    def set_column(self, *, issue, issue_url, name):
        raise RuntimeError("board down: POST /rest/api/3/issue/transitions 503")

    def place_after(self, *, issue, issue_url, after, column):
        raise RuntimeError("board down: PUT /rest/agile/1.0/issue/rank 503")


@pytest.mark.parametrize(("language", "queue", "order", "door"), [
    ("pt-BR", "não consegui colocar o DAR-9 na fila agora — ficou anotado, e eu tento de novo "
              "dentro de uma hora.",
     "não consegui reposicionar o DAR-9 agora. O time foi avisado e resolve.",
     "não consegui mover o DAR-9 para a fila agora. O time foi avisado e resolve."),
    ("en", "I could not put DAR-9 in the queue just now — it is noted, and I try again within the "
           "hour.",
     "I could not put DAR-9 in its place just now. The team has been told and will sort it out.",
     "I could not move DAR-9 into the queue just now. The team has been told and will sort it "
     "out."),
])
def test_a_move_that_raised_names_the_jira_card_in_the_conversations_language(
        monkeypatch, tmp_path, language, queue, order, door):
    """A queue move that raised is a failed effect of a promotion the door RECORDED (#414), applied
    again by the hourly round; what raises around the door is the team's to sort out."""
    import openfactory.lifecycle as lifecycle

    _project, _site, module = _jira(monkeypatch, tmp_path, language=language, board=_Down(),
                                    ranks=True)

    [queued] = module.promote(["DAR-9"], actor=ANA)
    [ordered] = module.reorder(["DAR-9"], actor=ANA)

    assert (queued.ok, queued.detail) == (False, queue)
    assert (ordered.ok, ordered.detail) == (False, order)

    def _raises(*_a, **_k):
        raise RuntimeError("the card record is down: sqlite3.OperationalError")

    monkeypatch.setattr(lifecycle, "transition", _raises)
    [unrecorded] = module.promote(["DAR-9"], actor=ANA)
    assert (unrecorded.ok, unrecorded.detail) == (False, door)


@pytest.mark.parametrize(("language", "unreachable", "unrankable"), [
    ("pt-BR", "não consegui acessar o quadro",
     "este quadro ainda não aceita reordenação por aqui — a ordem precisa ser mudada no próprio "
     "quadro"),
    ("en", "I could not reach the board",
     "this board does not take a new order from here yet — the order has to be changed on the "
     "board itself"),
])
def test_a_board_that_is_not_there_or_cannot_rank_is_said_in_the_conversations_language(
        monkeypatch, tmp_path, language, unreachable, unrankable):
    _project, _site, module = _jira(monkeypatch, tmp_path, language=language)
    monkeypatch.setattr(module, "_board", lambda: None)

    assert [r.detail for r in module.promote(["DAR-9"], actor=ANA)] == [unreachable]
    assert [r.detail for r in module.reorder(["DAR-9"], actor=ANA)] == [unreachable]

    monkeypatch.setattr(module, "_board", lambda: NS(add_item=lambda **_: None))
    assert [r.detail for r in module.reorder(["DAR-9"], actor=ANA)] == [unrankable]


# ── every other verb, and the release: their own details, in both languages (#513) ────────────

@pytest.mark.parametrize(("language", "said"), [
    ("pt-BR", {"missing": "não encontrei o cartão DAR-77 no quadro",
               "survivor": ("não encontrei o DAR-77 no quadro, então não fechei o DAR-9: mandar "
                            "quem ler procurar um cartão que não existe é pior do que deixar os "
                            "dois abertos."),
               "proposal": "o requisito 9 ainda não foi acordado, então não dá para virar "
                           "trabalho",
               "no_requirement": "não encontrei o requisito 99 escrito na base."}),
    ("en", {"missing": "I could not find card DAR-77 on the board",
            "survivor": ("I could not find DAR-77 on the board, so I did not close DAR-9: sending "
                         "whoever reads it to look for a card that does not exist is worse than "
                         "leaving both open."),
            "proposal": "requirement 9 has not been agreed yet, so it cannot become work",
            "no_requirement": "I could not find requirement 99 written in our base."}),
])
def test_the_card_acts_answer_on_jira_in_the_conversations_language(monkeypatch, tmp_path,
                                                                   language, said):
    """`refine`, `close_card`, the removal and `align_card` wrote "não encontrei o cartão
    #{number} no quadro": Portuguese in an English conversation, and `#DAR-77` on Jira. Driven on
    the Jira row, through the real module, its real tracker and board."""
    _project, _site, module = _jira(monkeypatch, tmp_path, language=language)

    missing = [module.refine("DAR-77", actor=ANA).detail,
               module.close_card("DAR-77", actor=ANA).detail,
               module.withdraw_card("DAR-77", actor=ANA, reason="r", remove=True).detail,
               module.align_card("DAR-77", requirement=6, actor=ANA).detail]

    assert missing == [said["missing"]] * 4, missing
    survivor = module.close_card("DAR-9", actor=ANA, in_favour_of="DAR-77").detail
    assert survivor == said["survivor"], survivor
    proposal = module.align_card("DAR-9", requirement=9, actor=ANA).detail
    assert proposal.startswith(said["proposal"]), proposal
    unwritten = module.align_card("DAR-9", requirement=99, actor=ANA).detail
    assert unwritten == said["no_requirement"], unwritten


@pytest.mark.parametrize(("language", "not_waiting", "failed"), [
    ("pt-BR", "o DAR-9 não está mais esperando essa liberação", "**Nada subiu**"),
    ("en", "DAR-9 is no longer waiting for this release", "**Nothing was released**"),
])
def test_a_release_that_did_not_go_out_is_said_in_the_conversations_language(
        monkeypatch, language, not_waiting, failed):
    """`release()` answered every project in Portuguese, naming the card `#DAR-9`, and said that
    nothing was released in Portuguese in an English project too."""
    from openfactory.product import release as rel

    project = NS(name=ROOM, language=language)

    async def _client():
        return object()

    async def _not_parked(*_a, **_k):
        return False

    async def _down(*_a, **_k):
        raise RuntimeError("the engine is down")

    monkeypatch.setattr(rel, "_client", _client)
    monkeypatch.setattr(rel, "_awaiting", _not_parked)
    ok, why = rel.release(project, "DAR-9", approver=ANA)
    assert not ok and why.startswith(not_waiting) and "#DAR" not in why, why

    monkeypatch.setattr(rel, "_awaiting", _down)
    ok, why = rel.release(project, "DAR-9", approver=ANA)
    assert not ok and failed in why, why


def test_a_list_cut_short_ends_in_the_conversations_language():
    """`voice._listed` ended every cut list in a hard-coded "e mais"."""
    refs = ["3", "5", "CONT-7"]
    assert voice._listed(refs, limit=2, language="en") == "#3, #5 and 1 more"
    assert voice._listed(refs, limit=2, language="pt-BR") == "#3, #5 e mais 1"
    assert voice._listed(refs, language="en") == "#3, #5, CONT-7"


#: The files whose details a person reads in the chat (#513) — every verb of the product role's pen,
#: and the client's release.
DETAILS = ("openfactory/product/module.py", "openfactory/product/release.py")


def _spelled(node) -> list[ast.AST]:
    """The strings `node` itself spells — not the arguments of a call it makes, where the voice's
    own key (`"queue_refused"`) is an argument and not a sentence, nor a key it looks up in a table
    (`said["no_title"]`)."""
    if isinstance(node, (ast.Call, ast.Subscript)):
        return []
    if isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant)
                                           and isinstance(node.value, str)
                                           and node.value.strip()):
        return [node]
    return [found for child in ast.iter_child_nodes(node) for found in _spelled(child)]


def details_written(source: str) -> tuple[set[str], set[str]]:
    """`(written, verbs)`: where `source` spells a detail of its own — a `detail=` of a result, the
    sentence handed to `_could_not`, what is assigned to `detail`, a sentence returned beside a
    verdict (`release`'s `(ok, said)`, `propose_queue`'s `(…, error)`) — and every function in which
    a detail is answered at all, so a walk that reached nothing cannot pass."""
    written: set[str] = set()
    verbs: set[str] = set()
    for verb in ast.walk(ast.parse(source)):
        if not isinstance(verb, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(verb):
            said = []
            if isinstance(node, ast.Call):
                said += [k.value for k in node.keywords if k.arg == "detail"]
                if getattr(node.func, "id", "") == "_could_not":
                    said += node.args[:1]
            elif isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "detail" for t in node.targets):
                said.append(node.value)
            elif isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
                said += node.value.elts
            verbs |= {verb.name} if said else set()
            written |= {f"{n.lineno} ({verb.name}) {ast.unparse(n)[:80]}"
                        for value in said for n in _spelled(value)}
    return written, verbs


def test_the_module_and_the_release_compose_no_detail_of_their_own():
    """Every detail the product role's writes answer comes from the voice — a literal or an
    f-string here is a sentence in one language, and the ones that named a card wrote `#{number}`.
    #497 held `promote` and `reorder` to it; #513, every verb and the release."""
    written, verbs = set(), set()
    for rel in DETAILS:
        found, answered = details_written((ROOT / rel).read_text(encoding="utf-8"))
        written |= {f"{rel}:{w}" for w in found}
        verbs |= answered
    assert {"promote", "reorder", "refine", "_close_one", "_remove_one", "correct_card",
            "align_card", "repoint_orphans", "release", "_run"} <= verbs, verbs
    assert not written, "a detail written in the module, in one language:\n  " + "\n  ".join(
        sorted(written))


def test_the_detail_guard_can_actually_see_one():
    """THE POSITIVE TWIN of the guard above: each shape a detail is written in, and the two it
    must leave alone — the voice's own key, and a key looked up in a table."""
    source = '''
def verb(n, exc, said):
    if n:
        return WriteResult(ok=False, detail=f"não encontrei o #{n}")
    if exc:
        return _could_not("não consegui fechar agora", act="close", cause=exc)
    detail = "3 critérios"
    if said:
        return _could_not(said["no_title"], act="file")
    return WriteResult(ok=True, detail=card_said("not_found", number=n, language="en"))

def release(project):
    return False, "Nada subiu"
'''
    written, verbs = details_written(source)

    assert {w.split(" ", 2)[1] for w in written} == {"(verb)", "(release)"}, written
    assert len(written) == 4, written
    assert verbs == {"verb", "release"}, verbs


# ── the guard ────────────────────────────────────────────────────────────────────────────────────

#: The modules whose strings are sentences a person reads — and, since #513, the module and the
#: release, whose details are said in the chat.
SENTENCES = ("openfactory/product/voice.py", "openfactory/product/followup.py",
             "openfactory/product/engine.py", *DETAILS)

#: `(file, the function or table it is in)` → why it may still write a `#` before a card.
ALLOWED: dict[tuple[str, str], str] = {
    # empty since #498 landed: `voice.queued` names its cards through `ref_label`
}

#: A format placeholder straight after a literal `#` — `#{number}`, `#{0}`, `#{}`, `*#{ref}*` —
#: and never an escaped `#{{`, nor a regex quantifier like `#{1,6}`.
_HASHED_FIELD = re.compile(r"#\{(?!\{)(?:[A-Za-z_][\w.\[\]]*|\d*)(?:![rsa])?(?::[^{}]*)?\}")
_HASHED_PERCENT = re.compile(r"#%(?:\([^)]*\))?[sdr]")

#: The calls that put a value INTO text: a bare `f"#{n}"` handed to one is a piece of a sentence.
_COMPOSES = frozenset({"format", "format_map", "join", "append", "extend", "insert"})
#: The keywords nobody in the conversation reads: the operator's log line `_could_not` writes
#: (`act`), and a prompt to a model — out of #513's scope unless a model quotes it back.
_UNSAID = frozenset({"act", "prompt"})
_LOGGERS = frozenset({"log", "logger"})


def _is_bare_ref(node) -> bool:
    """`f"#{n}"` — the decoration and one value, not a word around them."""
    return (isinstance(node, ast.JoinedStr) and len(node.values) == 2
            and isinstance(node.values[0], ast.Constant) and node.values[0].value == "#"
            and isinstance(node.values[1], ast.FormattedValue))


def not_a_sentence(node, parents: dict[int, ast.AST]) -> bool:
    """Whether a string goes somewhere no person reads it as a sentence (#513) — told by WHERE it
    goes, never by which function it is in:

    - a BARE REF handed straight to a call that does not compose text: `tracker.comment(f"#{n}",
      …)`, `transition(project, f"#{n}", …)`, `WriteResult(ref=f"#{n}")` — the tracker's own input
      spelling, which `canonical_ref` reads back; `"{x}".format(x=f"#{n}")` or
      `lines.append(f"#{n}")` is still a sentence, and so is anything with a word in it;
    - anything under `act=` or `prompt=`;
    - anything handed to `log.<level>(…)` — `card=#%s` is the operator's, not the client's."""
    parent = parents.get(id(node))
    call = parents.get(id(parent)) if isinstance(parent, ast.keyword) else parent
    if (_is_bare_ref(node) and isinstance(call, ast.Call) and node is not call.func
            and getattr(call.func, "attr", "") not in _COMPOSES):
        return True
    while id(node) in parents:
        node = parents[id(node)]
        if isinstance(node, ast.keyword) and node.arg in _UNSAID:
            return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id in _LOGGERS):
            return True
    return False


def hashed_refs(source: str) -> list[tuple[int, str, str]]:
    """`(line, where, what)` for every literal `#` placed straight before a value in `source`:
    an f-string's `#{…}`, a format string's `#{name}` (a catalogue's values are format strings,
    not f-strings), a `"#" + x`, a `"#%s"`. `where` is the innermost function, or the table."""
    tree = ast.parse(source)
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    docstrings = {id(body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                       ast.AsyncFunctionDef))
                  and (body := node.body) and isinstance(body[0], ast.Expr)
                  and isinstance(body[0].value, ast.Constant)}

    def where(node) -> str:
        while id(node) in parents:
            node = parents[id(node)]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return node.name
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                return node.targets[0].id
        return "<module>"

    found = []
    for node in ast.walk(tree):
        if not_a_sentence(node, parents):
            continue
        if isinstance(node, ast.JoinedStr):
            for left, right in zip(node.values, node.values[1:], strict=False):
                if (isinstance(left, ast.Constant) and str(left.value).endswith("#")
                        and isinstance(right, ast.FormattedValue)):
                    found.append((node.lineno, where(node), ast.unparse(node)))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            if isinstance(node.left, ast.Constant) and str(node.left.value).endswith("#"):
                found.append((node.lineno, where(node), ast.unparse(node)))
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and id(node) not in docstrings
              and not isinstance(parents.get(id(node)), ast.JoinedStr)):
            if _HASHED_FIELD.search(node.value) or _HASHED_PERCENT.search(node.value):
                found.append((node.lineno, where(node), node.value[:80]))
    return found


def test_no_sentence_puts_githubs_hash_before_a_card():
    offenders = []
    for rel in SENTENCES:
        for line, name, what in hashed_refs((ROOT / rel).read_text(encoding="utf-8")):
            if (rel, name) not in ALLOWED:
                offenders.append(f"{rel}:{line} ({name}) {what}")
    assert not offenders, (
        "a sentence writes `#` before a card — name it with `contracts.refs.ref_label`, which "
        "says `#12` on a numbered board and `CONT-412` on Jira:\n  " + "\n  ".join(offenders))


def test_the_guard_can_actually_see_an_offender():
    """THE POSITIVE TWIN. A scan that matched nothing — a broken walk, a pattern that never fires —
    would pass the guard for ever while proving nothing, so it is shown every shape it must catch,
    and the shapes it must leave alone."""
    source = '''
"""A docstring that mentions f"#{n}" and `*#{number}*` is not a sentence."""
_TABLE = {"pt-BR": "fechei o *#{number}*", "en": "closed #{ref} in favour of #{other!s}"}
_POSITIONAL = "card #{} and #{0}"
_PERCENT = "card #%s"
_ESCAPED = "a literal #{{brace}}"
_REGEX = r"^#{1,6}\\s"

def listed(numbers):
    return ", ".join(f"#{n}" for n in numbers)

def bold(item):
    return f"**#{item.ticket}**"

def glued(ref):
    return "#" + ref

def labelled(numbers):
    return ", ".join(ref_label(n) for n in numbers) + f" {{ref}} ({len(numbers)})"

def detail(n):
    return WriteResult(ok=False,
                       detail=f"não encontrei o #{n}",
                       ref=f"#{n}")

def failed(n, exc):
    return _could_not(f"could not close #{n}",
                      act=f"close #{n}",
                      cause=exc,
                      ref=f"#{n}")

def formatted(n):
    return "{ref} closed".format(ref=f"#{n}")

def appended(lines, n):
    lines.append(f"#{n}")

def tracked(tracker, n, role):
    tracker.comment(f"#{n}", "a note")
    log.warning("card=#%s could not be noted", n)
    role.ask(prompt=f"## Item #{n} — the title")
    return transition(project, f"#{n}", "closed")
'''
    found = {(name, line) for line, name, _what in hashed_refs(source)}

    assert {name for name, _ in found} == {"_TABLE", "_POSITIONAL", "_PERCENT", "listed", "bold",
                                           "glued", "detail", "failed", "formatted",
                                           "appended"}, found
    assert len(found) == 10, found


def test_the_allowlist_names_only_what_still_exists():
    """An entry whose function is gone is a hole nobody opened on purpose; and an entry the scan no
    longer needs is one, too (review of #514: the stronger form #507 uses), so an allowance whose
    reason is gone is taken out rather than kept for ever."""
    found = {(rel, name) for rel in SENTENCES
             for _line, name, _what in hashed_refs((ROOT / rel).read_text(encoding="utf-8"))}
    assert set(ALLOWED) <= found, f"an allowance no longer used — take it out: {set(ALLOWED) - found}"
    for (rel, name), why in ALLOWED.items():
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        names |= {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                  for t in n.targets if isinstance(t, ast.Name)}
        assert name in names, f"ALLOWED names {rel}::{name}, which is gone"
        assert why.strip(), f"ALLOWED names {rel}::{name} without saying why"


# ── the order the person approved ────────────────────────────────────────────────────────────────

def test_a_queue_is_read_back_in_the_order_it_was_approved(monkeypatch, tmp_path):
    """`promote` moves the cards in the sequence approved — the poller pulls in board order — and
    the reply says "nesta ordem". `_confirm_queue` sorted what landed, so a queue approved and
    moved as 3, 1, 2 was read back as "#1, #2, #3": the order the person approved, contradicted in
    the sentence that confirms it. Driven on the local row, a numbered board, through the yes.

    The sentence reads back what `promote` did. Which card the board then hands the factory first
    was the board's own ordering — the local board's was by ref — until #512 ranked the queue in
    the order approved (`test_the_queue_runs_in_the_order_a_person_approved.py`)."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule
    from openfactory.registry import ProjectRegistry
    from tests.test_card_maintenance import COMMIT, REQUIREMENTS_DIR, _corpus, _Harness

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    registry = ProjectRegistry()
    registry.add(Project(name=ROOM, repo_path=str(tmp_path), language="pt-BR",
                         tracker=ProviderRef(kind="local", repo=ROOM, options={}),
                         product=ProductConfig(docs_repo="acme/acme-docs", admins=[ANA],
                                               agent_name=AGENT)))
    project = registry.get(ROOM)
    LocalBoardSetup().create(project=project, owner="", title=ROOM, token=None)
    tracker = build_tracker(project)
    assert [tracker.create_ticket(title=t, body="x") for t in ("Um", "Dois", "Três")] == [
        "#1", "#2", "#3"]
    ctx = ProductContext(link=ProductLink(active=True, docs_repo="acme/acme-docs", kind="ok",
                                          reason="fine"),
                         corpus=_corpus(), docs_path=str(tmp_path), docs_commit=COMMIT,
                         requirements_dir=REQUIREMENTS_DIR)
    module = ProductModule(project, context=ctx, agent=_Harness("{}"))

    said = _yes(project, module, "queue", ["3", "1", "2"])

    assert build_board(project).items_in_status(QUEUE) == ["3", "1", "2"]
    assert said == ("Nina: Coloquei na fila, nesta ordem: #3, #1, #2. "
                    "A fábrica começa pelo primeiro."), said
