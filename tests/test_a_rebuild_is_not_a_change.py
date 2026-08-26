"""Updating the platform must not hold the client's factory, nor shout about it (2026-08-15).

The pilot opened his tech-lead channel before touching anything and found eight alarms:

    ⏸️ podbeam — tickets are not being picked up.
    the image openfactory-python:sandbox changed (sha256:e2822c… → sha256:dec652…) — run …
    ⏸️ podbeam — tickets are not being picked up.
    the image openfactory-python:sandbox changed (sha256:e2822c… → sha256:15f3f7…) — run …
    …six more, one per update…

*"it may make sense, but as we discussed this goes to a client, so I am putting myself in their
place."* Both halves were defects of ours, and both are structural on the FREE deployment:

  1. A compose install BUILDS its box image, so it has no registry digest and the proof pins the
     content id — which moves on every `--build`, including the ones carrying only a new version
     of our own package. A client's `setup:` and `validate:` depend on the TOOLCHAIN, so that is
     what the image now writes down and what the gate compares when the digest has moved.
  2. "Say it once" compared the whole sentence, and the sentence carries the digest that changed.
     Same hold, new words, new alarm — eight times.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openfactory import box_prove as bp

RUN_IT = "run `openfactory box prove acme`"


def _proof(tmp_path, **kw) -> bp.Proof:
    p = bp.Proof(project="acme", image="openfactory-python:sandbox", ok=True,
                 digest="sha256:aaa", toolbox="linux-arm64-glibc", commands_hash="c1",
                 toolchain="os=debian 12\npython=Python 3.12.4\nnode=v20.11.1", **kw)
    bp.save(p, root=tmp_path)
    return p


# ── 1. a rebuild that changes nothing a client depends on ───────────────────────────────────────

def test_the_same_toolchain_under_a_new_digest_is_still_proven(tmp_path, monkeypatch):
    """The pilot's case exactly: eight rebuilds, the same Debian, python and node inside."""
    proof = _proof(tmp_path)
    monkeypatch.setattr(bp, "PROOF_DIR", tmp_path)
    monkeypatch.setattr(bp, "_current_digest", lambda image: "sha256:bbb")
    monkeypatch.setattr(bp, "_toolchain_of", lambda image: proof.toolchain)

    assert bp._freshness_reason(proof, digest="sha256:bbb", variant=proof.toolbox,
                                commands="c1", run_it=RUN_IT) is None


def test_a_toolchain_that_really_changed_still_holds(tmp_path, monkeypatch):
    """The negative twin, and the reason this cannot simply ignore the digest: a box whose python
    moved under the client's commands is a box those commands were never proven in."""
    proof = _proof(tmp_path)
    monkeypatch.setattr(bp, "PROOF_DIR", tmp_path)
    monkeypatch.setattr(bp, "_toolchain_of",
                        lambda image: "os=debian 12\npython=Python 3.13.0\nnode=v22.0.0")

    reason = bp._freshness_reason(proof, digest="sha256:bbb", variant=proof.toolbox,
                                  commands="c1", run_it=RUN_IT)
    assert reason and "changed" in reason and "box prove" in reason


@pytest.mark.parametrize("recorded,live", [("", "os=debian 12"), ("os=debian 12", ""), ("", "")])
def test_an_unreadable_toolchain_is_not_a_verdict(tmp_path, monkeypatch, recorded, live):
    """A client's own toolbox image carries no stamp, and an image that cannot be run says
    nothing either. Neither may be read as "unchanged" — with nothing to compare, the digest is
    the only fact there is, and it moved."""
    proof = _proof(tmp_path)
    proof.toolchain = recorded
    monkeypatch.setattr(bp, "PROOF_DIR", tmp_path)
    monkeypatch.setattr(bp, "_toolchain_of", lambda image: live)

    assert bp._freshness_reason(proof, digest="sha256:bbb", variant=proof.toolbox,
                                commands="c1", run_it=RUN_IT) is not None


def test_the_question_is_asked_once_not_every_tick(tmp_path, monkeypatch):
    """Reading a toolchain runs a container. The poller ticks every few minutes, so a proof that
    survives a rebuild records the digest it now describes — otherwise the free deployment pays a
    `docker run` per project per tick, for ever."""
    proof = _proof(tmp_path)
    monkeypatch.setattr(bp, "PROOF_DIR", tmp_path)
    asked = []
    monkeypatch.setattr(bp, "_toolchain_of",
                        lambda image: asked.append(image) or proof.toolchain)

    bp._freshness_reason(proof, digest="sha256:bbb", variant=proof.toolbox,
                         commands="c1", run_it=RUN_IT)
    assert bp.load("acme", root=tmp_path).digest == "sha256:bbb", (
        "the proof still points at the digest it was taken against")

    bp._freshness_reason(bp.load("acme", root=tmp_path), digest="sha256:bbb",
                         variant=proof.toolbox, commands="c1", run_it=RUN_IT)
    assert len(asked) == 1, "the box was asked again for a digest that now matches"


def test_a_change_the_client_made_is_never_excused_by_the_toolchain(tmp_path, monkeypatch):
    """The toolchain answers ONE question — did the image move under us. It may not stand in for
    the others: edited commands and a changed toolbox variant are the client's world moving."""
    proof = _proof(tmp_path)
    monkeypatch.setattr(bp, "PROOF_DIR", tmp_path)
    monkeypatch.setattr(bp, "_toolchain_of", lambda image: proof.toolchain)

    assert bp._freshness_reason(proof, digest="sha256:aaa", variant=proof.toolbox,
                                commands="EDITED", run_it=RUN_IT) is not None
    assert bp._freshness_reason(proof, digest="sha256:aaa", variant="linux-amd64-musl",
                                commands="c1", run_it=RUN_IT) is not None


def test_prove_actually_RECORDS_what_the_gate_will_compare(tmp_path):
    """The reachability half, and this repository's signature defect: a field the gate reads and
    `prove` never writes would leave every proof with an empty toolchain, so the comparison above
    would never engage and every rebuild would go on holding the floor — with a full suite green."""
    probes = bp.Probes(
        resolve_digest=lambda img: "sha256:abc",
        image_platform=lambda img: ("linux", "arm64", "glibc"),
        toolbox_stamp=lambda: {"variant": "linux-arm64-glibc", "harnesses": ["claude"]},
        contract=lambda img: {},
        run_in_box=lambda cmd: (0, ""),
        harness_reachable=lambda: (True, "ok"),
        setup_commands=lambda: [],
        validate_commands=lambda: {"test": "true"},
        harness_name=lambda: "claude",
        toolchain_stamp=lambda img: "os=debian 12\npython=Python 3.12.14",
    )
    proof = bp.prove("acme", "openfactory-python:sandbox", probes)
    assert proof.toolchain == "os=debian 12\npython=Python 3.12.14"

    bp.save(proof, root=tmp_path)
    assert bp.load("acme", root=tmp_path).toolchain == proof.toolchain, (
        "the stamp is recorded in memory and lost on the way to disk")


def test_a_box_that_cannot_be_asked_still_proves(tmp_path):
    """A stamp is an optimisation. An image that will not answer must still be provable — the
    proof then pins its digest alone, which is exactly what it did before this existed."""
    def _boom(_img):
        raise OSError("no docker here")

    probes = bp.Probes(
        resolve_digest=lambda img: "sha256:abc",
        image_platform=lambda img: ("linux", "arm64", "glibc"),
        toolbox_stamp=lambda: {"variant": "linux-arm64-glibc", "harnesses": ["claude"]},
        contract=lambda img: {},
        run_in_box=lambda cmd: (0, ""),
        harness_reachable=lambda: (True, "ok"),
        setup_commands=lambda: [],
        validate_commands=lambda: {"test": "true"},
        harness_name=lambda: "claude",
        toolchain_stamp=_boom,
    )
    proof = bp.prove("acme", "openfactory-python:sandbox", probes)
    assert proof.ok is True and proof.toolchain == ""


def test_the_box_image_writes_the_line_the_proof_reads():
    """The two halves are in different files — a Dockerfile and a python module — so nothing but
    a guard keeps them talking about the same thing."""
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "docker" / "sandbox.Dockerfile").read_text()

    assert bp.TOOLCHAIN_FILE in dockerfile, (
        f"the box image does not write {bp.TOOLCHAIN_FILE}, so every rebuild reads as a change")
    for tool in ("python=", "node=", "git="):
        assert tool in dockerfile, f"the stamp does not record {tool!r}"


def test_box_status_asks_the_same_function_the_poller_asks():
    """TWO ANSWERS TO ONE QUESTION is what this file's own history is made of. `box status`
    reproduced the freshness rules inline, so the moment the gate learned that a rebuild with the
    same toolchain is not a change, the command would have said EXPIRED about a proof the factory
    was happily picking cards up on — and an operator would have re-proven for nothing, or worse,
    gone looking for the disagreement."""
    import inspect

    from openfactory import cli

    src = inspect.getsource(cli.box_status_cmd)
    assert "_freshness_reason" in src, "the command judges freshness by its own rules again"
    assert "proof.commands_hash != current" not in src, "a second copy of the rules is back"
    assert "proof.toolbox != variant" not in src


def test_box_status_says_what_the_proof_is_pinned_to(tmp_path, monkeypatch, capsys):
    """An operator cannot tell a proof that will survive the next update from one that will not,
    unless the thing it is pinned to is on screen. The pilot's first proof was taken against an
    image with no toolchain line — valid, and about to expire on his very next `--build`."""
    import json as _json

    from typer.testing import CliRunner

    from openfactory.cli import app

    repo = tmp_path / "repo"
    (repo / ".openfactory").mkdir(parents=True)
    (repo / ".openfactory" / "project.yaml").write_text("version: 1\nvalidate:\n  test: 'true'\n")
    reg = tmp_path / "registry.yaml"
    reg.write_text(_json.dumps({"projects": {"acme": {"name": "acme", "repo_path": str(repo)}}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))
    monkeypatch.setattr(bp, "PROOF_DIR", tmp_path)

    from openfactory.loader import load_manifest
    from openfactory.orchestrator.validation import gate_commands
    from openfactory.registry import ProjectRegistry

    m = load_manifest(ProjectRegistry().get("acme"))
    commands = bp._hash_commands(list(m.setup), gate_commands(m.validation),
                                 bp.component_gates(m))
    monkeypatch.setattr(bp, "_current_digest", lambda img: "sha256:same")

    for toolchain, expected in ((("os=debian 12\npython=Python 3.12"), "toolchain os=debian 12"),
                                ("", "carries no toolchain line")):
        bp.save(bp.Proof(project="acme", image="img", ok=True, digest="sha256:same", toolbox="",
                         commands_hash=commands, toolchain=toolchain, at="2026-08-15T20:00"),
                root=tmp_path)
        out = CliRunner().invoke(app, ["box", "status", "acme"]).output
        assert expected in out, f"status does not say what it is pinned to: {out!r}"


# ── 2. the same hold, said once ─────────────────────────────────────────────────────────────────

def test_the_same_hold_is_announced_once_however_its_detail_moves(tmp_path, monkeypatch):
    """Eight rebuilds, eight sentences, one fact. The detail belongs in the message — an operator
    needs to know which digest moved — and not in the question "have I already said this?"."""
    said = []
    monkeypatch.setattr(bp, "PROOF_DIR", tmp_path)
    monkeypatch.setattr(bp, "log", type("L", (), {
        "warning": lambda self, *a, **k: said.append(a), "info": lambda *a, **k: None})())

    first = bp.announce_gate(
        "acme", "the image openfactory-python:sandbox changed (sha256:aaa… → sha256:bbb…) — "
        "run `openfactory box prove acme`", root=tmp_path)
    again = bp.announce_gate(
        "acme", "the image openfactory-python:sandbox changed (sha256:aaa… → sha256:ccc…) — "
        "run `openfactory box prove acme`", root=tmp_path)

    assert first is True
    assert again is False, "the same hold spoke twice because its digest moved"


def test_a_DIFFERENT_hold_still_speaks(tmp_path, monkeypatch):
    """The negative twin, and the reason this is not simply "announce once per project": a proof
    that has started FAILING is a different fact from one that has gone stale, and an operator who
    is never told the second time learns nothing from the first."""
    monkeypatch.setattr(bp, "PROOF_DIR", tmp_path)

    assert bp.announce_gate("acme", "the image x changed (a… → b…) — run it", root=tmp_path)
    assert bp.announce_gate("acme", "the last box proof FAILED — run it", root=tmp_path), (
        "a new kind of hold stayed quiet because something else was announced first")
