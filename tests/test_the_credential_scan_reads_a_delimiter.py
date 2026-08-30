"""The floor's credential scan, against a vendored base64 bundle and against real credentials.

THE DEFECT (#11). A client vendoring `opencv.js` — 8.3 MB of minified WebAssembly on 47 lines, the
binary embedded as a base64 string literal — had every card on the project held. Base64 of
arbitrary bytes eventually contains an uppercase/digit run satisfying `(AKIA|ASIA)[0-9A-Z]{16}`,
and one did. Ten real repositories were measured clean when the pattern was written; the eleventh
was a Django app that vendors a library.

The consequence was larger than a noisy line: the gate is `advisory: true`, so it cannot block a
merge — but `box prove`'s `validate` station demands `rc == 0` from every repo-wide gate on
untouched main, and `gate_reason` consults that proof before a card is taken. No ticket on that
project could start.

THESE RUN THE ACTUAL COMMAND FROM `floor.yaml` AGAINST REAL GIT REPOSITORIES. A test that
re-implemented the pattern would prove something about the test. The command is read out of the
file the fleet inherits, handed to `sh`, and its exit code and output are the assertions — which is
also what makes them a regression guard rather than a description of one.
"""

from __future__ import annotations

import base64
import random
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

FLOOR = Path(__file__).resolve().parent.parent / "openfactory" / "org_defaults" / "floor.yaml"

pytestmark = pytest.mark.skipif(shutil.which("git") is None,
                                reason="the floor's scan is a shell command over a real git tree")


def _command() -> str:
    """The gate exactly as the fleet inherits it."""
    return yaml.safe_load(FLOOR.read_text(encoding="utf-8"))["validate"]["security"]["command"]


def _repo(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(body, encoding="utf-8")
    for args in (["init", "-q", "."], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["add", "-A"],
                 ["-c", "commit.gpgsign=false", "commit", "-qm", "x"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return root


def _scan(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", "-c", _command()], cwd=repo, capture_output=True, text=True)


def _vendored_bundle() -> str:
    """A minified bundle with a WASM binary inline, the shape #11 reports. The seed is pinned so
    the uppercase/digit run that trips the bare pattern is there every time — a fixture that only
    sometimes contains the collision would only sometimes be a guard."""
    random.seed(7)
    blob = base64.b64encode(bytes(random.getrandbits(8) for _ in range(400))).decode()
    blob = blob[:120] + "ASIAJQAAVSUAAPGLAACJ" + blob[140:]
    return 'var Module={};var wasmBinary="' + blob + '";\n'


def _base64_value_that_spells_it() -> str:
    """A short base64 VALUE whose whole content happens to spell the pattern, then padding.

    THE ONLY SHAPE IN WHICH THE TRAILING CLASS DECIDES ANYTHING, which is why it needs a fixture of
    its own and why two earlier attempts at one did not work. Inside a long blob the run is
    preceded by more base64, so the LEADING delimiter has already rejected it and the trailing
    class is never consulted — a mutation loosening it changed nothing and survived twice.

    The trailing class only speaks when the run begins right after a delimiter and the character
    that follows is `=`: base64 padding, meaning a value that ended, not an identifier somebody
    assigned. A real AWS key id is exactly twenty characters and is never followed by padding."""
    return '{"checksum": "ASIAJQAAVSUAAPGLAACJ="}\n'


# ── the defect ───────────────────────────────────────────────────────────────────────────────────

def test_a_vendored_base64_bundle_does_not_hold_a_project(tmp_path: Path) -> None:
    """#11, reproduced and closed. Nothing in this repository is a credential; before the delimiter
    the scan exited 1, `box prove` failed its validate station, and every card was held."""
    result = _scan(_repo(tmp_path / "vendored", {"static/js/vendor/opencv.js": _vendored_bundle()}))

    assert result.returncode == 0, result.stdout
    assert "credential is committed" not in result.stdout


def test_the_fixture_really_does_contain_the_collision(tmp_path: Path) -> None:
    """The control for the guard above. If the bundle stopped containing a run that satisfies the
    bare pattern, the test would pass for the wrong reason and go on passing for ever."""
    repo = _repo(tmp_path / "raw", {"vendor.min.js": _vendored_bundle()})
    bare = subprocess.run(
        ["git", "grep", "-nIE", "(AKIA|ASIA)[0-9A-Z]{16}", "--", "."],
        cwd=repo, capture_output=True, text=True)

    assert bare.returncode == 0, "the fixture no longer trips the undelimited pattern"


# ── and the real credentials still get caught ────────────────────────────────────────────────────

@pytest.mark.parametrize(("name", "line"), [
    # `=` is the commonest separator in the file a real key is likeliest to live in, and it is also
    # base64's padding. A symmetric character class dropped every one of these along with the
    # bundle — the false-negative risk this direction was warned about, arriving immediately.
    (".env", "AWS_ACCESS_KEY_ID=AKIAQYLPMN5HHHFPZAAA\n"),
    ("conf.yaml", 'aws:\n  key: "ASIAQYLPMN5HHHFPZAAB"\n'),
    ("trailing.txt", "key=AKIAQYLPMN5HHHFPZAAC\n"),          # at end of line
    ("lead.txt", "AKIAQYLPMN5HHHFPZAAD is the id\n"),        # at start of line
    ("google.txt", "GOOGLE_API_KEY=AIzaSyD-9tSrke72PouQMnMX-a7eZSW0jkFMBWY\n"),
    ("gh.txt", "token=ghp_abcdefghijklmnopqrstuvwxyz0123456789\n"),
    ("key.pem", "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n"),
])
def test_a_committed_credential_is_still_found(tmp_path: Path, name: str, line: str) -> None:
    """Every shape the gate has ever caught, kept caught. Delimiting is only worth anything if it
    costs no true positive, and a false negative is the more expensive error for this gate."""
    result = _scan(_repo(tmp_path / name.replace("/", "_"), {name: line}))

    assert result.returncode == 1, f"{name}: a real credential went unreported"
    assert "credential is committed" in result.stdout


def test_awss_own_documented_example_is_still_dropped(tmp_path: Path) -> None:
    """The second stage, unchanged: `AKIAIOSFODNN7EXAMPLE` in a README must not hold a pickup."""
    result = _scan(_repo(tmp_path / "example",
                         {"README.md": "export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"}))

    assert result.returncode == 0, result.stdout


def test_a_real_key_beside_a_vendored_bundle_is_still_found(tmp_path: Path) -> None:
    """The case that would make this fix dangerous if it were a path exclusion instead: the
    repository that has both. First-party code stays scanned."""
    result = _scan(_repo(tmp_path / "both", {
        "static/js/vendor/opencv.js": _vendored_bundle(),
        ".env": "AWS_ACCESS_KEY_ID=AKIAQYLPMN5HHHFPZAAE\n"}))

    assert result.returncode == 1
    assert ".env" in result.stdout
    assert "opencv.js" not in result.stdout


# ── what was deliberately left alone ─────────────────────────────────────────────────────────────

def test_only_the_two_base64_alphabet_patterns_are_delimited() -> None:
    """Eight of the ten patterns require a `_`, a `-`, a literal `AccountKey=` or a `^` anchor —
    none of which base64 contains — so they cannot false-positive on a blob and are safe by
    construction. Delimiting them would buy nothing and risk a false negative.

    Asserted on the command the fleet inherits, so a later edit that delimits everything "for
    consistency" has to argue with this."""
    command = _command()

    assert command.count("(^|[^0-9A-Za-z+/])") == 2, (
        "exactly the AWS and Google patterns are delimited — no more, no fewer")
    assert "(^|[^0-9A-Za-z+/])(AKIA|ASIA)" in command
    assert "(^|[^0-9A-Za-z+/])AIza" in command


def test_the_scan_that_could_not_run_still_refuses_to_read_as_clean(tmp_path: Path) -> None:
    """Untouched, and worth pinning while the command is being edited: `git grep` exiting above 1
    is a scan that could not look, and it must not come back 0. A directory that is not a
    repository is the cheapest way to produce that."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    result = _scan(plain)

    assert result.returncode > 1
    assert "could not run" in result.stdout


def test_a_clean_repository_passes(tmp_path: Path) -> None:
    """The control. Without it a scan that refused everything would satisfy every guard here."""
    result = _scan(_repo(tmp_path / "clean", {"app.py": "def f():\n    return 1\n"}))

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_a_collision_at_the_END_of_a_blob_is_not_a_credential(tmp_path: Path) -> None:
    """`=` is base64's padding, so a run followed by `=` is a run inside a blob that just ended —
    not a value somebody assigned. Allowing `=` on the trailing side brings the false positive back
    for the commonest shape of it, because every blob ends somewhere."""
    result = _scan(_repo(tmp_path / "padded",
                         {"lockfile.json": _base64_value_that_spells_it()}))

    assert result.returncode == 0, result.stdout


def test_a_credential_committed_INSIDE_a_vendored_path_is_still_found(tmp_path: Path) -> None:
    """THE REASON THIS IS A DELIMITER AND NOT A PATH EXCLUSION. Excluding `*/vendor/*` and
    `*.min.js` is predictable and cheap, and it silently stops scanning places where a credential
    can genuinely be committed — a patched vendor file, a built bundle with a key baked in by a
    misconfigured pipeline. The delimiter keeps every file scanned and rejects only what base64
    can spell."""
    result = _scan(_repo(tmp_path / "invendor", {
        "static/js/vendor/config.js": 'var key = "AKIAQYLPMN5HHHFPZAAF";\n',
        "app.min.js": "var t=\'ghp_abcdefghijklmnopqrstuvwxyz0123456789\';\n"}))

    assert result.returncode == 1, "a real credential in a vendored path went unreported"
    assert "vendor/config.js" in result.stdout
    assert "app.min.js" in result.stdout


def test_twenty_characters_is_the_accepted_assumption(tmp_path: Path) -> None:
    """THE BOUND THE DELIMITER COSTS, pinned so it is a known limit rather than a discovered one.

    AWS documents an access key id as 16-128 characters; every issued one anybody here has seen is
    exactly 20, and this pattern has always assumed 20. The delimiter makes that assumption BITE: a
    21-character run was caught by the bare pattern and is quiet now, because the character after
    the twentieth is alphanumeric and the trailing class refuses it.

    Kept deliberately — the false positive it buys back is real and measured, a longer id is
    theoretical — and asserted so that a future report of a missed key lands on this guard rather
    than on a surprise (review, 2026-08-30)."""
    repo = _repo(tmp_path / "twentyone", {"a.sh": "export AWS_KEY=AKIAY7QWERTYUIOPASDF0\n"})

    bare = subprocess.run(["git", "grep", "-nIE", "(AKIA|ASIA)[0-9A-Z]{16}", "--", "."],
                          cwd=repo, capture_output=True, text=True)

    assert bare.returncode == 0, "the fixture must be caught by the undelimited pattern"
    assert _scan(repo).returncode == 0, (
        "a 21-character run is quiet by design — if this goes red the assumption changed, and the "
        "comment block in floor.yaml is where to start")
