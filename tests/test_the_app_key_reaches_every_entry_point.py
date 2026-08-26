"""The App private key must resolve wherever it is delivered, from any entry point.

FOUND INSIDE THE COMPOSE WORKER. `docker-compose.yml` passes `OPENFACTORY_GH_APP_KEY_CONTENT`, because
that is how a secret arrives when it is not a file — Secrets Manager, an env var, a compose file.
Every reader of the credential asked for `OPENFACTORY_GH_APP_KEY`, a PATH. Two places bridged the gap by
writing a temp file at import time — `runtime/boxed_job.py` for the task, `api/app.py` for
the panel — and the comment in the second says "same as the worker/task do". Nothing else did. So
`python -m openfactory.cli doctor` inside that same container had no credential at all, and `gh` answered
"please run gh auth login" on a machine holding a perfectly good private key.

THE FIX IS NOT A THIRD MATERIALISER. `mint_installation_token(private_key=...)` takes the PEM as
CONTENT — it always did. The temp file existed only because the callers read a path before calling
it. So the resolution moves into `openfactory/credentials.py`, beside the tokens, where the composition
root already answers "what credential does this process have": content if content was delivered,
otherwise the file at the path. No temp file, no 0600 race, no import-order dependency, and every
entry point — CLI, worker, panel, task — gets it by asking the same function.

The guard below is the reachability half: it is not enough that `app_private_key()` is correct, it
has to be what the minting paths actually call. That is this repository's signature defect, and a
credential helper nobody calls is a particularly quiet instance of it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

PEM = "-----BEGIN RSA PRIVATE KEY-----\nnot-a-real-key\n-----END RSA PRIVATE KEY-----\n"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("OPENFACTORY_GH_APP_KEY", "OPENFACTORY_GH_APP_KEY_CONTENT", "OPENFACTORY_GH_APP_ID",
                "OPENFACTORY_GH_APP_INSTALLATION_ID"):
        monkeypatch.delenv(var, raising=False)


# ── the resolution ──────────────────────────────────────────────────────────────────────────────

def test_content_is_accepted_directly(monkeypatch):
    """The compose and Secrets Manager shape. Before this, content-without-path meant no key."""
    from openfactory.credentials import app_private_key

    monkeypatch.setenv("OPENFACTORY_GH_APP_KEY_CONTENT", PEM)
    assert app_private_key() == PEM


def test_a_path_still_works(monkeypatch, tmp_path):
    """The laptop and the terraform-mounted-file shape. Both deployments in flight use this."""
    from openfactory.credentials import app_private_key

    key = tmp_path / "bot.pem"
    key.write_text(PEM)
    monkeypatch.setenv("OPENFACTORY_GH_APP_KEY", str(key))
    assert app_private_key() == PEM


def test_content_wins_over_a_path_that_does_not_exist(monkeypatch):
    """Ordering matters and the safe order is content-first: a stale `OPENFACTORY_GH_APP_KEY` pointing at
    a file that is not in this container must not shadow the key that was actually delivered."""
    from openfactory.credentials import app_private_key

    monkeypatch.setenv("OPENFACTORY_GH_APP_KEY_CONTENT", PEM)
    monkeypatch.setenv("OPENFACTORY_GH_APP_KEY", "/nowhere/bot.pem")
    assert app_private_key() == PEM


def test_nothing_configured_is_None_not_an_exception(monkeypatch):
    """Its callers ask "do we have an App?" — a question, not an assertion. Raising here would
    turn "this deployment uses a PAT" into a crash."""
    from openfactory.credentials import app_private_key

    assert app_private_key() is None


def test_an_unreadable_path_is_None_and_says_so(monkeypatch, caplog):
    """Silence here means the forge simply appears unauthenticated, three layers away."""
    from openfactory.credentials import app_private_key

    monkeypatch.setenv("OPENFACTORY_GH_APP_KEY", "/definitely/not/here.pem")
    with caplog.at_level("WARNING"):
        assert app_private_key() is None
    assert any("here.pem" in r.getMessage() for r in caplog.records), caplog.text


# ── reachability: the minting paths must go through it ──────────────────────────────────────────

MINTERS = [
    "openfactory/factory.py",
    "openfactory/adapters/github_app.py",
    "openfactory/cli.py",
]


@pytest.mark.parametrize("rel", MINTERS)
def test_no_minting_path_reads_the_key_file_by_hand(rel):
    """The guard that keeps the helper from becoming decorative. Each of these used to do
    `Path(key).expanduser().read_text()`, which is exactly the line that cannot see a key delivered
    as content."""
    src = (ROOT / rel).read_text()
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "read_text"):
            continue
        rendered = ast.unparse(node)
        if "key" in rendered.lower():
            offenders.append(f"{rel}:{node.lineno} — {rendered}")
    assert not offenders, (
        "a minting path reads the App key from a file path directly, so it cannot see a key "
        "delivered as OPENFACTORY_GH_APP_KEY_CONTENT:\n  " + "\n  ".join(offenders)
    )


def test_the_token_minter_gets_content_from_a_content_only_environment(monkeypatch):
    """End to end through the real function, with the network stubbed: content in the environment
    must arrive at `mint_installation_token` as the PEM."""
    import openfactory.adapters.github_app as ga

    seen = {}

    def _fake(*, app_id, private_key, installation_id):
        seen.update(app_id=app_id, private_key=private_key, installation_id=installation_id)
        return ("ghs_stub", "2026-01-01T00:00:00Z")

    monkeypatch.setattr(ga, "mint_installation_token", _fake)
    monkeypatch.setenv("OPENFACTORY_GH_APP_ID", "12345")
    monkeypatch.setenv("OPENFACTORY_GH_APP_INSTALLATION_ID", "67890")
    monkeypatch.setenv("OPENFACTORY_GH_APP_KEY_CONTENT", PEM)

    from openfactory.factory import github_app_token_from_env

    assert github_app_token_from_env() == "ghs_stub"
    assert seen["private_key"] == PEM
    assert seen["installation_id"] == "67890"
