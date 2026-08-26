"""`openfactory init` generates the deployment's environment instead of asking for it — #116.

Raised by the pilot operator, unprompted, while filling `.env.compose` by hand: *"não deveria ser
o CLI da openfactory a gerar este .env.compose […]? é normal estas fases de config nos CLI, como
AWS por exemplo."* The strongest argument was this platform's own: `env read` proposes a manifest
from the repository, `project init` converges — and the deployment's own environment was the last
thing still hand-written, and the FIRST file an adopter opens.

THE PROPERTY THAT IS THE WHOLE POINT, and the one these tests exist for: **the generated file
contains only the variables the answers actually use.** A template with rows for vendors you do
not run is a file you cannot tell apart from one you filled in wrong — which is precisely what
the operator reported feeling. Every other guard here protects a credential.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
from typer.testing import CliRunner

from openfactory.cli import app
from openfactory.onboarding.deployment import Answers, Probes, UnknownAnswer, render

ROOT = pathlib.Path(__file__).resolve().parents[1]

_GITHUB_VARS = ("OPENFACTORY_BOT_TOKEN", "OPENFACTORY_GH_APP_ID",
                "OPENFACTORY_GH_APP_INSTALLATION_ID", "OPENFACTORY_GH_APP_KEY_CONTENT")


def _names(text: str) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, re.MULTILINE))


# ── the property: only what this deployment uses ────────────────────────────────────────────────

def test_an_azure_deployment_carries_no_github_variable():
    """The report that started this: an Azure DevOps shop opening a GitHub-shaped file reads it
    as 'not for us' — the opposite of the axis claim the README makes two paragraphs earlier."""
    text = render(Answers(forge="azure_devops", tracker="azure_devops")).text

    assert "AZURE_DEVOPS_PAT" in _names(text)
    for var in _GITHUB_VARS:
        assert var not in text, f"{var} is in a file for a deployment with no GitHub anywhere"
    assert "JIRA_API_TOKEN" not in text
    assert "SLACK_BOT_TOKEN" not in text


def test_a_github_deployment_carries_no_azure_or_jira_variable():
    text = render(Answers(forge="github", tracker="github")).text

    assert "OPENFACTORY_BOT_TOKEN" in _names(text)
    assert "AZURE_DEVOPS_PAT" not in text and "JIRA_API_TOKEN" not in text


def test_the_two_axes_are_independent_in_the_file_too():
    """Tickets on Jira, code on GitHub — an ordinary configuration the old template never showed."""
    text = render(Answers(forge="github", tracker="jira")).text

    assert {"OPENFACTORY_BOT_TOKEN", "JIRA_API_TOKEN"} <= _names(text)
    assert "AZURE_DEVOPS_PAT" not in text


def test_choosing_the_App_drops_the_token_row_and_vice_versa():
    """Two ways to authenticate one vendor is exactly the shape that made the template feel
    like a form: both rows present, neither explained as the alternative it is."""
    app_text = render(Answers(github_auth="app")).text
    tok_text = render(Answers(github_auth="token")).text

    assert "OPENFACTORY_GH_APP_ID" in _names(app_text)
    # no ROW — the name may (and should) appear in the comment warning that a filled PAT beats
    # the App everywhere; what must not exist is a fillable line
    assert "OPENFACTORY_BOT_TOKEN" not in _names(app_text)
    assert "OPENFACTORY_BOT_TOKEN" in _names(tok_text)
    assert "OPENFACTORY_GH_APP_ID" not in _names(tok_text)


def test_the_app_path_on_a_personal_account_writes_the_board_token_row():
    """The first pilot funnel run died at board creation because this row existed only as
    prose in the guide's §6: the App trio cannot drive a user-owned board, and nothing the
    operator FILLED said so. Now the account-type ANSWER writes the row and the to-do."""
    personal = render(Answers(github_auth="app", github_account="personal"))
    org = render(Answers(github_auth="app", github_account="org"))

    assert "OPENFACTORY_TRACKER_TOKEN" in _names(personal.text)
    assert "PERSONAL" in personal.text
    assert any("OPENFACTORY_TRACKER_TOKEN" in line and "classic" in line
               for line in personal.remaining)
    assert "OPENFACTORY_TRACKER_TOKEN" not in _names(org.text), (
        "an organisation's App needs no extra token — the row would be a blank nobody can "
        "evaluate, the exact defect init exists to remove")


def test_a_harness_with_no_credential_VARIABLE_invents_none():
    """Measured, not assumed: the container sandbox forwards exactly CLAUDE_CODE_OAUTH_TOKEN and
    ANTHROPIC_API_KEY. codex/kimi/opencode log in through their own CLI inside the box, so a
    variable for them would look configured and authenticate nothing."""
    out = render(Answers(harness="codex"))

    assert not ({"CODEX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"} & _names(out.text))
    assert any("box prove" in line for line in out.remaining), (
        "the reader must be told what DOES prove that harness authenticated")


# ── credentials: obtained, named, never echoed ──────────────────────────────────────────────────

def test_a_gh_login_fills_the_token_and_says_whose_it_is():
    out = render(Answers(), Probes(forge_token=lambda: "ghp_FROM_GH_LOGIN"))

    assert out.obtained == ["OPENFACTORY_BOT_TOKEN"]
    assert "ghp_FROM_GH_LOGIN" in out.text  # it IS the file's job to carry it
    assert any("AS YOU" in line or "as you" in line for line in out.remaining), (
        "a person's credential silently becoming the factory's identity is the thing to say out "
        "loud, not the convenience")


def test_no_gh_login_leaves_the_line_empty_with_the_recipe_beside_it():
    out = render(Answers(), Probes(forge_token=lambda: None))

    assert "OPENFACTORY_BOT_TOKEN=\n" in out.text
    assert any("github.com/settings/tokens" in line for line in out.remaining)
    assert any("NEVER `workflow`" in line for line in out.remaining), (
        "the one scope whose ABSENCE is a guardrail has to be named where somebody is choosing "
        "scopes")


def test_the_panel_token_is_generated_only_when_it_is_needed():
    exposed = render(Answers(panel_exposed=True), Probes(secret=lambda: "S3CRET"))
    local = render(Answers(panel_exposed=False))

    assert "OPENFACTORY_PANEL_TOKEN=S3CRET" in exposed.text
    assert "OPENFACTORY_PANEL_TOKEN" in exposed.obtained
    assert "OPENFACTORY_PANEL_TOKEN=\n" in local.text
    assert "EMPTY MEANS OPEN" in local.text, "a laptop default that is open must say so"


def test_a_scripted_install_may_not_leave_the_panel_open_by_omission(tmp_path):
    """Six questions refused without a terminal; the seventh silently DEFAULTED — to an OPEN
    panel (v2 verification pass, 2026-08-10). A default is the product: the panel-exposure
    answer must be stated, not assumed, when nobody is there to ask."""
    from typer.testing import CliRunner

    from openfactory.cli import app

    dest = tmp_path / ".env.compose"
    flags_without_panel = [f for f in _FLAGS if f != "--panel-local"]
    result = CliRunner().invoke(app, ["init", "--out", str(dest), *flags_without_panel])

    assert result.exit_code == 2, result.output
    assert "--panel-exposed" in result.output and "--panel-local" in result.output
    assert "OPEN" in result.output, "the refusal must say what the silence would have cost"
    assert not dest.exists(), "the refusal must not write"


def test_the_unpostponable_credential_is_literally_first_in_the_list():
    """ONBOARDING §1 calls the harness credential 'the one you cannot postpone' and says init
    put it at the top of the list. The funnel walkers caught the list disagreeing — the forge
    rows landed first on every path that has any, which is every path. The claim is the doc's;
    the ORDER is this module's; they must agree."""
    for answers in (Answers(), Answers(github_auth="app"),
                    Answers(forge="azure_devops", tracker="azure_devops"),
                    Answers(tracker="jira"), Answers(harness="kimi")):
        first = render(answers).remaining[0]
        assert ("CLAUDE_CODE_OAUTH_TOKEN" in first or "ANTHROPIC_API_KEY" in first
                or "authenticate the" in first), (
            f"the harness credential is not item 1 for {answers!r}: {first!r}")


def test_every_remaining_line_names_a_page_or_a_command():
    """The house bar: a refusal or a to-do without a way forward is a symptom handed to the one
    person who does not know the system."""
    # `channel="slack"` is an add-on kind since 2026-08-26 and is covered, with its package's row
    # installed, by `test_the_doors_derive_from_the_registries.py`
    for answers in (Answers(), Answers(github_auth="app"), Answers(forge="azure_devops"),
                    Answers(tracker="jira"),
                    Answers(harness="kimi"), Answers(claude_auth="api_key")):
        for line in render(answers).remaining:
            # a command, a page, or a document IN THE REPOSITORY THEY CLONED — all three are a
            # way forward; anything else is a symptom handed to the one person who does not know
            # the system. (The App line taught this: it points at docs/setup/github.md,
            # because the creation URL differs for an organisation and a personal account and
            # the permission table is the part that actually matters.)
            assert re.search(r"`[^`]+`|\b[a-z-]+\.(com|dev|io)\b|docs/[\w/.-]+\.md", line), (
                f"this to-do names no command, page or document: {line!r}")


def test_an_answer_outside_the_vocabulary_is_refused_BY_NAME():
    """The list in the refusal is the forge REGISTRY's (shipped rows plus installed add-ons,
    sorted) — not a copy kept here, which is why the order is the registry's and not this
    file's. `gitlab` is refused because nothing implements it, not because a tuple omits it."""
    from openfactory import plugins
    from openfactory.adapters.forge.registry import FORGES

    expected = ", ".join(plugins.known("forge", FORGES))
    with pytest.raises(UnknownAnswer, match=rf"forge: 'gitlab' is not one of {expected}"):
        render(Answers(forge="gitlab"))


# ── the CLI's own safety rules ──────────────────────────────────────────────────────────────────

_FLAGS = ["--forge", "github", "--tracker", "github", "--harness", "claude_code",
          "--github-auth", "token", "--claude-auth", "subscription", "--channel", "panel",
          "--panel-local"]


def test_it_never_overwrites_a_filled_file_without_force(tmp_path):
    """`env apply`'s rule, and here it protects credentials somebody pasted by hand."""
    dest = tmp_path / ".env.compose"
    dest.write_text("OPENFACTORY_BOT_TOKEN=mine-already\n")

    result = CliRunner().invoke(app, ["init", *_FLAGS, "--out", str(dest)])

    assert result.exit_code == 2
    assert dest.read_text() == "OPENFACTORY_BOT_TOKEN=mine-already\n"
    assert "--force" in result.output and "Nothing was changed" in result.output

    forced = CliRunner().invoke(app, ["init", *_FLAGS, "--out", str(dest), "--force"])
    assert forced.exit_code == 0 and "mine-already" not in dest.read_text()


def test_it_refuses_instead_of_hanging_when_nobody_can_answer(tmp_path):
    """Piped into a script, `typer.prompt` waits for input that never comes — the silent
    forever-wait this platform treats as its own defect class. It names the flag instead."""
    result = CliRunner().invoke(app, ["init", "--out", str(tmp_path / ".env.compose")])

    assert result.exit_code == 2
    assert "--forge is required" in result.output
    assert not (tmp_path / ".env.compose").exists()


def test_the_file_is_written_0600_and_no_secret_reaches_the_terminal(tmp_path, monkeypatch):
    # The login is discovered through the credential registry's row for the CHOSEN forge (the
    # CLI used to spawn `gh auth token` itself); the seam to drive is the neutral resolver.
    monkeypatch.setattr("openfactory.credentials.discover_forge_token",
                        lambda kind: "ghp_DO_NOT_ECHO_ME")
    dest = tmp_path / ".env.compose"

    result = CliRunner().invoke(app, ["init", *_FLAGS, "--out", str(dest)])

    assert result.exit_code == 0
    assert oct(dest.stat().st_mode)[-3:] == "600"
    assert "ghp_DO_NOT_ECHO_ME" in dest.read_text()
    assert "ghp_DO_NOT_ECHO_ME" not in result.output, (
        "a secret echoed to a terminal is a secret in a scrollback buffer, a screen recording "
        "and a CI log")
    assert "OPENFACTORY_BOT_TOKEN" in result.output  # the NAME is what a human needs


# ── the exception, asserted rather than assumed ─────────────────────────────────────────────────

#: `init` is deliberately terminal-only, and why. Same shape as `env rehearse`'s exception
#: (#99): an exception nobody asserts is indistinguishable from a capability somebody forgot to
#: expose, and the difference decides whether the next person "fixes" it.
TERMINAL_ONLY = {
    "init": (
        "it configures the DEPLOYMENT — including the panel's own credential — and it runs "
        "before any surface exists. A panel button that could rewrite the deployment's "
        "credentials would be the privilege inversion this platform's whole authorisation model "
        "exists to prevent: the surface would be granting itself its own access."
    ),
}


@pytest.mark.parametrize("name", sorted(TERMINAL_ONLY))
def test_the_terminal_only_exception_is_still_EARNED(name):
    """Staleness, the house pattern: the day `init` becomes a catalogue row, this entry is a lie
    and has to fail rather than sit there reading like documentation."""
    from openfactory import actions

    assert name not in actions.CATALOG, (
        f"`{name}` is a catalogue row now — delete its TERMINAL_ONLY entry; the exception was "
        f"paid down.")
    assert TERMINAL_ONLY[name].strip(), "an exception without a reason is a pass"


def test_init_is_a_real_top_level_command():
    """The positive twin: the guard above passes just as happily if the command never existed."""
    tree = ast.parse((ROOT / "openfactory/cli.py").read_text())
    commands = {
        arg.value
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for deco in node.decorator_list
        if isinstance(deco, ast.Call) and getattr(deco.func, "attr", "") == "command"
        for arg in deco.args
        if isinstance(arg, ast.Constant)
    }
    assert "init" in commands, f"`openfactory init` is not a command at all: {sorted(commands)}"


# ── the questions themselves: the reader's words, and what the answer changes ────────────────────

#: The platform's own vocabulary. These words are how WE talk about the axes, and a person
#: answering the questions has never read a line of this repository — so a prompt built out of
#: them ("channel (panel/slack)") is a prompt that gets asked back, which is exactly what the
#: pilot operator did: "não entendi essa pergunta e o que ela influenciaria".
_OUR_VOCABULARY = ("forge", "tracker", "channel", "harness", "sandbox", "box", "axis", "axes")


def test_no_question_is_asked_in_our_own_vocabulary():
    from openfactory.onboarding.deployment import QUESTIONS

    for entry in QUESTIONS:
        lowered = entry.ask.lower()
        for word in _OUR_VOCABULARY:
            assert not re.search(rf"\b{word}\b", lowered), (
                f"--{entry.flag} asks in our words, not the reader's: {entry.ask!r} contains "
                f"{word!r}. The FLAG may be technical; the question may not.")


def test_every_question_says_what_the_answer_changes():
    """An option list is not an explanation. `channel (panel/slack)` told the reader the two
    spellings and nothing about what picking one does to the file or to their factory."""
    from openfactory.onboarding.deployment import QUESTIONS

    for entry in QUESTIONS:
        assert entry.ask.strip().endswith("?"), f"--{entry.flag} is not phrased as a question"
        assert len(entry.effect.strip()) > 30, (
            f"--{entry.flag} does not say what the answer changes: {entry.effect!r}")
        assert entry.default in entry.options, (
            f"--{entry.flag} offers a default that is not one of its options")


def test_the_questions_cover_every_answer_the_generator_reads():
    """A question the CLI asks but the generator ignores, or an answer with no question, is the
    gap where a flag quietly stops working. Derived from the dataclass rather than listed."""
    import dataclasses

    from openfactory.onboarding.deployment import QUESTIONS, Answers

    asked = {entry.flag.replace("-", "_") for entry in QUESTIONS}
    fields = {f.name for f in dataclasses.fields(Answers)}
    assert asked == fields, f"asked but unused: {asked - fields}; unasked: {fields - asked}"
