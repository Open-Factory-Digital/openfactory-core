"""She has to understand a yes in whatever words it comes — and never claim a write she cannot see.

TWO DEFECTS, ONE CONVERSATION, 2026-07-30. The product owner approved a staged requirement with:

    "Sim — registre.\\n\\nE duas coisas antes das decisões. Você estava certa e eu estava errado…"

`is_yes` requires EVERY word in the message to be an approval token, so it returned False. The draft
was never consumed, the message fell through to the conversational model, and the reply said
"Registrado o Requisito 1 … Vai para o time conferir" and "#321 e #135 fechados em #136". Nothing
was registered. Nothing was closed. He believed five requirements existed; the documentation repo
held one PR from the day before.

The product owner: *"having to be a 'yes - register it' every time makes no sense, she has to
understand affirmations in different forms."*

The first fix attempt widened the word list to the first sentence. It accepted his message AND
"certo — e quem audita isso?" — a question — because no vocabulary separates an affirmation from a
word that appears inside one. So the shape changed instead: the lexical gate stays narrow and fast,
and anything it cannot read goes to a MODEL, which is the only thing that can read it.

The second defect is the dangerous one and is independent of the first: she asserted an outcome she
has no way to observe. Writes happen on a path she never sees, only after an authorised
confirmation. A claim of completion is therefore never hers to make.
"""

from __future__ import annotations

import pytest

import openfactory.product.channel as pc
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.product.voice import claims_a_write

APPROVER = "U1"
ALICES_REPLY = ("Sim — registre.\n\nE duas coisas antes das decisões. Você estava certa e eu "
                  "estava errado. Minha premissa era que o risco do #290 é menor hoje.")


def _project():
    return Project(name="books", repo_path="/t",
                   tracker=ProviderRef(kind="github", repo="a/b"),
                   forge=ProviderRef(kind="github", repo="a/b"),
                   product=ProductConfig(docs_repo="a/docs", channel_id="C0PROD",
                                         admins=[APPROVER], agent_name="Nina"))


# ── 1. the lexical gate stays narrow, and that is on purpose ────────────────────────────────────
def test_the_word_list_still_refuses_what_it_cannot_read():
    """It is not the widened gate any more. It accepts the unambiguous and defers the rest — which
    is why it no longer has to grow a bigger vocabulary every time somebody phrases a yes."""
    assert pc.is_yes("sim") and pc.is_yes("sim, pode registrar") and pc.is_yes("aprovado")
    assert not pc.is_yes(ALICES_REPLY), "widening this is what accepted a question as consent"
    assert not pc.is_yes("certo — e quem audita isso?")


# ── 2. the model reads what the list cannot ─────────────────────────────────────────────────────
class _Judging:
    """A module whose confirmation judge is scripted, and whose write records the call."""

    def __init__(self, verdict: str):
        self.verdict, self.wrote, self.judged = verdict, [], []

    def settle_acceptance(self, text):
        return None

    def close_decisions_answered(self, *, channel=""):
        return 0

    def confirmed(self, reply, *, proposal):
        self.judged.append((reply, proposal))
        return self.verdict

    def note_fact(self, *, term, body, said_by, where=""):
        from types import SimpleNamespace
        self.wrote.append(term)
        return SimpleNamespace(ok=True, existed=False, detail="", ref="")


def _stage_fact():
    pc.remember("C0PROD", {"kind": "fact", "term": "erp", "body": "a firma usa Primavera",
                           "said_by": APPROVER})


@pytest.mark.parametrize("reply", [
    ALICES_REPLY,
    "Sim. Registre o Requisito 1.",
    "isso mesmo, manda",
    "perfeito, segue",
    "concordo, pode ir",
    "beleza, faz isso",
])
def test_an_affirmation_IN_ANY_FORM_records_it(reply):
    """The point of the whole change: what matters is the OUTCOME, not which gate got there.

    Asserting "the judge was consulted" would be asserting the mechanism — and it fails on
    "isso mesmo, manda", which the word list happens to accept already. Either route is correct;
    a yes that writes nothing is not.
    """
    mod = _Judging("approve")
    _stage_fact()

    pc.handle(_project(), text=reply, user=APPROVER, thread="C0PROD", channel="C0PROD", module=mod)

    assert mod.wrote == ["erp"], f"{reply!r} was a yes and wrote nothing"


def test_ALICES_ACTUAL_REPLY_goes_through_the_model():
    """The regression, with the exact sentence. The word list cannot read it — so if the judge is
    not consulted, this is the bug again."""
    mod = _Judging("approve")
    _stage_fact()

    pc.handle(_project(), text=ALICES_REPLY, user=APPROVER, thread="C0PROD", channel="C0PROD",
              module=mod)

    assert mod.judged, "the sentence that broke this is still falling through to conversation"
    assert mod.wrote == ["erp"]


def test_a_CONDITIONAL_yes_does_not_write():
    """"sim, mas mude o prazo primeiro" has not approved what is on the table. Reading it as
    approval is how a requirement nobody agreed to ends up with somebody's name on it."""
    mod = _Judging("reject")
    _stage_fact()

    pc.handle(_project(), text="sim, mas mude o prazo primeiro", user=APPROVER, thread="C0PROD",
              channel="C0PROD", module=mod)

    assert mod.wrote == [], "a qualified yes wrote something"


def test_an_UNCLEAR_reply_leaves_the_proposal_pending():
    """Biased towards neither: the person repeats themselves, which costs one message. The proposal
    must still be findable — an approval that arrives later has to have something to approve."""
    mod = _Judging("neither")
    _stage_fact()

    pc.handle(_project(), text="e quem audita isso?", user=APPROVER, thread="C0PROD",
              channel="C0PROD", module=mod)

    assert mod.wrote == []
    assert pc.pending_for("C0PROD") is not None, "the proposal was consumed by a non-answer"


def test_a_FAILED_judgment_never_invents_an_approval():
    """The judge is a model call and models fail. A failure must not open a write."""
    class _Boom(_Judging):
        def confirmed(self, reply, *, proposal):
            raise RuntimeError("harness down")

    mod = _Boom("approve")
    _stage_fact()
    pc.handle(_project(), text=ALICES_REPLY, user=APPROVER, thread="C0PROD", channel="C0PROD",
              module=mod)

    assert mod.wrote == [], "a broken judge wrote something"
    assert pc.pending_for("C0PROD") is not None


def test_the_judge_is_given_WHAT_IS_ON_THE_TABLE():
    """A judge shown no proposal is deciding about nothing. It must see what would be written."""
    mod = _Judging("neither")
    _stage_fact()

    pc.handle(_project(), text=ALICES_REPLY, user=APPROVER, thread="C0PROD", channel="C0PROD",
              module=mod)

    _reply, proposal = mod.judged[0]
    assert "erp" in proposal and "Primavera" in proposal, proposal


def test_the_judge_is_NOT_consulted_when_nothing_is_pending():
    """One extra model call per confirmation is affordable; one per message is not."""
    mod = _Judging("approve")
    pc.forget("C0PROD")

    pc.handle(_project(), text="oi, tudo bem?", user=APPROVER, thread="C0PROD", channel="C0PROD",
              module=mod)

    assert not mod.judged, "a model was asked to judge a confirmation nobody was waiting for"


# ── 3. she must never claim a write she cannot see ──────────────────────────────────────────────
@pytest.mark.parametrize("claim", [
    "Registrado o Requisito 1. Vai para o time conferir.",
    "#321 e #135 fechados em #136.",
    "Criei os cards e movi para Backlog.",
    "Já gravei o fato sobre o ERP.",
])
def test_a_claim_of_completion_is_detected(claim):
    """These are the sentences that shipped. Each states an outcome on a code path she never
    observes, and each one was false."""
    assert claims_a_write(claim), claim


@pytest.mark.parametrize("honest", [
    "Confirma e eu registro.",
    "A minha proposta é fechar #321 e #135 em #136 — confirme e eu registro o pedido.",
    "Assim que você aprovar, isto vira requisito.",
    "Não consigo dizer o que foi feito no #491.",
])
def test_an_honest_sentence_is_not_flagged(honest):
    assert claims_a_write(honest) == "", honest


def test_the_rule_reaches_the_prompt():
    """A voice rule the model never receives changes nothing — this repository has shipped that
    thirteen times."""
    from openfactory.product.role import ProductRole

    prompt = ProductRole(None)._prompt("x", "y", audience="client")
    assert "NEVER SAY SOMETHING HAPPENED" in prompt
    assert "Registrado o Requisito 1" in prompt, \
        "the real failing sentence is not shown to the model as a counterexample"


def test_the_channel_watches_for_it(capsys):
    """Detected, logged, alarmable. Not edited: a wrong correction of what an agent said is worse
    than a flagged sentence."""
    import ast
    from pathlib import Path

    src = Path("openfactory/product/channel.py").read_text()
    assert "OPENFACTORY_PRODUCT_FALSE_CLAIM" in src
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_handle")
    assert any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "claims_a_write"
               for n in ast.walk(fn)), "the detector is never called on her reply"


# ── 4. she is told what her own turn can do ────────────────────────────────────────────────────
def test_the_prompt_states_that_this_reply_writes_NOTHING():
    """THE ROOT CAUSE, and it was not blindness to the world. She already had the requirement index
    saying "(this product has no requirements written down yet)" and still announced a registered
    requirement. What the prompt never described was her own turn."""
    from openfactory.product.role import ProductRole

    prompt = ProductRole(None)._prompt("x", "y", audience="client")
    assert "WRITES NOTHING" in prompt
    assert "never see" in prompt, "she is not told the result does not come back to her"


def test_a_PENDING_proposal_is_named_in_the_prompt():
    """The decisive fact she was missing: whether the thing she proposed last time is still
    waiting. Without it, "did you register it?" has no answer she can look up — so she guessed the
    useful one."""
    from openfactory.product.role import ProductRole

    prompt = ProductRole(None, pending_proposal="requisito: IVA do pacote de fecho")._prompt(
        "x", "y", audience="client")

    assert "STILL AWAITING confirmation" in prompt
    assert "IVA do pacote de fecho" in prompt
    assert "never that it is done" in prompt


def test_with_nothing_staged_she_is_told_that_too():
    """Silence about state is what she fills in. "Nothing is pending" is information."""
    from openfactory.product.role import ProductRole

    assert "Nothing of yours is currently awaiting" in ProductRole(None)._prompt(
        "x", "y", audience="client")


def test_the_TEAM_prompt_gets_none_of_it():
    """An issue body is read by the executor. The agency block is about talking to a client."""
    from openfactory.product.role import ProductRole

    assert "WRITES NOTHING" not in ProductRole(None)._prompt("x", "y", audience="team")


def test_the_channel_hands_the_pending_state_to_the_module():
    """Reach: the block is fed from the staged entry, or it describes a world that is always empty."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("openfactory/product/channel.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "answer"
             and any(k.arg == "pending" for k in n.keywords)]
    assert calls, "module.answer() is called without the pending state — the block never fires"


# ── 5. the client is never left with the false claim ───────────────────────────────────────────
class _Lying:
    """A module whose reply claims a write that did not happen — the sentence that shipped."""

    def settle_acceptance(self, text):
        return None

    def close_decisions_answered(self, *, channel=""):
        return 0

    def confirmed(self, reply, *, proposal):
        return "neither"

    def context(self):
        from types import SimpleNamespace
        return SimpleNamespace(available=True, reason="")

    def answer(self, question, *, context="", conversation="", **_):
        from types import SimpleNamespace
        return SimpleNamespace(ok=True, is_defect=False, is_request=False, decisions=[],
                               text="Registrado o Requisito 1. Vai para o time conferir.")


def test_a_claim_of_completion_is_OBSERVED_but_not_corrected_in_the_channel(caplog):
    """THE APPEND WAS REMOVED, and the evidence is why.

    It shipped, and in production it fired TWICE — both times on sentences that were CORRECT. Once
    on a retraction ("eu disse 'Registrado o Requisito 1' … Não foi") and once on an accurate
    history ("o texto foi gravado, o pedido de revisão não abriu"). Zero true positives in the same
    window. A word list cannot separate "I recorded it just now" from "it was recorded last time";
    that needs tense and temporal reference.

    A wrong correction is expensive in a way a missed one is not: it contradicts the agent in front
    of the client, so the reader learns to distrust both voices — and it lands hardest on exactly
    the honest, self-correcting messages the rule exists to produce.

    The observation stays, so a REAL false claim is still visible to us (ADR-0031).
    """
    pc.forget("C0PROD")
    # WARNING, not ERROR: after four production firings — all four false positives ("Anotado",
    # "Anotei"), zero true — an ERROR that is always wrong teaches the log's reader to skip
    # ERRORs. The observation itself is what this test defends, at whatever level it logs.
    with caplog.at_level("WARNING"):
        reply = pc.handle(_project(), text="e aí?", user=APPROVER, thread="C0PROD",
                          channel="C0PROD", module=_Lying())

    assert reply == "Registrado o Requisito 1. Vai para o time conferir.", \
        f"the platform edited or appended to her message: {reply!r}"
    assert any("OPENFACTORY_PRODUCT_FALSE_CLAIM" in r.getMessage() for r in caplog.records), \
        "the claim is no longer observed either — we would not see a real one"


def test_the_TWO_sentences_that_were_wrongly_corrected():
    """Regression, with the exact production text. Neither may be treated as a claim about THIS
    turn — the first denies a write, the second describes a past one."""
    retraction = ("eu disse \"Registrado o Requisito 1\", \"#321 e #135 fechados em #136\". "
                  "Não foi. Eu não vejo o resultado de escrita nenhuma.")
    history = ("Foi exatamente isso que deu errado da última vez: o texto foi gravado, o pedido de "
               "revisão não abriu, e eu não tinha como enxergar a falha.")

    assert claims_a_write(retraction) == "", "a retraction still reads as a claim"
    # the history DOES still match the word list — which is precisely why the append had to go
    # rather than the list growing another exception
    assert claims_a_write(history), "the observation should still fire; only the append was removed"


def test_an_HONEST_reply_is_left_completely_alone():
    """The correction must be invisible when there is nothing to correct — a platform that appends
    warnings to clean messages trains people to skip them."""
    class _Honest(_Lying):
        def answer(self, question, *, context="", conversation="", **_):
            from types import SimpleNamespace
            return SimpleNamespace(ok=True, is_defect=False, is_request=False,
                                   decisions=[], text="Confirma e eu registro.")

    pc.forget("C0PROD")
    reply = pc.handle(_project(), text="e aí?", user=APPROVER, thread="C0PROD", channel="C0PROD",
                      module=_Honest())

    assert reply == "Confirma e eu registro." or "Correção automática" not in reply, reply


# ── 6. the detector's coverage is DERIVED, not imagined ────────────────────────────────────────
#: Every sentence this platform sends when a write REALLY succeeded, with arguments that make one.
#: The agent echoing one of these is the likeliest false claim there is — and the invented first
#: version of the detector could not see "Anotado", the very word `fact_noted` uses.
_SUCCESS_SENTENCES = [
    ("fact_noted", {"term": "erp"}),
    ("defect_filed", {"ref": "#88", "violates": 4}),
    ("written_up", {"title": "Editar conciliado", "url": "https://x/1", "number": 7}),
    ("queued", {"numbers": [1, 2]}),
]


@pytest.mark.parametrize(("fn", "kw"), _SUCCESS_SENTENCES,
                         ids=[f for f, _ in _SUCCESS_SENTENCES])
def test_every_success_sentence_is_detected(fn, kw):
    """The guard that keeps the vocabulary from falling behind the phrases. If somebody adds a new
    confirmation sentence, or rewords one, this fails until the detector can see it — which is the
    only way a hand-written word list stays honest."""
    from openfactory.product import voice

    text = getattr(voice, fn)(language="pt-BR", **kw)
    assert claims_a_write(text), f"{fn} says a write happened and the detector cannot see it: {text}"


@pytest.mark.parametrize("echoed", [
    "Anotado.",
    "anotei o que você disse",
    "Coloquei na fila",
    "Filei o defeito",
    "Movi para Backlog",
    "Já incluí no Backlog",
])
def test_the_blind_spots_that_shipped(echoed):
    """Each of these passed the first detector untouched."""
    assert claims_a_write(echoed), echoed


# ── 7. the platform must not correct her when she is RIGHT ─────────────────────────────────────
#: Verbatim from the first production message where the rule worked. She checked the documentation
#: repo, found nothing, and retracted three claims she had made the day before. The detector saw the
#: word "Registrado" inside the quotation and the platform appended "nada foi gravado; o texto acima
#: diz o contrário, e está errado" underneath — contradicting a sentence that said exactly that.
_HER_SELF_CORRECTION = (
    "Contei: zero. A pasta de requisitos tem um arquivo só, o modelo em branco de número 0000.\n\n"
    "Então corrijo o que escrevi na mensagem anterior: eu disse \"Registrado o Requisito 1\", "
    "\"#321 e #135 fechados em #136\", \"#323 fechado em #137\". Não foi. Eu não vejo o resultado "
    "de escrita nenhuma e não devia ter falado como se visse. Nada daquela mensagem existe fora "
    "dela."
)


def test_a_SELF_CORRECTION_is_not_corrected():
    """Being corrected while right is worse than not being corrected: it teaches the reader to
    distrust both voices, and it punishes the exact behaviour the rule exists to produce."""
    assert claims_a_write(_HER_SELF_CORRECTION) == "", "the platform contradicted a correct retraction"


@pytest.mark.parametrize("denial", [
    "As decisões da sua última mensagem também não foram registradas.",
    "Nada foi gravado ainda — falta a sua confirmação.",
    "Não vejo o resultado de escrita nenhuma.",
    "Me corrijo: não está registrado.",
])
def test_an_explicit_denial_suppresses_the_correction(denial):
    assert claims_a_write(denial) == "", denial


def test_a_BARE_false_claim_is_still_corrected():
    """The suppression must not become a loophole: a message that claims a write and never denies
    one is exactly what shipped, and must still be caught."""
    assert claims_a_write("Registrado o Requisito 1. Vai para o time conferir.")
    assert claims_a_write("#321 e #135 fechados em #136.")
