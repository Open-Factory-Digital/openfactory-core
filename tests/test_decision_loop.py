"""What she asks a person for becomes a tracked commitment — ADR-0026.

THE CONVERSATION THAT CAUSED THIS. Nina ended a real reply with three explicit requests: close or
not the 11 cards in Review, what to do with the 9 uncolumned items and #284, and whether #491/#492
finish or get suspended. The ledger recorded NONE of them. Loops were only ever opened by the board
sweep, so a request made in conversation lived in a chat message and died when it scrolled away —
nobody chased, nobody was reminded, and the platform's standing invariant (no silent wait) was
broken in the one place a client can see.

THE TRAP THAT SHAPED THE DESIGN. A decision must not be a `QUESTION` loop. `followup.answered()`
closes every open QUESTION whose `subject:about` is missing from the board's live findings — and a
decision asked in a chat has no board finding at all, so the very next sweep would have closed it
as "resolved" minutes after it was made. Silently. Its own kind is what keeps it out of that rule,
and the first test here is that guard.
"""

from __future__ import annotations

import pytest

import openfactory.adapters.channel as channel_pkg
import openfactory.memory.store as loop_store
import openfactory.product.channel as pc
import openfactory.runtime.temporal.activities as activities_mod
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.memory.ledger import DECISION, QUESTION, fold, open_loop, waiting
from openfactory.product import followup
from openfactory.product.module import ProductModule, _decision_key
from openfactory.product.triage import TriageReport
from openfactory.runtime.temporal.activities import _product_followup

CHANNEL = "C0PROD"


def _project():
    return Project(name="books", repo_path="/t",
                   # THE CLIENT THIS SUITE IS ABOUT IS BRAZILIAN (#160). It was implicit
                   # while every composer wrote pt-BR unconditionally; now that they take
                   # the project's language, saying so is what proves the wiring — an
                   # unset language answers in English, which is the product's default.
                   language="pt-BR",
                   tracker=ProviderRef(kind="github", repo="a/b"),
                   forge=ProviderRef(kind="github", repo="a/b"),
                   product=ProductConfig(docs_repo="a/docs", channel_id=CHANNEL,
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


@pytest.fixture()
def wired(monkeypatch):
    import openfactory.product.authoring as authoring

    channel, rows = _Channel(), []
    monkeypatch.setattr(channel_pkg, "build_channel", lambda p=None: channel)
    monkeypatch.setattr(activities_mod, "_metrics_sink", lambda *a, **k: _Sink())
    monkeypatch.setattr(loop_store, "read", lambda project: list(rows))
    monkeypatch.setattr(loop_store, "write", lambda project, loops: rows.extend(loops))
    # THE SAME SEAM PRODUCTION ROUTES THROUGH. This faked `authoring._gh`, one layer down, back
    # when the sweep shelled out to `gh`; the sweep speaks to the ForgeAdapter port now (#95) and
    # the port IS the seam. Without it, any path reaching the sweep's proposal rescue makes live
    # API calls against the shared App rate limit — from a unit test.
    #
    # `monkeypatch.setattr` on a name that no longer exists RAISES, which is why this surfaced as
    # a loud error rather than as a patch that quietly stopped intercepting anything. That is the
    # good failure mode, and it is worth keeping in mind for seams patched by string.
    monkeypatch.setattr(authoring, "land_open_proposals", lambda **kw: [])
    return channel, rows


def _module():
    class _M(ProductModule):
        def __init__(self):
            self.project = _project()
    return _M()


# ── the trap ───────────────────────────────────────────────────────────────────────────────────
def test_a_decision_is_NOT_swept_away_by_the_board_rule(wired):
    """`answered()` closes questions whose finding is gone. A decision has no finding — if it were
    a QUESTION it would be closed as "resolved" by the next sweep, minutes after being asked."""
    _channel, rows = wired
    _module().record_decisions(["fechar ou não os 11 cards em Review"], channel=CHANNEL)

    live = [x for x in waiting(fold(rows), owner=followup.OWNER)]
    closed = followup.answered(live, live_keys=set())  # the board reports NOTHING

    assert live and live[0].kind == DECISION, [x.kind for x in live]
    assert not closed, f"the board sweep would have silently closed it: {closed}"
    assert DECISION != QUESTION


# ── opening ────────────────────────────────────────────────────────────────────────────────────
def test_the_three_real_requests_become_three_loops(wired):
    """The product owner's actual message, verbatim from the conversation that exposed the hole."""
    _channel, rows = wired
    asked = ["fechar ou não os 11 cards que estão na coluna Review",
             "o que fazer com os 9 itens sem coluna e o #284",
             "se o #491 e o #492 acabam ou ficam suspensos"]

    assert _module().record_decisions(asked, channel=CHANNEL) == 3
    live = [x for x in waiting(fold(rows), owner=followup.OWNER) if x.kind == DECISION]
    assert len(live) == 3
    assert all(x.context.get("asked") for x in live), "a loop with no text cannot be chased"


def test_re_asking_the_same_decision_does_not_stack_a_second_reminder(wired):
    """She has memory now and may restate a pending decision. Two loops would chase the person
    twice about one thing, which reads as a machine that is not listening."""
    _channel, rows = wired
    mod = _module()
    mod.record_decisions(["fechar ou não os 11 cards em Review"], channel=CHANNEL)
    added = mod.record_decisions(["Fechar ou nao os 11 cards em Review!"], channel=CHANNEL)

    assert added == 0, "the same decision was recorded twice"


def test_the_key_is_readable_by_a_human():
    """It shows up in the ledger and the panel. `fechar-nao-cards...` can be acted on; a hash
    cannot."""
    key = _decision_key("Fechar ou não os 11 cards que estão na coluna Review")
    assert "fechar" in key and "cards" in key, key
    assert len(key) <= 60


# ── the conversation wires it ──────────────────────────────────────────────────────────────────
def test_a_reply_that_ASKS_records_it_through_handle(wired):
    """End to end: the model declares the decision with a marker, the channel records it, and the
    marker never reaches the person."""
    _channel, rows = wired

    class _M:
        def settle_acceptance(self, text):
            return None

        def close_decisions_answered(self, *, channel=""):
            return 0

        def context(self):
            from types import SimpleNamespace
            return SimpleNamespace(available=True, reason="")

        def answer(self, question, *, context="", conversation="", **_):
            from types import SimpleNamespace
            return SimpleNamespace(ok=True, text="preciso que você decida isso.",
                                   is_defect=False, asked_for_something=False,
                                   decisions=["fechar ou não os 11 cards em Review"])

        record_decisions = ProductModule.record_decisions
        project = _project()

    reply = pc.handle(_project(), text="organiza o backlog", user="U1", thread=CHANNEL,
                      channel=CHANNEL, module=_M())

    assert reply and "DECISAO" not in reply, f"plumbing leaked to the client: {reply}"
    live = [x for x in waiting(fold(rows), owner=followup.OWNER) if x.kind == DECISION]
    assert live, "she asked and nothing was recorded — the request dies with the message"


def test_a_reply_that_asks_NOTHING_records_nothing(wired):
    """A decision recorded that nobody was asked for gets chased at a person who has no idea what
    it refers to."""
    _channel, rows = wired

    class _M:
        def settle_acceptance(self, text):
            return None

        def close_decisions_answered(self, *, channel=""):
            return 0

        def context(self):
            from types import SimpleNamespace
            return SimpleNamespace(available=True, reason="")

        def answer(self, question, *, context="", conversation="", **_):
            from types import SimpleNamespace
            return SimpleNamespace(ok=True, text="a conciliação cobre dois bancos.",
                                   is_defect=False, asked_for_something=False, decisions=[])

    pc.handle(_project(), text="quais bancos?", user="U1", thread=CHANNEL, channel=CHANNEL,
              module=_M())

    assert not [x for x in fold(rows) if x.kind == DECISION]


# ── closing ────────────────────────────────────────────────────────────────────────────────────
def test_the_persons_next_message_closes_what_she_asked(wired):
    """The observation is the human speaking — the same standard the acceptance loop uses. Partial
    answers are safe: she has the conversation in memory and re-asks what is still undecided."""
    _channel, rows = wired
    _module().record_decisions(["fechar ou não os 11 cards em Review"], channel=CHANNEL)

    assert _module().close_decisions_answered(channel=CHANNEL) == 1
    live = [x for x in waiting(fold(rows), owner=followup.OWNER) if x.kind == DECISION]
    assert not live, "she will keep chasing somebody who already answered"
    closed = [x for x in fold(rows) if x.kind == DECISION]
    assert closed[0].outcome == "answered", closed[0].outcome


def test_closing_happens_BEFORE_her_new_reply_can_open_more(wired):
    """Ordering contract. Closing afterwards would either wipe the ones she just opened, or leave
    the previous round's open for ever."""
    import ast
    from pathlib import Path

    src = Path("openfactory/product/channel.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_handle")
    lines = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None)
            if name in ("close_decisions_answered", "record_decisions"):
                lines[name] = node.lineno
    assert lines.get("close_decisions_answered", 1e9) < lines.get("record_decisions", 0), lines


# ── chasing ────────────────────────────────────────────────────────────────────────────────────
def test_an_unanswered_decision_is_chased_ONCE_and_repeats_the_question(wired):
    """A reminder days later must carry the decision with it: "voltando naquilo que te perguntei"
    is a reminder only for somebody who already remembers — exactly who does not need one."""
    channel, rows = wired
    rows.append(open_loop(DECISION, "fechar-cards-review", owner=followup.OWNER, about=CHANNEL,
                          ts="2020-01-01T00:00:00+00:00",
                          context={"asked": "fechar ou não os 11 cards que estão na coluna Review"}))
    project = _project()

    class _Mod:
        _board_tickets: list = []
        token = None

    _product_followup(project, _Mod(), TriageReport(), project.product)
    first = [p for p in channel.posts if "coluna Review" in p]
    _product_followup(project, _Mod(), TriageReport(), project.product)
    again = [p for p in channel.posts if "coluna Review" in p]

    assert len(first) == 1, f"chased {len(first)} times in one pass"
    assert len(again) == 1, "chased again — a reminder loop the person cannot escape"
    assert "paro de perguntar" in first[0], "no exit offered"
    assert [x for x in waiting(fold(rows), owner=followup.OWNER) if x.kind == DECISION], \
        "time closed a decision nobody made"


# ── the markers that actually shipped ──────────────────────────────────────────────────────────
#: Verbatim from the product owner's third real conversation (2026-07-29). All three were REJECTED
#: by the first regex, whose label cap was 120 characters — while the prompt asks for a
#: self-contained sentence naming the cards, which is naturally longer. One arbitrary constant produced two
#: failures at once: nothing was recorded, and all three appeared raw in the client's channel.
_REAL_MARKERS = [
    "[[DECISAO: Aprovar a ordem de trabalho proposta para o backlog (começando por #288, #290, "
    "#166, depois #285 e #297) e autorizar Nina a escrever os requisitos desses cards antes de o "
    "desenvolvimento arrancar]]",
    "[[DECISAO: Fechar sem executar os 11 cards de endpoint de diagnóstico na coluna In review "
    "(#167, #175, #179, #189, #192, #194, #198, #202, #205, #207, #222), dado que já existem doze "
    "endpoints equivalentes publicados]]",
    "[[DECISAO: Definir se os 9 cards hoje sem coluna (#286, #289, #293, #295, #298, #301, #304, "
    "#308, #311) entram na ordem proposta junto com #302/#306/#299 ou são fechados]]",
]


@pytest.mark.parametrize("marker", _REAL_MARKERS)
def test_a_REAL_decision_label_is_parsed(marker):
    """Regression, with the exact strings. A self-contained label naming eleven cards is long by
    necessity — the instruction and the parser must not contradict each other."""
    from openfactory.product.role import _DECISION_RE

    m = _DECISION_RE.search(marker)
    assert m, f"{len(marker)} chars and no match — the cap is fighting the prompt"
    assert len(m.group("label")) > 120, "the case that failed is no longer being exercised"


def test_an_UNPARSED_marker_never_reaches_the_client():
    """PARSE NARROWLY, STRIP BROADLY. Losing plumbing is recoverable — the log says it happened.
    Printing it at a client is not, and that is exactly what shipped: three raw [[DECISAO: …]]
    blocks in a business channel."""
    from openfactory.product.role import _ANY_MARKER_RE, _DECISION_RE

    text = ("a resposta dela.\n[[DECISAO: algo normal]]\n[[MARCADOR_QUE_NINGUEM_ESCREVEU: x]]\n"
            "[[PEDIDO_COM_TYPO]]")
    clean = _ANY_MARKER_RE.sub("", _DECISION_RE.sub("", text))

    assert "[[" not in clean and "]]" not in clean, clean
    assert "a resposta dela." in clean, "the answer itself was eaten"


def test_the_prompt_demands_one_marker_per_decision():
    """She listed six decisions in prose and emitted three markers. Three requests existed only in
    a chat message — the failure this whole loop exists to prevent."""
    import inspect

    from openfactory.product.role import ProductRole

    # the instruction lives in `answer()`'s task text, which is where the marker is asked for —
    # asserting on the generic `_prompt()` would pass while the real prompt said nothing
    task = inspect.getsource(ProductRole.answer)
    assert "ONE MARKER PER DECISION" in task
    assert "six marker lines" in task, "the instruction does not make the count explicit"
    assert "Length is not a problem" in task, "the prompt still implies labels must be short"


def test_an_OVERLONG_marker_is_RECORDED_now_and_still_never_leaks():
    """THE CONSTANT COST SOMETHING FOUR TIMES: 120, then 400, then 400 shared with the net, and on
    2026-07-31 a real decision longer than 400 was stripped correctly and LOST — never recorded,
    never chased. The ceiling was always redundant, because the tempered class cannot cross `]]`.

    So the assertion flipped: a long label is now PARSED (the commitment exists), and — unchanged
    and still the point — nothing marker-shaped reaches a person either way."""
    from openfactory.product.role import _ANY_MARKER_RE, _DECISION_RE

    for size in (450, 2000):
        big = "[[DECISAO: " + "x" * size + "]]"
        m = _DECISION_RE.search(big)
        assert m and len(m.group("label")) == size, f"a {size}-char decision was dropped"
        clean = _ANY_MARKER_RE.sub("", _DECISION_RE.sub("", big))
        assert "[[" not in clean and "]]" not in clean, f"{size} chars reached the client"


def test_a_LOST_decision_is_shouted_not_merely_warned():
    """A decision the agent asked for that the parser could not read will never be recorded and
    never chased. That is the exact silent loss the decision ledger exists to prevent, so it gets a
    marker an alarm can page on rather than a line in a list of warnings."""
    from pathlib import Path

    src = Path("openfactory/product/role.py").read_text()
    assert "OPENFACTORY_PRODUCT_LOST_MARKER" in src
    assert "_DECISION_SHAPED_RE" in src, "nothing distinguishes a lost decision from other plumbing"


# ── the gate: only a message she READS answers a decision ──────────────────────────────────────
def test_a_STATUS_message_does_not_close_the_decisions(wired):
    """The critical one. Closing rested on "a partial answer is safe because she re-asks what is
    still undecided" — true only if she reads the message. `status` answers from the board already
    in hand and never reaches the model, so three chased decisions were closed as `answered` and
    nothing would ever ask again."""
    _channel, rows = wired
    _module().record_decisions(["fechar ou não os 11 cards em Review"], channel=CHANNEL)

    class _M:
        def settle_acceptance(self, text):
            return None

        close_decisions_answered = ProductModule.close_decisions_answered
        project = _project()

        def status_line(self):
            return "3 em andamento"

    pc.handle(_project(), text="status", user="U1", thread=CHANNEL, channel=CHANNEL, module=_M())

    live = [x for x in waiting(fold(rows), owner=followup.OWNER) if x.kind == DECISION]
    assert live, "a status query silently closed a decision nobody answered"


def test_a_REAL_reply_still_closes_them(wired):
    """The gate must not break the legitimate path: a message that reaches her IS the answer."""
    _channel, rows = wired
    _module().record_decisions(["fechar ou não os 11 cards em Review"], channel=CHANNEL)

    class _M:
        def settle_acceptance(self, text):
            return None

        close_decisions_answered = ProductModule.close_decisions_answered
        project = _project()

        def context(self):
            from types import SimpleNamespace
            return SimpleNamespace(available=True, reason="")

        def answer(self, question, *, context="", conversation="", **_):
            from types import SimpleNamespace
            return SimpleNamespace(ok=True, text="entendido", is_defect=False, is_request=False,
                                   decisions=[])

    pc.handle(_project(), text="fecha os 11, e o #250 entra por último", user="U1",
              thread=CHANNEL, channel=CHANNEL, module=_M())

    live = [x for x in waiting(fold(rows), owner=followup.OWNER) if x.kind == DECISION]
    assert not live, "an answer she read left the decisions open for ever"


# ── the leak that shipped three times ──────────────────────────────────────────────────────────
#: Verbatim from production. Its label names a board card, and board cards carry bracketed prefixes
#: as a matter of course — "[Product] Decrypt document metadata …". The pattern was `[^\]\n]`, which
#: stops at that inner `]`, never reaches the closing `]]`, and so the marker was NEITHER parsed NOR
#: stripped. Third leak of the day, third distinct cause: a length cap, then a bounded safety net,
#: now a character class that forbade the very characters real labels contain.
_REAL_MARKER_WITH_BRACKETS = (
    "[[DECISAO: O Requisito 1 passa a ser a origem do card #288 — [Product] Decrypt document "
    "metadata before building the month-close pack (fix silent 0,00 IVA) —, sem abrir card novo "
    "que o duplique?]]"
)


def test_a_label_containing_brackets_is_parsed_and_stripped():
    from openfactory.product.role import _ANY_MARKER_RE, _DECISION_RE

    m = _DECISION_RE.search(_REAL_MARKER_WITH_BRACKETS)
    assert m, "a decision about a card with a bracketed title is lost"
    assert "[Product]" in m.group("label"), "the label was truncated at the inner bracket"

    clean = _ANY_MARKER_RE.sub("", _DECISION_RE.sub("", _REAL_MARKER_WITH_BRACKETS))
    assert "[[" not in clean and "]]" not in clean, clean


def test_TWO_markers_on_one_line_stay_two():
    """The side effect of the first fix. Non-greedy alone was not enough: with a minimum label
    length, the shortest legal match had to grow past the first `]]` to reach it — so two decisions
    became one row with a nonsense label, and one of them was silently lost."""
    from openfactory.product.role import _ANY_MARKER_RE, _DECISION_RE

    two = "[[DECISAO: primeira decisao]] texto no meio [[DECISAO: segunda decisao]]"
    labels = [m.group("label") for m in _DECISION_RE.finditer(two)]

    assert labels == ["primeira decisao", "segunda decisao"], labels
    assert "[[" not in _ANY_MARKER_RE.sub("", _DECISION_RE.sub("", two))


def test_the_safety_net_still_catches_what_the_parser_rejects():
    """The invariant that survived all four causes: whatever fails to parse must still never reach
    a person. With the length ceiling gone, the cases the parser genuinely declines are a label
    broken across lines, a marker nobody taught it, and a label too short to be one."""
    from openfactory.product.role import _ANY_MARKER_RE, _DECISION_RE

    for rejected in ("[[MARCADOR_NOVO: algo que parser nenhum conhece]]",
                     "[[DECISAO_V2: uma forma que ninguem ensinou]]",
                     "[[SUGGEST: resume #69]]"):
        assert not _DECISION_RE.search(rejected), f"{rejected!r} is no longer a rejection"
        clean = _ANY_MARKER_RE.sub("", _DECISION_RE.sub("", rejected))
        assert "[[" not in clean and "]]" not in clean, rejected
