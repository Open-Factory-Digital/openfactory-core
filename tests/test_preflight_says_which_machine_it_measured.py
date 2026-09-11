"""Every preflight finding says which machine it answered for.

WHY `measured_on` EXISTS AT ALL, in this codebase's own words: *a verdict about a laptop, delivered
with the authority of a verdict about the factory, is how a client gets blamed for a Docker daemon
that was never in question.* `openfactory/onboarding/readiness.py` carries the field for exactly
that reason, and its comment is blunter still — *a finding with no provenance is a finding about
the wrong computer, told with a straight face.*

PREFLIGHT IS WHERE THAT CONFUSION IS CHEAPEST TO CREATE. It runs during an install, possibly inside
a container (`openfactory-cli`), against a daemon that may be a VM (Docker Desktop), about a stack
that does not exist yet. Four candidate machines, and every finding here is about exactly one of
them: the HOST the user is sitting at. Saying so on every line is what stops the report being read
as a verdict on the factory it is trying to bring into existence.

`LOCAL` IS BORROWED FROM `readiness`, NOT REDECLARED. The whole reason that module exists is that
`doctor`, `gate_reason` and `conformance` had three disagreeing notions of "ready"; a preflight
that invented a fourth vocabulary for "which machine" would re-open the same defect on the field
whose entire job is disambiguation.
"""

from __future__ import annotations

from openfactory import preflight
from openfactory.onboarding import readiness


def _probes(**overrides) -> preflight.Probes:
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


def test_every_finding_on_a_healthy_machine_says_where_it_was_measured():
    report = preflight.check(_probes())

    assert report.findings, "no findings — this guard has no subject"
    blank = [f.check for f in report.findings if not f.measured_on]
    assert not blank, f"these findings claim nothing about which machine they describe: {blank}"


def test_a_failing_finding_says_it_too():
    """The half that matters most. A PASS with no provenance is merely vague; a FAILURE with no
    provenance is an accusation aimed at nobody in particular, and the person reading it is the one
    who does not yet know which computer the tool was looking at."""
    report = preflight.check(_probes(
        daemon=lambda: (False, "Cannot connect to the Docker daemon"),
        compose=lambda: (False, "not a docker command"),
        writable_without_root=lambda where: (False, "Permission denied"),
        env_file=lambda: (False, None),
        agent_credential=lambda: (False, "neither variable is set")))

    assert report.missing, "nothing failed — this guard has no subject"
    for finding in report.missing:
        assert finding.measured_on, f"{finding.check} fails and says nothing about whose machine"


def test_an_unanswered_finding_says_it_too():
    """"I could not answer this" is still a statement ABOUT a machine, and the third state is
    exactly where provenance is easiest to drop — the check never ran, so there is a temptation to
    leave the field empty."""
    report = preflight.check(_probes(image_present=lambda image: None, free_disk=lambda: None))

    assert report.unanswered, "nothing was unanswered — this guard has no subject"
    for finding in report.unanswered:
        assert finding.measured_on, f"{finding.check} could not answer and does not say for whom"


def test_a_check_that_RAISED_still_says_which_machine_it_was_asking_about():
    """The guarded path builds a finding by a different route from every other one, so it is the
    route most likely to forget a field that is set everywhere else."""
    def explodes():
        raise RuntimeError("boom")

    finding = next(f for f in preflight.check(_probes(free_disk=explodes)).findings
                   if f.check == "disk")

    assert finding.measured_on, "a crashed check reports about no machine at all"


def test_the_machine_is_the_HOST_and_never_the_worker():
    """Every fact preflight measures is the host's: its daemon, its ports, its disk, its
    `.env.compose`. Claiming `worker` for any of them would be the exact confusion `measured_on`
    was introduced to prevent, in the direction that gets somebody blamed for the wrong computer —
    and at install time there IS no worker."""
    report = preflight.check(_probes())

    wrong = {f.check: f.measured_on for f in report.findings if f.measured_on != readiness.LOCAL}
    assert not wrong, (
        f"these claim to describe a machine other than the host the user is sitting at: {wrong}")
    assert report.measured_on == readiness.LOCAL


def test_the_vocabulary_is_readiness_own_and_not_a_second_one():
    """A preflight-private spelling of "which machine" would be a fourth notion beside the three
    `readiness.py` was written to reconcile. The value has to be the SAME constant, not an equal
    string that drifts the day one of them is renamed."""
    assert preflight.LOCAL is readiness.LOCAL
    assert preflight.Finding is readiness.Finding
