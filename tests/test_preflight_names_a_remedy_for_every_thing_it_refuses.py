"""Every `preflight` refusal names a cause AND a remedy, and none of them is a traceback.

THE HOUSE RULE, MADE STRUCTURAL. *Anything a user can hit refuses with one sentence naming the
cause and the remedy — never a raw traceback, never a silent no-op.* `preflight` is the sharpest
possible test of that rule, because it is the first thing a stranger runs and the only thing
standing between them and a stack that does not start: a finding with no remedy is a symptom
delivered to the one person who does not yet know the system.

`readiness._fail` already enforces it at the constructor — `remedy` is positional and required —
and `preflight` imports that constructor rather than declaring its own precisely so the rule
travels with it. This file is the other half: that every failing finding actually goes through it,
that a check which RAISES becomes a finding rather than a traceback, and that a remedy is something
a person can act on rather than a restatement of the problem.

WHY EVERY BRANCH IS REACHABLE HERE WITH NO DOCKER. `preflight.Probes` is injected for the same
reason `doctor.Probes` is: a diagnostic that can only be exercised on a healthy machine is a
diagnostic nobody can prove reports illness — which is the defect it exists to prevent, one level
up.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from openfactory import preflight


def _probes(**overrides) -> preflight.Probes:
    """A machine where everything is fine, so each test can break exactly one thing.

    A HEALTHY BASELINE IS THE ONLY WAY TO ATTRIBUTE A FINDING. Building a broken machine per test
    would make every report red for several reasons at once, and "the check I meant to break went
    red" would be unprovable."""
    healthy = dict(
        compose=lambda: (True, "v2.29.1"),
        daemon=lambda: (True, "linux/arm64"),
        host_arch=lambda: "arm64",
        port_free=lambda port: True,
        free_disk=lambda: 200 * 1024 ** 3,
        work_dir=lambda: "/home/ana/.local/share/openfactory/work",
        writable_without_root=lambda where: (True, "created and written as this user"),
        image_present=lambda image: True,
        sandbox_image=lambda: "ghcr.io/open-factory-digital/openfactory-sandbox:v1.0.0",
        env_file=lambda: (True, 0o600),
        agent_credential=lambda: (True, "CLAUDE_CODE_OAUTH_TOKEN is set"),
        ports=lambda: (("panel", 8787), ("engine UI", 8080), ("engine", 7233)),
    )
    return preflight.Probes(**{**healthy, **overrides})


#: One broken thing per row, and the check each is expected to surface. DERIVED COVERAGE, not a
#: hand-kept list of names: `test_every_check_can_be_made_to_fail` below holds this table equal to
#: the set of checks `check()` emits, so a check added without a way to break it is reported.
BREAKAGES: tuple[tuple[str, dict], ...] = (
    ("docker_daemon", dict(daemon=lambda: (False, "Cannot connect to the Docker daemon"))),
    ("docker_compose", dict(compose=lambda: (False, "docker: 'compose' is not a docker command"))),
    ("architecture", dict(host_arch=lambda: "riscv64")),
    ("ports", dict(port_free=lambda port: port != 8787)),
    ("disk", dict(free_disk=lambda: 2 * 1024 ** 3)),
    ("work_dir", dict(writable_without_root=lambda where: (False, "Permission denied"))),
    ("box_image", dict(image_present=lambda image: False)),
    ("env_file", dict(env_file=lambda: (False, None))),
    ("agent_credential", dict(agent_credential=lambda: (False, "neither variable is set"))),
)


def _finding(report: preflight.Report, check: str) -> preflight.Finding:
    return next(f for f in report.findings if f.check == check)


def test_a_healthy_machine_passes_everything_and_says_so():
    """The baseline the rest of this file rests on. A fixture that was quietly red somewhere would
    make every "this check went red" assertion below meaningless."""
    report = preflight.check(_probes())

    assert report.ok, [f"{f.check}: {f.message}" for f in report.missing]
    assert report.verdict == "OK", report.verdict


@pytest.mark.parametrize("check, broken", BREAKAGES, ids=[name for name, _ in BREAKAGES])
def test_every_refusal_names_a_remedy(check, broken):
    """THE rule. `_fail` makes this impossible to violate by construction, which is the point —
    this asserts the constructor is the one actually used, not that somebody remembered."""
    finding = _finding(preflight.check(_probes(**broken)), check)

    assert not finding.ok, f"{check} did not go red when its probe said it should"
    assert finding.remedy.strip(), (
        f"{check} refuses with no remedy — a symptom handed to the one person who does not yet "
        f"know the system: {finding.message!r}")


#: What makes a sentence a REMEDY rather than a restatement: it hands over something the reader can
#: type or edit. A backticked command, an environment variable, a path, or a file name.
#:
#: MEASURED AGAINST A SURVIVING MUTATION (2026-08-30). The first version of the test below asked
#: only that the remedy differ from the message and run past 25 characters, and a cut that replaced
#: the agent-credential remedy with the bare sentence `"no agent credential is visible"` — 30
#: characters, not equal to the message — sailed through it green. Length is not actionability, and
#: a guard that cannot tell an instruction from a paraphrase is guarding the shape of the sentence
#: rather than its usefulness.
_ACTIONABLE = re.compile(
    r"`[^`]+`"                       # a command or a name in backticks
    r"|\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"   # AN_ENVIRONMENT_VARIABLE
    r"|\S+/\S+"                      # a path or an image reference
    r"|(?:^|\s)\.?[\w-]+\.[\w.]+(?:\s|$)"   # a file name, e.g. .env.compose
)


@pytest.mark.parametrize("check, broken", BREAKAGES, ids=[name for name, _ in BREAKAGES])
def test_a_remedy_is_something_to_DO_and_not_the_problem_restated(check, broken):
    """A remedy that repeats the message is a remedy nobody can follow. The test is not that the
    sentence is long or different — it is that it hands over something to TYPE."""
    finding = _finding(preflight.check(_probes(**broken)), check)

    assert finding.remedy.strip() != finding.message.strip(), (
        f"{check}'s remedy is its message again")
    assert _ACTIONABLE.search(finding.remedy), (
        f"{check}'s remedy names nothing a person can run, set or open — it restates the problem "
        f"in other words: {finding.remedy!r}")


def test_an_env_file_that_is_readable_by_everyone_is_refused_with_the_chmod():
    """The `.env.compose` check has TWO failing branches and `BREAKAGES` reaches only the first
    (the file is absent). This is the other: the file exists and carries a forge credential with
    write access to somebody's repositories, at a mode their whole machine can read."""
    finding = _finding(preflight.check(_probes(env_file=lambda: (True, 0o644))), "env_file")

    assert not finding.ok, "a world-readable credential file passed"
    assert "0644" in finding.message, finding.message
    assert _ACTIONABLE.search(finding.remedy), finding.remedy


def test_every_check_can_be_made_to_fail():
    """VERIFY THE VERIFIER, and keep the coverage honest. A check nothing above can break is a
    check this file says nothing about — and the table would go on passing while the new check's
    remedy went unwritten. Derived from what `check()` actually emits."""
    emitted = {f.check for f in preflight.check(_probes()).findings}
    covered = {name for name, _ in BREAKAGES}

    assert emitted == covered, (
        f"checks with no way to break them here: {sorted(emitted - covered)}; "
        f"rows that break a check that no longer exists: {sorted(covered - emitted)}")


def test_a_check_that_RAISES_becomes_a_finding_and_never_a_traceback():
    """A broken check is a defect to REPORT, not a crash. Preflight is what somebody runs when
    nothing works — `doctor._guarded`'s sentence, one layer lower — and a traceback out of the
    diagnostic tells them nothing about their machine and rather a lot about ours."""
    def explodes():
        raise RuntimeError("the probe blew up")

    report = preflight.check(_probes(free_disk=explodes))
    finding = _finding(report, "disk")

    assert not finding.ok and finding.answered, finding
    assert "the probe blew up" in finding.message, finding.message
    assert finding.remedy.strip(), "a check that raised left no remedy"


def test_every_check_runs_even_when_an_earlier_one_failed():
    """STOPPING AT THE FIRST FAILURE TURNS ONE SESSION INTO SIX, and during an install it turns
    into somebody giving up: a person who must re-run an installer once per problem stops after
    the second."""
    report = preflight.check(_probes(daemon=lambda: (False, "not running"),
                                     compose=lambda: (False, "no plugin")))

    assert len(report.findings) == len(BREAKAGES), [f.check for f in report.findings]


def test_an_unanswered_check_is_not_a_pass_and_not_a_failure():
    """THE THIRD STATE, and it is the one that earns its keep here: almost every check is
    downstream of the daemon, and with no daemon there is no answer to "is the box image present".
    Inventing one is worse than admitting it — a `False` would send somebody to `docker pull`
    against a daemon that is not running, a remedy that cannot work."""
    report = preflight.check(_probes(daemon=lambda: (False, "not running"),
                                     image_present=lambda image: None))
    box = _finding(report, "box_image")

    assert not box.answered, box
    assert box not in report.missing, "an unanswered check was counted as a failure"
    assert "MISSING" in report.verdict, "the daemon failure should still be counted"


def test_a_finding_that_could_not_be_ANSWERED_is_never_counted_even_if_it_also_says_not_ok():
    """FOUND BY A SURVIVING MUTATION (2026-08-30), and the survivor was the useful kind.

    `Report.missing` reads `f.answered and not f.ok`, and dropping the first clause changed
    nothing that any test could see — because `_unanswered` builds its findings with `ok=True`, so
    the two expressions agree on every finding the module itself produces. On that evidence the
    clause is dead code.

    It is not, and this is the case that says so. `answered` and `ok` are two booleans carrying
    THREE meanings, and that only works while a reader honours both: the moment anything builds a
    finding that could not be answered AND is not ok — a probe that half-answered, a future check,
    an add-on — the count has to ignore it, because "I could not look" must never be reported as
    "this is broken". That is `doctor.BoardUnreadable`'s whole argument, and the clause is where it
    is enforced. Asserted directly, since no probe can currently produce the shape."""
    report = preflight.Report(findings=[
        preflight.Finding(check="hypothetical", ok=False, answered=False,
                          message="could not look", remedy="", measured_on=preflight.LOCAL),
    ])

    assert report.missing == [], (
        "a finding nobody could answer was counted as a failure — that is a `docker pull` against "
        "a daemon that is not running, printed with the authority of a diagnosis")
    assert report.ok, report.verdict


def test_a_report_that_could_ask_almost_nothing_says_so_rather_than_reading_green():
    """A green report that asked nothing is not the same as a green report, and the difference is
    invisible unless the verdict says it. This is the shape `doctor.BoardUnreadable` was written
    about: a diagnostic reporting "could not look" as a clean bill of health."""
    report = preflight.check(_probes(image_present=lambda image: None,
                                     free_disk=lambda: None))

    assert report.ok, [f.check for f in report.missing]
    assert "could not be answered" in report.verdict, report.verdict


def test_it_cannot_tell_you_about_a_box_image_nobody_named():
    """MEASURED BY RUNNING THE COMMAND (2026-08-30). The first version fell back to the framework's
    `DEFAULT_BOX_IMAGE` when nothing said which image the deployment would use, and reported
    `ok  box_image  the box image openfactory-python is on this daemon` — a pass about a stale
    local tag on a machine that had never seen the published image the compose file names. A pass
    about the wrong image is worse than no answer about the right one."""
    box = _finding(preflight.check(_probes(sandbox_image=lambda: None)), "box_image")

    assert not box.answered, box
    assert box.ok, "an unanswerable question must not read as a failure either"
    assert "cannot tell" in box.message.lower(), box.message


def test_the_probes_this_machine_answers_with_fill_every_field():
    """The wiring, which no other test here touches: every field of `Probes` has to be supplied by
    `probes_for_this_machine`, or the command raises `TypeError` at the one moment it is most
    needed. It is never CALLED here — that would need Docker, ports and a filesystem."""
    wired = preflight.probes_for_this_machine()

    for f in dataclasses.fields(preflight.Probes):
        assert callable(getattr(wired, f.name)), f"{f.name} is not wired to anything callable"
