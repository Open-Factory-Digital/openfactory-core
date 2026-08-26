"""What the project's CI runs, against what its manifest declares — every time (#176, #177).

`onboarding/infer.py` proposes a manifest in a room, on a day. Nothing ever compared the two
again: podbeam was onboarded with three validations, its CI later grew a fourth — a gate the
client wrote BECAUSE the defect it catches is invisible to local tests — and the factory went on
running three. A pull request went out carrying exactly that defect.

TWO DIRECTIONS, because both are drift: a check the pipeline runs and the manifest does not
declare, and a validation the manifest declares that no pipeline runs any more. A check that only
ever grows the list cannot see a client retiring something.

ADVISORY, NEVER A GATE. Some CI steps must not run in a box — a deploy, anything holding a secret,
a matrix setup — and deciding which is guessing the client's stack, which the floor rule forbids.

#177 IS HERE TOO because it is the same measurement. The reader was blind to every environment
runner but `npx`, so a Python project's own `uv run pytest` / `uv run ruff` / `uv run mypy` were
invisible: the pilot's proposal offered a Python backend `npm test -- --run` — the FRONTEND's
command — and the file running its four real checks read as a deploy pipeline, which then made
this check report the client's declared validations as retired.
"""

from __future__ import annotations

import textwrap
import types

import pytest

from openfactory.doctor import Probes, _ci_declared
from openfactory.onboarding.infer import classify, infer


def _probes(**over):
    base = dict(
        docker_running=lambda: (True, ""), harness_on_path=lambda kind: True,
        manifest=lambda: types.SimpleNamespace(validation={}),
        forge_reachable=lambda: (True, ""), board_columns=lambda: [],
        pickup_column=lambda: "TO-DO", requires_review=lambda: False,
        floor_enforced=lambda: True, harness_kind=lambda: "claude_code",
        product_link=lambda: None,
    )
    return Probes(**{**base, **over})


def _manifest(**validations):
    return lambda: types.SimpleNamespace(validation=dict(validations))


# ── 1. the difference is reported, in both directions ───────────────────────────────────────────

def test_a_check_the_CI_runs_and_the_manifest_does_not_declare_is_NAMED():
    found = {"Alembic single head": ("alembic heads | grep -c '(head)'",
                                     ".github/workflows/ci-tests.yml:21"),
             "test": ("uv run pytest tests/unit", ".github/workflows/ci-tests.yml:26")}

    got = _ci_declared(_probes(ci_checks=lambda: found,
                               manifest=_manifest(test="uv run pytest tests/unit")))

    assert "Alembic single head" in got.message
    assert "ci-tests.yml:21" in got.message, "the finding does not say where to look"
    assert got.ok, "a difference is a question for the client, never a refusal"


def test_and_a_validation_no_pipeline_RUNS_ANY_MORE_is_named_too():
    """The negative twin. A check that only grows the list cannot see a client retiring a step,
    and the factory then spends a box on a command their pipeline abandoned."""
    got = _ci_declared(_probes(
        ci_checks=lambda: {"test": ("uv run pytest", "ci.yml:10")},
        manifest=_manifest(test="uv run pytest", lint="uv run ruff check src")))

    assert "lint" in got.message and "no pipeline" in got.message


def test_a_manifest_that_MATCHES_its_pipeline_says_so_and_nothing_else():
    got = _ci_declared(_probes(
        ci_checks=lambda: {"test": ("uv run pytest tests/unit -q --no-cov", "ci.yml:10")},
        manifest=_manifest(test="uv run pytest tests/unit")))

    assert got.ok and "every check" in got.message
    assert "will not run" not in got.message


def test_a_narrower_declared_SPELLING_is_not_reported_as_a_difference():
    """A manifest routinely carries a shorter form of what CI runs. Reporting that pair as a gap
    would make this noise on its first run, and a check nobody believes is worse than none."""
    got = _ci_declared(_probes(
        ci_checks=lambda: {"test": ("uv  run   pytest   tests/unit  -q", "ci.yml:10")},
        manifest=_manifest(test="uv run pytest tests/unit")))

    assert got.ok and "will not run" not in got.message, got.message


# ── 2. the three answers, and the middle one ────────────────────────────────────────────────────

def test_a_CI_this_deployment_cannot_READ_is_not_a_CI_that_agrees():
    """`None` is "I could not look". Collapsing it into `{}` tells a client whose pipeline we
    never opened that it matches — the reassurance this check exists to stop giving."""
    got = _ci_declared(_probes(ci_checks=lambda: None, manifest=_manifest(test="pytest")))

    assert got.ok
    assert "could not read" in got.message
    assert "nobody looked at" in got.note


def test_and_a_project_with_NO_ci_is_a_different_sentence():
    got = _ci_declared(_probes(ci_checks=lambda: {}, manifest=_manifest(test="pytest")))

    assert got.ok and "no CI was found" in got.message


def test_a_manifest_that_will_not_load_is_downstream_not_a_finding_of_its_own():
    def _raise():
        raise FileNotFoundError("no manifest")

    got = _ci_declared(_probes(ci_checks=lambda: {"t": ("pytest", "ci.yml:1")}, manifest=_raise))

    assert not got.ok and got.awaiting == "manifest"


# ── 3. #177 — the runner prefixes, which is what made any of this readable ──────────────────────

@pytest.mark.parametrize("command,role", [
    ("uv run pytest", "test"),
    ("uv run ruff check src tests", "lint"),
    ("uv run mypy src", "type"),
    ("uv run bandit -c pyproject.toml -r src", "security"),
    ("poetry run pytest -q", "test"),
    ("pipenv run pytest", "test"),
    ("pdm run pytest", "test"),
    ("hatch run pytest", "test"),
    ("bundle exec rubocop", "lint"),
    ("pnpm exec eslint .", "lint"),
    ("npx eslint .", "lint"),
    ("dotnet tool run dotnet-format --check", ""),
])
def test_a_tool_run_through_its_environment_is_still_that_tool(command, role):
    assert classify(command) == role, f"{command!r} read as {classify(command)!r}"


@pytest.mark.parametrize("command,role", [
    # THE CANARY THIS TABLE'S ANCHORING EXISTS FOR must survive the new stripping.
    ("python -m pip install --quiet pytest", "setup"),
    ("uv sync --all-extras --group dev", "setup"),
    ("uv python install 3.11", "setup"),
    # NOT TRANSPARENT LAUNCHERS: an alias whose recipe we cannot see, and a service the box does
    # not start. Both have their own handling and neither may be stripped.
    ("docker compose run api pytest", ""),
    ("echo pytest would run here", ""),
])
def test_but_a_prefix_that_is_not_a_LAUNCHER_is_not_stripped(command, role):
    assert classify(command) == role


def test_the_stripping_never_reaches_the_VALUE(tmp_path):
    """`pytest` without its `uv run` does not run in the box. The prefix is removed to ask what
    the command IS; what is proposed is the line the client's own file states."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(textwrap.dedent("""\
        name: CI
        on: [push]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - run: uv run pytest tests/unit
        """))
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "acme"\nversion = "0"\n')

    proposed = infer(tmp_path).fields["validate.test"].value

    assert proposed == "uv run pytest tests/unit", proposed


def test_a_python_project_is_not_offered_the_FRONTENDS_test_command(tmp_path):
    """The measured cost of the blindness, as a property. podbeam runs `uv run pytest` in CI and
    was proposed `npm test -- --run`, because only the JavaScript half could be read."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(textwrap.dedent("""\
        name: CI
        on: [push]
        jobs:
          backend:
            runs-on: ubuntu-latest
            steps:
              - run: uv run pytest tests/unit -q
          frontend:
            runs-on: ubuntu-latest
            steps:
              - run: npm ci
              - run: npm test -- --run
        """))
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "acme"\nversion = "0"\n')

    got = infer(tmp_path).fields["validate.test"]

    assert "pytest" in str(got.value), (
        f"a Python project was offered {got.value!r} as its test command")


def test_and_the_file_running_those_checks_is_seen_as_a_CHECK_file(tmp_path):
    """What made this check report a client's own declared validations as retired: the pipeline
    running four `uv run` checks yielded no role, so it read as a deploy pipeline."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(textwrap.dedent("""\
        name: CI
        on: [push]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - run: uv run pytest tests/unit
        """))
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "acme"\nversion = "0"\n')

    assert infer(tmp_path).ci_files_with_checks == [".github/workflows/ci.yml"]


def test_the_verbatim_reading_is_not_the_PROPOSAL(tmp_path):
    """`fields` carries the one command this pass would RECOMMEND per role, normalised and
    ranked. `ci_commands` carries what the pipelines actually run. Comparing a manifest against
    recommendations reported three false gaps in EACH direction on the pilot at once."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(textwrap.dedent("""\
        name: CI
        on: [push]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - run: uv run pytest tests/unit -q --no-cov
              - run: npm test -- --run
        """))
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "acme"\nversion = "0"\n')

    read = {str(c.value) for c in infer(tmp_path).ci_commands}

    assert "uv run pytest tests/unit -q --no-cov" in read
    assert "npm test -- --run" in read, "only the winner survived; the other command vanished"


# ── 4. the PROBE, which is what connects the two halves ─────────────────────────────────────────
#
# Every guard above drives `_ci_declared` with a hand-built dict, or `infer` on its own. Four
# mutations to the probe between them survived all of it — the seam nobody exercised, which is
# this repository's signature defect wearing a test suite.

def _repo_with(tmp_path, files: dict[str, str]):
    for rel, body in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body))
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "acme"\nversion = "0"\n')
    return tmp_path


CHECKS_YML = """\
    name: CI
    on: [push]
    jobs:
      test:
        runs-on: ubuntu-latest
        steps:
          - run: uv sync --all-extras
          - run: uv run pytest tests/unit -q
          - name: Schema drift check
            run: |
              alembic heads | grep -c '(head)'
    """

DEPLOY_YML = """\
    name: Deploy
    on: [push]
    jobs:
      ship:
        runs-on: ubuntu-latest
        steps:
          - name: Sync deploy files to S3
            run: aws s3 cp compose.yml s3://bucket/
    """


def _probe(tmp_path, monkeypatch):
    from openfactory import doctor

    monkeypatch.setattr("openfactory.factory.resolve_repo_path", lambda project, **k: tmp_path)
    return doctor.probes_for(types.SimpleNamespace(name="acme")).ci_checks()


def test_the_probe_reads_the_checkout_and_returns_what_the_PIPELINES_run(tmp_path, monkeypatch):
    got = _probe(_repo_with(tmp_path, {".github/workflows/ci.yml": CHECKS_YML}), monkeypatch)

    assert got is not None
    values = {command for command, _where in got.values()}
    assert "uv run pytest tests/unit -q" in values, values
    assert any("alembic heads" in v for v in values), values


def test_and_it_leaves_out_SETUP_which_the_manifest_declares_elsewhere(tmp_path, monkeypatch):
    """Reporting `uv sync` as an undeclared validation sends somebody to fix a file already
    right — `setup:` is its own manifest field."""
    got = _probe(_repo_with(tmp_path, {".github/workflows/ci.yml": CHECKS_YML}), monkeypatch)

    assert not any("uv sync" in command for command, _w in got.values()), got


def test_and_it_leaves_out_a_pipeline_that_carries_no_CHECK(tmp_path, monkeypatch):
    got = _probe(_repo_with(tmp_path, {".github/workflows/ci.yml": CHECKS_YML,
                                       ".github/workflows/deploy.yml": DEPLOY_YML}), monkeypatch)

    assert not any("aws s3" in command for command, _w in got.values()), got
    assert not any("deploy.yml" in where for _c, where in got.values()), got


def test_and_it_keeps_BOTH_commands_when_two_pipelines_run_two_suites(tmp_path, monkeypatch):
    """The proposal keeps one winner per role; this question needs every command. Reading the
    proposal instead reported three false gaps in each direction on the pilot at once."""
    got = _probe(_repo_with(tmp_path, {".github/workflows/ci.yml": CHECKS_YML,
                                       ".github/workflows/js.yml": """\
        name: JS
        on: [push]
        jobs:
          web:
            runs-on: ubuntu-latest
            steps:
              - run: npm test -- --run
        """}), monkeypatch)

    values = {command for command, _where in got.values()}
    assert "uv run pytest tests/unit -q" in values and "npm test -- --run" in values, values


def test_a_checkout_this_deployment_cannot_REACH_answers_None(tmp_path, monkeypatch):
    """`None` is "I could not look" — the answer `_ci_declared` turns into "nobody looked at it"
    rather than into "your CI agrees"."""
    from openfactory import doctor

    monkeypatch.setattr("openfactory.factory.resolve_repo_path",
                        lambda project, **k: tmp_path / "nowhere")

    assert doctor.probes_for(types.SimpleNamespace(name="acme")).ci_checks() is None


def test_a_pipeline_whose_only_check_is_a_TYPE_check_still_counts(tmp_path):
    """The role table says `type`; the manifest key is `types`. A set written in the manifest's
    spelling matches nothing — and it fails SILENTLY, by making every file look like a deploy
    pipeline. Every other fixture here runs a test too, so only a type-only pipeline can see it."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "types.yml").write_text(textwrap.dedent("""\
        name: Types
        on: [push]
        jobs:
          check:
            runs-on: ubuntu-latest
            steps:
              - run: uv run mypy src
              - name: Schema drift check
                run: alembic heads | grep -c '(head)'
        """))
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "acme"\nversion = "0"\n')

    assert infer(tmp_path).ci_files_with_checks == [".github/workflows/types.yml"]
