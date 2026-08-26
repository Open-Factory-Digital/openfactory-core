"""`sdlc doctor` said OK to a project whose quality floor was the empty set (#102).

MEASURED BEFORE THE FIX. `.sdlc/project.yaml` has 31 fields and **not one required**, so
`Manifest()` — the file containing `{}` — loads, `validate:` is `{}`, and `conformance.check`
returns no issues. `doctor`'s manifest check ran `p.manifest()`, discarded the result and said
".sdlc/project.yaml loads". That sentence is true and it is read as "the manifest is fine".

The two consequences are different and both are paid in money:

  1. `floor_reason` — the platform's own rule that a project must declare `test` and `security`
     validation — had exactly one reader on the job path, `orchestrator/machine.py:325`, which
     runs when a ticket has already been picked up. The client learns their floor is empty from a
     warning on a ticket they have already started paying for. Doctor holds the same manifest,
     before the first ticket, and never asked.
  2. `all([])` is True. A run with no gates reports every validation passed. `should_auto_merge`
     reads that property (`orchestrator/merge_policy.py`), so an empty manifest is not merely
     unverified — it is eligible to merge itself, having proven nothing.

WHY THE FIX IS NOT `required=True` ON THE MODEL. It was tried on the neighbouring contract and
reverted; `contracts/project.py` carries the note. `Project.tracker` has a `default_factory` that
several hundred tests inherit, and that many mechanical edits is that many chances to quietly
change what a test asserts. The protection belongs at the seams, where this platform already put
it: refuse at the seam that spends money, and SAY it at the seam a human runs first.

WHY THE FIX WAS NOT `OPENFACTORY_ENFORCE_FLOOR=1` EITHER, WHEN THIS WAS WRITTEN. No project in the fleet
declared a `security` gate, the live client included; flipping the switch stranded every one of
them, and a floor that arrives as an outage is a floor an operator switches off. That is history
now: `org_defaults/floor.yaml` gives every project the gate, the variable is gone, and the runner
REFUSES unconditionally. What doctor still adds is earliness — it says so before a ticket exists,
where the runner can only say it once the manifest is in hand and the client has already queued
work.

WHY AN UNMET FLOOR IS A **FAIL** HERE, AND WHY THAT USED TO DIFFER FROM THE RUNNER. `diagnose` has exactly one
production caller — `openfactory/cli.py:529`, a human typing `sdlc doctor <name>`. It spends nothing,
blocks nothing and holds nothing; its whole job is to say what is not right yet. `report.ok` means
*this project is ready*, not *this project will start*. And the CLI prints a remedy only for a
failing line, so a floor violation dressed as a pass would be less visible after this change than
before it — the state would be reported and the fix would not.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from openfactory import namespace
from openfactory.contracts import Manifest
from openfactory.contracts.project import Project, ProviderRef
from openfactory.doctor import Finding, Probes, diagnose
from openfactory.loader import load_manifest


def _findings(report) -> dict[str, Finding]:
    return {f.check: f for f in report.findings}


def _full() -> Manifest:
    """A manifest that satisfies the floor — the shape `sdlc project init` writes."""
    return Manifest(version=1, base_branch="main",
                    validate={"test": "pytest -q",
                              "security": {"command": "semgrep --config=auto .",
                                           "advisory": True}})


@pytest.fixture
def no_deployment_floor(monkeypatch):
    """A manifest that means exactly what its own file says — see the twin fixture in
    `test_the_floor_is_enforced_where_the_money_is.py` for the argument. These five tests are
    about DOCTOR carrying the floor's sentence through unedited; the deployment default now
    satisfies `security` for every project, so without this they would assert nothing."""
    monkeypatch.setattr("openfactory.policy.presets.org_default_validation", lambda: {})


def _probes(**over) -> Probes:
    base = dict(
        docker_running=lambda: (True, ""),
        harness_on_path=lambda kind: True,
        manifest=_full,
        forge_reachable=lambda: (True, ""),
        board_columns=lambda: ["Backlog", "TO-DO", "Done"],
        pickup_column=lambda: "TO-DO",
        requires_review=lambda: False,
        floor_enforced=lambda: False,
        harness_kind=lambda: "claude_code",
        product_link=lambda: type("_L", (), {"kind": "off", "active": False})(),
    )
    base.update(over)
    return Probes(**base)


# ── the empty manifest is no longer a pass ──────────────────────────────────────────────────────

def test_an_empty_manifest_used_to_pass_and_now_does_not():
    """THE card, as one line. `Manifest()` is `.sdlc/project.yaml` containing `{}`."""
    report = diagnose(_probes(manifest=Manifest))

    assert not report.ok
    assert not _findings(report)["manifest"].ok


def test_the_empty_manifest_finding_says_the_file_was_read_and_was_blank():
    """Not "invalid", not "missing" — read, and nothing in it. Those are three different remedies
    and the client can only act on the right one."""
    f = _findings(diagnose(_probes(manifest=Manifest)))["manifest"]

    assert "parses" in f.message and "declares nothing" in f.message
    assert "no gates" in f.message  # the consequence, not just the observation
    assert "project init" in f.remedy


def test_a_manifest_that_declares_something_is_not_called_empty():
    """The positive twin. A check that fails everything is as useless as one that passes
    everything, and this one gates the first command a new client runs."""
    f = _findings(diagnose(_probes()))["manifest"]

    assert f.ok
    assert "validate" in f.message, "it must name what it found, or nobody can spot the gap"


def test_the_pass_line_no_longer_says_only_that_the_file_LOADS():
    """The exact sentence that shipped the defect. "loads" is true of `{}` and reads as "is fine";
    the ratio is what makes an under-declared manifest visible at a glance."""
    message = _findings(diagnose(_probes()))["manifest"].message

    assert message != f"{namespace.MANIFEST} loads"
    # Counted from the schema, not typed as 31: a new OPTIONAL field is a version-1-compatible
    # change (see SUPPORTED_MANIFEST_VERSIONS' rule), and it must not turn this red.
    assert f"of {len(Manifest.model_fields)} settings" in message, message


def test_a_misspelled_key_was_never_this_defect():
    """Worth pinning, because the card describes it as one. `extra="forbid"` turns an unknown key
    into a load error, so a typo arrives as the ValueError branch and was always reported. The hole
    was the file with no keys at all — nothing to misspell."""
    with pytest.raises(Exception) as exc:
        Manifest(**{"validat": {"test": "pytest"}})
    assert "extra" in str(exc.value).lower() or "not permitted" in str(exc.value).lower()


# ── doctor asks the floor ───────────────────────────────────────────────────────────────────────

def test_doctor_asks_the_floor_at_all(no_deployment_floor):
    """The reachability guard, stated as behaviour: a manifest the runner would warn about must
    produce a finding here, on the check that names it."""
    only_test = Manifest(version=1, base_branch="main", validate={"test": "pytest -q"})
    f = _findings(diagnose(_probes(manifest=lambda: only_test)))["quality_floor"]

    assert not f.ok
    assert "security" in f.message


def test_the_floor_finding_carries_the_floors_OWN_words(no_deployment_floor):
    """`floor_reason` already writes the sentence that names the preset which satisfies it for
    free. Doctor must carry it through rather than paraphrase — a second copy of a rule is a second
    answer waiting to drift from the one the runner prints."""
    from openfactory.policy.conformance import floor_reason

    only_test = Manifest(version=1, base_branch="main", validate={"test": "pytest -q"})
    f = _findings(diagnose(_probes(manifest=lambda: only_test)))["quality_floor"]

    assert f.message == floor_reason(only_test)
    assert "security-oss" in f.message  # the preset that satisfies it at no cost


def test_a_satisfied_floor_says_so_out_loud():
    """A tool that only ever reports problems cannot be trusted when it reports none — the
    module's own bar."""
    f = _findings(diagnose(_probes()))["quality_floor"]

    assert f.ok
    assert "test" in f.message and "security" in f.message


def test_the_satisfied_line_names_the_FLOORS_roles_rather_than_a_copy_of_them(monkeypatch):
    """The same drift argument `floor_is_enforced` makes about the env var, applied to the roles.

    Asserting that the healthy line contains "test" and "security" cannot see a hardcoded pair —
    it is byte-identical to the derived one today. So the floor is given a third role and the
    message has to grow it. Otherwise the day `REQUIRED_VALIDATION_ROLES` gains one, doctor keeps
    telling clients their manifest "declares every validation the platform's floor requires" while
    naming the old list, which is a false statement in the tool that exists to prevent them."""
    from openfactory.policy import floor as floor_module

    monkeypatch.setattr(floor_module, "REQUIRED_VALIDATION_ROLES",
                        frozenset({"test", "security", "licence"}))
    m = Manifest(version=1, validate={"test": "pytest -q", "security": "semgrep",
                                      "licence": "reuse lint"})
    f = _findings(diagnose(_probes(manifest=lambda: m)))["quality_floor"]

    assert f.ok, f.message
    for role in ("test", "security", "licence"):
        assert f"`{role}`" in f.message, f.message


def test_a_PRESET_satisfies_it_here_too():
    """The floor is about what will RUN, not what is typed in one file. Doctor must not be stricter
    than the rule it reports, or it sends people to add a gate they already have."""
    m = Manifest(version=1, base_branch="main", validate={"test": "p"},
                 components={"api": {"path": "api/", "stack": "security-oss"}})

    assert _findings(diagnose(_probes(manifest=lambda: m)))["quality_floor"].ok


# ── the remedy states what will ACTUALLY happen on this deployment ──────────────────────────────

def test_a_deployment_that_does_NOT_refuse_says_jobs_still_run(no_deployment_floor):
    """Claiming "the floor refuses this" where nothing refuses anything would be a failure wearing
    an answer's clothes, in the tool written to prevent that.

    NO DEPLOYMENT ANSWERS `False` TODAY — `floor_is_enforced` is a constant since
    `OPENFACTORY_ENFORCE_FLOOR` was removed. The arm is kept, and so is this test, because the probe is
    what a test replaces: a doctor that hardcoded the verdict could never be SHOWN reporting the
    other state, and then the day somebody makes it configurable again nothing would notice the
    sentence had gone wrong."""
    only_test = Manifest(version=1, base_branch="main", validate={"test": "pytest -q"})
    f = _findings(diagnose(_probes(manifest=lambda: only_test,
                                   floor_enforced=lambda: False)))["quality_floor"]

    assert "jobs RUN with that gate missing" in f.remedy
    assert "held" not in f.remedy.lower()


def test_the_remedy_resolves_the_tense_of_the_floors_own_sentence(no_deployment_floor):
    """CAUGHT BY RUNNING THE COMMAND, not by reading the code. `floor_reason` is written from the
    refusal site and opens its second clause with "Nothing was run" — correct where the runner
    prints it, and stacked directly above "jobs still RUN" it is a flat contradiction on the two
    adjacent lines a client actually reads. The remedy has to open by saying which of the two is
    happening on THIS deployment."""
    only_test = Manifest(version=1, base_branch="main", validate={"test": "pytest -q"})
    off = _findings(diagnose(_probes(manifest=lambda: only_test,
                                     floor_enforced=lambda: False)))["quality_floor"]
    on = _findings(diagnose(_probes(manifest=lambda: only_test,
                                    floor_enforced=lambda: True)))["quality_floor"]

    assert "Nothing was run" in off.message  # the floor's own words, carried through unedited
    assert off.remedy.startswith("and on this deployment that is not being refused")
    assert on.remedy.startswith("and this is not advice")


def test_a_deployment_that_DOES_refuse_says_every_ticket_will_be_HELD(no_deployment_floor):
    """The same violation, the opposite operational meaning. One finding cannot carry both."""
    only_test = Manifest(version=1, base_branch="main", validate={"test": "pytest -q"})
    f = _findings(diagnose(_probes(manifest=lambda: only_test,
                                   floor_enforced=lambda: True)))["quality_floor"]

    assert "held" in f.remedy.lower()
    assert "jobs RUN" not in f.remedy


def test_what_doctor_REPORTS_is_what_the_runner_DOES(monkeypatch):
    """The drift guard, rewritten around a constant instead of a variable.

    It used to assert that doctor and the runner parsed `OPENFACTORY_ENFORCE_FLOOR` to the same answer —
    a real risk, because the disagreement would have been invisible: doctor reporting a blocking
    deployment while the runner waved jobs through. The variable is gone, so the guard is now that
    doctor reports what the runner unconditionally does, and that no environment can move either.
    """
    import ast
    import inspect

    from openfactory.doctor import floor_is_enforced
    from openfactory.orchestrator import machine

    for value in ("1", "true", "YES", "0", "", "maybe"):
        monkeypatch.setenv("OPENFACTORY_ENFORCE_FLOOR", value)
        assert floor_is_enforced() is True, value
    monkeypatch.delenv("OPENFACTORY_ENFORCE_FLOOR", raising=False)
    assert floor_is_enforced() is True

    # And the runner really is unconditional: the floor refusal is not inside an `if` that reads
    # anything. Source, not behaviour, because the behaviour half needs a whole job to observe.
    run = next(n for n in ast.walk(ast.parse(inspect.getsource(machine)))
               if isinstance(n, ast.FunctionDef) and n.name == "run")
    body = ast.unparse(run)
    assert "floor_reason" in body, "the runner no longer asks the floor at all"
    assert "OPENFACTORY_ENFORCE_FLOOR" not in body


def test_the_live_probe_set_wires_the_switch(tmp_path, monkeypatch):
    """The other half of reachability: `probes_for` must actually supply the fact, not merely be
    able to carry it. A `Probes` built by hand in a test proves nothing about the one production
    builds."""
    from openfactory.doctor import probes_for

    monkeypatch.setenv("OPENFACTORY_ENFORCE_FLOOR", "1")
    assert probes_for(Project(name="fixture", repo_path=str(tmp_path))).floor_enforced() is True


# ── an unreadable manifest is not a satisfied floor ─────────────────────────────────────────────

def test_a_manifest_that_cannot_be_read_leaves_the_floor_UNKNOWN_not_met():
    """The house rule, on this seam. "I could not tell" must never reach the caller looking like
    "it worked" — and a missing file is exactly when somebody is running doctor."""
    def _missing():
        raise FileNotFoundError(
            "no manifest at /repo/.openfactory/project.yaml. `openfactory env apply demo "
            "--yes --pr` proposes it as a pull request on the repository")

    f = _findings(diagnose(_probes(manifest=_missing)))["quality_floor"]

    assert not f.ok
    assert "has not loaded" in f.message
    assert "manifest finding" in f.remedy  # points at the one cause, does not invent a second
    # AND IT DOES NOT REPEAT THE LOADER'S INSTRUCTIONS. Those name the commands that WRITE a
    # manifest, which contradicts the manifest finding outright whenever one is already
    # proposed and merely waiting to be merged (pilot, 2026-08-14).
    assert "proposes it as a pull request" not in f.message, (
        "this check re-teaches how to propose a manifest, one line below the finding that may "
        "be saying a proposal is already open")


def test_an_INVALID_manifest_leaves_the_floor_unknown_TOO():
    """The second way a manifest fails to arrive, and `_floor` catches the broad `Exception` for
    exactly this reason. Narrow it to `FileNotFoundError` — the plausible tidy-up — and a version-42
    or typo'd manifest escapes into `_guarded`, which answers "could not check quality_floor" with
    "re-run with the underlying tool by hand": the generic fallback, on a cause the report has
    already named one line above. The finding stays a FAIL either way, so only the REMEDY tells the
    two apart, which is why this asserts on the remedy and not on `ok`."""
    def _invalid():
        raise ValueError("/repo/.openfactory/project.yaml is invalid: manifest version 42 …")

    f = _findings(diagnose(_probes(manifest=_invalid)))["quality_floor"]

    assert not f.ok
    assert "could not be read" in f.message
    assert "manifest finding" in f.remedy
    assert "underlying tool" not in f.remedy, "this is `_guarded`'s fallback, not _floor's remedy"


def test_a_manifest_object_that_cannot_SAY_is_not_reported_as_an_empty_one():
    """The None/[] rule on the branch this change added, from the side that is not obvious.

    `_declared` returns None for *cannot say* and `()` for *read it, nothing there*, and its
    docstring rests the whole design on the difference — unasserted until here. Collapse the two
    (`else ()` instead of `else None`) and a manifest object this build cannot interrogate is
    reported as ".sdlc/project.yaml parses and declares nothing", a FAIL and a non-zero exit on a
    project whose file may be perfectly complete. Absence reading as compliance is the usual
    direction of this defect; this is the expensive opposite one."""
    class _Foreign:  # an older contract, another build's model, a caller's own stand-in
        merge_policy = "human"
        validation = {"test": "pytest -q", "security": "semgrep"}
        components: dict = {}

    f = _findings(diagnose(_probes(manifest=_Foreign)))["manifest"]

    assert f.ok, f.message
    assert "declares nothing" not in f.message
    assert "cannot say" in f.message, "the pass must not read as 'the manifest is filled in'"


def test_it_does_not_repeat_the_manifests_own_remedy():
    """Two findings for one cause are acceptable only if the second adds something. The floor's
    line must not send the reader to fix the manifest twice, in two different ways.

    PINNED AS THE PROPERTY, NOT AS A COMMAND NAME. This asserted the literal `project init`,
    which stopped being the right verb the day the remedy learned to match how the project is
    REGISTERED — `project init` writes nothing for a clone-URL project, which is the shape the
    compose worker uses and the one the pilot hit (2026-08-13). What must hold is that the
    manifest finding carries the way forward and the floor finding defers to it."""
    def _missing():
        raise FileNotFoundError("no manifest at /repo/.openfactory/project.yaml — `openfactory "
                                "env apply <your-checkout> --yes` writes it")

    report = _findings(diagnose(_probes(manifest=_missing)))

    manifest_remedy = report["manifest"].remedy
    floor_remedy = report["quality_floor"].remedy
    assert "env apply" in report["manifest"].message or "env apply" in manifest_remedy, (
        "the manifest finding does not carry a way forward")
    assert "ONBOARDING" in manifest_remedy, "the step that writes it is not named"
    for verb in ("project init", "env apply", "env read"):
        assert verb not in floor_remedy, (
            f"the floor repeats the manifest's own remedy ({verb}) — one cause, one instruction")
    assert "fix the manifest finding" in floor_remedy


# ── end to end, through the real loader ─────────────────────────────────────────────────────────

def _project_with(text: str) -> Project:
    root = pathlib.Path(tempfile.mkdtemp())
    (root / namespace.DIR).mkdir()
    (root / namespace.MANIFEST).write_text(text)
    return Project(name="novo", repo_path=str(root),
                   tracker=ProviderRef(kind="github", repo="o/r"))


def test_an_empty_FILE_reaches_the_finding_through_the_real_loader():
    """Hand-built `Manifest()` objects could pass while the real path did not — `load_manifest`
    is what doctor's live probe calls, and `yaml.safe_load("") or {}` is the shape a client
    actually produces by creating the file and stopping."""
    manifest = load_manifest(_project_with("# nothing yet\n"))

    assert manifest.declared_keys() == ()
    assert not _findings(diagnose(_probes(manifest=lambda: manifest)))["manifest"].ok


def test_the_STARTER_the_platform_writes_passes_both_new_checks():
    """First contact. `sdlc project init` prints "then: `sdlc doctor <name>`", so the template we
    write must survive the command we tell them to run next — the same failure that was fixed for
    `sdlc conformance` and would otherwise have been reintroduced here."""
    from openfactory.cli import _MANIFEST_TEMPLATE

    manifest = load_manifest(_project_with(_MANIFEST_TEMPLATE))
    report = _findings(diagnose(_probes(manifest=lambda: manifest)))

    assert report["manifest"].ok, report["manifest"].message
    assert report["quality_floor"].ok, report["quality_floor"].message


def test_declared_keys_speaks_the_FILES_vocabulary_not_the_models():
    """The client goes looking in their own file. The field is `validation`; the key they wrote —
    and the only string they can search for — is `validate`."""
    manifest = load_manifest(_project_with("version: 1\nvalidate:\n  test: pytest -q\n"))

    assert manifest.declared_keys() == ("validate", "version")


def test_the_contract_still_exposes_the_question_doctor_asks():
    """The negative guard's positive twin. `doctor._declared` returns None — "cannot say" — when
    the attribute is absent, which is right for a foreign object and would silently restore the
    old vacuous ".sdlc/project.yaml loads" if this method were ever renamed."""
    assert callable(getattr(Manifest, "declared_keys", None))


def test_no_field_became_required():
    """The constraint this fix was given, asserted rather than remembered. If a later change makes
    a field mandatory, three hundred manifests in tests and in clients' repositories stop loading
    — and this line is where that decision has to be made deliberately."""
    required = [n for n, f in Manifest.model_fields.items() if f.is_required()]

    assert required == [], required
    assert Manifest() is not None  # still constructible with nothing at all
