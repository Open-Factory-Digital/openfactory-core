"""The test suite can never act with real credentials (C-07b).

Found while chasing two tests that failed with `httpx.ReadTimeout` under `pytest-randomly` and
passed in isolation. The traceback:

    tests/test_product_module.py:285
    openfactory/product/module.py:1021  file_issues
    openfactory/product/module.py:462   _read_board
    openfactory/product/module.py:343   token
    openfactory/factory.py:26           github_app_token_from_env
    openfactory/adapters/github_app.py:47  mint_installation_token   ← a real HTTPS call to GitHub

The cause is one line: `openfactory/cli.py:25` calls `load_dotenv()` **at module import time**. So the
moment any test imports `openfactory.cli` — directly, or transitively — the whole of `.env` enters the
process: `OPENFACTORY_GH_APP_ID`, `OPENFACTORY_GH_APP_INSTALLATION_ID`, `OPENFACTORY_GH_APP_KEY`, `SLACK_BOT_TOKEN`,
`TEMPORAL_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`. Every later test then runs holding live,
**write-capable** credentials for a real client's repository and Slack workspace.

The timeout is the mild symptom. The real exposure is that these tests were one code path away
from creating an issue, posting a comment or merging a PR on a production client's repository —
and it
would have depended on the random seed, so it passes ninety-nine runs and does something real on
the hundredth.

Two defences, because either alone is one mistake from failing:

    the cause     importing a module must not mutate global process state; the CLI loads its
                  environment when it RUNS, not when it is imported
    the floor     an autouse fixture strips real credentials from the session, so even a future
                  import-time loader cannot hand a test something live

This file is the reachability guard for both.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

#: Everything in `.env` that authenticates against something real. Not an exhaustive list of
#: secrets — an exhaustive list of things that would let a test ACT.
LIVE_CREDENTIALS = [
    "OPENFACTORY_GH_APP_ID",
    "OPENFACTORY_GH_APP_INSTALLATION_ID",
    "OPENFACTORY_GH_APP_KEY",
    "OPENFACTORY_GH_APP_KEY_CONTENT",
    "OPENFACTORY_BOT_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "SLACK_SIGNING_SECRET",
    "TEMPORAL_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
]


@pytest.mark.parametrize("name", LIVE_CREDENTIALS)
def test_no_live_credential_is_visible_to_a_test(name):
    """The floor. If this fails, some test in this session is holding a key to production."""
    assert not os.environ.get(name), (
        f"{name} is set during the test run. A test can now act against real infrastructure, "
        "and which test does depends on the random seed."
    )


def test_the_app_token_minter_finds_nothing_to_mint():
    """One level past the variables: the function that turns them into a network call must come
    back empty. This is what the two flaky tests actually reached."""
    from openfactory.factory import github_app_token_from_env

    assert github_app_token_from_env() is None


def test_the_forge_token_is_empty():
    from openfactory.credentials import forge_token

    assert not forge_token()


def test_importing_the_cli_does_not_load_dotenv():
    """The cause, asserted directly and in a CLEAN process — inside this session the fixture has
    already stripped everything, so an in-process check would pass even unfixed.

    A library module that mutates `os.environ` on import is a trap for every caller: the CLI, the
    worker, a notebook, and a test suite all inherit a side effect none of them asked for.
    """
    code = textwrap.dedent("""
        import os, sys
        marker = "OPENFACTORY_DOTENV_CANARY"
        before = os.environ.get(marker)
        import openfactory.cli  # noqa: F401
        after = os.environ.get(marker)
        # The canary lives in .env only if someone put it there; what we really assert is that
        # importing the CLI changed NOTHING about the environment.
        assert before == after, "importing sdlc.cli mutated the environment"
        # And specifically: the credentials that caused the incident must not have appeared.
        leaked = [k for k in ("OPENFACTORY_GH_APP_ID", "OPENFACTORY_GH_APP_KEY", "SLACK_BOT_TOKEN",
                              "TEMPORAL_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
                  if os.environ.get(k)]
        assert not leaked, f"importing sdlc.cli loaded live credentials: {leaked}"
        print("OK")
    """)
    env = {k: v for k, v in os.environ.items() if k not in LIVE_CREDENTIALS}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), env=env)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_cli_still_loads_its_environment_when_it_RUNS():
    """The fix must not break the CLI. `sdlc` is meant to pick up `.env` — the point is only that
    it does so on invocation, where a human asked for it, rather than on import, where nobody
    did."""
    from openfactory import cli

    assert hasattr(cli, "_load_environment"), (
        "the dotenv load must exist as a callable the CLI invokes, not as an import-time statement"
    )


def test_the_environment_is_loaded_before_a_command_runs(monkeypatch, tmp_path):
    """A loader nothing calls is worse than the import-time version it replaced: the CLI would
    silently stop finding its credentials, and the first symptom would be an auth error in front
    of a client."""
    from typer.testing import CliRunner

    from openfactory import cli

    calls: list[int] = []
    monkeypatch.setattr(cli, "_load_environment", lambda: calls.append(1))
    CliRunner().invoke(cli.app, ["conformance", "--help"])
    assert calls, "no CLI command loaded the environment"
