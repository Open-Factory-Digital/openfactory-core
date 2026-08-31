"""An advisory gate reports and does not authorise a halt — #11's second half.

WHAT `advisory` MEANT, AND WHAT IT DID. `floor.yaml` marks the credential scan advisory and says
why, in a whole paragraph:

    A first scan of a fifteen-year-old repository reports the debt of its whole history and none of
    it is the first ticket's fault; blocking on day one means the client turns the gate off, and a
    gate that gets turned off protects nothing.

`_all_passed` never consults an advisory gate, so it cannot block a merge — and that is all the
flag ever did. `box prove`'s validate station demanded `rc == 0` from every repo-wide gate on
untouched main, `proof.ok` went False, and `gate_reason` held every card on the project. The word
`advisory` appeared in `box_prove.py` zero times.

So the stated purpose of the flag was not achieved, and not only for false positives: a legacy
repository with ONE genuine credential in its history — precisely the case the paragraph is about —
had every ticket blocked on day one.

THE PRINCIPLE IS ALREADY IN THAT FILE, one station below. The per-component check draws exactly
this line and explains it: *"a per-component gate can be legitimately non-green on untouched main …
and this proof is a PRECONDITION OF PICKUP, so demanding green here would stop a working deployment
from picking up any work at all. What is never legitimate is a command the box cannot execute."*

An advisory gate is legitimately non-green by the project's own declaration. This is that
principle, one station up — with the same exception, because a command the box cannot RUN is not
advisory whatever the project declared.
"""

from __future__ import annotations

import pytest

from openfactory.box_prove import Finding, Probes, prove
from openfactory.contracts.manifest import Manifest
from openfactory.orchestrator.validation import advisory_gates, gate_commands


def _probes(**overrides) -> Probes:
    """A box that satisfies everything; each test breaks exactly one gate."""
    base = dict(
        resolve_digest=lambda image: "sha256:" + "a" * 64,
        image_platform=lambda image: ("linux", "arm64", "glibc"),
        toolbox_stamp=lambda: {"variant": "linux-arm64-glibc",
                               "harnesses": ["claude", "codex", "kimi"]},
        contract=lambda image: {},
        run_in_box=lambda cmd: (0, ""),
        harness_reachable=lambda: (True, ""),
        setup_commands=lambda: [],
        validate_commands=lambda: {"test": "pytest -q", "security": "scan"},
        harness_name=lambda: "claude",
    )
    base.update(overrides)
    return Probes(**base)


def _fails(*commands: str):
    """A box where exactly these commands exit 1 with ordinary output — a gate that RAN and said
    no, which is a different thing from one the box could not execute."""
    return lambda cmd: ((1, "found something") if cmd in commands else (0, ""))


def _prove(**overrides):
    return prove("acme", "img:1", _probes(**overrides))


# ── the defect ───────────────────────────────────────────────────────────────────────────────────

def test_an_advisory_gate_that_fails_does_not_hold_the_pickup() -> None:
    """#11's second half. Before this, a red advisory gate made `proof.ok` False and `gate_reason`
    held every card on the project — a gate the client declared advisory, stopping all their work."""
    proof = _prove(run_in_box=_fails("scan"),
                   advisory_gates=lambda: frozenset({"security"}))

    assert proof.ok, [f.message for f in proof.failures()]
    assert proof.failures() == []


def test_a_BLOCKING_gate_that_fails_still_holds_it() -> None:
    """The positive twin, and the whole floor rests on it: without this a version that ignored
    every red gate would pass the guard above and prove nothing at all."""
    proof = _prove(run_in_box=_fails("pytest -q"),
                   advisory_gates=lambda: frozenset({"security"}))

    assert not proof.ok
    assert any("test" in f.message for f in proof.failures())


def test_the_advisory_failure_is_REPORTED_rather_than_ignored() -> None:
    """The objection this answers rather than dodges: *a proof that ignores a red gate proves
    less*. It does not ignore it — the finding is there, it renders as `warn`, and `advisories()`
    returns it. Proving is a measurement; holding a pickup is an authorisation."""
    proof = _prove(run_in_box=_fails("scan"),
                   advisory_gates=lambda: frozenset({"security"}))

    advisories = proof.advisories()
    assert len(advisories) == 1
    assert "security" in advisories[0].message
    assert advisories[0].advisory is True
    assert advisories[0].remedy, "a finding with no remedy is a symptom handed to a stranger"


def test_the_green_count_does_not_include_the_advisory_failure() -> None:
    """"2 gate(s) green" while one of them failed is the sentence a reader trusts and should not."""
    proof = _prove(run_in_box=_fails("scan"),
                   advisory_gates=lambda: frozenset({"security"}))

    validate = next(f for f in proof.findings if f.check == "validate" and f.ok)
    assert "1 gate(s) green" in validate.message
    assert "did not hold it" in validate.message


def test_an_advisory_failure_does_not_cut_the_proof_short() -> None:
    """The blocking path returns early — `validating a broken environment stacks a second,
    misleading error`. An advisory one must not, or the harness smoke test and everything after it
    silently stop being proven the moment a project carries any debt."""
    proof = _prove(run_in_box=_fails("scan"),
                   advisory_gates=lambda: frozenset({"security"}))

    assert {f.check for f in proof.findings} >= {"image", "toolbox", "contract", "box", "validate"}
    assert proof.ok


# ── the exception, and it is the same one the station below already makes ────────────────────────

def test_a_command_the_box_CANNOT_RUN_is_not_advisory() -> None:
    """The flag says "a finding here should not stop the work". It cannot say "this image has the
    tool" when the shell has just said it does not — that is a box which cannot run its own gates,
    and `advisory: true` must not become a way to prove one."""
    proof = _prove(run_in_box=lambda cmd: ((127, "sh: 1: scan: not found") if cmd == "scan"
                                           else (0, "")),
                   advisory_gates=lambda: frozenset({"security"}))

    assert not proof.ok
    assert proof.advisories() == []


# ── the flag has to survive the seam it was being lost at ────────────────────────────────────────

def test_the_advisory_flag_reaches_the_proof_from_the_manifest() -> None:
    """`gate_commands` returns `{name: command}` and deliberately drops everything else — which is
    where the flag went missing. `advisory_gates` is its sibling, and this is the join."""
    manifest = Manifest.model_validate({"validate": {
        "test": "pytest -q",
        "security": {"command": "scan", "advisory": True},
    }})

    assert gate_commands(manifest.validation) == {"test": "pytest -q", "security": "scan"}
    assert advisory_gates(manifest.validation) == frozenset({"security"})


def test_gates_that_declare_nothing_are_not_advisory() -> None:
    """The default is the old behaviour exactly: nothing loosens by upgrading, and a gate has to
    SAY it is advisory to become one."""
    assert advisory_gates({"test": "pytest -q", "lint": {"command": "ruff"}}) == frozenset()
    assert advisory_gates({}) == frozenset()
    assert not _prove(run_in_box=_fails("pytest -q")).ok


def test_every_project_in_the_fleet_inherits_one_advisory_gate() -> None:
    """WHY THIS BUG REACHED A CLIENT AT ALL, and it is worth pinning rather than remembering.

    A manifest that declares only `test` still inherits `floor.yaml`'s `security` gate through
    `_inherit_the_deployment_floor` — so EVERY project carries an advisory gate whether or not it
    ever typed the word. Before this change, every one of them was a single false positive away
    from having its pickup held, and the flag that was supposed to prevent exactly that reached
    `box prove` as nothing at all."""
    inherited = Manifest.model_validate({"validate": {"test": "pytest -q"}})

    assert "security" in inherited.validation, "the floor is no longer inherited"
    assert advisory_gates(inherited.validation) == frozenset({"security"})


def test_the_floors_own_security_gate_is_the_one_this_is_about() -> None:
    """Read from `floor.yaml` rather than asserted from memory: the gate every project in the fleet
    inherits is the advisory one, and it is what #11 reported."""
    import pathlib

    import yaml

    floor = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parent.parent
         / "openfactory" / "org_defaults" / "floor.yaml").read_text(encoding="utf-8"))

    assert floor["validate"]["security"]["advisory"] is True
    assert advisory_gates(floor["validate"]) == frozenset({"security"})


# ── one spelling of the three states ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("ok", "advisory", "mark"), [
    (True, False, "ok"), (False, True, "warn"), (False, False, "FAIL"),
])
def test_the_mark_is_spelled_once(ok: bool, advisory: bool, mark: str) -> None:
    """Three renderers printed `ok if f.ok else FAIL`. A fourth state added in one of them would be
    three states in one place and two in the others — with `warn` rendered as `FAIL` on the surface
    a client actually reads."""
    assert Finding("validate", ok, "m", "r", advisory=advisory).mark == mark


def test_the_doctors_report_is_not_the_proof(monkeypatch) -> None:
    """TWO LOOPS THAT LOOK IDENTICAL AND ARE ABOUT DIFFERENT OBJECTS. `cli.py` renders
    `proof.findings` in one place and the DOCTOR's `report.findings` in another, and the two lines
    were byte-identical. `openfactory/doctor.py` has its own `Finding` with two states and no
    `mark`; changing that loop raised `AttributeError` inside the CLI runner and turned fourteen
    doctor guards into a blank page.

    Guarded on the classes rather than on the rendering, because it is the confusion that is the
    defect: a three-state mark belongs only to the object that has three states."""
    from openfactory import doctor as doc
    from openfactory.box_prove import Finding as ProofFinding

    assert hasattr(ProofFinding("c", True, "m"), "mark")
    assert not hasattr(doc.Finding("c", True, "m"), "mark"), (
        "the doctor's Finding grew a `mark` — if that is deliberate, this guard should say so "
        "rather than the two silently converging")
