"""`box status --json` is a versioned contract: the proof's digest, its toolchain pins and its
validity, per repository (#356, core change 2).

WHO READS IT. `openfactory certify` reads one of these per (project, repository) for its C-PROOF
control and its proof table, and an operator's scripts ask the same question the poller asks —
"will this repository's cards be picked up?" — without parsing prose. So, like `preflight --json`
and `doctor --json`, it says which version of itself it is and its keys are pinned by EQUALITY.

ONE STATUS, TWO RENDERINGS. `box status` assembled its answer inline; it now reads
`box_prove.status`, which judges freshness with the function the poller asks, and prints either
the lines a person reads or the document a script reads. The guards below hold the two to the same
answer and hold the lines to what the command has always printed, byte for byte.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import openfactory.box_prove as bp
from openfactory.cli import app

DOCUMENT_KEYS = {"schema", "project", "repository", "key", "valid", "state", "reason", "remedy",
                 "image", "digest", "toolchain", "proven_at", "advisories"}

TOOLCHAIN = "os=debian 12\npython=Python 3.12.5\nnode=v22.3.0"


@pytest.fixture()
def acme(tmp_path, monkeypatch):
    """A registered project with a real manifest, its proofs kept in a temporary directory, and a
    docker that answers one fixed digest and no toolchain line — nothing here reaches a daemon."""
    repo = tmp_path / "repo"
    (repo / ".openfactory").mkdir(parents=True)
    (repo / ".openfactory" / "project.yaml").write_text("version: 1\nvalidate:\n  test: 'true'\n")
    reg = tmp_path / "registry.yaml"
    reg.write_text(json.dumps({"projects": {"acme": {"name": "acme", "repo_path": str(repo)}}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))
    monkeypatch.setattr(bp, "PROOF_DIR", tmp_path / "proofs")
    monkeypatch.setattr(bp, "_current_digest", lambda img: "sha256:" + "a" * 64)
    monkeypatch.setattr(bp, "_toolchain_of", lambda img: "")

    from openfactory.loader import load_manifest
    from openfactory.orchestrator.validation import gate_commands
    from openfactory.registry import ProjectRegistry

    m = load_manifest(ProjectRegistry().get("acme"))
    commands = bp._hash_commands(list(m.setup), gate_commands(m.validation),
                                 bp.component_gates(m))

    def prove(**over):
        proof = dict(project="acme", image="ghcr.io/acme/box:1", ok=True,
                     digest="sha256:" + "a" * 64, toolbox="", commands_hash=commands,
                     toolchain=TOOLCHAIN, at="2026-10-01T09:00:00Z",
                     findings=[bp.Finding("setup", True, "1 command"),
                               bp.Finding("validate", False, "security: scan exited 1",
                                          advisory=True)])
        bp.save(bp.Proof(**{**proof, **over}), root=tmp_path / "proofs")

    return prove


def _both(*args):
    runner = CliRunner()
    text = runner.invoke(app, ["box", "status", *args])
    as_json = runner.invoke(app, ["box", "status", *args, "--json"])
    return text, as_json, json.loads(as_json.stdout)


# ── the shape ───────────────────────────────────────────────────────────────────────────────────

def test_a_valid_proof_carries_its_digest_its_pins_and_its_validity(acme):
    acme()

    text, as_json, document = _both("acme")

    assert set(document) == DOCUMENT_KEYS, (
        f"the document's keys are {sorted(document)}; the contract is {sorted(DOCUMENT_KEYS)} — "
        f"a schema change, and `box_prove.STATUS_SCHEMA` has to move with it")
    assert document["schema"] == bp.STATUS_SCHEMA == "openfactory.box-status/1"
    assert document["valid"] is True and document["state"] == "valid"
    assert document["digest"] == "sha256:" + "a" * 64
    assert document["toolchain"] == TOOLCHAIN.split("\n"), "the pins are not one per line"
    assert document["advisories"] == [{"check": "validate", "message": "security: scan exited 1"}]
    assert document["remedy"] == "" and document["reason"] == ""
    assert as_json.exit_code == text.exit_code == 0


def test_no_proof_is_unproven_with_the_command_that_proves_it(acme):
    text, as_json, document = _both("acme")

    assert document["state"] == "unproven" and document["valid"] is False
    assert document["remedy"] == "run `openfactory box prove acme`"
    assert document["digest"] == "" and document["toolchain"] == []
    assert document["advisories"] is None, "no proof is not a proof with zero advisories"
    assert as_json.exit_code == text.exit_code == 1


def test_another_repository_is_judged_under_its_own_key(acme):
    """Per repository: a foreign repository's proof lives under its own key, and its remedy names
    the `--repo` it needs."""
    text, as_json, document = _both("acme", "--repo", "someorg/web")

    assert document["repository"] == "someorg/web"
    assert document["key"] == "acme--someorg--web"
    assert document["remedy"] == "run `openfactory box prove acme --repo someorg/web`"
    assert as_json.exit_code == text.exit_code == 1


def test_a_moved_image_is_expired_and_says_which_fact_moved(acme):
    acme(digest="sha256:" + "b" * 64)

    text, as_json, document = _both("acme")

    assert document["state"] == "expired" and document["valid"] is False
    assert "changed" in document["reason"] and "box prove acme" in document["reason"]
    assert as_json.exit_code == text.exit_code == 1


def test_a_failed_proof_is_failed_not_expired(acme):
    acme(ok=False)

    text, as_json, document = _both("acme")

    assert document["state"] == "failed"
    assert as_json.exit_code == text.exit_code == 1


def test_legacy_findings_stay_unrecorded_rather_than_empty(acme):
    acme(findings=None)

    _, _, document = _both("acme")

    assert document["valid"] is True
    assert document["advisories"] is None


# ── the lines a person reads did not move ───────────────────────────────────────────────────────

@pytest.mark.parametrize("over,expected", [
    (None, ["acme: no proof — run `openfactory box prove acme`"]),
    ({"ok": False}, ["acme: the proof has EXPIRED — the last proof FAILED",
                     "  run `openfactory box prove acme`"]),
    ({"digest": "sha256:" + "b" * 64},
     ["acme: the proof has EXPIRED — the image ghcr.io/acme/box:1 changed (sha256:bbbbbbbbbbbb… → "
      "sha256:aaaaaaaaaaaa…) — run `openfactory box prove acme`"]),
    ({}, ["acme: proven at 2026-10-01T09:00:00Z on ghcr.io/acme/box:1 (sha256:aaaaaaaaaaaa…)",
          "  toolchain os=debian 12 · python=Python 3.12.5 · node=v22.3.0",
          "  a rebuild that leaves these unchanged does NOT expire this proof",
          "  warn  validate  security: scan exited 1"]),
    ({"toolchain": "", "findings": None},
     ["acme: proven at 2026-10-01T09:00:00Z on ghcr.io/acme/box:1 (sha256:aaaaaaaaaaaa…)",
      "  this image carries no toolchain line, so any rebuild expires the proof — rebuild the box "
      "image to get one (`up -d --build`)",
      "  advisory findings were not recorded for this proof — re-prove to record them"]),
], ids=["unproven", "failed", "expired", "valid", "valid-legacy"])
def test_the_text_report_is_the_one_the_command_always_printed(acme, over, expected):
    """BYTE FOR BYTE, because a person's eye and a person's grep both learned these lines."""
    if over is not None:
        acme(**over)

    result = CliRunner().invoke(app, ["box", "status", "acme"])

    assert result.output.splitlines() == expected


def test_the_document_and_the_lines_come_from_one_status(acme):
    """The JSON's validity is the text's verdict, for every state — the two renderings read ONE
    `BoxStatus`, never two assemblies of the same facts."""
    for over in (None, {"ok": False}, {"digest": "sha256:" + "b" * 64}, {}):
        if over is not None:
            acme(**over)
        text, _, document = _both("acme")
        proven = ": proven at " in text.output
        assert document["valid"] is proven, (over, document["state"], text.output)
