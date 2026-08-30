"""An advisory finding survives save(), renders in box status, and informs onboarding — #15.

THE DEFECT (#15, found by @hermesfelipe in review of #12).
`Proof.save()` serialized only eight scalar fields, omitting `findings`.
When `box prove` ran, advisory warnings were printed live, but after saving and reloading,
`proof.findings` was empty — so `box status` and the onboarding PR never displayed the warnings.

This suite tests:
1. `save()` / `load()` carry `findings` and `Proof.advisories()` returns them after reload.
2. 3-state discipline: a legacy proof file missing `"findings"` loads with `proof.findings is None`
   (not recorded), NEVER as `[]`.
3. `openfactory box status` renders advisory `warn` findings.
4. `onboarding/onboard.py` includes advisory warnings in the PR body.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from openfactory.box_prove import Finding, Proof, load, save
from openfactory.cli import app
from openfactory.onboarding.onboard import RepoOutcome, _pr_body


def test_findings_survive_save_and_load(tmp_path: Path):
    """A proof saved to disk must preserve all findings, including advisory flags."""
    proof = Proof(
        project="acme",
        image="ghcr.io/org/box:latest",
        ok=True,
        digest="sha256:1234567890abcdef",
        toolbox="linux-arm64-glibc",
        commands_hash="hash123",
        toolchain="python=3.12",
        at="2026-08-30T12:00:00Z",
        findings=[
            Finding("setup", True, "2 command(s)"),
            Finding(
                "validate",
                False,
                "security: `scan` exited 1\nfound credential",
                "declared `advisory: true`",
                advisory=True,
            ),
            Finding("validate", True, "1 gate(s) green on untouched main; 1 advisory gate(s) failed"),
        ],
    )
    saved_path = save(proof, root=tmp_path)
    assert saved_path is not None
    assert saved_path.exists()

    # Raw JSON inspection
    raw = json.loads(saved_path.read_text())
    assert "findings" in raw
    assert len(raw["findings"]) == 3
    assert raw["findings"][1]["advisory"] is True
    assert raw["findings"][1]["check"] == "validate"

    # Reloaded Proof object
    loaded = load("acme", root=tmp_path)
    assert loaded is not None
    assert loaded.project == "acme"
    assert loaded.ok is True
    assert loaded.findings is not None
    assert len(loaded.findings) == 3

    # Failures and Advisories
    assert len(loaded.failures()) == 0
    advisories = loaded.advisories()
    assert len(advisories) == 1
    assert advisories[0].check == "validate"
    assert advisories[0].advisory is True
    assert "security: `scan` exited 1" in advisories[0].message


def test_legacy_proof_without_findings_key_loads_as_none_not_empty(tmp_path: Path):
    """THREE-STATE DISCIPLINE: An older proof written before `findings` serialization carried no
    'findings' key in JSON. It must load as `proof.findings is None` (not recorded), NEVER as `[]`.
    Collapsing the two would make every legacy proof falsely claim it had zero advisory findings."""
    legacy_json = tmp_path / "legacy.json"
    legacy_json.write_text(json.dumps({
        "project": "legacy",
        "image": "img",
        "ok": True,
        "digest": "sha256:abc",
        "toolbox": "box",
        "commands_hash": "h123",
        "at": "2026-08-01T00:00:00Z",
        "toolchain": "",
    }))

    loaded = load("legacy", root=tmp_path)
    assert loaded is not None
    assert loaded.findings is None
    # failures() and advisories() must safely return [] without crashing
    assert loaded.failures() == []
    assert loaded.advisories() == []


def test_box_status_renders_advisory_warnings(tmp_path: Path, monkeypatch):
    """`openfactory box status` must render advisory warnings so operators see carried debt."""
    import openfactory.box_prove as bp

    repo = tmp_path / "repo"
    (repo / ".openfactory").mkdir(parents=True)
    (repo / ".openfactory" / "project.yaml").write_text("version: 1\nvalidate:\n  test: 'true'\n")

    reg = tmp_path / "registry.yaml"
    reg.write_text(json.dumps({"projects": {"acme": {"name": "acme", "repo_path": str(repo)}}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))
    monkeypatch.setattr(bp, "PROOF_DIR", tmp_path)

    from openfactory.loader import load_manifest
    from openfactory.orchestrator.validation import gate_commands
    from openfactory.registry import ProjectRegistry

    m = load_manifest(ProjectRegistry().get("acme"))
    commands = bp._hash_commands(list(m.setup), gate_commands(m.validation), bp.component_gates(m))
    monkeypatch.setattr(bp, "_current_digest", lambda img: "sha256:same")

    proof = Proof(
        project="acme",
        image="img",
        ok=True,
        digest="sha256:same",
        toolbox="",
        commands_hash=commands,
        toolchain="python=3.12",
        at="2026-08-30T12:00:00Z",
        findings=[
            Finding("setup", True, "1 command"),
            Finding("validate", False, "security: scan exited 1", advisory=True),
        ],
    )
    save(proof, root=tmp_path)

    res = CliRunner().invoke(app, ["box", "status", "acme"])
    assert res.exit_code == 0
    assert "proven at 2026-08-30T12:00:00Z" in res.output
    assert "warn  validate  security: scan exited 1" in res.output


def test_box_status_renders_legacy_proof_notice_when_findings_is_none(tmp_path: Path, monkeypatch):
    """`openfactory box status` must inform operators when a proof predates findings recording."""
    import openfactory.box_prove as bp

    repo = tmp_path / "repo"
    (repo / ".openfactory").mkdir(parents=True)
    (repo / ".openfactory" / "project.yaml").write_text("version: 1\nvalidate:\n  test: 'true'\n")

    reg = tmp_path / "registry.yaml"
    reg.write_text(json.dumps({"projects": {"legacy": {"name": "legacy", "repo_path": str(repo)}}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))
    monkeypatch.setattr(bp, "PROOF_DIR", tmp_path)

    from openfactory.loader import load_manifest
    from openfactory.orchestrator.validation import gate_commands
    from openfactory.registry import ProjectRegistry

    m = load_manifest(ProjectRegistry().get("legacy"))
    commands = bp._hash_commands(list(m.setup), gate_commands(m.validation), bp.component_gates(m))
    monkeypatch.setattr(bp, "_current_digest", lambda img: "sha256:same")

    proof = Proof(
        project="legacy",
        image="img",
        ok=True,
        digest="sha256:same",
        toolbox="",
        commands_hash=commands,
        toolchain="python=3.12",
        at="2026-08-30T12:00:00Z",
        findings=None,
    )
    save(proof, root=tmp_path)

    res = CliRunner().invoke(app, ["box", "status", "legacy"])
    assert res.exit_code == 0
    assert "proven at 2026-08-30T12:00:00Z" in res.output
    assert "advisory findings were not recorded for this proof — re-prove to record them" in res.output


def test_onboarding_pr_body_includes_advisory_warnings():
    """`onboarding/onboard.py` includes advisory warnings in the PR body as non-blocking notices."""
    out = RepoOutcome(
        ok=True,
        repo="acme/backend",
        proof="proven",
        proof_failures=[],
        proof_advisories=["validate: security: `scan` exited 1\n  → declared `advisory: true`"],
        modules=5,
    )
    body = _pr_body("acme/backend", out, manifest_proposed=True)
    assert "**Box proof: PASSED**" in body
    assert "**Advisory warnings (non-blocking tech debt):**" in body
    assert "validate: security: `scan` exited 1" in body
