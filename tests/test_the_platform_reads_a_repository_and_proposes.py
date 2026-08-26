"""`openfactory.onboarding.infer` — the first thing in this platform that PROPOSES instead of grading.

WHAT THESE GUARD. `doctor`, `conformance` and `box prove` all check a manifest the client already
wrote. On fifteen years of legacy the hard part is FINDING the test command among four candidates,
three of which only work on one developer's laptop. So the assertions here are about the three
things that make a proposal trustworthy enough to read aloud in a room full of the client's own
developers:

    1. the value came from THEIR file, and the citation is a real `file:line` that resolves;
    2. a guess is labelled a guess, and a refusal is a QUESTION, never an empty field;
    3. the pass runs nothing, writes nothing, reaches no network — so it is safe to run in that
       room, on their laptop, before anybody has agreed to anything.

THE FIXTURES ARE BUILT HERE, from the real files. the toy-project directory (`tests/demo_projects.py`) does not
exist in CI, so the shapes that matter — an Azure pipeline with a deployment stage, a GitHub
workflow pair where one runs on `pull_request` and the other on `push`, a .NET pair joined by a
`<ProjectReference>` — are written into `tmp_path` verbatim from the real ones. The two tests that
touch the real fixtures skip loudly when they are absent rather than passing for free.

EVERY GUARD BELOW WAS VERIFIED BY MUTATION: the defect it names was reintroduced in
`openfactory/onboarding/infer.py` and the named test was watched go red. A guard nobody has seen fail is
decoration.
"""

from __future__ import annotations

import hashlib
import os
import re
import socket
import subprocess
import types
from pathlib import Path

import pytest
import yaml

from openfactory import namespace
from openfactory.contracts import Manifest
from openfactory.onboarding import (
    INFERRED,
    OBSERVED,
    UNKNOWN,
    classify,
    infer,
    propose,
    render_report,
    render_yaml,
    split_commands,
    to_manifest_dict,
)
from tests.demo_projects import demo_projects_root  # noqa: E402 — beside its one use

REAL_FIXTURES = demo_projects_root()


# --- building repositories that look like the real ones ----------------------------------


def _git(root: Path, *, origin_head: str | None = "main", head: str = "main") -> None:
    """A `.git` directory with only the two files this module reads. Not a real repository on
    purpose: `infer` must answer from FILES, so a fixture that needed `git init` would be proving
    something about git rather than about the module."""
    git = root / ".git"
    (git / "refs" / "remotes" / "origin").mkdir(parents=True, exist_ok=True)
    (git / "HEAD").write_text(f"ref: refs/heads/{head}\n")
    if origin_head is not None:
        (git / "refs" / "remotes" / "origin" / "HEAD").write_text(
            f"ref: refs/remotes/origin/{origin_head}\n"
        )


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


#: fx-ado's real pipeline, trimmed to the two stages that matter. The install line is the harness's
#: own canary: it CONTAINS the word `pytest` and is not a test command.
ADO_PIPELINE = """\
trigger:
  branches:
    include:
      - main

pr:
  branches:
    include:
      - main

stages:
  - stage: test
    jobs:
      - job: pytest
        steps:
          - task: UsePythonVersion@0
            inputs:
              versionSpec: '3.11'
          - script: python -m pip install --quiet pytest
            displayName: install pytest
          - script: python -m pytest -q
            displayName: pytest -q

  - stage: staging
    dependsOn: test
    jobs:
      - deployment: staging
        environment: staging
        strategy:
          runOnce:
            deploy:
              steps:
                - script: echo "reached staging"
                  displayName: mark staging
"""

GH_CI = """\
name: ci
on:
  pull_request:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm test
"""

GH_DEPLOY = """\
name: deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: yarn test
      - run: zip -qr lambda.zip src/
"""


@pytest.fixture
def ado_repo(tmp_path: Path) -> Path:
    root = tmp_path / "fx-ado-like"
    root.mkdir()
    _git(root)
    _write(root, "azure-pipelines.yml", ADO_PIPELINE)
    _write(root, "orders/__init__.py", "")
    _write(root, "orders/pricing.py", "def price(): return 1\n")
    _write(root, "tests/test_pricing.py", "def test_price(): assert True\n")
    return root


@pytest.fixture
def dotnet_repo(tmp_path: Path) -> Path:
    """fx-dotnet's shape: two projects, NO solution file, joined by a `<ProjectReference>`. The
    hand-written manifest for the real one carries a comment saying `dotnet restore` with no target
    "não adivinha" — this is the fixture that proves the graph answers it."""
    root = tmp_path / "fx-dotnet-like"
    root.mkdir()
    _git(root)
    _write(root, "src/Orders.csproj", "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n")
    _write(
        root,
        "tests/Orders.Tests.csproj",
        '\ufeff<Project Sdk="Microsoft.NET.Sdk">\n'
        "  <ItemGroup>\n"
        '    <ProjectReference Include="..\\src\\Orders.csproj" />\n'
        "  </ItemGroup>\n"
        "</Project>\n",
    )
    _write(root, "src/Orders.cs", "public class Orders {}\n")
    return root


# --- 1. the classifier, and the case that must fail --------------------------------------


def test_an_install_line_that_mentions_pytest_is_not_a_test_command():
    """THE HARNESS'S OWN CANARY, and the reason every pattern is anchored at the head of the
    command. `python -m pip install --quiet pytest` is a real line in a real client pipeline, it
    contains the string `pytest`, and reading it as the test command would put an install into
    `validate.test` — a confident wrong answer with a citation next to it, which is worse than no
    answer at all."""
    assert classify("python -m pip install --quiet pytest") == "setup"
    assert classify("pip install pytest pytest-cov") == "setup"
    assert classify("python -m pytest -q") == "test"
    assert classify("pytest -q") == "test"
    # The case that isolates the ANCHOR from the ordering: no install pattern matches this line at
    # all, so only `^` keeps it out of `validate.test`. CI files are full of `echo` help text.
    assert classify('echo "run pytest before you merge"') == ""
    assert classify("git commit -m 'npm test is green'") == ""


def test_a_command_with_no_role_says_so_rather_than_being_forced_into_one():
    """`""` is a lookup that ran and found nothing — not a failure, and not a default role. Every
    deploy pipeline is full of these."""
    for line in ('echo "deploy simulado concluído"', "zip -qr lambda.zip src/", "aws s3 cp a b"):
        assert classify(line) == "", line


def test_a_shell_line_is_split_before_it_is_classified():
    """`cd x && pytest` is a test run. A classifier fed the whole line sees `cd`."""
    assert split_commands("cd api && python -m pytest -q") == ["cd api", "python -m pytest -q"]
    assert classify(split_commands("cd api && python -m pytest -q")[1]) == "test"
    assert split_commands("\t@ruff check .") == ["ruff check ."]


# --- 2. the client's CI beats anything we could guess ------------------------------------


def test_a_command_read_from_the_clients_pipeline_is_observed_and_cited(ado_repo: Path):
    """The value has to come out of THEIR file, and the citation has to point at the line that
    carries it — not at the file, not at the job, at the line. A reviewer reads the excerpt."""
    test = infer(ado_repo).fields["validate.test"]
    assert test.confidence == OBSERVED
    assert test.value == "python -m pytest -q"
    assert test.evidence[0].path == "azure-pipelines.yml"
    assert test.evidence[0].line == 21, "the citation must point at the line that carries it"
    assert "pull request" in test.candidates[0].why


def test_the_clients_own_ci_beats_the_convention_it_contradicts(tmp_path: Path):
    """THE WHOLE ARGUMENT OF THE MODULE, and it needs a repository where the two genuinely differ.

    The convention this stack implies is `python -m pytest -q`. This team's pipeline excludes a
    vendored tree, so their real command is longer — and it is the one that passes off somebody's
    laptop. The convention must not win, and it must not vanish either: "we found two candidates,
    here they both are" is the finding a legacy client actually needs, because the person in the
    room is the only one who knows why `vendor/` is excluded.
    """
    root = tmp_path / "contradiction"
    root.mkdir()
    _git(root)
    _write(root, "pkg/thing.py", "x = 1\n")
    _write(root, "tests/test_thing.py", "def test(): assert True\n")
    _write(
        root,
        ".github/workflows/ci.yml",
        "name: ci\non:\n  pull_request:\njobs:\n  test:\n    steps:\n"
        "      - run: python -m pytest -q --ignore=vendor\n",
    )

    test = infer(root).fields["validate.test"]
    assert test.value == "python -m pytest -q --ignore=vendor"
    assert test.confidence == OBSERVED
    assert test.evidence[0].locator == ".github/workflows/ci.yml:7"
    beaten = [c for c in test.candidates if c.confidence == INFERRED]
    assert beaten and beaten[0].value == "python -m pytest -q", test.candidates
    assert "2 candidates" in test.note


def test_setup_comes_from_the_same_ci_job_as_the_test_command(ado_repo: Path):
    """CI jobs are independent processes. An install step from the LINT job has never run in the
    same container as the test command, so stitching them together proposes a `setup:` no machine
    has ever executed."""
    setup = infer(ado_repo).fields["setup"]
    assert setup.confidence == OBSERVED
    assert setup.value == ["python -m pip install --quiet pytest"]
    assert setup.evidence[0].locator == "azure-pipelines.yml:19"


def test_azure_steps_are_found_inside_a_deployment_strategy(ado_repo: Path):
    """ADO nests steps four ways and the deepest is `deployment: strategy: runOnce: deploy:`.
    A reader that stops at three reports "no commands" on the pipelines that use the fourth."""
    from openfactory.onboarding.infer import _ado_steps, _load_yaml

    # THREE VALUES SINCE #175: the step's own `displayName` rides along, so a check the client
    # named and our roles do not cover can be proposed under their name rather than dropped.
    steps = _ado_steps(_load_yaml(ado_repo / "azure-pipelines.yml"))
    jobs = [job for job, _script, _name in steps]

    assert "staging" in jobs, "the deployment stage's steps were never reached"


def test_a_pull_request_workflow_outranks_a_push_only_one(tmp_path: Path):
    """`on:` IS NOT `"on"`. YAML 1.1 parses a bare `on` as the boolean True, so a naive reader
    finds no triggers on EVERY GitHub workflow ever written and ranks the deploy pipeline level
    with the PR gate. Here `ci.yml` (pull_request, `npm test`) must beat `deploy.yml` (push only,
    `yarn test`)."""
    root = tmp_path / "gh"
    root.mkdir()
    _git(root)
    # NAMED `build.yml` ON PURPOSE: it sorts BEFORE `ci.yml`, so if the ranking ever collapses
    # (the `on:`-is-True bug does exactly that — every workflow lands on the same rank) the
    # alphabetical tie-break hands the verdict to the push-only pipeline and this test goes red.
    # With both files named so the right answer also wins alphabetically, the guard proves nothing.
    _write(root, ".github/workflows/ci.yml", GH_CI)
    _write(root, ".github/workflows/build.yml", GH_DEPLOY)
    _write(root, "package.json", '{\n  "scripts": { "test": "node --test" }\n}\n')

    test = infer(root).fields["validate.test"]
    assert test.value == "npm test", "the push-only deploy workflow outranked the PR gate"
    assert test.evidence[0].path == ".github/workflows/ci.yml"
    assert "pull request" in test.candidates[0].why


# --- 3. the three tiers, and the refusal that is the product -----------------------------


def test_a_field_nothing_states_is_refused_with_a_question_never_guessed(tmp_path: Path):
    """The third tier is what earns trust. A repository with no linter must produce a QUESTION —
    not `validate: {}`, not a plausible `ruff check .` for a team that has never run ruff."""
    root = tmp_path / "bare"
    root.mkdir()
    _git(root)
    _write(root, "app/main.py", "x = 1\n")
    _write(root, "tests/test_main.py", "def test_x(): assert True\n")

    lint = infer(root).fields["validate.lint"]
    assert lint.confidence == UNKNOWN
    assert lint.value is None, "an unknown field must not carry a value"
    assert "?" in lint.note, f"a refusal has to ask something: {lint.note!r}"


def test_none_means_could_not_read_and_empty_means_read_and_nothing_there(tmp_path: Path):
    """This codebase's most expensive defect class, applied to `setup:`.

    `[]` is only reachable after reading a source that runs the tests WITHOUT installing anything
    (fx-dsk-ui's pipeline says so in a comment of its own), and it is only ever `observed`. `None`
    means we could not determine it, and it is only ever `unknown`. The two never share a tier.
    """
    read_it = tmp_path / "reads-empty"
    read_it.mkdir()
    _git(read_it)
    _write(read_it, ".github/workflows/ci.yml", "name: ci\non:\n  pull_request:\njobs:\n"
                                                "  t:\n    steps:\n      - run: npm test\n")
    _write(read_it, "package.json", '{\n  "scripts": { "test": "node --test" }\n}\n')
    empty = infer(read_it).fields["setup"]
    assert empty.value == [] and empty.confidence == OBSERVED
    assert empty.evidence, "an empty answer still has to cite what it read"

    could_not = tmp_path / "cannot-tell"
    could_not.mkdir()
    _git(could_not)
    _write(could_not, "app/main.py", "x = 1\n")
    _write(could_not, "tests/test_main.py", "def test_x(): assert True\n")
    unknown = infer(could_not).fields["setup"]
    assert unknown.value is None and unknown.confidence == UNKNOWN

    # the pair is the point — if these two ever collapse into one value, the distinction is gone
    assert empty.value != unknown.value


def test_a_python_repo_with_no_packaging_is_never_told_to_pip_install_dash_e(tmp_path: Path):
    """Card #99 §6 defect 9: `pip install -e '.[dev]'` is hardcoded into the project template for
    every client. On a repository with no `pyproject.toml` it fails on contact, and a proposal that
    fails on contact is worse than an admitted `unknown`."""
    root = tmp_path / "no-packaging"
    root.mkdir()
    _git(root)
    _write(root, "calc/money.py", "def add(a, b): return a + b\n")
    _write(root, "tests/test_money.py", "def test_add(): assert True\n")

    setup = infer(root).fields["setup"]
    assert setup.confidence == UNKNOWN
    assert setup.value is None


def test_a_packaged_python_repo_gets_the_extra_its_own_pyproject_declares(tmp_path: Path):
    """The positive twin. Without it, "we never propose `pip install -e`" also passes when the
    branch that proposes it is dead."""
    root = tmp_path / "packaged"
    root.mkdir()
    _git(root)
    _write(
        root,
        "pyproject.toml",
        "[project]\nname = 'x'\nversion = '0'\n\n"
        "[project.optional-dependencies]\ndev = ['pytest']\n",
    )
    _write(root, "tests/test_x.py", "def test_x(): assert True\n")

    setup = infer(root).fields["setup"]
    assert setup.confidence == INFERRED
    assert setup.value == ["pip install -e '.[dev]'"]
    assert setup.evidence[0].path == "pyproject.toml"


def test_the_test_command_is_python_dash_m_pytest_not_the_bare_console_script(tmp_path: Path):
    """A lesson this repository already paid for, in its own `pyproject.toml`: the bare `pytest`
    console script does not put the CWD on `sys.path`, `python -m pytest` does, and five commits
    landed on a red main because of the difference. A legacy repository with no packaging depends
    on exactly that entry to import its own modules."""
    root = tmp_path / "convention"
    root.mkdir()
    _git(root)
    _write(root, "pkg/thing.py", "x = 1\n")
    _write(root, "tests/test_thing.py", "def test(): assert True\n")

    test = infer(root).fields["validate.test"]
    assert test.value == "python -m pytest -q"
    assert test.confidence == INFERRED, "a convention is never `observed`"


# --- 4. evidence that resolves -----------------------------------------------------------


@pytest.mark.parametrize("builder", ["ado_repo", "dotnet_repo"])
def test_every_proposed_field_cites_a_line_that_actually_exists(builder, request):
    """An `observed` value whose citation does not resolve is an assertion wearing evidence's
    clothes. Every path must exist in the repository and every line must be inside the file."""
    repo: Path = request.getfixturevalue(builder)
    proposal = infer(repo)
    for field in proposal.proposed():
        assert field.evidence, f"{field.field} is proposed with no evidence at all"
        for evidence in field.evidence:
            if evidence.origin != "repo":
                continue
            path = repo / evidence.path
            assert path.is_file(), f"{field.field} cites {evidence.path}, which is not a file"
            if evidence.line is not None:
                lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                assert 1 <= evidence.line <= len(lines), (
                    f"{field.field} cites {evidence.locator}; that file has {len(lines)} lines"
                )


def test_the_dotnet_reference_graph_names_the_restore_target(dotnet_repo: Path):
    """The .NET case, and the client-2 stack. Two projects, no solution: `dotnet restore` with no
    target does not guess, it fails. The repository states the answer in `<ProjectReference>` — the
    project nothing points at is the one to restore."""
    proposal = infer(dotnet_repo)
    assert proposal.fields["setup"].value == ["dotnet restore tests/Orders.Tests.csproj"]
    assert proposal.fields["validate.test"].value == (
        "dotnet test tests/Orders.Tests.csproj --nologo -v quiet"
    )


def test_several_dotnet_entry_points_and_no_solution_is_a_question_not_a_coin_flip(tmp_path: Path):
    """The negative twin of the test above. Two projects that reference nothing and each other
    never: picking one is how a client's very first `setup:` fails on a project we never read."""
    root = tmp_path / "ambiguous-dotnet"
    root.mkdir()
    _git(root)
    _write(root, "a/A.csproj", "<Project></Project>\n")
    _write(root, "b/B.csproj", "<Project></Project>\n")

    proposal = infer(root)
    assert proposal.fields["setup"].confidence == UNKNOWN
    assert proposal.fields["validate.test"].confidence == UNKNOWN
    assert "entry point" in proposal.fields["validate.test"].note


# --- 5. what the schema cannot say -------------------------------------------------------


def test_a_stack_with_no_preset_is_declared_inexpressible_rather_than_dropped(dotnet_repo: Path):
    """Client 2 entirely. `available_stacks()` ships node/python/security-oss/terraform and
    `Component` requires BOTH `path` and `stack`, so a .NET area cannot be declared at all.
    Emitting a component anyway writes YAML `conformance` refuses; saying nothing hides it."""
    proposal = infer(dotnet_repo)
    dotnet = [s for s in proposal.stacks if s.stack == "dotnet"]
    assert dotnet and dotnet[0].expressible is False
    assert proposal.cannot_express, "a stack with no preset vanished from the report"
    assert "dotnet" in proposal.cannot_express[0]
    assert "repo-wide" in proposal.cannot_express[0], "the block must name the expressible answer"


def test_components_are_proposed_only_when_the_repo_is_genuinely_polyglot(tmp_path: Path):
    """POSITIVE TWIN, and it is required: "we do not invent components" also passes when the code
    that proposes them is dead. Two expressible stacks in disjoint subtrees must produce a map."""
    root = tmp_path / "polyglot"
    root.mkdir()
    _git(root)
    _write(root, "api/pyproject.toml", "[project]\nname='api'\nversion='0'\n")
    _write(root, "api/app.py", "x = 1\n")
    _write(root, "web/package.json", '{\n  "scripts": { "test": "node --test" }\n}\n')
    _write(root, "web/package-lock.json", "{}\n")

    components = infer(root).fields["components"]
    assert components.known, components.note
    assert components.value == {
        "api": {"path": "api/**", "stack": "python"},
        "web": {"path": "web/**", "stack": "node"},
    }


def test_a_single_stack_repo_is_told_repo_wide_gates_are_the_right_shape(ado_repo: Path):
    """The negative half of the pair. `{}` here is a reading, not a default — so it is `observed`
    and it carries a citation."""
    components = infer(ado_repo).fields["components"]
    assert components.value == {}
    assert components.confidence == OBSERVED
    assert components.evidence, "`{}` with no citation reads as a default rather than a reading"


def test_a_polyglot_repo_with_one_inexpressible_area_refuses_a_partial_map(tmp_path: Path):
    """A PARTIAL component map is worse than none: the unmapped area silently inherits repo-wide
    treatment while `max_touched_components` counts against a map that does not describe the
    repository."""
    root = tmp_path / "half-expressible"
    root.mkdir()
    _git(root)
    _write(root, "api/pyproject.toml", "[project]\nname='api'\nversion='0'\n")
    _write(root, "svc/Svc.csproj", "<Project></Project>\n")

    proposal = infer(root)
    components = proposal.fields["components"]
    assert components.confidence == UNKNOWN
    # NOT `{}`. See `test_a_refused_components_field_is_none_and_never_an_empty_map` below.
    assert components.value is None
    assert "PARTIAL" in components.note
    assert any("dotnet" in entry for entry in proposal.cannot_express)


@pytest.mark.parametrize(
    "name,build",
    [
        # polyglot with an area that has no preset — there ARE components, we cannot say them
        ("half-expressible", {"api/pyproject.toml": "[project]\nname='a'\nversion='0'\n",
                              "svc/Svc.csproj": "<Project></Project>\n"}),
        # a stack rooted at `/` — its glob would be `**` and would overlap everything
        ("rooted-at-slash", {"pyproject.toml": "[project]\nname='a'\nversion='0'\n",
                             "infra/main.tf": 'resource "null_resource" "x" {}\n'}),
        # nothing detected at all
        ("nothing-here", {"README": "a docs repo\n"}),
    ],
)
def test_a_refused_components_field_is_none_and_never_an_empty_map(name, build, tmp_path: Path):
    """THE None/{} RULE, at the one field where all four exits pass through the same return.

    `{}` is a CLAIM — "we read this repository and it has no components". It is true for exactly
    one exit: a single expressible stack, where repo-wide gates are the right shape and the tier is
    `observed`. Every other exit is a REFUSAL: there are areas here and the schema, or the layout,
    stops us naming them. Those must be `None`, because a caller that keys off the value would
    otherwise write `components: {}` into a manifest for a repository whose components we declined
    to name — and the module's own docstring promises that an empty value is only ever `observed`.

    All three shapes below returned `{}` under an `unknown` tier before this guard existed.
    """
    root = tmp_path / name
    root.mkdir()
    _git(root)
    for rel, text in build.items():
        _write(root, rel, text)

    components = infer(root).fields["components"]
    assert components.confidence == UNKNOWN, components
    assert components.value is None, f"{name}: a refusal carries None, never an empty container"


def test_no_field_ever_pairs_an_unknown_tier_with_an_empty_container(tmp_path: Path):
    """The rule stated once, over every field, so a new field cannot reintroduce it quietly."""
    root = tmp_path / "sweep"
    root.mkdir()
    _git(root)
    _write(root, "api/pyproject.toml", "[project]\nname='a'\nversion='0'\n")
    _write(root, "svc/Svc.csproj", "<Project></Project>\n")

    for name, field in infer(root).fields.items():
        if field.confidence == UNKNOWN:
            assert field.value is None, (
                f"{name} is `unknown` and carries {field.value!r} — `unknown` means we could not "
                f"determine it, and an empty container says we read it and there was nothing there"
            )


# --- 6. purity: it reads files and does nothing else --------------------------------------


def test_infer_never_runs_a_command_and_never_opens_a_socket(monkeypatch, ado_repo, dotnet_repo):
    """THE FENCE THAT MAKES IT SAFE TO RUN IN THE ROOM.

    Running a legacy suite can truncate a shared dev database (card #99 §4.1, attack 2), and a
    network call during onboarding is a call from the client's laptop with whatever credentials it
    happens to hold. So the guard forbids the capability rather than checking the behaviour: every
    process- and socket-opening entry point raises, and `infer` still has to answer. This is also
    why `base_branch` is read out of `.git/HEAD` as text instead of shelling out to `git`.
    """

    def forbidden(*args, **kwargs):
        raise AssertionError(f"infer reached outside the filesystem: {args[:1]}")

    for target in ("run", "Popen", "check_output", "call", "check_call"):
        monkeypatch.setattr(subprocess, target, forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    for repo in (ado_repo, dotnet_repo):
        proposal = infer(repo)
        assert proposal.fields["base_branch"].value == "main"


def _fingerprint(root: Path) -> str:
    """Every path under `root` with its bytes. Compared before and after, so "writes nothing" is
    measured on disk rather than inferred from a code path not being taken."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_infer_writes_not_one_byte_into_the_repository(ado_repo: Path):
    before = _fingerprint(ado_repo)
    infer(ado_repo)
    render_yaml(infer(ado_repo))
    render_report(infer(ado_repo))
    assert _fingerprint(ado_repo) == before


def test_the_same_repository_proposes_the_same_thing_twice(ado_repo: Path):
    """A proposal you cannot diff against last week's is a proposal nobody can review. Nothing may
    depend on `os.walk` order or on dict iteration luck."""
    first, second = infer(ado_repo), infer(ado_repo)
    assert first.model_dump() == second.model_dump()
    assert render_yaml(first) == render_yaml(second)


def test_a_repository_that_cannot_be_read_raises_instead_of_proposing_nothing(tmp_path: Path):
    """`os.walk` SWALLOWS the error and yields nothing, so a typo in a path would come back as a
    complete, confident proposal in which every field is `unknown` — a failure wearing the costume
    of an answer."""
    with pytest.raises(NotADirectoryError) as caught:
        infer(tmp_path / "not-here")
    assert "not a directory" in str(caught.value)


# --- 7. the proposal is a manifest the platform can load ----------------------------------


@pytest.mark.parametrize("builder", ["ado_repo", "dotnet_repo"])
def test_what_is_emitted_is_a_manifest_the_schema_accepts(builder, request):
    """`openfactory/policy/conformance.py:63` already ships the opposite: a remedy the platform prints
    (`stack: security-oss`) that its own schema refuses. A proposal that cannot be pasted into
    `.sdlc/project.yaml` repeats that, one layer earlier and with more authority."""
    proposal = infer(request.getfixturevalue(builder))
    emitted = to_manifest_dict(proposal)
    Manifest.model_validate(emitted)
    Manifest.model_validate(yaml.safe_load(render_yaml(proposal)) or {})


def test_an_unknown_field_is_never_written_as_an_empty_value(tmp_path: Path):
    """`setup: []` in a YAML file reads as "this project needs no install", which is a claim. The
    third tier exists precisely so we do not make it — the file has to SAY it does not know."""
    root = tmp_path / "unknowns"
    root.mkdir()
    _git(root)
    _write(root, "app/main.py", "x = 1\n")
    _write(root, "tests/test_main.py", "def test(): assert True\n")

    proposal = infer(root)
    emitted = to_manifest_dict(proposal)
    assert "setup" not in emitted
    text = render_yaml(proposal)
    assert "# setup: UNKNOWN" in text
    assert "setup: []" not in text
    assert "UNKNOWN" in text and "?" in text


# --- 8. it declares its own blindness ----------------------------------------------------


def test_the_proposal_declares_the_manifest_fields_it_never_looked_at(ado_repo: Path):
    """A proposal that covers 4 of 31 fields and says nothing about the other 27 reads as a
    complete proposal. Computed against the live schema, so it cannot go stale as fields are
    added — the same reason `knowledge/generator.py` surveys the extensions it did not read."""
    proposal = infer(ado_repo)
    assert proposal.not_attempted
    assert "merge_policy" in proposal.not_attempted
    assert "prod_approvers" in proposal.not_attempted
    attempted = {"base_branch", "setup", "validation", "components"}
    assert set(proposal.not_attempted) == set(Manifest.model_fields) - attempted


def test_a_ci_file_we_cannot_parse_is_not_reported_as_no_ci(tmp_path: Path):
    """"You have no CI" and "we could not read your CI" have opposite remedies, and telling a
    client the first when the second is true is how the platform gets blamed for their setup."""
    root = tmp_path / "bitbucket"
    root.mkdir()
    _git(root)
    _write(root, "bitbucket-pipelines.yml", "pipelines:\n  default:\n    - step:\n"
                                            "        script:\n          - pytest -q\n")
    proposal = infer(root)
    assert "bitbucket-pipelines.yml" in proposal.ci_files_seen
    assert "bitbucket-pipelines.yml" not in proposal.ci_files_read
    assert "NOT read" in render_report(proposal)


#: A workflow with a tab where YAML forbids one — the shape a hand-edited legacy pipeline takes.
BROKEN_WORKFLOW = "name: ci\non:\n  pull_request:\njobs:\n\tt:\n    steps:\n      - run: pytest -q\n"


def test_a_ci_file_that_does_not_parse_is_never_counted_as_one_we_read(tmp_path: Path):
    """A FILE WE COULD NOT PARSE IS NOT A FILE WE READ, and the difference is the whole report.

    Every branch of the collector used to append the path to `ci_files_read` before its reader ran.
    The reader returns `[]` on a document it cannot load — which is byte-for-byte what a reader
    returns for a pipeline that genuinely defines no commands — so a workflow with a tab in it came
    back as *"read 1 CI/build file(s): .github/workflows/ci.yml"* followed by *"no test command
    anywhere … (CI read: .github/workflows/ci.yml)"*. A failure wearing the costume of an answer,
    pointing at the one file that contained the answer.
    """
    root = tmp_path / "tabbed"
    root.mkdir()
    _git(root)
    _write(root, ".github/workflows/ci.yml", BROKEN_WORKFLOW)
    _write(root, "app/main.py", "x = 1\n")

    proposal = infer(root)
    assert ".github/workflows/ci.yml" not in proposal.ci_files_read
    assert ".github/workflows/ci.yml" in proposal.ci_files_seen
    assert any("could NOT read it" in q for q in proposal.questions), proposal.questions
    # and the refusal underneath must not blame the repository for what we could not read
    assert "CI read: .github/workflows/ci.yml" not in proposal.fields["validate.test"].note


def test_an_azure_template_that_exists_and_does_not_parse_is_declared_unread(tmp_path: Path):
    """A real Azure repository puts its steps in templates. `_read_azure` returns `([], [])` for a
    document it cannot load — identical to a template that defines no steps — so a template that
    IS there and does not parse used to vanish silently, and the entry pipeline was reported as
    fully read. Not-fetchable and not-parseable are both "we did not read it"."""
    root = tmp_path / "ado-template"
    root.mkdir()
    _git(root)
    _write(root, "azure-pipelines.yml",
           "pr:\n  branches:\n    include: [main]\nstages:\n  - template: ci/steps.yml\n")
    _write(root, "ci/steps.yml", "steps:\n\t- script: pytest -q\n")  # tab: will not parse
    _write(root, "app/main.py", "x = 1\n")

    proposal = infer(root)
    assert any("ci/steps.yml" in q for q in proposal.questions), proposal.questions
    assert "NOT read" in " ".join(proposal.questions)


def test_a_readable_ci_file_still_counts_as_read(tmp_path: Path):
    """POSITIVE TWIN. "An unparseable file is not counted" also passes when NOTHING is counted."""
    root = tmp_path / "fine"
    root.mkdir()
    _git(root)
    _write(root, ".github/workflows/ci.yml", GH_CI)
    _write(root, "package.json", '{\n  "scripts": { "test": "node --test" }\n}\n')

    proposal = infer(root)
    assert proposal.ci_files_read == [".github/workflows/ci.yml"]
    assert proposal.ci_files_seen == []


@pytest.mark.parametrize(
    "rel,text",
    [
        # `jobs:`/`phases:` as a LIST. Both readers said `(doc.get(...) or {}).items()`, which
        # raises AttributeError — a Python traceback on the screen, in the room, from the one
        # command whose entire promise is that it degrades to "I could not read your CI".
        (".circleci/config.yml", "version: 2.1\njobs:\n  - build\n  - test\n"),
        ("buildspec.yml", "version: 0.2\nphases:\n  - install\n  - build\n"),
        (".gitlab-ci.yml", "stages:\n  - test\n"),
        (".travis.yml", "language: python\nscript: pytest -q\n"),
        ("azure-pipelines.yml", "trigger:\n  - main\n"),
    ],
)
def test_a_malformed_ci_document_degrades_instead_of_crashing_the_workshop(rel, text, tmp_path):
    root = tmp_path / re.sub(r"[^a-z0-9]+", "-", rel.lower())
    root.mkdir()
    _git(root)
    _write(root, rel, text)
    _write(root, "app/main.py", "x = 1\n")

    proposal = infer(root)  # must not raise
    assert proposal.fields["base_branch"].value == "main", "the rest of the read still answered"


@pytest.mark.parametrize(
    "rel,text",
    [
        (".circleci/config.yml", "version: 2.1\njobs:\n  - build\n  - test\n"),
        ("buildspec.yml", "version: 0.2\nphases:\n  - install\n  - build\n"),
        (".github/workflows/ci.yml", "name: ci\non:\n  pull_request:\njobs:\n  - t\n"),
    ],
)
def test_a_ci_file_that_parses_but_is_not_a_shape_we_walk_is_also_not_read(rel, text, tmp_path):
    """PARSING IS NOT UNDERSTANDING, and the first fix stopped one line short of this.

    These documents load perfectly into a dict, so a "did it parse?" gate passes them; the reader
    then finds nothing it can walk and returns `[]`, which is byte-for-byte what a pipeline with
    no commands returns. Measured through `sdlc env read` itself, after the parse gate landed:
    *"no test command anywhere … (CI read: .circleci/config.yml)"* — the same sentence, about the
    same file, for the opposite reason.
    """
    root = tmp_path / ("shape-" + re.sub(r"[^a-z0-9]+", "-", rel.lower()))
    root.mkdir()
    _git(root)
    _write(root, rel, text)
    _write(root, "app/main.py", "x = 1\n")

    proposal = infer(root)
    assert rel not in proposal.ci_files_read, proposal.ci_files_read
    assert rel in proposal.ci_files_seen
    assert f"CI read: {rel}" not in proposal.fields["validate.test"].note


def test_a_repository_whose_ci_we_failed_to_read_is_never_told_it_has_no_ci(tmp_path: Path):
    """"…and no CI file at all" is a CLAIM ABOUT THE CLIENT, and it was built from the read-list
    alone — so a repository whose only pipeline we failed to read was told it had none, in the one
    sentence a client is most likely to argue with. Three cases, three sentences."""
    root = tmp_path / "unread-ci"
    root.mkdir()
    _git(root)
    _write(root, ".github/workflows/ci.yml", BROKEN_WORKFLOW)
    _write(root, "app/main.py", "x = 1\n")

    note = infer(root).fields["setup"].note
    assert "no CI file at all" not in note, note
    assert "could NOT be read" in note and ".github/workflows/ci.yml" in note

    bare = tmp_path / "genuinely-no-ci"
    bare.mkdir()
    _git(bare)
    _write(bare, "app/main.py", "x = 1\n")
    assert "no CI file at all" in infer(bare).fields["setup"].note, "the true case must still say so"


def test_a_ci_file_whose_command_key_is_simply_absent_is_still_read(tmp_path: Path):
    """THE FALSE-ALARM TWIN. Only a key that is PRESENT and of the wrong TYPE means "we could not
    read this". A workflow with no `jobs:` at all is a different file, not a broken one, and
    calling it unreadable trades a false silence for a false alarm."""
    root = tmp_path / "no-jobs-key"
    root.mkdir()
    _git(root)
    _write(root, ".github/workflows/ci.yml", "name: reusable\non:\n  workflow_call:\n")
    _write(root, "app/main.py", "x = 1\n")

    proposal = infer(root)
    assert ".github/workflows/ci.yml" in proposal.ci_files_read
    assert ".github/workflows/ci.yml" not in proposal.ci_files_seen


# --- 8b. a gate we SYNTHESISE must not be one that rewrites the tree or never returns -----


def test_a_watch_or_fix_script_is_never_promoted_to_a_gate(tmp_path: Path):
    """The one place this module does not READ a command but BUILDS one, and the only place it can
    propose something actively destructive.

    `npm run lint:fix` rewrites the client's working tree; `npm run test:watch` never returns. The
    platform runs `validate:` commands inside the sandbox on every ticket. Before this guard, a
    `package.json` listing those variants FIRST produced both of them as `observed` — the strongest
    tier — because candidates at the same rank were ordered by line number alone.
    """
    root = tmp_path / "npm-variants"
    root.mkdir()
    _git(root)
    _write(root, "package.json", """{
  "name": "x",
  "scripts": {
    "test:watch": "vitest --watch",
    "test": "vitest run",
    "lint:fix": "eslint . --fix",
    "lint": "eslint ."
  }
}
""")
    _write(root, "package-lock.json", "{}\n")

    fields = infer(root).fields
    assert fields["validate.test"].value == "npm test"
    assert fields["validate.lint"].value == "npm run lint"
    for field in ("validate.test", "validate.lint"):
        for candidate in fields[field].candidates:
            assert "watch" not in str(candidate.value), candidate
            assert "fix" not in str(candidate.value), candidate


def test_a_scripts_own_body_can_disqualify_it_even_under_an_innocent_name(tmp_path: Path):
    """`"test": "jest --watchAll"` is named `test` and still never returns. The name is not the
    only evidence in the file — the body is right there."""
    root = tmp_path / "innocent-name"
    root.mkdir()
    _git(root)
    _write(root, "package.json",
           '{\n  "name": "x",\n  "scripts": { "test": "jest --watchAll" }\n}\n')
    _write(root, "package-lock.json", "{}\n")

    assert infer(root).fields["validate.test"].confidence == UNKNOWN


def test_an_exact_named_script_outranks_a_variant_at_the_same_rank(tmp_path: Path):
    """POSITIVE TWIN for the precedence tie-break: `test:e2e` is neither destructive nor
    non-terminating, so it stays — it just must not WIN over the script actually called `test`,
    whatever order the author typed them in. `test:e2e` needs a deployed environment nobody has
    mentioned yet."""
    root = tmp_path / "e2e-first"
    root.mkdir()
    _git(root)
    _write(root, "package.json",
           '{\n  "name": "x",\n  "scripts": {\n    "test:e2e": "playwright test",\n'
           '    "test": "vitest run"\n  }\n}\n')
    _write(root, "package-lock.json", "{}\n")

    test = infer(root).fields["validate.test"]
    assert test.value == "npm test"
    assert any("e2e" in str(c.value) for c in test.candidates), "the variant is still reported"


def test_a_makefile_excerpt_is_the_cited_line_verbatim(tmp_path: Path):
    """`Evidence.excerpt` says verbatim, and a reviewer reads the excerpt rather than opening the
    file. Measured on a client repository: an `install:` target carrying `##` help text was cited
    as `install:` — the excerpt did not match the line it pointed at, and the half that was
    stripped was the half that said what the target does."""
    root = tmp_path / "helped-makefile"
    root.mkdir()
    _git(root)
    _write(root, "Makefile", "install: ## Install the CLI into ~/.local/bin\n\tcp x ~/.local/bin\n")
    _write(root, "app/main.py", "x = 1\n")

    setup = infer(root).fields["setup"]
    evidence = setup.evidence[0]
    line = (root / "Makefile").read_text().splitlines()[evidence.line - 1]
    assert evidence.excerpt == line.strip(), evidence.excerpt


# --- 8c. the shape the action layer resolves ---------------------------------------------


def test_the_package_hands_back_the_function_that_carries_the_whole_report():
    """A REACHABILITY GUARD, and it pins something that looks like an accident.

    `openfactory/onboarding/__init__.py` re-exports a FUNCTION named `infer`, shadowing the submodule of
    the same name. `openfactory/actions/catalog.py::_entry_point` resolves `propose` → `infer` → "is it
    callable?", so with the function bound on the package it lands on `infer()` and `sdlc env read`
    receives the rich object — the only shape carrying `cannot_express`, `questions`, `stacks` and
    `unreadable_dirs`, which is the entire client-2 block of the report. Remove the re-export to
    "disambiguate" the name and the resolver falls through to `propose()`, whose flat shape cannot
    express any of them: the block vanishes from the report with every other test still green.
    """
    import openfactory.onboarding as package

    assert callable(package.infer) and not isinstance(package.infer, types.ModuleType)
    rich = package.infer(Path(__file__).resolve().parents[1])
    for attribute in ("cannot_express", "questions", "stacks", "unreadable_dirs", "not_attempted"):
        assert hasattr(rich, attribute), attribute
    # and the flat adapter is still reachable by name, for a caller that wants JSON
    from openfactory.onboarding.infer import propose as flat

    assert flat is propose


# --- 9. the call site --------------------------------------------------------------------


def test_propose_returns_the_flat_shape_the_action_layer_consumes(ado_repo: Path):
    """A capability nothing reaches does not exist — roughly twenty-one shipped occurrences of that
    class say so. `sdlc env read` consumes `{field: {value, source, confidence, note}}`, and this
    is the function it calls; without it `infer` is a module the platform imports nowhere."""
    fields = propose(ado_repo)
    assert set(fields) >= {"base_branch", "setup", "validate.test", "validate.lint", "components"}
    for name, field in fields.items():
        assert set(field) == {"value", "source", "confidence", "note"}, name
        assert field["confidence"] in (OBSERVED, INFERRED, UNKNOWN), name
        if field["confidence"] == UNKNOWN:
            # `is None`, not `in (None, {}, [])`. An empty container under an `unknown` tier is
            # the None/empty collapse this module exists to refuse, and a permissive assertion
            # here is how it survived: `components` returned `{}` and this test stayed green.
            assert field["value"] is None, f"{name} claims a value it does not know"
            assert field["note"], f"{name} refuses without saying why"
        else:
            assert field["source"], f"{name} is proposed with no citation"


def test_propose_flattens_components_one_key_per_attribute(tmp_path: Path):
    root = tmp_path / "poly"
    root.mkdir()
    _git(root)
    _write(root, "api/pyproject.toml", "[project]\nname='api'\nversion='0'\n")
    _write(root, "web/package.json", '{\n  "scripts": { "test": "node --test" }\n}\n')
    _write(root, "web/package-lock.json", "{}\n")

    fields = propose(root)
    assert fields["components.api.path"]["value"] == "api/**"
    assert fields["components.api.stack"]["value"] == "python"
    assert fields["components.web.stack"]["value"] == "node"


# --- 10. base_branch, and the tier that separates the two ways to read it ------------------


def test_the_remotes_default_branch_outranks_whatever_is_checked_out(tmp_path: Path):
    """Run this mid-feature and the honest reading of `.git/HEAD` is `feature/whatever`. The remote
    is a statement by the forge; the working copy is a fact about one laptop."""
    root = tmp_path / "midfeature"
    root.mkdir()
    _git(root, origin_head="develop", head="feature/x")
    _write(root, "a.py", "x = 1\n")

    base = infer(root).fields["base_branch"]
    assert base.value == "develop"
    assert base.confidence == OBSERVED
    assert "develop" in base.note and "feature/x" in base.note


def test_without_a_remote_head_the_checked_out_branch_is_inferred_not_observed(tmp_path: Path):
    root = tmp_path / "noremote"
    root.mkdir()
    _git(root, origin_head=None, head="main")
    _write(root, "a.py", "x = 1\n")

    base = infer(root).fields["base_branch"]
    assert base.value == "main"
    assert base.confidence == INFERRED, "a working copy's branch is not a statement about PRs"


def test_a_worktree_is_read_through_its_gitdir_pointer(tmp_path: Path):
    """This platform runs its own jobs in git worktrees, so `.git` being a FILE is the common case
    here — and a reader that assumes a directory reports "not a git repository" on exactly the
    checkouts the factory produces."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, origin_head="main", head="main")

    tree = tmp_path / "wt"
    tree.mkdir()
    gitdir = main / ".git" / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "HEAD").write_text("ref: refs/heads/job-42\n")
    (gitdir / "commondir").write_text("../..\n")
    (tree / ".git").write_text(f"gitdir: {gitdir}\n")
    _write(tree, "a.py", "x = 1\n")

    base = infer(tree).fields["base_branch"]
    assert base.value == "main", "the worktree's shared remote ref was not followed"
    assert base.confidence == OBSERVED


# --- 11. the real fixtures, when they are present -----------------------------------------


@pytest.mark.skipif(not REAL_FIXTURES.is_dir(), reason="the toy projects are not on this machine")
@pytest.mark.parametrize(
    "name,expected_test,expected_setup",
    [
        ("fx-ado", "python -m pytest -q", ["python -m pip install --quiet pytest"]),
        ("fx-dsk-flows", "dotnet test tests/Flows.Tests.csproj --nologo -v quiet",
         ["dotnet restore tests/Flows.Tests.csproj"]),
        ("fx-dsk-ui", "npm test", []),
        ("fx-jira", "npm test", []),
        ("fx-dotnet", "dotnet test tests/Orders.Tests.csproj --nologo -v quiet",
         ["dotnet restore tests/Orders.Tests.csproj"]),
    ],
)
def test_the_real_toy_projects_get_the_command_their_humans_wrote(name, expected_test,
                                                                 expected_setup):
    """Measured against the hand-written `.sdlc/project.yaml` in each toy project — a manifest a
    human wrote and the platform has run real jobs against."""
    repo = REAL_FIXTURES / name
    if not repo.is_dir():
        pytest.skip(f"{name} is not present")
    proposal = infer(repo)
    assert proposal.fields["validate.test"].value == expected_test
    assert proposal.fields["setup"].value == expected_setup


@pytest.mark.skipif(not REAL_FIXTURES.is_dir(), reason="the toy projects are not on this machine")
def test_the_inexpressible_stacks_are_the_ones_conformance_actually_refuses():
    """The `CANNOT EXPRESS` block is not a rhetorical flourish: `py-serverless` and `dotnet-func`
    ship hand-written manifests that `conformance.check` REFUSES, for exactly the stacks this
    module predicts. The prediction is checked against the refusal, not against an opinion."""
    from openfactory.policy.conformance import check

    for name, stack in (("py-serverless", "sam"), ("dotnet-func", "dotnet")):
        repo = REAL_FIXTURES / name
        if not (repo / namespace.MANIFEST).is_file():
            pytest.skip(f"{name} is not present")
        proposal = infer(repo)
        assert any(stack in entry for entry in proposal.cannot_express), (
            f"{name}: {stack} was not declared inexpressible"
        )
        human = Manifest.model_validate(yaml.safe_load((repo / namespace.MANIFEST).read_text()))
        errors = [i.message for i in check(human, repo).issues if i.level == "error"]
        assert any(stack in message for message in errors), (
            f"{name}: conformance did not actually refuse {stack} — the prediction is unfounded"
        )
