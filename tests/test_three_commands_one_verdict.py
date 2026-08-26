"""`openfactory/onboarding/readiness.py` — one verdict where three commands disagreed (#99, slice 2).

Measured on `fx-py-simple`, at one instant, before this module existed:

    sdlc doctor fx-py-simple        "OK — can run a ticket"
    gate_reason(p, "container")     "the box has never been proven"   ← this holds pickup
    sdlc conformance fx-py-simple   "NOT runnable — floor unmet"

The bar for this suite is therefore not "the checks pass". It is that **no combination of inputs
produces a green verdict over a factory that would not move**, and that every line says which
machine answered it. Both are properties, so they are asserted as properties — over the whole
report, not over the cases somebody remembered to write.

THE TWO GUARDS THAT NEEDED A POSITIVE TWIN, because a negative one passes vacuously:

  * "never READY while `gate_reason` speaks" passes today on both live deployments for the wrong
    reason — they are `fargate`, and `gate_reason` returns None for a box that does not honour a
    per-project image, so the guard never has a string to see. Its twin is
    `test_a_fargate_project_with_no_proof_is_not_ready`, which measures the case the negative one
    cannot reach.
  * "the floor is not reported twice" would pass on a build where NOBODY reports it. Its twin is
    `test_the_floor_is_reported_when_doctor_does_not_ask_it`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from openfactory import doctor, namespace
from openfactory.onboarding import readiness as R

# ── a world, and every dial on it ───────────────────────────────────────────────────────────────


class _Proof:
    def __init__(self, ok=True, at="2026-08-06T10:00:00Z", image="python:3.12"):
        self.ok, self.at, self.image = ok, at, image


class _Route:
    def __init__(self, name="bedrock", endpoint="https://bedrock-runtime.eu-west-2.amazonaws.com",
                 remedy="name CLAUDE_CODE_USE_BEDROCK and a region in the project's `box.env`"):
        self.name, self.endpoint, self.remedy = name, endpoint, remedy


def _doctor_report(*, ok=True, with_floor=True):
    """A real `doctor.Report`, not a stand-in — this module composes that object, so the test has
    to hand it that object or it is testing a shape nobody produces."""
    findings = [
        doctor.Finding("docker", True, "docker is running"),
        doctor.Finding("harness", True, "harness 'claude_code' is on PATH"),
        doctor.Finding("manifest", True,
                       f"{namespace.MANIFEST} loads and declares 6 of 31 settings"),
        doctor.Finding("forge_access", True, "the forge is reachable"),
        doctor.Finding("board_columns", True, "the board has a 'TO-DO' column"),
        doctor.Finding("merge_policy", True, "merge_policy 'human' is consistent"),
        doctor.Finding("product_link", True, "no product module configured"),
    ]
    if with_floor:
        findings.insert(3, doctor.Finding("quality_floor", True,
                                          "the manifest declares every validation the floor wants"))
    if not ok:
        findings[0] = doctor.Finding("docker", False, "docker is not running",
                                     "start Docker Desktop, then re-run")
    return doctor.Report(findings)


def probes(**over) -> R.Probes:
    """A HEALTHY world by default, with one dial per failure this module can report.

    Healthy means: on the worker, a `container` box (so the gate is live), a current proof, a met
    floor, seven role prompts, agreeing routes, one `box.env` name that is set, and a worker
    registry that matches."""
    base = dict(
        project_name="fx-py-simple",
        measured_on=lambda: R.WORKER,
        registry_path=lambda: "/var/lib/openfactory/registry.yaml",
        doctor_report=_doctor_report,
        sandbox=lambda: "container",
        box_honours_image=lambda kind: kind == "container",
        gate_reason=lambda: None,
        proof=lambda: _Proof(),
        proof_dir=lambda: "/var/lib/openfactory/proofs",
        floor_reason=lambda: None,
        floor_enforced=lambda: False,
        role_prompt=lambda role: f"# {role}\ninstructions",
        declared_route=lambda: "bedrock",
        resolved_route=lambda: _Route(),
        harness_kind=lambda: "claude_code",
        box_env_names=lambda: ["CLAUDE_CODE_USE_BEDROCK"],
        environ=lambda: {"CLAUDE_CODE_USE_BEDROCK": "1"},
        enabled=lambda: True,
        registry_entry=lambda: {"name": "fx-py-simple", "enabled": True},
        worker_registry_entry=lambda: {"name": "fx-py-simple", "enabled": True},
        # OFF, to agree with the `doctor` report above ("no product module configured"). Most
        # projects never enable this, and a healthy world that disagreed with its own composed
        # report would be testing a state nothing produces.
        product_enabled=lambda: False,
        product_admins=lambda: [],
    )
    base.update(over)
    return R.Probes(**base)


def by_check(report) -> dict[str, R.Finding]:
    return {f.check: f for f in report.findings}


# ── the shape of an answer ──────────────────────────────────────────────────────────────────────

def test_the_report_names_every_check_it_ran():
    """A check that silently did not run is indistinguishable from one that passed."""
    names = {f.check for f in R.assess(probes()).findings}
    assert {"docker", "harness", "manifest", "quality_floor", "forge_access", "board_columns",
            "merge_policy", "product_link",                       # composed from doctor
            "enabled", "box_gate", "box_proof", "roles", "route", "env_names",
            "registry_parity", "product_role"} <= names           # added here


def test_a_healthy_deployment_is_ready_and_exits_zero():
    report = R.assess(probes())
    assert report.verdict == "READY", [f.message for f in report.findings if not f.ok]
    assert report.ready and report.exit_code == 0


def test_every_failing_check_says_what_to_do():
    """A finding with no remedy is a symptom handed to the one person who does not know the system.

    Asserted over a world where EVERY dial is broken at once, so the property is checked on every
    failure path this module has rather than on the one the writer had in mind."""
    report = R.assess(probes(
        doctor_report=lambda: _doctor_report(ok=False),
        gate_reason=lambda: "the box has never been proven — run `sdlc box prove fx-py-simple`",
        proof=lambda: None,
        floor_reason=lambda: "this project declares no `security` validation",
        role_prompt=lambda role: "",
        declared_route=lambda: "anthropic",
        box_env_names=lambda: ["MISSING_ONE"],
        environ=lambda: {},
        enabled=lambda: False,
        measured_on=lambda: R.LOCAL,
        worker_registry_entry=lambda: None,
    ))
    broken = [f for f in report.findings if not f.ok]
    assert len(broken) >= 8, [f.check for f in broken]
    for f in broken:
        assert f.remedy, f"{f.check} reports a problem without saying how to fix it"


def test_every_command_this_module_prints_is_a_command_that_EXISTS():
    """#99 §3 opens with a remedy the platform prints and the schema rejects — `stack:
    security-oss`, which `Manifest` forbids. "Um estranho segue esse remédio por uma hora."

    This module committed the same defect while being written to end it: the `enabled` remedy said
    `sdlc project enable <name>`, and `project` has `add`, `list`, `remove`, `init` and
    `forget-conversations` — nothing else. So the property is asserted rather than reviewed: every
    backticked `sdlc …` in every remedy this module can emit must resolve against the real Typer
    app. Nobody has to remember.

    THE FIRST VERSION OF THIS TEST WAS DECORATION, and only a mutation showed it. It asserted
    `call in known or call.split()[0] in known` — and the fallback, there so `sdlc doctor <name>`
    would not fail on its ARGUMENT, also accepted `project enable`, because `project` is a real
    group. Reintroducing the very bug it was written for left it green. A group needs a real
    subcommand; a leaf command's second token is an argument. Those are two different rules and one
    `or` cannot be both."""
    from openfactory.cli import app as cli

    leaves = {c.name for c in cli.registered_commands}
    groups = {g.name: {c.name for c in g.typer_instance.registered_commands}
              for g in cli.registered_groups}
    assert "doctor" in leaves and "prove" in groups.get("box", set()), \
        f"the scan is wrong, not the code: {leaves} {groups}"

    report = R.assess(probes(
        doctor_report=lambda: _doctor_report(ok=False), gate_reason=lambda: "held",
        proof=lambda: None, floor_reason=lambda: "no security gate", role_prompt=lambda r: "",
        declared_route=lambda: "anthropic", box_env_names=lambda: ["X"], environ=lambda: {},
        enabled=lambda: False, measured_on=lambda: R.LOCAL, worker_registry_entry=lambda: None,
    ))
    # BOTH NAMES, and that is not tidiness. The printed CLI became `openfactory`; a pattern that
    # still matched only `sdlc` found ZERO commands and this guard's own `assert invoked` was the
    # only thing that noticed — it would otherwise have gone silently blind to every remedy on the
    # day the product was renamed, which is precisely the class of failure it exists to catch.
    invoked = re.findall(r"`(?:openfactory|sdlc) ((?:[a-z-]+)(?: [a-z-]+)?)", " ".join(
        f"{f.message} {f.remedy}" for f in report.findings))
    assert invoked, "the scan found no commands at all — the pattern, not the code, is wrong"
    for call in invoked:
        parts = call.split()
        if parts[0] in leaves:
            continue                                    # the rest is an argument
        assert parts[0] in groups, \
            f"a remedy tells a stranger to run `sdlc {call}`, and `{parts[0]}` is not a command"
        assert len(parts) > 1 and parts[1] in groups[parts[0]], \
            f"a remedy tells a stranger to run `sdlc {call}`, and `{parts[0]}` has no such " \
            f"subcommand (it has: {sorted(groups[parts[0]])})"


def test_every_finding_says_which_machine_it_answered_for():
    """Provenance is not decoration: `doctor` measures the laptop typing the command, and the
    registry, toolbox and proofs a JOB reads live wherever the deployment runs."""
    for on in (R.WORKER, R.LOCAL):
        report = R.assess(probes(measured_on=lambda on=on: on))
        assert report.measured_on == on
        for f in report.findings:
            assert f.measured_on == on, f"{f.check} carries no provenance"


def test_a_local_run_says_so_before_any_finding():
    lines = R.assess(probes(measured_on=lambda: R.LOCAL,
                            registry_path=lambda: "/Users/x/.openfactory/registry.yaml")).header()
    assert "local" in lines[0] and "/Users/x/.openfactory/registry.yaml" in lines[0]
    assert "NOT the machine that runs your tickets" in lines[1]


def test_a_worker_run_does_not_carry_the_local_disclaimer():
    """The positive twin of the line above: a disclaimer printed everywhere is a disclaimer nobody
    reads, and it would make the `local` warning meaningless."""
    assert len(R.assess(probes()).header()) == 1


def test_an_unanswered_check_is_never_ok_and_never_missing():
    """`ok` alone cannot carry "I could not answer that here", and both readings do damage."""
    report = R.assess(probes(
        measured_on=lambda: R.LOCAL,
        worker_registry_entry=_raises(R.RegistryUnreachable("no file at /var/lib/openfactory/registry.yaml")),
        declared_route=lambda: "",
    ))
    unanswered = {f.check for f in report.unanswered}
    assert unanswered == {"registry_parity", "route"}
    for f in report.unanswered:
        assert f.ok, "an absence must not be counted as a failure"
        assert f not in report.missing, "an absence must not be counted as MISSING"
    assert report.verdict == "READY"


def test_an_unanswered_check_renders_as_neither_ok_nor_fail():
    """The reader has to be UNABLE to mistake "nothing here could answer that" for "that is fine"."""
    report = R.assess(probes(measured_on=lambda: R.LOCAL, declared_route=lambda: ""))
    line = next(x for x in report.render() if " route " in x)
    assert line.strip().startswith("----"), line
    assert "could not be answered on this machine" in "\n".join(report.render())


def test_a_broken_check_becomes_a_finding_not_a_crash():
    """This is what somebody runs when nothing works; a traceback tells them nothing about their
    setup and a lot about ours."""
    report = R.assess(probes(role_prompt=_raises(RuntimeError("boom"))))
    f = by_check(report)["roles"]
    assert not f.ok and "boom" in f.message and f.remedy
    assert report.verdict == "MISSING 1"


def test_a_doctor_that_cannot_run_is_one_finding_with_a_remedy():
    report = R.assess(probes(doctor_report=_raises(RuntimeError("no registry"))))
    f = by_check(report)["doctor"]
    assert not f.ok and "no registry" in f.message and f.remedy


# ── the verdict cannot contradict the factory ───────────────────────────────────────────────────

def test_a_held_pickup_is_never_ready_and_carries_the_gates_own_words():
    """`HELD: <reason>` is the gate's string VERBATIM — the same sentence `scan_todo` announces, so
    the channel message and the report on somebody's screen are one problem, not two."""
    reason = "the image python:3.12 changed (sha256:aaa… → sha256:bbb…) — run `sdlc box prove x`"
    report = R.assess(probes(gate_reason=lambda: reason))
    assert report.verdict == f"HELD: {reason}"
    assert not report.ready and report.exit_code == 1
    assert by_check(report)["box_gate"].message == reason


def test_the_most_upstream_hold_is_the_one_reported():
    """A disabled project is never polled at all, so its board, its gate and its floor cannot
    matter. Reporting the gate first would send somebody to prove a box for a project nothing
    will ever look at."""
    report = R.assess(probes(enabled=lambda: False,
                             gate_reason=lambda: "the box has never been proven"))
    assert report.verdict.startswith("HELD: the project is disabled")
    assert "also holding: the box has never been proven" in "\n".join(report.render())


def test_a_disabled_project_reports_disabled_before_an_enforced_floor():
    """THE POSITIVE TWIN THE ORDERING GUARD WAS MISSING, and it found the bug live.

    The test above turns two dials whose order was already right. The floor is the one that was
    wrong: `quality_floor` sat FIRST in `assess`'s list, so a disabled project with an unmet,
    enforced floor printed

        HELD: the quality floor is unmet, so every ticket this project picks up is held for a
              human before any agent runs

    as its headline — about tickets it will never pick up, because `scan_projects` skips a disabled
    project before any board is read. The floor is enforced in `orchestrator/machine.py`, AFTER
    pickup; `enabled` decides whether pickup is ever attempted. Both dials, at once, is the only
    world that can see the difference."""
    report = R.assess(probes(enabled=lambda: False,
                             floor_reason=lambda: "no `security` validation",
                             floor_enforced=lambda: True,
                             gate_reason=lambda: "the box has never been proven"))
    assert report.verdict.startswith("HELD: the project is disabled"), report.verdict
    assert report.holds[0].startswith("the project is disabled")
    # and nothing is lost: the floor is still held, just not as the headline
    assert any("the quality floor is unmet" in h for h in report.holds[1:])


def test_missing_counts_only_answered_failures():
    report = R.assess(probes(role_prompt=lambda role: "" if role == "sizer" else "x",
                             measured_on=lambda: R.LOCAL,
                             worker_registry_entry=_raises(R.RegistryUnreachable("no file"))))
    assert report.verdict == "MISSING 1"
    assert report.exit_code == 1


# ── the box: a gate that CANNOT speak, and a proof that can ─────────────────────────────────────

def test_a_fargate_project_with_no_proof_is_not_ready():
    """THE POSITIVE TWIN, and the reason it exists.

    Measured: `gate_reason(p, sandbox="fargate")` returns None because `box_traits("fargate")
    .honours_image` is False, and `default_sandbox()` answers `fargate` wherever
    `OPENFACTORY_FARGATE_CLUSTER` is set — which is both live deployments. So a guard that only asserted
    "never READY while the gate speaks" would pass here without ever seeing a string, over a
    project whose box has never been proven. This is the case that guard cannot reach."""
    report = R.assess(probes(sandbox=lambda: "fargate",
                             box_honours_image=lambda kind: False,
                             gate_reason=lambda: None,
                             proof=lambda: None))
    assert not report.ready
    assert report.verdict == "MISSING 1"
    assert report.exit_code == 1
    proof = by_check(report)["box_proof"]
    assert not proof.ok and "never been proven" in proof.message
    # and it says WHY nothing is held, so `MISSING` is not read as a softer `HELD`
    assert "a ticket WOULD run in a box nobody has proven" in proof.message


def test_an_inert_gate_says_it_is_inert_rather_than_ok():
    """Reporting the ABSENCE of a gate as a passing gate is vacuous truth printed with authority —
    strictly worse than the three-way disagreement it replaces."""
    f = by_check(R.assess(probes(sandbox=lambda: "fargate",
                                 box_honours_image=lambda kind: False)))["box_gate"]
    assert f.ok
    assert "not gated" in f.message and "honours_image is False" in f.message


def test_a_gated_box_with_a_current_proof_says_pickup_is_not_held():
    f = by_check(R.assess(probes()))["box_gate"]
    assert f.ok and "not held" in f.message


def test_a_failed_proof_is_distinguished_from_no_proof():
    """Two different remedies: one is "take a proof", the other is "read the FAIL lines of the one
    you took". Collapsing them sends somebody to re-run a command that already told them."""
    none = by_check(R.assess(probes(box_honours_image=lambda k: False,
                                    proof=lambda: None)))["box_proof"]
    failed = by_check(R.assess(probes(box_honours_image=lambda k: False,
                                      proof=lambda: _Proof(ok=False))))["box_proof"]
    assert "never been proven" in none.message
    assert "FAILED" in failed.message
    assert none.remedy != failed.remedy


def test_the_proof_remedy_names_the_machine_and_the_path():
    f = by_check(R.assess(probes(proof=lambda: None)))["box_proof"]
    assert "/var/lib/openfactory/proofs/fx-py-simple.json" in f.message
    assert "ON THE DEPLOYMENT" in f.remedy


def test_the_proof_message_claims_no_READABLE_record_rather_than_no_file():
    """`box_prove.load` returns None twice over: for a file that is not there, and for one that is
    there and will not parse — it logs "unreadable … treating it as absent" and returns None. This
    module cannot tell those apart, so it must not assert the stronger one. A reader who is told
    "no record at <path>", runs `ls`, and finds the file stops believing the other fourteen
    lines."""
    f = by_check(R.assess(probes(proof=lambda: None)))["box_proof"]
    assert "no readable record at" in f.message
    assert "no record at" not in f.message.replace("no readable record at", "")


# ── the floor: composed, not duplicated, and turned into a hold ─────────────────────────────────

def test_the_floor_is_reported_exactly_once():
    """`doctor.diagnose` gained `quality_floor` in 9f23d14. Two findings out of one problem is the
    thing `doctor.load_manifest_quietly` refuses to do one module over."""
    report = R.assess(probes(floor_reason=lambda: "no `security` validation"))
    assert [f.check for f in report.findings].count("quality_floor") == 1


def test_the_floor_is_reported_when_doctor_does_not_ask_it():
    """THE POSITIVE TWIN. "doctor covers it" must not silently become "nobody covers it" the day
    that build changes — a check that disappears is exactly the absence-reads-as-compliance shape
    this module is written against."""
    report = R.assess(probes(doctor_report=lambda: _doctor_report(with_floor=False),
                             floor_reason=lambda: "this project declares no `security` validation"))
    f = by_check(report)["quality_floor"]
    assert not f.ok and "security" in f.message and f.remedy


def test_a_passing_doctor_finding_cannot_outvote_the_floor_this_report_used():
    """THE REGRESSION THIS SUITE FOUND IN ITS OWN MODULE, and the reason `assess` de-duplicates the
    way round it does.

    The world: `doctor`'s report carries `quality_floor: ok` while `floor_reason` — the function
    the verdict is computed from — returns a string. The first version kept `doctor`'s finding and
    dropped its own, so the report showed a green line and printed **READY** over an unmet floor.
    One report, two answers, the confident one winning: the exact failure this module exists to
    remove, reproduced inside it.

    The two are consistent in production today (both call `floor_reason` on the same manifest), so
    nothing about the bug was visible from a healthy run. That is what makes it worth a test."""
    report = R.assess(probes(doctor_report=lambda: _doctor_report(with_floor=True),
                             floor_reason=lambda: "this project declares no `security` validation"))
    assert not report.ready, "a stale passing finding outvoted the answer the verdict was built on"
    assert report.verdict == "MISSING 1"
    f = by_check(report)["quality_floor"]
    assert not f.ok, "the finding shown must be the answer the verdict used"


def test_an_unmet_floor_holds_only_where_it_is_enforced():
    """One fact, two sentences, and reporting either as the other is its own silent stall: where
    the floor does not refuse, jobs RUN with that gate missing; where it does, every ticket is held
    for a human.

    NO DEPLOYMENT ANSWERS `False` TODAY (`OPENFACTORY_ENFORCE_FLOOR` was removed; `floor_is_enforced` is a
    constant). The probe is kept and so is this test, because the probe is what a test replaces: a
    module that hardcoded the verdict could never be SHOWN reporting the other state, and the day
    somebody makes it configurable again nothing would notice the sentence had gone wrong."""
    off = R.assess(probes(floor_reason=lambda: "no `security` validation",
                          floor_enforced=lambda: False))
    on = R.assess(probes(floor_reason=lambda: "no `security` validation",
                         floor_enforced=lambda: True))
    assert off.verdict == "MISSING 1" and off.holds == []
    assert on.verdict.startswith("HELD: the quality floor is unmet")
    assert on.exit_code == 1


def test_the_floor_hold_survives_doctor_reporting_the_same_fact():
    """The finding is dropped as a duplicate; the HOLD is the only thing this check adds and must
    not be dropped with it."""
    report = R.assess(probes(floor_reason=lambda: "no `security` validation",
                             floor_enforced=lambda: True))
    assert report.holds and "the quality floor is unmet" in report.holds[0]
    assert not report.ready


# ── roles: a broken installation, silent by design ──────────────────────────────────────────────

def test_an_empty_role_prompt_is_named():
    """WHICH roles, not how many. "some role prompts are missing" is a symptom; the seven have
    different owners and a missing `product` means something different from a missing `executor`.

    The remedy points at THIS INSTALLATION and deliberately not at `pyproject.toml`: the packaging
    finding #99 §2 makes was measured and refused (the wheel ships all seven either way), and a
    remedy repeating a disproved diagnosis sends a stranger to fix a file that was never wrong."""
    f = by_check(R.assess(probes(
        role_prompt=lambda role: "" if role in ("sizer", "product") else "x")))["roles"]
    assert not f.ok
    assert "2 of 7" in f.message and "sizer" in f.message and "product" in f.message
    assert "INSTALLATION is incomplete" in f.remedy
    assert "pyproject" not in f.remedy.lower()


def test_a_whitespace_only_role_prompt_counts_as_empty():
    """A file that exists and says nothing degrades exactly like a file that is not there, and
    `role_prompt` returns both without distinction."""
    f = by_check(R.assess(probes(role_prompt=lambda role: "  \n ")))["roles"]
    assert not f.ok and "7 of 7" in f.message


def test_the_roles_check_says_which_installation_it_read():
    """The deployed worker escapes the packaging bug by accident (its WORKDIR shadows
    site-packages) while the console script on the same host does not, so a green line from one
    says nothing about the other."""
    f = by_check(R.assess(probes(measured_on=lambda: R.LOCAL)))["roles"]
    assert f.ok and "local" in f.message


def test_every_call_site_this_file_cites_actually_exists():
    """A CITATION IS A CLAIM, and this file is almost entirely citations — the whole argument for
    every check is "here is the line that acts on this fact".

    It shipped with a false one. `_enabled` said `activities.py::projects_to_poll` skips a disabled
    project; there is no `projects_to_poll` anywhere in the tree, and the code that does it is
    `scan_projects` (`if not p.enabled: continue`). The module docstring had already been corrected
    and the function docstring had not — which is exactly how a citation rots: nobody re-greps a
    comment. A stranger reading it goes looking for a function that does not exist and concludes
    the description, not their search, is out of date.

    So the `file.py::symbol` form is checked mechanically. A basename that several modules share
    passes if ANY of them defines the symbol — the point is that the reader can find it, not which
    package it came from."""
    import ast

    root = Path(__file__).resolve().parent.parent / "openfactory"
    source = (root / "onboarding" / "readiness.py").read_text()
    cited = set(re.findall(r"([a-z_]+\.py)::([A-Za-z_][A-Za-z_0-9]*)", source))
    assert cited, "the scan found no citations at all — the pattern, not the code, is wrong"

    def defines(path: Path, symbol: str) -> bool:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) \
                    and node.name == symbol:
                return True
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) \
                    and node.id == symbol:
                return True
        return False

    for filename, symbol in sorted(cited):
        candidates = [p for p in root.rglob(filename)]
        assert candidates, f"this file cites {filename}::{symbol} and there is no {filename}"
        assert any(defines(p, symbol) for p in candidates), \
            f"this file cites `{filename}::{symbol}` and no {filename} in the tree defines it"


def _role_prompt_call_sites(root: Path) -> dict[str, set[str]]:
    """Every literal role name handed to `role_prompt(...)` / `_role_prompt(...)` under `root`,
    with the files that pass it — read from the syntax tree, so a docstring or a comment that
    MENTIONS the call is not a call.

    That distinction cost a red gate (2026-08-26): a sentence in the harness registry's docstring
    explaining that an add-on composes its prompt from `role_prompt` with its own name was scanned
    as a call site and reported as a prompt nobody checks — the strip-the-prose class, and the
    fix is to stop scanning prose rather than to forbid the sentence."""
    found: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            callee = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else None)
            first = node.args[0]
            if callee in ("role_prompt", "_role_prompt") and isinstance(first, ast.Constant) \
                    and isinstance(first.value, str):
                found.setdefault(first.value, set()).add(str(path.relative_to(root)))
    return found


def test_the_role_list_still_covers_every_call_site():
    """A LITERAL THAT CANNOT DRIFT. `ROLE_PROMPTS` is deliberately not a glob — a glob returns
    nothing exactly when the packaging bug is present, so the check would report "0 roles, all
    fine". The cost of a literal is drift, and this is what pays it: every literal any caller
    passes to `role_prompt` / `_role_prompt` has to be in the tuple."""
    called = _role_prompt_call_sites(Path(__file__).resolve().parent.parent / "openfactory")
    assert called, "the scan found no call sites at all — the pattern, not the code, is wrong"
    unchecked = {name: sorted(files) for name, files in called.items()
                 if name not in R.ROLE_PROMPTS}
    assert not unchecked, f"role prompts nobody checks: {unchecked}"


def test_the_call_site_scan_reads_code_and_not_the_sentence_explaining_it(tmp_path):
    """The verifier verified: fed a module whose docstring and comment both spell a call with a
    name no tuple checks, and whose code makes one real call, the scan sees the call alone. Without
    this the guard above is one explanatory sentence away from red, and the sentence is the one a
    stranger needs."""
    (tmp_path / "scratch.py").write_text(
        '"""An add-on composes its prompt from `roles.role_prompt("prose_only")` itself."""\n'
        "from openfactory.adapters.agent.roles import role_prompt\n"
        "# a reviewer once wrote role_prompt(\"comment_only\") here to explain the seam\n"
        "TEXT = role_prompt(\"really_called\")\n"
        "OTHER = roles._role_prompt(\"also_called\")\n")
    seen = _role_prompt_call_sites(tmp_path)
    assert set(seen) == {"really_called", "also_called"}, seen
    assert seen["really_called"] == {"scratch.py"}


# ── route: the registry's answer against the environment's ──────────────────────────────────────

def test_agreeing_routes_pass():
    assert by_check(R.assess(probes()))["route"].ok


def test_a_route_the_box_cannot_receive_is_a_failure():
    """The measured case: a worker configured for Bedrock whose project does not NAME
    `CLAUDE_CODE_USE_BEDROCK` in `box.env`. `container.py::_passthrough_env` carries only the named
    ones, so the harness gets nothing inside the box and the first agent call is the first symptom.
    """
    route = _Route(remedy="Bedrock needs CLAUDE_CODE_USE_BEDROCK and a region in `box.env`")
    f = by_check(R.assess(probes(declared_route=lambda: "anthropic",
                                 resolved_route=lambda: route)))["route"]
    assert not f.ok
    assert "'anthropic'" in f.message and "'bedrock'" in f.message
    assert route.remedy in f.remedy, "the route's own words, not a second copy of its table"


def test_the_route_remedy_offers_BOTH_directions_because_only_a_person_knows_which_is_right():
    """CAUGHT BY A REAL RUN, not by a fixture. Against `fx-dsk-flows` — a real .NET 8 repository
    whose `box.env` names `CLAUDE_CODE_USE_BEDROCK` — this printed the ANTHROPIC route's remedy
    ("the box passes these two through by default…"), because that is what the environment
    happened to resolve. Perfectly good advice about the wrong half of the contradiction.

    The disagreement has two directions: `box.env` may be missing what the environment resolves,
    OR the environment may be missing what the registry declares. The remedy names both, as
    executable options, because a human owns the decision and the machine owns neither side."""
    f = by_check(R.assess(probes(
        declared_route=lambda: "bedrock",
        resolved_route=lambda: _Route(name="anthropic",
                                      remedy="the box passes these two through by default"),
    )))["route"]
    assert "the box passes these two through by default" in f.remedy   # the resolved route's half
    assert "'bedrock' route's variables have to be set where the WORKER runs" in f.remedy
    assert "only a person can say which" in f.remedy


def test_an_opencode_prefix_is_not_a_disagreement():
    """`opencode/bedrock` and `bedrock` are the same provider reached by two harnesses. Comparing
    the prefix would report a disagreement that is not one, which is how a check gets ignored."""
    assert by_check(R.assess(probes(declared_route=lambda: "bedrock",
                                    resolved_route=lambda: _Route(name="opencode/bedrock")
                                    )))["route"].ok


def test_an_explicit_endpoint_override_is_not_a_disagreement():
    f = by_check(R.assess(probes(declared_route=lambda: "anthropic",
                                 resolved_route=lambda: _Route(name="declared",
                                                               endpoint="https://gw.corp/v1")
                                 )))["route"]
    assert f.ok and "https://gw.corp/v1" in f.message


def test_a_registry_that_cannot_say_which_route_is_unanswered_not_ok():
    f = by_check(R.assess(probes(declared_route=lambda: "")))["route"]
    assert not f.answered and f.ok


def test_a_harness_whose_route_cannot_be_named_is_unanswered_not_a_disagreement():
    """MEASURED ON A REAL REPOSITORY WITH `harness: codex` — the registry's own documented example
    (`contracts/project.py`) — and it was a permanent, confident FAIL over a correct deployment:

        FAIL route  the registry determines the 'anthropic' route for this project, and this
                    environment (local) resolves 'codex' — … the credentials this process holds
                    for 'codex' do not arrive where the harness runs

    `codex` is a HARNESS, not a route. `resolve_route`'s last branch is `AuthRoute(name=kind, …)`,
    reached for anything that is not `claude_code` or `opencode`; `declared_route` has no such
    branch and concludes `anthropic` from what `box.env` names. Two vocabularies, compared. Every
    codex or kimi deployment would have read that line on every machine, for ever.

    So the third state answers it: `name == harness_kind` is exactly "this environment has no
    provider to compare", which is not a pass and not a failure."""
    f = by_check(R.assess(probes(harness_kind=lambda: "codex",
                                 declared_route=lambda: "anthropic",
                                 resolved_route=lambda: _Route(name="codex", endpoint=""),
                                 )))["route"]
    assert not f.answered, "a category error was reported as a configuration failure"
    assert f.ok, "an absence must not be counted as a failure"
    assert "codex" in f.message and "OPENFACTORY_HARNESS_ENDPOINT" in f.message


def test_a_real_disagreement_is_still_a_failure_when_the_harness_is_known():
    """THE POSITIVE TWIN of the line above: the exemption is keyed on the resolved name EQUALLING
    the harness kind, so it must not swallow the case it sits next to — a `claude_code` project
    whose registry and environment genuinely disagree."""
    f = by_check(R.assess(probes(harness_kind=lambda: "claude_code",
                                 declared_route=lambda: "anthropic",
                                 resolved_route=lambda: _Route(name="bedrock"))))["route"]
    assert f.answered and not f.ok and f.remedy


# ── env_names: a typo and an unset variable are the same thing today ────────────────────────────

def test_a_name_that_is_not_set_is_named():
    f = by_check(R.assess(probes(box_env_names=lambda: ["A", "B"],
                                 environ=lambda: {"A": "1"})))["env_names"]
    assert not f.ok and "not set at all: B" in f.message


def test_a_name_that_is_set_and_empty_is_a_separate_bucket():
    """`FOO=""` is falsy, so `_passthrough_env` DROPS it exactly as it drops a typo. An operator who
    has just run `env | grep FOO` and seen a line has no way to tell it from a working one."""
    f = by_check(R.assess(probes(box_env_names=lambda: ["A"],
                                 environ=lambda: {"A": ""})))["env_names"]
    assert not f.ok and "set but empty: A" in f.message
    assert "not set at all" not in f.message


def test_a_whitespace_value_is_reported_too_and_for_its_own_reason():
    """`FOO="  "` is truthy, so it IS passed into the box — and then `AuthRoute.missing` strips it
    and reads the route as incomplete. Same symptom, different mechanism, and the message says so
    rather than leaving somebody to find out twice."""
    f = by_check(R.assess(probes(box_env_names=lambda: ["A"],
                                 environ=lambda: {"A": "   "})))["env_names"]
    assert not f.ok and "set but empty: A" in f.message
    assert "AuthRoute.missing" in f.message


def test_no_declared_names_is_a_pass_that_says_what_the_box_does_get():
    f = by_check(R.assess(probes(box_env_names=lambda: [])))["env_names"]
    assert f.ok and "_AUTH_ENV_VARS" in f.message


def test_the_env_check_says_whose_environment_it_read():
    f = by_check(R.assess(probes(measured_on=lambda: R.LOCAL)))["env_names"]
    assert f.ok and "local environment" in f.message


# ── registry parity: is this a report about a project the factory has heard of? ─────────────────

def test_on_the_worker_there_is_nothing_to_compare():
    f = by_check(R.assess(probes()))["registry_parity"]
    assert f.ok and f.answered and "IS the deployment's registry" in f.message


def test_a_project_absent_from_the_workers_registry_is_a_failure():
    """READ, and not there. Every other line in the report is then about a project the factory has
    never heard of — which is not a warning, it is the headline."""
    f = by_check(R.assess(probes(measured_on=lambda: R.LOCAL,
                                 worker_registry_entry=lambda: None)))["registry_parity"]
    assert not f.ok and "does not contain 'fx-py-simple'" in f.message and f.remedy


def test_a_registry_that_could_not_be_read_is_not_a_failure():
    """The ordinary case on a laptop. Reporting it as a failure would make every local run print a
    line nobody can act on, which is how a tool teaches people to skim it."""
    f = by_check(R.assess(probes(
        measured_on=lambda: R.LOCAL,
        worker_registry_entry=_raises(R.RegistryUnreachable("no file at /var/lib/openfactory/registry.yaml"))
    )))["registry_parity"]
    assert f.ok and not f.answered
    assert "not answered" in f.message and "no file at" in f.message


def test_differing_values_name_the_keys():
    f = by_check(R.assess(probes(
        measured_on=lambda: R.LOCAL,
        registry_entry=lambda: {"name": "fx-py-simple", "enabled": True, "harness": "claude_code"},
        worker_registry_entry=lambda: {"name": "fx-py-simple", "enabled": False,
                                       "harness": "codex"},
    )))["registry_parity"]
    assert not f.ok and "enabled, harness" in f.message


def test_a_repo_path_that_differs_is_named_but_is_not_a_failure():
    """THE ONLY DIFFERENCE THIS CHECK COULD EVER SEE ON A LIVE DEPLOYMENT, and it was a FAIL with a
    remedy nobody can follow.

    `deploy/registry.yaml` carries `repo_path: /work/<project>` with the comment "repo_path is a
    placeholder — the Fargate job clones the repo fresh from the forge"; a laptop's entry names the
    laptop's checkout. `activities.py` says the same in its own words above `RepoCache().sync`: on
    the worker that value "names no real directory at all". So this printed "this report describes
    a configuration the factory is not running → reconcile the two … a rebuild and a deploy" over a
    correct setup, every time it could speak.

    It is not hidden — "quietly dropped from the comparison" is the absence-reads-as-compliance
    shape this whole module is written against. Both values are printed, on a passing line."""
    f = by_check(R.assess(probes(
        measured_on=lambda: R.LOCAL,
        registry_entry=lambda: {"name": "fx-py-simple", "repo_path": "/Users/x/Projects/fx"},
        worker_registry_entry=lambda: {"name": "fx-py-simple", "repo_path": "/work/fx"},
    )))["registry_parity"]
    assert f.ok and f.answered, "an expected difference was reported as a configuration failure"
    assert "/Users/x/Projects/fx" in f.message and "/work/fx" in f.message, \
        "the exemption hides the fact instead of explaining it"


def test_a_repo_path_difference_does_not_hide_a_real_one():
    """THE POSITIVE TWIN. An exemption that swallows its neighbours is worse than the false alarm
    it removed — `enabled` differing is the difference that decides whether the factory polls at
    all, and it must still fail while `repo_path` differs alongside it."""
    f = by_check(R.assess(probes(
        measured_on=lambda: R.LOCAL,
        registry_entry=lambda: {"name": "fx-py-simple", "repo_path": "/Users/x/fx",
                                "enabled": True},
        worker_registry_entry=lambda: {"name": "fx-py-simple", "repo_path": "/work/fx",
                                       "enabled": False},
    )))["registry_parity"]
    assert not f.ok and "enabled" in f.message and f.remedy
    assert "repo_path" in f.message, "the second difference vanished from the message"


# ── provenance is measured, not declared ────────────────────────────────────────────────────────

def test_the_live_registry_path_is_what_makes_this_the_worker():
    from openfactory.registry import LIVE_REGISTRY_PATH

    assert R.where_this_answers_for(LIVE_REGISTRY_PATH) == R.WORKER
    assert R.where_this_answers_for(Path("/Users/x/.openfactory/registry.yaml")) == R.LOCAL


# ── the LIVE probes, because everything above runs against fakes ────────────────────────────────
#
# Every test to this point hands `assess` a `Probes` somebody wrote. That proves the logic and
# proves nothing about the wiring — which is this codebase's signature defect, shipped twenty-one
# times: built, tested, reached by nothing. These exercise `probes_for` itself, without a network,
# a docker daemon or a credential.

@pytest.fixture()
def a_real_project(tmp_path, monkeypatch):
    """A registered project with a manifest on disk, built the way the platform builds one."""
    import yaml

    from openfactory.contracts.project import Project

    repo = tmp_path / "dotnet"
    (repo / namespace.DIR).mkdir(parents=True)
    (repo / namespace.MANIFEST).write_text(yaml.safe_dump({
        "version": 1, "setup": ["dotnet restore"],
        "validate": {"test": "dotnet test", "security": {"command": "trivy fs .",
                                                         "advisory": True}},
    }))
    registry = tmp_path / "registry.yaml"
    entry = {"name": "legacy", "repo_path": str(repo), "enabled": False,
             "box": {"env": ["NUGET_FEED_TOKEN"]}}
    registry.write_text(yaml.safe_dump({"projects": {"legacy": entry}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(registry))
    return Project(**entry)


def test_the_live_probes_read_the_registry_and_the_manifest(a_real_project):
    """No fakes: the real `probes_for`, against a real manifest and a real registry entry."""
    p = R.probes_for(a_real_project)
    assert p.project_name == "legacy"
    assert p.enabled() is False                       # the registry entry says so
    assert p.box_env_names() == ["NUGET_FEED_TOKEN"]  # the `box:` block is reached
    assert p.floor_reason() is None                   # test + security are both declared
    assert p.registry_entry()["name"] == "legacy"
    assert p.role_prompt("techlead").strip(), "the shipped role prompts are unreachable from here"
    # the harness axis, from the same resolver both route functions use
    assert p.harness_kind() == "claude_code"
    # the box trait table, not a local copy of it
    assert p.box_honours_image("container") is True
    assert p.box_honours_image("fargate") is False
    assert p.box_honours_image("no-such-box") is False


def test_the_live_probes_read_the_real_product_block(tmp_path, monkeypatch):
    """The wiring, not the logic: `probes_for` against a registry entry that really has a
    `product:` block, parsed by the real `Project` model.

    Every product test above hands `assess` a `Probes` I wrote, which would pass just as happily if
    `probes_for` had never been taught to read `product.admins` — the twenty-one-time defect, in
    the check written to catch a twenty-second."""
    import yaml

    from openfactory.contracts.project import Project

    repo = tmp_path / "dsk"
    (repo / namespace.DIR).mkdir(parents=True)
    (repo / namespace.MANIFEST).write_text(yaml.safe_dump({"version": 1}))
    entry = {"name": "dsk", "repo_path": str(repo),
             "product": {"enabled": True, "docs_repo": "acme/dsk-context",
                         "admins": ["ana", "bruno"]}}
    registry = tmp_path / "registry.yaml"
    registry.write_text(yaml.safe_dump({"projects": {"dsk": entry}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(registry))

    p = R.probes_for(Project(**entry))
    assert p.product_enabled() is True
    assert p.product_admins() == ["ana", "bruno"]

    # …and switched off, the same block reads as off rather than as absent
    off = dict(entry, product=dict(entry["product"], enabled=False))
    assert R.probes_for(Project(**off)).product_enabled() is False

    # …and a project with no `product:` at all answers without raising
    bare = {k: v for k, v in entry.items() if k != "product"}
    bare_probes = R.probes_for(Project(**bare))
    assert bare_probes.product_enabled() is False
    assert bare_probes.product_admins() == []


def test_the_live_probes_read_the_real_route_functions(a_real_project, monkeypatch):
    """`declared_route` reads what `box.env` NAMES; `resolve_route` reads this process. The whole
    point of the check is that these are two different sources, so the probes must be two."""
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("OPENFACTORY_HARNESS_ENDPOINT", raising=False)
    p = R.probes_for(a_real_project)
    assert p.declared_route() == "anthropic"      # box.env names no discriminating variable
    assert p.resolved_route().name == "anthropic"

    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_REGION", "eu-west-2")
    p = R.probes_for(a_real_project)
    assert p.declared_route() == "anthropic", "the registry still names no Bedrock variable"
    assert p.resolved_route().name == "bedrock", "the environment does"
    # …and that is the disagreement the check exists to report, on the real functions
    finding, _ = R._route(p, R.LOCAL)
    assert not finding.ok and "'bedrock'" in finding.message


def test_the_worker_registry_probe_has_three_answers(a_real_project, tmp_path, monkeypatch):
    """`None` = read it, this project is not there. Raise = could not look. A dict = compare.

    Two values cannot carry three meanings — `doctor.BoardUnreadable` paid for that lesson, and
    collapsing "could not look" into either of the others here would certify a registry nobody
    read or accuse a correct deployment of not knowing its own project."""
    import yaml

    live = tmp_path / "live.yaml"

    # 1. the file is not there at all
    monkeypatch.setattr("openfactory.registry.LIVE_REGISTRY_PATH", live)
    with pytest.raises(R.RegistryUnreachable):
        R.probes_for(a_real_project).worker_registry_entry()

    # 2. it is there and this project is not in it
    live.write_text(yaml.safe_dump({"projects": {"other": {"name": "other", "repo_path": "/x"}}}))
    monkeypatch.setattr("openfactory.registry.LIVE_REGISTRY_PATH", live)
    assert R.probes_for(a_real_project).worker_registry_entry() is None

    # 3. it is there and holds it
    live.write_text(yaml.safe_dump({"projects": {"legacy": {"name": "legacy",
                                                            "repo_path": "/elsewhere"}}}))
    monkeypatch.setattr("openfactory.registry.LIVE_REGISTRY_PATH", live)
    entry = R.probes_for(a_real_project).worker_registry_entry()
    assert entry["repo_path"] == "/elsewhere"

    # …and the check turns that into a named difference rather than a shrug
    finding, _ = R._registry_parity(R.probes_for(a_real_project), R.LOCAL)
    assert not finding.ok and "repo_path" in finding.message


def test_the_live_proof_probes_point_at_the_directory_the_poller_reads(a_real_project):
    from openfactory.box_prove import PROOF_DIR

    p = R.probes_for(a_real_project)
    assert p.proof_dir() == str(PROOF_DIR)
    # `gate_reason` must be callable with no proof, no docker and no crash — it runs on every tick
    assert isinstance(p.gate_reason(), (str, type(None)))


def test_every_probe_is_reached_by_some_check():
    """A PROBE NOTHING CALLS DOES NOT EXIST — this codebase's signature defect, shipped twenty-one
    times, and a `Probes` field is exactly the shape it takes here: declared, wired in
    `probes_for`, typed, documented, and asked by nobody. Nothing above would go red, because every
    test hands `assess` a probe set and reads the findings.

    So the probes are INSTRUMENTED and `assess` is run over the worlds that reach each branch, and
    the union of what was actually called has to be the whole dataclass. `harness_kind` was added
    for the codex finding; this is what stops the next one being added and never asked."""
    import dataclasses

    called: set[str] = set()

    def watched(**over):
        base = probes(**over)
        wrapped = {}
        for f in dataclasses.fields(base):
            value = getattr(base, f.name)
            if not callable(value):
                continue

            def spy(*a, _n=f.name, _v=value, **kw):
                called.add(_n)
                return _v(*a, **kw)

            wrapped[f.name] = spy
        return dataclasses.replace(base, **wrapped)

    # the healthy worker world, then the worlds that reach the branches it does not
    for world in ({}, {"measured_on": lambda: R.LOCAL},                    # registry parity
                  {"box_honours_image": lambda kind: False},               # the inert gate
                  {"declared_route": lambda: "anthropic"},                 # a route disagreement
                  {"floor_reason": lambda: "no `security` validation"},    # advice or a hold
                  {"product_enabled": lambda: True}):                      # the client's surface
        R.assess(watched(**world))

    every = {f.name for f in dataclasses.fields(R.Probes) if f.name != "project_name"}
    assert every <= called, f"probes nothing asks: {sorted(every - called)}"


# ── the client's half of the deployment ─────────────────────────────────────────────────────────
#
# The round owns the PO's setup — *"a rodada já configura o PO sim, querer usar é outra coisa … mas
# setup é setup, sai com tudo"*. These are the two facts about it that nothing else asks: `admins`
# appears in neither `product/config.py`'s resolution nor `doctor.py`, and no report anywhere checks
# that a credential exists for the surface the client is supposed to use.

def test_an_enabled_product_role_with_no_approvers_is_a_failure():
    """The state that passes every other check and fails at the client's first request.

    `resolve_product_link` never reads `admins` — it reconciles the corpus — so a role with an
    empty allowlist resolves ACTIVE and `doctor` reports `product_link` green. Reading is not
    gated, so the client can hold a whole conversation with it and meets the refusal only when
    they try to agree to something."""
    report = R.assess(probes(product_enabled=lambda: True, product_admins=lambda: []))
    f = by_check(report)["product_role"]
    assert not f.ok, f.message
    assert "approver list is empty" in f.message
    # the remedy names the field, not the symptom
    assert "product.admins" in f.remedy


def test_an_unreachable_product_role_never_holds_the_floor():
    """It is a failure, and it is NOT a hold — those are different sentences with different fixes.

    Tickets are still picked up, agents still work, releases still happen: what is broken is the
    client's ability to ASK. Reporting it as a hold sends an operator hunting for a stalled queue
    that is moving perfectly well, and — because the first hold is the headline — would let it
    outrank a fact that really does stop the factory."""
    report = R.assess(probes(product_enabled=lambda: True, product_admins=lambda: []))
    assert not any("product" in h for h in report.holds), report.holds
    assert not report.verdict.startswith("HELD"), report.verdict


def test_a_configured_product_role_with_no_product_credential_is_a_failure():
    """Configured and reachable by nobody — this codebase's most repeated defect, on the surface
    the client was sold.

    The door is closed (a floor credential exists) and no product credential was issued, so the
    only way in opens the whole panel. There is nothing to hand the client."""
    report = R.assess(probes(
        product_enabled=lambda: True, product_admins=lambda: ["ana"],
        environ=lambda: {"CLAUDE_CODE_USE_BEDROCK": "1", "OPENFACTORY_PANEL_TOKEN": "s3cret"}))
    f = by_check(report)["product_role"]
    assert not f.ok, f.message
    assert "no product credential is issued" in f.message
    assert "OPENFACTORY_PRODUCT_TOKENS" in f.remedy


def test_an_open_deployment_is_not_asked_for_a_credential_it_has_no_use_for():
    """Nothing configured at all is the local-development default: every request is permitted, so
    there is no credential to issue and no lock-out to report.

    THE ARM THAT KEEPS THE CHECK HONEST. Demanding a product token here would be a failure about a
    world where the client already has access — advice that makes the report wrong rather than
    strict."""
    report = R.assess(probes(
        product_enabled=lambda: True, product_admins=lambda: ["ana"],
        environ=lambda: {"CLAUDE_CODE_USE_BEDROCK": "1"}))
    f = by_check(report)["product_role"]
    assert f.ok, f.message
    assert "open to everyone" in f.message


def test_a_configured_product_role_reports_who_may_approve():
    report = R.assess(probes(
        product_enabled=lambda: True, product_admins=lambda: ["ana", "bruno"],
        environ=lambda: {"CLAUDE_CODE_USE_BEDROCK": "1", "OPENFACTORY_PRODUCT_TOKENS": "ana:t"}))
    f = by_check(report)["product_role"]
    assert f.ok, f.message
    assert "2 approver(s)" in f.message and "ana" in f.message
    assert "a product credential is issued" in f.message


def test_a_project_with_no_product_role_is_not_nagged():
    """Configuring and adopting are different questions. Most projects never enable this, and a
    report that treated absence as an unfinished install would cry wolf on every one of them."""
    f = by_check(R.assess(probes()))["product_role"]
    assert f.ok and "no product role is configured" in f.message


def test_the_product_check_reads_the_doors_own_variable_names(monkeypatch):
    """The remedy tells somebody to set a variable. If it names one by literal and the gate is
    renamed, the report keeps confidently naming a variable that opens nothing.

    THE OBVIOUS VERSION OF THIS TEST CANNOT GO RED: asserting `local.PRODUCT_PEOPLE_ENV in remedy`
    is satisfied by a hardcoded `"OPENFACTORY_PRODUCT_TOKENS"`, because the literal and the constant are
    the same string today — a guard that passes whether or not the property holds. So the name is
    MOVED, and the remedy has to follow it."""
    from openfactory.identity import local

    monkeypatch.setattr(local, "PRODUCT_PEOPLE_ENV", "OPENFACTORY_RENAMED_PEOPLE")
    monkeypatch.setattr(local, "PRODUCT_SHARED_ENV", "OPENFACTORY_RENAMED_SHARED")
    report = R.assess(probes(
        product_enabled=lambda: True, product_admins=lambda: ["ana"],
        environ=lambda: {"OPENFACTORY_PANEL_TOKEN": "s3cret"}))
    remedy = by_check(report)["product_role"].remedy
    assert "OPENFACTORY_RENAMED_PEOPLE" in remedy and "OPENFACTORY_RENAMED_SHARED" in remedy


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────

def _raises(exc):
    def _boom(*_a, **_kw):
        raise exc
    return _boom


@pytest.fixture(autouse=True)
def _no_ambient_environment(monkeypatch):
    """Nothing here may read the developer's shell. Every probe is injected; this is the floor
    underneath that, because a probe added later without one would pass on one machine only."""
    monkeypatch.delenv("OPENFACTORY_ENFORCE_FLOOR", raising=False)
    monkeypatch.delenv("OPENFACTORY_FARGATE_CLUSTER", raising=False)
