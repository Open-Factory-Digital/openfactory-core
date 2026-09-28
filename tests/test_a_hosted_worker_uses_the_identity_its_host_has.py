"""A hosted worker can use the identity its machine was given, declared, not guessed (#373).

WHAT IT DID: a compose deployment on a cloud VM whose host holds a managed identity, added to the
organisation as a user, could not reach its forge from the worker. The only credential a hosted
worker could hold was a STORED SECRET; the one keyless path, a person's `az` login, lives on the
host and not in the worker container. Reproduced on Azure DevOps: on the VM host, `az login
--identity` minted a JWT that cloned, pushed and opened a pull request; in the worker container on
the same VM, `token_for()` with `AZURE_DEVOPS_PAT` empty answered None. The organisation forbids
long-lived tokens, so the deployment's only way forward was the thing it forbids.

THE FIX IS A THIRD KIND OF SOURCE, NOT A THIRD SPECIAL CASE. An axis declares
`identity: workload` (and `identity_client_id` for a user-assigned identity); the vendor's
credential row answers it through `CredentialRow.source`, the ONE resolution the adapter and the
doctor both ask; the four refresh guarantees the `az` login earned live in `ShortLivedToken`, which
both short-lived sources plug into; and a box is handed a minted value, never the declaration.

The metadata endpoint is faked at `_workload_mint` for the resolution tests, and at the opener for
the one test that reads what the request itself carries.
"""

from __future__ import annotations

import json
import time

import pytest

from openfactory.adapters import azure_devops as ado
from openfactory.adapters.credential.short_lived import ShortLivedToken
from openfactory.contracts.project import Project, ProviderRef

_CREDENTIAL_VARS = (
    "AZURE_DEVOPS_PAT", "OPENFACTORY_FORGE_TOKEN", "OPENFACTORY_BOT_TOKEN",
    "OPENFACTORY_TRACKER_TOKEN", "OPENFACTORY_GH_APP_ID", "OPENFACTORY_GH_APP_INSTALLATION_ID",
    "OPENFACTORY_GH_APP_KEY", "OPENFACTORY_GH_APP_KEY_CONTENT",
    "OPENFACTORY_BOX_TRACKER_TOKEN", "OPENFACTORY_BOX_FORGE_TOKEN",
)

#: The real minter, captured before `conftest` replaces it for each test — the one test that
#: reads what the request carries calls it with only the opener faked.
_REAL_WORKLOAD_MINT = ado._workload_mint

#: One distinct value per source, so a token names the source it came from.
PAT, LOGIN, IDENTITY, GENERIC = "the-stored-pat", "the-az-login-jwt", "the-identity-jwt", "gh-tok"


@pytest.fixture(autouse=True)
def _no_credential_anywhere(monkeypatch):
    for name in _CREDENTIAL_VARS:
        monkeypatch.delenv(name, raising=False)


def _identity(monkeypatch, *, answers: bool = True, expires_in: float = 3600,
              minted: list | None = None) -> None:
    """The machine's identity, at the seam every request to it goes through. `minted` collects
    the client id of each mint, so a test can count them and tell identities apart."""
    def mint(client_id=""):
        if minted is not None:
            minted.append(client_id)
        if not answers:
            return None
        return f"{IDENTITY}{':' + client_id if client_id else ''}", time.time() + expires_in

    monkeypatch.setattr(ado, "_workload_mint", mint)
    monkeypatch.setattr(ado, "_WORKLOAD", {})


def _login(monkeypatch, *, logged_in: bool) -> list:
    calls: list = []

    def mint():
        calls.append(1)
        return (LOGIN, time.time() + 3600) if logged_in else None

    monkeypatch.setattr(ado, "_az_mint", mint)
    ado._AZ_LOGIN.forget()
    return calls


def _ado(**options) -> Project:
    ref = ProviderRef(kind="azure_devops", repo="api",
                      options={"organization": "acme", "project": "Deskline", **options})
    return Project(name="dsk", repo_path="https://dev.azure.com/acme/Deskline/_git/api",
                   tracker=ref, forge=ref)


def _probe_the_ado_forge(monkeypatch) -> dict:
    from openfactory.adapters.forge import azure_devops as forge_mod

    seen: dict = {}

    def pr_status(self, *, pr, repo=""):
        seen["asked"] = pr
        seen["token"] = self.token
        raise RuntimeError("TF401180: pull request not found")  # 404-shaped: allowed to ask

    monkeypatch.setattr(forge_mod.AzureReposForge, "pr_status", pr_status, raising=True)
    return seen


# ── 1. the reported case: a declared identity is the credential ─────────────────────────────────

def test_a_declared_identity_is_the_credential_with_no_secret_stored(monkeypatch):
    """The deployment that reported this: no PAT, no `az`, a machine identity. The adapter's own
    resolution answers the identity's token."""
    _identity(monkeypatch)
    _login(monkeypatch, logged_in=False)

    assert ado.token_for({"identity": "workload"}) == IDENTITY


def test_a_user_assigned_identity_is_asked_by_its_client_id_and_held_apart(monkeypatch):
    """Two projects on two identities never hand each other a token: one refresh machinery per
    client id, and the client id reaches the mint."""
    minted: list = []
    _identity(monkeypatch, minted=minted)

    a = ado.token_for({"identity": "workload", "identity_client_id": "aaaa"})
    b = ado.token_for({"identity": "workload", "identity_client_id": "bbbb"})
    machine = ado.token_for({"identity": "workload"})

    assert (a, b, machine) == (f"{IDENTITY}:aaaa", f"{IDENTITY}:bbbb", IDENTITY)
    assert minted == ["aaaa", "bbbb", ""]


def test_a_declared_identity_wins_over_a_stored_secret_and_a_login(monkeypatch):
    """A declaration is the axis's credential. A PAT set for ANOTHER project, or a person logged
    in on the host, must not quietly become this axis's credential instead."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", PAT)
    _identity(monkeypatch)
    calls = _login(monkeypatch, logged_in=True)

    assert ado.token_for({"identity": "workload"}) == IDENTITY
    assert calls == [], "a declared identity spawned `az`"


def test_a_declared_identity_that_does_not_answer_is_no_credential_never_a_fallback(monkeypatch):
    """On the wrong machine, a declared identity answers nothing, and that is what is said. It
    does not fall back to a PAT or a login nobody chose for this axis."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", PAT)
    _identity(monkeypatch, answers=False)
    _login(monkeypatch, logged_in=True)

    assert ado.token_for({"identity": "workload"}) is None


@pytest.mark.parametrize("options, says", [
    ({"identity": "vm"}, "names no credential"),
    ({"identity": "workload", "token_env": "MY_PAT"}, "both `token_env`"),
    ({"identity_client_id": "aaaa"}, "no `identity: workload`"),
])
def test_a_declaration_nothing_can_use_is_refused_by_name(monkeypatch, options, says):
    from openfactory.adapters.credential.registry import declared_identity

    monkeypatch.setenv("AZURE_DEVOPS_PAT", PAT)
    monkeypatch.setenv("MY_PAT", PAT)
    _identity(monkeypatch)
    _login(monkeypatch, logged_in=True)

    declared, problem = declared_identity(options)
    assert not declared and says in problem, problem
    assert ado.token_for(options) is None, "a declaration nothing can use fell back to a source"


def test_an_axis_that_declares_nothing_resolves_exactly_as_before(monkeypatch):
    """Every axis written before this existed: the PAT without spawning anything, else the login,
    and the identity is never asked — nothing probes a metadata endpoint because it is there."""
    minted: list = []
    _identity(monkeypatch, minted=minted)

    monkeypatch.setenv("AZURE_DEVOPS_PAT", PAT)
    calls = _login(monkeypatch, logged_in=True)
    assert ado.token_for({}) == PAT and calls == []

    monkeypatch.delenv("AZURE_DEVOPS_PAT")
    assert ado.token_for({}) == LOGIN
    assert minted == [], "an undeclared axis asked the machine's identity"


# ── 2. one refresh machinery for every short-lived source ──────────────────────────────────────

def test_the_identity_is_held_by_the_same_machinery_as_the_login(monkeypatch):
    """One mint per lifetime, renewed early — the guarantees the `az` path earned, not a copy of
    them. `ShortLivedToken` is the one home; both sources are instances of it."""
    minted: list = []
    _identity(monkeypatch, minted=minted, expires_in=3600)

    for _ in range(5):
        assert ado.workload_token() == IDENTITY
    assert len(minted) == 1, "the identity was minted per call rather than per lifetime"

    assert isinstance(ado._AZ_LOGIN, ShortLivedToken)
    assert isinstance(ado._WORKLOAD[""], ShortLivedToken)


def test_an_identity_token_near_its_expiry_is_minted_again(monkeypatch):
    minted: list = []
    _identity(monkeypatch, minted=minted, expires_in=60)  # inside the five-minute margin

    ado.workload_token()
    ado.workload_token()

    assert len(minted) == 2


def test_a_failed_refresh_keeps_a_token_that_is_still_valid():
    answers = iter([("live", time.time() + 120), None])
    held = ShortLivedToken(lambda: next(answers))

    assert held() == "live"   # minted, and inside the margin
    assert held() == "live", "a failed refresh evicted a token still valid for two minutes"


# ── 3. what the request to the endpoint carries ────────────────────────────────────────────────

def test_the_identity_is_asked_of_the_link_local_endpoint_with_no_proxy(monkeypatch):
    """A worker on a corporate network carries `http_proxy`, and `urlopen` honours it: the
    identity's request would leave the machine for a proxy that cannot answer for it. The opener
    is built with no proxy; the request names the resource, the header the endpoint demands, and
    the user-assigned identity when one is declared."""
    import urllib.request

    seen: dict = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"access_token": IDENTITY,
                               "expires_on": str(int(time.time()) + 3600)}).encode()

    class Opener:
        def open(self, request, timeout=None):
            seen["url"] = request.full_url
            seen["metadata"] = request.get_header("Metadata")
            return Response()

    def build_opener(*handlers):
        seen["handlers"] = handlers
        return Opener()

    monkeypatch.setenv("http_proxy", "http://proxy.corp:3128")
    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    token, expires = _REAL_WORKLOAD_MINT("aaaa")

    assert token == IDENTITY and expires > time.time()
    assert seen["url"].startswith(ado.IMDS_TOKEN_URL)
    assert f"resource={ado.ADO_RESOURCE}" in seen["url"] and "client_id=aaaa" in seen["url"]
    assert seen["metadata"] == "true"
    proxies = [h for h in seen["handlers"] if isinstance(h, urllib.request.ProxyHandler)]
    assert proxies and all(not h.proxies for h in proxies), (
        "the identity's request can go through the worker's proxy")


# ── 4. the doctor reports the source the adapter uses (#170's class, for any row) ──────────────

_SCENARIOS = {
    "a stored secret": dict(pat=True, login=False, identity=False, declared=False),
    "a login only": dict(pat=False, login=True, identity=False, declared=False),
    "a stored secret and a login": dict(pat=True, login=True, identity=False, declared=False),
    "a declared identity": dict(pat=False, login=False, identity=True, declared=True),
    "a declared identity beside a PAT and a login": dict(pat=True, login=True, identity=True,
                                                         declared=True),
    "a declared identity that does not answer": dict(pat=True, login=True, identity=False,
                                                     declared=True),
    "the deployment's GitHub token only": dict(pat=False, login=False, identity=False,
                                               declared=False, generic=True),
    "nothing": dict(pat=False, login=False, identity=False, declared=False),
}

#: The token each reported source would hand out — what the adapter must then be holding.
_VALUE_OF = {"env:AZURE_DEVOPS_PAT": PAT, "login:az": LOGIN, "identity:workload": IDENTITY}


@pytest.mark.parametrize("scenario", list(_SCENARIOS))
def test_the_source_the_doctor_reports_is_the_source_the_adapter_uses(monkeypatch, scenario):
    """AGREEMENT, NOT LITERALS. For each combination of sources, the doctor's answer (which
    source, or none) and the token the forge adapter actually authenticates with name the same
    source. #170 was the doctor saying "none" while the adapter pushed; the measured case of this
    issue was the opposite, the doctor counting a GitHub token the Azure adapter never used."""
    from openfactory.adapters.forge.registry import build_forge
    from openfactory.credentials import forge_credential_source, forge_token_for

    s = _SCENARIOS[scenario]
    if s["pat"]:
        monkeypatch.setenv("AZURE_DEVOPS_PAT", PAT)
    if s.get("generic"):
        monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", GENERIC)
    _login(monkeypatch, logged_in=s["login"])
    _identity(monkeypatch, answers=s["identity"])
    project = _ado(**({"identity": "workload"} if s["declared"] else {}))

    reported = forge_credential_source(project)
    used = build_forge(project, token=forge_token_for(project)).token

    assert _VALUE_OF.get(reported) == used, (
        f"{scenario}: the doctor reports {reported or 'no credential'!r}, and the adapter "
        f"authenticates with {used!r}")


def test_the_doctor_names_the_source_that_answered(monkeypatch):
    """A stored secret, a person's login and the machine's own identity are three things to
    rotate, revoke and audit; "reachable" alone does not say which one the factory is using."""
    from openfactory.doctor import probes_for

    _identity(monkeypatch)
    seen = _probe_the_ado_forge(monkeypatch)

    reachable, detail = probes_for(_ado(identity="workload")).forge_reachable()

    assert reachable is True and seen.get("token") == IDENTITY
    assert "identity the platform gave this machine" in detail, detail


def test_a_declaration_nothing_can_use_is_said_as_itself_by_the_doctor(monkeypatch):
    """"No credential is configured" beside `identity: workload` would send the operator to
    configure the stored secret the declaration exists to replace."""
    from openfactory.doctor import _forge, probes_for

    seen = _probe_the_ado_forge(monkeypatch)

    finding = _forge(probes_for(_ado(identity="workload", token_env="MY_PAT")))

    assert not finding.ok and "asked" not in seen
    assert "both `token_env`" in finding.message, finding.message
    assert "token_env" in finding.remedy


def test_the_remedy_names_all_three_sources(monkeypatch):
    from openfactory.adapters.credential.registry import credential_row

    said = credential_row("azure_devops").when_missing
    assert "identity: workload" in said and "az login" in said and "AZURE_DEVOPS_PAT" in said


# ── 5. the box receives a value, never the declaration ─────────────────────────────────────────

def test_a_remote_box_is_handed_the_minted_token_and_not_the_declaration(monkeypatch):
    """A declaration inside a box would ask the metadata endpoint of whatever machine the box runs
    on, from the process that runs agent-written code. The worker mints; the box's options name
    the variable the value travels in, in the declaration's place."""
    from openfactory.credentials import BOX_TOKEN_ENV, box_credential_env, box_options

    _identity(monkeypatch)
    project = _ado(identity="workload", identity_client_id="aaaa")

    options = box_options(project, "forge")
    env = box_credential_env(project)

    assert "identity" not in options and "identity_client_id" not in options
    assert options["token_env"] == BOX_TOKEN_ENV["forge"]
    assert options["organization"] == "acme", "the axis's other options must travel whole (#162)"
    assert env == {BOX_TOKEN_ENV["tracker"]: f"{IDENTITY}:aaaa",
                   BOX_TOKEN_ENV["forge"]: f"{IDENTITY}:aaaa"}
    # …and inside the box, that variable is the axis's credential, through the same resolution.
    monkeypatch.setenv(BOX_TOKEN_ENV["forge"], env[BOX_TOKEN_ENV["forge"]])
    assert ado.token_for(options) == f"{IDENTITY}:aaaa"


def test_an_axis_that_declares_nothing_is_handed_to_the_box_as_before(monkeypatch):
    from openfactory.credentials import box_credential_env, box_options

    project = _ado(token_env="MY_PAT")

    assert box_options(project, "forge") == {"organization": "acme", "project": "Deskline",
                                             "token_env": "MY_PAT"}
    assert box_credential_env(project) == {}


def test_a_declared_identity_that_does_not_answer_launches_no_box(monkeypatch):
    """A box launched without its credential fails inside with a sentence about the wrong thing."""
    from openfactory.credentials import CredentialUnavailable, box_credential_env

    _identity(monkeypatch, answers=False)

    with pytest.raises(CredentialUnavailable, match="forge|tracker"):
        box_credential_env(_ado(identity="workload"))


def test_a_box_handed_a_declaration_anyway_drops_it(capsys):
    """A launcher older than this, or a hand-built box: the declaration is dropped and said, so
    the box never mints from the machine it runs on."""
    from openfactory.runtime.boxed_job import config_from_env

    cfg = config_from_env({
        "OPENFACTORY_PROJECT": "dsk", "OPENFACTORY_ISSUE": "1", "OPENFACTORY_REPO": "api",
        "OPENFACTORY_FORGE_OPTIONS": json.dumps({"identity": "workload", "organization": "acme"}),
    })

    assert cfg.forge_options == {"organization": "acme"}
    assert "declare a machine identity" in capsys.readouterr().out


def test_the_minted_box_token_is_withheld_from_the_agent():
    """The framework in the box pushes with it; the agent in the box must not."""
    from openfactory.adapters.sandbox.worktree import _FORGE_CRED_VARS
    from openfactory.credentials import BOX_TOKEN_ENV

    assert set(BOX_TOKEN_ENV.values()) <= set(_FORGE_CRED_VARS)


# ── 6. the doctor measures whether a box reaches the identity ──────────────────────────────────

def _doctor_box_identity(monkeypatch, *, sandbox: str, reached=None):
    from openfactory.adapters.sandbox import container
    from openfactory.doctor import probes_for
    from openfactory.runtime.temporal import io

    monkeypatch.setattr(io, "default_sandbox", lambda: sandbox)
    asked: list = []

    def measured(network):
        asked.append(network)
        return reached, "172.18.0.0/16" if reached is not None else "docker did not answer"

    monkeypatch.setattr(container, "metadata_reached", measured)
    probes = probes_for(_ado(identity="workload"))
    return probes, asked


def test_a_container_box_that_reaches_the_endpoint_is_red_with_the_rule_that_closes_it(
        monkeypatch):
    probes, asked = _doctor_box_identity(monkeypatch, sandbox="container", reached=True)

    ok, message, remedy = probes.box_identity()

    assert asked and not ok
    assert "169.254.169.254" in message and "DOCKER-USER -s 172.18.0.0/16" in remedy


def test_a_container_box_that_does_not_reach_the_endpoint_is_measured_green(monkeypatch):
    probes, _ = _doctor_box_identity(monkeypatch, sandbox="container", reached=False)

    ok, message, _ = probes.box_identity()

    assert ok and "measured now" in message


def test_an_unmeasurable_box_is_never_reported_as_safe(monkeypatch):
    probes, _ = _doctor_box_identity(monkeypatch, sandbox="container", reached=None)

    ok, message, _ = probes.box_identity()

    assert not ok and "could not be measured" in message


def test_the_worktree_box_is_red_because_the_agent_runs_as_this_machine(monkeypatch):
    probes, asked = _doctor_box_identity(monkeypatch, sandbox="worktree")

    ok, message, remedy = probes.box_identity()

    assert not ok and asked == [], "the worktree box has no network of its own to measure"
    assert "container" in remedy


def test_a_project_that_declares_no_identity_has_no_such_line(monkeypatch):
    from openfactory.doctor import probes_for

    assert probes_for(_ado()).box_identity is None
