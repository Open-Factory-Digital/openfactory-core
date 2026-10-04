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
"""

from __future__ import annotations

import ast
import io
import json
import re
import urllib.error
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
    "_listed": lambda a, b, lang: voice._listed([a, b]),
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
    "card_moved": lambda a, b, lang: [voice.card_moved(notice, ref=a, title="T", language=lang)
                                      for notice in ("stopped_work", "back")],
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
     "Aberto: #12. Fica no Backlog até o time aprovar a próxima leva — e quando sair, eu aviso "
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
    `unranked`."""

    def __init__(self, *cards: str) -> None:
        self.status = dict.fromkeys(cards, BACKLOG)
        self.refuses: set[str] = set()
        self.unranked: set[str] = set()
        self.ranked: list[dict] = []

    def urlopen(self, req, timeout=0):  # noqa: ARG002 — urllib's own signature
        method, url = req.get_method(), req.full_url
        body = json.loads(req.data) if req.data else None
        if url.endswith("/rest/agile/1.0/issue/rank") and method == "PUT":
            if set(body["issues"]) & self.unranked:
                raise urllib.error.HTTPError(url, 400, "rank refused", {}, io.BytesIO(b"{}"))
            self.ranked.append(body)
            return _Answer(None)
        path = url.split("/rest/api/3/", 1)[1]
        if method == "GET" and path.startswith("search/jql?"):    # the board's own read
            return _Answer({"isLast": True, "issues": [{"key": k} for k, s in self.status.items()
                                                       if s == BACKLOG]})
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
    the detail is the whole reply."""
    project, site, module = _jira(monkeypatch, tmp_path, language="en")
    site.refuses = {"DAR-9", "DAR-10"}

    said = _yes(project, module, "queue", ["DAR-9", "DAR-10"])

    assert site.status == {"DAR-9": BACKLOG, "DAR-10": BACKLOG}
    assert said == "the board refused the move", said


class _Down:
    """A board that is there and raises on every move — the branch Jira's adapter never reaches,
    since it answers False for everything that goes wrong."""

    def add_item(self, *, issue_url):
        return None

    def set_column(self, *, issue, issue_url, name):
        raise RuntimeError("board down: POST /rest/api/3/issue/transitions 503")

    def place_after(self, *, issue, issue_url, after, column):
        raise RuntimeError("board down: PUT /rest/agile/1.0/issue/rank 503")


@pytest.mark.parametrize(("language", "queue", "order"), [
    ("pt-BR", "não consegui mover o DAR-9 para a fila agora. O time foi avisado e resolve.",
     "não consegui reposicionar o DAR-9 agora. O time foi avisado e resolve."),
    ("en", "I could not move DAR-9 into the queue just now. The team has been told and will sort "
           "it out.",
     "I could not put DAR-9 in its place just now. The team has been told and will sort it out."),
])
def test_a_move_that_raised_names_the_jira_card_in_the_conversations_language(
        monkeypatch, tmp_path, language, queue, order):
    _project, _site, module = _jira(monkeypatch, tmp_path, language=language, board=_Down(),
                                    ranks=True)

    [queued] = module.promote(["DAR-9"], actor=ANA)
    [ordered] = module.reorder(["DAR-9"], actor=ANA)

    assert (queued.ok, queued.detail) == (False, queue)
    assert (ordered.ok, ordered.detail) == (False, order)


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


def test_promote_and_reorder_compose_no_detail_of_their_own():
    """Every detail the two verbs answer comes from the voice — a literal or an f-string here is a
    sentence in one language, and the one that named a card wrote `#{number}`."""
    tree = ast.parse((ROOT / "openfactory/product/module.py").read_text(encoding="utf-8"))
    verbs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name in ("promote", "reorder")}
    assert set(verbs) == {"promote", "reorder"}
    def text(node) -> list[ast.AST]:
        """The strings `node` itself spells — not the arguments of a call it makes, where the
        voice's own key (`"queue_refused"`) is an argument and not a sentence."""
        if isinstance(node, ast.Call):
            return []
        if isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant)
                                               and isinstance(node.value, str)
                                               and node.value.strip()):
            return [node]
        return [found for child in ast.iter_child_nodes(node) for found in text(child)]

    written = []
    for name, verb in verbs.items():
        for node in ast.walk(verb):
            said = [k.value for k in getattr(node, "keywords", []) if k.arg == "detail"]
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_could_not":
                said += node.args[:1]
            written += [f"{name}:{n.lineno}" for value in said for n in text(value)]
    assert not written, f"a detail written in the module: {written}"


# ── the guard ────────────────────────────────────────────────────────────────────────────────────

#: The modules whose strings are sentences a person reads.
SENTENCES = ("openfactory/product/voice.py", "openfactory/product/followup.py",
             "openfactory/product/engine.py")

#: `(file, the function or table it is in)` → why it may still write a `#` before a card.
ALLOWED = {
    ("openfactory/product/voice.py", "queued"):
        "#491 (PR #498) rewrites this one line to `ref_label`, with the refs it is handed; it is "
        "left alone here so the two merge cleanly. Delete this entry when that lands.",
}

#: A format placeholder straight after a literal `#` — `#{number}`, `#{0}`, `#{}`, `*#{ref}*` —
#: and never an escaped `#{{`, nor a regex quantifier like `#{1,6}`.
_HASHED_FIELD = re.compile(r"#\{(?!\{)(?:[A-Za-z_][\w.\[\]]*|\d*)(?:![rsa])?(?::[^{}]*)?\}")
_HASHED_PERCENT = re.compile(r"#%(?:\([^)]*\))?[sdr]")


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
'''
    found = {(name, line) for line, name, _what in hashed_refs(source)}

    assert {name for name, _ in found} == {"_TABLE", "_POSITIONAL", "_PERCENT", "listed", "bold",
                                           "glued"}, found
    assert len(found) == 6, found


def test_the_allowlist_names_only_what_still_exists():
    """An entry whose function is gone is a hole nobody opened on purpose."""
    for (rel, name), why in ALLOWED.items():
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        names |= {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                  for t in n.targets if isinstance(t, ast.Name)}
        assert name in names, f"ALLOWED names {rel}::{name}, which is gone"
        assert why.strip(), f"ALLOWED names {rel}::{name} without saying why"
