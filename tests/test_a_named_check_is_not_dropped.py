"""A command the client's CI runs that fills none of our roles is PROPOSED, not dropped (#175).

Measured on the pilot. podbeam declares three validations; its own `ci-tests.yml` runs those
three verbatim plus a fourth the client wrote with this comment:

    # A second Alembic head silently passes local tests (they use create_all) but
    # breaks the prod migrate step. Fail the build before it ever deploys.

`onboarding/infer.py` READ that file — it is first in `ci_files_read` — found no role for the
line, and dropped it. A pull request then went out carrying exactly the defect that gate exists to
stop, our reviewer rejected it, and a human had to decide at a gate.

NOTHING HERE IS ABOUT ALEMBIC. `classify()` answers a fixed vocabulary — test, lint, security —
while `Manifest.validation` is `dict[str, str | Gate]` and takes any key. The reader had the
closed vocabulary and the thing it fills is open. The same line vanishes for a `dotnet format
--verify-no-changes`, an `mvn enforcer:enforce`, a `dbt compile`, a `terraform validate`.

THE BOUNDARIES ARE THE DESIGN, and both were found by measuring rather than by reasoning:
  * the KEY is the name the client's own CI gave the step — a validation needs a key, they wrote
    one, and inventing a name for somebody else's gate is how a proposal stops being reviewable;
  * the VALUE is the whole step, not a fragment — the first version proposed
    `run alembic heads 2>/dev/null | grep -c '(head)')`, cut at the `$(`, unrunnable;
  * it is read only from a FILE THAT ALREADY GAVE US A ROLE — without that, ten of seventeen
    proposals were deploy plumbing and the one that mattered was buried in them.
"""

from __future__ import annotations

import textwrap

import pytest

from openfactory.onboarding.infer import NAMED_CHECK, classify, infer, slug_for

#: The pilot's own workflow, verbatim in shape: a role command, the named gate, another role
#: command. Written out rather than dedented — mixing an indented block into a dedented f-string
#: produced YAML that parsed to nothing, and a fixture that silently describes no CI at all makes
#: every assertion below pass for the wrong reason.
CI = """name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: uv run ruff check src tests
      - name: Alembic single head
        run: |
          heads=$(uv run alembic heads 2>/dev/null | grep -c '(head)')
          test "$heads" -eq 1
      - run: python -m pytest -q
"""


def _repo(tmp_path, workflows: dict[str, str]):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    for name, body in workflows.items():
        (tmp_path / ".github" / "workflows" / name).write_text(textwrap.dedent(body))
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "acme"\nversion = "0"\n')
    return tmp_path


def _validate(proposal) -> dict[str, str]:
    return {k.split(".", 1)[1]: p.value for k, p in proposal.fields.items()
            if k.startswith("validate.") and p.value}


# ── 1. it survives, keyed by the client's own name ──────────────────────────────────────────────

def test_a_named_check_reaches_the_proposal(tmp_path):
    got = _validate(infer(_repo(tmp_path, {"ci.yml": CI})))

    assert "alembic-single-head" in got, (
        f"the client's own gate was dropped; proposed: {sorted(got)}")


def test_and_its_value_is_the_WHOLE_step_so_it_can_actually_run(tmp_path):
    """The first version shredded the block and proposed the fragment before the `$(` — a value
    that cannot run, presented as an answer."""
    got = _validate(infer(_repo(tmp_path, {"ci.yml": CI})))["alembic-single-head"]

    assert "grep -c '(head)')" in got and 'test "$heads" -eq 1' in got, got
    assert got.count("\n") >= 1, "the step was flattened to one of its lines"


def test_and_it_carries_where_it_was_read_from(tmp_path):
    proposal = infer(_repo(tmp_path, {"ci.yml": CI}))
    field = proposal.fields["validate.alembic-single-head"]

    assert field.evidence and field.evidence[0].path == ".github/workflows/ci.yml"
    assert field.evidence[0].line
    assert field.confidence == "observed"
    assert "fills none of the roles" in field.note, (
        "the proposal does not tell the reader why it is being asked about this")


# ── 2. what it must NOT propose ─────────────────────────────────────────────────────────────────

def test_a_step_our_roles_ALREADY_cover_is_not_asked_twice(tmp_path):
    """A step named "Run tests" whose command is the one `validate.test` carries must not arrive
    under two keys — a proposal that asks one question in two places is one nobody finishes.

    IT HOLDS BY CONSTRUCTION, and that is worth stating rather than defending with a filter:
    `classify()` is consulted first, so a command with a role is never a named check. The first
    version of the production code carried a set to exclude them; removing it changed nothing,
    which is how the set was found to be unreachable."""
    got = _validate(infer(_repo(tmp_path, {"ci.yml": """\
        name: CI
        on: [push]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - name: Run tests
                run: python -m pytest -q
        """})))

    assert "run-tests" not in got, f"the test command was proposed twice: {sorted(got)}"


def test_an_ANONYMOUS_command_is_not_given_a_name_we_invented(tmp_path):
    """A validation needs a key. Where the client wrote none there is none to take, and minting
    one from a job name would put every anonymous line of a deploy pipeline into the proposal."""
    # THE JOB IS NAMED `checks`, NOT `test`, ON PURPOSE. The plausible wrong fix substitutes the
    # JOB name for the missing step name — and with a job called `test` the invented key collides
    # with a field we already proposed, is skipped, and the guard passes while the code is wrong.
    # A job name that is not one of our roles is what makes the substitution visible.
    got = _validate(infer(_repo(tmp_path, {"ci.yml": """\
        name: CI
        on: [push]
        jobs:
          checks:
            runs-on: ubuntu-latest
            steps:
              - run: python -m pytest -q
              - run: ./scripts/whatever.sh --strict
        """})))

    # THE ASSERTION IS ON THE KEY SET, NOT ON THE COMMAND TEXT. The first version looked for a
    # key derived from the script's filename, which no mutation of this code could ever produce:
    # falling back to the JOB name — the plausible wrong fix — keys it `test`, and the guard
    # passed. What must hold is that an anonymous command adds NO named check at all.
    assert set(got) <= {"test", "lint", "security", "types"}, (
        f"a name was invented for an anonymous command: {sorted(got)}")
    # AND THE FIELDS WE DID PROPOSE STILL SAY WHAT THEY SAID. Asserting only the key SET missed
    # the worse half: with the job name substituted for the step name, the anonymous command
    # slugged to `test` and REPLACED the client's real test command — a proposal that looks
    # correct, under a key we expect, carrying somebody's deploy script.
    assert got["test"] == "python -m pytest -q", got["test"]


def test_a_file_that_carries_NO_check_of_ours_contributes_nothing(tmp_path):
    """THE MEASUREMENT THAT SHAPED THIS. Without the rule, ten of seventeen proposals from the
    pilot were deploy plumbing — `aws s3 cp`, `ssm send-command`, an instance being started, a
    smoke test — every one of them a NAMED step, and the gate that mattered was among them.

    The discriminator is this module's own classification, not a filename and not an `on:`
    trigger: a file that yields a test, a lint or a scanner is where this project keeps its
    checks; one that yields none is something else, whatever it is called."""
    got = _validate(infer(_repo(tmp_path, {
        "ci.yml": CI,
        "deploy.yml": """\
        name: Deploy
        on: [push]
        jobs:
          ship:
            runs-on: ubuntu-latest
            steps:
              - name: Sync deploy files to S3
                run: aws s3 cp docker-compose.yml s3://bucket/
              - name: Deploy on EC2 via SSM
                run: aws ssm send-command --document-name AWS-RunShellScript
        """})))

    assert "alembic-single-head" in got
    for noise in ("sync-deploy-files-to-s3", "deploy-on-ec2-via-ssm"):
        assert noise not in got, f"deploy plumbing reached the proposal: {sorted(got)}"


# ── 3. the same fact in every vendor's spelling ─────────────────────────────────────────────────

def test_the_step_name_is_read_in_AZURES_spelling_too(tmp_path):
    """`displayName`. Threading this for GitHub alone would be #161 committed one layer up — a
    capability that exists for whichever provider somebody happened to be holding."""
    (tmp_path / "azure-pipelines.yml").write_text(textwrap.dedent("""\
        trigger: [main]
        steps:
          - script: python -m pytest -q
          - displayName: Schema drift check
            script: |
              alembic heads | grep -c '(head)'
        """))
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "acme"\nversion = "0"\n')

    got = _validate(infer(tmp_path))

    assert "schema-drift-check" in got, sorted(got)


def test_and_in_CIRCLECIS(tmp_path):
    """Its step name lives inside the `run:` mapping — the third spelling of one fact."""
    (tmp_path / ".circleci").mkdir()
    (tmp_path / ".circleci" / "config.yml").write_text(textwrap.dedent("""\
        version: 2.1
        jobs:
          build:
            steps:
              - run: python -m pytest -q
              - run:
                  name: Schema drift check
                  command: alembic heads | grep -c '(head)'
        """))
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "acme"\nversion = "0"\n')

    got = _validate(infer(tmp_path))

    assert "schema-drift-check" in got, sorted(got)


# ── 4. the primitives ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,key", [
    ("Alembic single head", "alembic-single-head"),
    ("  Schema drift  CHECK ", "schema-drift-check"),
    ("dotnet format --verify-no-changes", "dotnet-format-verify-no-changes"),
    ("", ""),
    ("---", ""),
])
def test_the_key_is_derived_from_the_clients_own_name(name, key):
    assert slug_for(name) == key


def test_classify_still_answers_EMPTY_for_a_command_in_no_role():
    """`""` means "I do not know what this is" — the caller decides what to do with that, and
    what changed in #175 is only the caller. A `classify` that started guessing roles would be a
    much worse fix than the defect."""
    assert classify("alembic heads | grep -c '(head)'") == ""
    assert classify("python -m pytest -q") == "test"
    assert NAMED_CHECK not in {classify("python -m pytest -q"), classify("echo hi")}
