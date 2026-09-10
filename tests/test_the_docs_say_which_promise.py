"""The documentation leads with the door that needs nothing (ADR-0049 slice 6).

Every claim here is DERIVED from the code it describes, never from a copy of it. A docs guard that
asserts its own literal is a second source of truth with no way to notice the first one moved —
which is how the quickstart came to open with `docker --version` and a clone URL months after the
platform learned to run on a path with no account anywhere.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
ONBOARDING = (ROOT / "docs" / "ONBOARDING.md").read_text(encoding="utf-8")
ONE_MACHINE = ROOT / "docs" / "setup" / "one-machine.md"


def _first_registration(text: str) -> str:
    """The argument the first `project init`/`project add` in a document registers."""
    return next(m.group(1) for m in
                re.finditer(r"openfactory project (?:init|add) \S+ +(\S+)", text))


# ── the prompts and the prose say the same thing ────────────────────────────────────────────────

def test_the_prompt_DEFAULTS_are_the_kind_a_path_registers_as():
    """The two questions a person answers first and the rule the door applies must agree. They
    are set in different files, so nothing but this holds them together: a flip on one side and
    the docs would promise a machine that the door then registers as somebody's GitHub."""
    from openfactory import doors
    from openfactory.onboarding.deployment import QUESTIONS

    defaults = {q.flag: q.default for q in QUESTIONS if q.flag in ("forge", "tracker")}

    assert defaults == {"forge": "local", "tracker": "local"}
    assert doors.kind_for("/home/me/code/myapp") == "local", (
        "the door no longer registers a bare path as `local`, so the quickstart's first command "
        "does something other than what it says")


@pytest.mark.parametrize("doc,text", [("README.md", README), ("docs/ONBOARDING.md", ONBOARDING)])
def test_the_first_registration_a_reader_meets_is_a_PATH(doc, text):
    """Both entry documents used to open on a clone URL, which asks for an account before the
    reader has seen anything work."""
    first = _first_registration(text)

    assert "://" not in first and not first.startswith("git@"), (
        f"{doc} registers {first} first — a reader meets a vendor before they meet a card")


def test_the_one_machine_door_is_a_page_and_it_is_ON_THE_MAP():
    """IN THE TABLE, not merely mentioned in the quickstart's prose. The table is what a reader
    scans when they are deciding what to read; a page that is only linked from inside one section
    is invisible to everybody who did not already start there — which was the whole difficulty
    with the four onboarding pages this repository consolidated."""
    assert ONE_MACHINE.exists()

    rows = [line for line in README.splitlines() if line.startswith("| [docs/setup/")]

    assert any("one-machine.md" in row for row in rows), (
        f"the one-machine door is not on the README's map of pages: {rows}")


def test_docker_is_asked_for_by_the_door_that_needs_it():
    """Docker was the FIRST word of the prerequisites, for every reader, including the ones who
    never containerise anything. It belongs to the compose door, at the hour that needs it."""
    first_door = README.split("## Quickstart — with Docker")[0]

    # THE COMMANDS, NOT THE WORD. That block SAYS "no Docker" — which is the promise — and what
    # must not appear is Docker as something the reader has to have or run.
    for asked in ("docker --version", "docker compose", "Docker Desktop", "Prerequisites: Docker"):
        assert asked not in first_door, (
            f"the one-machine quickstart asks for `{asked}`, which that door does not use")
    assert "## Quickstart — with Docker" in README, "the hosted door lost its block"
    assert README.index("## Quickstart — one machine") < README.index("## Quickstart — with Docker")


def test_the_compose_file_says_whose_credentials_those_are():
    """`.env.compose.example` opens by naming TWO irreducible credentials. That is true of the
    door it belongs to and false of the other one, and a reader who arrives from the one-machine
    page must not be sent to fetch a forge token that nothing will read."""
    example = (ROOT / ".env.compose.example").read_text(encoding="utf-8")

    assert "one-machine.md" in example
    assert "local" in example
