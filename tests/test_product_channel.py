"""The product channel — routing, the single confirmation, and who may confirm.

The listener runs inside a Socket Mode loop, so the contract is: never raise, never stay silently
quiet on a request, and never let an unauthorised yes consume a draft the real approver still has
to find.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product import channel as pc
from openfactory.product.authoring import WriteResult
from openfactory.product.config import ProductLink
from openfactory.product.corpus import Corpus, Requirement
from openfactory.product.loader import ProductContext
from openfactory.product.role import Conflict, ProductAnswer, RequirementDraft

PRODUCT_CH, OPS_CH = "C0PRODUCT", "C0OPS"
APPROVER, CLIENT = "U0APPROVER", "U0CLIENT"


@pytest.fixture(autouse=True)
def _clean():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


def _project(**kw):
    cfg = kw.pop("product", {"docs_repo": "a/b", "slack_channel": PRODUCT_CH,
                             "slack_admins": [APPROVER]})
    return Project(name="books", repo_path="/t", language="pt-BR", channel_id=OPS_CH,
                   product=ProductConfig(**cfg) if cfg is not None else None, **kw)


class _Module:
    """A product module with the model replaced — the conversation logic is what is under test."""

    def __init__(self, *, available=True, answer="uma resposta", draft=None, propose=None):
        self._ctx = ProductContext(
            link=ProductLink(active=available, docs_repo="a/b",
                             reason="fine" if available else "o repo sumiu"),
            corpus=Corpus(requirements=[Requirement(number=4, slug="x", path="p")]))
        self._answer, self._draft, self._propose = answer, draft, propose
        self.proposed: list[tuple] = []

    def settle_acceptance(self, text):
        """No delivery is awaiting a "did it work?" in these cases — the conversation logic under
        test here is upstream of the acceptance loop (ADR-0025)."""
        return None

    def context(self, **kw):
        return self._ctx

    def answer(self, question, **kw):
        return ProductAnswer(ok=True, text=self._answer)

    def draft(self, request, **kw):
        return self._draft or ProductAnswer(ok=False, error="nada testável")

    def propose(self, answer, *, actor, **kw):
        self.proposed.append((answer, actor))
        return self._propose or WriteResult(ok=True, url="https://x/pull/1")


def _draft_answer(title="Editar conciliado", conflicts=()):
    return ProductAnswer(ok=True, draft=RequirementDraft(
        title=title, must_be_true=["um administrador pode corrigir"],
        conflicts=list(conflicts)))


# ── routing ─────────────────────────────────────────────────────────────────────────────────────

def test_only_the_product_channel_is_routed_here():
    p = _project()
    assert pc.is_product_channel(p, PRODUCT_CH) is True
    assert pc.is_product_channel(p, OPS_CH) is False
    assert pc.is_product_channel(p, "") is False


def test_a_project_without_the_module_never_reaches_this_path():
    """The tech-lead's channel is untouched by construction, not by care."""
    assert pc.is_product_channel(_project(product=None), PRODUCT_CH) is False


def test_a_switched_off_module_stops_routing_too():
    p = _project(product={"docs_repo": "a/b", "slack_channel": PRODUCT_CH, "enabled": False})
    assert pc.is_product_channel(p, PRODUCT_CH) is False


# ── the yes ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["sim", "Sim!", "isso mesmo", "pode registrar", "confirmo",
                                  "ok", "yes", "that's right", " pode seguir. "])
def test_a_plain_confirmation_is_recognised(text):
    assert pc.is_yes(text) is True


def test_certo_is_READ_rather_than_assumed():
    """`certo` MOVED from asserting to accompanying (#161), and this is the decision rather than a
    deletion. It asserted approval here — of a proposal that can promote tickets and spend money —
    while the operator channel merely allowed it and the floor's table had audited it out in as
    many words: "'understood' as often as 'do it'".

    Refusing it costs one model call and gains a reading in context; accepting it wrongly records
    a decision nobody made. That asymmetry is this surface's own stated rule — ambiguity goes to
    the judge, never to a closed verdict — and one word could not go on having three answers."""
    assert pc.is_yes("certo") is False
    assert pc.is_no("certo") is False, "it is not a rejection either — it is a question for a model"
    assert pc.is_yes("certo, pode registrar") is True, (
        "it must still ACCOMPANY a yes, or the confirmation people actually type stops working")


@pytest.mark.parametrize("text", [
    "ok mas e se o cliente não tiver conta?",
    "sim, porém só para administradores",
    "certo isso vale para extratos antigos?",
    "não",
    "",
])
def test_a_QUALIFIED_reply_is_never_read_as_a_yes(text):
    """Reading a qualified sentence as approval is how a requirement nobody agreed to ends up in
    the corpus with someone's name on it."""
    assert pc.is_yes(text) is False


# ── the single confirmation ─────────────────────────────────────────────────────────────────────

def test_a_draft_is_shown_for_confirmation_in_the_clients_words():
    from openfactory.product.voice import jargon_in

    mod = _Module(draft=_draft_answer())
    reply = pc.offer_draft(_project(), request="deixar admin editar", user=CLIENT,
                           thread="t1", module=mod)
    assert "Entendi certo" in reply
    assert "um administrador pode corrigir" in reply
    assert jargon_in(reply) == []
    assert pc.pending_for("t1") is not None


def test_a_conflict_is_shown_BEFORE_the_confirmation_is_asked_for():
    mod = _Module(draft=_draft_answer(conflicts=[
        Conflict(requirement=7, kind="contradicts", explanation="conciliado não pode mudar")]))
    reply = pc.offer_draft(_project(), request="x", user=CLIENT, thread="t1", module=mod)
    assert reply.index("requisito 7") < reply.index("Entendi certo")


def test_a_yes_records_the_requirement_and_says_so_without_mechanics():
    from openfactory.product.voice import jargon_in

    mod = _Module(draft=_draft_answer())
    pc.offer_draft(_project(), request="x", user=CLIENT, thread="t1", module=mod)
    reply = pc.handle(_project(), text="sim", user=APPROVER, thread="t1", module=mod)

    assert mod.proposed and mod.proposed[0][1] == APPROVER
    # NO URL, and the sentence depends on whether it LANDED. This fake returns a WriteResult with
    # `merged` at its default of False, which is the honest degradation: the proposal exists, the
    # team must finish it, and — the part that bit in production — she cannot read it yet herself.
    assert "https://x/pull/1" not in reply, "a code-forge link reached the client (ADR-0032)"
    assert "guardei em segurança" in reply and "não entrou na base" in reply, reply
    assert jargon_in(reply) == []
    assert pc.pending_for("t1") is None          # consumed


def test_the_confirmation_carries_who_asked_as_provenance():
    """That yes IS the record of who wanted this — asked for in the conversation with the person
    who wanted it, not on an artefact they would never open."""
    mod = _Module(draft=_draft_answer())
    pc.offer_draft(_project(), request="x", user=CLIENT, thread="t1", module=mod)
    pc.handle(_project(), text="sim", user=APPROVER, thread="t1", module=mod)
    assert pc.pending_for("t1") is None


# ── authority ───────────────────────────────────────────────────────────────────────────────────

def test_an_unauthorised_yes_does_NOT_consume_the_draft():
    """The real approver's later yes still has to find it. The tech-lead's action path learned
    this the same way."""
    mod = _Module(draft=_draft_answer())
    pc.offer_draft(_project(), request="x", user=CLIENT, thread="t1", module=mod)

    reply = pc.handle(_project(), text="sim", user=CLIENT, thread="t1", module=mod)
    assert mod.proposed == []
    assert reply and "aprova" in reply.lower()
    assert pc.pending_for("t1") is not None      # still there

    pc.handle(_project(), text="sim", user=APPROVER, thread="t1", module=mod)
    assert mod.proposed


def test_a_refusal_is_said_out_loud_not_swallowed():
    """A request that vanishes is indistinguishable from a broken bot, and the person repeats it."""
    mod = _Module(draft=_draft_answer())
    pc.offer_draft(_project(), request="x", user=CLIENT, thread="t1", module=mod)
    assert pc.handle(_project(), text="sim", user=CLIENT, thread="t1", module=mod)


def test_reading_is_open_to_anyone_in_the_channel():
    mod = _Module(answer="Conciliado não pode mudar (requisito 7).")
    reply = pc.handle(_project(), text="posso editar um conciliado?", user=CLIENT,
                      thread="t1", module=mod)
    assert "requisito 7" in reply


# ── failure behaviour ───────────────────────────────────────────────────────────────────────────

def test_an_unavailable_module_admits_it_would_be_guessing():
    mod = _Module(available=False)
    reply = pc.handle(_project(), text="uma pergunta", user=CLIENT, thread="t1", module=mod)
    assert "chute" in reply
    assert "sumiu" not in reply                  # the diagnosis stays with the team


def test_a_no_clears_the_draft_so_a_later_yes_cannot_resurrect_it():
    mod = _Module(draft=_draft_answer())
    pc.offer_draft(_project(), request="x", user=CLIENT, thread="t1", module=mod)
    pc.handle(_project(), text="não, não é isso", user=CLIENT, thread="t1", module=mod)
    assert pc.pending_for("t1") is None

    pc.handle(_project(), text="sim", user=APPROVER, thread="t1", module=mod)
    assert mod.proposed == []


def test_a_handler_exception_never_kills_the_socket():
    class _Boom:
        def settle_acceptance(self, text):
            raise RuntimeError("everything is on fire")

        def context(self, **kw):
            raise RuntimeError("everything is on fire")

    # The socket survives — AND the person hears something. Silence was the old behaviour and it
    # is the one answer a colleague never gives (see test_transcript_memory for the full contract).
    reply = pc.handle(_project(), text="oi", user=CLIENT, thread="t1", module=_Boom())
    assert reply and "quebrou do meu lado" in reply, reply


def test_a_failed_write_reports_instead_of_pretending():
    mod = _Module(draft=_draft_answer(), propose=WriteResult(ok=False, detail="não deu"))
    pc.offer_draft(_project(), request="x", user=CLIENT, thread="t1", module=mod)
    assert pc.handle(_project(), text="sim", user=APPROVER, thread="t1", module=mod) == "não deu"


def test_pending_drafts_do_not_grow_without_bound():
    """An unbounded dict in a long-lived worker is a leak, and the oldest unconfirmed draft is the
    least likely to ever be confirmed."""
    mod = _Module(draft=_draft_answer())
    for i in range(pc._MAX_PENDING + 25):
        pc.offer_draft(_project(), request="x", user=CLIENT, thread=f"t{i}", module=mod)
    assert len(pc._PENDING) <= pc._MAX_PENDING


# ── a request becomes a draft; a question does not ──────────────────────────────────────────────

class _AskingModule(_Module):
    """A module whose answer says the person was ASKING FOR SOMETHING."""

    def answer(self, question, **kw):
        return ProductAnswer(ok=True, text="Hoje não dá pra editar depois de conciliar.",
                             is_request=True)


def test_a_REQUEST_turns_into_a_draft_and_asks_for_confirmation():
    """Without this the write path is unreachable from the channel: every message gets a polite
    answer and nothing is ever written down."""
    mod = _AskingModule(draft=_draft_answer())
    reply = pc.handle(_project(), text="preciso que admin possa corrigir conciliado",
                      user=CLIENT, thread="t1", module=mod)
    assert "Entendi certo" in reply
    assert "Hoje não dá pra editar" in reply     # the answer is kept, not replaced
    assert pc.pending_for("t1") is not None


def test_a_QUESTION_is_answered_and_nothing_is_staged():
    mod = _Module(answer="Conciliado não muda (requisito 7).")
    reply = pc.handle(_project(), text="posso editar conciliado?", user=CLIENT,
                      thread="t1", module=mod)
    assert "requisito 7" in reply
    assert pc.pending_for("t1") is None


def test_a_request_the_role_could_not_draft_still_gets_its_answer():
    """A draft with nothing testable is refused upstream — the person must still hear something."""
    mod = _AskingModule()                        # no draft configured → draft() returns not-ok
    reply = pc.handle(_project(), text="melhora os relatórios", user=CLIENT,
                      thread="t1", module=mod)
    assert "Hoje não dá pra editar" in reply
    assert pc.pending_for("t1") is None


def test_the_marker_never_reaches_a_person():
    """It is plumbing between the role and the channel."""
    from openfactory.contracts import AgentRunResult
    from openfactory.product.role import REQUEST_MARKER, ProductRole

    class _H:
        name = "rec"

        def ask(self, *, sandbox, workspace, prompt, phase="ask"):
            return AgentRunResult(ok=True, summary=f"Hoje não dá.\n{REQUEST_MARKER}")

    class _S:
        def run(self, **kw):
            return 0, ""

    from openfactory.adapters.sandbox.base import Workspace

    res = ProductRole(_H()).answer(sandbox=_S(),
                                   workspace=Workspace(path="/tmp", branch="m", base_branch="m"),
                                   question="preciso de X")
    assert res.is_request is True
    assert REQUEST_MARKER not in res.text
    assert res.text == "Hoje não dá."


# ── the brownfield first pass: not built is fine, PRETENDING is not ─────────────────────────────

def test_asking_for_the_first_pass_now_STARTS_it():
    """This test used to assert the honest refusal ("ainda não consigo fazer esse levantamento
    sozinha") — correct while the pass was unwired, because implying it started would have been
    worse than admitting the gap. The pass is wired now, so the honest answer changed: it says it
    is running, warns the output is observations rather than promises, and reports back when the
    pull request exists."""
    module = _Module()
    module.status_line = lambda: "3 requisitos, nada na fila"
    module.baseline = lambda **kw: WriteResult(ok=True, url="https://x/pull/9")

    reply = pc._baseline_reply(_project(), module, "Nina", APPROVER)

    assert "ainda não consigo" not in reply, "it is wired — this is the stale refusal"
    assert "minutos" in reply, "it must say the pass takes time rather than going quiet"
    assert "OBSERVA" in reply.upper(), "it must warn the output is not a set of promises"

def test_the_honest_refusal_still_speaks_the_clients_language():
    """An apology written in delivery jargon is still a message the client cannot use."""
    from openfactory.product.voice import jargon_in

    module = _Module()
    module.status_line = lambda: "nada pendente"
    reply = pc._baseline_reply(_project(), module, "Nina", APPROVER)
    assert not jargon_in(reply), f"jargon leaked into the refusal: {jargon_in(reply)}"


def test_an_unauthorised_person_gets_the_refusal_not_the_admission():
    module = _Module()
    module.status_line = lambda: "nada pendente"
    reply = pc._baseline_reply(_project(), module, "Nina", CLIENT)
    assert "ainda não consigo" not in reply
