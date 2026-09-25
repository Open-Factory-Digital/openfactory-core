"""The speaker and the reply — #266 slice 4 (ADR-0051 D1's `speaker` and `in_reply_to`, D11).

A GROUP ROOM IS SEVERAL PEOPLE, AND THE ROLE ANSWERED IT AS ONE. Until this slice the product role
did not know who was speaking; one proposal was staged per conversation and the last one won, so a
second person's request displaced the first person's draft; any admin's "sim" confirmed whatever
was staged; any message from anyone closed every open decision of the project; and nothing kept
which reply answered which message once it was recorded. Each test below is one of those, driven
through the turn engine the way a transport drives it (the characterisation suite's harness,
`test_the_conversation_is_pinned.py`), and each fails on the code before this slice:

  - in a room, a second request no longer displaces the first person's draft, and each person
    confirms their own;
  - another admin's "yes" does not confirm someone else's draft — typed or clicked — unless the
    product sets `accept_on_behalf`;
  - one person's message does not close another person's decision;
  - `in_reply_to` survives into the transcript;
  - a learned fact is used in another conversation without a name, and the card sweep's "already
    noted" names nobody;
  - the speaker is a person with a role in the product, and the role's prompt says which.

NO NAME CROSSES A CONVERSATION (ADR-0051 D5, D9), and several tests read for one: the staging key
and the token carry a digest of the person, the decision loop a digest of whom it was asked of,
the refusal of somebody else's yes nobody's name.

#266 SLICE 6 RE-PINNED ONE VALUE: who asked for a proposal (`asked_by`) and the admins named under
one are the person's id as the platform knows it, no longer wrapped in a chat vendor's mention
syntax. The rows that READ an old entry still carrying that syntax are kept as they were — a row
staged before the slice is read the same way.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import openfactory.memory.store as loop_store
from openfactory.contracts import AgentRunResult
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.memory import messages, transcript
from openfactory.memory.ledger import DECISION, fold, waiting
from openfactory.memory.transcript import TRANSCRIPT_KIND
from openfactory.product import engine, followup, speaker, staging, voice
from openfactory.product.config import ProductLink
from openfactory.product.confirm import _is_requester, answer_staged, not_theirs
from openfactory.product.domain import LEARNED, Domain, Fact, glossary_index
from openfactory.product.facts import render_decisions
from openfactory.product.key import product_key
from openfactory.product.loader import ProductContext
from openfactory.product.module import ProductModule
from openfactory.product.role import ProductAnswer, ProductRole, RequirementDraft
from tests.test_the_conversation_is_pinned import ASKS, PLAIN, _Conversation, _Module, _Table
from tests.the_sink_door import SINK_DOOR

ROOM = "C0PROD"
ANA, BIA, CAIO, EDU = "U0ANA", "U0BIA", "U0CAIO", "U0EDU"
LANG, AGENT, PROJECT = "pt-BR", "Nina", "books"

PDF = "preciso exportar o extrato em PDF"
CSV = "preciso importar o extrato em CSV"


@pytest.fixture()
def table(monkeypatch) -> _Table:
    """The characterisation suite's telemetry table: the transcript and the durable staging mirror,
    in memory, behind the production code's own write and read."""
    t = _Table()
    monkeypatch.setattr(SINK_DOOR, lambda *a, **k: t)
    monkeypatch.setattr("openfactory.observability.query.records_of_kind", t.of_kind)
    return t


@pytest.fixture()
def ledger(monkeypatch) -> list:
    """The loop ledger as a list, append-only like the real one."""
    rows: list = []
    monkeypatch.setattr(loop_store, "read", lambda project: list(rows))
    monkeypatch.setattr(loop_store, "write", lambda project, loops: rows.extend(loops))
    return rows


def _project(*, accept_on_behalf: bool = False, engineers: tuple = ()) -> Project:
    """A room with two admins, a client and an engineer — the product's own default, on purpose:
    the first yes is the requester's unless `accept_on_behalf` says otherwise."""
    return Project(name=PROJECT, repo_path="/t", language=LANG, channel_id="C0OPS",
                   product=ProductConfig(docs_repo="a/b", channel_id=ROOM, admins=[ANA, BIA],
                                         engineers=list(engineers), agent_name=AGENT,
                                         accept_on_behalf=accept_on_behalf))


def _drafted(title: str) -> ProductAnswer:
    return ProductAnswer(ok=True, draft=RequirementDraft(
        title=title, must_be_true=[f"{title.lower()} funciona"]))


class _Room(_Module):
    """Two different requests, two different drafts — the harness's module, drafting by what was
    asked rather than one fixed draft, and remembering who each answer was given to."""

    DRAFTS = {"PDF": _drafted("Exportar em PDF"), "CSV": _drafted("Importar em CSV")}

    def __init__(self, project, **kw) -> None:
        asked = ProductAnswer(ok=True, text="Hoje não fazemos isso.", is_request=True)
        super().__init__(project, replies={"PDF": asked, "CSV": asked, "backlog": ASKS}, **kw)
        self.speakers: list = []

    def draft(self, request, *, asked_by=""):
        self._record("draft", request=request, asked_by=asked_by)
        return next(d for word, d in self.DRAFTS.items() if word in request)

    def answer(self, question, *, speaker=None, **kw):
        self.speakers.append(speaker)
        return super().answer(question, **kw)


def _proposed(module) -> list[tuple[str, str, str]]:
    return [(p["answer"].draft.title, p["actor"], p["asked_by"]) for p in module.asked("propose")]


def _staged(who: str, where: str = ROOM, **kw):
    return staging.pending_for(staging.key_for(where, who), **kw)


# ── 1. a second request no longer displaces the first person's draft ────────────────────────────

def test_in_a_room_a_second_request_keeps_the_first_person_s_draft_and_each_confirms_their_own(
        table, ledger):
    """Ana asks, then Bia asks, in the same room. Bia's draft is staged beside Ana's — no "I set
    aside what was waiting" — and each "sim" performs its own speaker's draft, in their name.
    Before this slice the second staging displaced the first, and Bia's "sim" was the only one
    that could ever write."""
    project = _project()
    module = _Room(project)
    talk = _Conversation(project, module)

    talk.say(PDF, user=ANA)
    second = talk.say(CSV, user=BIA)

    assert "Deixei de lado" not in second, "the second request displaced the first person's draft"
    assert _staged(ANA)["answer"].draft.title == "Exportar em PDF"
    assert _staged(BIA)["answer"].draft.title == "Importar em CSV"
    assert len(messages.pending(PROJECT)) == 2, "the panel lost one of the two proposals"

    # Ana first: hers is the OLDER of the two, so her "sim" finds her own before the newest
    talk.say("sim", user=ANA)
    talk.say("sim", user=BIA)

    assert _proposed(module) == [("Exportar em PDF", ANA, ANA),
                                 ("Importar em CSV", BIA, BIA)]
    assert _staged(ANA) is None and _staged(BIA) is None


def test_a_yes_finds_the_speaker_s_own_before_one_staged_under_the_conversation_alone(table,
                                                                                    ledger):
    """A proposal staged by a caller that named nobody (or before this slice) waits under the
    conversation's own name, and anybody there may still find it; the speaker's OWN is looked for
    first, so Ana's "sim" confirms Ana's draft, not the older anonymous one."""
    project = _project()
    module = _Room(project)
    staging.remember(ROOM, {"kind": "queue", "channel": ROOM, "numbers": ["12"]}, lang=LANG,
                     project=project)
    talk = _Conversation(project, module)
    talk.say(PDF, user=ANA)

    talk.say("sim", user=ANA)

    assert _proposed(module) == [("Exportar em PDF", ANA, ANA)]
    assert not module.asked("promote")


def test_a_yes_at_room_level_finds_the_speaker_s_own_in_a_thread_before_a_newer_one(table,
                                                                                   ledger):
    """Ana asked inside a thread; Bia asked at room level afterwards. Ana's bare "sim" in the room
    means Ana's proposal — her own is taken before anybody else's newer one."""
    project = _project()
    module = _Room(project)
    talk = _Conversation(project, module)
    talk.say(PDF, user=ANA, thread="1726000000.000100", channel=ROOM)
    talk.say(CSV, user=BIA)

    talk.say("sim", user=ANA)

    assert _proposed(module) == [("Exportar em PDF", ANA, ANA)]


def test_a_start_proposed_to_one_admin_is_that_admin_s_to_confirm(table, ledger):
    """The queue — the yes that spends money — carries no `asked_by` of its own; it is bound to
    whoever asked for the start all the same, because every turn records who staged it."""
    project = _project()
    module = _Room(project)
    talk = _Conversation(project, module)
    talk.say("o que entra agora?", user=ANA)

    refused = talk.say("sim", user=BIA)

    assert refused == voice.only_the_requester_confirms(language=LANG)
    assert not module.asked("promote")

    talk.say("sim", user=ANA)

    assert module.asked("promote") == [{"numbers": ["12"], "actor": ANA}]


def test_a_person_s_second_request_still_replaces_their_OWN_first_and_says_so(table, ledger):
    """The key is the person's, so what a staging displaces is only ever that same person's own
    earlier proposal — and that is still admitted in a sentence, while Bia's stays where it was."""
    project = _project()
    module = _Room(project)
    talk = _Conversation(project, module)
    talk.say(CSV, user=BIA)
    talk.say(PDF, user=ANA)

    again = talk.say("anota que o fechamento roda sempre no quinto dia útil", user=ANA)

    assert again.startswith("(Deixei de lado"), again
    assert _staged(ANA)["kind"] == "fact"
    assert _staged(BIA)["answer"].draft.title == "Importar em CSV"


# ── 2. another admin's yes does not confirm someone else's draft ────────────────────────────────

def test_another_admin_s_yes_does_not_confirm_a_draft_somebody_else_asked_for(table, ledger):
    """Bia is an admin and did not ask. Her "sim" is refused out loud — naming nobody — and the
    draft stays staged for Ana, whose own "sim" then writes it."""
    project = _project()
    module = _Room(project)
    talk = _Conversation(project, module)
    talk.say(PDF, user=ANA)

    refused = talk.say("sim", user=BIA)

    assert refused == voice.only_the_requester_confirms(language=LANG)
    assert ANA not in refused and "Ana" not in refused
    assert not module.asked("propose")
    assert _staged(ANA) is not None, "a refused yes consumed the draft"

    talk.say("sim", user=ANA)

    assert _proposed(module) == [("Exportar em PDF", ANA, ANA)]


def test_with_accept_on_behalf_an_admin_confirms_for_the_requester(table, ledger):
    """The one way past the requester binding is the product's configuration: with
    `accept_on_behalf` set, Bia's yes performs Ana's draft — in Bia's name, as Ana's request."""
    project = _project(accept_on_behalf=True)
    module = _Room(project)
    talk = _Conversation(project, module)
    talk.say(PDF, user=ANA)

    talk.say("sim", user=BIA)

    assert _proposed(module) == [("Exportar em PDF", BIA, ANA)]


def test_accept_on_behalf_never_lets_somebody_off_the_admin_list_confirm(table, ledger):
    """`accept_on_behalf` widens whose proposal an ADMIN may confirm, and nothing else: a client's
    yes on somebody else's draft is refused by the admin list, as it always was."""
    project = _project(accept_on_behalf=True)
    module = _Room(project)
    talk = _Conversation(project, module)
    talk.say(PDF, user=ANA)

    refused = talk.say("sim", user=CAIO)

    assert refused == voice.cannot_write(has_approvers=True, language=LANG)
    assert not module.asked("propose") and _staged(ANA) is not None


def test_another_admin_s_yes_is_refused_from_a_process_that_never_staged_the_draft(table,
                                                                                  ledger):
    """The worker that staged Ana's draft restarted (or it was staged by another process): the
    durable store still holds it, and Bia's "sim" is still found against it and refused — never
    answered as small talk while Ana's draft waits."""
    project = _project()
    module = _Room(project)
    talk = _Conversation(project, module)
    talk.say(PDF, user=ANA)
    staging._PENDING.clear()  # ← the process boundary

    refused = talk.say("sim", user=BIA)

    assert refused == voice.only_the_requester_confirms(language=LANG)
    assert not module.asked("propose")

    talk.say("sim", user=ANA)

    assert _proposed(module) == [("Exportar em PDF", ANA, ANA)]


def test_the_admins_are_not_told_to_confirm_what_their_yes_cannot(table, ledger):
    """Under a client's proposal the role used to name the admins — "the record needs your
    confirmation". With the first yes bound to the requester that sentence would send them to a
    refusal, so it is said only where the product lets them accept on the requester's behalf."""
    fact = "anota que o fechamento roda sempre no quinto dia útil"

    bound = _Conversation(_project(), _Room(_project())).say(fact, user=CAIO)
    on_behalf = _Conversation(_project(accept_on_behalf=True),
                              _Room(_project(accept_on_behalf=True))).say(fact, user=CAIO)

    assert ANA not in bound and "precisa da sua confirmação" not in bound
    assert ANA in on_behalf and "precisa da sua confirmação" in on_behalf


def test_the_intake_case_that_moves_is_the_requester_s_never_another_person_s(table, ledger,
                                                                             monkeypatch):
    """Each person's intake is a case of their own in the room (#33 hole 7). When Bia confirms her
    draft, HER case is confirmed and filed — not Ana's, whose draft was proposed after hers and is
    still waiting. The case used to be picked as the latest one in the conversation."""
    from openfactory.product import case as intake

    ticks = iter(range(1, 10**6))
    monkeypatch.setattr(intake, "time", SimpleNamespace(time=lambda: 1_700_000_000 + next(ticks)))
    project = _project()
    talk = _Conversation(project, _Room(project))
    talk.say(CSV, user=BIA)
    talk.say(PDF, user=ANA)

    talk.say("sim", user=BIA)

    assert intake.current(project, ROOM, ANA).state == intake.PROPOSED
    assert intake.current(project, ROOM, BIA) is None, "Bia's case is still open"
    [filed] = [c for c in intake._CASES[PROJECT].values() if c.state == intake.FILED]
    assert filed.opened_by == BIA


def test_a_click_by_another_admin_is_refused_and_named_for_the_http_caller(table, ledger):
    """The token route (the panel's buttons, `product_answer`) is bound the same way, and NAMES
    the refusal `unauthorized` — the panel's 403 — rather than recording a decision."""
    project = _project()
    module = _Room(project)
    _Conversation(project, module).say(PDF, user=ANA)
    token = staging.proposal_token(staging.key_for(ROOM, ANA), _staged(ANA))

    code, sentence = answer_staged(project, token=token, approved=True, user=BIA, module=module)

    assert (code, sentence) == ("unauthorized",
                                voice.only_the_requester_confirms(language=LANG))
    assert not module.asked("propose") and _staged(ANA) is not None

    code, _ = answer_staged(project, token=token, approved=True, user=ANA, module=module)

    assert code == "done"
    assert _proposed(module) == [("Exportar em PDF", ANA, ANA)]
    # the click is a turn of the proposal's CONVERSATION, never of the key it waited under
    assert ("person", "sim", ANA) in table.turns(ROOM)


def test_the_requester_is_compared_EXACTLY_never_found_inside_a_mention():
    """`_is_requester` matched the id INSIDE the mention, so `U0ANA` was the requester of what
    `<@U0ANABELA>` asked for. It decides whose yes confirms now, so it compares whole ids."""
    project = _project()
    theirs = {"kind": "draft", "asked_by": "<@U0ANABELA>"}

    assert not _is_requester(theirs, ANA)
    assert not_theirs(project, theirs, ANA) == voice.only_the_requester_confirms(language=LANG)
    assert _is_requester({"kind": "draft", "asked_by": f"<@{ANA}>"}, ANA)
    assert _is_requester({"kind": "draft", "requester": ANA, "asked_by": "<@x>"}, ANA)


def test_a_proposal_nobody_is_recorded_as_asking_for_has_nobody_to_defer_to():
    """A row staged before this slice, or by a caller that named nobody, carries no requester:
    the admin list alone decides it, which is the reading the second yes gives the same case."""
    assert not_theirs(_project(), {"kind": "queue", "numbers": ["12"]}, BIA) == ""


# ── 3. one person's message does not close another person's decision ────────────────────────────

def test_one_person_s_message_does_not_close_another_person_s_decision(table, ledger):
    """The role asks Ana to decide something in the room. Bia's message in the room closes
    nothing, nor does Ana's in a conversation of her own; Ana's in the room closes it."""
    project = _project()
    module = _Room(project)
    talk = _Conversation(project, module)
    talk.say("organiza o backlog", user=ANA)

    def asked() -> list[str]:
        return [x.context["asked"] for x in waiting(fold(ledger), owner=followup.OWNER)
                if x.kind == DECISION]

    assert asked() == ["fechar ou não os cards em Review"]

    talk.say("bom dia", user=BIA)
    talk.say("bom dia", user=ANA, thread="person:ana", channel="")

    assert asked() == ["fechar ou não os cards em Review"], "somebody else's message closed it"

    talk.say("pode fechar os de março", user=ANA)

    assert asked() == []
    [closed] = [x for x in fold(ledger) if x.kind == DECISION]
    assert closed.outcome == "answered"


def test_the_same_decision_asked_of_two_people_is_two_loops_each_closed_by_its_own(table, ledger):
    """Asked of Ana and of Bia, the same label is two decisions: Bia's answer closes hers and
    leaves Ana's open — a close keyed by the ledger's `(kind, subject, about)` alone would have
    answered both."""
    project = _project()
    module = _Room(project)
    talk = _Conversation(project, module)
    talk.say("organiza o backlog", user=ANA)
    talk.say("organiza o backlog", user=BIA)

    assert len([x for x in waiting(fold(ledger), owner=followup.OWNER) if x.kind == DECISION]) == 2

    talk.say("pode fechar", user=BIA)

    still = [x for x in waiting(fold(ledger), owner=followup.OWNER) if x.kind == DECISION]
    assert len(still) == 1
    assert still[0].context["asked_of"] == speaker.sealed(ANA)


def test_a_decision_records_whom_it_was_asked_of_as_a_digest_and_the_register_names_nobody(
        table, ledger):
    """The ledger is read into every conversation's prompt — the decisions register, "possibly
    already asked" — so whom a decision was asked of is kept as something to compare, never a
    name, and the sweep's chase (which reads `person`) is given nobody to name."""
    project = _project()
    _Conversation(project, _Room(project)).say("organiza o backlog", user=ANA)

    [loop] = [x for x in fold(ledger) if x.kind == DECISION]
    assert ANA not in str(loop.context) and "person" not in loop.context
    assert loop.context["asked_of"] == speaker.sealed(ANA)
    assert ANA not in render_decisions(ledger)


def test_a_decision_opened_before_this_slice_closes_on_a_message_in_its_own_room_only(table,
                                                                                       ledger):
    """A loop that records nobody cannot be scoped to a person; the narrowest the old rows allow is
    their room — a message elsewhere no longer answers it."""
    project = _project()
    module = _Room(project)
    module.record_decisions(["qual banco entra primeiro"], channel="C0ELSEWHERE")
    talk = _Conversation(project, module)

    talk.say("bom dia", user=BIA)

    assert [x.kind for x in waiting(fold(ledger), owner=followup.OWNER)] == [DECISION]

    talk.say("bom dia", user=BIA, thread="C0ELSEWHERE", channel="C0ELSEWHERE")

    assert not waiting(fold(ledger), owner=followup.OWNER)


# ── 4. in_reply_to survives into the transcript ─────────────────────────────────────────────────

def test_in_reply_to_survives_into_the_transcript(table, ledger):
    """The person's turn is recorded under its own id and what it replied to; the role's turn is
    recorded as the reply to it — and both come back out of the transcript's reader."""
    project = _project()
    module = _Room(project)

    replies = engine.turn(project, engine.Message(
        id="m-2", project=PROJECT, conversation=ROOM, room=ROOM, speaker=ANA,
        text="o extrato conciliado pode ser editado?", in_reply_to="m-1"), module=module)

    assert [r.in_reply_to for r in replies] == ["m-2"] * len(replies)
    rows = [r for r in table.of_kind(product_key(project), TRANSCRIPT_KIND)
            if r["ticket"] == ROOM]
    assert [(r["role"], r["extra"].get("id", ""), r["extra"].get("in_reply_to", ""))
            for r in rows] == [("person", "m-2", "m-1"), ("agent", "", "m-2")]
    turns = transcript.recent(project, thread=ROOM)
    assert [(t.role, t.id, t.in_reply_to) for t in turns] == [
        ("person", "m-2", "m-1"), ("agent", "", "m-2")]
    assert turns[1].text == PLAIN.text


# ── 5. no name crosses a conversation ───────────────────────────────────────────────────────────

class _Harness:
    """The model, recording every prompt it is handed."""

    name = "recorder"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        return AgentRunResult(ok=True, summary="O fechamento roda no quinto dia útil.")


def _ask(role: ProductRole, **kw) -> str:
    from openfactory.adapters.sandbox.base import Workspace

    role.answer(sandbox=SimpleNamespace(run=lambda **_k: (0, "")),
                workspace=Workspace(path="/tmp", branch="m", base_branch="m"),
                question="quando roda o fechamento?", **kw)
    return role.agent.prompts[-1]


LEARNED_FROM_ANA = Fact(term="fechamento", body="roda sempre no quinto dia útil",
                        status=LEARNED, source=f"<@{ANA}>", where="person:ana",
                        learned_on="2026-09-01")


def test_a_learned_fact_is_used_in_another_conversation_without_a_name(monkeypatch):
    """Ana told the role a fact in her own conversation; Bia asks about it in the room. The
    glossary the prompt carries holds the fact and its status — never who said it — and the
    instruction that said "say who told you" now says never to."""
    monkeypatch.setattr(ProductRole, "_meter", lambda *a, **k: None)
    role = ProductRole(_Harness(), domain=Domain(facts=[LEARNED_FROM_ANA]), language=LANG)

    prompt = _ask(role, speaker=speaker.person(_project(), BIA))

    assert "fechamento" in prompt and LEARNED in prompt
    assert ANA not in prompt, "a name crossed into another conversation's prompt"
    assert "NEVER say who told you" in prompt
    assert "say who told you when you use one" not in prompt
    assert "fonte" not in glossary_index(Domain(facts=[LEARNED_FROM_ANA]))


def test_the_card_sweep_s_already_noted_names_nobody():
    """A person answered, on a card, something the context already holds: the sentence posted
    back on the card says what is written, never who told it."""
    project = _project()
    module = ProductModule(project, context=ProductContext(
        link=ProductLink(active=True, docs_repo="a/b"),
        domain=Domain(facts=[LEARNED_FROM_ANA])))

    result = module.record_answer(about="fechamento", question="quando roda?", answer="dia 5",
                                  said_by="edu", where="card #12")

    assert result.existed and not result.ok
    assert "quinto dia útil" in result.detail
    assert ANA not in result.detail, result.detail


def test_the_staging_key_and_the_token_carry_no_name(table, ledger):
    """The token travels — onto a button, into the panel's pending list, into the write log — and
    it holds a digest of the person, never the person."""
    project = _project()
    _Conversation(project, _Room(project)).say(PDF, user=ANA)

    [row] = messages.pending(PROJECT)

    assert ANA not in row.token and row.token.startswith(f"{ROOM}~")
    assert row.channel == ROOM, "the panel's row names a key where it named the conversation"


# ── 6. the speaker is a person with a role in the product ───────────────────────────────────────

@pytest.mark.parametrize(("who", "role", "approver"), [
    (CAIO, speaker.CLIENT, False),
    (ANA, speaker.ADMIN, True),
    (EDU, speaker.ENGINEER, False),
    ("", speaker.CLIENT, False),
], ids=["client-by-default", "admin", "engineer", "nobody"])
def test_the_speaker_s_role_is_read_from_the_product_s_configuration(who, role, approver):
    person = speaker.person(_project(engineers=(EDU,)), who)

    assert (person.id, person.role, person.approver) == (who, role, approver)


def test_an_engineer_on_the_admin_list_is_an_engineer_whose_yes_records():
    person = speaker.person(_project(engineers=(ANA,)), ANA)

    assert (person.role, person.approver) == (speaker.ENGINEER, True)


def test_the_engine_hands_the_answer_who_is_speaking_and_in_which_role(table, ledger):
    project = _project(engineers=(EDU,))
    module = _Room(project)
    talk = _Conversation(project, module)

    for who in (CAIO, ANA, EDU):
        talk.say("o extrato conciliado pode ser editado?", user=who)

    assert [(p.id, p.role) for p in module.speakers] == [
        (CAIO, speaker.CLIENT), (ANA, speaker.ADMIN), (EDU, speaker.ENGINEER)]


def test_the_role_s_prompt_says_who_is_speaking_and_in_which_role(monkeypatch):
    monkeypatch.setattr(ProductRole, "_meter", lambda *a, **k: None)
    role = ProductRole(_Harness(), language=LANG)

    as_client = _ask(role, speaker=speaker.person(_project(), CAIO))
    as_engineer = _ask(role, speaker=speaker.person(_project(engineers=(EDU,)), EDU))
    as_nobody = _ask(role)

    assert f"## Who is speaking\n{CAIO} — a client of this product" in as_client
    assert "does not record anything here" in as_client
    assert f"{EDU} — an engineer who builds this product" in as_engineer
    assert "## Who is speaking" not in as_nobody
    assert as_client.index("## Who is speaking") < as_client.index("## Question")


def test_a_speaker_the_registry_cannot_answer_for_is_a_client(monkeypatch):
    """An unreadable allowlist makes a client — the role with the fewest assumptions — and never
    costs the turn."""
    monkeypatch.setattr("openfactory.product.module.may_act",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))

    assert speaker.person(_project(), ANA) == speaker.Person(id=ANA, role=speaker.CLIENT)


def test_the_module_hands_the_speaker_to_the_role(monkeypatch):
    """`ProductModule.answer` carries the speaker to the role's prompt."""
    seen: list = []

    class _Role:
        def answer(self, **kw):
            seen.append(kw.get("speaker"))
            return ProductAnswer(ok=True, text="ok")

    project = _project()
    module = ProductModule(project, context=ProductContext(
        link=ProductLink(active=True, docs_repo="a/b")))
    monkeypatch.setattr(module, "_workspace", lambda: (None, None))
    monkeypatch.setattr(module, "_role", lambda **_kw: _Role())
    monkeypatch.setattr(module, "already_asked", lambda _q: "")
    ana = speaker.person(project, ANA)

    module.answer("quando roda o fechamento?", speaker=ana)

    assert seen == [ana]
