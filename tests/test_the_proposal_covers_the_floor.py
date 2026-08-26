"""What the machine proposes must be able to pass the check the same onboarding runs next — #99.

`infer()` reads a repository and proposes a manifest. `doctor` then refuses a project whose
manifest does not declare every validation the platform's floor requires. Those are two halves of
one onboarding, and until this file nothing tied them together.

WHAT THAT COST, measured rather than imagined. `_ROLE_PATTERNS` carries a full security table —
bandit, pip-audit, semgrep, trivy, gitleaks, npm audit, snyk, tfsec — and `classify()` answers
`"security"` for every one of them. `infer()` built `validate.test` and `validate.lint` and
**never `validate.security`**, so the answer was computed and thrown away: no field, no question,
no entry in `not_attempted`. A proposal that could not pass `doctor`, silent about why.

And the suite did not notice. Adding the field back broke NOTHING — 5,304 tests green before and
after — because no test asserted which fields a proposal carries. That is the blindness that let
the gap live, and it is the reason the guard below is DERIVED from the floor rather than written
as a list: a list would have to be remembered by the same person who forgot.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from openfactory import namespace
from openfactory.onboarding.infer import classify, infer
from openfactory.policy import floor
from tests.demo_projects import demo_projects_root


def _repo(root: Path, files: dict[str, str]) -> Path:
    """A real git repository — `base_branch` is read from `.git`, so a bare directory would make
    every case here answer 'unknown' for a reason that has nothing to do with the test."""
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    subprocess.run(["git", "init", "-b", "main", "-q", str(root)], check=True)
    return root


# ── the class rule ──────────────────────────────────────────────────────────────────────────────

def test_the_floor_declares_the_roles_this_guard_derives_from():
    """The positive twin, first. Every assertion below is satisfied by a floor that requires
    nothing — and a derivation that quietly returns an empty set reads exactly like compliance."""
    assert {"test", "security"} <= set(floor.REQUIRED_VALIDATION_ROLES), (
        f"the floor requires {sorted(floor.REQUIRED_VALIDATION_ROLES)} — this guard derives its "
        f"whole subject from that list, and cannot mean anything if it is empty")


@pytest.mark.parametrize("role", sorted(floor.REQUIRED_VALIDATION_ROLES))
def test_every_gate_the_floor_REQUIRES_is_attempted_by_the_proposal(role, tmp_path):
    """A role the floor demands must appear in the proposal — as a value, or as an honest unknown
    carrying a question. What it may never be is ABSENT: a caller cannot tell "this repository
    says nothing about it" from "this pass does not look", and the two have opposite remedies.

    Derived from `REQUIRED_VALIDATION_ROLES`, so a role added to the floor tomorrow fails here the
    same day rather than being silently unproposed until a client's `doctor` refuses them.
    """
    repo = _repo(tmp_path / "quiet", {"README.md": "# nothing to go on\n"})

    proposal = infer(repo)
    field = f"validate.{role}"

    assert field in proposal.fields, (
        f"the floor requires a `{role}` validation and the proposal has no `{field}` at all — "
        f"neither a value nor an unknown. `doctor` will refuse the project this produced, and the "
        f"proposal said nothing about why")
    known = proposal.fields[field]
    if not known.known:
        assert known.note or any(role in q for q in proposal.questions), (
            f"`{field}` is unknown and nothing asks about it — the client is never told that the "
            f"floor needs it")


# ── behaviour: it reads the client's own pipeline ────────────────────────────────────────────────

_SCANNERS = ("bandit -r src", "python -m pip_audit --strict", "trivy fs .", "npm audit")


@pytest.mark.parametrize("scanner", _SCANNERS)
def test_a_security_command_in_the_clients_CI_is_PROPOSED_not_only_classified(scanner, tmp_path):
    """The half that was thrown away. `classify()` already answered `"security"` for each of these
    — the gap was that nothing consumed the answer, which is this repository's signature defect
    with the arrow pointing inward.

    Asserted per scanner, because a single case would pass on the one pattern somebody tested."""
    assert classify(scanner) == "security", f"the classifier stopped recognising {scanner!r}"

    repo = _repo(tmp_path / scanner.split()[0], {
        "README.md": "# app\n",
        ".github/workflows/ci.yml": (
            "on: [pull_request]\njobs:\n  ci:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: python -m pytest -q\n"
            f"      - run: {scanner}\n"
        ),
    })

    proposal = infer(repo)
    field = proposal.fields.get("validate.security")

    assert field is not None and field.known, (
        f"the client's own pipeline runs `{scanner}` and the proposal does not carry it: "
        f"{None if field is None else field.note}")
    assert scanner.split()[0] in str(field.value), (field.value, scanner)


def test_a_repository_with_no_scanner_is_ASKED_rather_than_given_one(tmp_path):
    """The other direction, and it is not symmetry for its own sake. Proposing a scanner nobody
    runs would hand a client a gate whose first act is to report the accumulated debt of their
    whole history — the exact failure `validate.lint` names one field up, and the first thing a
    client turns off.

    The question has to say the floor REQUIRES it, or the reader treats it as a preference and
    skips it — and then `doctor` refuses them for something they were never told about.
    """
    repo = _repo(tmp_path / "bare", {
        "README.md": "# app\n",
        ".github/workflows/ci.yml": (
            "on: [push]\njobs:\n  ci:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: python -m pytest -q\n"),
    })

    proposal = infer(repo)
    field = proposal.fields["validate.security"]

    assert not field.known, f"a scanner was invented where none is configured: {field.value}"
    asked = " ".join(proposal.questions) + " " + (field.note or "")
    assert "floor" in asked.lower() or "piso" in asked.lower(), (
        f"the question does not say the floor requires it, so it reads as a preference: {asked}")


# ── the fixtures are the ground truth, and they are used as one ─────────────────────────────────

# `demo_projects_root()`, NOT `demo_projects()`: at module scope the latter answers None where
# the toy projects are absent, and `None.is_dir()` at collection aborts the ENTIRE suite — the
# fifteen-day outage `tests/demo_projects.py` records. The root helper answers a path that exists
# nowhere, so the skip below happens at RUN time, per test, like everywhere else.
FIXTURES = demo_projects_root()


@pytest.mark.skipif(not FIXTURES.is_dir(), reason="the toy projects are not on this machine")
@pytest.mark.parametrize("name", ["py-simple", "fx-ado", "fx-dotnet", "fx-dsk-flows"])
def test_a_fixture_with_its_manifest_HIDDEN_still_gets_its_test_command(name, tmp_path):
    """The measurement that turns an impression into a number: the fixture carries the answer, so
    hide it and compare. These four are the ones whose test command is derivable from what the
    repository itself states — the scoring pass over all nine lives outside the suite, because a
    score is a report and not a pass/fail.

    SKIPPED LOUDLY when the toy projects are absent rather than passing for free: a guard that
    quietly does nothing on CI is the shape this file exists downstream of.
    """
    import yaml

    src = FIXTURES / name
    truth = yaml.safe_load((src / namespace.MANIFEST).read_text())
    expected = truth["validate"]["test"]

    work = tmp_path / name
    shutil.copytree(src, work, ignore=shutil.ignore_patterns(
        "__pycache__", "venv", "node_modules", ".pytest_cache"))
    shutil.rmtree(work / namespace.DIR)         # the answer is hidden

    proposal = infer(work)
    got = proposal.fields.get("validate.test")

    assert got is not None and got.known, f"{name}: no test command proposed at all"
    assert got.value.strip() == expected.strip(), (
        f"{name}: proposed {got.value!r}, the fixture's own manifest says {expected!r}")


# ── a command that is RIGHT for the team and unrunnable in the box ──────────────────────────────

def test_a_command_that_enters_a_RUNNING_service_is_flagged_not_translated(tmp_path):
    """FOUND ON A REAL PROJECT, and it is the ambiguity nobody planted.

    A working application's Makefile said `test: docker-compose exec api pytest tests/ -v`. That
    is correct for a developer with the stack up, it is the line their own file states, and this
    pass therefore reads it and proposes it at the highest confidence tier it has. It is also
    unrunnable where the platform runs it: the box mounts the repository into ONE container and
    starts no services.

    Two things are asserted, and the second matters as much as the first:

      the VALUE is not rewritten — translating `docker-compose exec api pytest tests/` into
      `pytest backend/tests` would invent a command nobody wrote, in the one field the whole run
      is gated on, and be silently wrong the first time the paths did not line up;

      the NOTE says so — without it, the first sign is `box prove` failing minutes later with the
      container runtime's own words ("no such service: api"), in front of the client, about a
      command they know works.
    """
    repo = _repo(tmp_path / "compose", {
        "README.md": "# app\n",
        "Makefile": "test:\n\tdocker-compose exec api pytest tests/ -v\n",
    })

    field = infer(repo).fields["validate.test"]

    assert field.value == "make test", (
        f"the entry point was rewritten: {field.value!r}. A make target is proposed by NAME so it "
        f"survives a change to the recipe")
    assert "ALREADY RUNNING" in (field.note or ""), (
        f"the proposal hides that this cannot run in the box: {field.note!r}")


def test_the_recipe_BEHIND_a_make_target_is_what_gets_read(tmp_path):
    """The half that made this invisible. A `make` target is proposed by NAME — deliberately, so
    it survives a change to the recipe — and that is exactly what hid `docker-compose exec` from
    every reader of the proposal: the value said `make test` and nothing carried what it runs.

    So the recipe travels with the command, for warning only. Asserted by the CONTRAST: the same
    Makefile shape, one target that enters a running service and one that does not.
    """
    repo = _repo(tmp_path / "both", {
        "README.md": "# app\n",
        "Makefile": "test:\n\tpython -m pytest -q\n\nlint:\n\tdocker compose exec api ruff check .\n",
    })

    fields = infer(repo).fields

    assert "ALREADY RUNNING" not in (fields["validate.test"].note or ""), (
        "a plain recipe was flagged as needing a running service — the guard cries wolf")
    assert "ALREADY RUNNING" in (fields["validate.lint"].note or ""), (
        f"the recipe behind `make lint` was not read: {fields['validate.lint'].note!r}")


def test_building_an_image_is_NOT_treated_as_entering_a_running_service(tmp_path):
    """The precision the warning needs to be worth reading. `docker build` and `docker run` bring
    their own container; only `exec` (and `compose run`) require one somebody else started. A
    guard that fired on the word "docker" would fire on half the repositories in the world and be
    ignored within a week."""
    repo = _repo(tmp_path / "build", {
        "README.md": "# app\n",
        "Makefile": "test:\n\tdocker build -t app . && docker run --rm app pytest -q\n",
    })

    field = infer(repo).fields["validate.test"]

    assert "ALREADY RUNNING" not in (field.note or ""), (
        f"`docker build`/`docker run` were flagged as needing a running service: {field.note!r}")


def test_the_warning_NAMES_a_candidate_that_would_run(tmp_path):
    """"Your command will not work" without "this one might" is homework, not onboarding. When the
    repository states another way to run the same role, the note names it — and says to check that
    it covers the same tests, because this pass cannot know that.

    THE ALTERNATIVE HAS TO RANK BELOW THE MAKEFILE, or there is nothing to warn about: a CI
    workflow OUTRANKS a make target, so a repository with a runnable command in its pipeline gets
    that one PROPOSED and never reaches this branch. Measured while writing this test — the first
    version put the alternative in `.github/workflows` and the tool simply picked the right
    command, which is the tool being correct and the test being wrong. A `Dockerfile` sits below
    the Makefile, which is exactly the shape the real project had."""
    repo = _repo(tmp_path / "alt", {
        "README.md": "# app\n",
        "Makefile": "test:\n\tdocker-compose exec api pytest tests/ -v\n",
        "Dockerfile": "FROM python:3.12\nRUN python -m pytest -q\n",
    })

    field = infer(repo).fields["validate.test"]

    assert "Another candidate does not" in (field.note or ""), field.note
    assert "python -m pytest -q" in (field.note or ""), field.note
