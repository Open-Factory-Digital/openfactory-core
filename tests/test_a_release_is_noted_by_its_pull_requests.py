"""A release's notes are assembled from a line each pull request carries (#517).

WHAT WAS MISSING. A release's notes were drafted by hand at the cut, from the milestone's merged
pull requests (docs/RELEASING.md, "Before the cut"), and they lived only on the GitHub release
page: not in the tree, not greppable, never reviewed beside the change they describe. Drafting
them was also the one step of the process an agent could get subtly wrong. Raised in the review
of #510.

Now each pull request carries its line as a FRAGMENT, `changes/<issue>.<type>.md`, and
`scripts/release_notes.py` does the rest. This file runs it offline, with fake inputs:

  check     a pull request adds or edits a fragment, or carries the label `no-release-note`;
            every fragment is well formed; a final version is declared only with its notes
  assemble  the version's section goes to the top of CHANGELOG.md, the fragments it used are
            removed, and what it prints is what the release page carries
  page      a final's page reads CHANGELOG.md, a candidate's the fragments, and neither ever
            fails the release run, which by then has published the images under the tag
  the CI    `.github/workflows/release-note.yml`'s own step, run in a repository whose HEAD is
            a pull request's merge commit, as GitHub builds it
  the docs  every command they give is one the script has; the types and the label are its own
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release_notes.py"
PAGE_SCRIPT = ROOT / "scripts" / "release-page-body.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "release-note.yml"
RELEASING = ROOT / "docs" / "RELEASING.md"
AGENT = ROOT / ".claude" / "agents" / "release-manager.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"

PREAMBLE = "# Changelog\n\nWhat changed in each release, newest first.\n"


def _load():
    """The script as a module, for the values it EXPORTS: its types and its label."""
    spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["release_notes"] = module          # a dataclass looks its module up by name
    spec.loader.exec_module(module)
    return module


NOTES = _load()
LABEL = NOTES.LABEL
TYPES = dict(NOTES.TYPES)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """The root of a checkout, as far as the script reads one: on `main`, between two releases."""
    (tmp_path / "changes").mkdir()
    (tmp_path / "CHANGELOG.md").write_text(PREAMBLE)
    _declare(tmp_path, "0.7.0.dev0")
    return tmp_path


def _declare(tree: Path, version: str) -> None:
    (tree / "pyproject.toml").write_text(f'[project]\nname = "openfactory"\nversion = "{version}"\n')


def _fragment(tree: Path, name: str, text: str) -> Path:
    path = tree / "changes" / name
    path.write_text(text + "\n")
    return path


def _run(tree: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=tree, input=stdin,
                          capture_output=True, text=True, timeout=60)


def _check(tree: Path, changed: list[tuple[str, str]], labels: tuple[str, ...] = ()):
    """The check, fed what `git diff --name-status --no-renames` prints and the event's labels."""
    listing = "".join(f"{status}\t{path}\n" for status, path in changed)
    return _run(tree, "check", "--labels", json.dumps(list(labels)), stdin=listing)


# ── the check a pull request meets ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["A", "M"])
def test_a_pull_request_that_adds_or_edits_a_fragment_carries_its_note(tree, status):
    _fragment(tree, "531.fix.md", "A candidate's page installs the candidate.")

    done = _check(tree, [(status, "changes/531.fix.md"), ("M", "openfactory/cli.py")])

    assert done.returncode == 0, done.stderr
    assert "changes/531.fix.md" in done.stdout


def test_a_pull_request_without_one_is_told_how_to_carry_it(tree):
    done = _check(tree, [("M", "openfactory/cli.py")])

    assert done.returncode == 1, done.stdout
    assert "changes/<issue>.<type>.md" in done.stderr and f"`{LABEL}`" in done.stderr
    assert all(name in done.stderr for name in TYPES), done.stderr
    assert "CONTRIBUTING.md" in done.stderr, "the sentence does not say where the example is"


def test_removing_a_fragment_is_not_carrying_one(tree):
    done = _check(tree, [("D", "changes/531.fix.md"), ("M", "openfactory/cli.py")])

    assert done.returncode == 1, "a pull request that only deletes a line was read as carrying one"


def test_the_label_exempts_a_pull_request_and_no_other_label_does(tree):
    docs_only = [("M", "docs/RELEASING.md")]

    assert _check(tree, docs_only, labels=("documentation", LABEL)).returncode == 0
    assert _check(tree, docs_only, labels=("documentation", "bug")).returncode == 1


@pytest.mark.parametrize("name, text, said", [
    ("531.feature.md", "A line.", "`feature` is not a type of release note"),
    ("notes.md", "A line.", "is named `changes/<issue>.<type>.md`"),
    ("531.fix.txt", "A line.", "is named `changes/<issue>.<type>.md`"),
    ("531.fix.md", "", "is empty"),
    ("531.fix.md", "A sentence wrapped the way an editor\nwraps it at a hundred columns.", "line 2"),
    ("531.fix.md", "**Lead.**\n- a sub-item that goes on\n  past its line.", "line 3"),
])
def test_a_file_in_changes_that_is_not_a_fragment_is_refused_by_name_even_with_the_label(
        tree, name, text, said):
    _fragment(tree, name, text)

    done = _check(tree, [("A", f"changes/{name}")], labels=(LABEL,))

    assert done.returncode == 1, done.stdout
    assert f"changes/{name}" in done.stderr and said in done.stderr, done.stderr


def test_an_unknown_type_is_answered_with_the_types_there_are(tree):
    _fragment(tree, "531.feature.md", "A line.")

    done = _check(tree, [("A", "changes/531.feature.md")])

    assert all(name in done.stderr for name in TYPES), done.stderr


def test_a_fragment_may_carry_sub_items_paragraphs_and_a_command(tree):
    _fragment(tree, "531.upgrade.md",
              "**Lead.** One sentence, however long it is.\n- a sub-item\n- another\n\n"
              "A second paragraph.\n\n```bash\nsh install.sh --version v0.7.0\n--force\n```")

    done = _check(tree, [("A", "changes/531.upgrade.md")])

    assert done.returncode == 0, done.stderr


def test_a_final_version_is_declared_only_with_its_notes(tree):
    """The final's version pull request is where the notes are assembled, and the check sees it."""
    _declare(tree, "0.7.0")
    version_pr = [("M", "pyproject.toml"), ("M", "openfactory/__init__.py")]

    missing = _check(tree, version_pr, labels=(LABEL,))
    assert missing.returncode == 1 and "assemble 0.7.0" in missing.stderr, missing.stderr

    (tree / "CHANGELOG.md").write_text(PREAMBLE + "\n## 0.7.0 (2026-10-21)\n\n### Fixes\n\n- x (#1).\n")
    assert _check(tree, version_pr, labels=(LABEL,)).returncode == 0

    _fragment(tree, "540.fix.md", "Left out of the notes.")
    leftover = _check(tree, version_pr, labels=(LABEL,))
    assert leftover.returncode == 1 and "changes/540.fix.md" in leftover.stderr, leftover.stderr

    # AFTER THE FINAL, a backport for the next patch brings its fragment to a branch that still
    # declares the final: that is the next notes' first line, not a forgotten one
    backport = _check(tree, [("A", "changes/540.fix.md"), ("M", "openfactory/cli.py")])
    assert backport.returncode == 0, backport.stderr


# ── the assembly ────────────────────────────────────────────────────────────────────────────────


def test_the_assembly_writes_the_version_on_top_and_removes_what_it_used(tree):
    older = "## 0.6.0 (2026-10-14)\n\n### Fixes\n\n- An older line (#1).\n"
    (tree / "CHANGELOG.md").write_text(PREAMBLE + "\n" + older)
    _fragment(tree, "540.fix.md", "A defect that no longer happens.")
    _fragment(tree, "541.highlight.md", "**The headline.**")

    done = _run(tree, "assemble", "0.7.0", "--date", "2026-10-21")

    assert done.returncode == 0, done.stderr
    written = (tree / "CHANGELOG.md").read_text()
    assert written.startswith(PREAMBLE), "the file's own introduction was not kept on top"
    assert written.index("## 0.7.0 (2026-10-21)") < written.index("## 0.6.0 (2026-10-14)"), written
    assert written.endswith(older), "the older version's notes were changed"
    assert not list((tree / "changes").iterdir()), "the fragments it used are still there"
    assert "- A defect that no longer happens (#540)." in written

    # WHAT IT PRINTS IS WHAT THE PAGE CARRIES: the version pull request's body is the page's notes
    page = _run(tree, "page", "v0.7.0")
    assert done.stdout == page.stdout, (done.stdout, page.stdout)
    assert done.stdout.startswith("### Highlights"), done.stdout


def test_the_notes_read_in_the_order_a_reader_looks(tree):
    for number, name in enumerate(reversed(TYPES), start=100):
        _fragment(tree, f"{number}.{name}.md", f"A {name} line.")
    _fragment(tree, "10.behaviour.md", "The tenth.")
    _fragment(tree, "9.behaviour.md", "The ninth.")
    _fragment(tree, "GHSA-abcd-efgh-ijkm.behaviour.md", "The advisory's.")

    notes = _run(tree, "preview", "0.7.0").stdout

    headings = re.findall(r"^### (.+)$", notes, re.M)
    assert headings == list(TYPES.values()), headings
    assert notes.index("The ninth (#9).") < notes.index("The tenth (#10)."), "#10 sorted as text"
    assert notes.index("The tenth (#10).") < notes.index("The advisory's (GHSA-abcd-efgh-ijkm).")


def test_each_line_closes_with_its_reference_and_keeps_its_sub_items(tree):
    _fragment(tree, "531.fix.md", "A plain sentence.")
    _fragment(tree, "532.fix.md", "**A bold lead.**\n- one detail\n- another")
    _fragment(tree, "533.fix.md", "- Written with its own dash.")
    _fragment(tree, "534.fix.md", "The board's own columns. That covers:\n- Jira\n- GitHub")

    notes = _run(tree, "preview", "0.7.0").stdout

    # EACH FROM THE START OF ITS LINE: `- - Written…` holds `- Written…`
    assert "\n- A plain sentence (#531).\n" in notes
    assert "\n- **A bold lead.** (#532)\n  - one detail\n  - another\n" in notes
    assert "\n- Written with its own dash (#533).\n" in notes
    assert "\n- The board's own columns. That covers (#534):\n  - Jira\n" in notes


@pytest.mark.parametrize("version, why", [
    ("0.7.0-rc.1", "is not a final version"),
    ("0.6.0", "already has the notes of 0.6.0"),
])
def test_the_assembly_refuses_what_it_should_not_write(tree, version, why):
    (tree / "CHANGELOG.md").write_text(PREAMBLE + "\n## 0.6.0 (2026-10-14)\n\n- x (#1).\n")
    _fragment(tree, "540.fix.md", "A line.")
    before = (tree / "CHANGELOG.md").read_text()

    done = _run(tree, "assemble", version)

    assert done.returncode != 0 and why in done.stderr, done.stderr
    assert (tree / "CHANGELOG.md").read_text() == before
    assert (tree / "changes" / "540.fix.md").exists()


def test_the_assembly_refuses_a_version_with_no_line_or_a_broken_one(tree):
    assert "no fragment" in _run(tree, "assemble", "0.7.0").stderr

    _fragment(tree, "540.fix.md", "A good line.")
    _fragment(tree, "541.fixes.md", "A misnamed one.")
    done = _run(tree, "assemble", "0.7.0")

    assert done.returncode == 1 and "changes/541.fixes.md" in done.stderr, done.stderr
    assert (tree / "CHANGELOG.md").read_text() == PREAMBLE, "it wrote half the notes"
    assert (tree / "changes" / "540.fix.md").exists()


def test_the_preview_writes_nothing(tree):
    _fragment(tree, "540.fix.md", "A line.")

    done = _run(tree, "preview", "0.7.0")

    assert done.returncode == 0 and done.stdout.startswith("## 0.7.0 (unreleased)\n"), done.stdout
    assert (tree / "CHANGELOG.md").read_text() == PREAMBLE
    assert (tree / "changes" / "540.fix.md").exists()


# ── the release page ────────────────────────────────────────────────────────────────────────────


def test_a_final_page_carries_its_section_and_a_candidate_page_the_fragments(tree):
    (tree / "CHANGELOG.md").write_text(PREAMBLE + "\n## 0.7.0 (2026-10-21)\n\n### Fixes\n\n"
                                       "- Shipped in the final (#1).\n")
    _fragment(tree, "600.fix.md", "Waiting for the next one.")

    final = _run(tree, "page", "v0.7.0").stdout
    candidate = _run(tree, "page", "v0.8.0-rc.1").stdout

    assert "Shipped in the final (#1)." in final and "Waiting" not in final, final
    assert "Waiting for the next one (#600)." in candidate and "Shipped" not in candidate
    assert "0.8.0 so far" in candidate, candidate


@pytest.mark.parametrize("tag, said", [
    ("v0.8.0", "The notes of 0.8.0 are not in CHANGELOG.md"),
    ("v0.8.0-rc.1", "No release-note fragment yet"),
])
def test_a_page_without_its_notes_says_so_and_never_fails_the_run(tree, tag, said):
    done = _run(tree, "page", tag)

    assert done.returncode == 0, done.stderr
    assert said in done.stdout, done.stdout


def test_a_candidate_page_leaves_a_broken_fragment_out_and_says_so_in_the_run(tree):
    _fragment(tree, "600.fix.md", "A good line.")
    _fragment(tree, "601.fixes.md", "A misnamed one.")

    done = _run(tree, "page", "v0.8.0-rc.1")

    assert done.returncode == 0 and "A good line (#600)." in done.stdout, done.stdout
    assert "::warning::changes/601.fixes.md" in done.stderr, done.stderr


def _page_from(tree: Path, tag: str, *, with_notes: bool = True) -> subprocess.CompletedProcess:
    """The page as the release job writes it, from a checkout whose root is `tree`."""
    (tree / "scripts").mkdir(exist_ok=True)
    shutil.copy(PAGE_SCRIPT, tree / "scripts" / PAGE_SCRIPT.name)
    if with_notes:
        shutil.copy(SCRIPT, tree / "scripts" / SCRIPT.name)
    return subprocess.run(["sh", "scripts/release-page-body.sh", tag], cwd=tree,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("tag", ["v0.7.0", "v0.7.0-rc.1"])
def test_the_release_page_carries_the_notes_under_the_install_block(tree, tag):
    if "-" in tag:
        _fragment(tree, "600.fix.md", "The line of this release.")
    else:
        (tree / "CHANGELOG.md").write_text(PREAMBLE + "\n## 0.7.0 (2026-10-21)\n\n### Fixes\n\n"
                                           "- The line of this release (#600).\n")

    page = _page_from(tree, tag)

    assert page.returncode == 0, page.stderr
    out = page.stdout
    assert out.index("### Install") < out.index("Verify the assets") < out.index("### Fixes"), out
    assert "- The line of this release (#600).\n" in out, out


def test_a_page_whose_notes_cannot_be_written_is_still_published(tree):
    """By the page's step the images are public under the tag: a failure here burns the version."""
    page = _page_from(tree, "v0.7.0", with_notes=False)

    assert page.returncode == 0, page.stderr
    assert "### Install" in page.stdout and "adds them to this page by hand" in page.stdout


# ── the check, as CI runs it ────────────────────────────────────────────────────────────────────


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _the_step() -> dict:
    steps = _workflow()["jobs"]["release-note"]["steps"]
    [step] = [s for s in steps if "release_notes.py check" in str(s.get("run", ""))]
    return step


def test_the_check_runs_on_every_pull_request_and_again_when_its_labels_change():
    workflow = _workflow()
    triggers = workflow.get("on") or workflow.get(True)          # YAML 1.1 reads `on` as true

    types = set(triggers["pull_request"]["types"])
    assert {"opened", "synchronize", "reopened", "labeled", "unlabeled"} <= types, types
    assert workflow["permissions"] == {"contents": "read"}, "the check needs no write, nor a token"
    assert _the_step()["env"]["LABELS"] == "${{ toJSON(github.event.pull_request.labels.*.name) }}"
    steps = workflow["jobs"]["release-note"]["steps"]
    [checkout] = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
    assert checkout["with"]["fetch-depth"] == 2, "HEAD^1, the base, is not fetched"


def _pull_request(tmp_path: Path, files: dict[str, str]) -> Path:
    """A repository whose HEAD is a pull request's merge commit, as `actions/checkout` hands it
    over: the base is the first parent, the pull request the second."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / SCRIPT.name)
    (repo / "README.md").write_text("x\n")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, timeout=60)

    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "the base")
    git("switch", "-q", "-c", "the-change")
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git("add", "-A")
    git("commit", "-q", "-m", "the change")
    git("switch", "-q", "main")
    git("merge", "-q", "--no-ff", "the-change", "-m", "the merge GitHub builds")
    return repo


@pytest.mark.parametrize("files, labels, passes", [
    ({"changes/531.fix.md": "A line.\n", "openfactory/x.py": "x = 1\n"}, [], True),
    ({"openfactory/x.py": "x = 1\n"}, [], False),
    ({"docs/x.md": "words\n"}, [LABEL], True),
])
def test_the_workflow_step_reads_the_pull_request_s_own_files_and_labels(
        tmp_path, files, labels, passes):
    repo = _pull_request(tmp_path, files)
    scratch = tmp_path / "runner"
    scratch.mkdir()

    done = subprocess.run(["bash", "-e", "-c", _the_step()["run"]], cwd=repo,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "LABELS": json.dumps(labels),
                               "RUNNER_TEMP": str(scratch)})

    assert (done.returncode == 0) is passes, done.stdout + done.stderr


# ── the tree and its documents ──────────────────────────────────────────────────────────────────


def test_this_tree_is_one_the_check_accepts():
    """Every fragment here is well formed, and a final version is not declared without its notes."""
    done = _run(ROOT, "check", "--labels", json.dumps([LABEL]))

    assert done.returncode == 0, done.stderr
    assert _run(ROOT, "preview", "0.0.0").returncode == 0


def test_the_changelog_is_in_the_tree_from_the_first_release_made_this_way():
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "CHANGELOG.md"], cwd=ROOT,
                             capture_output=True, check=False)
    assert tracked.returncode == 0, "CHANGELOG.md is not tracked"

    versions = re.findall(r"^## (\d+)\.(\d+)\.(\d+)", (ROOT / "CHANGELOG.md").read_text(), re.M)
    assert all((int(a), int(b)) >= (0, 6) for a, b, _ in versions), (
        "CHANGELOG.md starts from 0.6.0, the first release whose notes were assembled; the "
        "notes of the earlier ones are on their release pages")


def _subcommands() -> set[str]:
    usage = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True,
                           text=True, check=True).stdout
    return set(re.search(r"\{([a-z,]+)\}", usage).group(1).split(","))


def test_every_command_the_documents_give_is_one_the_script_has():
    commands = _subcommands()
    named = {}
    for path in (RELEASING, AGENT, CONTRIBUTING, WORKFLOW, ROOT / ".github/workflows/release.yml",
                 PAGE_SCRIPT):
        for word in re.findall(r"release_notes\.py (\w+)", path.read_text()):
            named.setdefault(word, set()).add(path.relative_to(ROOT).as_posix())

    assert set(named) <= commands, {w: p for w, p in named.items() if w not in commands}
    assert {"preview", "assemble", "page", "check"} <= {
        w for w, p in named.items() if "docs/RELEASING.md" in p}, "the process skips a command"
    assert {"preview", "assemble"} <= {
        w for w, p in named.items() if ".claude/agents/release-manager.md" in p}


def test_the_types_and_the_label_are_the_ones_the_documents_teach():
    page = RELEASING.read_text()
    section = page[page.index("## The release notes"):page.index("## Rules that do not bend")]
    # IN ORDER: the table's order is the page's, Highlights first
    taught = re.findall(r"^\s*\| `([a-z]+)` \| ([^|]+?) \|", section, re.M)
    assert taught == list(TYPES.items()), f"docs/RELEASING.md teaches {taught}, the script {TYPES}"

    contributing = CONTRIBUTING.read_text()
    assert all(f"`{name}`" in contributing for name in TYPES), "CONTRIBUTING.md misses a type"
    setup = page[page.index("## One-time setup"):page.index("## The release tracking issue")]
    for text in (contributing, section, setup):
        assert f"`{LABEL}`" in text, "a document names a label the check does not read"
