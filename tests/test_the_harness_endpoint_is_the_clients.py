"""The proof probes the endpoint the harness will ACTUALLY use (C-38, #81).

`box_prove` hardcoded `https://api.anthropic.com/v1/messages`, and that proof is what gates
pickup. `box.env`'s own docstring had already named the Bedrock and gateway routes as the reason
it exists — so the mechanism was declared ready while the gate still assumed one vendor.

Three failures came out of that one string, and each has a test here:

  * the FALSE BLOCK — a client running the harness against their own Bedrock account, behind a
    proxy that (correctly) does not allow `api.anthropic.com`, is refused pickup for a host their
    box never contacts;
  * the FALSE PASS — a proxy that allows Anthropic but not the client's own Bedrock endpoint gets
    a green proof and dies on the first real agent call, at agent prices;
  * the WRONG QUESTION — a Codex or Kimi deployment proven against Anthropic's API either way.

And the fourth thing the endpoint alone cannot see: a worker holding `ANTHROPIC_BASE_URL` that
`box.env` does not carry INTO the box. From the worker the route looks configured; the box runs
without it. That is what `harness auth` is for.
"""

from __future__ import annotations

from openfactory.adapters.agent.routes import ENDPOINT_OVERRIDE, resolve_route
from openfactory.contracts.project import Project


def _project(**kw) -> Project:
    return Project(name="p", repo_path="/tmp/p", **kw)


def _clear(monkeypatch):
    from openfactory.adapters.agent import registry as harnesses

    for var in (*harnesses.ROLES.values(), *harnesses.ROLE_MODELS.values(), ENDPOINT_OVERRIDE,
                "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                "AWS_REGION", "AWS_DEFAULT_REGION", "CLOUD_ML_REGION", "VERTEX_REGION"):
        monkeypatch.delenv(var, raising=False)


# ── which host, for which route ──────────────────────────────────────────────────────────────────

def test_the_default_stays_exactly_where_it_was(monkeypatch):
    """Every deployment running today takes this route. It must not move."""
    _clear(monkeypatch)
    route = resolve_route(_project(), env={})
    assert route.name == "anthropic"
    assert route.endpoint == "https://api.anthropic.com/v1/messages"


def test_bedrock_is_probed_at_the_clients_own_regional_endpoint(monkeypatch):
    """The first enterprise client's route. Anthropic's API is not on its path at all."""
    _clear(monkeypatch)
    route = resolve_route(_project(), env={"CLAUDE_CODE_USE_BEDROCK": "1",
                                           "AWS_REGION": "eu-west-2"})
    assert route.name == "bedrock"
    assert route.endpoint == "https://bedrock-runtime.eu-west-2.amazonaws.com"
    assert "anthropic.com" not in route.endpoint


def test_a_gateway_is_probed_at_the_gateway(monkeypatch):
    """`ANTHROPIC_BASE_URL` is how a Foundry-hosted Claude is reached today: the harness speaks
    its own protocol and the gateway translates."""
    _clear(monkeypatch)
    route = resolve_route(_project(), env={"ANTHROPIC_BASE_URL": "https://llm.corp.internal/v1"})
    assert route.name == "gateway"
    assert route.endpoint == "https://llm.corp.internal/v1"


def test_bedrock_with_no_region_refuses_to_invent_one(monkeypatch):
    """A guessed region builds a real-looking URL for an endpoint that does not serve this client
    — a probe that answers proves nothing and a probe that fails blocks pickup for the wrong
    reason. Empty endpoint plus a named unresolved variable is the honest answer."""
    _clear(monkeypatch)
    route = resolve_route(_project(), env={"CLAUDE_CODE_USE_BEDROCK": "1"})
    assert route.endpoint == ""
    assert "AWS_REGION" in route.unresolved


def test_an_unknown_harness_admits_it_rather_than_guessing(monkeypatch):
    """A guessed host that refuses pickup is the same damage as the bug, wearing a helmet."""
    _clear(monkeypatch)
    route = resolve_route(_project(harness="kimi"), env={})
    assert route.endpoint == ""
    assert ENDPOINT_OVERRIDE in route.remedy


def test_the_override_beats_every_rule(monkeypatch):
    """No table here can enumerate a private VPC endpoint or an on-prem gateway."""
    _clear(monkeypatch)
    route = resolve_route(
        _project(), env={ENDPOINT_OVERRIDE: "https://vpce-123.bedrock.eu-west-2.vpce.amazonaws.com",
                         "CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "eu-west-2"})
    assert route.endpoint.startswith("https://vpce-123")


def test_a_falsey_bedrock_flag_is_not_bedrock(monkeypatch):
    """`CLAUDE_CODE_USE_BEDROCK=0` is how an operator turns the route OFF."""
    _clear(monkeypatch)
    route = resolve_route(_project(), env={"CLAUDE_CODE_USE_BEDROCK": "0"})
    assert route.name == "anthropic"


def test_the_harness_the_project_chose_decides(monkeypatch):
    """The route is per-project, like the harness and the model it belongs beside."""
    _clear(monkeypatch)
    assert resolve_route(_project(harness="codex"), env={}).endpoint.startswith(
        "https://api.openai.com")


# ── what the route needs INSIDE the box ──────────────────────────────────────────────────────────

def test_a_route_is_missing_what_the_box_cannot_see(monkeypatch):
    _clear(monkeypatch)
    route = resolve_route(_project(), env={"ANTHROPIC_BASE_URL": "https://gw/v1"})
    assert route.missing({}) == ["ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY"]
    assert route.missing({"ANTHROPIC_API_KEY": "x"}) == []


def test_an_empty_value_is_missing_not_present(monkeypatch):
    """A named-but-empty variable is the shape a secret-delivery failure takes, and it reads as
    compliance to anything that only checks the key exists."""
    _clear(monkeypatch)
    route = resolve_route(_project(), env={})
    assert route.missing({"ANTHROPIC_API_KEY": "  "}) != []


def test_bedrock_does_not_demand_a_credential_VARIABLE(monkeypatch):
    """A task role delivers AWS credentials with no variable set at all, so requiring one would
    fail the deployments that are configured best. The remedy says it; the gate does not assert
    it."""
    _clear(monkeypatch)
    route = resolve_route(_project(), env={"CLAUDE_CODE_USE_BEDROCK": "1",
                                           "AWS_REGION": "eu-west-2"})
    satisfied = route.missing({"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "eu-west-2"})
    assert satisfied == []
    assert "credential" in route.remedy


# ── and the proof uses it ────────────────────────────────────────────────────────────────────────

def _probes(**over):
    """A green box, so every test below fails for exactly the reason it names."""
    from openfactory import box_prove as bp

    base = dict(
        resolve_digest=lambda _i: "sha256:" + "a" * 64,
        image_platform=lambda _i: ("linux", "amd64", "glibc"),
        toolbox_stamp=lambda: {"variant": "linux-amd64-glibc", "harnesses": ["claude"]},
        contract=lambda _i: {},
        run_in_box=lambda _c: (0, "ok"),
        harness_reachable=lambda: (True, "200"),
        setup_commands=list,
        validate_commands=dict,
        harness_name=lambda: "claude",
    )
    base.update(over)
    return bp.Probes(**base)


def test_the_proof_NAMES_the_endpoint_it_probed(monkeypatch):
    """`the harness endpoint is not reachable` is unusable when four hosts are possible."""
    from openfactory import box_prove as bp

    _clear(monkeypatch)
    route = resolve_route(_project(), env={"CLAUDE_CODE_USE_BEDROCK": "1",
                                           "AWS_REGION": "eu-west-2"})
    proof = bp.prove("p", "img", _probes(auth_route=lambda: route,
                                         harness_reachable=lambda: (False, "000")))
    net = [f for f in proof.findings if f.check == "network"][0]
    assert not net.ok
    assert "bedrock-runtime.eu-west-2.amazonaws.com" in net.message


def test_a_credential_that_does_not_reach_the_box_FAILS_the_proof(monkeypatch):
    """The one thing invisible from the worker: it holds the variable, `box.env` does not carry
    it, and the box runs without it."""
    from openfactory import box_prove as bp

    _clear(monkeypatch)
    route = resolve_route(_project(), env={"ANTHROPIC_BASE_URL": "https://gw/v1"})
    proof = bp.prove("p", "img", _probes(auth_route=lambda: route, env_in_box=lambda _n: {}))
    auth = [f for f in proof.findings if f.check == "harness auth"][0]
    assert not auth.ok
    assert "gateway" in auth.message
    assert "box.env" in auth.remedy
    assert not proof.ok


def test_the_same_credential_PRESENT_passes(monkeypatch):
    """The positive twin: without it, a check that can only fail proves nothing."""
    from openfactory import box_prove as bp

    _clear(monkeypatch)
    route = resolve_route(_project(), env={"ANTHROPIC_BASE_URL": "https://gw/v1"})
    proof = bp.prove("p", "img", _probes(auth_route=lambda: route,
                                         env_in_box=lambda _n: {"ANTHROPIC_API_KEY": "1"}))
    assert [f for f in proof.findings if f.check == "harness auth"][0].ok
    assert proof.ok


def test_a_box_that_cannot_ANSWER_is_not_reported_as_missing(monkeypatch):
    """`None` means the probe could not look. Reading that as absence would refuse pickup for
    every correctly-configured deployment whose box declined one shell command."""
    from openfactory import box_prove as bp

    _clear(monkeypatch)
    route = resolve_route(_project(), env={"ANTHROPIC_BASE_URL": "https://gw/v1"})
    proof = bp.prove("p", "img", _probes(auth_route=lambda: route, env_in_box=lambda _n: None))
    auth = [f for f in proof.findings if f.check == "harness auth"][0]
    assert auth.ok and "not checked" in auth.message


def test_an_unknown_endpoint_does_not_claim_the_host_answers(monkeypatch):
    """The old code's green said "the harness endpoint answers". For a route with no known host
    that sentence is false, and false comfort in a proof is worse than a gap."""
    from openfactory import box_prove as bp

    _clear(monkeypatch)
    route = resolve_route(_project(harness="kimi"), env={})
    proof = bp.prove("p", "img", _probes(auth_route=lambda: route))
    net = [f for f in proof.findings if f.check == "network"][0]
    assert "not proven" in net.message
    assert "answers" not in net.message


def test_the_probe_is_never_asked_when_there_is_nothing_to_probe(monkeypatch):
    """Probing a guessed host is how a false failure gets manufactured."""
    from openfactory import box_prove as bp

    _clear(monkeypatch)
    called = []
    route = resolve_route(_project(harness="kimi"), env={})
    bp.prove("p", "img", _probes(auth_route=lambda: route,
                                 harness_reachable=lambda: called.append(1) or (True, "")))
    assert called == []


def test_the_in_box_probe_prints_the_NAME_and_never_the_value():
    """The proof is written to a file, logged, and rendered in the panel. `echo $VAR` instead of
    `echo VAR` would put a live credential in all three, from the one component whose entire
    purpose is to be safe to run before anything else does."""
    from openfactory.box_prove import presence_script

    script = presence_script(("ANTHROPIC_API_KEY", "AWS_REGION"))
    assert "echo ANTHROPIC_API_KEY" in script
    assert "echo $ANTHROPIC_API_KEY" not in script
    assert 'echo "$' not in script


def test_the_presence_probe_survives_a_variable_that_is_unset():
    """`set -u` or a non-zero tail would turn "this one is not set" into "the box could not
    answer", and the caller treats those two as opposites."""
    from openfactory.box_prove import presence_script

    assert presence_script(("A",)).rstrip().endswith("true")


def test_the_probe_reads_only_the_names_it_asked_about(monkeypatch):
    """The box's own output is untrusted input: a client image whose profile prints a banner
    would otherwise have every line read as a satisfied requirement."""
    from openfactory import box_prove as bp

    _clear(monkeypatch)
    route = resolve_route(_project(), env={"ANTHROPIC_BASE_URL": "https://gw/v1"})
    noise = {"Welcome to Corp Linux": "1", "ANTHROPIC_API_KEY": "1"}
    proof = bp.prove("p", "img", _probes(auth_route=lambda: route, env_in_box=lambda _n: noise))
    assert [f for f in proof.findings if f.check == "harness auth"][0].ok
