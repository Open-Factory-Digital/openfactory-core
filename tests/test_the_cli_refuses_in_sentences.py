"""A provider that refused the CLI produces a sentence, not a traceback (#111).

Measured in the pre-pilot review (2026-08-09), reproduced end to end with no network:
`openfactory run <project> <n>` against a repository that does not exist, or with `gh` not
authenticated, or against a private repository the credential cannot see, ended in a raw Rich
traceback — `RuntimeError: gh issue view failed: …` — instead of the one-cause-one-remedy sentence
this platform demands of every other surface. A stranger's first hour ends in a stack trace about
a tool the documentation never named.

The commonest case (the `gh` binary missing) already refuses by name from inside the adapter. What
was missing is the general class: the provider ANSWERED, and its answer was no.

TWO PROPERTIES CARRY THIS FILE, and they pull against each other on purpose:

    translate   a provider's refusal becomes a cause and a remedy, at the EDGE;
    do not      anything that is not a provider keeps its traceback, and a cause nobody
                recognised keeps the provider's own words instead of a guessed remedy.

THE CATCH IS AT THE EDGE AND NOWHERE ELSE. The durable worker needs the real exception —
`techlead/classify.py` reads it to decide whether a job parks as a credential problem, a policy
problem or a transient one — so an adapter that flattened failures into prose would cost the
platform the ability to tell a revoked token from a renamed repository. The card says so in its
own method note, and the guard at the bottom of this file holds it.
"""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from openfactory.cli_refusals import (
    as_a_sentence,
    looks_like_a_provider,
    name_the_cause,
    speaks_plainly,
)


def _gh(message: str) -> RuntimeError:
    """A failure in the shape every GitHub adapter here actually raises."""
    return RuntimeError(f"gh issue view failed: {message}")


# ── 1. the causes a person meets ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("said,expect_in_remedy", [
    ("gh: To get started with GitHub CLI, please run: gh auth login", "gh auth login"),
    ("HTTP 401: Bad credentials", "gh auth login"),
    ("HTTP 403: Resource not accessible by integration", "installation"),
    ("Could not resolve to a Repository with the name 'o/nope'", "registry"),
    ("HTTP 404: Not Found", "registry"),
    ("You have exceeded a secondary rate limit", "refill"),
    ("dial tcp: connection refused", "status page"),
])
def test_each_cause_a_person_actually_hits_gets_its_own_remedy(said, expect_in_remedy):
    named = name_the_cause(_gh(said))
    assert named is not None, f"nothing recognised {said!r}"
    _what, remedy = named
    assert expect_in_remedy in remedy, f"{said!r} → {remedy!r}"


def test_a_private_repository_and_a_missing_one_get_the_SAME_sentence():
    """They are indistinguishable to the caller — GitHub answers 404 for both, deliberately — so
    two different sentences would be this platform inventing a distinction the provider refuses to
    make."""
    missing = name_the_cause(_gh("Could not resolve to a Repository with the name 'o/x'"))
    private = name_the_cause(_gh("HTTP 404: Not Found"))
    assert missing == private
    assert "PRIVATE" in missing[1], (
        "it does not tell the reader that a private repo they cannot see looks exactly like this")


def test_an_UNRECOGNISED_failure_keeps_the_providers_own_words():
    """No guess. Somebody told to run `gh auth login` about a repository that was renamed spends
    the afternoon on the credential — a wrong remedy costs more than an unhelpful one."""
    exc = _gh("some new thing GitHub started saying last Tuesday")
    assert name_the_cause(exc) is None

    said = as_a_sentence(exc, doing="run that ticket")
    assert "some new thing GitHub started saying last Tuesday" in said
    assert "gh auth login" not in said, "it guessed a remedy for a cause it does not know"
    assert "verbatim" in said, "it does not admit that this is the provider talking, not us"


def test_the_sentence_always_says_what_was_being_ATTEMPTED():
    said = as_a_sentence(_gh("HTTP 404: Not Found"), doing="onboard that repository")
    assert "onboard that repository" in said


def test_the_narrow_reading_wins_over_the_broad_one():
    """"403 Resource not accessible" contains no 401 and must not fall into the auth bucket; a
    rate limit mentioning `403` must not either. Ordering is the mechanism, so it is asserted."""
    perm = name_the_cause(_gh("HTTP 403: Resource not accessible by integration"))
    assert "not allowed on this repository" in perm[0]


def test_the_whole_CHAIN_is_read_not_just_the_outer_message():
    """A `gh` failure usually arrives wrapped, and the sentence identifying the cause is rarely
    the outermost one — which is how a perfectly recognisable 404 reaches a person as
    'Activity task failed'."""
    inner = _gh("Could not resolve to a Repository with the name 'o/x'")
    outer = RuntimeError("could not read the ticket")
    outer.__cause__ = inner
    assert name_the_cause(outer) is not None


# ── 2. what must keep its traceback ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("exc", [
    TypeError("'module' object is not callable"),
    AttributeError("'NoneType' object has no attribute 'name'"),
    KeyError("project"),
    ValueError("invalid literal for int()"),
])
def test_a_BUG_IN_THIS_CODEBASE_is_never_dressed_up_as_a_provider(exc):
    """`namespace()` calling a module — the defect that swallowed the pilot's merge — is a
    `TypeError`. A friendly note about credentials over the top of it is the same failure wearing
    an explanation, and it would be harder to find than the traceback it replaced."""
    assert not looks_like_a_provider(exc)


def test_an_interrupt_is_not_a_provider():
    assert not looks_like_a_provider(KeyboardInterrupt())
    assert not looks_like_a_provider(SystemExit(1))


def test_a_provider_shaped_failure_IS_recognised():
    """The positive twin: if the shape test stopped matching, every refusal would quietly go back
    to being a traceback and every test above would still pass."""
    for exc in (_gh("HTTP 404"),
                RuntimeError("gh pr create failed: nope"),
                RuntimeError("AzureDevOpsError: GET build/definitions returned 401")):
        assert looks_like_a_provider(exc), exc


# ── 3. the edge, driven ─────────────────────────────────────────────────────────────────────────

def _one_command(boom: BaseException):
    app = typer.Typer()

    @app.command("go")
    @speaks_plainly("run that ticket")
    def go(name: str, issue: str,
           review: bool = typer.Option(True, help="Run the independent reviewer")) -> None:
        raise boom

    return app


def test_a_provider_refusal_exits_1_with_the_sentence_and_no_traceback():
    result = CliRunner().invoke(_one_command(_gh("HTTP 404: Not Found")), ["p", "12"])

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "could not run that ticket" in result.output
    assert "registry" in result.output


def test_a_real_bug_still_RAISES():
    result = CliRunner().invoke(_one_command(TypeError("'module' object is not callable")),
                                ["p", "12"])
    assert result.exit_code != 0
    assert isinstance(result.exception, TypeError), (
        "a defect in this codebase is being reported as somebody else's credential problem")


def test_typer_EXIT_passes_through_untouched():
    """`raise typer.Exit(1)` is how every command in this file reports an ordinary failure. A
    wrapper that re-labelled it would turn "the job did not reach a done state" into a sentence
    about the forge."""
    result = CliRunner().invoke(_one_command(typer.Exit(3)), ["p", "12"])
    assert result.exit_code == 3
    assert "could not run" not in result.output


def test_the_decorator_leaves_typer_able_to_read_the_OPTIONS():
    """`functools.wraps` is what makes this safe; without it typer sees `*args, **kwargs` and
    every flag disappears from `--help` — a fix that silently removes the command's interface."""
    import re

    app = _one_command(RuntimeError("x"))
    result = CliRunner().invoke(app, ["--help"])
    # ANSI stripped and whitespace collapsed: typer boxes and wraps its help to the terminal
    # width, so a raw substring match asserts the terminal's geometry as much as the interface.
    plain = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())
    assert "--review" in plain, plain
    assert "independent reviewer" in plain, plain

    # THE ARGUMENTS ARE ASKED OF THE PARAMETER LIST, NOT OF THE PROSE. Measured 2026-08-21 on four
    # fresh `pip install -e '.[runtime,dev]'` environments: green on typer 0.26.8 under BOTH Python
    # 3.12 and 3.13, red on typer 0.27.1 under BOTH. The Python version was never the variable —
    # `typer>=0.12` resolves to the newest release on a clean runner, so CI installed 0.27.1 while
    # this venv still carried 0.26.8 from an older install. All 0.27 changed is typer's own
    # SPELLING: `TyperArgument.make_metavar` grew a `usage=` branch that stopped upper-casing and
    # now writes a required argument as `{name}`, so the usage line reads
    # `Usage: go [OPTIONS] {name} {issue}` where 0.26 wrote `NAME ISSUE` (the Arguments panel's
    # type column moved from `TEXT` to `<str>` in the same release). The command's interface never
    # moved. Matching an upper-case metavar was asserting typer's RENDERER inside a test whose
    # subject is whether `functools.wraps` left typer able to SEE the parameters at all.
    #
    # `param_type_name` is click's own answer to "argument or option?" and reads
    # argument/argument/option identically on typer 0.15.4, 0.26.8 and 0.27.1 — so this holds on
    # both versions instead of pinning one. `isinstance(p, click.Argument)` would NOT do: measured
    # False on 0.26.8 AND 0.27.1, because since 0.26 `TyperArgument` subclasses the vendored
    # `typer._click.core.Parameter` and not `click.Argument` — a check that reads False on the
    # author's own machine, not merely on CI.
    kinds = {p.name: p.param_type_name for p in typer.main.get_command(app).params}
    assert kinds.get("name") == "argument", (
        f"an ARGUMENT disappeared from the command's interface: {kinds}")
    assert kinds.get("issue") == "argument", (
        f"an ARGUMENT disappeared from the command's interface: {kinds}")
    assert kinds.get("review") == "option", (
        f"an OPTION disappeared from the command's interface: {kinds}")
    # DRIVEN, both ways, on both versions (2026-08-21): with `functools.wraps` deleted the dict
    # reads {'args': 'argument', 'kwargs': 'argument'} and all three lines fail; with `issue`
    # demoted to `typer.Option(...)` the second line fails. The help match below cannot see that
    # demotion — `--issue` matches `\bissue\b` too — which is why the parameter list, not the
    # page, carries the property. The page still gets a line of its own so the guard also proves
    # the argument reaches what a person reads, in whichever case typer spells it: 0.26 put
    # `ISSUE` in the usage line, 0.27 puts `issue` there and in the Arguments panel.
    assert re.search(r"\bissue\b", plain, re.IGNORECASE), plain


# ── 4. it is on the commands that touch a provider ──────────────────────────────────────────────

@pytest.mark.parametrize("command", ["run", "poll", "onboard"])
def test_the_commands_that_reach_a_provider_are_wrapped(command):
    import ast
    import inspect

    from openfactory import cli

    tree = ast.parse(inspect.getsource(cli))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        registered = any(
            isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "command"
            and d.args and isinstance(d.args[0], ast.Constant) and d.args[0].value == command
            for d in node.decorator_list)
        if not registered:
            continue
        wrapped = any(isinstance(d, ast.Call) and getattr(d.func, "id", "") == "speaks_plainly"
                      for d in node.decorator_list)
        assert wrapped, f"`{command}` still ends in a traceback when the forge says no"
        return
    pytest.fail(f"no command called {command!r} — this guard is measuring nothing")


def test_the_ADAPTERS_still_raise_so_the_WORKER_can_classify():
    """THE METHOD NOTE ON THE CARD, held as a property. The durable path reads the real exception
    to decide whether a job parks as a credential problem, a policy problem or a transient one; an
    adapter that returned prose instead would cost the platform that distinction entirely."""
    import inspect

    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    src = inspect.getsource(GitHubIssuesTracker)
    assert "raise RuntimeError" in src, (
        "the tracker stopped raising — the worker can no longer tell a revoked token from a "
        "renamed repository, and every failure parks under one label")
    assert "speaks_plainly" not in src and "as_a_sentence" not in src, (
        "the CLI's edge translation leaked into an adapter the worker also uses")
