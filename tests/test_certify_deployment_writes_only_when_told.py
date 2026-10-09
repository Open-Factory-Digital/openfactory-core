"""`openfactory certify deployment`: what it refuses, what it prints, and when it writes (#356).

THE COMMAND'S CONTRACT, from the issue: `--partner`, `--profile` and `--practitioner` have no
default and a refusal names the flag (with its cause and its remedy, `cli_refusals.py`'s rule);
`--dry-run` prints the entire pack and writes nothing; without `--yes` nothing is written; `--yes`
writes a tarball whose `pack.json` validates against the published schema and whose checksums
are the files beside it. And what is not built yet is SAID — in the pack and its summary — rather
than filled in: no signature, outcomes not measured. A forge read that could not be made reads
`unknown`, never `pass`.
"""

from __future__ import annotations

import hashlib
import json
import tarfile

import pytest
from typer.testing import CliRunner

from openfactory.certify import pack
from openfactory.certify.schema import validate
from tests import certify_bed as bed

FULL = ["--partner", "altiva", "--profile", "standard", "--practitioner", bed.PRACTITIONER]


def _invoke(*args: str):
    from openfactory.cli import app

    return CliRunner().invoke(app, ["certify", "deployment", *args])


@pytest.fixture()
def nothing_is_read(monkeypatch):
    """A refusal is asked BEFORE anything is read: gathering here is a failure of the test."""
    def refuse(**_kw):
        raise AssertionError("certify read the deployment before refusing its flags")
    monkeypatch.setattr(pack, "gather", refuse)


# ── the refusals ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("missing", ["--partner", "--profile", "--practitioner"])
def test_a_required_flag_left_out_is_refused_by_name(missing, nothing_is_read):
    args = [a for i, a in enumerate(FULL)
            if a != missing and (i == 0 or FULL[i - 1] != missing)]

    result = _invoke(*args)

    assert result.exit_code == 2, result.output
    assert f"✗ {missing} is required" in result.output, result.output
    assert "pass" in result.output.split("\n\n", 1)[1], "the refusal names no remedy"


def test_an_empty_practitioner_is_no_practitioner(nothing_is_read):
    result = _invoke("--partner", "altiva", "--profile", "light", "--practitioner", "   ")

    assert result.exit_code == 2 and "✗ --practitioner is required" in result.output


@pytest.mark.parametrize("args,flag", [
    (["--partner", "Altiva AI", "--profile", "light", "--practitioner", "x"], "--partner"),
    (["--partner", "altiva", "--profile", "gold", "--practitioner", "x"], "--profile"),
    (["--partner", "altiva", "--profile", "light", "--practitioner", "x", "--window-days", "0"],
     "--window-days"),
    (["--partner", "altiva", "--profile", "light", "--practitioner", "x", "--consent", "Ana"],
     "--consent"),
])
def test_a_flag_with_a_value_it_cannot_take_is_refused_by_name(args, flag, nothing_is_read):
    result = _invoke(*args)

    assert result.exit_code == 2, result.output
    assert result.output.startswith(f"✗ {flag} "), result.output


# ── printing and writing ────────────────────────────────────────────────────────────────────────

def _listing(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_dry_run_prints_the_entire_pack_and_writes_nothing(tmp_path, monkeypatch):
    deploy = bed.build(tmp_path, monkeypatch)
    before = _listing(tmp_path)

    result = _invoke(*FULL, "--dry-run")

    assert result.exit_code == 0, result.output
    assert _listing(tmp_path) == before, "a dry run wrote something"
    files = bed.files_of(result.output)
    document = bed.pack_json(files)
    assert set(document["checksums"]) | {"pack.json"} == set(files), (
        "the dry run did not print every file the pack holds")
    assert "nothing was written" in result.output
    assert not list(deploy.glob("*.tgz"))


def test_without_yes_nothing_is_written_and_it_says_how_to_write(tmp_path, monkeypatch):
    bed.build(tmp_path, monkeypatch)
    before = _listing(tmp_path)

    result = _invoke(*FULL)

    assert result.exit_code == 2, result.output
    assert _listing(tmp_path) == before
    assert "# OpenFactory deployment evidence pack" in result.output
    assert "Nothing was written. Re-run with --yes" in result.output


def test_yes_writes_a_tarball_that_validates_and_whose_checksums_hold(tmp_path, monkeypatch):
    deploy = bed.build(tmp_path, monkeypatch)

    result = _invoke(*FULL, "--yes")

    assert result.exit_code == 0, result.output
    written = list(deploy.glob("openfactory-evidence-*.tgz"))
    assert len(written) == 1, result.output
    with tarfile.open(written[0]) as tar:
        files = {m.name: tar.extractfile(m).read() for m in tar.getmembers()}
    document = json.loads(files["pack.json"])
    assert validate(document) == []
    assert written[0].name == f"openfactory-evidence-{document['salt_id']}-" \
                              f"{document['generated_at'][:10]}.tgz"
    for name, digest in document["checksums"].items():
        assert digest == "sha256:" + hashlib.sha256(files[name]).hexdigest(), name
    assert set(files) == set(document["checksums"]) | {"pack.json"}
    assert "pack.sig" not in files, "a signature this slice cannot make"


def test_an_existing_file_is_never_replaced(tmp_path, monkeypatch):
    bed.build(tmp_path, monkeypatch)
    out = tmp_path / "pack.tgz"
    out.write_text("somebody's earlier pack")

    result = _invoke(*FULL, "--yes", "--out", str(out))

    assert result.exit_code == 1
    assert out.read_text() == "somebody's earlier pack"


# ── what this slice does not do, said rather than filled in ─────────────────────────────────────

def test_what_the_pack_does_not_contain_is_said_in_it(tmp_path, monkeypatch):
    bed.build(tmp_path, monkeypatch)

    files = bed.files_of(_invoke(*FULL, "--dry-run").output)
    document = bed.pack_json(files)

    assert document["signature"] is None and document["unsigned_because"].strip()
    assert document["outcomes"]["status"] == "not_measured", (
        "outcomes were reported as measured — zeros read as a deployment that did nothing")
    assert document["outcomes"]["reason"].strip()
    summary = files["summary.md"]
    assert "## What this pack does not contain yet" in summary
    for gap in ("signature", "outcome aggregates"):
        assert gap in summary, f"the summary does not say the pack lacks {gap}"
    assert not [g for g in document["not_in_this_pack"] if "C-" in g], (
        "the pack still says a control is not read — the forge and releases reads are built")
    assert summary.index("does not contain yet") < summary.index("## Controls"), (
        "what is missing is said after the results, where a reader has already decided")


def test_a_forge_that_refuses_every_read_leaves_its_controls_unknown_never_pass(tmp_path,
                                                                                 monkeypatch):
    """The forge's branch protection, the credential's grants, the releases list, each refused —
    a credential without the scope to ask: on a deployment where everything else is green, those
    three say `unknown`."""
    bed.build(tmp_path, monkeypatch)
    no = bed.refused("Resource not accessible by personal access token", 403)
    bed.forge_answers(monkeypatch, rules=no, branch=no, settings=no, scopes=no, releases=no)

    for profile in ("standard", "enterprise"):
        document = bed.pack_json(bed.files_of(_invoke(
            "--partner", "altiva", "--profile", profile, "--practitioner", "x",
            "--dry-run").output))
        results = {x["id"]: x for x in document["controls"]}
        for control in ("C-WORKFLOWS", "C-BRANCH", "C-VERSION"):
            assert results[control]["result"] == "unknown", results[control]
            assert "could not be read" in results[control]["evidence"]["detail"]


def test_every_control_is_computed_from_what_the_deployment_and_its_forge_say(tmp_path,
                                                                             monkeypatch):
    """Every control answers from the deployment — none of them falls back to `unknown` on a
    deployment that has everything they read, the forge's three reads included."""
    bed.build(tmp_path, monkeypatch)

    document = bed.pack_json(bed.files_of(_invoke(*FULL, "--dry-run").output))

    results = {x["id"]: x["result"] for x in document["controls"]}
    assert {k: v for k, v in results.items() if v == "unknown"} == {}
    assert results["C-BRANCH"] == "pass" and results["C-WORKFLOWS"] == "pass"
    assert results["C-VERSION"] == "fail", "a development build passed as a release"
    assert results["C-PANEL"] == "pass" and results["C-ENVFILE"] == "pass"
    assert results["C-BOX-ENV"] == "fail", "a project with no box.env passed the allow list"
    assert results["C-PROOF"] == "fail", "an unproven repository passed the proof control"
