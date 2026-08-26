"""What the factory says FIRST follows the project's language (#124).

The pilot asked how to make his project speak English and the honest answer had two halves. The
setting existed and had no command (fixed, `83fd494`). And the tech-lead's canned voice ignored it
entirely: `classify.py`, `watch.py` and the park announcement were Portuguese string literals with
no language selection anywhere near them, so an English deployment was told, in Portuguese, that it
needed to look at something — on the surface whose whole job is to be understood in an emergency.

THE RULE, as the product owner set it on 2026-08-16:

    a message the project sends FIRST — a park alert, a scheduled round, a remedy, a comment on a
    ticket nobody asked for — is written in the project's configured `language`;

    a REPLY follows the language of the QUESTION. Somebody who writes in English gets English,
    whatever the project is configured for.

He also settled the exception this file pins: a CANNED reply uses the configured language too,
because there is no language detector in this codebase and inventing one to satisfy a rule about
five sentences would be a dependency in a layer that has none. The replies that matter — the
tech-lead's chat and the product role's — are the AGENT's, and the agent sees the question.

AND THE CONVERSION FOUND THE REAL BUG. `Verdict.detail` was ALREADY MIXED — `"throttled"`,
`"network"`, `"the change"` beside `"uma corrida com outra mudança"`, `"uma regra da organização,
funcionando"` — one table, one interpolated sentence. The message a pt-BR operator read was
incoherent whatever the setting said. The defect was never "it is Portuguese"; it was "it is
unselected".
"""

from __future__ import annotations

import ast
import importlib
import inspect

import pytest

from openfactory.techlead import voice
from openfactory.techlead.classify import classify, remedy_for
from openfactory.techlead.watch import AtAGate, FloorState, Parked, report, watch

#: The modules whose canned sentences an OPERATOR reads. Portuguese literals here are the defect;
#: Portuguese in the phrasebook is the product working.
_SPEAKS = ("openfactory.techlead.classify", "openfactory.techlead.watch")

_ACCENTS = "áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ"


def _canned_literals(module: str) -> list[str]:
    """Every string literal that is not a docstring — the shape a canned sentence takes."""
    src = inspect.getsource(importlib.import_module(module))
    tree = ast.parse(src)
    docs = {ast.get_docstring(n) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and not any(d and n.value[:40] in d for d in docs)]


# ── 1. no module speaks a language of its own ───────────────────────────────────────────────────

@pytest.mark.parametrize("module", _SPEAKS)
def test_no_canned_sentence_is_hardcoded_in_ONE_language(module):
    """The defect itself. A literal with an accent in it, outside the phrasebook, is a sentence
    that will reach an English deployment in Portuguese."""
    offenders = [t[:70] for t in _canned_literals(module) if any(c in t for c in _ACCENTS)]
    assert not offenders, (
        f"{module} still carries canned Portuguese — it reaches every deployment whatever their "
        f"`language` says: {offenders}")


def test_the_phrasebook_is_where_the_language_lives():
    """The positive twin: if the accents had simply been deleted rather than moved, the test above
    would pass and the product would have lost its Portuguese."""
    pt = [e["pt-BR"] for table in (voice.DETAIL, voice.REMEDY, voice.FINDING, voice.OUTCOME,
                                   voice.HEADLINE)
          for e in table.values() if "pt-BR" in e]
    assert len(pt) > 25, f"the pt-BR catalogue has only {len(pt)} entries — was it deleted?"
    assert any(any(c in s for c in _ACCENTS) for s in pt)


@pytest.mark.parametrize("table", ["DETAIL", "REMEDY", "FINDING", "OUTCOME", "HEADLINE"])
def test_every_entry_exists_in_BOTH_languages(table):
    """A half-translated catalogue degrades silently to English for the missing key, which reads
    as "somebody chose this" rather than "somebody forgot"."""
    missing = [k for k, e in getattr(voice, table).items() if not {"en", "pt-BR"} <= set(e)]
    assert not missing, f"voice.{table} entries are missing a language: {missing}"


# ── 2. the same event, two languages ────────────────────────────────────────────────────────────

def test_a_remedy_renders_in_the_projects_language():
    v = classify("rate limit exceeded", state="paused")
    assert "passes on its own" in remedy_for(v, language="en").say
    assert "passa sozinho" in remedy_for(v, language="pt-BR").say


def test_a_ROUND_renders_in_the_projects_language():
    state = FloorState(at_a_gate=[AtAGate("87", 14.0, "merge")],
                       parked=[Parked(ticket="42", hours=9, note="decision needed")])
    assert "waiting 14h on you" in report(watch(state, language="en"), language="en")
    assert "esperando vocês há 14h" in report(watch(state, language="pt-BR"), language="pt-BR")


def test_a_language_nobody_translated_reads_as_ENGLISH_not_as_a_crash():
    """This runs on the path that reports the factory is stuck. A KeyError here takes down the
    message about the outage."""
    v = classify("rate limit exceeded", state="paused")
    assert remedy_for(v, language="de").say == remedy_for(v, language="en").say
    assert report(watch(FloorState(at_a_gate=[AtAGate("87", 14.0, "merge")]), language="de"),
                  language="de")


def test_an_unknown_KEY_renders_as_the_key_rather_than_as_silence():
    """Raising takes down the message that was reporting a problem; "" is the silence this
    platform's whole invariant is written against. A reader seeing `park.stuck` knows what to
    report."""
    assert voice.say(voice.FINDING, "park.stuck", "en") == "park.stuck"
    assert voice.say(voice.FINDING, "gate.merge.detail", "en", nothing="x")


# ── 3. the language reaches the places that speak ───────────────────────────────────────────────
#
# These read the CALLS, not the source text. The first cut of this section asserted a substring
# ("language=params.language" appears somewhere) and two mutations walked straight through it,
# because the string occurs twice and deleting one occurrence leaves the other. A guard that a
# real regression survives is worse than no guard: it reports that the property holds.

#: Everything that composes a sentence for an operator. Each must be TOLD which language.
_MUST_BE_TOLD = {"remedy_for", "watch", "report"}


def _speaking_calls(obj):
    """`(name, node, bindings)` for every call in `obj` that composes an operator's sentence."""
    tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(obj)))
    bindings = {t.id: ast.unparse(n.value)
                for n in ast.walk(tree) if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)}
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", "")
            if name in _MUST_BE_TOLD:
                out.append((name, n, bindings))
    return out


def _language_of(node, bindings) -> str | None:
    """What the call was told, resolved through one level of local assignment."""
    for kw in node.keywords:
        if kw.arg == "language":
            expr = ast.unparse(kw.value)
            return bindings.get(expr, expr)
    return None


def test_the_workflow_gets_the_language_as_a_FIELD_not_a_lookup():
    """A park announcement is composed inside the workflow, which may not do IO — and fetching the
    language would be a NEW COMMAND in the sequence, so every job in flight would diverge
    (TMPRL1100). A field with a default deserialises fine on a history that predates it."""
    from openfactory.runtime.temporal.io import JobParams

    assert JobParams(project="p", issue="1").language == "", (
        "a job started before this field existed must still deserialise — a required field, or a "
        "different default, rewrites what a job in flight was started with")

    calls = _speaking_calls(
        importlib.import_module("openfactory.runtime.temporal.workflow").JobWorkflow)
    assert calls, "the workflow composes no operator sentence — this guard measures nothing"
    for name, node, bindings in calls:
        assert _language_of(node, bindings) == "params.language", (
            f"{name}() at line {node.lineno} of the workflow composes a sentence without the "
            f"language the job was started with — that announcement reaches an operator in "
            f"whatever language somebody typed into the source")


def test_the_ROUND_resolves_it_from_the_PROJECT_it_already_holds():
    """The round is an activity, so it MAY read the registry — and must, because it speaks about
    a project it was handed rather than a job it started."""
    calls = _speaking_calls(
        importlib.import_module("openfactory.runtime.temporal.activities").techlead_watch)
    assert calls, "the round composes no operator sentence — this guard measures nothing"
    for name, node, bindings in calls:
        told = _language_of(node, bindings)
        assert told and "project" in told and "language" in told, (
            f"{name}() at line {node.lineno} of the round is told {told!r} — a language that does "
            f"not come from the project is a constant, and the setting stops meaning anything")


def test_start_jobs_fills_it_from_the_registry():
    """The one place that may look it up for a JOB: an activity, which may read a registry."""
    src = inspect.getsource(
        importlib.import_module("openfactory.runtime.temporal.activities").start_jobs)
    assert "language=" in src, "a job is started without the language its project speaks"


# ── 4. a REPLY is not governed by this ──────────────────────────────────────────────────────────

def test_the_agents_still_follow_whoever_asked():
    """The other half of the rule, and the one this card must not break: the harness instruction
    chooses a default for unprompted speech and defers to the incoming language on a reply."""
    from openfactory.adapters.agent.roles import language_directive

    directive = language_directive("pt-BR").lower()
    assert "pt-br" in directive
    assert "repl" in directive or "answer" in directive, (
        "the harness no longer distinguishes speaking first from replying — the whole rule would "
        "then exist only in a phrasebook that governs neither")
