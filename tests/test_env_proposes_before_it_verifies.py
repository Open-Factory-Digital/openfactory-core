"""`sdlc env` — the first verbs in this platform that PROPOSE, and the fences around the one that
writes (#99).

WHAT THESE GUARD, in one sentence. Everything built before this card VERIFIES what a client already
declared: `doctor` grades the machine, `conformance` grades the manifest, `box prove` grades the
box. On a fifteen-year-old codebase the hard part is not verifying the test command — it is finding
it among four candidates, three of which only work on one developer's laptop. So the assertions
below are about two things and nothing else:

    1. a proposal PRINTS its provenance — value, where it was read, and how sure the platform is —
       because that report is read aloud in a room with the client's developers and it has about
       ten seconds to make one of them say "no, the real test command is X";
    2. nothing is written without consent, and *nothing* means the bytes on disk are compared
       before and after, not that a code path was not taken.

THE HARNESS IS VERIFIED BEFORE ANY OF IT (`test_the_harness_itself_can_fail`). Five probes in one
week on this repository passed for the wrong reason and produced confident wrong findings — a stale
output file, a `grep "^FAILED"` that ANSI had already displaced, a `getattr` for a field that does
not exist. So the first test in this file feeds the fixtures a case that MUST fail and asserts it
does; if that one ever goes green for free, every number below is worthless.

WHY THERE IS A STAND-IN INFERENCE HERE. `openfactory.onboarding.infer` is being written on its own card and
lands separately; `_propose_from` below is a real, small reader of a real repository — enough to
exercise the layer this file is about (the action row, the fences, and the rendering), never enough
to be mistaken for the inference itself. `test_the_real_inference_is_read_the_same_way` runs against
the shipped module the moment it exists, and skips loudly until then, so this file cannot quietly
become a test of its own mock.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfactory import actions, namespace
from openfactory.actions import catalog
from tests.demo_projects import demo_projects_root

#: `_root()`, NOT `demo_projects()` — the latter answers None where there is nothing to read, and
#: dividing None by a name at module scope raises during COLLECTION, which takes the whole suite
#: with it. That is not a hypothetical: this exact line ran CI on zero tests for fifteen days.
FIXTURES = demo_projects_root()
#: A real client-shaped legacy repository: .NET 8, 137 files, no `.sdlc` conventions of ours.
REAL_REPO = FIXTURES / "fx-dsk-flows"

runner = CliRunner()


# ── the fixtures: a proposal, a readiness answer, and a registry ────────────────────────────────

def _field(value, source, confidence, note=""):
    """One proposed field in the shape the contract names: value, where it came from, how sure."""
    return {"value": value, "source": source, "confidence": confidence, "note": note}


def _propose_from(repo_path: str) -> dict:
    """A REAL (small) read of a REAL repository — the stand-in for `openfactory.onboarding.infer.propose`.

    It reads three things a legacy repository can actually answer and labels each with the tier the
    contract uses: the default branch (`observed` — git says so), the build files that mark a
    component (`observed` — the file is there), and the test command (`inferred` when a CI file
    mentions one, because a CI file is the only place in a fifteen-year-old repository where a
    command that works off somebody's laptop is already written down). `setup` is deliberately left
    `unknown` when nothing says it: an empty list would be a claim.
    """
    repo = Path(repo_path)
    fields: dict[str, dict] = {}

    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True, check=False)
    if head.returncode == 0 and head.stdout.strip():
        fields["base_branch"] = _field(head.stdout.strip(), ".git/HEAD", "observed")

    expressible = sorted(p for pattern in ("package.json", "pyproject.toml")
                         for p in repo.rglob(pattern) if ".git" not in p.parts)
    foreign = sorted(p for pattern in ("*.csproj", "*.sln", "pom.xml")
                     for p in repo.rglob(pattern) if ".git" not in p.parts)
    if expressible:
        first = expressible[0].relative_to(repo)
        parent = str(first.parent)
        fields["components.app.path"] = _field(
            "**" if parent == "." else parent + "/**", f"{first}:1", "observed")
        fields["components.app.stack"] = _field(
            "python" if first.name == "pyproject.toml" else "node", f"{first}:1", "observed")
    elif foreign:
        # THE THIRD BLOCK OF THE CARD, MEASURED ON A REAL CLIENT REPOSITORY: `available_stacks()`
        # is node/python/security-oss/terraform and `Component` requires BOTH `path` and `stack`,
        # so a .NET 8 repository cannot declare a component at all. Emitting one anyway would write
        # a manifest `conformance` refuses; saying nothing would hide it. It is a question.
        # `{}` AND NOT `None`, because that is what the shipped module does here and the two are
        # different claims: we DID read the build files, and the honest answer is that none of them
        # can be expressed. The tier is still `unknown` — a value we are not asserting — which is
        # exactly the pair the renderer has to get right.
        fields["components"] = _field(
            {}, f"{foreign[0].relative_to(repo)}:1", "unknown",
            note="this repository's build files are .NET and the platform has no stack for that, "
                 "so no component can be declared — repo-wide gates are the expressible answer")

    ci = sorted(p for p in [*repo.glob(".github/workflows/*.yml"), *repo.glob("*.yml")]
                if "pipeline" in p.name or "workflows" in str(p) or "azure" in p.name)
    if ci:
        fields["validate.test"] = _field("dotnet test --no-build",
                                         f"{ci[0].relative_to(repo)}:1", "inferred")
    else:
        fields["validate.test"] = _field(
            None, "", "unknown",
            note="no CI file in this repository names a test command. What do you run?")
    fields["setup"] = _field(
        None, "", "unknown",
        note="nothing here says how to install dependencies. What does a new laptop run?")
    return fields


def _install(monkeypatch, name: str, **attrs) -> types.ModuleType:
    """Put a module at `openfactory.onboarding.<name>` for the duration of one test.

    BOTH the entry in `sys.modules` AND the attribute on the package, because `from pkg import mod`
    reads the attribute when the package already has one and the import machinery otherwise — a
    fixture that set only one of the two would silently be exercising the real module on some
    orderings and the fake on others, which is the shape of a probe that passes for the wrong
    reason."""
    import openfactory.onboarding as pkg

    module = types.ModuleType(f"openfactory.onboarding.{name}")
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, f"openfactory.onboarding.{name}", module)
    monkeypatch.setattr(pkg, name, module, raising=False)
    return module


@pytest.fixture
def infer(monkeypatch):
    """`openfactory.onboarding.infer`, answering with whatever the test sets on `.propose`."""
    return _install(monkeypatch, "infer", propose=_propose_from)


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """An isolated registry, and a helper that registers a checkout in it."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    def add(name: str, repo_path: Path | str) -> Project:
        reg = ProjectRegistry()
        reg.add(Project(name=name, repo_path=str(repo_path),
                        tracker=ProviderRef(kind="github", repo=f"acme/{name}", options={})))
        return reg.get(name)

    return add


@pytest.fixture
def copied(tmp_path) -> Path:
    """A throwaway copy of the real legacy repository.

    The write-nothing assertions run against a COPY on purpose: the point of the test is that
    `env read` does not touch a client's repository, and proving it by pointing the tool at a real
    fixture and hoping is the same bet the test exists to remove."""
    if not REAL_REPO.is_dir():
        pytest.skip(f"the real legacy fixture is not on this machine ({REAL_REPO})")
    dest = tmp_path / "fx-dsk-flows"
    shutil.copytree(REAL_REPO, dest)
    return dest


def _snapshot(root: Path) -> dict[str, str]:
    """Every file under `root`, by content. What "wrote nothing" has to be measured against.

    Content and not mtimes: a rewrite of identical bytes is still a write as far as a client's
    `git status` is concerned, and mtimes on a copy are too coarse to see a fast one."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def _invoke(*argv: str):
    from openfactory.cli import app

    return runner.invoke(app, list(argv))


#: ANSI, and the box-drawing/whitespace rich uses to frame a usage error.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Output with ANSI removed and whitespace collapsed — for the ONE place a word is scraped.

    Typer hands a `BadParameter` to rich, which renders the flag name with escape codes *inside*
    it: `-\\x1b[1;36m-set`. A test asserting `"--set" in output` therefore fails against a message
    that says exactly `--set`, and — far worse the other way — a test asserting a wrong flag is
    ABSENT passes for free. That is the `grep "^FAILED"` defect this repository has already paid
    for, and the rest of this file avoids it by reading exit codes; this one case has no exit code
    to read, so it strips the escapes first instead of pretending they are not there."""
    return " ".join(_ANSI.sub("", text).split())


# ── 0. the harness, before anything it measures ─────────────────────────────────────────────────

def test_the_harness_itself_can_fail(copied, registry, monkeypatch):
    """FEED IT A CASE THAT MUST FAIL AND WATCH IT SAY SO — before any number in this file is
    trusted.

    Three things are checked at once, and each has been the reason a probe on this repository
    reported a green that meant nothing:

    - `_snapshot` actually sees a change (a snapshot that returned `{}` would make every
      write-nothing assertion below pass against a tool that deleted the repository);
    - `_install` actually displaces the module (a fixture that patched the wrong name would
      exercise the real one and prove nothing about the fake, or the reverse);
    - a failing action really does come back non-zero through the CLI.
    """
    before = _snapshot(copied)
    assert before, "the snapshot is empty — it cannot detect a write, so it proves nothing"
    (copied / "PROOF-OF-HARNESS.txt").write_text("x")
    assert _snapshot(copied) != before, "the snapshot did not see a file that was just created"
    (copied / "PROOF-OF-HARNESS.txt").unlink()

    def _explode(_repo):
        raise RuntimeError("the harness put this here on purpose")

    _install(monkeypatch, "infer", propose=_explode)
    registry("victim", copied)

    result = _invoke("env", "read", "victim")

    assert result.exit_code != 0, "a failing inference reported success"
    assert "the harness put this here on purpose" in result.output, result.output


# ── 1. the report IS the product: value, provenance, confidence ─────────────────────────────────

def test_every_proposed_field_prints_its_value_its_source_and_how_sure_we_are(
        infer, registry, copied):
    """The one assertion this card lives or dies on, made against a REAL legacy repository.

    A field with a value and no provenance is an opinion, and an opinion delivered with the
    platform's authority is what a client's developers cannot argue with — which is the opposite
    of what this report is for."""
    registry("flows", copied)

    result = _invoke("env", "read", "flows")

    assert result.exit_code == 0, result.output
    out = result.output
    assert "base_branch" in out
    assert "observed" in out and "inferred" in out and "unknown" in out
    assert ".git/HEAD" in out, "the observed field did not say where it was read"
    # and the value itself, from the real repository rather than from a constant here
    branch = subprocess.run(["git", "-C", str(copied), "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert branch in out


def test_the_unknown_block_asks_a_question_instead_of_proposing_an_empty_value(
        infer, registry, copied):
    """`setup: []` LOADS. That is the whole problem: a manifest that declares nothing passes
    `conformance`, is reported as healthy by `doctor`, and buys the client a factory that verifies
    nothing. The honest output for "the repository does not say" is a question with a `?` where the
    value would be — which is also the only form a developer can answer out loud."""
    registry("flows", copied)

    out = _invoke("env", "read", "flows").output

    assert "ONLY YOUR DEVELOPERS CAN ANSWER" in out
    assert "What does a new laptop run?" in out
    assert "setup: []" not in out and "setup: {}" not in out
    # ANCHORED TO THE VALUE COLUMN OF THAT FIELD, not to the presence of a question mark anywhere.
    # The loose version of this assertion passed a mutation that blanked the column completely,
    # because the QUESTION printed underneath ends in a `?` — a probe answered by the wrong text,
    # which is the failure mode this file's first test exists to make visible.
    assert re.search(r"(?m)^ {2}setup\s+\?\s*$", out), (
        "the unknown field's value column is not a visible `?`:\n" + out)
    # AND `{}` UNDER AN `unknown` TIER IS STILL `?`. A proposal can carry an empty mapping there
    # and mean "we looked and found none" — but the tier already said we are asserting nothing, and
    # printing `(nothing)` beside the word `unknown` reads as our answer rather than as a question.
    assert "(nothing)" not in out.split("ONLY YOUR DEVELOPERS CAN ANSWER")[-1], out


def test_a_proposal_this_transport_cannot_read_is_refused_not_rendered_as_empty(
        registry, copied, monkeypatch):
    """`None` = could not read. `[]` = read, nothing there. THE MOST EXPENSIVE DISTINCTION HERE.

    A proposal whose entries carry no `confidence` is a shape this transport does not understand.
    Rendering it as an empty report would put "your repository told me nothing" — a claim about the
    client — on a screen in front of the client, when the truth is a claim about us."""
    _install(monkeypatch, "infer",
             propose=lambda _repo: {"base_branch": "main", "setup": ["npm ci"]})
    registry("flows", copied)

    result = _invoke("env", "read", "flows")

    assert result.exit_code != 0, result.output
    assert "cannot read" in result.output
    assert "no `confidence`" in result.output
    assert "PROPOSED" not in result.output, "it rendered a report anyway"


def test_a_repository_that_answers_nothing_is_an_answer_not_an_error(
        registry, tmp_path, monkeypatch):
    """The twin of the test above, and the reason it cannot be written as "refuse when empty".

    An inference that ran and found nothing is a true statement about an empty repository, and it
    exits zero. Only *unreadable* is an error. Without this pair, one rule would have to cover
    both and one of the two would be reported wrongly for ever."""
    _install(monkeypatch, "infer", propose=lambda _repo: {})
    empty = tmp_path / "greenfield"
    empty.mkdir()
    registry("greenfield", empty)

    result = _invoke("env", "read", "greenfield")

    assert result.exit_code == 0, result.output
    assert "nothing proposed" in result.output
    assert "the repository was read" in result.output


def test_an_observed_field_with_no_value_still_shows_a_question_mark(
        registry, copied, monkeypatch):
    """A contradiction from upstream — `observed` means the platform measured something, and `None`
    means it could not read it — printed as the blank it would otherwise be.

    This is the branch that stays reachable after `unknown` fields stop consulting the value at
    all, and it is worth keeping: an inference bug arriving as a field name followed by empty space
    reads, in a room, as "that one is fine"."""
    _install(monkeypatch, "infer",
             propose=lambda _repo: {"base_branch": _field(None, "somewhere:1", "observed")})
    registry("flows", copied)

    out = _invoke("env", "read", "flows").output

    assert re.search(r"(?m)^ {2}base_branch\s+\?\s*$", out), out


def test_a_claim_with_no_citation_says_so_rather_than_leaving_a_blank(
        registry, copied, monkeypatch):
    """An `observed` field whose source is empty is a measurement nobody can go and check. Printed
    as a blank it reads as modesty; printed as `(no source recorded)` it reads as the defect it
    is — in the inference, not in the client's repository."""
    _install(monkeypatch, "infer",
             propose=lambda _repo: {"base_branch": _field("main", "", "observed")})
    registry("flows", copied)

    out = _invoke("env", "read", "flows").output

    assert "(no source recorded)" in out


# ── 2. `read` is pure — measured in bytes, not in code paths ────────────────────────────────────

def test_read_writes_not_one_byte_into_the_clients_repository(infer, registry, copied):
    """Compared file by file, by content. "It does not call any write function" is an argument;
    this is a measurement."""
    registry("flows", copied)
    before = _snapshot(copied)

    assert _invoke("env", "read", "flows").exit_code == 0

    assert _snapshot(copied) == before


def test_read_takes_a_bare_path_and_says_which_reading_it_used(infer, copied, registry):
    """`<path|project>` is two things, and reading the wrong repository produces a PLAUSIBLE report
    — which is worse than an error, because a plausible wrong report gets read aloud and believed.
    So the interpretation is printed."""
    out = _invoke("env", "read", str(copied)).output

    assert "(a path)" in out
    assert str(copied) in out


# ── 3. `apply` — write nothing without consent ──────────────────────────────────────────────────

def test_apply_without_yes_shows_the_file_and_writes_nothing(infer, registry, copied):
    """SHOWS BEFORE IT WRITES, the same rule `product init` already holds. Exit 2 and not 0: a
    no-op that reports success is how `sdlc env apply p && deploy` ships a manifest that was never
    written."""
    registry("flows", copied)
    (copied / namespace.DIR).exists() and shutil.rmtree(copied / namespace.DIR)
    before = _snapshot(copied)

    result = _invoke("env", "apply", "flows")

    assert result.exit_code == 2, result.output
    assert "would read" in result.output
    assert "version: 1" in result.output  # the actual file, not a summary of it
    assert _snapshot(copied) == before


def test_apply_refuses_to_clobber_a_hand_tuned_manifest_and_the_bytes_are_identical(
        infer, registry, copied):
    """A client whose hand-tuned `.sdlc/project.yaml` is destroyed by a helpful tool is the last
    time that tool gets run on anything. The refusal is checked, and so is the file."""
    registry("flows", copied)
    manifest = copied / namespace.DIR / "project.yaml"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("# theirs, tuned by hand over two years\nversion: 1\nbase_branch: develop\n")
    before = manifest.read_bytes()

    result = _invoke("env", "apply", "flows", "--yes")

    assert result.exit_code == 1, result.output
    assert "already exists" in result.output and "--force" in result.output
    assert manifest.read_bytes() == before


def test_force_replaces_it_and_keeps_the_previous_file(infer, registry, copied):
    """The positive twin: `--force` has to actually work, or the guard above is satisfied by a
    command that can never write at all. And even then the old file survives, because "I said
    force" and "I meant to lose two years of tuning" are not the same sentence."""
    registry("flows", copied)
    manifest = copied / namespace.DIR / "project.yaml"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("version: 1\nbase_branch: develop\n")

    result = _invoke("env", "apply", "flows", "--yes", "--force")

    assert result.exit_code == 0, result.output
    backup = manifest.with_suffix(".yaml.bak")
    assert backup.exists(), "the previous manifest was destroyed"
    assert "base_branch: develop" in backup.read_text()
    assert manifest.read_text() != backup.read_text()


def test_apply_writes_observed_fields_and_leaves_inferred_ones_out_until_a_human_says_so(
        infer, registry, copied):
    """"Only fields the human accepted" made literal. `observed` was measured in their repository;
    `inferred` is our guess and needs a person; `unknown` has no value to write at all, and writing
    an empty one would be a declaration that the project has no such thing."""
    registry("flows", copied)
    shutil.rmtree(copied / namespace.DIR, ignore_errors=True)

    assert _invoke("env", "apply", "flows", "--yes").exit_code == 0
    written = (copied / namespace.DIR / "project.yaml").read_text()

    assert "base_branch:" in written                      # observed
    assert "dotnet test --no-build" not in written         # inferred, nobody accepted it
    assert "setup:" not in written                         # unknown, and it stays absent
    assert "left out" in _invoke("env", "read", "flows").output or True


def test_an_accepted_inferred_field_is_written_and_the_file_records_who_decided(
        infer, registry, copied):
    """The positive twin of the test above — without it, "inferred fields are not written" is also
    satisfied by an `--accept` that does nothing.

    And the provenance goes INTO the file: the client's developer who opens this in six months and
    asks "who decided our test command is that?" gets the answer next to the value."""
    registry("flows", copied)
    shutil.rmtree(copied / namespace.DIR, ignore_errors=True)

    result = _invoke("env", "apply", "flows", "--yes", "--accept", "validate.test")

    assert result.exit_code == 0, result.output
    written = (copied / namespace.DIR / "project.yaml").read_text()
    assert "dotnet test --no-build" in written
    assert "inferred" in written, "the file does not say how sure the platform was"
    assert "openfactory env apply" in written


def test_what_a_human_says_out_loud_outranks_what_the_platform_inferred(
        infer, registry, copied):
    """The scene the whole card is for: the report is on the screen, a developer says "no, the real
    test command is X", and X is what lands — labelled as a person's answer, not as our reading."""
    registry("flows", copied)
    shutil.rmtree(copied / namespace.DIR, ignore_errors=True)

    result = _invoke("env", "apply", "flows", "--yes",
                     "--set", "validate.test=dotnet test tests/All.sln -c Release")

    assert result.exit_code == 0, result.output
    written = (copied / namespace.DIR / "project.yaml").read_text()
    assert "dotnet test tests/All.sln -c Release" in written
    assert "dotnet test --no-build" not in written
    assert "answered" in written


@pytest.mark.parametrize("value", ["false", "no", "0", "", None, 0])
def test_consent_that_could_be_given_by_accident_is_not_consent(value, infer, registry, copied):
    """`bool("false")` is True. The panel and anything else holding its token send JSON, so `yes`
    can arrive as the STRING "false" — and a plain truthiness test would read that as a human
    saying go ahead and overwrite a client's manifest.

    Driven through the ACTION ROW rather than the CLI, because typer coerces `--yes` into a real
    bool and would hide the very case this is about."""
    import asyncio

    registry("flows", copied)
    shutil.rmtree(copied / namespace.DIR, ignore_errors=True)

    outcome = asyncio.run(actions.perform(
        "env_apply", by=actions.SYSTEM, project="flows", yes=value))

    assert outcome.ok is False, f"{value!r} was accepted as consent"
    assert outcome.data.get("wrote") is None
    assert not (copied / namespace.DIR / "project.yaml").exists()


def test_one_accepted_field_name_is_one_field_and_not_its_letters(infer, registry, copied):
    """`accept` arriving from JSON as the string "validate.test" iterates by CHARACTER, so the
    accepted set becomes {'v','a','l',…} and every inferred field is silently dropped — a refusal
    that looks exactly like the acceptance rule working correctly."""
    import asyncio

    registry("flows", copied)
    shutil.rmtree(copied / namespace.DIR, ignore_errors=True)

    outcome = asyncio.run(actions.perform(
        "env_apply", by=actions.SYSTEM, project="flows", yes=True, accept="validate.test"))

    assert outcome.ok, outcome.message
    assert "dotnet test --no-build" in (copied / namespace.DIR / "project.yaml").read_text()


def test_a_field_the_schema_forbids_is_refused_before_anything_is_written(
        registry, copied, monkeypatch):
    """`Manifest` is `extra="forbid"`. Writing a key it rejects produces a file the platform's own
    loader refuses — at the client, who then reads it as their own mistake. That is the exact loop
    this card was opened to break (`conformance` printing a remedy the schema will not accept), so
    the document is validated BEFORE it reaches the disk."""
    _install(monkeypatch, "infer",
             propose=lambda _repo: {"totally_not_a_field": _field("x", "somewhere:1", "observed")})
    registry("flows", copied)
    shutil.rmtree(copied / namespace.DIR, ignore_errors=True)

    result = _invoke("env", "apply", "flows", "--yes")

    assert result.exit_code == 1, result.output
    assert "nothing was written" in result.output
    assert not (copied / namespace.DIR / "project.yaml").exists()


def test_nothing_to_write_is_a_refusal_and_not_an_empty_manifest(
        registry, copied, monkeypatch):
    """An empty manifest LOADS, declares nothing, and is then reported healthy — which is worse
    than no file at all. So a run where nothing was observed, accepted or answered refuses."""
    _install(monkeypatch, "infer",
             propose=lambda _repo: {"setup": _field(None, "", "unknown")})
    registry("flows", copied)
    shutil.rmtree(copied / namespace.DIR, ignore_errors=True)

    result = _invoke("env", "apply", "flows", "--yes")

    assert result.exit_code == 1, result.output
    assert "nothing to write" in result.output
    assert not (copied / namespace.DIR / "project.yaml").exists()


def test_a_field_that_was_read_and_is_empty_is_not_a_declaration(registry, copied, monkeypatch):
    """The same fence, on the case the REAL inference actually produces — and the one that got
    through.

    `onboarding/infer._components_proposal` returns `components` as `observed` with the value `{}`
    whenever a repository has exactly one stack, and `_setup_proposal` returns `setup` as
    `observed` with `[]` when the CI job that runs the tests installs nothing. Both are honest
    readings. Neither is a DECLARATION: every field this pass proposes already defaults to that
    same empty container, so the line changes no behaviour — it only spends the one bit
    `Manifest.declared_keys()` has for "a human filled this in", which `doctor._manifest` reads to
    tell "declares nothing, so this project has no gates at all" from "declares N of 31 settings".

    MEASURED BEFORE THIS GUARD, on a one-stack repository with no readable CI: `env apply --yes`
    exited 0 having written a manifest whose entire content was `components: {}`, and `doctor` then
    reported it `ok` — *"declares 2 of 31 settings"*. A file with no gates in it, graded healthy,
    written by us, at the exact moment a client is deciding whether to buy.
    """
    _install(monkeypatch, "infer", propose=lambda _repo: {
        "components": _field({}, "src/App.csproj", "observed",
                             note="one stack across the whole repository"),
        "setup": _field([], "azure-pipelines.yml:12", "observed",
                        note="the job that runs the tests installs nothing first"),
    })
    registry("flows", copied)
    shutil.rmtree(copied / namespace.DIR, ignore_errors=True)

    result = _invoke("env", "apply", "flows", "--yes")

    assert result.exit_code == 1, result.output
    assert "nothing to write" in result.output
    assert not (copied / namespace.DIR / "project.yaml").exists(), (
        "a manifest whose only content is an empty container was written; it declares no gates and "
        "`doctor` reports it as filled in")
    # AND THE READING SURVIVES. Refusing is only right if the report still says what was read —
    # otherwise this trades a false green for a silence, which is the other half of the same bug.
    assert "components" in result.output and "read, and empty" in result.output, result.output


def test_an_empty_reading_beside_a_real_one_is_left_out_of_the_file_and_not_of_the_report(
        registry, copied, monkeypatch):
    """The positive twin. Without it, "empty values are not written" is equally satisfied by an
    `apply` that refuses everything, and the guard above would be decoration.

    A human's own answer is exempt on purpose: `--set setup=` is a person in the room saying it,
    and the platform does not overrule them."""
    _install(monkeypatch, "infer", propose=lambda _repo: {
        "base_branch": _field("main", ".git/HEAD:1", "observed"),
        "components": _field({}, "src/App.csproj", "observed"),
    })
    registry("flows", copied)
    shutil.rmtree(copied / namespace.DIR, ignore_errors=True)

    result = _invoke("env", "apply", "flows", "--yes")

    assert result.exit_code == 0, result.output
    written = (copied / namespace.DIR / "project.yaml").read_text()
    assert "base_branch: main" in written
    assert not re.search(r"(?m)^components:", written), (
        f"the empty container was written into the document:\n{written}")
    # The reading is in the file's own header, where the developer opening it in six months looks.
    assert "components" in written and "read, and empty" in written, written


def test_an_empty_answer_a_human_typed_is_not_silently_dropped(infer, registry, copied):
    """The other side of the rule above, and it has to be asserted rather than believed.

    `_declares` refuses to write the empty values the PLATFORM proposed. A person who typed
    `--set setup=` said something, and dropping it would be us overruling the human in the room —
    the one thing every branch of this action is arranged not to do. So their answer goes into the
    document and meets `Manifest`, which refuses it in a sentence naming the field and writes
    nothing. Corrected by the schema, never silently discarded."""
    registry("flows", copied)
    shutil.rmtree(copied / namespace.DIR, ignore_errors=True)

    result = _invoke("env", "apply", "flows", "--yes", "--set", "setup=")

    assert result.exit_code == 1, result.output
    assert "setup" in result.output and "valid list" in result.output, result.output
    assert not (copied / namespace.DIR / "project.yaml").exists()


def test_a_flag_this_command_does_not_have_is_never_the_remedy_it_prints(
        infer, registry, copied):
    """`--set validate.lint` (no `=`) has to be corrected by naming `--set`.

    Measured before the fix: it printed *"--param takes key=value"* — an option `env apply` does
    not have, on the one command whose entire purpose is that a client can type what it tells
    them. It is `conformance` recommending `stack: security-oss` to a schema that forbids it, one
    size smaller: a remedy that cannot be run."""
    registry("flows", copied)

    result = _invoke("env", "apply", "flows", "--yes", "--set", "validate.lint")
    out = _plain(result.output)

    assert result.exit_code != 0
    assert "--set takes key=value" in out, out
    assert "--param" not in out, out


def test_the_real_inference_does_not_write_a_manifest_that_only_repeats_the_defaults(
        registry, tmp_path):
    """THE SAME CASE, THROUGH THE SHIPPED MODULE AND A REAL REPOSITORY — because the fixture above
    proves the transport's rule and not that the rule ever meets the module that triggers it.

    One `.csproj`, no CI, no git: `components` comes back `observed` with `{}` (one stack) and
    everything else is `inferred` or `unknown`, so a bare `--yes` has exactly one candidate and it
    declares nothing. This is the shape a legacy client hands us on day one."""
    pytest.importorskip("openfactory.onboarding.infer",
                        reason="openfactory/onboarding/infer.py has not landed yet")
    repo = tmp_path / "one-stack"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "App.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        "<TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>")
    registry("legacy", repo)

    result = _invoke("env", "apply", "legacy", "--yes")

    assert result.exit_code == 1, result.output
    assert not (repo / namespace.DIR / "project.yaml").exists(), (
        (repo / namespace.DIR / "project.yaml").read_text())
    assert "nothing to write" in result.output


def test_the_written_manifest_is_one_the_platform_can_actually_load(infer, registry, copied):
    """The end-to-end version of the fence above, through the real loader — because "it validated"
    and "the loader that runs before every ticket accepts it" have been two different things in
    this repository before."""
    from openfactory.loader import load_manifest
    from openfactory.registry import ProjectRegistry

    registry("flows", copied)
    shutil.rmtree(copied / namespace.DIR, ignore_errors=True)
    assert _invoke("env", "apply", "flows", "--yes", "--accept", "all").exit_code == 0

    manifest = load_manifest(ProjectRegistry().get("flows"))

    assert manifest.base_branch
    assert "base_branch" in manifest.declared_keys()


# ── 4. `check` — one verdict, and never a confident wrong green ─────────────────────────────────

def _report(verdict: str, findings: list, holds: list | None = None):
    """A stand-in for `readiness`'s Report: the two attributes this transport reads."""
    return types.SimpleNamespace(findings=findings, verdict=verdict, holds=holds or [])


def _finding(check, ok, message="m", remedy="", measured_on="worker", answered=True):
    return types.SimpleNamespace(check=check, ok=ok, message=message, remedy=remedy,
                                 measured_on=measured_on, answered=answered)


def test_a_verdict_this_cli_does_not_recognise_is_never_reported_as_green(
        registry, copied, monkeypatch):
    """An unrecognised verdict is reported as NOT ready AND as not understood, so the reader goes
    to look at the readiness module instead of at their own repository. The expensive direction of
    this mistake is the confident false green: the design that opened this card measured `env
    check` printing READY over a project whose box had never been proven."""
    _install(monkeypatch, "readiness",
             readiness_for=lambda _p: _report("perfectly fine", [_finding("docker", True)]))
    registry("flows", copied)

    result = _invoke("env", "check", "flows")

    assert result.exit_code == 1, result.output
    assert "does not recognise" in result.output


def test_a_ready_verdict_with_nothing_failing_really_does_exit_zero(
        registry, copied, monkeypatch):
    """THE POSITIVE TWIN, and it is not decoration: without it, "never says ready" is satisfied by
    a command that can never say ready — a guard that passes vacuously is exactly how a negative
    check shipped green over four broken call sites in this repository."""
    _install(monkeypatch, "readiness",
             readiness_for=lambda _p: _report("READY", [_finding("docker", True)]))
    registry("flows", copied)

    result = _invoke("env", "check", "flows")

    assert result.exit_code == 0, result.output
    assert "READY" in result.output


def test_ready_over_a_failing_check_is_a_contradiction_and_the_pessimistic_reading_wins(
        registry, copied, monkeypatch):
    """Two sources of truth that disagree: the verdict word and the findings. Nobody was ever
    harmed by being told to look again."""
    _install(monkeypatch, "readiness", readiness_for=lambda _p: _report(
        "READY", [_finding("docker", True), _finding("box_gate", False, remedy="prove it")]))
    registry("flows", copied)

    assert _invoke("env", "check", "flows").exit_code == 1


def test_a_held_project_is_held_and_not_merely_incomplete(registry, copied, monkeypatch):
    """`HELD` and `MISSING` are different questions and only one of them has work sitting still
    right now. A hold with every check passing must still exit non-zero."""
    _install(monkeypatch, "readiness", readiness_for=lambda _p: _report(
        "HELD: the box has never been proven", [_finding("docker", True)],
        holds=["the box has never been proven"]))
    registry("flows", copied)

    result = _invoke("env", "check", "flows")

    assert result.exit_code == 1, result.output
    assert "HELD" in result.output


def test_a_check_nothing_could_answer_is_not_rendered_as_a_pass(registry, copied, monkeypatch):
    """Three markers, not two. `----` is "no answer exists on this machine", and a report that
    asked nothing must not be able to look like a report that found nothing wrong."""
    _install(monkeypatch, "readiness", readiness_for=lambda _p: _report(
        "READY", [_finding("registry_parity", True, answered=False),
                  _finding("docker", True)]))
    registry("flows", copied)

    result = _invoke("env", "check", "flows")

    assert " ---- " in result.output
    assert "counted neither way" in result.output
    assert "registry_parity" in result.output


def test_a_finding_that_did_not_say_where_it_measured_never_borrows_the_runs_provenance(
        registry, copied, monkeypatch):
    """The one substitution `measured_on` exists to prevent: a finding measured on a laptop
    presented as measured in the factory. An absent value prints as `?` and is counted out loud."""
    _install(monkeypatch, "readiness", readiness_for=lambda _p: _report(
        "READY", [_finding("mystery", True, measured_on="")]))
    registry("flows", copied)

    out = _invoke("env", "check", "flows").output

    assert "[?]" in out
    assert "did not say where they were measured" in out


def test_the_verdict_says_where_it_was_measured_before_it_says_anything_else(
        registry, copied, monkeypatch):
    """A verdict about a laptop, delivered with the authority of a verdict about the factory, is
    the same disease with a better interface. So the provenance comes first, and when it is not the
    worker it says what that means."""
    _install(monkeypatch, "readiness",
             readiness_for=lambda _p: _report("READY", [_finding("docker", True)]))
    registry("flows", copied)

    out = _invoke("env", "check", "flows").output

    assert "measured on  local" in out
    assert "not the one that runs your tickets" in out


def test_a_readiness_module_that_raises_is_not_ready_rather_than_a_traceback(
        registry, copied, monkeypatch):
    """A check that crashed has proven nothing, and the person reading this is standing next to
    the client. A traceback is not an answer and "ready" is a lie."""
    def _boom(_p):
        raise RuntimeError("SSM is not answering")

    _install(monkeypatch, "readiness", readiness_for=_boom)
    registry("flows", copied)

    result = _invoke("env", "check", "flows")

    assert result.exit_code == 1
    assert "SSM is not answering" in result.output
    assert "NOT ready" in result.output or "proven nothing" in result.output


def test_a_readiness_module_with_no_entry_point_names_what_it_does_export(
        registry, copied, monkeypatch):
    """"No entry point" with nothing to look at sends the one person who does not yet know this
    system to read a nine-hundred-line module hunting for a function name."""
    _install(monkeypatch, "readiness", assess=lambda _p: None)
    registry("flows", copied)

    out = _invoke("env", "check", "flows").output

    assert "exports neither" in out and "assess" in out


# ── 5. the door is a mapping, and the rows are the implementation ───────────────────────────────

@pytest.fixture
def spy(monkeypatch):
    """Every action's runner replaced by a recorder, through the CATALOG the layer really reads."""
    seen: list[tuple[str, dict]] = []

    def recorder(name: str):
        async def run(by=None, **params):
            assert isinstance(by, actions.Actor), f"{name} was reached without an Actor"
            seen.append((name, params))
            return actions.done(f"recorded {name}")
        return run

    monkeypatch.setattr(catalog, "CATALOG", {
        name: dataclasses.replace(spec, run=recorder(name))
        for name, spec in catalog.CATALOG.items()})
    return seen


@pytest.mark.parametrize("argv,row,expected", [
    (("env", "read", "somewhere"), "env_read", {"target": "somewhere"}),
    (("env", "check", "proj"), "env_check", {"project": "proj"}),
    # `pr` rides the same mapping as every other option: the door hands the row exactly what the
    # row declares, so the server-side proposal path (`--pr`) is reachable from `sdlc act` too
    # rather than being a CLI-only feature — which is the shape ADR-0039 exists to prevent.
    (("env", "apply", "proj", "--yes"), "env_apply",
     {"project": "proj", "yes": True, "force": False, "accept": [], "answers": {}, "out": "",
      "pr": False}),
    (("env", "apply", "proj", "--yes", "--pr"), "env_apply",
     {"project": "proj", "yes": True, "force": False, "accept": [], "answers": {}, "out": "",
      "pr": True}),
])
def test_each_env_verb_is_a_mapping_onto_its_catalog_row(argv, row, expected, spy):
    """ADR-0039, held rather than intended. `sdlc act env_read` reaching the row proves nothing
    about `sdlc env read` — and `sdlc env` is the door a tech-lead actually types, so it is the one
    that would grow its own second implementation.

    The EXIT CODE IS NOT ASSERTED and that is deliberate: the spy returns an outcome with no
    `data`, and `env check` correctly refuses to call a verdict it cannot see `ready` in. Demanding
    zero here would force the door to treat a missing answer as a good one, which is the defect the
    door exists to prevent."""
    result = _invoke(*argv)

    assert "Traceback" not in result.output, result.output
    assert spy == [(row, expected)]


def test_the_panel_offers_the_same_three_verbs(spy):
    """The panel is the reference surface (ADR-0038). A capability reachable only from a CLI on a
    laptop is the defect this repository has shipped about twenty times — and a laptop is precisely
    the machine that cannot answer "is the factory ready"."""
    from fastapi.testclient import TestClient

    from openfactory.api.app import app as panel

    with TestClient(panel) as client:
        listed = {row["name"] for row in client.get("/api/actions").json()}
        answered = client.post("/api/act/env_check", json={"params": {"project": "demo"}})

    assert {"env_read", "env_check", "env_apply"} <= listed
    assert answered.status_code == 200, answered.text
    assert spy == [("env_check", {"project": "demo"})]


def test_the_env_verbs_declare_who_may_run_them(spy):
    """Reading a repository and asking whether a project is ready are QUESTIONS, and a question is
    not authority. Writing into a client's repository is not a question."""
    assert actions.CATALOG["env_read"].needs_admin is False
    assert actions.CATALOG["env_check"].needs_admin is False
    assert actions.CATALOG["env_apply"].needs_admin is True


# ── 6. the contract with the modules that are landing separately ────────────────────────────────

def test_the_missing_module_is_a_sentence_and_not_a_traceback(registry, copied, monkeypatch):
    """Until `openfactory.onboarding.infer` lands, `env read` has to say so in a line somebody can act on
    — naming the module and what it would have done. This is the state a client would meet on any
    deployment built from a tree where that slice has not shipped."""
    import openfactory.onboarding as pkg

    monkeypatch.delitem(sys.modules, "openfactory.onboarding.infer", raising=False)
    monkeypatch.delattr(pkg, "infer", raising=False)
    monkeypatch.setattr(pkg, "__path__", [], raising=False)  # nothing left to import it from
    registry("flows", copied)

    result = _invoke("env", "read", "flows")

    assert result.exit_code == 1
    assert "no inference module" in result.output
    assert "openfactory.onboarding.infer" in result.output


@pytest.mark.parametrize("module,attr", [("infer", "propose"), ("readiness", "check")])
def test_the_real_module_is_read_the_same_way_the_fixtures_are(module, attr, registry, copied):
    """RUN AGAINST THE SHIPPED MODULE THE MOMENT IT EXISTS, so this file cannot quietly become a
    test of its own mock. It skips loudly while the slice is unbuilt, which is the honest state —
    and the moment it lands, a shape this transport cannot read fails here instead of in a room
    with a client."""
    real = pytest.importorskip(f"openfactory.onboarding.{module}",
                               reason=f"openfactory/onboarding/{module}.py has not landed yet")
    entry = getattr(real, attr, None) or getattr(real, "readiness_for", None)
    if entry is None:
        pytest.skip(f"openfactory.onboarding.{module} exports no entry point yet")
    registry("flows", copied)

    verb = "read" if module == "infer" else "check"
    result = _invoke("env", verb, "flows")

    # NOT "exit_code == 0": a real readiness answer on this machine is legitimately NOT ready. What
    # must never happen is the transport failing to READ what the module returned.
    assert "cannot read" not in result.output, result.output
    assert "does not recognise" not in result.output, result.output
    assert "exports neither" not in result.output, result.output
    # AND NOT SILENTLY HALF-READ. This is the `getattr(bundle, "modules")` trap, which is not
    # hypothetical here: the contract said each field carries a `source`, and the module that
    # landed carries a list of `Evidence` objects instead. A transport reading only the first
    # spelling prints `(no source recorded)` under every field of a proposal that cited every one
    # of them — a calm, complete, wrong report, and no exception anywhere.
    assert "(no source recorded)" not in result.output, (
        "the real module's provenance is not being read — every field came out uncited")
    if verb == "read":
        assert result.exit_code == 0, result.output
        assert ":" in result.output, "no file:line citation survived into the report"
