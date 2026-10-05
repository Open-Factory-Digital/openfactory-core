"""`openfactory certify verify <pack.tgz>`: a pack checked offline the way the submissions bot
checks it — its members, its schema, its checksums, its signature, and every threshold, each by id
(#356).

THE CONTRACT, from the issue: exit 0 when everything holds, 1 with a finding per failure, 2 when
the pack cannot be read. The thresholds ship with the core (`openfactory/certify/thresholds.yaml`)
and `--thresholds` replaces them whole. Two rules no thresholds file can bend: an `unknown` control
is never a pass, and an outcome the pack did not measure fails as "not measured", never as zero.
Signing is not built: an unsigned pack is a finding unless `--allow-unsigned`, which exists for a
rehearsal and which the bot never passes.

The packs below are the ones `certify deployment --yes` writes on `certify_bed`'s deployment; a
pack that meets every threshold is that pack with its answers set to passing ones and resealed —
nothing this build's deployment could produce yet, since C-WORKFLOWS, C-BRANCH and C-VERSION read
`unknown` until their reads are built.
"""

from __future__ import annotations

import copy
import io
import json
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfactory.certify import controls as c
from openfactory.certify import pack
from openfactory.certify import verify as v
from tests import certify_bed as bed

FULL = ["--partner", "altiva", "--profile", "standard", "--practitioner", bed.PRACTITIONER]


def _cli(*args: str):
    from openfactory.cli import app

    return CliRunner().invoke(app, ["certify", *args])


@pytest.fixture()
def written(tmp_path, monkeypatch) -> Path:
    """The pack `certify deployment --yes` writes on the bed."""
    bed.build(tmp_path, monkeypatch)
    out = tmp_path / "pack.tgz"
    result = _cli("deployment", *FULL, "--yes", "--out", str(out))
    assert result.exit_code == 0, result.output
    return out


def _lines(output: str) -> list[tuple[str, str, str]]:
    """The result lines as `(mark, id, message)` — the ids are padded to one column."""
    return [tuple(line.split(None, 2)) for line in output.splitlines()
            if line[:2] in ("✓ ", "✗ ", "– ") and len(line.split(None, 2)) == 3]


def _members(path: Path) -> dict[str, bytes]:
    with tarfile.open(path) as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers()}


def _tar(path: Path, files: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def _sealed(files: dict[str, bytes]) -> dict[str, bytes]:
    """The files with `SHA256SUMS` written again over them, as `certify deployment` writes it."""
    out = {k: val for k, val in files.items() if k != pack.SUMS_FILE}
    out[pack.SUMS_FILE] = pack.sha256sums(
        {k: val.decode("utf-8") for k, val in out.items()}).encode()
    return out


def measured(**over) -> dict:
    """An outcomes block that meets every threshold, changed by `over`."""
    block = {
        "status": "measured", "reason": "read", "projects": 2, "jobs": 40,
        "ended": {"merged": 25, "done": 5, "on_hold": 6, "skipped": 2, "failed": 2},
        "past_the_merge": 30, "without_a_recorded_ending": 1,
        "parks": {**dict.fromkeys(("transient", "credential", "environment", "requirement",
                                   "code", "policy", "project", "tree", "gate"), 0),
                  "unknown": 2},
        "cost_per_merged_ticket_usd": {"median": 1.2, "p90": 3.4, "tickets": 28, "unpriced": 2},
        "pickup_to_pr_open_seconds": {"median": 3600.0, "jobs": 30},
        "review_rejections": {"total": 4, "median_per_job": 0.0, "jobs": 40},
        "repair_passes": {"total": 12, "median_per_job": 0.0, "jobs": 38, "unrecorded": 2},
        "needs_action": {"cards": 1, "oldest_days": 3.0},
        "versions": {"seen": [{"version": "0.6.0", "build": "", "attempts": 40}],
                     "unstamped": 0},
        "proof_expiries": None, "reproofs": 3,
        "not_measured": {"proof_expiries": "never recorded"},
    }
    for key, value in over.items():
        block[key] = value
        if value is None:
            block["not_measured"][key] = f"{key} was not read here"
    return block


def passing(document: dict) -> dict:
    """`document` with every answer a passing one."""
    out = copy.deepcopy(document)
    for entry in out["controls"]:
        entry["required"], entry["result"] = True, "pass"
    for proof in out["proofs"]:
        proof["status"] = "valid"
    out["outcomes"] = measured()
    return out


@pytest.fixture()
def good(written, tmp_path) -> Path:
    """The written pack, with passing answers, resealed: everything holds but the signature."""
    files = _members(written)
    files["pack.json"] = json.dumps(passing(json.loads(files["pack.json"]))).encode()
    return _tar(tmp_path / "good.tgz", _sealed(files))


def _thresholds(document: dict, *, profile: str | None = None, held_to=None) -> list[v.Result]:
    bundle = v.Bundle(name="x.tgz", files={}, document=document)
    return [r for r in v.verify(bundle, thresholds=held_to or v.load_thresholds(),
                                profile=profile) if r.id.startswith("T-")]


def _failed(results, ident: str) -> list[str]:
    return [r.message for r in results if r.id == ident and not r.ok]


# ── the command ─────────────────────────────────────────────────────────────────────────────────

def test_the_pack_certify_wrote_holds_together_and_is_unsigned(written):
    result = _cli("verify", str(written))

    assert result.exit_code == 1, result.output
    lines = result.output.splitlines()
    for check in ("contents", "schema", "checksums"):
        assert any(line.startswith(f"✓ {check}") for line in lines), result.output
    assert any(line.startswith("✗ signature") and v.UNSIGNED in line for line in lines)


def test_a_pack_that_meets_every_threshold_exits_0_only_when_unsigned_is_allowed(good):
    unsigned = _cli("verify", str(good))
    rehearsal = _cli("verify", str(good), "--allow-unsigned")

    assert unsigned.exit_code == 1, unsigned.output
    assert [(i, m) for mark, i, m in _lines(unsigned.output) if mark == "✗"] == [
        ("signature", v.UNSIGNED), ("1", "finding(s): this pack does not meet the thresholds.")]
    assert rehearsal.exit_code == 0, rehearsal.output
    assert "– signature" in rehearsal.output and "never passes it" in rehearsal.output
    assert "signature was not checked" in rehearsal.output


def test_every_threshold_is_reported_by_its_id(good):
    output = _cli("verify", str(good), "--allow-unsigned").output

    for threshold in v.load_thresholds():
        assert any(line.startswith(f"✓ {threshold.id} ") for line in output.splitlines()), (
            threshold.id, output)


def test_a_finding_is_one_line_per_failure_under_the_id_of_what_failed(written):
    output = _cli("verify", str(written)).output

    controls = [line for line in output.splitlines() if line.startswith("✗ T-CONTROLS")]
    assert {line.split()[2].rstrip(":") for line in controls} >= set(c.NOT_BUILT), output


@pytest.mark.parametrize("make", [
    lambda d: d / "absent.tgz",
    lambda d: (d / "plain.tgz").write_text("not a tarball") and d / "plain.tgz",
    lambda d: _tar(d / "nojson.tgz", {"summary.md": b"# a pack"}),
    lambda d: _tar(d / "badjson.tgz", {"pack.json": b"{not json"}),
    lambda d: _tar(d / "list.tgz", {"pack.json": b"[]"}),
])
def test_a_pack_that_cannot_be_read_exits_2_and_judges_nothing(tmp_path, make):
    result = _cli("verify", str(make(tmp_path)))

    assert result.exit_code == 2, result.output
    assert "cannot be read" in result.output and "T-" not in result.output


# ── the pack itself ─────────────────────────────────────────────────────────────────────────────

def test_a_diagnostic_changed_after_writing_fails_both_lists(written, tmp_path):
    files = _members(written)
    name = next(n for n in files if n.startswith("diagnostics/"))
    files[name] += b"\nedited"

    results = v.verify(v.read(_tar(tmp_path / "x.tgz", files)), thresholds=[])

    said = [r.message for r in results if r.id == "checksums" and not r.ok]
    assert f"{name}: its SHA-256 is not the one SHA256SUMS lists" in said
    assert f"{name}: its SHA-256 is not the one pack.json lists" in said


def test_a_pack_json_changed_after_writing_is_caught_by_sha256sums(written, tmp_path):
    """`pack.json` cannot list its own digest; `SHA256SUMS` is what covers it."""
    files = _members(written)
    document = json.loads(files["pack.json"])
    document["practitioner"] = "Somebody Else"
    files["pack.json"] = json.dumps(document).encode()

    results = v.verify(v.read(_tar(tmp_path / "x.tgz", files)), thresholds=[])

    assert [r.message for r in results if r.id == "checksums" and not r.ok] == [
        "pack.json: its SHA-256 is not the one SHA256SUMS lists"]


def test_a_file_slipped_in_or_taken_out_is_a_finding(written, tmp_path):
    files = _members(written)
    files["extra.txt"] = b"hello"
    gone = next(n for n in files if n.startswith("diagnostics/"))
    del files[gone]

    said = [r.message for r in v.verify(v.read(_tar(tmp_path / "x.tgz", files)), thresholds=[])
            if r.id == "checksums" and not r.ok]

    assert "extra.txt: in the pack and not listed in SHA256SUMS" in said
    assert "extra.txt: not listed in pack.json's checksums" in said
    assert f"{gone}: listed in SHA256SUMS and not in the pack" in said
    assert f"{gone}: listed in pack.json's checksums and not in the pack" in said


def test_a_pack_without_sha256sums_is_a_finding(written, tmp_path):
    files = _members(written)
    del files[pack.SUMS_FILE]

    results = v.verify(v.read(_tar(tmp_path / "x.tgz", files)), thresholds=[])

    assert "the pack carries no SHA256SUMS" in [r.message for r in results if not r.ok]


def test_a_member_that_is_not_a_plain_file_is_a_finding(written, tmp_path):
    out = tmp_path / "x.tgz"
    with tarfile.open(written) as src, tarfile.open(out, "w:gz") as tar:
        for member in src.getmembers():
            tar.addfile(member, src.extractfile(member))
        link = tarfile.TarInfo("diagnostics/elsewhere")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(link)

    said = [r.message for r in v.verify(v.read(out), thresholds=[]) if r.id == "contents"]

    assert said == ["diagnostics/elsewhere: not a regular file"]


def test_a_schema_violation_is_one_finding_per_error(written, tmp_path):
    files = _members(written)
    document = json.loads(files["pack.json"])
    document["extra"] = 1
    del document["salt_id"]
    files["pack.json"] = json.dumps(document).encode()

    results = v.verify(v.read(_tar(tmp_path / "x.tgz", _sealed(files))), thresholds=[])

    said = [r.message for r in results if r.id == "schema"]
    assert any("'extra' is not part of the schema" in m for m in said)
    assert any("missing 'salt_id'" in m for m in said)
    assert all(r.ok for r in results if r.id == "checksums")


def test_a_present_signature_this_build_cannot_check_is_a_finding_too(written, tmp_path):
    files = _members(written)
    files["pack.sig"] = b"untrusted comment: nothing"

    said = [(r.ok, r.message) for r in v.verify(v.read(_tar(tmp_path / "x.tgz", files)),
                                                 thresholds=[]) if r.id == "signature"]

    assert said == [(False, "pack.sig is present and this build cannot check a signature "
                            "(signing is not built yet)")]


# ── the thresholds ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def document(written) -> dict:
    return passing(json.loads(_members(written)["pack.json"]))


def test_the_passing_document_passes_every_threshold(document):
    assert [r for r in _thresholds(document) if not r.ok] == []


def test_an_unknown_control_is_never_a_pass(document):
    entry = next(e for e in document["controls"] if e["id"] == "C-WORKFLOWS")
    entry["result"] = "unknown"

    results = _thresholds(document)

    assert _failed(results, "T-CONTROLS") == [
        f"C-WORKFLOWS: unknown — {entry['evidence']['detail']}"]
    assert not _failed(results, "T-SECURITY"), "unknown is not a failure — it is not a pass"


def test_no_thresholds_file_can_make_unknown_a_pass(document, tmp_path):
    lax = tmp_path / "lax.yaml"
    lax.write_text(f"schema: {v.THRESHOLDS_SCHEMA}\nthresholds:\n"
                   "  - {id: T-CONTROLS, check: required_controls, accept: [pass, unknown]}\n")
    with pytest.raises(v.ThresholdsError, match="accept"):
        v.load_thresholds(lax)

    next(e for e in document["controls"] if e["id"] == "C-BRANCH")["result"] = "unknown"
    forged = [v.Threshold("T-CONTROLS", "required_controls", {"accept": ["pass", "unknown"]})]
    assert _failed(_thresholds(document, held_to=forged), "T-CONTROLS")


def test_what_is_required_is_the_profile_table_never_the_packs_own_flags(document):
    entry = next(e for e in document["controls"] if e["id"] == "C-BRANCH")
    entry["required"], entry["result"] = False, "n/a"

    assert _failed(_thresholds(document, profile="standard"), "T-CONTROLS")[0].startswith(
        "C-BRANCH: n/a")
    assert not _failed(_thresholds(document, profile="light"), "T-CONTROLS")


@pytest.mark.parametrize("profile", sorted(c.PROFILES))
def test_a_security_control_that_fails_is_a_finding_on_every_profile(document, profile):
    for ident in c.SECURITY_CONTROLS:
        broken = copy.deepcopy(document)
        next(e for e in broken["controls"] if e["id"] == ident)["result"] = "fail"

        assert _failed(_thresholds(broken, profile=profile), "T-SECURITY")[0].startswith(
            f"{ident}: fail"), (ident, profile)


@pytest.mark.parametrize("jobs,ok", [(20, True), (19, False)])
def test_twenty_jobs_meet_the_threshold(document, jobs, ok):
    document["outcomes"] = measured(jobs=jobs, past_the_merge=jobs)

    assert (not _failed(_thresholds(document), "T-JOBS")) is ok


@pytest.mark.parametrize("merged,ok", [(10, True), (9, False)])
def test_half_the_jobs_reach_the_merge(document, merged, ok):
    document["outcomes"] = measured(jobs=20, past_the_merge=merged)

    assert (not _failed(_thresholds(document), "T-MERGED")) is ok


@pytest.mark.parametrize("unknown,ok", [(1, True), (2, False)])
def test_unclassified_parks_stay_under_a_tenth_of_the_jobs(document, unknown, ok):
    block = measured(jobs=20, past_the_merge=20)
    block["parks"]["unknown"] = unknown
    document["outcomes"] = block

    assert (not _failed(_thresholds(document), "T-UNKNOWN-PARKS")) is ok


@pytest.mark.parametrize("days,ok", [(7.0, True), (7.1, False)])
def test_no_card_waits_more_than_seven_days_in_needs_action(document, days, ok):
    document["outcomes"] = measured(needs_action={"cards": 2, "oldest_days": days})

    assert (not _failed(_thresholds(document), "T-NEEDS-ACTION")) is ok


def test_an_outcome_not_measured_fails_as_not_measured_never_as_zero(document):
    document["outcomes"] = measured(jobs=None, parks=None, needs_action=None)

    results = _thresholds(document)

    for ident in ("T-JOBS", "T-MERGED", "T-UNKNOWN-PARKS", "T-NEEDS-ACTION"):
        said = _failed(results, ident)
        assert len(said) == 1 and "not measured — " in said[0], (ident, said)
        assert "0 job" not in said[0] and " 0 " not in said[0]
    assert _failed(results, "T-JOBS") == ["jobs: not measured — jobs was not read here"]


def test_no_job_in_the_window_is_no_share_of_them(document):
    document["outcomes"] = measured(jobs=0, past_the_merge=0)

    results = _thresholds(document)

    assert _failed(results, "T-MERGED") == ["no job ended in the window, so no share of them "
                                            "merged"]
    assert _failed(results, "T-UNKNOWN-PARKS")


def test_every_proof_is_valid_and_a_pack_with_none_fails(document):
    document["proofs"][0]["status"] = "expired"
    assert _failed(_thresholds(document), "T-PROOFS")[0].endswith(": expired")

    document["proofs"] = []
    assert _failed(_thresholds(document), "T-PROOFS") == ["the pack carries no box proof"]


def test_the_version_threshold_is_c_version(document):
    entry = next(e for e in document["controls"] if e["id"] == "C-VERSION")
    entry["result"] = "unknown"

    assert _failed(_thresholds(document), "T-VERSION")[0].startswith("C-VERSION: unknown")


def test_a_practitioner_of_whitespace_names_nobody(document):
    document["practitioner"] = "   "

    assert _failed(_thresholds(document), "T-PRACTITIONER") == [
        "the pack names no practitioner (--practitioner)"]


# ── the thresholds file ─────────────────────────────────────────────────────────────────────────

def test_the_shipped_thresholds_are_the_issues_numbers():
    shipped = {t.id: t for t in v.load_thresholds()}

    assert set(shipped) == {"T-CONTROLS", "T-SECURITY", "T-JOBS", "T-MERGED", "T-UNKNOWN-PARKS",
                            "T-NEEDS-ACTION", "T-PROOFS", "T-VERSION", "T-PRACTITIONER"}
    assert shipped["T-JOBS"].params == {"min": 20}
    assert shipped["T-MERGED"].params == {"min": 0.5}
    assert shipped["T-UNKNOWN-PARKS"].params == {"share": 0.1}
    assert shipped["T-NEEDS-ACTION"].params == {"days": 7}
    assert tuple(shipped["T-SECURITY"].params["controls"]) == c.SECURITY_CONTROLS
    assert set(shipped["T-CONTROLS"].params["accept"]) <= {"pass", "info"}


def test_a_thresholds_file_replaces_the_defaults_whole(good, tmp_path):
    mine = tmp_path / "mine.yaml"
    mine.write_text(f"schema: {v.THRESHOLDS_SCHEMA}\nthresholds:\n"
                    "  - {id: T-JOBS, check: min_jobs, min: 41}\n")

    result = _cli("verify", str(good), "--allow-unsigned", "--thresholds", str(mine))

    assert result.exit_code == 1, result.output
    assert ("✗", "T-JOBS", "40 job(s) ended in the window; at least 41 are required") in \
        _lines(result.output)
    assert "T-CONTROLS" not in result.output


@pytest.mark.parametrize("body,said", [
    ("schema: something/1\nthresholds: []\n", "schema"),
    (f"schema: {v.THRESHOLDS_SCHEMA}\nthresholds: []\n", "no thresholds"),
    (f"schema: {v.THRESHOLDS_SCHEMA}\nthresholds:\n  - {{id: T-X, check: vibes}}\n",
     "not a check"),
    (f"schema: {v.THRESHOLDS_SCHEMA}\nthresholds:\n  - {{id: T-X, check: min_jobs}}\n",
     "needs `min`"),
    (f"schema: {v.THRESHOLDS_SCHEMA}\nthresholds:\n  - {{id: T-X, check: min_jobs, min: 2, "
     f"max: 3}}\n", "takes no `max`"),
    (f"schema: {v.THRESHOLDS_SCHEMA}\nthresholds:\n  - {{id: T-X, check: min_jobs, min: '20'}}\n",
     "a whole number"),
    (f"schema: {v.THRESHOLDS_SCHEMA}\nthresholds:\n  - {{id: T-X, check: min_merged_share, "
     f"min: 2}}\n", "from 0 to 1"),
    (f"schema: {v.THRESHOLDS_SCHEMA}\nthresholds:\n  - {{id: T-X, check: never_fail, "
     f"controls: [C-NOPE]}}\n", "a non-empty list"),
    (f"schema: {v.THRESHOLDS_SCHEMA}\nthresholds:\n  - {{id: T-X, check: proofs_current}}\n"
     f"  - {{id: T-X, check: proofs_current}}\n", "twice"),
    (f"schema: {v.THRESHOLDS_SCHEMA}\nthresholds:\n  - {{id: jobs, check: proofs_current}}\n",
     "T-JOBS"),
])
def test_a_thresholds_file_this_build_cannot_enforce_is_refused(tmp_path, body, said):
    path = tmp_path / "t.yaml"
    path.write_text(body)

    with pytest.raises(v.ThresholdsError, match=said.replace("`", ".")):
        v.load_thresholds(path)


def test_a_thresholds_file_that_cannot_be_used_exits_2_before_the_pack_is_judged(good, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(f"schema: {v.THRESHOLDS_SCHEMA}\nthresholds:\n  - {{id: T-X, check: vibes}}\n")

    result = _cli("verify", str(good), "--thresholds", str(bad))

    assert result.exit_code == 2 and "No pack was judged" in result.output
    assert "✓" not in result.output


def test_an_unknown_profile_is_refused_by_name(good):
    result = _cli("verify", str(good), "--profile", "gold")

    assert result.exit_code == 2 and result.output.startswith("✗ --profile ")


def test_a_pack_is_verified_as_another_profile_when_asked(tmp_path, monkeypatch):
    """A `light` pack was not evaluated for `standard`: the controls light does not require read
    `n/a`, and `n/a` is not a pass."""
    bed.build(tmp_path, monkeypatch)
    out = tmp_path / "light.tgz"
    assert _cli("deployment", "--partner", "altiva", "--profile", "light", "--practitioner",
                bed.PRACTITIONER, "--yes", "--out", str(out)).exit_code == 0

    result = _cli("verify", str(out), "--profile", "standard")

    assert "profile light (verified as standard)" in result.output
    assert any(mark == "✗" and i == "T-CONTROLS" and m.startswith("C-TEST: n/a")
               for mark, i, m in _lines(result.output)), result.output
