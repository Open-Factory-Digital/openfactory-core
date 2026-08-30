"""Why the backfill downgraded to its deterministic half, said accurately.

THE DEFECT. `_backfill` chose between its two modes like this:

    binary = harness_binary(harness_kind(project, "techlead"))
    has_credential = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
                          or os.environ.get("ANTHROPIC_API_KEY"))

The BINARY was resolved from the project's configured tech-lead harness — `codex`, `kimi`,
`opencode` or `claude_code`. The CREDENTIAL was two hardcoded Anthropic variable names. So a
deployment running any harness but Claude Code took the else-branch on every onboarding, whatever
it had configured, and was told:

    "no harness credential on this machine"

which was false, named no variable that would fix it, and pointed a reader at a token they did not
need. The platform already knew the right answer in one place — `routes.resolve_route` — and that
place was never asked.

TWO SENTENCES, NOT ONE. The same branch also served an uninstalled binary, so a machine missing
`codex` was told its credential was missing. Those are different problems with different remedies
and they now read differently.

AND A ROUTE WITH NO REQUIREMENTS MEANS "CANNOT TELL", NOT "NOTHING NEEDED". `codex` and `kimi` fall
through to the generic route with empty `requires`, because nobody here has verified which variable
either reads. Guessing one would refuse a working deployment by name, so an unknown route is
attempted — and `propose_context`'s existing arms turn a harness that cannot authenticate into the
deterministic pass with the reason stated. Trying and being told why beats refusing and being told
something untrue.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.agent.routes import resolve_route


class _Project:
    """Enough of a project for `harness_kind` / `model_for` to resolve a role."""

    def __init__(self, harness, model=None):
        self.name = "acme"
        self.harness = harness
        self.model = model


# ── the route now answers per ROLE ───────────────────────────────────────────────────────────────

def test_the_route_answers_for_the_role_it_is_asked_about(monkeypatch) -> None:
    """`harness:` is per-role. A project may run `codex` for the executor and `claude_code` for the
    tech-lead, and every caller before this one happened to want the executor — so a caller asking
    about another role silently received a well-formed answer about the wrong harness."""
    monkeypatch.delenv("OPENFACTORY_AGENT_ENDPOINT", raising=False)
    project = _Project({"executor": "codex", "techlead": "claude_code"})

    assert resolve_route(project, env={}, role="executor").name != "anthropic"
    assert resolve_route(project, env={}, role="techlead").name == "anthropic"


def test_the_role_defaults_to_the_executor(monkeypatch) -> None:
    """The positive twin: every existing caller passes no role and must keep the answer it had."""
    monkeypatch.delenv("OPENFACTORY_AGENT_ENDPOINT", raising=False)
    project = _Project({"executor": "claude_code", "techlead": "codex"})

    assert resolve_route(project, env={}).name == resolve_route(
        project, env={}, role="executor").name


def test_the_opencode_route_reads_the_role_s_own_model(monkeypatch) -> None:
    """OpenCode names its provider inside `model:`, so reading the executor's model to answer about
    the tech-lead names the wrong provider — and both answers are well-formed, which is what makes
    it silent."""
    monkeypatch.delenv("OPENFACTORY_AGENT_ENDPOINT", raising=False)
    project = _Project(
        {"executor": "opencode", "techlead": "opencode"},
        {"executor": "openai/gpt-5", "techlead": "anthropic/claude-sonnet-4"})

    assert resolve_route(project, env={}, role="executor").name == "opencode/openai"
    assert resolve_route(project, env={}, role="techlead").name == "opencode/anthropic"


# ── what the backfill now decides on ─────────────────────────────────────────────────────────────

def _decide(monkeypatch, *, harness: str, env: dict[str, str], on_path: bool):
    """The decision alone: `semantic_pass_for` takes a project and a path and answers.

    No clone, no forge, no sandbox — which is what extracting it bought. Only the two things a
    SATISFIED route still reaches are stubbed, because this asks what the platform DECIDES, not
    what a harness then does with the decision."""
    import shutil
    from pathlib import Path

    from openfactory.onboarding import context as ctx
    from openfactory.onboarding import onboard as ob

    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY",
                 "ANTHROPIC_BASE_URL", "OPENFACTORY_AGENT_ENDPOINT",
                 "OPENFACTORY_TECHLEAD_HARNESS", "OPENFACTORY_HARNESS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    monkeypatch.setattr(shutil, "which", lambda b: "/usr/bin/x" if on_path else None)
    monkeypatch.setattr("openfactory.adapters.agent.build_asker", lambda p: object())
    monkeypatch.setattr("openfactory.adapters.sandbox.registry.judging_worktree",
                        lambda p, root=None: object())
    monkeypatch.setattr(ctx, "agent_ask", lambda *a, **k: (lambda *_a, **_k: ""))

    return ob.semantic_pass_for(_Project({"techlead": harness}), Path("/tmp"))


def _mode(monkeypatch, *, harness: str, env: dict[str, str], on_path: bool) -> str:
    """Just the sentence, for the guards that are about what it says."""
    return _decide(monkeypatch, harness=harness, env=env, on_path=on_path)[1]


def test_a_non_anthropic_harness_is_no_longer_told_it_has_no_credential(monkeypatch) -> None:
    """THE DEFECT. With `codex` configured and `OPENAI_API_KEY` set, the old code read two
    Anthropic variables, found neither, and reported a missing credential."""
    mode = _mode(monkeypatch, harness="codex", env={"OPENAI_API_KEY": "sk-x"}, on_path=True)

    assert "no harness credential" not in mode, mode


def test_a_claude_code_deployment_without_its_variables_still_says_credential(
        monkeypatch) -> None:
    """The positive twin, and the behaviour that must not regress: where the platform DOES know the
    requirement, an unmet one is still named."""
    mode = _mode(monkeypatch, harness="claude_code", env={}, on_path=True)

    assert "no harness credential" in mode
    assert "ANTHROPIC_API_KEY" in mode or "CLAUDE_CODE_OAUTH_TOKEN" in mode


def test_the_downgrade_names_the_variable_that_would_fix_it(monkeypatch) -> None:
    """"No credential" is a diagnosis. The remedy is a name, and a reader given only the diagnosis
    goes looking for the wrong token — which is what happened here."""
    mode = _mode(monkeypatch, harness="claude_code", env={}, on_path=True)

    assert "ANTHROPIC_API_KEY" in mode


def test_a_missing_binary_is_a_different_sentence_from_a_missing_credential(
        monkeypatch) -> None:
    """One branch served both, so a machine that simply had not installed the harness was told to
    go and find a token it already had."""
    mode = _mode(monkeypatch, harness="claude_code",
                 env={"ANTHROPIC_API_KEY": "sk-x"}, on_path=False)

    assert "PATH" in mode
    assert "no harness credential" not in mode


def test_a_satisfied_route_reaches_the_semantic_pass(monkeypatch) -> None:
    """The control. If this goes red the backfill has stopped spending its agent pass at all, and
    every guard above would still be green.

    IT ASSERTS THE ASK FUNCTION, NOT ONLY THE SENTENCE. The first version checked `mode` alone, and
    the mutation that returns `None` beside an unchanged "semantic" survived it — a backfill that
    reports the semantic pass and runs the deterministic one, which is the worst of the three
    possible states because nothing about the outcome says so (2026-08-29)."""
    ask_fn, mode = _decide(monkeypatch, harness="claude_code",
                           env={"ANTHROPIC_API_KEY": "sk-x"}, on_path=True)

    assert mode.startswith("semantic"), mode
    assert ask_fn is not None, "the mode says semantic; something has to actually ask"


def test_every_deterministic_answer_carries_no_ask_function(monkeypatch) -> None:
    """The other half of the same invariant: the sentence and the capability cannot disagree in
    either direction. A `mode` saying deterministic while an ask function is handed back would
    spend a pass the outcome swears it did not."""
    for harness, env, on_path in (("claude_code", {}, True),
                                  ("claude_code", {"ANTHROPIC_API_KEY": "sk-x"}, False)):
        ask_fn, mode = _decide(monkeypatch, harness=harness, env=env, on_path=on_path)
        assert mode.startswith("deterministic"), mode
        assert ask_fn is None, mode


def test_a_harness_whose_requirements_are_unknown_is_attempted_not_refused(
        monkeypatch) -> None:
    """`codex` and `kimi` reach the generic route with empty `requires`, because nobody here has
    verified which variable either reads. An empty requirement means the platform CANNOT TELL —
    inventing one would refuse a working deployment by name, so it tries, and the existing arms
    report a real failure with a real reason."""
    mode = _mode(monkeypatch, harness="kimi", env={}, on_path=True)

    assert "no harness credential" not in mode, mode


@pytest.mark.parametrize("harness", ["claude_code", "codex", "kimi", "opencode"])
def test_no_harness_is_told_something_untrue_about_anthropic(monkeypatch, harness: str) -> None:
    """The shape of the defect rather than one instance of it: only a deployment whose route
    actually needs an Anthropic variable may be told about one."""
    mode = _mode(monkeypatch, harness=harness, env={"OPENAI_API_KEY": "sk-x"}, on_path=True)

    if harness != "claude_code":
        assert "ANTHROPIC" not in mode, mode
