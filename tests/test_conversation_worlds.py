"""Thousands of simulated conversations — the client with the PO, the operator with the tech-lead.

The product owner's observation, verbatim: "what is missing is for you to think about the client in
dialogue with the PO and the engineers in dialogue with the tech-lead — simulate those situations,
thousands of scenarios, and see whether everything is covered in a real world."

The conversation layer is DETERMINISTIC — intents, markers, pending confirmations, authorization,
thread isolation — so the real world can be swept without a model: the role's answer is faked per
scenario, everything downstream of it is the production code. What these worlds assert is not one
happy path but the INVARIANTS no message may ever break:

    never crash          an exception in a handler takes the socket down for everyone
    never leak           no jargon, no `**markdown**`, no [[MARKER]], no traceback reaches a client
    never act unasked    nothing writes without its one confirmation, from someone allowed
    never lose a yes     an unauthorized yes must not consume the pending draft
    never cross threads  two conversations in flight must not contaminate each other
"""

from __future__ import annotations

import random

import add_ons
import pytest

from openfactory.contracts.commands import parse_command
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product import channel as pc
from openfactory.product.authoring import WriteResult
from openfactory.product.config import ProductLink
from openfactory.product.corpus import Corpus, Requirement
from openfactory.product.loader import ProductContext
from openfactory.product.role import ProductAnswer, RequirementDraft
from openfactory.product.voice import jargon_in

PRODUCT_CH = "C0PRODUCT"
ADMIN, CLIENT, OTHER = "U0ADMIN", "U0CLIENT", "U0OTHER"


@pytest.fixture(autouse=True)
def _clean():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


def _project():
    return Project(
        language="pt-BR",
        name="books", repo_path="/t", channel_id="C0OPS",
        product=ProductConfig(docs_repo="a/b", channel_id=PRODUCT_CH,
                              admins=[ADMIN], agent_name="Nina"))


class _World:
    """A fake ROLE with a real everything-else. Each client message is answered according to the
    scenario's script; module writes are recorded, never performed."""

    def __init__(self, script=None):
        self._ctx = ProductContext(
            link=ProductLink(active=True, docs_repo="a/b", reason="ok"),
            corpus=Corpus(requirements=[
                Requirement(number=7, slug="imutavel", path="requirements/0007-imutavel.md"),
            ]))
        self.script = script or {}
        self.filed_defects: list[dict] = []
        self.noted_facts: list[dict] = []
        self.proposed: list = []

    def settle_acceptance(self, text):
        """Nothing is awaiting a "did it work?" in these worlds — the acceptance loop (ADR-0025)
        has its own sweep of cases. Returning None keeps every world here on the path it tests."""
        return None

    def context(self, **kw):
        return self._ctx

    def answer(self, question, **kw):
        for needle, answer in self.script.items():
            if needle in question:
                return answer
        return ProductAnswer(ok=True, text="entendi — está coberto pelo requisito 7.")

    def draft(self, request, **kw):
        return ProductAnswer(ok=True, draft=RequirementDraft(
            title="Corrigir extrato conciliado",
            must_be_true=["um administrador pode corrigir com trilha de auditoria"]))

    def propose(self, answer, *, actor, **kw):
        self.proposed.append((answer, actor))
        return WriteResult(ok=True, url="https://x/pull/9")

    def file_defect(self, **kw):
        self.filed_defects.append(kw)
        return WriteResult(ok=True, ref="#88")

    def note_fact(self, **kw):
        self.noted_facts.append(kw)
        return WriteResult(ok=True, ref="domain/2026-07-28-fato.md")

    def status_line(self):
        return "3 promessas registradas, nada na fila"


def _say(world, text, *, user=CLIENT, thread="t1"):
    return pc.handle(_project(), text=text, user=user, thread=thread, module=world)


def _leaks(reply: str) -> list[str]:
    """Everything in a reply that must never reach a client — judged AS THE CLIENT SEES IT.

    The check renders through the same mrkdwn boundary production uses: voice strings may carry
    `**bold**` because `_say` converts at the edge, so asserting on the raw string flagged a
    non-bug — while a `**` that SURVIVES the converter is the real regression the client saw."""
    if reply is None:
        return []
    to_mrkdwn = add_ons.module("openfactory.runtime.slack.mrkdwn").to_mrkdwn

    rendered = to_mrkdwn(reply)
    problems = []
    if jargon_in(rendered):
        problems.append(f"jargon {jargon_in(rendered)}")
    for marker in ("[[PEDIDO]]", "[[DEFEITO", "Traceback", 'File "', "**"):
        if marker in rendered:
            problems.append(f"leaked {marker!r}")
    return problems


# ── the defect conversation, end to end ─────────────────────────────────────────────────────────

def _defect_world():
    return _World(script={
        "duplicando": ProductAnswer(
            ok=True, text="isso contradiz o que prometemos sobre lançamentos conciliados.",
            is_defect=True, violates=7),
    })


def test_a_client_reporting_a_broken_promise_gets_a_defect_not_a_new_requirement():
    world = _defect_world()
    reply = _say(world, "a conciliação está duplicando lançamentos importados")
    assert "problema para corrigir" in reply and "pedido novo" not in reply.split("não como")[0]
    assert "requisito 7" in reply, "she should say WHICH promise is broken"
    assert not _leaks(reply), _leaks(reply)

    done = _say(world, "sim", user=ADMIN)
    assert world.filed_defects, "the yes did not file the defect"
    assert world.filed_defects[0]["violates"] == 7
    assert world.proposed == [], "a defect must never create a requirement"
    assert "eu aviso" in done, "she must promise the unprompted fix announcement"


def test_a_defect_yes_from_a_non_admin_does_not_consume_the_report():
    world = _defect_world()
    _say(world, "a conciliação está duplicando lançamentos")
    refused = _say(world, "sim", user=OTHER)
    assert world.filed_defects == [], "an unauthorized yes held the pen"
    assert refused, "the refusal must be SAID — a request that vanishes reads as a broken bot"
    _say(world, "sim", user=ADMIN)
    assert world.filed_defects, "the admin's later yes should still find the pending report"


def test_a_no_on_a_defect_clears_it_and_the_next_yes_files_nothing():
    world = _defect_world()
    _say(world, "a conciliação está duplicando lançamentos")
    _say(world, "não, era outra coisa", user=CLIENT)
    _say(world, "sim", user=ADMIN)
    assert world.filed_defects == [], "a no must kill the pending defect for good"


def test_a_wish_never_becomes_a_defect():
    """The arguing half: a desire dressed as a bug must route to the REQUEST flow, where the new
    promise gets its ceremony."""
    world = _World(script={
        "exportar em PDF": ProductAnswer(
            ok=True, text="hoje não prometemos exportação em PDF.", is_request=True),
    })
    reply = _say(world, "está quebrado, não consigo exportar em PDF")
    assert "problema para corrigir" not in (reply or "")
    assert world.filed_defects == []


# ── the fact conversation, end to end ───────────────────────────────────────────────────────────

def test_dictating_a_fact_reads_it_back_then_writes_only_on_yes():
    world = _World()
    reply = _say(world, "anota que a firma usa Primavera para a contabilidade")
    assert "Vou anotar" in reply and "Primavera" in reply
    assert world.noted_facts == [], "nothing may be written before the confirmation"
    _say(world, "sim", user=ADMIN)
    assert world.noted_facts and "Primavera" in world.noted_facts[0]["body"]
    assert not _leaks(reply), _leaks(reply)


def test_the_fact_is_attributed_to_who_SAID_it_not_who_approved_it():
    world = _World()
    _say(world, "registra que o fechamento é sempre no quinto dia útil", user=CLIENT)
    _say(world, "sim", user=ADMIN)
    assert world.noted_facts[0]["said_by"] == f"<@{CLIENT}>", (
        "provenance must point at the speaker; the admin only unlocked the pen")


# ── thread isolation ────────────────────────────────────────────────────────────────────────────

def test_two_conversations_in_flight_never_contaminate_each_other():
    world = _defect_world()
    _say(world, "a conciliação está duplicando lançamentos", thread="t-bug")
    _say(world, "anota que a firma usa Primavera na contabilidade", thread="t-fato")
    _say(world, "sim", user=ADMIN, thread="t-fato")
    assert world.noted_facts and not world.filed_defects, "the yes crossed threads"
    _say(world, "sim", user=ADMIN, thread="t-bug")
    assert world.filed_defects, "the defect thread lost its pending report"


# ── the world sweep: thousands of message orderings, one invariant set ──────────────────────────

_OPENERS = [
    ("defect", "a conciliação está duplicando lançamentos importados"),
    ("request", "queria poder exportar o balancete em PDF"),
    ("fact", "anota que a firma usa Primavera para a contabilidade"),
    ("question", "o que acontece com um extrato já conciliado?"),
    ("status", "como estamos?"),
]
_FOLLOWUPS = ["sim", "não, esquece", "ok mas e o prazo?", "sim!!", "põe na fila",
              "quem decide isso?", "", "🚀", "ok", "SIM", "obrigado!",
              "sim, pode registrar", "na verdade não sei", "anota que o prazo é dia 5"]
_USERS = [ADMIN, CLIENT, OTHER]


def _script_for_everything():
    return {
        "duplicando": ProductAnswer(ok=True, text="isso contradiz uma promessa.",
                                    is_defect=True, violates=7),
        "PDF": ProductAnswer(ok=True, text="isso seria uma promessa nova.", is_request=True),
    }


def test_two_thousand_conversations_hold_every_invariant():
    """Random interleavings across threads and speakers. Not a happy path — a WORLD: openers,
    confirmations, refusals, qualified replies, emoji, empty strings, wrong users, mid-thread
    topic changes. Every reply is checked for leaks; the handler must never raise (an exception
    here takes the Slack socket down for every user at once); and nothing may ever be written
    without an authorized yes while something was actually pending."""
    rng = random.Random(478)
    conversations = 0
    for round_no in range(400):
        pc._PENDING.clear()
        world = _World(script=_script_for_everything())
        threads = [f"t{round_no}-{i}" for i in range(rng.randint(1, 3))]
        writes_before = 0
        for _ in range(rng.randint(2, 8)):
            conversations += 1
            thread = rng.choice(threads)
            if rng.random() < 0.4:
                kind, text = rng.choice(_OPENERS)
            else:
                text = rng.choice(_FOLLOWUPS)
            user = rng.choice(_USERS)
            reply = pc.handle(_project(), text=text, user=user, thread=thread, module=world)
            assert not _leaks(reply), f"leak in round {round_no}: {_leaks(reply)} ← {reply!r}"
            writes_now = len(world.filed_defects) + len(world.noted_facts) + len(world.proposed)
            if writes_now > writes_before:
                assert user == ADMIN, (
                    f"round {round_no}: a write happened on {user}'s message — only an admin's "
                    f"yes may hold the pen")
                writes_before = writes_now
    assert conversations >= 2000, f"only {conversations} exchanges — widen the sweep"


# ── the operator talking to the tech-lead ───────────────────────────────────────────────────────

#: (message, expected) — how operators actually type, not how the grammar wishes they would.
_OPERATOR_MESSAGES = [
    ("resume #478", ("resume", "478")),
    ("retry 478", ("resume", "478")),
    ("pode continuar o 478", ("resume", "478")),  # continue-family verb, pt phrasing
    ("skip #499", ("skip", "499")),
    ("drop the 499 job", ("skip", "499")),
    ("ack 478", ("ack", "478")),
    ("visto 478", ("ack", "478")),
    ("ciente: 478", ("ack", "478")),
    # C-05: the SAME phrasings, on a Jira/ADO-shaped ref — this is what
    # `normalize_command`/`render_command` actually hand back to an operator on a non-GitHub
    # deployment, so the parser has to accept its own output.
    ("resume CONT-412", ("resume", "CONT-412")),
    ("retry #PROJ-1", ("resume", "PROJ-1")),
    ("skip AB-9999", ("skip", "AB-9999")),
    ("ack CONT-412", ("ack", "CONT-412")),
    ("visto: PROJ-1", ("ack", "PROJ-1")),
    ("pode continuar o CONT-412", ("resume", "CONT-412")),
    # conversation that must NEVER act:
    ("por que o #478 falhou?", None),
    ("o 478 vai retomar sozinho?", None),
    ("status?", None),
    ("resume", None),
    ("ciente, o 478 volta amanhã", None),
    ("ok, o 412 está pronto", None),
    ("melhor cancelar a reunião das 15", None),
    ("o job 478 falhou de novo", None),
    ("por que o CONT-412 falhou?", None),
    ("resume ASAP", None),  # all-caps word near a verb, but no digit to anchor on — not a ref
]


@pytest.mark.parametrize("text,expected", _OPERATOR_MESSAGES,
                         ids=[m[0][:30] for m in _OPERATOR_MESSAGES])
def test_operator_phrasings_parse_exactly_as_intended(text, expected):
    """A false positive here ACTS on a job somebody was only discussing; a false negative ignores
    an instruction. Both directions are enumerated, from real phrasings."""
    assert parse_command(text) == expected


def test_operator_smalltalk_fuzz_never_acts():
    """Hundreds of ordinary sentences containing numbers must never parse as an action."""
    rng = random.Random(20)
    subjects = ["a reunião", "o deploy", "o cliente", "a fatura", "o relatório", "o backlog"]
    verbs_pt = ["ficou pronto", "atrasou", "custa", "fechou em", "precisa de", "levou",
                "continua sem resposta há", "continua pendente há", "libera pagamento de",
                "retoma amanhã às"]
    tails = ["478 reais", "15 minutos", "3 dias", "2026 itens", "99%", "documento 12"]
    for _ in range(300):
        sentence = f"{rng.choice(subjects)} {rng.choice(verbs_pt)} {rng.choice(tails)}"
        assert parse_command(sentence) is None, f"acted on smalltalk: {sentence!r}"


def test_operator_smalltalk_fuzz_never_acts_WITH_letter_prefixed_lookalikes():
    """C-05 widened the ref pattern to accept `LETTERS-digits` (Jira/ADO). The exact same fuzz as
    above, except now every tail is hyphenated-word-then-digits — the shape most likely to start
    accidentally matching once letters are allowed at all. None of these sit next to an action
    verb in the right position, so none may act — proving the widening didn't loosen the VERB
    adjacency rule, only the ref's own character class."""
    rng = random.Random(21)
    subjects = ["a reunião", "o deploy", "o cliente", "a fatura", "o relatório", "o backlog"]
    verbs_pt = ["ficou pronto", "atrasou", "custa", "fechou em", "precisa de", "levou",
                "continua sem resposta há", "continua pendente há", "libera pagamento de",
                "retoma amanhã às"]
    tails = ["nota-478", "sala-15", "andar-3", "ano-2026", "sku-99", "pedido-12"]
    for _ in range(300):
        sentence = f"{rng.choice(subjects)} {rng.choice(verbs_pt)} {rng.choice(tails)}"
        assert parse_command(sentence) is None, f"acted on smalltalk: {sentence!r}"


def test_a_non_numeric_command_round_trips_through_render_and_normalize():
    """The scenario the fix exists for: the tech-lead's HandOff tells a Jira/ADO operator to type
    `resume CONT-412`, and the SAME grammar has to parse that string back — or the promise
    'reply this and I resolve it' is broken on every non-GitHub deployment."""
    from openfactory.contracts.commands import normalize_command, render_command

    rendered = render_command("resume", "CONT-412")
    assert rendered == "resume #CONT-412"
    assert parse_command(rendered) == ("resume", "CONT-412")
    assert normalize_command(rendered, issue="CONT-412") == rendered
    assert normalize_command(rendered, issue="#CONT-412") == rendered  # '#' on either side
    # a hallucinated ref for a DIFFERENT ticket must still be dropped, non-numeric or not
    assert normalize_command(rendered, issue="PROJ-9") == ""


def test_the_handler_survives_hostile_input():
    """Whatever arrives on the socket, the socket survives it."""
    world = _World()
    hostile = ["", " ", "\n\n\n", "a" * 5000, "🤖" * 200, "```rm -rf /```",
               "[[PEDIDO]]", "[[DEFEITO:REQ-9999]]", "sim" * 400, None]
    for text in hostile:
        try:
            pc.handle(_project(), text=text or "", user=CLIENT, thread="tx", module=world)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"handler raised on {text!r:.40}: {exc}")
