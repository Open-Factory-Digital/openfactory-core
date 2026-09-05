"""The shared walk respects what the repository itself ignores.

MEASURED ON A REAL CLIENT REPOSITORY, 2026-09-05, the first time the inventory ran outside the
suite: git tracked 143 files and the walk saw 448. A Puppeteer-downloaded `chrome/` (288
binaries), every workspace's `dist/` and the developer's own `.env` were all in `.gitignore` —
and `generator._walk_files` pruned by NAME (`node_modules`, `dist`, `.venv`…), which knows nothing
a `.gitignore` says. Four callers share that walk (the module map, the extension survey, the
onboarding survey, `infer`), so all four counted a browser as the client's unread stack, the
inventory called 289 files unclassified, and the credential scan read a file the repository had
declared private.

Now the walk asks git once (`ignored_by_git`) and prunes what it names, before the name-based
skip list; a tree that is not a repository, or a git that will not answer, prunes by name alone
as it always did — and the survey RECORDS the ignored set, so "not inventoried" is a sentence a
reader can check rather than a silence. After: 143 files, 0 unclassified. The one file left
without a rule was a root certificate, which now has a kind of its own.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from openfactory.knowledge import generator
from openfactory.knowledge.generator import _walk_files, ignored_by_git, survey_extensions
from openfactory.knowledge.inventory import (
    WHY_NOT,
    classify,
    render_inventory_md,
    take_inventory,
)
from openfactory.onboarding.context import _collect_files

ROOT = Path(__file__).resolve().parents[1]


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _client_repo(tmp_path: Path) -> Path:
    """The shape that was measured: a tracked app, an ignored browser download, an ignored build
    output, and an ignored `.env` with a real-looking secret in it."""
    repo = tmp_path / "client"
    files = {
        "app.py": "VALUE = 1\n",
        "web/index.html": "<html></html>\n",
        ".gitignore": "chrome/\ndist/\n.env\n",
        "chrome/linux-152/chrome": "\x00binary\x00",
        "chrome/linux-152/resources.pak": "\x00pak\x00",
        "chrome/linux-152/hyphen-data/hyph-af.hyb": "\x00hyb\x00",
        "dist/bundle.min.js": "x",
        ".env": 'AUTH_DEMO_OPERATOR_PASSWORD="hunter2hunter2"\n',
    }
    for rel, body in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t.dev"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    return repo


def _walked(repo: Path) -> list[str]:
    out: list[str] = []
    for rel_dir, names in _walk_files(repo):
        prefix = "" if rel_dir == Path(".") else f"{rel_dir.as_posix()}/"
        out += [f"{prefix}{n}" for n in names]
    return sorted(out)


# --- the question to git -------------------------------------------------------------------

def test_git_names_each_ignored_subtree_once(tmp_path):
    assert ignored_by_git(_client_repo(tmp_path)) == frozenset({"chrome/", "dist/", ".env"})


def test_a_tree_that_is_not_a_repository_declares_nothing(tmp_path):
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "a.py").write_text("x = 1\n")
    assert ignored_by_git(tmp_path / "plain") == frozenset()
    assert ignored_by_git(tmp_path / "nowhere") == frozenset()


# --- the walk --------------------------------------------------------------------------------

def test_the_walk_never_yields_what_the_repository_ignores(tmp_path):
    assert _walked(_client_repo(tmp_path)) == [".gitignore", "app.py", "web/index.html"]


def test_a_tree_that_is_not_a_repository_is_walked_by_name_as_before(tmp_path):
    plain = tmp_path / "plain"
    for rel in ("app.py", "chrome/chrome", "node_modules/x/index.js", "dist/b.js"):
        (plain / rel).parent.mkdir(parents=True, exist_ok=True)
        (plain / rel).write_text("x\n")
    # `node_modules` and `dist` are name-pruned; `chrome/` is nobody's declaration here
    assert _walked(plain) == ["app.py", "chrome/chrome"]


def test_the_caller_may_hand_the_answer_in_so_git_is_asked_once(tmp_path, monkeypatch):
    repo = _client_repo(tmp_path)
    asked: list[Path] = []
    real = generator.ignored_by_git
    monkeypatch.setattr(generator, "ignored_by_git", lambda r: asked.append(r) or real(r))
    list(_walk_files(repo, ignored=frozenset({"chrome/", "dist/", ".env"})))
    assert asked == [], "the walk asked git although the caller had the answer"
    list(_walk_files(repo))
    assert asked == [repo]


def test_the_four_readers_share_the_one_walk():
    """The map, the extension survey, the onboarding survey and `infer` walk the same way, or the
    'files read / files not read' numbers describe four different repositories."""
    callers = 0
    for name in ("openfactory/knowledge/generator.py", "openfactory/onboarding/context.py",
                 "openfactory/onboarding/infer.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        callers += src.count("_walk_files(repo")
        assert src.count("os.walk(") == (1 if name.endswith("generator.py") else 0), (
            f"{name} walks the tree on its own")
    assert callers == 4, callers
    infer = (ROOT / "openfactory/onboarding/infer.py").read_text(encoding="utf-8")
    assert "_walk_files(repo, on_error=on_error, ignored=frozenset())" in infer, (
        "`infer` asks git — and `infer` never runs a command, which is the promise that reads a "
        "stranger's repository safely")


# --- the survey and the inventory --------------------------------------------------------------

def test_the_survey_records_what_it_did_not_walk(tmp_path):
    files = _collect_files(_client_repo(tmp_path), 20_000)
    assert files.ignored == [".env", "chrome/", "dist/"]
    assert "app.py" in files.all and not any(p.startswith("chrome/") for p in files.all)


def test_the_inventory_is_the_repository_not_the_disk(tmp_path):
    taken = take_inventory(_client_repo(tmp_path))
    assert sorted(r.path for r in taken.files) == [".gitignore", "app.py", "web/index.html"]
    assert taken.unclassified == [] and taken.ignored == [".env", "chrome/", "dist/"]
    assert taken.secret_risks == [], "the scan read a file the repository declared private"
    text = render_inventory_md(taken)
    assert "## Not inventoried — what the repository itself ignores" in text
    assert "- `chrome/`" in text and "- `.env`" in text
    assert "hunter2" not in text


def test_the_extension_survey_stops_counting_the_browser(tmp_path):
    survey = survey_extensions(_client_repo(tmp_path))
    assert not any(ext in {".pak", ".hyb"} for ext in survey.unread), survey.unread


# --- the kind that was missing ------------------------------------------------------------

def test_certificate_material_has_a_kind_and_a_private_half_is_a_risk_by_name(tmp_path):
    assert classify("certs/zscaler-root-ca.pem")[0] == "certificate"
    assert classify("certs/server.key") == ("certificate", "`.key` is private key material")
    assert WHY_NOT["certificate"][1] is True, "a certificate is owed a concept"
    repo = tmp_path / "r"
    (repo / "certs").mkdir(parents=True)
    (repo / "certs" / "server.key").write_bytes(b"\x30\x82\x00\x00binary key")
    (repo / "certs" / "root.pem").write_text("-----BEGIN CERTIFICATE-----\nMIIB\n")
    taken = take_inventory(repo)
    risks = {r.path: (r.key, r.severity) for r in taken.secret_risks}
    assert risks == {"certs/server.key": ("private key material", "high")}, risks


def test_generated_and_vendored_literals_are_listed_but_low(tmp_path):
    """A package NAMED `js-tokens` in a lockfile and `password` inside a minified third-party
    bundle are not this repository's secrets; a high on them hides the one that is."""
    repo = tmp_path / "r"
    (repo / "vendor").mkdir(parents=True)
    (repo / "package-lock.json").write_text('{"js-tokens": "abcdefghijk"}\n')
    (repo / "vendor" / "lib.js").write_text('var password="abcdefghijk";\n')
    taken = take_inventory(repo)
    assert {r.path: r.severity for r in taken.secret_risks} == {
        "package-lock.json": "low", "vendor/lib.js": "low"}
