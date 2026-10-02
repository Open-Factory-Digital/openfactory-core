"""What the product role waits for from a person survives the process that asked (#452).

THE DEFECT, MEASURED ON `main` (7fa72bc) on the real SQLite store, with the worker's memory dropped
between the question and the answer:

- a card question held (ADR-0054 D4: "I need one thing before I can write this card: …"), then
  the answer: the role's whole turn ran again — the role's answer was asked, the card started
  over — because the question lived in `cards._OPEN`, a dictionary in the worker;
- a proposal that aged out, read so by a message before the restart, then a late "sim": an
  ordinary message, answered politely, because the notice it was owed lived in
  `staging._EXPIRED_TOMBSTONES`;
- a card refused with a "não" on another worker, and its correction staged there: this worker's
  own copy was believed over the store, and the person's "sim" FILED THE CARD THEY HAD REFUSED.

THE PROOF IS TWO PROCESSES, NOT TWO DICTIONARIES. The question is asked in this test's process
and answered in a fresh interpreter (`_in_a_fresh_process`): new modules, no cache, no object in
common — only the store in `tmp_path` and the journals the deployment mounts, as two workers of
one deployment share them. The doubles stand in only for the model (`_Role`); the store, the
engine, the staging, the confirmation and the card loop are the shipped ones.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.memory import messages
from openfactory.product import cards, staging, waiting
from openfactory.product.voice import card_needs, proposal_expired
from tests.the_chat_turn import chat_turn

ROOT = Path(__file__).resolve().parents[1]

ADMIN = "U1"
KEY = "C0PROD"
NAME = "books"
LANG = "pt-BR"

GESTURE = "pode criar um card novo e siga para a correção"
CORRECTION = "não, é na tela de configurações"
ASK = "Em qual altura de tela isso acontece?"
ANSWER = "acontece com 646 px de altura"
PLAIN = "Certo, entendi."

GOOD = {
    "title": "Página inicial: botão Criar e dica fora da vista em telas baixas",
    "objective": "O botão Criar e a dica continuam alcançáveis em telas de pouca altura.",
    "description": "Com a janela a cerca de 646 px de altura, a caixa de texto da página inicial "
                   "empurra a dica e o botão Criar para fora da área visível, e a página não "
                   "rola.",
    "done_when": ["Com 646 px de altura, o botão Criar e a dica ficam visíveis ou alcançáveis "
                  "por rolagem"],
    "out_of_scope": [], "related": [], "source_quote": "", "questions": [],
}
#: the card the correction asks for — another title, so the two proposals are two tokens
OTHER = {**GOOD, "title": "Configurações: botão Salvar fora da vista em telas baixas",
         "objective": "O botão Salvar das configurações continua alcançável em telas baixas.",
         "description": "Com a janela a cerca de 646 px de altura, a tela de configurações "
                        "empurra o botão Salvar para fora da área visível, e a página não rola."}


def _project() -> Project:
    return Project(name=NAME, repo_path="/t", language=LANG,
                   tracker=ProviderRef(kind="github", repo="a/b"),
                   forge=ProviderRef(kind="github", repo="a/b"),
                   product=ProductConfig(docs_repo="a/docs", channel_id=KEY,
                                         admins=[ADMIN], agent_name="Nina"))


def _verdict(level: int, ask: str = "") -> str:
    rubric = cards.load_rubric()
    return json.dumps({"scores": {c.id: level for c in rubric.criteria}, "evidence": {},
                       "critical": [], "findings": ["say at which height the page breaks"]
                       if level < 4 else [], "ask": ask})


class _Role:
    """The product role with its model calls scripted — and only those: `compose_card` runs the
    shipped card loop, and the yes reaches `file_ticket` through the shipped confirmation."""

    def __init__(self, *drafts: dict, blocks: int = 0):
        self.drafts = list(drafts)
        self.prompts: list[str] = []
        self.verdicts = [_verdict(2, ASK)] * blocks
        self.answered = 0
        self.composed: list[dict] = []
        self.filed: list[dict] = []

    def _draft(self, prompt: str):
        self.prompts.append(prompt)
        return self.drafts.pop(0) if self.drafts else None

    def _judge(self, prompt: str) -> str:
        return self.verdicts.pop(0) if self.verdicts else _verdict(5)

    def settle_acceptance(self, text):
        return None

    def close_decisions_answered(self, *, channel=""):
        return 0

    def confirmed(self, reply, *, proposal):
        return "neither"

    def context(self):
        return SimpleNamespace(available=True, reason="")

    def answer(self, question, *, context="", conversation="", **_):
        self.answered += 1
        card = question in (GESTURE, CORRECTION)
        return SimpleNamespace(ok=True, is_ticket=card,
                               ticket_title=(GOOD if question == GESTURE else OTHER)["title"],
                               is_defect=False, is_request=False, decisions=[], gesture="",
                               text="Abro o cartão." if card else PLAIN, violates=None)

    def compose_card(self, **kw):
        self.composed.append(kw)
        return cards.compose(draft=self._draft, judge=self._judge, rubric=cards.load_rubric(),
                             template=cards.load_template(kind=kw.get("kind", "ticket"),
                                                          language=kw.get("language")), **kw)

    def file_ticket(self, *, title, described, reported_by, source="", card=""):
        self.filed.append({"title": title, "card": card})
        return SimpleNamespace(ok=True, ref="#77", url="https://forge/x/77", detail="",
                               existed=False)


def _say(role: _Role, text: str) -> str:
    return str(chat_turn(_project(), text=text, user=ADMIN, thread=KEY, module=role))


@contextmanager
def _past_every_deadline():
    """This process's clock, moved past every deadline a wait was given — and back."""
    real = {module: module.time for module in (staging, cards, waiting)}
    later = time.time() + staging.PROPOSAL_TTL_SECONDS + 60
    clock = SimpleNamespace(time=lambda: later, monotonic=time.monotonic)
    try:
        for module in real:
            module.time = clock
        yield
    finally:
        for module, was in real.items():
            module.time = was


def _child(step: str, text: str = "", later: str = "") -> dict:
    """One turn of a worker that never saw this conversation — run in a FRESH interpreter by
    `_in_a_fresh_process`, never called in the test's own."""
    if later:
        with _past_every_deadline():
            return _child(step, text)
    if step == "waits":
        return {"waits": [{"kind": w.kind, "key": w.key, "text": w.text}
                          for w in waiting.in_conversation(_project(), KEY, ADMIN)]}
    role = _Role(*{"resume": [GOOD], "talk": [OTHER], "yes": [], "die": []}[step])
    if step == "die":
        # KILLED IN THE REDRAFT, the way a redeploy or the OOM killer ends a worker: no `finally`
        role.compose_card = lambda **kw: os.kill(os.getpid(), signal.SIGKILL)
    said = _say(role, text)
    _, staged = staging.find_waiting(KEY, KEY, project=_project(), person=ADMIN)
    return {"said": said, "answered": role.answered, "filed": role.filed,
            "composed": [{"request": kw["request"], "title": kw.get("title", ""),
                          "answer": kw["answered"].answer if kw.get("answered") else None}
                         for kw in role.composed],
            "prompts": role.prompts,
            "staged": {"title": staged.get("title"), "card": staged.get("card")}
            if staged else None}


_CHILD = ("import json, sys\n"
          "from tests.test_what_the_role_waits_for_survives_a_restart import _child\n"
          "print('\\n' + json.dumps(_child(*sys.argv[1:])))\n")


def _in_a_fresh_process(step: str, text: str = "", *, later: bool = False) -> dict:
    """`_child` in another interpreter, on the same store and the same journals — the environment
    this test set is the environment it inherits. `{}` for a step that kills its own process."""
    done = subprocess.run([sys.executable, "-c", _CHILD, step, text, "later" if later else ""],
                          cwd=ROOT, env=dict(os.environ), capture_output=True, text=True,
                          timeout=180)
    if step == "die":
        assert done.returncode == -signal.SIGKILL, (done.returncode, done.stderr[-4000:])
        return {}
    assert done.returncode == 0, done.stderr[-4000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    """The real SQLite store, in this test's own directory — the deployment's shared record."""
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    cards._OPEN.clear()
    yield
    cards._OPEN.clear()


# ── the held question ──────────────────────────────────────────────────────────────────────────

def test_a_question_asked_here_is_answered_in_a_fresh_process_by_one_redraft():
    """THE DEFECT: the answer started the role's whole turn again. In the process the answer
    reaches, it goes straight to one redraft of the card the question was held on."""
    asked = _say(_Role(GOOD, GOOD, blocks=2), GESTURE)
    assert card_needs(ask=ASK, language=LANG) in asked

    there = _in_a_fresh_process("resume", ANSWER)

    assert there["answered"] == 0, "the answer started a new turn of the role"
    [resumed] = there["composed"]
    assert resumed == {"request": GESTURE, "title": GOOD["title"], "answer": ANSWER}
    [redraft] = there["prompts"]
    assert ANSWER in redraft and GOOD["title"] in redraft, "the held draft did not travel"
    assert there["staged"]["title"] == GOOD["title"]
    assert there["staged"]["card"] in there["said"], "the person must read the card for the yes"


def test_a_question_taken_in_another_process_is_not_taken_again_from_this_ones_copy():
    """This process keeps its copy of the question; the person declined it on another worker, and
    the store says so — so the next message here is a conversation, never a redraft of a question
    already taken."""
    _say(_Role(GOOD, GOOD, blocks=2), GESTURE)
    assert len(cards._OPEN) == 1, "the asking process keeps its copy"
    there = _in_a_fresh_process("talk", "não")
    assert there["composed"] == [] and there["staged"] is None

    here = _Role(GOOD)
    _say(here, ANSWER)

    assert here.answered == 1 and here.composed == []


def test_a_worker_killed_in_the_redraft_leaves_the_question_for_the_turns_retry():
    """The redraft is minutes of model calls, and a worker killed in them has its turn run again
    on another (`TURN_RETRY`). The question is closed with the redraft in hand, so the retry still
    reads the answer as the answer."""
    _say(_Role(GOOD, GOOD, blocks=2), GESTURE)

    _in_a_fresh_process("die", ANSWER)
    retried = _in_a_fresh_process("resume", ANSWER)

    assert retried["answered"] == 0, "the retry read the answer as a new message"
    assert [c["answer"] for c in retried["composed"]] == [ANSWER]


def test_a_question_past_its_written_deadline_is_not_an_answer_in_any_process():
    """The deadline is on the record: a process whose clock is past it reads the message as a
    conversation, and closes the record as expired."""
    _say(_Role(GOOD, GOOD, blocks=2), GESTURE)

    there = _in_a_fresh_process("talk", ANSWER, later=True)

    assert there["answered"] == 1 and not any(c["answer"] for c in there["composed"])
    [(_, closed)] = [(m, c) for m, c in messages.held(NAME)
                     if m.token == waiting.question_token(staging.key_for(KEY, ADMIN))]
    assert closed is not None and closed.answer == cards.EXPIRED


def test_what_waits_is_listed_from_the_store_by_a_process_that_never_asked():
    """The Pending tab's reader (ADR-0055 D11): after a restart it must not say "nothing pending".
    A held question is listed, with what the person was asked; once answered, the card it became
    is listed in its place."""
    _say(_Role(GOOD, GOOD, blocks=2), GESTURE)

    before = _in_a_fresh_process("waits")["waits"]
    _in_a_fresh_process("resume", ANSWER)
    after = _in_a_fresh_process("waits")["waits"]

    assert before == [{"kind": waiting.QUESTION, "key": staging.key_for(KEY, ADMIN),
                       "text": ASK}]
    assert [w["kind"] for w in after] == [waiting.PROPOSAL]


# ── the staged proposal ────────────────────────────────────────────────────────────────────────

def test_a_proposal_staged_here_is_confirmed_by_a_yes_in_a_fresh_process():
    asked = _say(_Role(GOOD), GESTURE)
    staged = staging.pending_for(staging.key_for(KEY, ADMIN))
    assert staged["card"] in asked

    there = _in_a_fresh_process("yes", "sim")

    assert there["filed"] == [{"title": GOOD["title"], "card": staged["card"]}]


def test_a_proposal_answered_and_replaced_on_another_worker_is_not_believed_here():
    """THE SECOND WORKER: this process still holds the first proposal; another took its "não" and
    staged the correction. This process's "sim" confirms the correction — the proposal the person
    read last — and never answers it with "already handled"."""
    _say(_Role(GOOD), GESTURE)
    there = _in_a_fresh_process("talk", CORRECTION)
    assert there["staged"]["title"] == OTHER["title"]

    here = _Role()
    _say(here, "sim")

    assert here.filed == [{"title": OTHER["title"], "card": there["staged"]["card"]}]


def test_a_late_yes_hears_that_its_proposal_expired_in_a_fresh_process_once():
    """The expiry was found here, by a message before the restart; the late "sim" reaches a worker
    that never saw it, and is told — once: the next yes, anywhere, is a message like any other."""
    _say(_Role(GOOD), GESTURE)
    with _past_every_deadline():
        _say(_Role(), "oi, tudo certo?")

    told = _in_a_fresh_process("yes", "sim")
    again = _in_a_fresh_process("yes", "sim")

    assert told["said"] == proposal_expired(language=LANG) and told["answered"] == 0
    assert told["filed"] == []
    assert again["said"] == PLAIN and again["answered"] == 1


def test_a_proposal_that_ages_out_while_no_process_runs_is_refused_with_the_sentence():
    _say(_Role(GOOD), GESTURE)

    there = _in_a_fresh_process("yes", "sim", later=True)

    assert there["said"] == proposal_expired(language=LANG) and there["filed"] == []


def test_a_fresh_proposal_retires_the_notice_an_older_one_left():
    """A "não" to the new proposal is the person correcting it — never told that the old one
    expired."""
    _say(_Role(GOOD), GESTURE)
    with _past_every_deadline():
        _say(_Role(), "oi, tudo certo?")
    _say(_Role(GOOD), GESTURE)

    there = _in_a_fresh_process("talk", CORRECTION)

    assert there["said"] != proposal_expired(language=LANG)
    assert there["staged"]["title"] == OTHER["title"]


# ── the copy and the record, in one process ───────────────────────────────────────────────────

def _entry(title: str) -> dict:
    return {"kind": "ticket", "title": title, "card": f"## {title}", "channel": KEY}


def test_the_copy_is_the_proposal_while_the_store_says_it_is_open():
    """The same object, not a thawed twin: `consume` confirms by identity."""
    key = staging.key_for(KEY, ADMIN)
    staging.remember(key, _entry("a"), project=_project(), person=ADMIN)
    copy = staging._PENDING[key]

    assert staging.pending_for(key, project=_project()) is copy


def test_a_copy_the_store_says_was_answered_is_dropped():
    key = staging.key_for(KEY, ADMIN)
    staging.remember(key, _entry("a"), project=_project(), person=ADMIN)
    token = staging.proposal_token(key, staging._PENDING[key])
    messages.answer(NAME, token=token, answer="approve", by="elsewhere")

    assert staging.pending_for(key, project=_project()) is None
    assert key not in staging._PENDING


def test_a_copy_whose_own_row_did_not_land_is_still_the_proposal(monkeypatch):
    """The mirror is best-effort: a staging whose row was not written is newer than the store's
    latest, and is what the person was shown."""
    key = staging.key_for(KEY, ADMIN)
    staging.remember(key, _entry("a"), project=_project(), person=ADMIN)
    monkeypatch.setattr(messages, "ask", lambda *a, **k: False)
    time.sleep(0.002)
    staging.remember(key, _entry("b"), project=_project(), person=ADMIN)

    assert staging.pending_for(key, project=_project())["title"] == "b"


def test_a_hold_is_open_until_a_later_row_closes_it_and_open_again_when_held_again():
    messages.hold(NAME, "q1", token="t", expires="")
    [(first, closed)] = messages.held(NAME)
    assert (first.text, closed) == ("q1", None)

    messages.release(NAME, token="t", answer="taken")
    [(_, closed)] = messages.held(NAME)
    assert closed is not None and closed.answer == "taken"

    messages.hold(NAME, "q2", token="t", expires="")
    [(again, closed)] = messages.held(NAME)
    assert (again.text, closed) == ("q2", None)


def test_a_hold_is_not_a_question_with_buttons():
    """`pending` is what every surface draws Approve / Reject for."""
    messages.hold(NAME, ASK, token=waiting.question_token(KEY))

    assert messages.pending(NAME) == []
