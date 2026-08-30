"""The backfill's questions get an identity and a way to end.

WHAT THEY WERE. `propose_context` has always produced questions and rendered them into
`docs/perguntas-abertas.md` and the onboarding pull request body, as `list[str]`. No identity, no
state, no way to know whether one was ever dealt with — re-run the backfill next month and the same
six questions arrive again, indistinguishable from six new ones.

WHY ONLY THE DERIVABLE ONES ARE TRACKED, and it is a scoping decision rather than a first
instalment: a loop needs an identity that survives a re-run. `blind-modules` is the same question
next month because the same code derives it from the same kind of fact. A question an LLM wrote is
not — the wording drifts, and hashing the text would open a fresh loop every pass and chase a person
about something they already answered.

THE GUARD THIS FILE IS ARRANGED AROUND. A survey that could not run produces ZERO questions, and
zero questions read as "every gap is gone". A repository that became unreadable, a clone that
failed, a walk that raised — each would silently close every open question and the platform would
stop asking about a codebase it can no longer see. That is absence of evidence arriving as evidence
of absence, and here it does not merely misreport: it erases the record.
"""

from __future__ import annotations

import pytest

from openfactory.memory.ledger import CONTEXT, KINDS, QUESTION, close_by_observation, open_loop
from openfactory.onboarding.questions import (
    BLIND_MODULES,
    CODES,
    GAP_CLOSED,
    UNREAD_CODE,
    UNTESTED_MODULES,
    SurveyQuestion,
    resolved,
    to_open,
)

REPO = "acme/legacy"
TS = "2026-08-30T10:00:00Z"


def _q(code: str) -> SurveyQuestion:
    return SurveyQuestion(code, f"a question about {code}")


# ── identity ─────────────────────────────────────────────────────────────────────────────────────

def test_a_question_the_survey_earns_becomes_a_loop() -> None:
    """The control. Until now these were sentences the platform emitted and forgot."""
    rows = to_open([_q(BLIND_MODULES), _q(UNREAD_CODE)], repo=REPO, waiting=[], ts=TS)

    assert [(r.kind, r.subject, r.about) for r in rows] == [
        (CONTEXT, REPO, BLIND_MODULES), (CONTEXT, REPO, UNREAD_CODE)]
    assert rows[0].context["text"], "the question a person reads travels with the loop"


def test_re_running_the_backfill_does_not_ask_twice() -> None:
    """Deduplicated on the CODE, not the text — which is the whole point of having a code. The same
    gap re-derived with different wording is the same question, and opening it again would chase
    somebody about what they are already looking at."""
    first = to_open([_q(BLIND_MODULES)], repo=REPO, waiting=[], ts=TS)
    reworded = [SurveyQuestion(BLIND_MODULES, "completely different wording, same gap")]

    assert to_open(reworded, repo=REPO, waiting=first, ts="2026-09-30T10:00:00Z") == []


def test_a_question_about_another_repository_is_a_different_question() -> None:
    """One deployment drives many projects. `blind-modules` on the API and on the front end are two
    gaps, and closing one must not close the other."""
    api = to_open([_q(BLIND_MODULES)], repo="acme/api", waiting=[], ts=TS)

    assert len(to_open([_q(BLIND_MODULES)], repo="acme/web", waiting=api, ts=TS)) == 1


def test_a_closed_question_can_be_asked_again_when_the_gap_returns() -> None:
    """A module that loses its description again is a live question again. Deduplication is against
    what is still WAITING, never against everything that ever was."""
    opened = to_open([_q(BLIND_MODULES)], repo=REPO, waiting=[], ts=TS)
    closed = close_by_observation(
        opened, resolved(opened, repo=REPO, fresh=[], surveyed=True))

    assert to_open([_q(BLIND_MODULES)], repo=REPO, waiting=closed, ts="t2")


# ── closing, by observation ──────────────────────────────────────────────────────────────────────

def test_a_gap_the_survey_no_longer_earns_is_closed() -> None:
    """The module now has a description; the question is over. Closed because a pass LOOKED at the
    world, which is the only closing this ledger accepts."""
    opened = to_open([_q(BLIND_MODULES), _q(UNREAD_CODE)], repo=REPO, waiting=[], ts=TS)

    closed = close_by_observation(
        opened, resolved(opened, repo=REPO, fresh=[_q(UNREAD_CODE)], surveyed=True))

    assert [(c.about, c.outcome) for c in closed] == [(BLIND_MODULES, GAP_CLOSED)]


def test_a_gap_still_there_stays_open() -> None:
    """The positive twin: a `resolved` that closed everything would satisfy the guard above."""
    opened = to_open([_q(BLIND_MODULES)], repo=REPO, waiting=[], ts=TS)

    assert resolved(opened, repo=REPO, fresh=[_q(BLIND_MODULES)], surveyed=True) == {}


def test_the_outcome_says_the_gap_closed_and_not_that_anyone_answered() -> None:
    """This pass never observes a reply and must never claim one: it saw a gap close, and a ledger
    that records an answer it did not see is the single thing this store exists to refuse.

    THE LITERAL, NOT THE CONSTANT. The first version asserted `== {GAP_CLOSED}` — comparing the
    value to itself, so renaming the constant to `"answered"` changed both sides and the guard
    stayed green. A tautology is not a guard, and this one was protecting the sentence that
    matters most in the module."""
    opened = to_open([_q(BLIND_MODULES)], repo=REPO, waiting=[], ts=TS)

    assert set(resolved(opened, repo=REPO, fresh=[], surveyed=True).values()) == {"gap-closed"}
    assert "answer" not in GAP_CLOSED, "the outcome must not claim a reply nobody observed"


# ── the guard this file is arranged around ───────────────────────────────────────────────────────

def test_a_survey_that_could_not_run_closes_NOTHING() -> None:
    """THE ONE THAT MATTERS. Zero questions from a survey that failed is not "every gap is gone" —
    it is "nobody looked". Trusted, it would erase the record of a codebase the platform can no
    longer see, which is worse than misreporting it."""
    opened = to_open([_q(c) for c in CODES], repo=REPO, waiting=[], ts=TS)

    assert resolved(opened, repo=REPO, fresh=[], surveyed=False) == {}
    assert len(resolved(opened, repo=REPO, fresh=[], surveyed=True)) == len(CODES), (
        "the fixture must be able to reach the cut — a trusted empty survey closes everything")


def test_a_survey_that_ran_and_found_nothing_DOES_close() -> None:
    """The other side, and it is what the flag buys: a repository whose gaps genuinely all closed
    reports exactly that. Without this the guard above is satisfied by refusing to ever close."""
    opened = to_open([_q(BLIND_MODULES)], repo=REPO, waiting=[], ts=TS)

    assert resolved(opened, repo=REPO, fresh=[], surveyed=True)


# ── the kind, and the trap it exists to avoid ────────────────────────────────────────────────────

def test_context_is_its_own_ledger_kind() -> None:
    """`followup.answered()` closes every open QUESTION whose `subject:about` is absent from the
    board's live findings — closing by ABSENCE. A question about a codebase has no board finding at
    all, so sharing the kind would close it on the very next product sweep, minutes after it was
    opened. `DECISION` carries the same scar for the same reason."""
    assert CONTEXT in KINDS
    assert CONTEXT != QUESTION

    rows = to_open([_q(BLIND_MODULES)], repo=REPO, waiting=[], ts=TS)
    assert all(r.kind != QUESTION for r in rows)


def test_the_product_sweep_cannot_close_a_context_question() -> None:
    """The trap, run rather than described: `followup.answered` is given a board with no findings
    at all, which is what a context question always looks like to it."""
    from openfactory.product.followup import answered

    rows = to_open([_q(BLIND_MODULES)], repo=REPO, waiting=[], ts=TS)

    assert answered(rows, live_keys=set()) == {}


def test_a_context_question_does_not_eat_the_products_question_budget() -> None:
    """`followup.MAX_QUESTIONS_PER_PASS` counts already-open QUESTION loops. Sharing the kind would
    push a stalled ticket's question out of the batch that reaches a person — the platform would go
    quieter about the board the more it learned about the code."""
    from openfactory.product.followup import MAX_QUESTIONS_PER_PASS, Question
    from openfactory.product.followup import to_open as ask

    context_rows = to_open([_q(c) for c in CODES], repo=REPO, waiting=[], ts=TS)
    board = [Question(ticket="7", code="stalled", text="why is this stalled?")]

    assert len(ask(board, waiting=context_rows, ts=TS)) == 1
    assert len(CODES) > MAX_QUESTIONS_PER_PASS, "the fixture must exceed the cap to reach the cut"


# ── the survey now earns questions that carry their code ─────────────────────────────────────────

def test_the_survey_produces_coded_questions(tmp_path) -> None:
    """End to end through the real survey: a repository with no description anywhere earns the
    blind-modules question, and it arrives with an identity rather than as a sentence."""
    from openfactory.onboarding import context as ctx

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "a.py").write_text("def f():\n    return 1\n")

    proposal = ctx.propose_context(ctx.survey(str(tmp_path)), language="en")

    assert proposal.tracked, "the survey earned no tracked question at all"
    assert {q.code for q in proposal.tracked} <= set(CODES)
    assert all(q.code for q in proposal.tracked), "a tracked question with no code cannot close"


def test_the_rendered_questions_still_carry_the_tracked_text(tmp_path) -> None:
    """One source, two views. `questions` is what a reader sees — the model's and the demoted
    claims' included — and the tracked ones' text has to be inside it, or the identity was bought
    by dropping the agenda."""
    from openfactory.onboarding import context as ctx

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")

    proposal = ctx.propose_context(ctx.survey(str(tmp_path)), language="en")

    for q in proposal.tracked:
        assert q.text in proposal.questions


def test_the_closed_set_is_exactly_what_the_survey_can_earn() -> None:
    """A code with no derivation behind it is a question nothing can ask and nothing can close; a
    derivation with no code is a question nothing can track. The set is CLOSED so those two stay
    equal — unlike the concept taxonomy, which is open because it describes a client's system
    rather than what this code can see.

    ASSERTED BY DERIVING, NOT BY GREPPING THE SOURCE. The first version searched
    `inspect.getsource` for each code and failed on all six: the function names the CONSTANTS
    (`BLIND_MODULES`), never their values. A guard that cannot see the thing it guards is the
    trap this codebase has paid for from the other direction — a comment containing the string
    it greps for."""
    from openfactory.onboarding import context as ctx
    from openfactory.onboarding.context import RepoSurvey, SurveyedModule, UnreadExtension

    everything = RepoSurvey(
        repo="/x",
        modules=[SurveyedModule(name="pkg", path="pkg", purpose="pkg",
                                purpose_is_folder_name=True, files=3)],
        module_count=1,
        untested_modules=["pkg"],
        unread_code_extensions=[".java"],
        unread_extensions=[UnreadExtension(suffix=".java", files=9)],
        unreadable_dirs=["vendor/opaque"],
        entry_points=[],
        terms_dropped=["handler"],
    )

    earned = {q.code for q in ctx._survey_questions(everything, ctx._words("en"))}

    assert earned == set(CODES), (
        "a code nothing derives, or a derivation with no code — the two must stay equal")


def test_an_unknown_kind_is_refused_by_the_ledger() -> None:
    """The ledger refuses a kind nobody knows how to close, and says so. That refusal is why
    `CONTEXT` had to be added deliberately, with its closing observation written down."""
    with pytest.raises(ValueError, match="closing observation"):
        open_loop("not-a-kind", REPO, owner="onboarding", ts=TS)


def test_a_survey_closes_nothing_that_is_not_its_own_kind() -> None:
    """A backfill survey knows nothing about a stalled ticket or a failed remedy. Without the kind
    filter it would close a product QUESTION and a tech-lead REMEDY on the same repository, because
    neither `about` is a code the survey earns — every foreign loop looks resolved to it."""
    from openfactory.memory.ledger import REMEDY

    foreign = [open_loop(QUESTION, REPO, owner="product", ts=TS, about="stalled"),
               open_loop(REMEDY, REPO, owner="techlead", ts=TS, about="flaky-test")]
    mine = to_open([_q(BLIND_MODULES)], repo=REPO, waiting=[], ts=TS)

    closed = resolved(foreign + mine, repo=REPO, fresh=[], surveyed=True)

    assert list(closed) == [(CONTEXT, REPO, BLIND_MODULES)], (
        "a survey closed a loop belonging to somebody else")


def test_a_question_the_model_wrote_is_NOT_tracked(tmp_path) -> None:
    """The over-tightened direction, and it is the reason `tracked` is a subset rather than the
    whole list. An LLM's wording drifts between runs, so a loop keyed on it opens fresh every pass
    and chases a person about a question they answered last month — and nothing can re-derive it,
    so nothing can ever close it. The model's questions stay in the document, which is where a
    conversation starts."""
    import json

    from openfactory.onboarding import context as ctx

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "a.py").write_text("def f():\n    return 1\n")

    def _ask(_prompt: str) -> str:
        return "```json\n" + json.dumps({
            "overview": [], "entities": [], "invariants": [], "vocabulary": [],
            "questions": ["why does the settlement window start on a Tuesday?"],
        }) + "\n```"

    proposal = ctx.propose_context(ctx.survey(str(tmp_path)), ask=_ask, language="en")

    assert any("Tuesday" in q for q in proposal.questions), (
        "the model's question must still reach the agenda a person reads")
    assert all(q.code in CODES for q in proposal.tracked)
    assert not any("Tuesday" in q.text for q in proposal.tracked), (
        "a question nothing can re-derive was opened as a loop nothing can close")


# ── the closer has to be reachable, and `test_loops_are_reachable` already says so ───────────────
#
# The ledger's own guard refuses a kind whose closer no live code path calls: "opened and never
# closed is worse than not tracking — the list grows for ever and everyone learns to ignore it."
# Adding CONTEXT failed that guard until `carry` was wired into `_backfill`, which is the honest
# order: the kind is only allowed to exist because something closes it.

def test_carry_closes_and_opens_in_one_pass() -> None:
    """One pass over a repository: the gap that closed is recorded as closed, the one still there
    is left alone, and the one newly earned is opened."""
    from openfactory.onboarding.questions import carry

    ledger = to_open([_q(BLIND_MODULES), _q(UNREAD_CODE)], repo=REPO, waiting=[], ts=TS)

    rows = carry(REPO, ledger=ledger,
                 fresh=[_q(UNREAD_CODE), _q(UNTESTED_MODULES)], surveyed=True, ts="t2")

    closed = [(r.about, r.outcome) for r in rows if r.outcome]
    opened = [r.about for r in rows if not r.outcome]
    assert closed == [(BLIND_MODULES, GAP_CLOSED)]
    assert opened == [UNTESTED_MODULES], "unread-code was already open and is not re-opened"


def test_carry_touches_no_loop_that_is_not_its_own() -> None:
    """A backfill survey knows nothing about a stalled ticket or a failed remedy — and every
    foreign `about` looks resolved to a closer that asks "does the survey still earn this?"."""
    from openfactory.memory.ledger import REMEDY
    from openfactory.onboarding.questions import carry

    # ONE OF THESE COLLIDES WITH A CODE ON PURPOSE. `resolved` filters by kind on its own, so a
    # foreign loop with an unrelated `about` is safe either way and the fixture would not reach the
    # cut — the mutation survived exactly that. A product question that happens to be ABOUT
    # `blind-modules` is what `carry`'s own filter is for: without it, `to_open` sees it as already
    # open and the context question is never asked at all.
    foreign = [open_loop(QUESTION, REPO, owner="product", ts=TS, about="stalled"),
               open_loop(QUESTION, REPO, owner="product", ts=TS, about=BLIND_MODULES),
               open_loop(REMEDY, REPO, owner="techlead", ts=TS, about="flaky-test")]

    rows = carry(REPO, ledger=foreign, fresh=[_q(BLIND_MODULES)], surveyed=True, ts="t2")

    assert [(r.kind, r.about) for r in rows] == [(CONTEXT, BLIND_MODULES)], (
        "a survey closed somebody else's loop, or let one suppress its own question")


def test_carry_on_a_survey_that_could_not_run_closes_nothing() -> None:
    """The guard, at the layer the caller actually uses. `_backfill` passes `surveyed` explicitly
    rather than inferring it from an empty list, because only the caller knows which happened."""
    from openfactory.onboarding.questions import carry

    ledger = to_open([_q(c) for c in CODES], repo=REPO, waiting=[], ts=TS)

    assert carry(REPO, ledger=ledger, fresh=[], surveyed=False, ts="t2") == []
    assert carry(REPO, ledger=ledger, fresh=[], surveyed=True, ts="t2"), (
        "the fixture must reach the cut — a trusted empty survey closes every one")


def test_the_backfill_actually_carries_them(tmp_path, monkeypatch) -> None:
    """THE WIRING, and the mutation that removed the one call survived without this. Everything
    else here tests `carry` on ledgers built by hand; if `_backfill` never invokes it the questions
    are computed with an identity and then dropped — the same sentences on paper, nothing carried.

    The clone is stubbed to a real little repository so the survey and the proposal run for real:
    what is faked is the network, not the reading."""
    from openfactory.adapters.forge import registry as forge_registry
    from openfactory.credentials import __name__ as creds
    from openfactory.onboarding import onboard as ob
    from openfactory.onboarding import propose_manifest as pm
    from openfactory.onboarding import questions as q

    source = tmp_path / "src"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg" / "__init__.py").write_text("")
    (source / "pkg" / "a.py").write_text("def f():\n    return 1\n")
    docs = tmp_path / "docs"
    docs.mkdir()

    monkeypatch.setattr(forge_registry, "repo_of", lambda p: REPO)
    monkeypatch.setattr(forge_registry, "clone_url_for", lambda p, r, token=None: "u")
    monkeypatch.setattr(f"{creds}.forge_token_for", lambda p: "t")
    monkeypatch.setattr(f"{creds}.deployment_forge_token", lambda p: "t")
    monkeypatch.setattr(pm, "clone_for_proposal", lambda **kw: (source, ""))

    seen: dict = {}
    real = q.carry
    monkeypatch.setattr(q, "carry",
                        lambda repo, **kw: seen.update(repo=repo, **kw) or real(repo, **kw))
    monkeypatch.setattr("openfactory.memory.store.read", lambda project, **kw: [])
    written: list = []
    monkeypatch.setattr("openfactory.memory.store.write",
                        lambda project, loops, **kw: written.extend(loops) or len(loops))

    project = type("_P", (), {"name": "acme", "language": "en", "harness": {"techlead": "codex"}})()
    ob._backfill(project, docs, stream=None)

    assert seen.get("repo") == REPO, "the backfill never carried its questions"
    assert seen.get("surveyed") is True, "a survey that DID run must be reported as one"
    assert written, "the loops were computed and never written"
    assert all(r.kind == CONTEXT for r in written)
