"""The quality floor becomes real without editing every client repository (#99).

WHAT WAS MEASURED BEFORE THIS. `policy/conformance._effective_validation` reads
`manifest.validate ∪ (per-component preset ∪ per-component validate)` — every term of it inside
the client's own `.sdlc/project.yaml`. There was no deployment-level term at all, so "adopt the
security preset across the fleet" meant editing every client repository by hand, including a live
one in production, and a NEW client inherited nothing: the hole reopened at every onboarding.
Measured against the real registry, an enforced floor would have HELD `fx-py-simple` and `fx-dsk`
on every ticket for want of one line each — which is why the floor was behind an off-by-default
switch at all. This file removed that reason; `OPENFACTORY_ENFORCE_FLOOR` was then removed too, and the
floor refuses unconditionally.

WHAT THESE GUARDS ARE FOR, and it is one specific failure. A default that satisfies the floor
without the gate RUNNING is not a fix, it is the same hole with a green light over it: every
project passes because the deployment said so. `_effective_validation` is what the floor INSPECTS;
`orchestrator.validation.applicable_validations` is what the job EXECUTES. Satisfying one and not
the other is this codebase's signature defect (~21 shipped occurrences), so the first two tests
below assert BOTH ends of that pair, and the rest hold the properties that make the default safe
to inherit: it never removes a command that would already have run, it never forges provenance, it
never lies when it cannot read itself, and it actually executes in the images clients bring.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from openfactory.contracts import Manifest, ValidationResult
from openfactory.orchestrator.validation import applicable_validations, as_gate
from openfactory.policy import floor
from openfactory.policy.conformance import (
    _effective_validation,
    check,
    floor_reason,
    inherited_floor_roles,
)
from openfactory.policy.presets import ORG_FLOOR_FILE, load_preset, org_default_validation

REPO = Path(__file__).resolve().parent.parent


def _floor_roles() -> set[str]:
    return set(org_default_validation() or {})


# ── the headline: what the floor inspects and what the job runs are the same thing ───────────────

def test_the_deployment_default_reaches_the_map_the_job_actually_EXECUTES():
    """`applicable_validations` — machine.py:1587 iterates exactly this and runs each command.

    A diff that reaches no declared component is the case the floor was missing: it takes only the
    repo-wide map, which is where a project that never wrote `security:` had nothing at all."""
    m = Manifest(validate={"test": "pytest -q"})

    assert _floor_roles(), "the deployment ships no default gate — there is nothing to inherit"
    assert _floor_roles() <= set(applicable_validations([], m))


def test_the_floor_INSPECTS_exactly_what_it_EXECUTES():
    """The signature defect, asserted as an equality rather than as two separate passes.

    Both sides are computed from the same manifest; if a future change installs the default
    somewhere only one of them reads, this is the test that says so."""
    for m in (Manifest(),
              Manifest(validate={"test": "pytest -q"}),
              Manifest(components={"api": {"path": "api/**", "stack": "python"}}),
              Manifest(validate={"test": "t"},
                       components={"api": {"path": "api/**", "stack": "security-oss"}})):
        runs = set(applicable_validations([], m))
        inspected = _effective_validation(m)
        assert _floor_roles() <= runs, m
        assert _floor_roles() <= inspected, m
        assert runs <= inspected, m


def test_the_two_projects_the_real_registry_would_have_HELD_now_pass_the_floor():
    """Measured, not hypothetical: `fx-py-simple` and `fx-dsk` declare `test` and nothing else, so
    an enforced floor would hold every ticket of both. Their manifests, inline."""
    for validate in ({"test": "python -m pytest -q"},
                     {"test": "dotnet test tests/Flows.Tests.csproj --nologo -v quiet"}):
        m = Manifest(version=1, base_branch="main", merge_policy="human", validate=validate)
        assert floor_reason(m) is None
        assert "security" in applicable_validations([], m)


def test_the_role_no_deployment_can_guess_is_still_refused():
    """The positive twin of the tests above, and the reason the floor is not now vacuous: there is
    no command that runs a project's tests in every language, so `test` is never defaulted and a
    project without one is still refused. A floor.yaml that grew a guessed `test:` would turn every
    project green on a gate that tests nothing — this is what would notice."""
    assert "test" not in _floor_roles()
    reason = floor_reason(Manifest(validate={"security": "s"}))
    assert reason is not None and "`test`" in reason


# ── inheriting never takes anything away ─────────────────────────────────────────────────────────

def test_a_project_that_declares_the_role_keeps_its_own_command():
    m = Manifest(validate={"test": "pytest -q", "security": "make security"})

    assert as_gate(m.validation["security"]).command == "make security"
    assert as_gate(applicable_validations([], m)["security"]).command == "make security"
    assert inherited_floor_roles(m) == set()


def test_inheriting_a_gate_never_REMOVES_a_command_that_would_already_have_run():
    """THE INVARIANT, over the powerset of touched components rather than over one example.

    Repo-wide beats a component's stack preset in `applicable_validations`, so putting the
    deployment default there would silently have replaced the `python` preset's `bandit` and
    `terraform`'s `tfsec` for the diffs that reach those components — and removed them from what
    `box_prove.component_gates` proves the image can run. `Manifest._inherit_the_deployment_floor`
    pins each preset command onto its component first. This walks every subset and compares the
    resolved command, role by role, against the same manifest with nothing inherited."""
    from itertools import chain, combinations

    spec = dict(validate={"test": "pytest -q"},
                components={"api": {"path": "api/**", "stack": "python"},
                            "infra": {"path": "infra/**", "stack": "terraform"},
                            "web": {"path": "web/**", "stack": "node",
                                    "validate": {"security": "npm audit"}}})
    after = Manifest(**spec)
    names = sorted(after.components)
    subsets = chain.from_iterable(combinations(names, n) for n in range(len(names) + 1))

    # the same manifest as its own file describes it, with no deployment term at all
    from openfactory.policy import presets as presets_mod

    real, presets_mod.org_default_validation = presets_mod.org_default_validation, lambda: {}
    try:
        before = Manifest(**spec)
    finally:
        presets_mod.org_default_validation = real

    for touched in subsets:
        was = applicable_validations(list(touched), before)
        now = applicable_validations(list(touched), after)
        for role, cmd in was.items():
            assert as_gate(now[role]).command == as_gate(cmd).command, (touched, role)
        assert set(was) <= set(now)


def test_the_preset_gate_stays_visible_to_the_box_proof():
    """`box_prove.component_gates` skips any gate the repo-wide map already carries, so a default
    that shadowed the preset would ALSO have stopped proving the tool exists in the image — the
    C-35 hole (47 agent turns, then `ruff: not found`) reopened one level up."""
    from openfactory.box_prove import component_gates

    gates = component_gates(Manifest(validate={"test": "pytest -q"},
                                     components={"api": {"path": "api/**", "stack": "python"}}))
    assert gates.get("api:security") == load_preset("python")["validate"]["security"]


# ── the default never pretends to be the client's ────────────────────────────────────────────────

def test_the_inherited_gate_does_not_forge_provenance():
    """`declared_keys()` exists to tell "the client wrote `validate:`" from "the client never wrote
    it" — **read, nothing there** and **never written** are different facts, and `doctor`/`env
    check` report them differently. Assigning to a field marks it set, so an unrestored
    `model_fields_set` would make every manifest in the fleet claim it had declared `validate:`:
    the inherited gate erasing the evidence that it was inherited."""
    assert "validate" not in Manifest().declared_keys()
    assert "validate" in Manifest(validate={"test": "pytest -q"}).declared_keys()
    assert "security" in Manifest().validation  # …and it is genuinely there


def test_conformance_says_out_loud_which_roles_are_the_DEPLOYMENTS():
    """The trap this change was warned about: every project passes because the deployment said so,
    and a client reads `ok: True` believing their own team declared a scanner. The report names the
    role, the command it will run, and the one-line way to replace it."""
    issues = check(Manifest(validate={"test": "pytest -q"}), REPO).issues
    said = [i for i in issues if "DEPLOYMENT" in i.message]

    assert len(said) == 1, [i.message for i in issues]
    assert said[0].level == "warning"  # inheriting the floor is correct, not an error
    assert "'security'" in said[0].message and "git grep" in said[0].message
    assert "Declare" in said[0].message


def test_a_project_declaring_its_own_gate_is_not_told_it_inherited_one():
    issues = check(Manifest(validate={"test": "t", "security": "make security"}), REPO).issues
    assert not [i for i in issues if "DEPLOYMENT" in i.message]


# ── a build that cannot read its own floor says so ───────────────────────────────────────────────

def test_unreadable_is_not_the_same_answer_as_empty(tmp_path, monkeypatch):
    """**None = could not read. {} = read, nothing there.** Collapsing them here would make the
    floor evaporate in exactly the installation where nobody is watching."""
    import openfactory.policy.presets as presets_mod

    monkeypatch.setattr(presets_mod, "ORG_FLOOR_FILE", tmp_path / "absent.yaml")
    presets_mod.org_default_validation.cache_clear()
    assert presets_mod.org_default_validation() is None

    deliberate = tmp_path / "empty.yaml"
    deliberate.write_text("# this deployment ships no default gate\n")
    monkeypatch.setattr(presets_mod, "ORG_FLOOR_FILE", deliberate)
    presets_mod.org_default_validation.cache_clear()
    assert presets_mod.org_default_validation() == {}

    presets_mod.org_default_validation.cache_clear()  # leave the process reading the real file


def test_an_unreadable_default_fails_CLOSED_and_blames_the_install(tmp_path, monkeypatch):
    """Fail-open would be the catastrophe: no gate inherited, every project silently conformant.
    Instead nothing is inherited, `floor_reason` refuses exactly as it did before this file
    existed, and the sentence points at the INSTALL rather than at the client's repository — a
    stranger sent to edit a file that is already correct is the failure `doctor` exists to end."""
    import openfactory.policy.presets as presets_mod

    monkeypatch.setattr(presets_mod, "ORG_FLOOR_FILE", tmp_path / "absent.yaml")
    presets_mod.org_default_validation.cache_clear()
    try:
        m = Manifest(validate={"test": "pytest -q"})
        assert "security" not in m.validation
        reason = floor_reason(m)
        assert reason and "org_defaults/floor.yaml" in reason
        report = check(m, REPO)
        errors = [i for i in report.issues if i.level == "error"]
        assert report.ok is False
        assert any("cannot read its own default gates" in i.message for i in errors)
    finally:
        presets_mod.org_default_validation.cache_clear()


def _no_floor(monkeypatch) -> None:
    """The world in which BOTH required roles can be missing — which is the only world where the
    `security` half of the refusal is reachable at all once `floor.yaml` ships. Patching the
    presets module reaches `Manifest`'s late import, which is where the inheritance happens."""
    monkeypatch.setattr("openfactory.policy.presets.org_default_validation", lambda: {})


#: Every YAML snippet the refusal prints inside backticks, e.g. `components: {scan: {…}}`.
_SNIPPET = re.compile(r"`(components: \{[^`]*\})`")


def test_a_floor_the_install_cannot_DECODE_is_still_the_INSTALLS_fault(tmp_path, monkeypatch):
    """THE ONE BRANCH THAT ESCAPED. Every other unreadable shape returns None and blames the
    install; a `floor.yaml` that is not valid UTF-8 — a truncated or corrupted copy in an image
    layer — raised `UnicodeDecodeError`, which is a `ValueError` and not an `OSError`, straight out
    of `read_text`. This function is called from a `Manifest` model validator, so it came back as
    `ValidationError: 1 validation error for Manifest`: a broken INSTALL reported to the client as
    a broken `.sdlc/project.yaml`, and EVERY project in the fleet stopped loading at once."""
    import openfactory.policy.presets as presets_mod

    corrupt = tmp_path / "floor.yaml"
    corrupt.write_bytes(b"\xff\xfe\x00validate:\n  security: s\n")
    monkeypatch.setattr(presets_mod, "ORG_FLOOR_FILE", corrupt)
    presets_mod.org_default_validation.cache_clear()
    try:
        assert presets_mod.org_default_validation() is None
        m = Manifest(validate={"test": "pytest -q"})  # the manifest still LOADS
        assert "security" not in m.validation
        assert any("cannot read its own default gates" in i.message
                   for i in check(m, REPO).issues if i.level == "error")
    finally:
        presets_mod.org_default_validation.cache_clear()


def test_every_manifest_snippet_the_floor_PRINTS_is_one_the_schema_ACCEPTS(monkeypatch):
    """Measured live on #99: the refusal used to end "adopt a preset that carries one (`stack:
    security-oss` ships free advisory scanners)" — and `Manifest(stack='security-oss')` is a
    ValidationError, because `Manifest` has no `stack` field and is `extra="forbid"`. The platform
    printed an instruction its own schema refuses, to a client on their first day.

    ASKED OF EVERY MISSING-ROLE SHAPE, not of one example, and with the deployment floor suppressed
    so `security` is reachable as a missing role at all — with `floor.yaml` installed it never is,
    which is exactly how the successor defect below hid."""
    _no_floor(monkeypatch)
    for validate in ({}, {"test": "t"}, {"security": "s"}):
        reason = floor_reason(Manifest(validate=validate))
        assert reason
        assert "`stack: security-oss`" not in reason  # the form that does not load
        for snippet in _SNIPPET.findall(reason):
            Manifest(**yaml.safe_load(snippet))  # loads, which is the whole claim

    with pytest.raises(ValidationError):
        Manifest(**yaml.safe_load("stack: security-oss"))  # what it used to tell people to write


@pytest.mark.parametrize("missing", sorted(floor.REQUIRED_VALIDATION_ROLES))
def test_every_required_role_has_a_remedy_that_actually_LIFTS_the_refusal(missing, monkeypatch):
    """A SNIPPET THAT LOADS IS NOT A SNIPPET THAT FIXES ANYTHING, and the gap between those two
    claims was live: the test above was satisfied by a schema-valid sentence, and the sentence was
    the same one for every role.

    MEASURED. `floor.yaml` makes `security` inherited by every project, so on a healthy install
    `test` is the only role that can be missing — and the shared sentence told that client to write
    `security: "<your scanner>"` or to add a `stack: security-oss` component. Both load. Neither
    declares a `test` gate. `floor_reason` returned the identical sentence afterwards, so under
    an enforced floor the client does exactly what they were told and the next tick holds
    again, with the same words. This applies the remedy and asserts the refusal LIFTS."""
    _no_floor(monkeypatch)
    others = {r: "cmd" for r in floor.REQUIRED_VALIDATION_ROLES if r != missing}
    reason = floor_reason(Manifest(validate=others))

    assert reason and f"`{missing}`" in reason
    # the key it tells them to write is the one that is MISSING, not a different required role
    assert f"`{missing}:" in reason
    for other in floor.REQUIRED_VALIDATION_ROLES - {missing}:
        assert f"`{other}:" not in reason, f"the remedy for a missing {missing} names {other}"

    # every executable form it offers — the direct one and any component snippet — actually works
    assert floor_reason(Manifest(validate={**others, missing: "cmd"})) is None
    for snippet in _SNIPPET.findall(reason):
        applied = Manifest(validate=others, **yaml.safe_load(snippet))
        assert floor_reason(applied) is None, f"the snippet {snippet!r} leaves {missing} missing"


# ── the gate is one a client's own image can actually run ────────────────────────────────────────

def _run(cmd: str, cwd: Path) -> tuple[int, str]:
    p = subprocess.run(["sh", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


def _git_repo(root: Path, contents: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "app.py").write_text(contents)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


@pytest.fixture(scope="module")
def security_command() -> str:
    return as_gate(org_default_validation()["security"]).command


def test_the_default_gate_needs_only_a_shell_and_git(security_command):
    """The two things `box_prove`'s `contract` station already REFUSES an image for, so these are
    preconditions the platform enforces rather than hopes for. Measured before choosing this
    command: semgrep, trivy, gitleaks and bandit are all absent from the framework's own default
    box image (`openfactory-python:sandbox`) AND from the .NET client's (`mcr.microsoft.com/dotnet/
    sdk:8.0`) — adopting `security-oss` verbatim would have exited 127 on every job of every
    project and failed `box prove`'s `validate` station fleet-wide."""
    assert "git " in security_command
    for tool in ("semgrep", "trivy", "gitleaks", "bandit", "pip ", "npm ", "python"):
        assert tool not in security_command


#: `git` subcommands that change a repository. Everything the platform is forbidden to do to a
#: client's tree without being asked goes through one of these.
_GIT_WRITES = ("add", "commit", "push", "checkout", "reset", "clean", "rm", "mv", "restore",
               "stash", "merge", "rebase", "branch", "tag", "fetch", "pull", "config", "apply",
               "update-ref", "gc", "prune", "filter-branch", "switch", "worktree", "init")


def test_the_deployments_default_gates_can_only_READ_a_clients_repository():
    """THE BLAST RADIUS IS WHY THIS IS ASSERTED RATHER THAN BELIEVED. Every gate in `floor.yaml`
    runs inside every registered project's checkout, on every diff, without any client ever having
    written it down — that is the whole point of a deployment default, and it is also the largest
    reach any single line in this repository has into somebody else's world. `git grep` is a read;
    a future edit to this file that reached for `git checkout --` or `git config` to "clean up
    first" would be a fleet-wide write nobody opted into, and it would land through a YAML file
    that no schema validates.

    Eleven smoke tickets are already on the record for a change whose reach was not checked before
    it ran. So: no git write verb, no shell redirection into the tree, and no `rm`."""
    gates = org_default_validation() or {}
    assert gates, "the deployment ships no default gate — there is nothing to check"
    for role, gate in gates.items():
        cmd = as_gate(gate).command
        for verb in _GIT_WRITES:
            assert f"git {verb}" not in cmd, f"the '{role}' floor gate WRITES: `git {verb}`"
        assert ">" not in cmd.replace("2>&1", "").replace(">&2", ""), (
            f"the '{role}' floor gate redirects output into the client's tree: {cmd[:120]}")
        assert "rm " not in cmd and "mv " not in cmd, f"the '{role}' floor gate deletes: {cmd[:120]}"


def test_a_clean_repository_is_green_and_a_planted_credential_is_not(security_command):
    with tempfile.TemporaryDirectory() as d:
        clean = _git_repo(Path(d) / "clean", 'API = os.environ["TOKEN"]\n')
        dirty = _git_repo(Path(d) / "dirty", 'AWS = "AKIA' + "3H7XQ2ZKJ4WNPLMV" + '"\n')

        rc_clean, _ = _run(security_command, clean)
        rc_dirty, out_dirty = _run(security_command, dirty)

    assert rc_clean == 0
    assert rc_dirty == 1
    assert "app.py:1" in out_dirty            # names the file and line, not just "failed"
    assert "rotate it first" in out_dirty     # …and what to do, which is not "fix the code"


def test_the_documented_example_key_every_AWS_page_prints_is_not_a_finding(security_command):
    """FOUND BY RUNNING THE GATE OVER ALL TEN REAL REPOSITORIES, which is also how the anchored
    PEM pattern was arrived at. The scan matched nothing anywhere — and then matched
    `AKIAIOSFODNN7EXAMPLE` the moment a fixture planted one. Advisory means a job shrugs, but
    `box prove` runs repo-wide gates on untouched main and demands rc==0, so one example key in a
    README would hold a client's pickup: a false positive that costs a deployment, not a warning.

    THE POSITIVE TWIN IS THE TEST ABOVE. "The dummy is ignored" cannot see a filter that has
    quietly started swallowing real keys too; the two only mean something together."""
    with tempfile.TemporaryDirectory() as d:
        repo = _git_repo(Path(d) / "docs", "use " + "AKIA" + "IOSFODNN7EXAMPLE" + " as your id\n")
        rc, out = _run(security_command, repo)

    assert rc == 0, out


def test_vendored_base64_blob_is_not_a_false_positive(security_command):
    """VENDORED BINARIES (e.g. OpenCV.js / WASM base64) CONTAIN RANDOM RUNS MATCHING
    (AKIA|ASIA)[0-9A-Z]{16} (#11).

    An unanchored pattern fired on minified base64 strings because 20-character uppercase/digit
    runs naturally appear in base64 streams. Requiring delimiters ensures committed keys in code
    or configs are caught while random base64 substrings are ignored."""
    import base64
    import random

    random.seed(7)
    blob = base64.b64encode(bytes(random.getrandbits(8) for _ in range(400))).decode()
    blob = blob[:120] + "ASIAJQAAVSUAAPGLAACJ" + blob[140:]

    with tempfile.TemporaryDirectory() as d:
        repo = _git_repo(Path(d) / "vendor", 'var Module={};var wasmBinary="' + blob + '";\n')
        rc, out = _run(security_command, repo)

    assert rc == 0, out



@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root reads a mode-000 file, so the case cannot be constructed")
def test_a_file_the_scan_could_not_READ_is_never_reported_as_a_CREDENTIAL(security_command):
    """THE SAME CONFLATION AS `None` vs `{}`, one layer down, in the direction nobody checks.

    The command's first version captured `git grep … 2>&1`. `git grep` writes its per-file troubles
    to STDERR and still exits 1 — "nothing matched in what I could read" — so a tracked file the
    box cannot stat produced `error: failed to stat 'x': Permission denied` inside `$raw`, the
    AWS-dummy filter did not drop it, and the gate printed that line followed by "a credential is
    committed in the lines above: rotate it first". A scan that could not read a file told a human
    to rotate a key that does not exist; on a box that honours the image gate the same exit 1 holds
    `box prove` on untouched main forever, on a repository with nothing wrong in it.

    THE POSITIVE TWIN IS `test_a_clean_repository_is_green_and_a_planted_credential_is_not`:
    "stderr is not a finding" cannot see a capture that has stopped finding anything at all."""
    with tempfile.TemporaryDirectory() as d:
        repo = _git_repo(Path(d) / "denied", 'API = os.environ["TOKEN"]\n')
        blocked = repo / "locked.txt"
        blocked.write_text("nothing secret in here\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        blocked.chmod(0o000)
        try:
            rc, out = _run(security_command, repo)
        finally:
            blocked.chmod(0o644)

    assert "Permission denied" in out, "the case was not constructed — git read the file fine"
    assert rc == 0, out
    assert "a credential is committed" not in out
    assert "rotate it" not in out


def test_a_scan_that_could_not_RUN_never_reports_a_clean_repository(security_command):
    """`git grep` exits 1 for "nothing matched" and >1 for "I could not look". Collapsing those —
    `|| true`, or `&& … || exit 0` — is how a broken scan reports a clean repository, and it is
    the most expensive defect class in this codebase wearing a scanner's clothes."""
    with tempfile.TemporaryDirectory() as d:
        rc, out = _run(security_command, Path(d))  # not a git repository at all

    assert rc != 0
    assert rc != 1  # and not the "nothing matched" code either
    assert "could not run" in out


def test_the_inherited_gate_is_ADVISORY_and_therefore_never_blocks():
    """A first scan of a fifteen-year-old repository reports the debt of its whole history and none
    of it is the first ticket's fault. Blocking on day one means the client turns the gate off, and
    a gate that gets turned off protects nothing."""
    from openfactory.orchestrator.machine import _all_passed

    gate = as_gate(Manifest().validation["security"])
    assert gate.advisory is True
    assert gate.timeout_minutes and gate.timeout_minutes <= 20  # not the test suite's wall

    failing = ValidationResult(name="security", command=gate.command, exit_code=1, passed=False,
                               advisory=True)
    assert _all_passed([ValidationResult(name="test", command="pytest", exit_code=0, passed=True),
                        failing]) is True


# ── it has to survive leaving this working tree ──────────────────────────────────────────────────

def test_the_package_DATA_declaration_selects_the_default_file():
    """A floor that exists only in a git checkout is a floor no distributed install has.

    THE FIRST VERSION OF THIS TEST ASSERTED THE WRONG THING and passed while the defect was live.
    It checked `git ls-files`, on the strength of the comment in `pyproject.toml` claiming
    `include-package-data` carries every git-tracked file into the wheel. It does not — there is no
    setuptools-scm here to ask git — and a wheel built from a pristine copy of the tree came out
    WITHOUT `openfactory/org_defaults/floor.yaml`: `org_defaults/**/*.md` does not match a `.yaml`. Every
    pip install would have logged OPENFACTORY_FLOOR_UNREADABLE and inherited nothing, with this suite
    green. Tracked-by-git is necessary and says nothing about shipping.

    So this reads the declaration that actually decides, and
    `tests/test_the_wheel_ships_what_the_platform_needs.py` proves the artefact — that one builds a
    wheel and looks inside it, which is the only place the answer was ever knowable."""
    import fnmatch
    import tomllib

    assert ORG_FLOOR_FILE.is_relative_to(REPO / "openfactory")
    globs = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"]["setuptools"][
        "package-data"]["openfactory"]
    rel = ORG_FLOOR_FILE.relative_to(REPO / "openfactory")

    # `PurePath.full_match` IS PYTHON 3.13, AND THIS PROJECT'S FLOOR IS 3.12 (`requires-python`).
    # It passed on the author's 3.13 interpreter and raised `AttributeError` on CI's 3.12 for as
    # long as CI was running anything — a defect visible only where the floor is actually honoured.
    # `fnmatch` on the posix string is the portable equivalent: anchored at both ends, and `**`
    # degrades to `*`, which cannot hide a match that `Path.match` above would not already find.
    assert any(rel.match(g) or fnmatch.fnmatch(rel.as_posix(), g) for g in globs), (
        f"no entry in [tool.setuptools.package-data].openfactory selects {rel} — it will not be in the "
        f"wheel, and `org_default_validation()` will be None in every install: {globs}"
    )
    assert as_gate(org_default_validation()["security"]).command.strip()


def test_the_floor_ships_a_gate_for_every_role_it_can_honestly_default():
    """`REQUIRED_VALIDATION_ROLES` is the platform's list; this asserts the deployment ships a
    default for the one role a command can be written for, so that adding a third role to the floor
    is a decision somebody makes rather than a fleet-wide hold nobody predicted."""
    assert _floor_roles() <= set(floor.REQUIRED_VALIDATION_ROLES)
    assert "security" in _floor_roles()


# ── the control: it must stay GREEN under every mutation above ───────────────────────────────────

def test_control_the_preset_layer_is_untouched():
    """A mutation that introduces a SyntaxError reddens everything and looks exactly like proof.
    This asserts something none of the mutations above should reach; if it goes red, the run proves
    nothing about the guard that was being tested."""
    assert load_preset("python")["validate"]["lint"] == "ruff check ."
    assert load_preset("nothing-ships-this") == {}
