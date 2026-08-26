"""Identity is an axis and authorization is policy (C-26, #55).

THE DEEPEST PROBLEM WAS NEVER THE ABSENCE OF SSO, IT WAS THE ABSENCE OF A SUBJECT. There were
three authorization models and they did not know about each other:

    Slack   `project.admins`          an allowlist per project; empty = read-only
    product `project.product.admins`  a second allowlist, for the gestures that WRITE
    panel   `OPENFACTORY_PANEL_TOKEN`        a shared password — everyone holding it was the same person

Two of those rules differing is legitimate: the operator who may skip a job and the client who may
approve a requirement are different trusts. The third is not a rule at all, and it made *who
approved that production release* a question with no answer — which for an enterprise buyer is
audit, and the first thing their security review asks.

Adding OIDC first would have implemented identity a second time, in the layer where it is most
expensive to undo. So the axis comes first and a provider is a row.
"""

from __future__ import annotations

import add_ons
import pytest
from fastapi.testclient import TestClient

from openfactory.identity.base import ANONYMOUS, UNKNOWN, IdentityProvider, Subject
from openfactory.identity.local import LocalIdentity
from openfactory.identity.registry import build_identity
from openfactory.policy import authz


class _Product:
    def __init__(self, admins=(), enabled=True):
        self.admins = list(admins)
        self.enabled = enabled


class _Project:
    def __init__(self, admins=(), product=None, name="demo"):
        self.name = name
        self.admins = list(admins)
        self.product = product


# ── the axis ─────────────────────────────────────────────────────────────────────────────────────

def test_the_local_provider_satisfies_the_port_by_SHAPE():
    assert isinstance(LocalIdentity(env={}), IdentityProvider)


def test_the_registry_builds_it_from_config_and_refuses_what_it_does_not_have():
    """Refusing is the point. The failure mode of this axis is letting the WRONG person in, so a
    deployment naming a provider this build lacks must fail loudly rather than fall back to
    something more permissive."""
    assert isinstance(build_identity({}), LocalIdentity)
    assert isinstance(build_identity({"OPENFACTORY_IDENTITY": "local"}), LocalIdentity)

    with pytest.raises(ValueError, match="unknown identity provider"):
        build_identity({"OPENFACTORY_IDENTITY": "entraid"})


def test_a_per_person_token_resolves_to_that_person():
    """The whole point of the card: the panel can name who acted."""
    provider = LocalIdentity(env={"OPENFACTORY_PANEL_TOKENS": "s3cret-a:alice:Alice Ferreira,"
                                                       "s3cret-b:ana"})

    alice = provider.identify(credential="s3cret-a")
    ana = provider.identify(credential="s3cret-b")

    assert (alice.id, alice.display, alice.via) == ("alice", "Alice Ferreira", "local")
    assert (ana.id, ana.display) == ("ana", "ana"), "a person with no name falls back to their id"
    assert alice.known and ana.known


def test_an_unknown_credential_is_nobody_rather_than_somebody_plausible():
    """An unknown caller who gets a plausible identity is worse than one who is refused: the
    refusal is visible, and the wrong identity is written into an audit line as fact."""
    provider = LocalIdentity(env={"OPENFACTORY_PANEL_TOKENS": "a:alice"})

    assert provider.identify(credential="not-a-token") is None
    assert provider.identify(credential="") is None
    assert provider.identify(credential="   ") is None


def test_the_legacy_shared_token_still_works_and_is_reported_as_anonymous(caplog):
    """Breaking every existing deployment's panel to close an audit gap would close it by locking
    everyone out. So the gap stays reachable and becomes GREPPABLE instead of invisible."""
    provider = LocalIdentity(env={"OPENFACTORY_PANEL_TOKEN": "shared"})

    with caplog.at_level("INFO"):
        who = provider.identify(credential="shared")

    assert who == UNKNOWN
    assert who.via == ANONYMOUS and not who.known
    assert "OPENFACTORY_IDENTITY_ANONYMOUS" in caplog.text


def test_a_person_with_their_own_token_is_not_mistaken_for_the_shared_one():
    """A deployment mid-migration sets both. During that window somebody with their own token must
    be recognised as themselves, which is why the per-person map is consulted first."""
    provider = LocalIdentity(env={"OPENFACTORY_PANEL_TOKENS": "mine:alice", "OPENFACTORY_PANEL_TOKEN": "shared"})

    assert provider.identify(credential="mine").id == "alice"
    assert provider.identify(credential="shared") == UNKNOWN


def test_a_malformed_row_costs_that_person_and_nobody_else(caplog):
    """Half-parsing a row would hand somebody an identity that is not theirs."""
    with caplog.at_level("WARNING"):
        provider = LocalIdentity(env={"OPENFACTORY_PANEL_TOKENS": "broken,,ok:ana"})
        assert provider.identify(credential="ok").id == "ana"
        assert provider.identify(credential="broken") is None

    assert "OPENFACTORY_IDENTITY_BAD_ROW" in caplog.text


def test_the_token_comparison_is_constant_time():
    """This compares a secret reachable from a browser. `==` leaks its prefix to anyone who can
    measure, and a timing bug is invisible in every functional test — so the guard reads the
    source, which is the only place the property is expressible."""
    import inspect

    source = inspect.getsource(LocalIdentity)

    assert "compare_digest" in source
    assert "== person.token" not in source and "token ==" not in source


def test_the_provider_never_raises(monkeypatch):
    """Its callers are request handlers and a chat listener; a provider that throws takes down the
    door rather than closing it."""
    provider = LocalIdentity(env={"OPENFACTORY_PANEL_TOKENS": "a:alice"})
    monkeypatch.setattr("openfactory.identity.local._people", lambda raw: (_ for _ in ()).throw(
        RuntimeError("boom")))

    assert provider.identify(credential="a") is None


# ── the policy ───────────────────────────────────────────────────────────────────────────────────

def test_one_decision_answers_both_scopes():
    """The two allowlists still differ — that difference is legitimate. What moved is the ANSWERING:
    one function reads both, so a fourth surface cannot invent a fourth rule."""
    project = _Project(admins=["U-op"], product=_Product(admins=["U-po"]))
    op, po = Subject(id="U-op", via="slack"), Subject(id="U-po", via="slack")

    assert authz.may(op, project=project, scope=authz.FACTORY)
    assert not authz.may(op, project=project, scope=authz.PRODUCT)
    assert authz.may(po, project=project, scope=authz.PRODUCT)
    assert not authz.may(po, project=project, scope=authz.FACTORY)


def test_an_anonymous_caller_may_do_nothing():
    """`UNKNOWN` is the shared-token panel and a bare CLI. It identifies nobody, so it authorises
    nobody — the split that stops an identity provider from granting its own callers permission."""
    project = _Project(admins=["U-op"], product=_Product(admins=["U-op"]))

    for scope in authz.SCOPES:
        decision = authz.may(UNKNOWN, project=project, scope=scope)
        assert not decision
        assert "could not tell who is asking" in decision.why


def test_an_empty_allowlist_means_nobody_not_everybody():
    """The safe default and the honest one: a deployment that has not said who may act has not
    said it, and guessing "then everyone" is how a factory acts on the word of whoever found the
    URL."""
    assert not authz.may(Subject(id="U1", via="slack"), project=_Project(), scope=authz.FACTORY)


def test_an_unknown_scope_is_REFUSED_not_treated_as_the_default(caplog):
    """A typo would otherwise widen permission silently, which is the one direction this module
    must never fail in."""
    project = _Project(admins=["U1"])

    with caplog.at_level("ERROR"):
        decision = authz.may(Subject(id="U1", via="slack"), project=project, scope="factroy")

    assert not decision
    assert "OPENFACTORY_AUTHZ_UNKNOWN_SCOPE" in caplog.text


def test_a_disabled_product_role_says_so_rather_than_just_no():
    """"You are not on the list" is actionable by an admin; "the product role is off" is actionable
    by whoever configured it. Collapsing both into False is how a support conversation starts."""
    project = _Project(product=_Product(admins=["U1"], enabled=False))

    decision = authz.may(Subject(id="U1", via="slack"), project=project, scope=authz.PRODUCT)

    assert not decision and "not enabled" in decision.why


def test_a_GROUP_authorises_too_so_an_OIDC_provider_needs_no_rewrite():
    """Dead for the local provider, which asserts no groups. It is here because the moment an SSO
    provider exists the allowlist stops being a list of people and becomes a list of groups — and a
    policy that could only compare ids would need rewriting exactly when somebody depends on it."""
    project = _Project(admins=["platform-team"])

    assert authz.may(Subject(id="U1", via="oidc", groups=("platform-team",)), project=project)


def test_a_decision_is_falsy_so_a_caller_cannot_accidentally_pass_it():
    """`Decision` carries a reason, and a truthy object with `allowed=False` would authorise
    everybody at every `if` in this codebase."""
    assert not bool(authz.Decision(False, "no"))
    assert bool(authz.Decision(True))


# ── both front ends actually go through it ───────────────────────────────────────────────────────

def test_slack_asks_the_policy_rather_than_holding_its_own_rule(monkeypatch):
    """REACHABILITY, not behaviour: the rule could have been copied instead of moved, and every
    behaviour test would still pass. So the policy is replaced and Slack's answer must follow."""
    bot = add_ons.module("openfactory.runtime.slack.bot")

    project = _Project(admins=["U-op"])
    assert bot._is_authorized(project, "U-op") is True

    monkeypatch.setattr(authz, "may", lambda *a, **kw: authz.Decision(False, "policy said no"))

    assert bot._is_authorized(project, "U-op") is False, "Slack kept a rule of its own"


def test_the_product_role_asks_the_same_policy(monkeypatch):
    from openfactory.product.module import may_act

    project = _Project(product=_Product(admins=["U-po"]))
    assert may_act(project, "U-po") is True

    monkeypatch.setattr(authz, "may", lambda *a, **kw: authz.Decision(False, "policy said no"))

    assert may_act(project, "U-po") is False, "the product role kept a rule of its own"


# ── the panel's door ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def app(tmp_path, monkeypatch):
    from openfactory.api.app import app as fastapi_app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKENS", raising=False)
    monkeypatch.delenv("OPENFACTORY_IDENTITY", raising=False)
    return fastapi_app


def test_PER_PERSON_TOKENS_ALONE_STILL_CLOSE_THE_PANEL(app, monkeypatch):
    """THE REGRESSION THIS CARD ARMED AND THIS TEST DISARMS. `require_auth` used to ask only
    whether `OPENFACTORY_PANEL_TOKEN` was set. A deployment that migrated to per-person tokens and removed
    the shared one would have had a WIDE OPEN panel — the exact direction this gate must never fail
    in, and invisible, because every existing auth test sets the old variable."""
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "mine:alice")
    client = TestClient(app)

    assert client.post("/api/projects/x/enabled", json={"enabled": True}).status_code == 401
    assert client.post("/api/projects/x/enabled", json={"enabled": True},
                       headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = client.post("/api/projects/x/enabled", json={"enabled": True},
                     headers={"Authorization": "Bearer mine"})
    assert ok.status_code != 401, "the person's own token was refused"


def test_nothing_configured_is_still_open_for_local_development(app):
    """The documented posture, and the reason `open_to_everyone` is a separate question from
    `identify`: the two answers point opposite ways."""
    client = TestClient(app)

    assert client.post("/api/projects/x/enabled", json={"enabled": True}).status_code != 401


def test_a_provider_this_build_does_not_have_refuses_every_request(app, monkeypatch):
    """"I cannot check credentials" must not read as "let everyone in"."""
    monkeypatch.setenv("OPENFACTORY_IDENTITY", "entraid")
    client = TestClient(app)

    assert client.post("/api/projects/x/enabled", json={"enabled": True}).status_code == 503


def test_the_audit_line_names_the_PERSON_not_the_panel(app, monkeypatch):
    """What the card is actually for. `perform` writes one audit line per action, and until now
    every one of them said "panel" — for every person who ever held the one token."""
    from openfactory.api.app import _actor

    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "mine:alice:Alice Ferreira")

    class _Req:
        headers = {"authorization": "Bearer mine"}

    who = _actor(_Req())

    assert (who.id, who.display, who.via) == ("alice", "Alice Ferreira", "panel")


def test_a_NAMED_person_cannot_rename_themselves_in_the_audit_trail(app, monkeypatch):
    """`X-SDLC-Actor` was always a label rather than an identity. Once the provider CAN name
    somebody, letting that person overwrite the name would be worse than having no name at all —
    an audit line that is confidently wrong."""
    from openfactory.api.app import _actor

    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "mine:alice:Alice Ferreira")

    class _Req:
        headers = {"authorization": "Bearer mine", "x-openfactory-actor": "somebody else"}

    assert _actor(_Req()).id == "alice"


def test_an_ANONYMOUS_caller_may_still_label_itself(app, monkeypatch):
    """The label keeps its one honest use: a script or a bot on the shared token can say what it
    is, and the audit line reads better than "panel". It carries no id, so nothing downstream can
    mistake it for an authenticated person."""
    from openfactory.api.app import _actor

    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "shared")

    class _Req:
        headers = {"authorization": "Bearer shared", "x-openfactory-actor": "nightly-deploy"}

    who = _actor(_Req())

    assert who.display == "nightly-deploy"
    assert who.id == "panel", "a labelled anonymous caller must not acquire an identity"


# ── the SECOND gate — the middleware C-26 missed, found by the adversarial review ───────────────

def test_MID_MIGRATION_a_personal_token_passes_the_middleware_too(app, monkeypatch):
    """The review's first trace: with both variables set (the migration window the identity module
    documents), a personal token was 401'd by the middleware's compare against the SHARED token —
    on every route, before `require_auth` ever ran. Personal tokens simply did not work."""
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "shared")
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "mine:alice")
    client = TestClient(app)

    assert client.get("/api/actions",
                      headers={"Authorization": "Bearer mine"}).status_code != 401
    assert client.get("/api/actions",
                      headers={"Authorization": "Bearer shared"}).status_code != 401


def test_MIGRATED_the_middleware_still_closes_every_READ(app, monkeypatch):
    """The review's second trace, and the worse direction: with only per-person tokens set, the
    old middleware saw no shared token and DISABLED ITSELF — every read endpoint on an
    internet-facing panel open. `require_auth` covers mutations; the middleware is what covers
    the journal, the metrics, the message store, the SSE streams."""
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "mine:alice")
    client = TestClient(app)

    assert client.get("/api/actions").status_code == 401
    assert client.get("/api/actions",
                      headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/actions",
                      headers={"Authorization": "Bearer mine"}).status_code != 401


def test_the_SSE_query_param_carries_a_personal_token_as_well(app, monkeypatch):
    """EventSource cannot set headers — `?token=` is its documented door, and it must accept the
    same credentials the header does or the migration silently breaks every live stream."""
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "mine:alice")
    client = TestClient(app)

    assert client.get("/api/actions?token=mine").status_code != 401
    assert client.get("/api/actions?token=wrong").status_code == 401


def test_an_unknown_provider_closes_the_MIDDLEWARE_not_just_require_auth(app, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_IDENTITY", "entraid")
    client = TestClient(app)

    assert client.get("/api/actions").status_code == 503
