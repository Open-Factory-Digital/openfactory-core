"""A human who decided in words has decided (#120, pilot 2026-08-15).

With `#87`'s PR open and the panel showing `View PR · Merge · Adjust… · Discard`, the pilot typed
into the tech-lead chat:

    pode fazer o merge

and was told *"I can't merge from here — a merge is a human action, outside what I execute."*
Half right, and the wrong half is the expensive one: `merge_policy: human` makes the DECISION a
human's, and the EXECUTION has always been the catalogue's — the button beside that chat posts to
the very row the chat refused to reach.

The two properties this is held to are in tension, which is why both are asserted here:

  * a typed instruction reaches the row, WITH the gate — through `perform`, with the actor that
    came through the door, so a credential that cannot press the button cannot type past it;
  * a QUESTION is never an instruction, and neither is a sentence about merging. A miss costs a
    rephrase; a false positive lands a pull request in somebody's main branch.
"""

from __future__ import annotations

import pytest

from openfactory.actions.floor_intents import match_floor_intent

# ── 1. the matcher: what instructs, and what only talks about it ────────────────────────────────

@pytest.mark.parametrize("said,intent", [
    ("pode fazer o merge", "merge"),
    ("faz o merge", "merge"),
    ("manda o merge", "merge"),
    ("merge", "merge"),                       # the word on the button is an instruction
    ("mergeia", "merge"),
    ("merge it", "merge"),
    ("ship it", "merge"),
    ("descarta esse", "discard"),
    ("discard", "discard"),
    ("ajusta: usa a data local em vez do relógio", "adjust"),
])
def test_an_instruction_is_read_as_one(said, intent):
    matched = match_floor_intent(said)
    assert matched and matched[0] == intent, f"{said!r} did not read as {intent}"


@pytest.mark.parametrize("said", [
    "posso fazer o merge?",
    "o que acontece se eu mergear?",
    "vale a pena mergear agora?",
    "esse PR está pronto para merge?",
    # ABOUT merging rather than an order to merge — no question mark to save us
    "quero mudar o merge policy para auto",
    "o merge_policy pode ser auto?",
    "deu merge conflict aqui",
    "qual a merge strategy do repo",
    # not about the floor at all
    "como está o podbeam?",
    "quantos testes rodaram",
    "ajusta",                                  # an instruction nobody could carry out
])
def test_a_question_or_a_conversation_is_never_an_instruction(said):
    assert match_floor_intent(said) is None, (
        f"{said!r} would have acted — a false positive here lands a pull request")


def test_a_question_followed_by_an_instruction_still_instructs():
    """The CLAUSE decides, not the message — the rule the product matcher pays for by name."""
    assert match_floor_intent("vale a pena? descarta esse")[0] == "discard"


# ── 1b. negation and narration — the sweep's B1 (2026-08-16) ────────────────────────────────────
#
# EVERY SENTENCE IN THE FIRST LIST USED TO MATCH `('merge', {})`, probe-proven — and with one PR
# waiting, the router took `waiting[0]` and merged it. "não faça o merge" merging the PR is the
# human gate inverted by the exact sentence that exercises it; a false positive here is the
# mistake the module's own docstring prices as "lands a pull request in somebody's main branch".

@pytest.mark.parametrize("said", [
    "não faça o merge",
    "nao faz o merge ainda",
    "do not merge yet",
    "don't merge",
    "nunca faça o merge disso",
    "segura o merge",
    "espera, não mergeia",
    "hold the merge",
    "não descarta",                            # negation guards every intent, not just merge
])
def test_a_negated_or_held_order_is_the_OPPOSITE_order(said):
    assert match_floor_intent(said) is None, (
        f"{said!r} would have acted — a negated instruction executing is the gate inverted")


@pytest.mark.parametrize("said", [
    "o merge falhou ontem",                    # narration of a past event
    "o merge de ontem demorou demais",
    "the merge broke staging last night",
])
def test_a_sentence_that_MENTIONS_merging_is_not_an_order_to_do_it_again(said):
    assert match_floor_intent(said) is None, (
        f"{said!r} is a report, and it would have been executed as an instruction")


def test_a_clause_before_the_order_does_not_poison_it():
    """The boundary of the negation guard: the clause decides. "a espera acabou" contains a
    hold-verb and is a different clause from the order that follows it."""
    assert match_floor_intent("a espera acabou, faz o merge")[0] == "merge"


# ── 1c. the ref the sentence names ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("said,intent,ref", [
    ("merge #87", "merge", "87"),
    ("merge 90", "merge", "90"),
    ("faz o merge do #90", "merge", "90"),
    ("descarta o CONT-412", "discard", "CONT-412"),   # the provider's ref, never assumed numeric
    ("ajusta #87: o botão na direita", "adjust", "87"),
])
def test_the_ref_the_sentence_names_is_captured(said, intent, ref):
    matched = match_floor_intent(said)
    assert matched and matched[0] == intent
    assert matched[1].get("ref") == ref, (
        f"{said!r} names {ref} and the matcher dropped it — the router would act on whatever "
        f"happened to be waiting")


def test_merge_it_does_not_read_it_as_a_ticket():
    matched = match_floor_intent("merge it")
    assert matched and matched[1].get("ref") is None


# ── 2. the routing: the same row, through the same gate ─────────────────────────────────────────

@pytest.fixture
def floor(monkeypatch):
    """One job waiting at the merge gate, and a `perform` that records instead of acting."""
    from openfactory import actions
    from openfactory.actions import catalog

    performed: list[dict] = []

    async def _waiting(project):
        return [{"issue": "87", "pr_url": "https://github.com/o/r/pull/88"}]

    async def _perform(row, *, by, **params):
        performed.append({"row": row, "by": by, **params})
        from openfactory.actions.base import done

        return done(f"{row} performed")

    monkeypatch.setattr(catalog, "_waiting_on_a_human", _waiting)
    monkeypatch.setattr(actions, "perform", _perform)
    return performed


@pytest.mark.asyncio
async def test_a_typed_merge_performs_the_row_the_button_performs(floor):
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor

    by = Actor(id="operator-1", admin=True)
    out = await catalog._floor_say_as_an_intent("pode fazer o merge", project="podbeam", by=by)

    assert out is not None and out.ok
    assert floor == [{"row": "merge", "by": by, "project": "podbeam", "issue": "87"}], (
        "the sentence did not reach the same row the panel's Merge button posts to")
    assert out.data.get("read_as") == "merge", "the answer does not say how it was read"


@pytest.mark.asyncio
async def test_the_gate_is_the_row_s_own_and_is_never_bypassed(floor):
    """THE SECURITY PROPERTY. `ask` is deliberately NOT admin-gated — it reads and answers. So the
    instruction must go through `perform`, which applies the scope and the admin check to the SAME
    actor; hand-rolling the dispatch here would be a second authorization surface."""
    import inspect

    from openfactory.actions import catalog

    src = inspect.getsource(catalog._floor_say_as_an_intent)
    assert "actions.perform(" in src, "the row is called directly — the gate is bypassed"
    assert "by=by" in src, "the performing actor is not the one that came through the door"
    for row in ("_merge(", "_discard(", "_adjust("):
        assert row not in src, f"{row} is invoked directly rather than through the catalogue"


@pytest.mark.asyncio
async def test_an_ambiguous_floor_asks_which_rather_than_choosing(monkeypatch):
    """Two jobs waiting is the case where being helpful is dangerous: merging the wrong pull
    request is not something a rephrase undoes."""
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor

    async def _two(project):
        return [{"issue": "87", "pr_url": ""}, {"issue": "91", "pr_url": ""}]

    monkeypatch.setattr(catalog, "_waiting_on_a_human", _two)
    out = await catalog._floor_say_as_an_intent("merge", project="podbeam",
                                                by=Actor(id="operator-1", admin=True))
    assert out is not None and not out.ok
    assert "#87" in out.message and "#91" in out.message


@pytest.mark.asyncio
async def test_the_refusals_dictated_reply_actually_works(floor, monkeypatch):
    """THE ROUND TRIP, and the sweep found it broken: with two PRs waiting the refusal said
    *'say which one, e.g. "merge #87"'* — and the matcher then threw the ref away, so the dictated
    reply re-entered the same refusal, for ever. A message that tells somebody what to type is
    accountable for that sentence parsing."""
    import re

    from openfactory.actions import catalog
    from openfactory.actions.base import Actor

    by = Actor(id="operator-1", admin=True)

    async def _two(project):
        return [{"issue": "87", "pr_url": ""}, {"issue": "91", "pr_url": ""}]

    monkeypatch.setattr(catalog, "_waiting_on_a_human", _two)
    refusal = await catalog._floor_say_as_an_intent("merge", project="podbeam", by=by)
    dictated = re.search(r'"([^"]+)"', refusal.message).group(1)   # what it told them to type

    out = await catalog._floor_say_as_an_intent(dictated, project="podbeam", by=by)
    assert out is not None and out.ok, (
        f"the refusal dictated {dictated!r} and typing it back produced {out and out.message!r} — "
        f"an instruction loop with no exit")
    assert out.data["issue"] == "87"


@pytest.mark.asyncio
async def test_a_NAMED_ref_is_binding_never_a_suggestion(monkeypatch):
    """"merge #90" with only #87 waiting must refuse naming what IS waiting — acting on a
    different job than the one named is worse than refusing."""
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor

    performed: list[str] = []

    async def _one(project):
        return [{"issue": "87", "pr_url": ""}]

    async def _perform(row, *, by, **params):
        performed.append(params.get("issue"))
        from openfactory.actions.base import done

        return done("ok")

    monkeypatch.setattr(catalog, "_waiting_on_a_human", _one)
    from openfactory import actions

    monkeypatch.setattr(actions, "perform", _perform)
    by = Actor(id="operator-1", admin=True)

    out = await catalog._floor_say_as_an_intent("merge #90", project="podbeam", by=by)
    assert out is not None and not out.ok and performed == [], (
        "the operator named #90 and something else was merged in its name")
    assert "#90" in out.message and "#87" in out.message, (
        "the refusal neither echoes what was asked nor names what is actually waiting")

    ok = await catalog._floor_say_as_an_intent("merge #87", project="podbeam", by=by)
    assert ok is not None and ok.ok and performed == ["87"]


@pytest.mark.asyncio
async def test_with_nothing_waiting_the_tech_lead_answers_instead(monkeypatch):
    """None hands the sentence back to the conversation — the rule `_run_intent` states for
    itself: a shrug from a matcher is worse than an answer that turns out to be about something
    else. The tech-lead can then say WHY nothing is waiting."""
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor

    async def _none(project):
        return []

    monkeypatch.setattr(catalog, "_waiting_on_a_human", _none)
    assert await catalog._floor_say_as_an_intent(
        "merge", project="podbeam", by=Actor(id="operator-1", admin=True)) is None


# ── 3. the floor read ITSELF, which is where the feature actually died ──────────────────────────
#
# EVERY TEST ABOVE MONKEYPATCHES `_waiting_on_a_human`, AND THAT IS HOW A DEAD FEATURE SHIPPED
# GREEN. The pilot rebuilt, typed "pode fazer o merge" at a pull request sitting on the gate, and
# got the tech-lead's prose again. The function these tests replace with a stub called
# `namespace()` — which at module scope in `catalog.py` is `openfactory.namespace`, the paths
# MODULE — so every call raised `TypeError`, the function's own `except` returned "nothing is
# waiting", and the routing above was never reached. Twenty-seven assertions covered the sentence,
# the gate and the ordering; not one of them ran the line that decides whether there is anything to
# merge.
#
# So these three stub the ENGINE and nothing else: the real body runs.

@pytest.fixture
def engine(monkeypatch):
    """A connected client whose `list_jobs` answers with whatever the test puts on the floor."""
    from openfactory.actions import catalog
    from openfactory.runtime.temporal import view as tv

    rows: list[dict] = []

    async def _connected():
        return object(), None

    async def _list_jobs(client, ns, **kw):
        assert isinstance(ns, str), (
            f"the Temporal namespace reached the engine as {type(ns).__name__} — "
            f"a module is not a namespace, and it is not callable either")
        return list(rows)

    monkeypatch.setattr(catalog, "_connected", _connected)
    monkeypatch.setattr(tv, "list_jobs", _list_jobs)
    return rows


@pytest.mark.asyncio
async def test_the_floor_read_finds_the_job_the_panel_puts_a_merge_button_on(engine):
    from openfactory.actions import catalog
    from openfactory.runtime.temporal import view as tv

    engine += [
        {"project": "podbeam", "issue": "87", "state": "awaiting_your_merge",
         "action": {"kind": tv.MERGE_WAIT, "pr_url": "https://github.com/o/r/pull/88"}},
        {"project": "podbeam", "issue": "60", "state": "running", "action": None},
        {"project": "outra", "issue": "12", "action": {"kind": tv.MERGE_WAIT, "pr_url": "x"}},
    ]
    assert await catalog._waiting_on_a_human("podbeam") == [
        {"issue": "87", "pr_url": "https://github.com/o/r/pull/88"}], (
        "the read that decides whether a typed merge has anything to act on did not find a job "
        "the panel is showing a Merge button for")


@pytest.mark.asyncio
async def test_a_floor_nobody_could_read_is_not_a_floor_with_nothing_on_it(engine, monkeypatch):
    """THE DISTINCTION THIS COST US. `[]` and a failed read used to be the same value, and the
    failed read is the one that must never pass for an answer."""
    from openfactory.actions import catalog
    from openfactory.runtime.temporal import view as tv

    assert await catalog._waiting_on_a_human("podbeam") == []  # genuinely empty

    async def _explode(client, ns, **kw):
        raise RuntimeError("the engine hung up")

    monkeypatch.setattr(tv, "list_jobs", _explode)
    assert await catalog._waiting_on_a_human("podbeam") is None, (
        "an unreadable floor is being reported as an empty one — the shape that swallowed a merge")


@pytest.mark.asyncio
async def test_an_unreadable_floor_says_so_instead_of_changing_the_subject(monkeypatch):
    """The instruction is not swallowed. Handing it to the tech-lead produces an answer about what
    a tech-lead does and does not do, which reads as a refusal of the request rather than as what
    it is — and the button that still works goes unmentioned."""
    from openfactory.actions import catalog
    from openfactory.actions.base import UNAVAILABLE, Actor

    async def _blind(project):
        return None

    monkeypatch.setattr(catalog, "_waiting_on_a_human", _blind)
    out = await catalog._floor_say_as_an_intent("pode fazer o merge", project="podbeam",
                                                by=Actor(id="operator-1", admin=True))
    assert out is not None and not out.ok and out.code == UNAVAILABLE
    assert "merge" in out.message.lower() and "button" in out.message.lower(), (
        "the refusal does not name the surface that would still work")


def test_the_button_and_the_sentence_read_ONE_definition_of_waiting():
    """A second spelling of `merge_wait` would not raise — it would quietly mean "nothing is
    waiting", which is a sentence both surfaces are willing to say."""
    import inspect
    import pathlib

    from openfactory.actions import catalog
    from openfactory.runtime.temporal import view as tv

    panel = (pathlib.Path(__file__).resolve().parents[1]
             / "openfactory" / "api" / "panel.html").read_text()
    assert f'"{tv.MERGE_WAIT}"' in panel or f"'{tv.MERGE_WAIT}'" in panel, (
        "the panel decides which job gets a Merge button by a different string than the engine "
        "writes")
    src = inspect.getsource(catalog._waiting_on_a_human)
    assert "MERGE_WAIT" in src and f'"{tv.MERGE_WAIT}"' not in src, (
        "the chat re-spells the gate's name instead of importing it")


@pytest.mark.asyncio
async def test_the_chat_row_routes_before_it_spends_an_agent_pass(floor, monkeypatch):
    """An instruction must not cost a tech-lead invocation to be refused afterwards — and the
    order is what makes the answer to "pode fazer o merge" a merge rather than an opinion."""
    import inspect

    from openfactory.actions import catalog

    src = inspect.getsource(catalog._ask)
    assert src.index("_floor_say_as_an_intent") < src.index("AskWorkflow"), (
        "the agent is asked first, so a typed instruction spends a pass and still does nothing")


# ── 4. a verb inside prose is not an order (#152, measured on the pilot) ────────────────────────
#
# The operator pasted a 586-character review instruction into the tech-lead chat. It contained the
# words "a real type fix" near the end. That fired `adjust`, whose `(?P<instruction>.+)` captured
# the twenty-six characters that happened to follow — and the platform spent a full agent pass on
# them, in 150ms, with no agent and no confirmation. He had pasted a MESSAGE, and it was executed
# as a COMMAND with a parameter cut out of the middle of his own sentence.
#
# Sweeping the other rows found the same shape everywhere, which is why this section is not about
# `adjust`: `discard` CLOSES a pull request and `stop` TERMINATES a run.

@pytest.mark.parametrize("prose", [
    # the exact tail of the pilot's paste, and the shape of it
    "Also remove the # type: ignore suppressions, or replace each with a real type fix — "
    "do not silence the gate.",
    "I think the review is right — the fix is incomplete",
    # A DETERMINER IS NOT POLITENESS. These sit at the head of their clause, so only the leader
    # list keeps them out — and a mutation that let `the` in passed every other case in this file.
    "the fix is incomplete",
    "o rework ficou pela metade",
    "can you look at the fix for the rounding?",
    "the CI fix landed yesterday, no action needed",
    "we should rework this later, not now",
    # a ticket title quoted back. EVERY ticket in this product is named `fix(scope): …`, so this
    # is what an operator types when saying WHICH job they mean.
    "fix(generation): episodes run short of their style target",
    # discard closes a pull request
    "the discard button is confusing",
    "I would drop it if the review were worse",
    "descartar seria um desperdício",
    # stop terminates a run — and this one QUOTES the command the tech-lead itself dictates
    "stop #101 was suggested by the tech-lead earlier",
    "o merge falhou ontem",
])
def test_a_sentence_that_MENTIONS_a_verb_is_not_a_command(prose):
    got = match_floor_intent(prose)
    assert got is None, (
        f"this would have been performed as {got[0]!r} with {got[1]!r} — a false positive here "
        f"spends an agent pass, closes a pull request or kills a run")


@pytest.mark.parametrize("order,intent", [
    ("ajusta: o botão deve ficar à direita", "adjust"),
    ("corrige o teste do caso vazio", "adjust"),
    ("please fix the rounding", "adjust"),
    ("ok, adjust #101: add a test", "adjust"),
    ("e corrige o alinhamento", "adjust"),
    ("pode fazer o merge", "merge"),
    ("merge #87", "merge"),
    ("ok, merge", "merge"),
    ("descarta #87", "discard"),
    ("vale a pena mergear? descarta esse", "discard"),   # the docstring's own case
    ("stop #101", "stop"),
])
def test_and_the_orders_STILL_reach_their_row(order, intent):
    """The twin, and the one that decides whether the fix is worth having. A matcher that refuses
    everything passes the block above and makes the chat useless — which is the state #120 was
    filed to end."""
    got = match_floor_intent(order)
    assert got and got[0] == intent, f"{order!r} no longer instructs (got {got!r})"


def test_the_instruction_a_command_carries_is_the_words_AFTER_it_and_all_of_them():
    """The second half of the pilot's defect. Even a correctly-matched `adjust` was carrying a
    fragment: whatever followed the verb, however little of the message that was."""
    got = match_floor_intent("ajusta: persiste o finish_reason por episódio e cobre com um teste")
    assert got and got[0] == "adjust"
    assert got[1]["instruction"] == "persiste o finish_reason por episódio e cobre com um teste"


# ── 5. the polite forms are the common ones (#153) ──────────────────────────────────────────────
#
# With the merge gate on screen the pilot typed `pode dar o merge` — a decision made in words —
# and it fell through to the tech-lead, which answered with an opinion. That IS #120, surviving in
# a verb nobody had listed: the pattern knew `pode FAZER o merge` and stopped there.

@pytest.mark.parametrize("said", [
    "pode dar o merge",
    "pode dar merge",
    "pode mandar o merge",
    "dá o merge",
    "manda o merge",
    "please merge",          # the word on the button, politely — `_BARE` allowed only "ok,"
    "e merge",
    "por favor, descarta #87",
])
def test_a_decision_said_politely_is_still_a_decision(said):
    got = match_floor_intent(said)
    assert got, f"{said!r} reached the tech-lead as conversation, with the button right beside it"


@pytest.mark.parametrize("said", [
    "vale a pena dar o merge?",     # the same verb, asking
    "o merge falhou ontem",
    "não faça o merge ainda",
])
def test_and_widening_the_verbs_did_not_widen_the_MISTAKES(said):
    assert match_floor_intent(said) is None, f"{said!r} would now be performed"


def test_the_politeness_list_has_ONE_home():
    """`_BARE` carried its own hand-written `ok,` prefix while `_LEADERS` carried the real list —
    two spellings of the same idea, which is how `please merge` ended up conversation."""
    import inspect as _inspect
    import re as _re

    from openfactory.actions import floor_intents as fi

    src = _inspect.getsource(fi)
    body = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert body.count("_LEADER_WORDS") >= 2, "the leader list is not shared"
    assert not _re.search(r"ok\[,\.!\]\?", body), (
        "a second, narrower politeness prefix is spelled out beside the shared one")


# ── 6. the matcher is handed arbitrary text, so it must ANSWER ──────────────────────────────────

def test_no_sentence_can_make_the_matcher_stop_answering():
    """A prefix loop written with `\\s*` at BOTH ends lets a run of spaces be eaten by the tail of
    one iteration or the head of the next — two ways per space, 2^n paths, and the engine walks all
    of them before it can report failure. Every typed message on the panel goes through here, so
    that is a denial of service on a web-facing path, in a file whose whole job is to be handed
    arbitrary text.

    IN A SUBPROCESS, AND THAT IS THE POINT. The obvious guard — call it, then assert on elapsed
    time — CANNOT FAIL: a call that never returns never reaches the assertion, so it hangs the
    suite instead of failing it. `signal.alarm` does not help either, because CPython's `re` never
    checks for signals while it is matching. Only a process this test can KILL can observe the
    defect, and the two versions before this one hung `pytest` for twelve minutes apiece."""
    import pathlib as _pathlib
    import subprocess
    import sys
    import textwrap

    probe = textwrap.dedent("""
        from openfactory.actions.floor_intents import match_floor_intent
        for hostile in ("e " * 2000 + "merge", "ok, " * 2000, "please " * 2000 + "x",
                        " " * 4000 + "merge", "fix " * 2000, "descarta " * 2000):
            match_floor_intent(hostile)
        print("answered")
    """)
    root = _pathlib.Path(__file__).resolve().parents[1]
    try:
        done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                              timeout=30, cwd=str(root))
    except subprocess.TimeoutExpired:
        raise AssertionError(
            "the matcher never came back on hostile input — a regex that walks its input twice "
            "over, on the path every typed message takes") from None

    assert done.returncode == 0, done.stderr[-600:]
    assert "answered" in done.stdout


# ── 7. politeness leads AND trails (#158) ───────────────────────────────────────────────────────
#
# The pilot typed `vai la da o merge por favor` — as plain an order as the language has — and it
# reached nobody. Two of my own rules refused it: the head rule (#152) counted "vai la" as words
# standing in front of the verb, and the fills-its-clause rule counted "por favor" as a sentence
# carrying on. Both are right about prose and were wrong about courtesy.

@pytest.mark.parametrize("said,intent", [
    ("vai la da o merge por favor", "merge"),
    ("vai lá dá o merge", "merge"),
    ("go ahead and merge", "merge"),
    ("pode descartar #87", "discard"),
    ("pode fazer o merge, obrigado", "merge"),
    ("por favor, descarta #87", "discard"),
])
def test_courtesy_on_either_side_of_the_verb_is_still_an_order(said, intent):
    got = match_floor_intent(said)
    assert got and got[0] == intent, f"{said!r} reached nobody (got {got!r})"


@pytest.mark.parametrize("said", [
    # `vai` ALONE must never be a leader: in Portuguese it is also the future auxiliary, so this
    # is "that will discard everything" — a narration, and the most expensive false positive here.
    "vai descartar tudo",
    "isso vai descartar tudo",
    "vale a pena dar o merge?",
    "stop #101 was suggested by the tech-lead earlier",
    "the CI fix landed yesterday, no action needed",
])
def test_and_the_courtesy_words_did_not_open_a_door_for_prose(said):
    assert match_floor_intent(said) is None, f"{said!r} would now be performed"
