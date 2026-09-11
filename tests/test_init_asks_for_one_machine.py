"""ADR-0049 slice 4b — `openfactory init` defaults to the machine the person is sitting at.

THE FIRST TWO QUESTIONS decided which credential the whole file would ask for, and both answered
`github` unless the person said otherwise. So the shortest path through the platform's own
onboarding — press Enter, press Enter — produced a deployment that cannot run until somebody
creates an account, a token and a board somewhere else. ADR-0049 exists because that is not
where a person starts.

Both now default to `local`: their own repository is the forge, their tickets live in `board.db`
beside the registry, and the only line left to fill is the harness credential — the one this
platform calls the one you cannot postpone.

**AND THE FILE SAYS SO, IN WORDS.** `local` is a SHIPPED row, so it never reached the add-on
section; it needs no credential, so it reached no block at all. A person answering it twice got a
file with nothing in it about where their code or their tickets live — silence that looks exactly
like an oversight. The guard that should have caught that (`test_every_shipped_kind_NAMES_itself…`)
passed by LUCK: it searched the rendered text for the word, and
`OPENFACTORY_BOT_EMAIL=bot@openfactory.local` contains it. That row is dropped from the search now
and the kind is asked for as a word.
"""

from __future__ import annotations

import pytest

from openfactory.onboarding.deployment import QUESTIONS, Answers, Probes, render

_ASKED = {q.flag: q for q in QUESTIONS}


# ── 1. the default ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("flag", ["forge", "tracker"])
def test_the_prompt_defaults_to_this_machine(flag):
    """Press Enter twice and the factory runs where you are."""
    assert _ASKED[flag].default == "local", (
        f"the {flag} question still sends a person to a vendor before they have run anything")
    assert "local" in _ASKED[flag].options


@pytest.mark.parametrize("flag", ["forge", "tracker"])
def test_the_question_says_what_local_MEANS(flag):
    """An option list is not an explanation — the rule this command's prompts already follow."""
    assert "`local`" in _ASKED[flag].effect, (
        f"the {flag} question offers `local` without saying what answering it does")


def test_the_bare_answers_are_the_same_default_the_prompt_carries():
    """A test that builds `Answers()` directly must meet what a person meets. The two drifting is
    how a suite comes to prove a path nobody walks."""
    a = Answers()
    assert (a.forge, a.tracker) == ("local", "local")
    assert (a.forge, a.tracker) == (_ASKED["forge"].default, _ASKED["tracker"].default)


# ── 2. what it renders ──────────────────────────────────────────────────────────────────────────

def test_a_local_deployment_owes_exactly_one_credential():
    """The promise of ADR-0049 in one assertion: nothing hosted, so nothing to fill in but the
    coding agent's own sign-in."""
    out = render(Answers())

    assert len(out.remaining) == 1, out.remaining
    # AND ON THIS RUNTIME IT IS A LOGIN (ADR-0049 D9, slice 8). It read `CLAUDE_CODE_OAUTH_TOKEN`
    # while every runtime rendered the compose file: the token variable exists because a CLI has
    # to authenticate INSIDE a container with no human at a browser, and the machine this file is
    # now written for has no container and a person already signed in. The claim is unchanged —
    # exactly one thing is owed, and it is the coding agent's own credential.
    assert "is signed in on this machine" in out.remaining[0], out.remaining
    hosted = render(Answers(runtime="compose", forge="github", tracker="github"))
    assert "CLAUDE_CODE_OAUTH_TOKEN" in hosted.remaining[0], "the container door lost its token"


@pytest.mark.parametrize("axis", ["forge", "tracker"])
def test_each_local_axis_gets_a_NAMED_row_less_section(axis):
    """Named, and row-less. Silence and "the section has not been written yet" read the same."""
    text = render(Answers()).text

    heading = f"# ── {axis}: local — this machine, and no credential ──"
    assert heading in text, f"the file says nothing about where this deployment's {axis} is"
    body = text[text.index(heading):]
    body = body[:body.index("\n# ──", 1)] if "\n# ──" in body[1:] else body
    assert not [line for line in body.splitlines() if "=" in line and not line.startswith("#")], (
        "a row-less section grew a row — `local` needs no variable, and one here is a variable "
        "nobody can fill")


@pytest.mark.parametrize("axis, said", [
    ("forge", "your own repository"),
    ("tracker", "board.db"),
])
def test_the_section_says_what_that_axis_IS_and_not_only_that_it_is_free(axis, said):
    """"no credential" is half of it, and the half that does not tell a person where their work
    will actually go."""
    assert said in render(Answers()).text


def test_the_rendered_file_names_local_somewhere_other_than_the_bots_email():
    """THE DEFECT THE OLD GUARD COULD NOT SEE. Its search was satisfied by
    `bot@openfactory.local`, so the whole of this slice's subject could have been missing and the
    suite would have been green."""
    text = render(Answers()).text
    without_the_email = "\n".join(line for line in text.splitlines()
                                  if not line.startswith("OPENFACTORY_BOT_EMAIL="))

    assert "local" in without_the_email.lower()


# ── 3. the hosted answers lose nothing ──────────────────────────────────────────────────────────

def test_a_github_deployment_renders_exactly_what_it_always_did():
    """The flip is a DEFAULT, never a removal. Answering `github` must produce the same file it
    produced before this slice."""
    out = render(Answers(forge="github", tracker="github"),
                 Probes(forge_token=lambda: "ghp_TOKEN"))

    assert "OPENFACTORY_BOT_TOKEN=ghp_TOKEN" in out.text
    assert "forge: local" not in out.text and "tracker: local" not in out.text


def test_a_split_deployment_renders_the_local_axis_AND_the_hosted_one():
    """Tickets in Jira with the code on this machine is a shape the two axes exist to allow."""
    out = render(Answers(forge="local", tracker="jira"))

    assert "# ── forge: local — this machine, and no credential ──" in out.text
    assert "# ── tracker: local" not in out.text
    assert "jira" in out.text.lower()
    assert any("JIRA" in line for line in out.remaining), out.remaining
