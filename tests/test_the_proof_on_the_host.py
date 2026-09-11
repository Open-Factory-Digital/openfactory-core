"""`box prove` on the box that runs no image, and the gate that reads it (ADR-0049 D9, slice 9b).

The proof exists because two things burn an agent pass before anybody notices: a box that cannot
install the project, and a harness that cannot answer. Both are as true on somebody's own machine
as in a container — and until now the worktree box was not provable and not gated, so the one
runtime with no operations team was the one where a card could be picked up with nothing checked.

WHAT IS PROVEN HERE:

  · the three IMAGE stations are skipped for a box that runs none, and the proof says so — and
    says it is the weaker of the two;
  · what the proof pins instead is this machine's harness, and the gate compares the same string
    the proof recorded;
  · the gate holds this runtime and exempts every other imageless box exactly as before;
  · the proofs are recorded where this operator can write, and an explicit path still wins;
  · the harness remedy names PATH rather than a mount that does not exist here.
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "tests")


@pytest.fixture
def declared(monkeypatch, tmp_path):
    """A deployment that has said the worker is its own machine."""
    from openfactory import own_work

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(own_work.VARIABLE, "1")
    return tmp_path


def _probes(**over):
    """A probe set for a box that runs no image, green everywhere it can be."""
    from openfactory.box_prove import Probes

    base = dict(
        # THE FOUR THE DATACLASS REQUIRES are the image ones, and this box has no image: they are
        # handed answers that would EXPLODE if the proof asked, which is the assertion underneath
        # the first test in this file — a station that is skipped must not be reached.
        resolve_digest=lambda img: (_ for _ in ()).throw(AssertionError("an image was pulled")),
        image_platform=lambda img: (_ for _ in ()).throw(AssertionError("an image was read")),
        toolbox_stamp=lambda: (_ for _ in ()).throw(AssertionError("a toolbox was asked about")),
        contract=lambda img: (_ for _ in ()).throw(AssertionError("an image contract was checked")),
        honours_image=False,
        machine_stamp=lambda: "claude 2.1.0",
        run_in_box=lambda cmd: (0, ""),
        setup_commands=lambda: [],
        validate_commands=lambda: {"test": "true"},
        advisory_gates=set,
        component_gate_commands=dict,
        harness_name=lambda: "claude",
        harness_reachable=lambda: (True, "200"),
    )
    base.update(over)
    return Probes(**base)


# ── the stations an imageless box does not have ─────────────────────────────────────────────────

def test_the_image_stations_are_skipped_and_the_proof_SAYS_WHY():
    from openfactory.box_prove import prove

    proof = prove("myapp", "openfactory-python", _probes())

    image = next(f for f in proof.findings if f.check == "image")
    assert image.ok and "no image" in image.message
    assert "weaker of the two" in image.message, "the trade is not stated"
    assert not any(f.check == "toolbox" for f in proof.findings), "a toolbox volume was checked"
    assert not any(f.check == "contract" for f in proof.findings), "an image contract was checked"


def test_what_it_pins_instead_is_THIS_MACHINES_harness():
    from openfactory.box_prove import prove

    proof = prove("myapp", "", _probes())

    assert proof.toolchain == "claude 2.1.0"
    assert proof.image == "" and proof.digest == ""


def test_the_clients_own_gates_still_run_which_is_the_point():
    from openfactory.box_prove import prove

    ran: list[str] = []
    proof = prove("myapp", "", _probes(
        run_in_box=lambda cmd: (ran.append(cmd), (0, ""))[1],
        setup_commands=lambda: ["pip install -e ."],
        validate_commands=lambda: {"test": "pytest -q"}))

    assert any("pip install" in c for c in ran) and any("pytest" in c for c in ran)
    assert proof.ok, [f.message for f in proof.findings if not f.ok]


def test_the_harness_remedy_names_the_PATH_not_a_mount_that_is_not_there():
    from openfactory.box_prove import prove

    proof = prove("myapp", "", _probes(run_in_box=lambda cmd: (
        (127, "claude: not found") if "--version" in cmd else (0, ""))))

    harness = next(f for f in proof.findings if f.check == "harness" and not f.ok)
    assert "PATH" in harness.remedy and "toolbox" not in harness.remedy


# ── the gate ────────────────────────────────────────────────────────────────────────────────────

def test_this_runtime_is_GATED_like_any_other(declared, monkeypatch):
    """Today a worktree was not gated at all: on the one runtime with no operations team, a card
    could be picked up with nothing checked."""
    from openfactory.box_prove import gate_reason
    from openfactory.contracts.project import Project, ProviderRef

    project = Project(name="myapp", repo_path=str(declared),
                      tracker=ProviderRef(kind="local", repo="myapp"))

    assert gate_reason(project, sandbox="worktree"), "the host runtime is not gated"


def test_every_other_imageless_box_keeps_its_exemption(tmp_path, monkeypatch):
    """A cloud task's image is baked into its task definition, and a deployment that never said
    the worker is its own machine is exactly the one this exemption was written for."""
    from openfactory import own_work
    from openfactory.box_prove import gate_reason
    from openfactory.contracts.project import Project, ProviderRef

    monkeypatch.delenv(own_work.VARIABLE, raising=False)
    project = Project(name="myapp", repo_path=str(tmp_path),
                      tracker=ProviderRef(kind="local", repo="myapp"))

    assert gate_reason(project, sandbox="worktree") is None


def test_a_HOST_proof_beside_a_populated_toolbox_volume_is_not_stale():
    """The hold whose remedy could never clear it (found in review of #105).

    A proof taken against no image never recorded a toolbox — that field is the IMAGE side's, the
    variant of the volume mounted into a container — and `gate_reason` reads the worker's stamp
    whatever box it is asking about. So on any gating process with a populated volume AND the
    declaration set, a host proof reported *the harness toolbox changed (none → …)* on every tick,
    and running `box prove` wrote the same empty field again.

    The old guard never put the two next to each other: it passed `variant=""` on both calls."""
    from openfactory.box_prove import Proof, _freshness_reason

    host = Proof(project="myapp", image="", ok=True, toolchain="claude 2.1", toolbox="",
                 commands_hash="abc")

    assert _freshness_reason(host, digest="", variant="linux-amd64-glibc", commands="abc",
                             run_it="re-prove", machine="claude 2.1") is None


def test_an_IMAGE_proof_still_expires_when_its_toolbox_moves():
    """The other half: where the box does run an image, the volume's variant is exactly the fact
    that can make the proof describe a box that is no longer there."""
    from openfactory.box_prove import Proof, _freshness_reason

    image = Proof(project="myapp", image="an-image", ok=True, digest="sha256:a",
                  toolbox="linux-amd64-glibc", commands_hash="abc")

    moved = _freshness_reason(image, digest="sha256:a", variant="linux-arm64-musl",
                              commands="abc", run_it="re-prove")

    assert moved and "toolbox changed" in moved


def test_the_two_sides_of_the_machine_stamp_are_ONE_spelling():
    """The proof records it and the gate compares it; a second derivation of the harness binary
    would make every host proof look stale on the tick after it was taken."""
    import inspect

    from openfactory import box_prove

    gate_side = inspect.getsource(box_prove._machine_version)

    assert "_harness_binary(project)" in gate_side, (
        "the gate derives the binary itself instead of asking the one helper that knows")


def test_the_proof_notices_the_harness_moving_underneath_it(declared):
    """An upgraded CLI is the same shape of change as a rebuilt image, and it is the one fact a
    host proof is pinned to."""
    from openfactory.box_prove import Proof, _freshness_reason

    proof = Proof(project="myapp", image="", ok=True, toolchain="claude 2.1.0",
                  commands_hash="abc")

    assert _freshness_reason(proof, digest="", variant="", commands="abc", run_it="re-prove",
                             machine="claude 2.1.0") is None
    moved = _freshness_reason(proof, digest="", variant="", commands="abc", run_it="re-prove",
                              machine="claude 2.2.0")
    assert moved and "the harness changed" in moved


# ── where the proofs go ─────────────────────────────────────────────────────────────────────────

def test_the_proofs_are_recorded_where_this_operator_can_WRITE(declared):
    """`/var/lib/openfactory` is a service's directory: `box prove` produced a real proof on a
    laptop and could not record it, so the very next pickup was held with "never been proven"."""
    from openfactory.box_prove import _proof_dir

    assert str(declared) in str(_proof_dir())


def test_an_explicit_path_is_never_second_guessed(declared, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PROOFS", "/somewhere/else")
    from openfactory.box_prove import _proof_dir

    assert str(_proof_dir()) == "/somewhere/else"


def test_a_service_deployment_keeps_the_directory_it_had(tmp_path, monkeypatch):
    from openfactory import own_work
    from openfactory.box_prove import _proof_dir

    monkeypatch.delenv(own_work.VARIABLE, raising=False)
    monkeypatch.delenv("OPENFACTORY_PROOFS", raising=False)

    assert str(_proof_dir()) == "/var/lib/openfactory/proofs"
