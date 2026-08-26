"""The box must not execute the client image's login-shell profile (ADR-0037 D2).

`ContainerSandbox.run` invoked every command as `sh -lc`. The `-l` makes it a LOGIN shell, which
sources `/etc/profile` and `/etc/profile.d/*` **from the client's image** before the command runs —
with the harness token already in the environment, because the auth vars are passed on the same
`docker exec`. Under ADR-0037 D1 that image is chosen by the client, so this is arbitrary
third-party code executing ahead of every single command the platform issues, with a credential in
scope. No agent involvement, no PATH shadowing, no exploit needed: it is just what `-l` means.

IT ALSO BREAKS THE DESIGN WITHOUT ANY MALICE. Debian's stock `/etc/profile` — and Alpine's —
assigns `PATH` unconditionally. ADR-0037 D2 delivers the harness by mounting a toolbox and pointing
at it, and any `PATH` the framework sets is discarded by an ordinary, entirely benign base image
before the command runs. That is why D2 says absolute paths and why this test exists beside it: the
two are one fix, and shipping only the absolute paths would leave the credential exposure standing.

`-l` bought nothing. Nothing in this platform depends on a login shell: `setup:` and `validate:` are
strings the client wrote, run in a container whose environment the framework sets explicitly.

The tests below are unit-level over the argv the adapter builds. The end-to-end version — an image
whose `/etc/profile` writes a marker file, asserted absent after a run — needs a Docker daemon and
lives in the box-prove suite; the argv assertion is what runs on every commit.
"""

from __future__ import annotations

import subprocess

import pytest

from openfactory.adapters.sandbox.container import ContainerSandbox


class _Recorder:
    """Captures the argv the adapter hands to the OS, and lets a trivial real process stand in.

    THE SEAM MOVED WITH THE IMPLEMENTATION, THE ASSERTIONS DID NOT. This recorded `container._host`
    — `subprocess.run(capture_output=True)` — until `run()` had to become readable WHILE it runs
    (C-39, #82) and started its process with `Popen`. Recording at `_host` after that captured
    nothing from `run()` at all, and `_shell_argv` raised "no shell exec found in []": four
    assertions about a credential exposure, observing a call that no longer happens.

    It records at `Popen` now, which is the actual argv handed to the OS — a strictly closer look
    at the same property. Returning a REAL process (`sh -c :`, exits immediately, says nothing)
    rather than a stub keeps `run_and_stream`'s reader, wait and drain in the picture, so the
    fixture cannot pass against an adapter that builds the right argv and then mishandles it."""

    def __init__(self, real_popen):
        self.calls: list[list[str]] = []
        self._real = real_popen

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        return self._real(["sh", "-c", ":"], **kwargs)


@pytest.fixture
def box(monkeypatch):
    rec = _Recorder(subprocess.Popen)
    monkeypatch.setattr(subprocess, "Popen", rec)
    sandbox = ContainerSandbox(image="mycorp/ci-base:2026.7")
    sandbox._container = "openfactory-fixture-1"  # as prepare() would leave it
    return sandbox, rec


def _shell_argv(calls) -> list[str]:
    for argv in calls:
        if "exec" in argv and "sh" in argv:
            return argv
    raise AssertionError(f"no shell exec found in {calls}")


def test_the_command_shell_is_not_a_login_shell(box):
    """THE defect. `-l` sources the client image's /etc/profile with the harness token in scope."""
    sandbox, rec = box
    sandbox.run(workspace=None, command="pytest -q", timeout=60)

    argv = _shell_argv(rec.calls)
    assert "-lc" not in argv, (
        "the box runs commands through a LOGIN shell, so the client image's /etc/profile executes "
        f"before every command, with the harness credential present: {argv}"
    )
    assert "-l" not in argv, argv


def test_the_command_still_goes_through_a_shell(box):
    """`setup:` and `validate:` are shell strings a client wrote — pipes, `&&`, globs and all. The
    fix must drop the login behaviour, not the shell."""
    sandbox, rec = box
    sandbox.run(workspace=None, command="make build && pytest -q", timeout=60)

    argv = _shell_argv(rec.calls)
    assert argv[-2:] == ["-c", "make build && pytest -q"], argv
    assert "sh" in argv


def test_the_command_is_passed_as_one_argument_never_interpolated(box):
    """A client command containing quotes must reach the shell intact rather than being split."""
    sandbox, rec = box
    command = "python -c 'print(\"ok\")'"
    sandbox.run(workspace=None, command=command, timeout=60)

    assert _shell_argv(rec.calls)[-1] == command


def test_the_auth_vars_are_still_passed_by_name_per_exec(box, monkeypatch):
    """Regression guard on the audit-CRITICAL behaviour this must not disturb: the value comes from
    the client env at EXEC time, so a token-pool rotation is picked up instead of the whole lap
    burning on one dead credential."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-rotated")
    sandbox, rec = box
    sandbox.run(workspace=None, command="true", timeout=60)

    argv = _shell_argv(rec.calls)
    assert "-e" in argv and "CLAUDE_CODE_OAUTH_TOKEN" in argv
    assert "sk-ant-rotated" not in argv, "the VALUE must never reach the command line"
