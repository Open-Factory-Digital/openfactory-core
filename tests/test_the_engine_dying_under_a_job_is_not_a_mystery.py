"""A worker dying under a job is a class the platform knows, not a mystery for a human (#159).

MEASURED ON THE PILOT. A rebuild SIGTERMed the worker fifteen seconds after #103 reached
`implementing`; the activity heartbeat timed out; the channel said:

    I need you: I could not identify the cause, so I will not try again blindly.
    Reply `resume` and I will try again once you have adjusted it, or `skip` to free the queue.

Adjust WHAT? Minutes later the tech-lead's own diagnosis identified the cause precisely — clean
working tree, orchestration-level timeout, "Resume the job — there's nothing in the repo to fix
first" — and then told the operator to reply in a channel this deployment does not have, with a
command the panel chat could not execute. The operator's verdict, translated because it is the spec: "this TL is useless... can't it
interact with what was built, understand it and adjust? what is it for, then?"

Four fixes, four sections: the class is CLASSIFIED (self-heal reaches it), the classification is
REPLAY-SAFE (a job parked under the old verdict must replay the old verdict), the dictated command
is EXECUTABLE on the reference surface, and the diagnosis names no channel.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from openfactory.techlead.classify import TRANSIENT, UNKNOWN, classify, remedy_for

NOTE = "job errored after retries: ActivityError: Activity task timed out"


# ── 1. the class is known ────────────────────────────────────────────────────────────────────────

def test_the_pilots_exact_note_is_TRANSIENT_not_unknown():
    got = classify(NOTE)
    assert got.cause == TRANSIENT, f"still a mystery: {got}"
    assert got.detail == "engine-interrupted"


@pytest.mark.parametrize("note", [
    "ActivityError: Activity task timed out",
    "activity Heartbeat timed out",
    "heartbeat timeout after worker restart",
])
def test_the_engine_death_shapes_are_recognised(note):
    assert classify(note).cause == TRANSIENT


@pytest.mark.parametrize("note,expected", [
    ("bad credentials for the forge", "credential"),
    ("setup: npm install exited 1", "project"),
    ("ticket too large to size", "requirement"),
    ("", UNKNOWN),
])
def test_and_the_rule_did_not_swallow_its_neighbours(note, expected):
    assert classify(note).cause == expected


def test_the_remedy_is_ONE_retry_then_a_person():
    """A dev's move exactly: retry once — nothing is wrong with the ticket or the code — and if it
    dies again, that is not transient any more and a person should hear about it."""
    first = remedy_for(classify(NOTE), already_tried=0)
    assert first.action == "retry"
    assert first.wait_seconds > 0
    assert "machine under the job" in first.say or "engine" in first.say.lower(), first.say

    later = remedy_for(classify(NOTE), already_tried=99)
    assert later.action == "escalate", "it would retry a recurring death for ever"


def test_the_sentence_exists_in_both_catalogued_languages():
    from openfactory.techlead import voice

    for lang, must in (("en", "worker restart"), ("pt-BR", "restart do worker")):
        line = voice.say(voice.DETAIL, "engine-interrupted", lang)
        assert must in line, f"{lang}: {line}"


# ── 2. replay safety — the gate is the fix's own load-bearing wall ──────────────────────────────

def test_the_engine_rule_can_be_SWITCHED_OFF_for_replay():
    """#103 is parked in a workflow whose history says UNKNOWN → escalate. A worker restart
    replays that classify call; a different verdict there is a different command sequence, which
    is TMPRL1100 — the exact failure the `workflow-changes-need-patched` rule exists for, arriving
    through a PURE function because its value drives commands."""
    got = classify(NOTE, engine=False)
    assert got.cause == UNKNOWN, "the gate is decorative — an in-flight parked job would wedge"


def test_the_workflow_passes_the_gate_from_patched():
    import openfactory.runtime.temporal.workflow as temporal_workflow

    src = inspect.getsource(temporal_workflow)
    call = next((n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "classify"), None)
    assert call is not None, "the workflow no longer classifies parks — this guard measures nothing"
    engine = next((k.value for k in call.keywords if k.arg == "engine"), None)
    assert engine is not None, (
        "the workflow classifies with the DEFAULT engine rules — a job parked under the old "
        "verdict replays into a different command sequence (TMPRL1100)")
    assert "patched" in ast.unparse(engine), (
        f"`engine` comes from {ast.unparse(engine)!r}, not from workflow.patched(...)")


# ── 3. the dictated command works where it is read ───────────────────────────────────────────────

@pytest.mark.parametrize("said,intent,ref", [
    ("resume #103", "resume", "103"),
    ("retoma o 103", "resume", "103"),
    ("skip #103", "skip", "103"),
    ("pula o #103", "skip", "103"),
])
def test_the_diagnosis_dictated_reply_is_executable(said, intent, ref):
    from openfactory.actions.floor_intents import match_floor_intent

    got = match_floor_intent(said)
    assert got and got[0] == intent and got[1].get("ref", "").lstrip("#") == ref, (
        f"{said!r} → {got!r}: the platform dictates a command its own chat cannot run (#68/#120)")


@pytest.mark.parametrize("prose", [
    "resume",                                     # the ref is REQUIRED — a bare noun is not an order
    "o resume dele é bom",
    "we could resume tomorrow later",
    "resume #103 was suggested by the tech-lead earlier",
    "vai pular o 103?",
    "não pula o 103",
])
def test_and_prose_about_resuming_still_reaches_nobody(prose):
    from openfactory.actions.floor_intents import match_floor_intent

    assert match_floor_intent(prose) is None, f"{prose!r} would act on a parked job"


@pytest.mark.parametrize("said,row", [
    ("resume #103", "resume"),
    ("skip #103", "skip"),
    ("stop #103", "stop"),
])
async def test_the_chat_performs_the_ROW_the_word_names(said, row, monkeypatch):
    """BEHAVIOURAL, because the source-reading version of this guard was fooled: a mutation
    hard-coding `perform("stop", ...)` survived while `FLOOR_ROWS[intent]` still appeared one
    line down in the echo dict. Typing `resume` and getting a TERMINATED job is the worst
    possible reading of this branch, so the claim is driven, not read."""
    import openfactory.actions as actions
    from openfactory.actions import catalog

    performed: list[str] = []

    async def _spy(name, *, by, **params):
        performed.append(name)
        return catalog.done("ok", **params)

    monkeypatch.setattr(actions, "perform", _spy)
    out = await catalog._floor_say_as_an_intent(said, project="demo", by=actions.SYSTEM)

    assert performed == [row], (
        f"typed {said!r} and the chat performed {performed} — the word and the row disagree")
    assert out is not None and out.data.get("issue") == "103"


# ── 4. the diagnosis names no channel ────────────────────────────────────────────────────────────

def test_the_handoff_renderers_name_no_vendor_channel():
    """"Reply `resume #103` in Slack" — on a deployment with no Slack. The reader is reading the
    sentence SOMEWHERE; wherever that is, is where they reply (ADR-0038: the panel is the
    reference surface, channels are add-ons)."""
    from openfactory.contracts import decision

    ho = decision.HandOff(headline="h", what_happened="w", why="y", correction="c",
                          recommendation="r", alternatives="a", suggested_command="resume #103")
    # ON THE RENDERED OUTPUT, not the source — the source-scan version of this guard tripped on a
    # docstring ABOUT vendors converting in their adapters, which is the strip-the-prose lesson
    # again; and the output is what a reader actually receives.
    for rendered in (decision.handoff_to_markdown(ho), decision.handoff_to_plain(ho)):
        assert "Slack" not in rendered, "the reader is sent to one vendor's channel"
        assert "resume #103" in rendered, "the executable reply was lost with the vendor's name"
    assert "Pra eu resolver" not in decision.handoff_to_plain(ho), (
        "the plain scaffold is hardcoded Portuguese — shipped to every deployment in any language")


def test_the_unknown_park_no_longer_claims_ignorance_the_diagnosis_disproves():
    """The channel said "I could not identify the cause" while the diagnosis — produced by the
    same platform, minutes later — identified it precisely. The line now promises the diagnosis
    instead of contradicting it."""
    from openfactory.techlead import voice

    for lang in ("en", "pt-BR"):
        line = voice.say(voice.REMEDY, "why.unknown", lang)
        assert "diagn" in line.lower(), f"{lang}: {line!r} still ends the conversation"
