"""The Azure DevOps credential: a PAT when a deployment holds one, a minted JWT when it does not.

TWO DEPLOYMENTS, ONE ADAPTER, AND THEY PULL IN OPPOSITE DIRECTIONS.

    hosted    a SERVICE USER's PAT in the environment. Long-lived, depends on nobody being
              logged in, and the container it runs in has no Azure CLI at all.
    a laptop  inside an enterprise tenant where a person cannot create a PAT. Their only
              credential is `az account get-access-token`, and it lasts about an hour.

The first must never spawn a subprocess and must never change; the second must survive a job that
outlives one token. `token_for` is where both are answered, and it is the single place every Azure
axis reaches its credential through — the tracker, the board, the forge and the pipelines all build
the same shared client.

WHAT THIS FILE WAS WRITTEN FOR, measured on a real Azure DevOps deployment: `token_for` re-read
`os.environ` at each use, which LOOKS like a refresh and is not — a process's environment does not
renew itself, so a worker started with a JWT re-read the same expired one until it was restarted.
The re-resolution machinery was already built and correct; the value it re-resolved was frozen.

The client's half is the second mouth of the same defect. The forge and the board resolve their
credential per call and say so in their own comments; the TRACKER holds one client for the life of
the job, and the tracker is what moves a card to Done — the last thing a job does, on the token it
was built with.
"""

from __future__ import annotations

import json

import pytest

from openfactory.adapters import azure_devops as ado
from openfactory.adapters.azure_devops import AzureDevOpsClient, az_token, token_for
from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker

JWT = "ey" + ".a.b"          # the shape `_auth_header` reads as a Bearer credential
PAT = "x" * 52               # what a service user's PAT looks like

#: THE REAL MINTER, captured at import — before `conftest._the_suite_never_borrows_this_machines_az_login`
#: replaces the module's, which it does per test. Section 3 below is the only place that drives the
#: subprocess layer, and it must drive the actual one: pointed at the neutralised stand-in, every
#: assertion there is `None == None` and the whole section passes against reverted code.
_REAL_AZ_MINT = ado._az_mint


def _mint(token: str, *, expires_in: float, minted: list | None = None):
    """An `_az_mint` that answers `token`, recording each call so a test can count the subprocesses
    a real one would have spawned."""
    import time

    def go():
        if minted is not None:
            minted.append(token)
        return token, time.time() + expires_in

    return go


# ── 1. the hosted deployment: the PAT wins, and nothing is spawned ──────────────────────────────

def test_a_service_users_PAT_wins_and_the_az_CLI_is_never_reached(monkeypatch):
    """THE PRODUCTION PATH. A deployment that set the variable has already said what its credential
    is. Reaching the CLI to second-guess it would be wrong twice over: it would prefer a human's
    identity to the service user's, and it would spawn a process per call in a container that has
    no `az` to spawn."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", PAT)
    monkeypatch.setattr(ado, "_az_mint", lambda: pytest.fail(
        "the PAT was set and the Azure CLI was reached anyway"))

    assert token_for() == PAT


def test_the_variable_a_project_NAMES_also_wins_over_the_mint(monkeypatch):
    """`options.token_env` is the same promise one level down — the pattern every other axis uses.
    A deployment driving two ADO organisations names a variable per project, and the fallback must
    not quietly reunify them onto one machine login."""
    monkeypatch.setenv("ADO_FOR_THIS_CLIENT", PAT)
    monkeypatch.setattr(ado, "_az_mint", lambda: pytest.fail(
        "a named variable was set and the Azure CLI was reached anyway"))

    assert token_for({"token_env": "ADO_FOR_THIS_CLIENT"}) == PAT


def test_no_az_and_no_PAT_is_None_rather_than_a_raise(monkeypatch):
    """The deployed container's ordinary state if its PAT is ever missing: no Azure CLI to call.
    `None` here is what produces the shared client's sentence naming the variable to set, which is
    an actionable error; an exception out of a credential lookup is a stack trace instead."""
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    monkeypatch.setattr(ado, "_az_mint", lambda: None)
    monkeypatch.setattr(ado, "_az_cached", None)

    assert token_for() is None


def test_a_missing_az_binary_is_absorbed_by_the_minter_itself(monkeypatch):
    """The absorption is `_az_mint`'s own, so the deployed container never sees an exception even
    though nothing there patches anything. A raise from `subprocess.run` is the shape a machine
    with no Azure CLI produces."""
    def refuse(*a, **kw):
        raise FileNotFoundError("az")

    monkeypatch.setattr(ado.subprocess, "run", refuse)

    assert _REAL_AZ_MINT() is None


# ── 2. the laptop: a job that outlives one token still authenticates ────────────────────────────

def test_an_empty_variable_falls_back_to_the_machines_az_login(monkeypatch):
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    monkeypatch.setattr(ado, "_az_mint", _mint(JWT, expires_in=3600))
    monkeypatch.setattr(ado, "_az_cached", None)

    assert token_for() == JWT


def test_a_token_near_its_expiry_is_minted_AGAIN_so_a_long_job_still_pushes(monkeypatch):
    """THE GUARD THIS FILE EXISTS FOR. A coding job can run for hours; the JWT lasts about one. The
    late push and the pull request that follows it must not carry the credential the job STARTED
    with."""
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    monkeypatch.setattr(ado, "_az_cached", None)

    minted: list[str] = []
    monkeypatch.setattr(ado, "_az_mint", _mint("first", expires_in=60, minted=minted))
    assert az_token() == "first"

    # 60 seconds left is inside the refresh margin: this is the hour-old token, not a fresh one.
    monkeypatch.setattr(ado, "_az_mint", _mint("second", expires_in=3600, minted=minted))
    assert az_token() == "second", "the job would push with a credential about to expire"
    assert minted == ["first", "second"]


def test_a_fresh_token_is_CACHED_so_one_job_does_not_spawn_az_per_call(monkeypatch):
    """`push_remote()` alone is called at ten sites in the orchestrator and the client is rebuilt
    per call, so an uncached mint is a subprocess on every HTTP request the platform makes."""
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    monkeypatch.setattr(ado, "_az_cached", None)
    minted: list[str] = []
    monkeypatch.setattr(ado, "_az_mint", _mint(JWT, expires_in=3600, minted=minted))

    assert [az_token(), az_token(), az_token()] == [JWT, JWT, JWT]
    assert minted == [JWT], f"{len(minted)} subprocesses where one was enough"


def test_a_failed_refresh_does_not_evict_a_credential_that_is_still_valid(monkeypatch):
    """`az` fails for reasons that pass on their own — off the VPN for a minute, a throttled
    tenant. Dropping a token still good for another minute because one attempt failed would turn a
    blip into the mid-job auth failure this whole path exists to prevent."""
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    monkeypatch.setattr(ado, "_az_cached", None)
    monkeypatch.setattr(ado, "_az_mint", _mint("live", expires_in=120))
    assert az_token() == "live"

    monkeypatch.setattr(ado, "_az_mint", lambda: None)

    assert az_token() == "live"


def test_a_refresh_that_fails_on_an_EXPIRED_token_answers_None_rather_than_the_dead_one(
        monkeypatch):
    """The other side of that tolerance. A token past its stated expiry is not a credential, and
    returning it produces a 401 whose message blames the token instead of the failed refresh."""
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    monkeypatch.setattr(ado, "_az_cached", None)
    monkeypatch.setattr(ado, "_az_mint", _mint("dead", expires_in=-1))
    assert az_token() == "dead"          # minted just now; the freshness gate is the NEXT caller's

    monkeypatch.setattr(ado, "_az_mint", lambda: None)

    assert az_token() is None


# ── 3. what the CLI actually answers ────────────────────────────────────────────────────────────

def _az_answering(payload: str, *, returncode: int = 0):
    class Done:
        pass

    done = Done()
    done.returncode, done.stdout, done.stderr = returncode, payload, ""
    return lambda *a, **kw: done


def test_the_expiry_read_is_epoch_seconds_and_not_the_local_wall_time_sibling(monkeypatch):
    """`az` answers BOTH `expires_on` (epoch) and `expiresOn` (local wall time, no zone). Reading
    the second parses to a different instant on any machine whose timezone is not the one the CLI
    formatted it in — a token treated as an hour fresher or an hour staler than it is, and the
    stale direction is a credential handed out after it died."""
    monkeypatch.setattr(ado.subprocess, "run", _az_answering(json.dumps({
        "accessToken": JWT,
        "expiresOn": "2026-08-28 13:28:28.000000",
        "expires_on": 1787920108,
        "tokenType": "Bearer",
    })))

    assert _REAL_AZ_MINT() == (JWT, 1787920108.0)


def test_a_nonzero_exit_is_no_credential_EVEN_WHEN_the_CLI_still_printed_one(monkeypatch):
    """THE EXIT CODE IS AUTHORITATIVE, and it has to be checked for its own sake rather than left
    to the parse below to notice. `az` exits nonzero while still writing a payload to stdout — a
    refresh that failed against a token it had cached, an expired login it can still describe — and
    a mint that reads the payload anyway hands out a credential the CLI has just refused to vouch
    for. An empty stdout hides this: it is caught downstream by the empty-token check, so a guard
    written with one measures nothing."""
    monkeypatch.setattr(ado.subprocess, "run", _az_answering(json.dumps({
        "accessToken": JWT, "expires_on": 1787920108,
    }), returncode=1))

    assert _REAL_AZ_MINT() is None


def test_output_that_is_not_the_documented_JSON_is_no_credential(monkeypatch):
    """`az` prints warnings and upgrade notices to stdout in some configurations."""
    monkeypatch.setattr(ado.subprocess, "run", _az_answering("WARNING: an upgrade is available"))

    assert _REAL_AZ_MINT() is None


def test_an_answer_with_no_expiry_is_still_usable_and_still_expires(monkeypatch):
    """A token trusted forever is the original defect with an extra step."""
    monkeypatch.setattr(ado.subprocess, "run",
                        _az_answering(json.dumps({"accessToken": JWT})))

    minted = _REAL_AZ_MINT()

    assert minted is not None and minted[0] == JWT
    import time
    assert 0 < minted[1] - time.time() <= 3600


def test_the_minted_token_is_sent_as_a_BEARER_credential():
    """The shape check that makes the two credential kinds interchangeable everywhere else."""
    assert ado._auth_header(JWT).startswith("Bearer ")
    assert ado._auth_header(PAT).startswith("Basic ")


# ── 4. the shared client resolves at each use, never at construction ────────────────────────────

def test_the_shared_client_resolves_its_credential_at_each_CALL(monkeypatch):
    """It was `self.token = token or token_for(options)` in `__init__`. Every axis that keeps one
    client — the tracker keeps it for the whole job — therefore carried the credential the job
    started with, however long the job ran."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "first")
    client = AzureDevOpsClient(organization="acme-ai", project="factory")
    assert client.token == "first"

    monkeypatch.setenv("AZURE_DEVOPS_PAT", "refreshed")

    assert client.token == "refreshed"


def test_an_explicit_token_handed_to_the_client_still_wins(monkeypatch):
    """The forge passes `token=self.token`, already resolved through its own per-use property. That
    value is the one thing the client cannot work out for itself, so it must not be re-derived."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "the-environments")

    assert AzureDevOpsClient(organization="acme-ai", project="factory",
                             token="the-callers").token == "the-callers"


def test_the_client_reads_the_variable_the_PROJECT_names(monkeypatch):
    monkeypatch.setenv("ADO_FOR_THIS_CLIENT", "named")
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)

    assert AzureDevOpsClient(organization="acme-ai", project="factory",
                             options={"token_env": "ADO_FOR_THIS_CLIENT"}).token == "named"


def test_the_TRACKER_that_closes_a_long_job_moves_the_card_with_a_FRESH_token(monkeypatch):
    """The end-to-end shape of the defect, on the axis that has it. The tracker builds one client in
    `__init__` and uses it hours later to move the card to Done and post the closing comment."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "at-job-start")
    tracker = AzureBoardsTracker(organization="acme-ai", project="factory")
    assert tracker.ado.token == "at-job-start"

    monkeypatch.setenv("AZURE_DEVOPS_PAT", "three-hours-later")

    assert tracker.ado.token == "three-hours-later", (
        "the card would be moved with the credential the job started with"
    )


def test_no_credential_anywhere_still_raises_the_sentence_that_names_the_variable(monkeypatch):
    """The honest error is load-bearing: it is what a deployment missing its PAT reads instead of a
    bare 401 from Azure."""
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    monkeypatch.setattr(ado, "_az_mint", lambda: None)
    monkeypatch.setattr(ado, "_az_cached", None)

    with pytest.raises(ado.AzureDevOpsError, match="AZURE_DEVOPS_PAT"):
        AzureDevOpsClient(organization="acme-ai", project="factory").call("GET", "wit/wiql")
