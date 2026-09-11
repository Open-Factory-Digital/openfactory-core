"""The end-to-end install's body is a script, and a script can be parsed, linted and run.

THREE VERSION NUMBERS WERE SPENT ON SHELL DEFECTS IN WORKFLOW STEPS THAT ONLY A TAG COULD EXECUTE:

  v0.1.1  a release asset attached with a leading dot, which GitHub renames to `default.…`
  v0.1.2  a dotfile guard written on a bare glob, which reported its own unexpanded pattern
  v0.1.4  a `docker run … sh -c '…'` block in which an apostrophe inside a COMMENT closed the
          single-quoted string:

              /home/runner/work/_temp/….sh: line 71: unexpected EOF while looking for matching `"'

          `\\'` escapes nothing inside single quotes. The installer never executed a line.

`scripts/collect-release-assets.sh` ended that class for the release assembly by moving it out of
YAML into a file `make lint` shellchecks and this suite runs. These are the same move for the job
that installs, and this file is the half that makes it worth anything: a script nothing executes is
a `run:` block with extra steps.

WHAT A MACHINE WITHOUT ACTIONS CAN CHECK, and it is more than it sounds: that the workflow really
invokes these files and nothing else; that they parse under `sh -n`; that they refuse by name when
their inputs are absent; that the quoting hazard cannot come back; and — where a daemon is present
— that the container the job builds really has Docker, really has no Python, and really reaches the
socket through a supplementary group. What it cannot check is a full install against a published
release, which needs the release; that is stated where it is skipped rather than left implied.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
E2E = ROOT / ".github" / "workflows" / "install-e2e.yml"

#: The three files the job is made of, and what each is for.
BODIES = {
    "e2e-install.sh": "prepares the shared directory and starts the container",
    "e2e-in-container.sh": "installs prerequisites and runs the installer as an unprivileged user",
    "e2e-verify.sh": "asserts a panel that answers and a preflight that speaks",
}

_HAS_SH = shutil.which("sh") is not None
_HAS_DOCKER = shutil.which("docker") is not None


def _steps() -> list[dict]:
    workflow = yaml.safe_load(E2E.read_text())
    return next(iter(workflow["jobs"].values()))["steps"]


def test_every_body_the_job_runs_is_a_file_in_this_tree():
    for name, purpose in BODIES.items():
        assert (SCRIPTS / name).is_file(), f"scripts/{name} is missing — it {purpose}"


def test_the_workflow_invokes_the_scripts_and_carries_no_inline_shell_of_its_own():
    """THE PROPERTY THE v0.1.4 FAILURE IS ABOUT. A `run:` that is one invocation of a file has
    nothing to quote; the block it replaced had fourteen quote characters across two nesting
    levels, which no reviewer catches by reading — I wrote it and did not."""
    runs = [str(step.get("run", "")) for step in _steps() if step.get("run")]
    assert runs, "the job runs nothing at all"

    invoked = {re.search(r"scripts/(\S+\.sh)", run).group(1)
               for run in runs if "scripts/" in run}
    assert invoked >= {"e2e-install.sh", "e2e-verify.sh"}, (
        f"the workflow does not invoke the scripts; it runs {invoked}")

    for run in runs:
        assert "sh -c" not in run, (
            f"the workflow has gone back to inline shell in a `sh -c` block, which is where the "
            f"v0.1.4 quoting failure lived: {run.strip()[:120]}")


def test_no_body_hides_an_apostrophe_escape_that_would_close_a_quoted_block():
    """THE EXACT CHARACTER SEQUENCE THAT BROKE v0.1.4, kept out of the files that replaced it.

    `\\'` is meaningless inside single quotes — it ends the string. It is harmless in a standalone
    script, which is the point, but it is also the tell that somebody has pasted YAML-era text back
    in; and if any of this ever returns to a `sh -c` block, that is exactly how it fails again."""
    for name in BODIES:
        text = (SCRIPTS / name).read_text()
        assert "\\'" not in text, (
            f"scripts/{name} contains a backslash-apostrophe. Inside a single-quoted block that "
            f"closes the string — it is what stopped v0.1.4 before the installer ran a line.")


@pytest.mark.skipif(not _HAS_SH, reason="no POSIX shell on this machine")
@pytest.mark.parametrize("name", sorted(BODIES))
def test_each_body_parses(name):
    """`sh -n` is the check the workflow could never get: the v0.1.4 block was syntactically broken
    and nothing said so until a tag ran it."""
    done = subprocess.run(["sh", "-n", str(SCRIPTS / name)],
                          capture_output=True, text=True, timeout=60)

    assert done.returncode == 0, f"scripts/{name} does not parse:\n{done.stderr}"


@pytest.mark.skipif(not _HAS_SH, reason="no POSIX shell on this machine")
def test_the_container_body_refuses_by_name_when_it_is_told_nothing():
    """It takes everything as environment rather than as interpolated text — which is what removes
    the quoting hazard — so the failure mode is an unset variable, and that must be a sentence
    rather than an empty expansion running `chown : /`."""
    done = subprocess.run(["sh", str(SCRIPTS / "e2e-in-container.sh")],
                          capture_output=True, text=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin"})

    assert done.returncode != 0, "it ran with no socket gid and no shared directory"
    assert "SOCKET_GID" in done.stderr, (
        f"the refusal does not name what is missing: {done.stderr[:300]}")


@pytest.mark.skipif(not _HAS_SH, reason="no POSIX shell on this machine")
def test_the_driver_refuses_when_there_is_no_socket_to_hand_over():
    """The other input it cannot invent. A missing socket used to be discovered inside the
    container, three steps later, as a daemon that would not answer."""
    done = subprocess.run(["sh", str(SCRIPTS / "e2e-install.sh")],
                          capture_output=True, text=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin", "OPENFACTORY_E2E_SOCKET": "/nope.sock",
                               # required since 2026-09-04 — the gate must know which release it
                               # tests, so it refuses on that first if it is not given one
                               "OPENFACTORY_E2E_VERSION": "v0.0.0-probe"})

    assert done.returncode != 0
    assert "no docker socket" in done.stderr, done.stderr[:300]


def test_the_verify_body_asserts_both_halves_of_the_claim():
    """A stack that starts and serves nothing is not an install; a preflight that names nothing is
    not a diagnosis. Read off the script, so it cannot quietly lose one."""
    text = (SCRIPTS / "e2e-verify.sh").read_text()
    instructions = "\n".join(line for line in text.splitlines()
                             if not line.lstrip().startswith("#"))

    assert "the panel never answered" in instructions, "nothing fails when the panel is silent"
    assert "openfactory.preflight/" in instructions, "the document's schema is not checked"

    # RUN, NOT SPELLED. This used to read `'finding["remedy"]' in instructions`, and it went red
    # when the check was rewritten from `finding["remedy"]` to `finding.get("remedy", "")` — a
    # rewrite that made the check STRONGER. The guard was matching a spelling of the property
    # rather than the property, so it could be broken by an improvement and satisfied by the
    # string appearing anywhere. Executing it can be neither.
    with tempfile.TemporaryDirectory() as scratch:
        done = _check_it(pathlib.Path(scratch), _MALFORMED["a red finding whose remedy is "
                                                           "whitespace"])
    assert done.returncode != 0, (
        "the preflight document is accepted without checking that its refusals carry remedies")


# ── what a daemon lets us prove, short of a published release ───────────────────────────────────

@pytest.mark.skipif(not (_HAS_DOCKER and _HAS_SH), reason="docker is not available here")
def test_the_container_the_job_builds_has_docker_and_no_python():
    """THE CLAIM THE WHOLE JOB EXISTS FOR, exercised without needing a release: `debian:12-slim`
    plus what the script installs must give a working `docker` and `docker compose`, and must NOT
    give a Python — if any step of the install needed a host interpreter it would fail there.

    This runs the real prerequisite block from `e2e-in-container.sh`; it stops before the installer,
    which needs a published release to install."""
    prelude = "\n".join(
        line for line in (SCRIPTS / "e2e-in-container.sh").read_text().splitlines()
        if not line.lstrip().startswith("#"))
    prelude = prelude[:prelude.index("groupadd")] + '\ndocker --version\necho E2E-PRELUDE-OK\n'

    done = subprocess.run(
        # `sh -s v0.0.0-probe` — the body takes the release under test as its first positional
        # now, and refuses without one.
        ["docker", "run", "--rm", "-i", "-e", "SOCKET_GID=1", "-e", "SHARED=/tmp/x",
         "debian:12-slim", "sh", "-s", "v0.0.0-probe"],
        input=prelude, capture_output=True, text=True, timeout=900)

    if done.returncode != 0 and "Cannot connect to the Docker daemon" in done.stderr:
        pytest.skip("the Docker daemon is not answering on this machine")
    assert "E2E-PRELUDE-OK" in done.stdout, (
        f"the container the job builds is not usable:\n{done.stdout[-800:]}\n{done.stderr[-800:]}")
    assert "Docker version" in done.stdout, done.stdout[-400:]


# ── the harness reads a file the product was right to protect ───────────────────────────────────

def test_the_verify_body_never_reads_the_credentials_file_and_never_loosens_it():
    """MEASURED ON THE v0.1.5 RUN, which installed successfully and then could not check itself:

        panel: up on :8787
        open /opt/openfactory-e2e/openfactory/.env.compose: permission denied

    The install runs as `installer`; this step runs as the runner's own user; `openfactory init`
    writes the file 0600 because it holds a forge credential and a harness token. The product was
    RIGHT and the harness was wrong — so the fix borrows the owner's identity rather than widening
    the mode, which is the one repair that would have left the credentials readable."""
    body = (SCRIPTS / "e2e-verify.sh").read_text()
    instructions = "\n".join(line for line in body.splitlines()
                             if not line.lstrip().startswith("#"))

    # THE PROPERTY GOT STRONGER TWICE. v0.1.5 read the file as the runner and could not (0600).
    # v0.1.6 borrowed the owner's uid with `sudo -n -u #1000` and that process could not reach the
    # docker socket — measured 2026-09-04: `sudo -u` PRESERVES supplementary groups, so the cause
    # was the uid itself. The file is owned by uid 1000 as created INSIDE the container, and on a
    # GitHub runner uid 1000 is `ubuntu` while the runner is `runner` at 1001. Borrowing a uid
    # across a container boundary borrows a number, not an identity.
    #
    # `docker compose exec` needs the PROJECT, not the credentials: `--project-directory` plus the
    # compose file's own `name:` is enough to find a running service. So the step reads nothing it
    # is not entitled to, which beats being entitled to read it.
    # `--env-file` WAS NEVER THE WHOLE PATH TO THE FILE, which is why dropping it in v0.1.7 left
    # v0.1.8 failing with the v0.1.5 message. `docker-compose.yml` declares `env_file:
    # .env.compose` itself, so COMPOSE reads it because the project asks — and `required: false`
    # covers absent, not present-and-unreadable. Reproduced locally with no `--env-file` anywhere:
    # `open …/.env.compose: permission denied`, exit 1.
    #
    # So the property is not "no --env-file" but "no compose at all": the worker is found through
    # compose's own container labels, which need no file and no credential. Measured: exit 0.
    assert "docker compose" not in instructions, (
        "the verify step goes through compose, which reads .env.compose because docker-compose.yml "
        "DECLARES it — no command-line change can prevent that")
    assert "com.docker.compose.service=worker" in instructions, (
        "the worker is not located by label, so something has to parse the project")
    assert "sudo" not in instructions, (
        "the verify step escalates to read something; it should not need to read anything")
    for loosening in ("chmod 6", "chmod 0644", "chmod a+r", "chmod 777"):
        assert loosening not in instructions, (
            f"the verify step widens the credentials file's mode ({loosening}) instead of "
            f"borrowing its owner — that is fixing the product to suit the harness")


def test_a_failed_preflight_command_is_a_sentence_and_not_a_traceback():
    """The other half of the same v0.1.5 failure: the empty output of the command that had just
    failed was fed to a JSON parser, which answered with

        json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

    `never a raw traceback` is this project's rule for anything a user can hit, and this is our own
    script breaking it about a file it could not read."""
    instructions = "\n".join(line for line in (SCRIPTS / "e2e-verify.sh").read_text().splitlines()
                             if not line.lstrip().startswith("#"))

    assert "-s " in instructions and "preflight.json" in instructions, (
        "nothing checks that the document is non-empty before parsing it")
    assert "die " in instructions, "the verify step has no way to refuse by name"
    assert "except (OSError, ValueError)" in instructions, (
        "the parser still lets an unreadable or truncated document raise a traceback")


def test_a_red_preflight_does_not_fail_the_job_because_a_CI_machine_has_no_credential():
    """CONFIRMING THIS IS BY DESIGN RATHER THAN BY ACCIDENT. The e2e machine has no Claude token,
    so `agent_credential` is red and `openfactory preflight` exits non-zero — which is the honest
    answer, and ONBOARDING calls that credential the one thing that cannot be postponed. What the
    job asserts is therefore not "preflight is green" but "preflight produced a document in the
    published shape, and every refusal in it carries a remedy"."""
    instructions = "\n".join(line for line in (SCRIPTS / "e2e-verify.sh").read_text().splitlines()
                             if not line.lstrip().startswith("#"))

    assert "|| true" in instructions, (
        "a non-zero preflight fails the job — on a machine that has no agent credential by "
        "construction, which would make the job impossible to pass rather than meaningful")
    # Executed rather than spelled, for the reason given in the guard above.
    with tempfile.TemporaryDirectory() as scratch:
        home = pathlib.Path(scratch)
        refused = _check_it(home, _MALFORMED["a red finding whose remedy is whitespace"])
        tolerated = _check_it(home, _A_GOOD_DOCUMENT, name="good.json")

    assert refused.returncode != 0, (
        "the job tolerates a red preflight without checking that its refusals carry remedies, "
        "which is the only thing that makes tolerating it safe")
    assert tolerated.returncode == 0, (
        "a red preflight whose refusals DO carry remedies fails the job, which no machine "
        "without an agent credential could ever pass")


# ── the gate must test the release it gates ─────────────────────────────────────────────────────

def test_the_job_refuses_to_run_without_being_told_which_release_to_test():
    """EVERY RUN OF THIS JOB BEFORE 2026-09-04 INSTALLED THE PREVIOUS RELEASE. The v0.1.7 run
    reported `Installing OpenFactory v0.1.6`; v0.1.6's tested v0.1.5; v0.1.5's tested v0.1.4. The
    job that exists to prove a release had never once exercised the release it was gating, and
    every fix we shipped was validated against the artefact that predated it.

    `install.sh` falls back to `releases/latest` when given no `--version`, which is right for a
    person running the one-liner and catastrophic for a gate — a silent fallback is what hid this
    for four releases. So the version is REQUIRED here, and it is a positional rather than an
    environment variable whose name collides with an internal of `install.sh`."""
    driver = (SCRIPTS / "e2e-install.sh").read_text()
    body = (SCRIPTS / "e2e-in-container.sh").read_text()

    assert "OPENFACTORY_E2E_VERSION:?" in driver, (
        "the driver accepts an empty version, so the job can silently test whatever "
        "`releases/latest` happens to be")
    assert "${1:?" in body, (
        "the container body accepts an empty version rather than refusing")
    assert '-e VERSION=' not in driver, (
        "the version still crosses as an environment variable named VERSION, which is also an "
        "internal of install.sh — one rename from being discarded again")


def test_the_job_asserts_what_it_installed_is_what_it_was_asked_to_test():
    """The guard that would have caught it on run one. Passing the version correctly is not the
    same as having installed that version, and only the second is the property — the plumbing
    measured correct at every hop locally while the runs installed something else."""
    body = "\n".join(line for line in (SCRIPTS / "e2e-in-container.sh").read_text().splitlines()
                     if not line.lstrip().startswith("#"))

    assert 'OPENFACTORY_VERSION=' in body and "installed" in body, (
        "nothing reads back which release was actually installed")
    assert '"$installed" != "$VERSION"' in body, (
        "the installed release is never compared with the one under test")
    assert "exit 1" in body, "a gate that tested the wrong release does not fail"


def test_a_socket_refusal_says_which_identity_was_refused():
    """Two runs died on `permission denied … docker.sock` and the first was diagnosed as a
    borrowed-uid problem — a diagnosis this step no longer permits, because it borrows nothing.
    Reasoning from a log produced a wrong answer twice, so the log carries the evidence now."""
    body = (SCRIPTS / "e2e-verify.sh").read_text()

    assert "who this step is" in body and "$(id" in body, (
        "a socket refusal does not say which identity was refused")
    assert "ls -ln /var/run/docker.sock" in body, (
        "a socket refusal does not say who owns the socket it was refused")


def test_the_run_says_which_release_it_is_testing_before_it_does_anything():
    """v0.1.8 installed v0.1.7 and its log contained NEITHER the read-back's success line nor its
    failure. That cannot happen if the read-back ran, so it says the script did not reach it — and
    a guard whose silence is unreadable is the thing CONTRIBUTING now has a rule about.

    The release under test is announced before any work, so "never got there" and "got there and
    agreed" stop looking identical from outside."""
    body = "\n".join(line for line in (SCRIPTS / "e2e-in-container.sh").read_text().splitlines()
                      if not line.lstrip().startswith("#"))
    announce = body.index("e2e: this run is testing release")

    assert announce < body.index("apt-get"), (
        "the release under test is announced after work has already begun, so a run that dies "
        "early cannot be told from one that never checked")
    assert "e2e: verified" in body, "the read-back no longer says what it compared"


# ── the document check refuses; it does not raise ───────────────────────────────────────────────
#
# The Python block inside `e2e-verify.sh` is the only thing that reads the preflight document, and
# it checked the document's shape with bare `assert`s (Roberto, 2026-09-04). Three ways that fails
# a reader: `doc["schema"]` on a document with no schema raises KeyError before any assert message
# is built; an AssertionError prints a traceback about our subscripts rather than a line about
# their install; and `python3 -O` deletes assert statements outright, so the check can be removed
# by a flag. This guard RUNS the block against documents shaped wrong in five different ways.

def _document_check() -> str:
    """The block as the shell here-doc feeds it to python3 — extracted, not re-implemented, so a
    guard cannot pass against a copy that has drifted from the script CI runs."""
    body = (SCRIPTS / "e2e-verify.sh").read_text()
    found = re.search(r"python3 - \"\$\{SHARED\}/preflight\.json\" <<'PY'\n(.*?)\nPY\n", body, re.S)
    assert found, "e2e-verify.sh no longer feeds a python3 here-doc the preflight document"
    return found.group(1)


_A_GOOD_DOCUMENT = {
    "schema": "openfactory.preflight/1", "verdict": "red",
    "findings": [{"check": "agent-credential", "answered": True, "ok": False,
                  "remedy": "Set OPENFACTORY_AGENT_TOKEN."},
                 {"check": "docker-socket", "answered": True, "ok": True, "remedy": ""}],
}

_MALFORMED = {
    "not an object at all": [1, 2],
    "no schema": {"findings": [{"check": "a", "answered": True, "ok": True}]},
    "a schema from some other document": {
        "schema": "openfactory.something-else/1",
        "findings": [{"check": "a", "answered": True, "ok": True}]},
    "no findings": {"schema": "openfactory.preflight/1", "findings": []},
    "a finding that is a string, not an object": {
        "schema": "openfactory.preflight/1", "findings": ["docker-socket: ok"]},
    # A NUMBER, and not only a string, because the string is caught one check later by accident:
    # `{"check", ...} - set("docker-socket: ok")` is a set of characters and reports three missing
    # keys, so the per-finding isinstance check looked unnecessary until a mutation removed it and
    # nothing went red. `set(42)` raises TypeError, which is the traceback this whole change exists
    # to prevent.
    "a finding that is a number": {
        "schema": "openfactory.preflight/1", "findings": [42]},
    "a finding missing the keys the agent lane reads": {
        "schema": "openfactory.preflight/1", "findings": [{"check": "a"}]},
    "a red finding whose remedy is whitespace": {
        "schema": "openfactory.preflight/1",
        "findings": [{"check": "socket", "answered": True, "ok": False, "remedy": "   "}]},
}


def _check_it(tmp_path, doc, name="d.json", optimised=False):
    program = tmp_path / "check.py"
    program.write_text(_document_check())
    document = tmp_path / name
    document.write_text(json.dumps(doc) if not isinstance(doc, str) else doc)
    argv = [sys.executable] + (["-O"] if optimised else []) + [str(program), str(document)]
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("description", sorted(_MALFORMED))
def test_a_malformed_preflight_document_is_refused_not_raised(tmp_path, description):
    done = _check_it(tmp_path, _MALFORMED[description])

    assert done.returncode != 0, f"{description} was accepted: {done.stdout}"
    assert "Traceback" not in done.stderr, (
        f"{description} raised instead of refusing:\n{done.stderr}")
    assert "remedy:" in done.stderr, (
        f"{description} refuses without saying what to do about it:\n{done.stderr}")


def test_an_unreadable_document_is_refused_not_raised(tmp_path):
    """Truncated JSON — the shape that made the outer read a try/except in the first place."""
    done = _check_it(tmp_path, '{"schema": "openfactory.preflight/1", "findi')

    assert done.returncode != 0
    assert "Traceback" not in done.stderr, done.stderr
    assert "could not be read" in done.stderr, done.stderr


def test_a_good_document_passes_and_says_what_it_saw(tmp_path):
    """The positive twin: none of the above can be satisfied by a block that refuses everything."""
    done = _check_it(tmp_path, _A_GOOD_DOCUMENT)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "preflight: red over 2 checks" in done.stdout, done.stdout


def test_the_shape_checks_survive_python_optimisation(tmp_path):
    """`python3 -O` DELETES assert statements. Nothing runs this under -O today, so this is not a
    bug report — it is why the checks are `if`/`sys.exit` and not asserts: a check a flag can
    remove is not a check, and the flag is one word away in any workflow."""
    done = _check_it(tmp_path, _MALFORMED["no schema"], optimised=True)

    assert done.returncode != 0, (
        "under -O the document check accepts a document with no schema, so the checks are "
        "assert statements the interpreter has deleted")


def test_no_bare_assert_reads_the_preflight_document():
    """Read as CODE, not as text: the block above is the thing, and a comment about asserts must
    not satisfy or break this."""
    statements = [line.split("#")[0].rstrip() for line in _document_check().splitlines()]

    offenders = [line for line in statements if line.lstrip().startswith("assert ")]
    assert not offenders, (
        f"these lines check the preflight document with assert, which -O deletes and which "
        f"prints a traceback rather than a remedy: {offenders}")
