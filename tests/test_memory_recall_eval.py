"""Twenty hand-written recall cases — the evaluation the memory design asks for.

WHY THIS FILE EXISTS. The reference model the product owner brought is blunt about it: an
evaluation set is
what separates memory that works from memory that LOOKS like it works, and almost nobody writes
one. Every other test in this repository checks plumbing — that a row is written, that a function
is called. None of them can tell whether the thing that answers a question actually reaches the
model, which is the only property a user experiences.

WHAT IT HONESTLY MEASURES, AND WHAT IT DOES NOT. Each case is: turns were said, later a question
is asked, and the material that answers it MUST appear in the text handed to the agent. That is
the retrieval half of "does she remember?" — deterministic, free, and the half that regresses when
somebody changes a key, a budget, an ordering or a scan window.

It does NOT evaluate the model's judgment: whether she reasons well from what she was given is not
knowable without spending money and accepting nondeterminism in CI. Saying so plainly matters —
a test suite that implied otherwise would be the more dangerous artifact.

Cases are DATA. Adding one is three lines, which is the point: the set only stays useful if adding
to it is cheaper than arguing about it. When a real conversation goes wrong, it becomes case 21.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import openfactory.observability.query as query_mod
import openfactory.runtime.temporal.activities as activities_mod
from openfactory.memory import transcript
from openfactory.product.channel import conversation_key

CHANNEL = "C0PROD"


@dataclass
class Case:
    """One recall scenario.

    `turns` are (role, text) in order. `question` is asked afterwards. `recalls` are fragments that
    MUST reach the prompt; `forgets` are fragments that must NOT (leakage between conversations is
    as wrong as forgetting). `events` lets a case say WHERE each turn was said — bare in the
    channel or inside a thread — because that key is what broke in production once already.
    """

    name: str
    turns: list[tuple[str, str]]
    question: str
    recalls: list[str] = field(default_factory=list)
    forgets: list[str] = field(default_factory=list)
    thread_of: dict[int, str] = field(default_factory=dict)
    ask_in_thread: str = ""


CASES: list[Case] = [
    Case("o segundo de uma lista",
         [("person", "quais bancos a conciliação cobre?"),
          ("agent", "cobre Itaú e Bradesco, pelo requisito 12")],
         "e o segundo?", recalls=["Itaú e Bradesco", "requisito 12"]),

    Case("correção do próprio usuário",
         [("person", "o fechamento é mensal"),
          ("agent", "anotado: fechamento mensal"),
          ("person", "na verdade é quinzenal")],
         "então qual é a periodicidade?", recalls=["quinzenal", "mensal"]),

    Case("ela lembra da pergunta que ELA fez",
         [("agent", "sobre o Fechamento mensal: qual o prazo-limite?")],
         "dia 5", recalls=["prazo-limite", "Fechamento mensal"]),

    Case("pronome sem antecedente",
         [("person", "o relatório de comissões está saindo com valor errado"),
          ("agent", "registrei como defeito contra o requisito 9")],
         "isso já foi corrigido?", recalls=["comissões", "requisito 9"]),

    Case("decisão tomada há vários turnos",
         [("person", "podemos adiar a integração com o Primavera"),
          ("agent", "ok, tirei da fila"),
          ("person", "e o módulo fiscal?"),
          ("agent", "esse continua para esta quinzena")],
         "me lembra o que a gente adiou?", recalls=["Primavera", "tirei da fila"]),

    Case("número de requisito citado antes",
         [("agent", "isso está no requisito 47, ainda não aceito")],
         "e quando ele é aceito, o que muda?", recalls=["requisito 47"]),

    Case("quem disse o quê",
         [("person", "a Ana pediu o relatório consolidado"),
          ("agent", "entendi, vou tratar como pedido dela")],
         "de quem era esse pedido mesmo?", recalls=["Ana", "consolidado"]),

    Case("negativa anterior tem que sobreviver",
         [("person", "o sistema emite nota fiscal?"),
          ("agent", "não — não encontrei nenhum requisito que prometa isso")],
         "e se eu quisesse, dava?", recalls=["nota fiscal", "não encontrei"]),

    Case("uma pergunta que ficou sem resposta",
         [("agent", "faltou o critério de aceite do #412 — como saber que está pronto?"),
          ("person", "vou ver com o time")],
         "conseguiu ver aquilo?", recalls=["critério de aceite", "#412"]),

    Case("entrega anunciada e não confirmada",
         [("agent", "o que foi pedido no requisito 7 está pronto"),
          ("person", "vou testar amanhã")],
         "testei hoje", recalls=["requisito 7", "testar amanhã"]),

    Case("três turnos atrás, não o último",
         [("person", "o cliente é a Acme"),
          ("agent", "anotado"),
          ("person", "quantos usuários?"),
          ("agent", "não sei dizer — não está escrito em lugar nenhum"),
          ("person", "uns 40")],
         "de quem mesmo é esse produto?", recalls=["Acme"]),

    Case("resposta em thread vê a pergunta do canal",
         [("agent", "qual o prazo-limite do fechamento?")],
         "até o dia 5", recalls=["prazo-limite"], ask_in_thread="9999.1"),

    Case("thread separada não contamina",
         [("person", "pergunta sobre folha de pagamento")],
         "e sobre estoque?", recalls=[], forgets=[],
         thread_of={0: "OUTRO_THREAD"}),

    Case("acentuação sobrevive à ida e volta",
         [("person", "a conciliação não está batendo com a integração")],
         "isso ainda acontece?", recalls=["conciliação", "integração"]),

    Case("texto longo não é truncado no meio da palavra",
         [("person", "preciso que o relatório " + "detalhado " * 30 + "saia em PDF")],
         "e em Excel?", recalls=["PDF"]),

    Case("o mais recente sempre entra",
         [("person", f"turno antigo {i}") for i in range(30)]
         + [("person", "esta é a última coisa que eu disse")],
         "e agora?", recalls=["esta é a última coisa que eu disse"]),

    Case("defeito reportado, vocabulário do cliente",
         [("person", "a conciliação está duplicando lançamentos"),
          ("agent", "o problema que foi reportado aqui está corrigido")],
         "não, continua", recalls=["duplicando"]),

    Case("um fato de negócio dito em conversa",
         [("person", "anota que a firma usa Primavera como ERP"),
          ("agent", "Vou anotar assim — a firma usa Primavera como ERP")],
         "qual ERP mesmo?", recalls=["Primavera"]),

    Case("pedido de prioridade anterior",
         [("person", "prioriza o módulo fiscal antes de tudo"),
          ("agent", "coloquei o fiscal no topo da proposta")],
         "por que o fiscal está na frente?", recalls=["fiscal", "topo"]),

    Case("a agente se contradiz e o histórico prova",
         [("agent", "o requisito 3 já foi aceito"),
          ("person", "tem certeza?")],
         "você disse que o 3 estava aceito", recalls=["requisito 3", "aceito"]),
]


class _Sink:
    def __init__(self):
        self.rows: list = []

    def record(self, rec):
        self.rows.append(rec)


@pytest.fixture()
def store(monkeypatch):
    sink = _Sink()
    monkeypatch.setattr(activities_mod, "_metrics_sink", lambda *a, **k: sink)

    def _read(project, kind, *, limit=500, **kw):
        return [{"ticket": r.ticket, "role": r.role, "ts": r.ts, "extra": r.extra}
                for r in sink.rows if r.project == project and r.kind == kind][-limit:]

    monkeypatch.setattr(query_mod, "records_of_kind", _read)
    return sink


def _prompt_for(case: Case) -> str:
    """Everything the model would be given about the conversation, for this case's question."""
    for i, (role, text) in enumerate(case.turns):
        key = case.thread_of.get(i, conversation_key({"ts": f"{i}.0"}, CHANNEL))
        transcript.record("books", thread=key, role=role, text=text, channel=CHANNEL)

    thread = case.ask_in_thread or conversation_key({"ts": "99.0"}, CHANNEL)
    return transcript.render(
        transcript.recent("books", thread=thread, channel=CHANNEL), agent_name="Nina")


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_what_answers_the_question_reaches_the_model(case, store):
    """The retrieval half of memory. Not "was a row written" — whether the material that answers
    the question is in the text the agent receives."""
    prompt = _prompt_for(case)

    for fragment in case.recalls:
        assert fragment in prompt, (
            f"[{case.name}] '{fragment}' is what answers {case.question!r} and it is NOT in what "
            f"the model receives:\n---\n{prompt[:900]}\n---")
    for fragment in case.forgets:
        assert fragment not in prompt, f"[{case.name}] '{fragment}' leaked in: {prompt[:400]}"


def test_a_separate_thread_does_not_leak_into_this_one(store):
    """Held apart from the parametrised set because it asserts the negative: material from another
    exchange must NOT arrive. Recall that over-recalls is a different failure with the same
    symptom — an agent answering confidently about the wrong thing."""
    transcript.record("books", thread="THREAD_A", role="person", text="assunto folha")
    transcript.record("books", thread="THREAD_B", role="person", text="assunto estoque")

    only_a = transcript.render(transcript.recent("books", thread="THREAD_A"))

    assert "folha" in only_a and "estoque" not in only_a, only_a


def test_the_eval_set_is_big_enough_to_be_worth_having():
    """Twenty is the number the reference model names as catching most regressions. Below it, this
    file is decoration; the assertion is here so shrinking it is a decision rather than a drift."""
    assert len(CASES) >= 20, f"only {len(CASES)} recall cases"


def test_under_budget_pressure_the_RECENT_end_survives(store):
    """Shrinking the budget SHOULD drop old material — that is what a budget is for, and a case
    asserting otherwise would pin a bug. What must never invert is the direction: under pressure
    the newest turns survive and the oldest go, because the recent end is the half that carries
    the thread. Sabotaging the budget alone therefore does not fail the cases above; sabotaging
    the ORDER fails this one.
    """
    for i in range(40):
        transcript.record("books", thread="T_PRESSURE", role="person",
                          text=f"turno {i} " + "conteudo " * 30)

    turns = transcript.recent("books", thread="T_PRESSURE", budget=1200)

    assert turns, "the budget dropped everything"
    assert "turno 39" in turns[-1].text, f"the newest turn was dropped: {turns[-1].text[:40]}"
    assert "turno 0" not in " ".join(t.text for t in turns), "nothing was dropped — no budget"
