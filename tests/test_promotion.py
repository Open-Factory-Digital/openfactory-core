"""Prod promotion (ADR-0001 D-12): approval gate, semver, and the promote lifecycle.

The real deploy observation + the panel button can't be exercised until a real
staging/prod pipeline exists (prod is off in the dev phase) — TECH DEBT to verify
end-to-end later. The logic below is fully tested with fakes."""

from __future__ import annotations

import json

from openfactory.approvals import hash_password, verify_approver
from openfactory.contracts import Environment, JobState, Manifest
from openfactory.orchestrator.promotion import PromotionRunner
from openfactory.semver import bump, suggest


# --- approval gate ---
def test_verify_approver_needs_allowlist_and_password(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_APPROVERS", json.dumps({"alice": hash_password("s3cret")}))
    allowed = ["alice", "socio"]
    assert verify_approver("alice", "s3cret", allowed) is True
    assert verify_approver("alice", "wrong", allowed) is False
    assert verify_approver("alice", "s3cret", ["socio"]) is False  # not allowed on this project
    assert verify_approver("ghost", "x", allowed) is False


# --- semver ---
def test_semver_bumps():
    assert bump("v1.2.3", "patch") == "1.2.4"
    assert bump("1.2.3", "minor") == "1.3.0"
    assert bump("v1.2.3", "major") == "2.0.0"
    assert bump(None, "patch") == "0.0.1"


def test_semver_suggest():
    assert suggest("v2.5.9") == {"current": "2.5.9", "patch": "2.5.10",
                                 "minor": "2.6.0", "major": "3.0.0"}


# --- promotion lifecycle (fakes) ---
class FakeTracker:
    def __init__(self):
        self.states, self.comments = [], []

    def set_state(self, ref, state, reason=None, *, needs_person=None):
        self.states.append(state)

    def comment(self, ref, body):
        self.comments.append(body)


class FakeForge:
    def __init__(self):
        self.tags = []

    def create_tag(self, *, tag, ref):
        self.tags.append(tag)


class FakeObserver:
    def __init__(self, healthy=True):
        self.healthy = healthy

    def deploy_status(self, *, env, ref):
        return "success"

    def health(self, *, url, timeout=10):
        return self.healthy


def _runner(healthy=True, environments=None):
    return PromotionRunner(
        tracker=FakeTracker(), forge=FakeForge(), observer=FakeObserver(healthy),
        manifest=Manifest(environments=environments or {}, prod_approvers=["alice"]),
    )


#: A project that HAS somewhere to release to. The gate below only means something for one of
#: these — and this fixture used to declare staging alone, which is why "no production declared"
#: went unnoticed as a distinct state for so long.
_WITH_PROD = {"staging": Environment(health_url="http://staging/health"),
              "prod": Environment(health_url="http://prod/health")}


def test_promote_awaits_human_when_staging_green():
    r = _runner(True, _WITH_PROD)
    result = r.promote("#5")
    assert result.state is JobState.AWAITING_PROD_APPROVAL  # stops for a human
    assert any("staging verified" in c for c in r.tracker.comments)


# --- a project born WITHOUT production (2026-07-31: the live client's own manifest) ---

def test_a_project_with_no_prod_environment_does_not_park_on_a_gate_nobody_can_open():
    """Something under construction has nowhere to release to yet, and that is an ordinary state.

    Parking anyway held the gate for the whole approval window and then went ON_HOLD with "prod
    approval window elapsed" — a stall with no way out, which is the one failure this platform
    exists to make impossible. Nothing is lost by finishing here: the work merged, and the client
    is still asked whether it is right by the delivery/acceptance loop, which runs off the board
    and not off an environment."""
    r = _runner(True, {"staging": Environment(health_url="http://staging/health")})

    result = r.promote("#5")

    assert result.state is JobState.DONE, result.state
    assert JobState.AWAITING_PROD_APPROVAL not in r.tracker.states, r.tracker.states
    assert any("no release step" in c for c in r.tracker.comments), r.tracker.comments


def test_nothing_declared_is_never_reported_as_something_VERIFIED():
    """`_verify` answers True for an undeclared environment — correct, and the claim built on it
    was not. A project with no environments at all had "✅ staging verified" written on its ticket
    about a check that never ran."""
    r = _runner(True, {})          # exactly the live client's manifest: no environments at all

    result = r.promote("#5")

    assert result.state is JobState.DONE
    assert not any("staging verified" in c for c in r.tracker.comments), r.tracker.comments
    assert JobState.STAGING_VERIFYING not in r.tracker.states, (
        f"it recorded observing an environment that does not exist: {r.tracker.states}")


def test_promote_holds_when_staging_red():
    r = _runner(False, {"staging": Environment(health_url="http://staging/health")})
    result = r.promote("#5")
    assert result.state is JobState.ON_HOLD
    assert any("staging" in c and "failed" in c for c in r.tracker.comments)


def test_release_prod_tags_and_records_approver():
    r = _runner(True, {"prod": Environment(health_url="http://prod/health")})
    result = r.release_prod("#5", version="1.4.0", approver="alice", comment="ship it")
    assert result.state is JobState.DONE
    assert r.forge.tags == ["v1.4.0"]  # prod_tag_prefix default "v"
    assert any("@alice" in c and "v1.4.0" in c and "ship it" in c for c in r.tracker.comments)


def test_release_prod_rolls_back_when_prod_red():
    r = _runner(False, {"prod": Environment(health_url="http://prod/health")})
    result = r.release_prod("#5", version="1.4.0", approver="alice")
    assert JobState.ROLLING_BACK in r.tracker.states
    assert result.state is JobState.ON_HOLD
    assert any("rolling back" in c for c in r.tracker.comments)


# --- the declared chain (#109) ---

class OrderedObserver:
    """Records WHICH health URLs were probed, in order — the chain's order IS its meaning."""

    def __init__(self, red: set[str] | None = None):
        self.probed: list[str] = []
        self.red = red or set()

    def deploy_status(self, *, env, ref):
        return "success"

    def health(self, *, url, timeout=10):
        self.probed.append(url)
        return url not in self.red


def _chain_runner(observer, promote):
    envs = {"dev": Environment(health_url="http://dev/h"),
            "qa": Environment(health_url="http://qa/h"),
            "producao": Environment(health_url="http://producao/h")}
    return PromotionRunner(
        tracker=FakeTracker(), forge=FakeForge(), observer=observer,
        manifest=Manifest(environments={k: envs[k] for k in promote},
                          promote=promote, prod_approvers=["alice"]),
    )


def test_a_declared_chain_is_walked_in_order_and_gates_before_the_LAST():
    """The corporate manifest, running: dev and qa observed in the client's order, and the gate
    parks before `producao` — which is never probed until a human approves, because observing
    production BEFORE the release would read the previous version's health as this release's."""
    obs = OrderedObserver()
    r = _chain_runner(obs, ["dev", "qa", "producao"])

    result = r.promote("#5")

    assert obs.probed == ["http://dev/h", "http://qa/h"], obs.probed
    assert result.state is JobState.AWAITING_PROD_APPROVAL
    assert any("dev, qa verified" in c for c in r.tracker.comments), r.tracker.comments
    assert any("Awaiting producao approval" in c for c in r.tracker.comments), r.tracker.comments


def test_a_red_MIDDLE_stage_stops_the_chain_with_its_own_name():
    """The stage the client named is the stage the failure names — 'qa red', not 'staging red'
    about an environment their change-management document has no entry for."""
    obs = OrderedObserver(red={"http://qa/h"})
    r = _chain_runner(obs, ["dev", "qa", "producao"])

    result = r.promote("#5")

    assert result.state is JobState.ON_HOLD and result.note == "qa red"
    assert any("qa" in c and "failed" in c for c in r.tracker.comments), r.tracker.comments
    assert "http://producao/h" not in obs.probed, "a red stage must stop the walk"


def test_release_verifies_the_chains_LAST_stage_not_a_fixed_name():
    """`release_prod` used to ask for `environments.get("prod")` — on a declared chain that
    answered None and the release was 'verified' vacuously. The last stage is production
    whatever it is called, and its OWN health decides done-vs-rollback."""
    obs = OrderedObserver()
    r = _chain_runner(obs, ["qa", "producao"])

    result = r.release_prod("#5", version="1.0.0", approver="alice")

    assert result.state is JobState.DONE
    assert "http://producao/h" in obs.probed, "the release must observe the REAL last stage"

    red = OrderedObserver(red={"http://producao/h"})
    r2 = _chain_runner(red, ["qa", "producao"])
    assert r2.release_prod("#5", version="1.0.0", approver="alice").state is JobState.ON_HOLD


def test_a_single_entry_chain_is_a_production_gate_and_nothing_else():
    obs = OrderedObserver()
    r = _chain_runner(obs, ["producao"])

    result = r.promote("#5")

    assert result.state is JobState.AWAITING_PROD_APPROVAL
    assert obs.probed == [], "there is nothing before production to observe"
    assert JobState.STAGING_VERIFYING not in r.tracker.states, (
        f"it recorded observing a stage the chain does not have: {r.tracker.states}")
    assert any("✅ merged. Awaiting producao approval" in c for c in r.tracker.comments)
