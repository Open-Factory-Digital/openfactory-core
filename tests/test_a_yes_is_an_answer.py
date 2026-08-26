"""The factory asked, the operator said yes, and only a button counted (#156).

MEASURED ON THE PILOT, 2026-08-19:

    19:38  (operator)  vai la da o merge por favor
    19:38  (tech-lead) … the decision is yours, I will go ahead with the merge.
                       ▶ merge #101
    19:40  (operator)  pode seguir
    19:40  (tech-lead) [a status report. No merge.]

The pull request was still open. He said merge twice, in plain Portuguese, and the platform did
nothing both times — the first a matcher gap (#158), the second this.

The tech-lead had STAGED a real proposal: a token, retired on a second click, expiring on a TTL.
The machinery was good and the only way to accept it was pressing the button. Answering in words
fell through as a fresh question, so the tech-lead re-read the floor and answered about it again.
From the operator's side, the factory asked a yes/no question, was told yes, and changed the
subject — this repository's own rule inverted, on the one screen where the PLATFORM is the one
asking.

TWO PROPERTIES, IN TENSION, WHICH IS WHY BOTH ARE HERE. A yes must reach the proposal — and a
false positive presses a button that merges a pull request into somebody's main branch, so what
counts as yes is anchored to the whole message exactly like the bare verb is.
"""

from __future__ import annotations

import ast
import inspect

import add_ons
import pytest

from openfactory.actions.floor_intents import is_affirmation


@pytest.mark.parametrize("said", [
    "sim", "ok", "OK!", "beleza", "blz", "tá", "tá bom", "fechado", "aprovado", "confirmo",
    "pode", "pode seguir", "Pode seguir.", "pode ir", "pode prosseguir", "pode mandar",
    "segue", "manda", "manda ver", "vai lá", "bora",
    "yes", "yep", "sure", "go", "go ahead", "do it", "ship it", "proceed", "lgtm",
])
def test_a_yes_is_recognised_as_one(said):
    assert is_affirmation(said), f"{said!r} did not count as an answer"


@pytest.mark.parametrize("said", [
    "pode ser",                     # agrees with a suggestion; does not order it
    "certo",                        # "understood" as often as "do it"
    "talvez",
    "não", "no", "nope",
    "pode?",                        # asking permission, not granting it
    "pode seguir com o merge?",
    "sim, mas o teste falhou",      # a yes with a condition is not a yes
    "ok, mas espera",
    "pode descartar",               # an ORDER, not an answer — it names its own action
    "ta",                           # "thanks" in British English — thanking is not approving
    "obrigado", "thanks",           # gratitude in any language is not consent
    "", "   ",
])
def test_and_everything_else_is_not(said):
    assert not is_affirmation(said), f"{said!r} would have pressed a staged merge button"


# ── the words are a TABLE, not a pattern (#157) ─────────────────────────────────────────────────
#
# The pilot's own question, translated: "that is not hard-coded, right? because it will not
# necessarily be in Portuguese." The first version was one regex with Portuguese and English
# welded in — MORE tied to two languages than anything else in the product. And keying the table
# on the project's configured language would be the same mistake from the other side: his project
# is configured `en` and he answers in Portuguese, because people type in their own tongue
# whatever the config says.

def test_adding_a_language_is_a_ROW_and_it_works_immediately(monkeypatch):
    """`monkeypatch.setitem`, not try/finally: pytest restores it even when the process dies
    mid-test, and a global left mutated by a hard failure poisons every later test in the worker."""
    from openfactory.language import assent

    assert not is_affirmation("vas-y")
    monkeypatch.setitem(assent.CORE, "fr", ("vas-y", "oui", "d'accord"))
    assert is_affirmation("vas-y") and is_affirmation("oui"), (
        "a new language row is dead until something else changes — the extension point is "
        "decoration")
    monkeypatch.delitem(assent.CORE, "fr")
    assert not is_affirmation("oui"), "the table is cached somewhere, so it is not the truth"


def test_every_catalogued_language_is_accepted_at_once():
    """The pilot is the proof: his project says `language: en` and he types "sim". Keying the
    match on the setting would have refused the exact word the card was filed about."""
    for word in ("sim", "yes", "pode seguir", "ship it"):
        assert is_affirmation(word), f"{word!r} refused — the union collapsed to one row"


def test_the_words_live_in_the_table_and_nowhere_else():
    """No natural-language word may be welded into the matching code: that is the shape the pilot
    caught, and a word in the code is a word no deployment can remove or extend. Now checked
    across all THREE surfaces, which is the point of #161 — one table, three consumers."""
    import re as _re

    from openfactory.actions import floor_intents as fi
    from openfactory.language import assent
    from openfactory.product import staging
    bot = add_ons.module("openfactory.runtime.slack.bot")

    src = "\n".join(inspect.getsource(f) for f in (
        assent.is_bare_assent, assent.asserts_assent, fi.is_affirmation,
        staging.is_yes, bot._is_approval, bot._mentions_approval))
    # DOCSTRINGS AND *TRAILING* COMMENTS BOTH. The first version stripped only whole-line
    # comments and tripped on `return True  # a phrase the word tier cannot see ("go ahead")` —
    # the sentence explaining the rule this guard protects. Third time in one session
    # ([[strip-the-prose-before-asserting]]).
    code = _re.sub(r'"""[\s\S]*?"""', "", src)
    code = "\n".join(_re.sub(r"(^|\s)#.*$", "", ln) for ln in code.splitlines())
    for table in (assent.CORE, assent.CORE_PHRASES, assent.FILLER):
        for row in table.values():
            for word in row:
                assert f'"{word}"' not in code, (
                    f"{word!r} is welded into the matching code beside the table")


def test_the_collision_discipline_holds():
    """A word may enter a row only if, as a complete message, it can mean nothing but assent in
    EVERY catalogued language. These are the known collisions and design exclusions — each one, as
    a whole message beside a staged merge button, would press it while meaning something else."""
    from openfactory.language.assent import CORE, CORE_PHRASES

    every = {w for row in {**CORE, **CORE_PHRASES}.values() for w in row}
    # BOTH HALVES, because only one of them was ever asserted and the other silently went away:
    # `tá` was dropped into FILLER while consolidating these tables, and the pilot typing it beside
    # a staged merge button got nothing.
    assert "tá" in CORE["pt-br"], (
        "`tá` left the table — it is how a Brazilian answers yes and it collides with no "
        "catalogued language, which is exactly why `ta` is banned and it is not")
    for banned, why in [("ta", "thanks, in British English"),
                        ("pode ser", "agrees with a suggestion; does not order it"),
                        ("certo", "'understood' as often as 'do it'"),
                        ("maybe", "hedges"), ("i think so", "hedges"),
                        ("no", "is a negation"), ("não", "is a negation")]:
        assert banned not in every, f"{banned!r} entered a row — it {why}"


def test_a_double_space_cannot_unsay_a_yes():
    assert is_affirmation("pode   seguir")
    assert is_affirmation("go  ahead")


def test_the_question_test_is_reused_rather_than_reinvented():
    """`pode?` is refused by the same `_asks_rather_than_tells` every other gesture in that file
    goes through — a second notion of "this is a question" is how two surfaces come to disagree
    about the same sentence."""
    from openfactory.actions import floor_intents as fi

    src = inspect.getsource(fi.is_affirmation)
    assert "_asks_rather_than_tells" in src


# ── one implementation, two doors ───────────────────────────────────────────────────────────────

def test_the_ROUTE_no_longer_carries_its_own_copy_of_the_sequence():
    """`perform` → retire the button → put the outcome in the thread. Three steps, every one of
    them load-bearing, and the day the chat learned to accept a proposal there would have been two
    of them. The route is the mapping onto the action layer, like every other door."""
    from openfactory.api import app

    route = inspect.getsource(app.approve_suggestion)
    assert "run_staged" in route, "the route does not go through the action layer"
    for own in ("channel.answer(", "channel.say(", "actions.perform("):
        assert own not in route, (
            f"the route still performs {own} itself — a second implementation of the sequence")


def test_the_chat_and_the_button_reach_the_SAME_function():
    from openfactory.actions import catalog
    from openfactory.api import app

    for where in (inspect.getsource(catalog._ask), inspect.getsource(app.approve_suggestion)):
        assert "run_staged" in where


def test_the_words_path_is_tried_BEFORE_the_agent_is_asked():
    """An answer to a staged question must not cost a tech-lead invocation to be understood — and
    if it fell through to the agent it would not be an answer at all, it would be a new question
    about the floor, which is exactly what the pilot got."""
    src = inspect.getsource(__import__("openfactory.actions.catalog", fromlist=["x"])._ask)
    assert src.index("is_affirmation") < src.index("AskWorkflow"), (
        "the agent is asked first, so a yes spends a pass and presses nothing")


# ── the yes REACHES it, and that is not a claim about source order ─────────────────────────────
#
# THE TWO MUTATIONS THAT SURVIVED THE FIRST ROUND WERE BOTH THIS GAP. Cutting `if
# is_affirmation(text):` out of `_ask` entirely left every guard above green, because every one of
# them read the SOURCE — the name was still in the file, still before `AskWorkflow`. Nothing drove
# the path. `built-tested-reached-by-nothing`, in the change that exists to stop an answer going
# nowhere.

async def test_a_yes_typed_at_the_tech_lead_presses_the_LIVE_proposal(monkeypatch):
    import openfactory.actions as actions
    from openfactory.actions import catalog
    from openfactory.memory import messages as channel

    class _Msg:
        token = "t9"

    pressed: list[dict] = []

    async def _fake_run(*, project, by, token=""):
        pressed.append({"project": project, "token": token})
        return catalog.done("merging #101 now")

    monkeypatch.setattr(catalog, "_project", lambda p: (type("P", (), {"name": p})(), None))
    monkeypatch.setattr(catalog, "_remember", lambda *a, **k: None)
    monkeypatch.setattr(channel, "staged", lambda p, **k: (_Msg(), ""))
    monkeypatch.setattr(catalog, "run_staged", _fake_run)

    out = await catalog._ask(project="demo", question="pode seguir", by=actions.SYSTEM)

    assert pressed == [{"project": "demo", "token": ""}], (
        "a plain yes did not reach the staged proposal — it fell through as a new question, which "
        "is exactly what the pilot got")
    assert out.ok and "merging" in out.message


async def test_a_SENTENCE_typed_at_the_tech_lead_does_not(monkeypatch):
    """The twin, on the same wiring: anything that is not a bare yes must not press anything, and
    a guard that only proved the yes arrives would be satisfied by a function that presses on
    every message."""
    import openfactory.actions as actions
    from openfactory.actions import catalog
    from openfactory.memory import messages as channel

    pressed: list[str] = []

    async def _fake_run(*, project, by, token=""):
        pressed.append(project)
        return catalog.done("pressed")

    async def _no_route(*a, **k):
        return catalog.done("the tech-lead answered in prose")

    monkeypatch.setattr(catalog, "_project", lambda p: (type("P", (), {"name": p})(), None))
    monkeypatch.setattr(catalog, "_remember", lambda *a, **k: None)
    monkeypatch.setattr(channel, "staged", lambda p, **k: (object(), ""))
    monkeypatch.setattr(catalog, "run_staged", _fake_run)
    monkeypatch.setattr(catalog, "_floor_say_as_an_intent", _no_route)

    await catalog._ask(project="demo", question="sim, mas o teste falhou",
                       by=actions.SYSTEM)

    assert pressed == [], "a sentence that merely starts with a yes pressed a staged merge"


# ── what happens when the proposal is not live ──────────────────────────────────────────────────

async def test_a_yes_with_NOTHING_staged_is_still_a_question():
    """Nothing is proposed, so a bare "ok" is conversation — it must reach the tech-lead rather
    than turn into a refusal about a button that was never there."""
    from openfactory.actions import catalog

    src = inspect.getsource(catalog._ask)
    tree = ast.parse(inspect.cleandoc("\n" + src))
    guarded = [n for n in ast.walk(tree)
               if isinstance(n, ast.If) and "live is not None" in ast.unparse(n.test)]
    assert guarded, "a yes runs `run_staged` even when nothing is staged"


@pytest.mark.parametrize("why,expected", [
    ("answered", "already ran that one"),
    ("expired", "too old to press"),
    ("superseded", "no longer open"),
])
async def test_a_yes_that_arrives_LATE_is_told_which_kind_of_late(why, expected):
    """A staged suggestion retires three ways, and "nothing happened" is the one answer none of
    them may produce: a person who sees "this expired" asks again, a person who sees silence
    concludes the platform forgot."""
    import openfactory.actions as actions
    from openfactory.actions import catalog

    class _Msg:
        token = "t1"

    class _Channel:
        @staticmethod
        def staged(project, **k):
            return _Msg(), why

    from openfactory.memory import messages as channel

    real, channel.staged = channel.staged, _Channel.staged
    try:
        out = await catalog.run_staged(project="demo", by=actions.SYSTEM, token="")
    finally:
        channel.staged = real

    assert out.ok is False
    assert out.code == catalog.CONFLICT
    assert expected in out.message, out.message


async def test_an_UNREADABLE_store_is_not_read_as_nothing_proposed():
    """503, not "the tech-lead is not proposing that" — an outage that renders as a refusal blames
    a person for a decision nobody made. The rule the routes already state, now where the sequence
    actually lives."""
    import openfactory.actions as actions
    from openfactory.actions import catalog
    from openfactory.memory import messages as channel
    from openfactory.observability.query import StoreUnreadable

    def _boom(project, **k):
        raise StoreUnreadable("disk gone")

    # PATCHED ON THE MODULE, not through `sys.modules`: `from openfactory.memory import messages`
    # reads the package ATTRIBUTE once the package is imported, so a stand-in registered in
    # `sys.modules` is ignored — which is why this passed alone and failed in the full suite.
    real, channel.staged = channel.staged, _boom
    try:
        out = await catalog.run_staged(project="demo", by=actions.SYSTEM)
    finally:
        channel.staged = real

    assert out.code == catalog.UNAVAILABLE
    assert "nothing was done" in out.message.lower()


# ── 7. a token that cannot decide must not be DROPPED (#161) ────────────────────────────────────
#
# The sweep's sharpest finding, reproduced before it was fixed: `acceptance_verdict` closes a
# delivery loop as the CLIENT'S OWN SIGN-OFF, and it runs before the model judge. Spanish
# "todavía no funciona" — "it still doesn't work" — is three words; it matches no unambiguous
# denial (bare "no" was dropped from that list because it is also the Portuguese preposition em+o)
# and hits `funciona` in the positive list. The complaint signed off the delivery.
#
# The file already stated the rule it was breaking: "a borrowed token must be unambiguous across
# BOTH languages". What it did with a token that failed the test was DROP it — and dropping lets
# the other list decide alone. Ambiguity is now a verdict: "" , and a model reads the sentence.

@pytest.mark.parametrize("said,verdict", [
    ("todavía no funciona", ""),      # the measured case: a complaint that used to sign off
    ("ya no funciona", ""),           # es: a regression
    ("ya funciona", "worked"),        # es: an acceptance — the negator is `no`, not `ya`
    ("no funciona", ""),
    ("no está funcionando", ""),      # the negator is two words from what it negates
    ("nada funciona", ""),
    ("ça ne marche pas", ""),         # fr: no row at all, and nothing to decide with
    # THE READINGS THE EXISTING SUITE PINNED, and they are why position decides rather than
    # presence: the Portuguese locative em+o comes AFTER the positive word, the Spanish negation
    # comes BEFORE it. Deleting either reading would have been a fix that broke a live client.
    ("sim, resolveu no sistema", "worked"),
    ("funcionou no celular", "worked"),
    ("resolveu no caso da folha", "worked"),
    ("funktioniert nicht", ""),       # a language with no row at all
    ("não resolveu", "did-not-work"),  # unambiguous denial still wins, and wins FIRST
    ("continua quebrado", "did-not-work"),
    ("still broken", "did-not-work"),
    ("sim", "worked"),
    ("funcionou perfeitamente", "worked"),
    ("it works", "worked"),
])
def test_the_clients_acceptance_is_never_INFERRED_from_a_shared_word(said, verdict):
    from openfactory.product.followup import acceptance_verdict

    assert acceptance_verdict(said) == verdict, (
        f"{said!r} → {acceptance_verdict(said)!r}: a delivery loop is closed as the client's own "
        f"sign-off, and this is the direction that must never fail")


def test_the_denial_still_outranks_the_doubt():
    """Order matters and the file's own rule sets it: a message carrying BOTH an unambiguous
    denial and an ambiguous token is a denial. Failing towards 'not accepted' is the safe
    direction — a wrongly-open loop costs one more question, a wrongly-closed one claims success
    on the client's behalf."""
    from openfactory.product.followup import acceptance_verdict

    assert acceptance_verdict("não funciona no sistema") == "did-not-work"


def test_a_doubtful_token_is_not_a_REJECTION_either():
    """The opposite over-correction, and it would be just as wrong: "" sends the sentence to the
    judge, it does not record that the client said no."""
    from openfactory.product.followup import acceptance_verdict

    assert acceptance_verdict("no funciona") == "", "a doubtful denial became a recorded rejection"


def test_only_NEGATORS_carry_doubt():
    """`ya` was in the doubt list for one commit, and "ya funciona" — a Spanish sign-off — came
    back deferred. A temporal adverb negates nothing; the word that separates "ya funciona" from
    "ya no funciona" is `no`."""
    from openfactory.product import followup

    for word in ("ya", "todavía", "mais", "más", "already"):
        assert not followup._CANNOT_DECIDE.search(word), (
            f"{word!r} carries doubt — it is not a negator, and it defers real acceptances")
    for word in ("no", "nada", "pas", "nicht"):
        assert followup._CANNOT_DECIDE.search(word), f"{word!r} stopped carrying doubt"


# ── 8. two bars, one vocabulary — and the difference is DECLARED (#161) ─────────────────────────
#
# The floor's gesture MERGES, so it asks that the whole message BE an assent. The channels approve
# a staged proposal in conversation, where "sim, pode registrar" is the most Brazilian
# confirmation there is. Different bars, one table — which is the only way they can be compared at
# all, and comparing them is how `certo` was found asserting on one surface, merely accompanying
# on the second, and audited out of the third.

@pytest.mark.parametrize("said", [
    "sim, pode registrar",     # every word catalogued, ≥1 core — a channel yes, NOT a merge
    "certo, pode registrar",
    "ok então",
])
def test_the_FLOOR_refuses_what_the_channel_accepts(said):
    from openfactory.product.staging import is_yes

    assert is_yes(said) is True, f"{said!r} stopped being a confirmation on the product channel"
    assert is_affirmation(said) is False, (
        f"{said!r} would press a staged MERGE — the floor's bar is the whole message, and it "
        f"dropped to the channel's")


@pytest.mark.parametrize("said", ["sim", "ok", "pode seguir", "vai lá"])
def test_and_a_bare_assent_still_clears_BOTH(said):
    from openfactory.product.staging import is_yes

    assert is_affirmation(said) is True and is_yes(said) is True


def test_certo_ACCOMPANIES_and_never_asserts():
    """One word, three answers, measured by the sweep — this is the resolution. It may carry a yes
    on the channels; it may never BE one anywhere, and it presses nothing on the floor."""
    from openfactory.language import assent
    from openfactory.product.staging import is_yes

    assert "certo" in assent.filler_words()
    assert "certo" not in assent.core_words(), (
        "`certo` asserts approval again — on a surface that promotes tickets and spends money")
    assert is_yes("certo") is False and is_affirmation("certo") is False
    assert is_yes("certo, pode registrar") is True, (
        "it stopped ACCOMPANYING a yes, and the confirmations people type broke with it")


def test_the_OPERATOR_channel_reads_the_same_table():
    """`bot._is_approval` was the third hand-rolled list, and its own comment justified `certo`
    being non-core by citing the product channel as keeping `pode`-alone out — which it did not.
    A justification citing a false fact is what one table makes impossible to restate."""
    bot = add_ons.module("openfactory.runtime.slack.bot")

    assert bot._is_approval("sim, pode registrar") is True
    assert bot._is_approval("certo") is False, "`certo` asserts on the operator channel again"
    assert bot._is_approval("isso continua quebrado, não mexe") is False, (
        "a complaint fires the staged action — the defect this gate was rewritten for")
    assert bot._is_approval("qualquer coisa") is False, (
        "the gate accepts anything with words in it")
    assert bot._mentions_approval("ok mas espera") is True, (
        "the ambiguous middle stopped being ambiguous — the caller re-asks on this")


def test_the_ACCENT_is_what_separates_a_yes_from_a_thank_you():
    """The collision discipline in one line of behaviour: `tá` presses the button, `ta` does not.

    They are different strings and this path never folds accents — asserted here because a
    normaliser added upstream "for convenience" would collapse them and hand a British "ta" the
    merge button."""
    from openfactory.language.assent import is_bare_assent

    assert is_bare_assent("tá") and not is_bare_assent("ta")


@pytest.mark.parametrize("said", ["tá difícil", "tá ruim", "tá errado", "tá quebrado"])
def test_and_a_tá_that_STARTS_a_complaint_is_not_a_yes(said):
    """`tá` is a yes only as the whole message. The channel's bar needs every word catalogued, so
    a complaint that opens with it is refused by the words that follow — which is the property
    that makes putting a two-letter word in CORE safe at all."""
    from openfactory.language.assent import asserts_assent, is_bare_assent

    assert not is_bare_assent(said) and not asserts_assent(said)
