"""The product role talks to a CLIENT, not to an operator.

Every other agent in this factory speaks to engineers, so "say it in Slack" has always meant "say
it to someone technical". Here that assumption is wrong in a way that quietly destroys the role's
value: a client told to "review the PR on the `req/0012` branch" learns this thing is not for them.

So every client-facing string this codebase can generate is asserted jargon-free. Not a style
preference — jargon leaks back one helpful sentence at a time, and nothing else catches it.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product.module import unauthorized_message
from openfactory.product.voice import (
    AUDIENCE_RULES,
    announcement,
    cannot_write,
    confirmation_request,
    jargon_in,
    unavailable,
    written_up,
)

CLIENT_TEXTS = {
    "announcement": announcement(product="Acme Books", areas=["reconciliation"]),
    "announcement-no-area": announcement(product="Acme Books"),
    "confirmation": confirmation_request(
        title="Editable reconciled statements",
        must_be_true=["an administrator can correct a reconciled statement"],
        conflicts=["requirement 7: a reconciled statement can't be changed"]),
    "confirmation-clean": confirmation_request(title="t", must_be_true=["x"]),
    "written-up": written_up(title="Editable statements", url="https://example/x", number=12),
    "cannot-write-none": cannot_write(has_approvers=False),
    "cannot-write-some": cannot_write(has_approvers=True),
    "unavailable": unavailable(reason_for_team="`.openfactory/product.yaml` is missing"),
}


@pytest.mark.parametrize("name", sorted(CLIENT_TEXTS))
def test_no_client_facing_message_uses_jargon(name):
    assert jargon_in(CLIENT_TEXTS[name]) == [], CLIENT_TEXTS[name]


def test_the_refusal_a_client_sees_never_names_a_configuration_file():
    """Useless to them, and slightly insulting to someone who was never meant to edit one."""
    for admins in ([], ["U0ADMIN"]):
        msg = unauthorized_message(Project(name="c", repo_path="/t",
                                           product=ProductConfig(docs_repo="a/b",
                                                                 admins=admins)))
        assert jargon_in(msg) == []
        assert "slack_admins" not in msg and ".yaml" not in msg


def test_the_jargon_detector_actually_catches_things():
    """A guard nobody can fail is not a guard."""
    assert "pull request" in jargon_in("I opened a pull request for you to review")
    assert "branch" in jargon_in("it's on the req/0012 branch")
    assert jargon_in("Once it's approved it becomes part of what we promise") == []


def test_requirement_numbers_survive_because_they_are_shared_vocabulary():
    """Stripping them would make the role unable to point at anything — the opposite of the goal."""
    text = confirmation_request(title="t", must_be_true=["x"],
                                conflicts=["requirement 7: statements can't be changed"])
    assert "requirement 7" in text and jargon_in(text) == []


# ── the confirmation IS the provenance ──────────────────────────────────────────────────────────

CONFIRM_MARKER = {"pt-BR": ("Entendi certo", "sim"), "en": ("Have I got it right", "yes")}
CONFLICT_MARKER = {"pt-BR": "mudança de ideia", "en": "change of mind"}
NOT_BUILDING = {"pt-BR": "Nada está sendo construído ainda", "en": "Nothing is being built yet"}
GUESSING = {"pt-BR": "chute", "en": "guesswork"}


@pytest.mark.parametrize("lang", ["pt-BR", "en"])
def test_the_client_is_asked_to_confirm_content_not_to_review_an_artefact(lang):
    """Two approvals of different things: the client approves the CONTENT, the team approves the
    CONSEQUENCE. A client asked to review a pull request has been handed the wrong job."""
    text = confirmation_request(title="Editable statements",
                                must_be_true=["an administrator can correct one"], language=lang)
    question, yes = CONFIRM_MARKER[lang]
    assert question in text and yes in text.lower()
    assert jargon_in(text) == []


@pytest.mark.parametrize("lang", ["pt-BR", "en"])
def test_a_conflict_is_put_BEFORE_the_confirmation_is_asked_for(lang):
    """Confirming something that reverses an earlier decision without being told is how a product
    contradicts itself with everyone's signature on it."""
    text = confirmation_request(title="t", must_be_true=["x"],
                                conflicts=["requirement 7 says the opposite"], language=lang)
    question, _ = CONFIRM_MARKER[lang]
    assert text.index("requirement 7") < text.index(question)
    assert CONFLICT_MARKER[lang] in text


@pytest.mark.parametrize("lang", ["pt-BR", "en"])
def test_after_writing_up_the_client_is_told_nothing_is_being_built_yet(lang):
    """The expectation most likely to go wrong: "it's written down" reads as "it's happening".

    THE URL ASSERTION WAS INVERTED, and it took the owner asking to see it. This line used to
    require the pull-request link to be IN the message — "a link, where a path would have gone" —
    treating a code-forge URL as the acceptable form of a file path. It is not: a link to a diff is
    delivery machinery (ADR-0026), and the person reading it runs an accounting firm. What they can
    judge is the sentence, and they already approved it in their own words before it was written.
    The URL is still returned on the `WriteResult`, where the team and the log can use it.
    """
    text = written_up(title="t", url="https://example/x", number=3, language=lang)
    assert NOT_BUILDING[lang] in text
    assert "https://example/x" not in text, "a code-forge link reached the client"
    assert "http" not in text, "a link of any kind reached the client"


@pytest.mark.parametrize("lang", ["pt-BR", "en"])
def test_unavailability_admits_it_would_be_guessing(lang):
    """Better than a confident answer from a corpus it cannot see — and the diagnosis stays with
    the team, who are the only ones who can act on it."""
    text = unavailable(reason_for_team="the documentation repo could not be checked out",
                       language=lang)
    assert GUESSING[lang] in text
    assert "checked out" not in text


# ── language ────────────────────────────────────────────────────────────────────────────────────

def test_the_default_language_is_the_projects_not_the_models():
    """Left to itself a model answers in whatever language it feels like, and a proactive message
    has no incoming language to copy — so the PROJECT chooses, and the choice is written in the
    registry where anybody can read it.

    THE DEFAULT ITSELF IS ENGLISH (2026-08-14). It was `pt-BR` — the first deployment's language
    wearing a default's clothes — so every client who never declared one was addressed in
    Portuguese by a product that ships worldwide. A default IS the product; a deployment that
    wants another language says so, and this asserts both halves."""
    from openfactory.contracts.project import Project

    assert Project(name="c", repo_path="/t").language == "en"
    assert "Hello" in announcement(product="p")
    assert "Olá" in announcement(product="p", language="pt-BR")


def test_an_untranslated_language_degrades_to_something_readable():
    """A KeyError inside a chat listener over an unusual language code would take the channel down
    for a configuration typo."""
    text = written_up(title="t", url="u", number=1, language="ja-JP")
    assert text and "requirement 1" in text  # the default, not a crash


@pytest.mark.parametrize("lang", ["pt-BR", "en"])
def test_no_message_leaks_jargon_in_EITHER_language(lang):
    """The leak will happen in the project's own language, which is the one nobody thinks to
    check."""
    for text in (announcement(product="p", areas=["conciliação"], language=lang),
                 confirmation_request(title="t", must_be_true=["x"], language=lang),
                 written_up(title="t", url="u", number=1, language=lang),
                 cannot_write(has_approvers=False, language=lang),
                 cannot_write(has_approvers=True, language=lang),
                 unavailable(language=lang)):
        assert jargon_in(text) == [], text


def test_a_reply_follows_the_ASKERS_language_not_the_default():
    """Someone who writes in English wants an answer in English, whatever the project says — and a
    hard setting that ignores that is visible immediately."""
    from openfactory.adapters.agent.roles import language_directive

    rule = language_directive("pt-BR")
    assert "pt-BR" in rule
    assert "language THEY wrote in" in rule
    assert "not translated" in rule


def test_only_human_facing_phases_are_localised():
    """An executor's prompt language is a different question, and changing it would move a path
    that works in production for a benefit nobody asked for."""
    from openfactory.adapters.agent.roles import HUMAN_PHASES

    assert {"chat", "diagnose", "advise", "size", "product_answer"} <= HUMAN_PHASES
    assert not ({"execute", "plan", "repair", "review"} & HUMAN_PHASES)


# ── the rules reach the model ────────────────────────────────────────────────────────────────────

def test_the_audience_rules_are_concrete_not_a_plea_for_niceness():
    """"be friendly" changes nothing. A before/after pair does."""
    assert "instead of" in AUDIENCE_RULES
    assert "pull request" in AUDIENCE_RULES        # named explicitly as forbidden
    assert "requirement 7" in AUDIENCE_RULES       # and what to say instead


def test_conversation_gets_the_rules_and_team_artefacts_do_not():
    """Softening an issue body into business prose would strip the detail the people acting on it
    need. The answer is two surfaces, not one vague voice."""
    from openfactory.contracts import AgentRunResult
    from openfactory.product.corpus import Requirement
    from openfactory.product.role import ProductRole

    class _H:
        name = "rec"

        def __init__(self):
            self.prompts = []

        def ask(self, *, sandbox, workspace, prompt, phase="ask"):
            self.prompts.append(prompt)
            return AgentRunResult(ok=True, summary='{"issues": [{"title": "t", "objective": "o",'
                                                   ' "acceptance_criteria": ["c"]}]}')

    class _S:
        def run(self, **kw):
            return 0, ""

    from openfactory.adapters.sandbox.base import Workspace

    ws = Workspace(path="/tmp", branch="main", base_branch="main")
    h = _H()
    role = ProductRole(h)

    role.answer(sandbox=_S(), workspace=ws, question="q")
    assert "Who you are talking to" in h.prompts[0]

    role.issues_for(sandbox=_S(), workspace=ws,
                    requirement=Requirement(number=1, slug="x", path="p"), sources=[])
    assert "Who you are talking to" not in h.prompts[1]


# ── the agent has a name ────────────────────────────────────────────────────────────────────────

def test_it_introduces_itself_by_name_when_it_has_one():
    """People argue with a named colleague. They do not argue with "the product agent", and this
    role is only worth having if a non-technical owner pushes back on it."""
    from openfactory.product.voice import announcement

    text = announcement(product="Acme Books", agent_name="Nina", language="pt-BR")
    assert "meu nome é Nina" in text
    assert "cuido do produto *Acme Books*" in text


def test_the_greeting_works_for_ANY_name_not_just_a_feminine_one():
    """"sou a Nina" reads correctly and "sou a Bruno" does not — so no phrase carries a gendered
    article, and a client naming theirs anything gets a sentence that works."""
    from openfactory.product.voice import announcement

    for name in ("Nina", "Bruno", "Alex", "Kim"):
        # pt-BR NAMED: the trap this guards ("sou a Bruno") exists only in Portuguese, so the
        # language is part of the case rather than something inherited from a default
        assert f"meu nome é {name}" in announcement(product="X", agent_name=name,
                                                    language="pt-BR")


def test_without_a_name_it_introduces_itself_by_function():
    from openfactory.product.voice import announcement

    text = announcement(product="X", language="pt-BR")
    assert "agente de produto do *X*" in text
    assert "meu nome" not in text


def test_a_signature_names_the_ROLE_as_well_as_the_person():
    """The team reads these. "Nina" alone tells a new joiner nothing about why the comment exists."""
    from openfactory.product.voice import signature

    assert signature("Nina") == "**Nina (produto):**"
    assert signature("") == "**Produto:**"


def test_ticket_comments_carry_the_name():
    from openfactory.product.needs_action import TECHNICAL, Verdict, hand_back_comment

    v = Verdict(ticket=1, cause=TECHNICAL, confidence="high")
    assert hand_back_comment(v, agent_name="Nina").startswith("**Nina (produto):**")
    assert hand_back_comment(v).startswith("**Produto:**")


def test_the_role_is_TOLD_its_own_name():
    """Without this it answers about itself in the third person, which is exactly the tell that
    something is a bot wearing a name badge."""
    from openfactory.contracts import AgentRunResult
    from openfactory.product.role import ProductRole

    class _H:
        name = "rec"

        def __init__(self):
            self.prompts = []

        def ask(self, *, sandbox, workspace, prompt, phase="ask"):
            self.prompts.append(prompt)
            return AgentRunResult(ok=True, summary="ok")

    class _S:
        def run(self, **kw):
            return 0, ""

    from openfactory.adapters.sandbox.base import Workspace

    h = _H()
    ProductRole(h, agent_name="Nina").answer(
        sandbox=_S(), workspace=Workspace(path="/tmp", branch="m", base_branch="m"), question="oi")
    assert "You are called Nina" in h.prompts[0]
    assert "third person" in h.prompts[0]

    h2 = _H()
    ProductRole(h2).answer(sandbox=_S(),
                           workspace=Workspace(path="/tmp", branch="m", base_branch="m"),
                           question="oi")
    assert "You are called" not in h2.prompts[0]


# ── the guard must be usable, not just strict ───────────────────────────────────────────────────

def test_a_LINK_is_not_jargon():
    """A URL is what this role says INSTEAD of a file path, so every well-behaved message has one.
    Substring matching flagged `https://github.com/...` for "git" and would have rejected exactly
    the messages the rules ask for — a guard that fires on every good message is one nobody keeps.
    Found by simulating a real confirmation, not by any unit test."""
    assert jargon_in("Você pode ler aqui: https://github.com/x/pull/9") == []
    assert jargon_in("Leia <https://github.com/AcmeCorp/docs/pull/3>") == []


def test_short_terms_are_matched_on_word_boundaries():
    """"git" hides in "digital", "repo" in "repor", "merge" in "emergem". Flagging those would make
    ordinary Portuguese unwritable."""
    assert jargon_in("a transformação digital repõe o que emergem dos dados") == []


def test_the_guard_still_catches_the_real_thing():
    """A guard nobody can fail is not a guard."""
    assert jargon_in("abri um pull request na branch req/0012") == ["branch", "pull request"]
    assert jargon_in("depois do merge eu faço o deploy") == ["deploy", "merge"]


@pytest.mark.parametrize("lang", ["pt-BR", "en"])
def test_a_MERGED_requirement_and_an_UNMERGED_one_read_differently(lang):
    """Two different facts, two different sentences. "It is in the base" and "it exists but has not
    landed" are not interchangeable, and the second carries something the first does not: SHE CANNOT
    READ IT YET. That was invisible until she said "do meu lado ela está vazia" about a requirement
    she had just written, and was right — she reads the docs branch, and it was on a branch."""
    landed = written_up(title="t", url="u", number=3, language=lang, merged=True)
    open_ = written_up(title="t", url="u", number=3, language=lang, merged=False)

    assert landed != open_
    for text in (landed, open_):
        assert "http" not in text, text
    assert ("acordo" in landed or "agreement" in landed), "the landed text must say it is NOT yet agreed"


@pytest.mark.parametrize("lang", ["pt-BR", "en"])
def test_writing_a_requirement_is_never_described_as_agreeing_to_it(lang):
    """The distinction the whole lifecycle rests on: a written requirement is a PROPOSAL. Only a
    person's confirmation makes it a promise the factory defends (ADR-0032), and conflating the two
    is how a factory starts arguing from something nobody agreed to."""
    text = written_up(title="t", url="u", number=3, language=lang, merged=True)
    assert ("não** é um acordo" in text) or ("NOT an agreement yet" in text), text
