"""The catalogue is worth nothing if the language never arrives (#160).

Sibling of `test_nothing_speaks_before_it_asks_the_language.py`, which asserts that no outward
surface composes its own sentence. That guard is satisfied by a call that renders a catalogue entry
in a hardcoded `"en"` — the sentence would be translatable and never translated, which is this
repository's signature defect wearing the fix as a disguise: built, tested, reached by nothing.

So this one walks the other way. For each composer, it asks whether the PROJECT's declared language
is what reaches it — through the registry row the runner is handed, the field on `JobParams`, or the
argument the round passes down.
"""

from __future__ import annotations

import types

import pytest


def _project(language="pt-BR", name="acme"):
    return types.SimpleNamespace(name=name, language=language, product=None)


# ── 1. the two runners are handed the row's language, not a constant ────────────────────────────

def test_the_promotion_runner_speaks_the_projects_language():
    from openfactory.orchestrator.promotion import PromotionRunner

    runner = PromotionRunner(tracker=object(), forge=object(), observer=object(),
                             manifest=object(), language="pt-BR")

    said = runner._say("promo.live")

    assert said == "no ar em produção", said


def test_and_an_UNCONFIGURED_one_gets_understandable_English():
    """The answer a deployment that declared nothing would want — never a KeyError on a release."""
    from openfactory.orchestrator.promotion import PromotionRunner

    runner = PromotionRunner(tracker=object(), forge=object(), observer=object(),
                             manifest=object())

    assert runner._say("promo.live") == "live in production"


def test_the_in_job_machine_reads_it_off_the_REGISTRY_ROW_it_was_given():
    """`JobRunner.project` is that row. It is optional — an ad-hoc construction has none — and
    absent must mean English rather than an AttributeError inside a park announcement."""
    from openfactory.orchestrator.machine import JobRunner

    fields = {"tracker": object(), "forge": object(), "agent": object(), "sandbox": object(),
              "manifest": object(), "repo_path": "/tmp"}
    with_row = JobRunner(**fields, project=_project())
    without = JobRunner(**fields)

    assert with_row._say("job.verb.on-hold") == "em espera"
    assert without._say("job.verb.on-hold") == "on hold"


# ── 2. the builders actually pass it ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("builder", ["factory", "catalog"])
def test_both_places_that_BUILD_a_promotion_runner_hand_it_the_language(builder):
    """Reachability. A runner that reads `self.language` and is never given one answers English
    for every project on earth, and every guard above still passes."""
    import ast
    import inspect

    if builder == "factory":
        from openfactory import factory as mod
    else:
        from openfactory.actions import catalog as mod

    src = inspect.getsource(mod)
    built = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call)
             and (getattr(n.func, "id", "") or getattr(n.func, "attr", "")) == "PromotionRunner"]

    assert built, f"{builder} no longer builds a promotion runner — this guard measures nothing"
    for call in built:
        given = {k.arg for k in call.keywords}
        assert "language" in given, (
            f"{builder} builds a promotion runner that will answer English for every project")


def test_the_workflow_renders_with_params_language_and_never_a_constant():
    """`JobParams.language` is a FIELD precisely so the workflow can render without doing IO — a
    lookup there would be a new command in the sequence and every job in flight would diverge."""
    import ast
    import inspect

    from openfactory.runtime.temporal import workflow as wf

    src = inspect.getsource(wf.JobWorkflow)
    calls = [n for n in ast.walk(ast.parse(src.lstrip()))
             if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "say"]

    assert len(calls) >= 8, f"only {len(calls)} catalogue renders in the whole lifecycle"
    for call in calls:
        rendered = ast.unparse(call)
        assert "params.language" in rendered, f"a lifecycle sentence hardcodes a language: {rendered}"


# ── 3. the product role and the round ───────────────────────────────────────────────────────────

def test_the_role_writes_its_ticket_comments_in_the_projects_language():
    """`review()` composes the comment that lands on a parked card. It took `agent_name` and not
    `language`, so the client read Portuguese whatever they had declared."""
    import inspect

    from openfactory.product.module import ProductModule
    from openfactory.product.needs_action import review

    assert "language" in inspect.signature(review).parameters

    src = inspect.getsource(ProductModule.review_needs_action)
    assert src.count("language=getattr(self.project") == 2, (
        "one of `review_needs_action`'s two exits composes without the project's language — the "
        "empty-board one is the exit a quiet project takes every hour")


def test_the_rounds_escalation_sentence_keeps_the_language_it_was_given():
    """`watch()` receives `language` and rendered every finding with it except one: the escalation
    `action`, which is `remedy.say` — the longest sentence in the message."""
    import inspect

    from openfactory.techlead import watch as watch_mod

    src = inspect.getsource(watch_mod.watch)
    remedies = [line for line in src.splitlines() if "remedy_for(" in line]

    assert remedies, "watch() no longer asks for a remedy — this guard measures nothing"
    for line in remedies:
        assert "language" in line, f"a remedy is composed without the round's language: {line}"


def test_a_finding_reminder_is_composed_in_it_too():
    """`report()` renders `detail` and `action` verbatim, so a finding composed in one language
    survives the whole trip — and a round could print four localized lines and one welded one."""
    import inspect

    from openfactory.runtime.temporal import activities

    assert "language" in inspect.signature(activities._finding_reminders).parameters

    src = inspect.getsource(activities.techlead_watch)
    assert "_finding_reminders, project_name, ledger, lang" in src, (
        "the round builds its reminders without handing over the language it just resolved")
