"""`init` refuses to overwrite THE FILE THIS RUN WILL WRITE — not the one the default names.

Found by running the first command of a demonstration, 2026-09-11. Standing in a directory that
holds a `.env.compose` (this repository's own clone does, and so does any tree where somebody once
brought the stack up), `openfactory init` printed

    ✗ .env.compose already exists — re-run with --force to overwrite it

and exited 2 — before asking the first question. The answer to that question is what decides the
destination: `local` writes `~/.openfactory/env` and never touches `.env.compose` at all. So the
one command a new deployment starts with refused, about a file it was not going to write, over an
answer the person had not been allowed to give.

The rule itself is right and stays: the file carries credentials somebody pasted by hand, and
silently rewriting it is the one mistake that costs more than the whole command saves. What moved
is WHEN it is asked — after the destination is known.

WHAT IS PROVEN HERE:

  · a `.env.compose` in the room does not stop a `local` deployment, and the file is left alone;
  · the file the run WILL write is still refused, by name, with nothing changed;
  · `--force` still overwrites;
  · the refusal happens before any work, on the compose runtime too.
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "tests")

from one_machine import cli  # noqa: E402

#: WHAT THE FILES IN THIS TEST CARRY, and it is deliberately inert.
#:
#: Every command here runs in the PYTEST PROCESS, and `openfactory`'s first act is to load the
#: deployment's environment — `.env` beside you, then `~/.openfactory/env` — into `os.environ`
#: with dotenv, which monkeypatch cannot take back. So a row named after a real platform variable
#: does not stay in the file this test wrote: it becomes this process's environment for everything
#: that runs afterwards. The first version of this file planted `OPENFACTORY_PANEL_TOKEN=mine`,
#: and CI came back with `401 unauthorized` from every panel test in the suite — a token the panel
#: was right to honour, on a deployment nobody had configured. Eight local chunks could not see it
#: (each is its own process); the arbiter runs the suite whole, and did.
_PASTED = "SOMETHING_A_PERSON_PASTED_BY_HAND=keep-me\n"


@pytest.fixture
def room(tmp_path, monkeypatch):
    """A directory with a `.env.compose` in it and a home nobody has initialised."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.compose").write_text(_PASTED, encoding="utf-8")
    return tmp_path


def _local(*extra):
    return ("init", "--runtime", "local", "--forge", "local", "--tracker", "local",
            "--harness", "claude_code", "--channel", "panel", "--panel-local", *extra)


def test_a_compose_file_in_the_room_does_not_stop_a_LOCAL_deployment(room):
    code, out = cli(*_local())

    assert code == 0, out
    assert (room / "home" / ".openfactory" / "env").exists(), "the local file was not written"


def test_and_the_compose_file_is_left_exactly_as_it_was(room):
    cli(*_local())

    assert (room / ".env.compose").read_text() == _PASTED


def test_the_file_this_run_WOULD_write_is_still_refused(room):
    """The rule did not loosen — it moved. The refusal names the real destination."""
    host = room / "home" / ".openfactory" / "env"
    host.parent.mkdir(parents=True)
    host.write_text(_PASTED, encoding="utf-8")

    code, out = cli(*_local())

    assert code == 2
    assert str(host) in out and "--force" in out
    assert host.read_text() == _PASTED, "it was overwritten anyway"


def test_force_still_overwrites(room):
    host = room / "home" / ".openfactory" / "env"
    host.parent.mkdir(parents=True)
    host.write_text(_PASTED, encoding="utf-8")

    code, out = cli(*_local("--force"))

    assert code == 0, out
    assert _PASTED.strip() not in host.read_text()


def test_the_compose_runtime_is_refused_over_ITS_file(room):
    """The half that already worked, kept: on `compose` the default destination is the file in
    the room, and it is the one protected."""
    code, out = cli("init", "--runtime", "compose", "--forge", "github", "--tracker", "github",
                    "--github-auth", "token", "--harness", "claude_code",
                    "--claude-auth", "api_key", "--channel", "panel", "--panel-local")

    assert code == 2
    assert ".env.compose already exists" in out


def test_the_rows_this_file_plants_are_INERT():
    """The trap this file fell into, made a guard rather than a memory.

    Every command here runs in the pytest process, and `openfactory` loads the deployment's
    environment into `os.environ` with dotenv before it does anything else — monkeypatch cannot
    take that back. So whatever this file writes into a `.env`-shaped file becomes the environment
    of every test that runs after it. The first version planted `OPENFACTORY_PANEL_TOKEN=mine`;
    CI answered `401 unauthorized` from every panel test in the suite, and eight local chunks —
    eight processes — could not see it.
    """
    name = _PASTED.split("=")[0]

    assert not name.startswith(("OPENFACTORY_", "ANTHROPIC_", "CLAUDE_", "GH_", "GITHUB_",
                                "TEMPORAL_", "AWS_")), (
        f"{name} is a variable this platform READS — planted here it is not a fixture, it is the "
        f"environment of everything that runs after this file")
