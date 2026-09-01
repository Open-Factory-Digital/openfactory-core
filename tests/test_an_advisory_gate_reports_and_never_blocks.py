"""A gate can report without deciding (C-37, #79).

`validate:` values were bare strings, so every gate BLOCKED and every failure fed the repair loop.
That is right for `test` and wrong for the thing this card exists to allow: a security or licence
scan pointed at a real codebase reports the accumulated debt of its whole history, none of which
is this ticket's fault. Wired as a blocking gate on day one it is the first thing a client turns
off — after the platform has paid an agent to attempt a fix it cannot make, because a CVE in a
transitive dependency is not a code change.

The claim being pinned is narrow and total: an advisory gate RUNS, is REPORTED where a human reads
it, and decides NOTHING — not the job's outcome, not the merge, not the repair loop.
"""

from __future__ import annotations

from openfactory.contracts import ValidationResult
from openfactory.contracts.manifest import Gate, Manifest
from openfactory.orchestrator.machine import _all_passed
from openfactory.orchestrator.validation import applicable_validations, as_gate, gate_commands


def _manifest(**validate) -> Manifest:
    return Manifest(version=1, base_branch="main", validate=validate)


# ── the shape ────────────────────────────────────────────────────────────────────────────────────

def test_a_plain_string_is_still_a_blocking_gate():
    """Every manifest in existence uses this form. It must not change meaning."""
    g = as_gate(_manifest(test="pytest -q").validation["test"])
    assert g.command == "pytest -q"
    assert g.advisory is False and g.timeout_minutes is None


def test_a_mapping_carries_the_policy():
    m = _manifest(security={"command": "semgrep .", "advisory": True, "timeout_minutes": 20})
    g = as_gate(m.validation["security"])
    assert (g.command, g.advisory, g.timeout_minutes) == ("semgrep .", True, 20)


def test_the_two_shapes_coexist_in_one_manifest():
    m = _manifest(test="pytest -q", security={"command": "semgrep .", "advisory": True})
    assert as_gate(m.validation["test"]).advisory is False
    assert as_gate(m.validation["security"]).advisory is True


def test_consumers_that_only_want_COMMANDS_still_get_strings():
    """`box prove` and the command hash never cared about the policy. Keeping them on strings is
    what makes this schema change invisible to them — and the hash must not churn, or every
    project's proof expires for a change that touched none of their gates."""
    m = _manifest(test="pytest -q", security={"command": "semgrep .", "advisory": True})
    assert gate_commands(m.validation) == {"test": "pytest -q", "security": "semgrep ."}


def test_the_hash_does_not_move_for_an_unchanged_manifest(monkeypatch):
    """The subject is the `Gate` SCHEMA — a manifest that reads `security: "semgrep ."` and one
    that reads the mapping form must hash identically, or every project's box proof expires for a
    change that touched none of their gates.

    The deployment's default gate is suppressed here for the same reason the hand-written map on
    the left has no `security` in it: this asks whether the schema churns the hash, and the floor's
    inheritance is a different question with a different answer — it DOES move the hash, once, for
    the projects that inherit, and `test_the_floor_is_a_deployment_default_not_a_transcription`
    asserts that consequence out loud instead of hiding it here."""
    from openfactory.box_prove import _hash_commands

    monkeypatch.setattr("openfactory.policy.presets.org_default_validation", lambda: {})
    before = _hash_commands([], {"test": "pytest -q"})
    after = _hash_commands([], gate_commands(_manifest(test="pytest -q").validation))
    assert before == after


# ── it decides nothing ───────────────────────────────────────────────────────────────────────────

def test_an_advisory_failure_does_not_fail_the_job():
    v = [ValidationResult(name="test", command="pytest", exit_code=0, passed=True),
         ValidationResult(name="security", command="semgrep", exit_code=1, passed=False,
                          advisory=True)]
    assert _all_passed(v) is True


def test_a_BLOCKING_failure_still_fails_the_job():
    """The positive twin. Making advisory not block must not make anything else stop blocking."""
    v = [ValidationResult(name="test", command="pytest", exit_code=1, passed=False),
         ValidationResult(name="security", command="semgrep", exit_code=1, passed=False,
                          advisory=True)]
    assert _all_passed(v) is False


def test_advisory_defaults_to_FALSE_everywhere():
    """A gate that quietly stopped blocking is the dangerous direction of this change."""
    assert Gate(command="x").advisory is False
    assert ValidationResult(name="n", command="c", exit_code=1, passed=False).advisory is False


# ── and it is SEEN, or it is a log rather than a gate ────────────────────────────────────────────

def _pr_body(validations):
    import types

    from openfactory.contracts import RunResult, Ticket
    from openfactory.orchestrator.machine import JobRunner

    result = RunResult(ticket_id="#1", state="pr_open", validations=validations)
    ticket = Ticket(id="#1", title="t", objective="o", repo="o/r")
    return JobRunner._pr_body(
        # A REAL MANIFEST, because `JobRunner.manifest` is never None: the constructor
        # takes one. The stub used to say None and `_pr_body` tolerated it only because
        # nothing there read a field of it — a shape production cannot produce, agreed
        # with by a test that built it.
        types.SimpleNamespace(manifest=Manifest()), ticket, result)


def test_an_advisory_failure_appears_in_the_pull_request():
    body = _pr_body([ValidationResult(name="security", command="semgrep", exit_code=1,
                                      passed=False, advisory=True)])
    assert "security" in body
    assert "advisory" in body.lower()


def test_it_does_not_wear_the_same_mark_as_a_blocking_failure():
    """The two ask opposite things of the reader: fix this now, or look at this when you can."""
    adv = _pr_body([ValidationResult(name="security", command="s", exit_code=1, passed=False,
                                     advisory=True)])
    blk = _pr_body([ValidationResult(name="test", command="t", exit_code=1, passed=False)])
    assert "⚠️" in adv and "❌" not in adv
    assert "❌" in blk


# ── the free preset ──────────────────────────────────────────────────────────────────────────────

def test_the_oss_security_preset_is_advisory_by_default():
    """Free by default is the differentiator; advisory by default is what makes it survive contact
    with a real codebase."""
    from openfactory.policy.presets import load_preset

    preset = load_preset("security-oss")
    gates = preset["validate"]
    assert gates, "the preset ships no gates"
    for name, spec in gates.items():
        assert as_gate(spec).advisory is True, f"{name} would block on day one"
        assert as_gate(spec).timeout_minutes, f"{name} would borrow the test suite's wall"


def test_a_project_can_override_the_preset_and_make_it_BLOCKING():
    """The client who wants it blocking says so deliberately — the point is the default, not the
    ceiling."""
    m = Manifest(version=1, base_branch="main",
                 validate={"security": {"command": "semgrep .", "advisory": False}})
    gates = applicable_validations([], m)
    assert as_gate(gates["security"]).advisory is False


def test_a_PRESET_gate_is_not_stringified_into_its_own_repr():
    """The bug the preset test found. Presets never pass through Manifest validation —
    `load_preset` is `yaml.safe_load` — so a mapping gate arrives as a plain dict. Coercing it
    with `str()` produced `command="{'command': 'semgrep …', 'advisory': True}"`, which the
    platform would have run as a shell command: the gate silently does nothing, on the very
    preset shipped to make security free, and `advisory` is lost so it blocks as well."""
    raw = {"command": "semgrep .", "advisory": True, "timeout_minutes": 20}
    g = as_gate(raw)
    assert g.command == "semgrep ."
    assert g.advisory is True and g.timeout_minutes == 20
    assert "{" not in g.command


def test_a_preset_reaches_the_runner_with_its_policy_intact():
    """End of the chain: through `applicable_validations`, the path the job actually takes."""
    m = Manifest(version=1, base_branch="main",
                 components={"api": {"path": "api/", "stack": "security-oss"}})
    gates = applicable_validations(["api"], m)
    assert gates, "the preset contributed no gate"
    for name, spec in gates.items():
        g = as_gate(spec)
        assert g.advisory is True, name
        assert "{" not in g.command, name
