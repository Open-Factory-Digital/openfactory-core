"""One workspace holding the documentation repo and every source repo.

Real git, real directories: the property under test is that an agent confined to its working
directory can reach both — and only a real layout can show that.
"""

from __future__ import annotations

import subprocess

import pytest

from openfactory.product.workspace import compose


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _repo(path, files):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", cwd=path)
    _git("config", "user.email", "t@t", cwd=path)
    _git("config", "user.name", "t", cwd=path)
    for rel, body in files.items():
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    _git("add", "-A", cwd=path)
    _git("commit", "-qm", "seed", cwd=path)
    return path


@pytest.fixture
def docs(tmp_path):
    return _repo(tmp_path / "docs-co", {"requirements/0001-x.md": "# REQ-0001 — x\n"})


@pytest.fixture
def code(tmp_path):
    return _repo(tmp_path / "code-co", {"app/rules.py": "def apply(): ...\n"})


def test_both_repos_live_INSIDE_the_workspace(tmp_path, docs, code):
    """The whole point: a harness confined to its working directory (`codex -s read-only`) must
    still reach the code. An absolute path handed over in the prompt would read nothing there,
    while the answers kept arriving — the worst possible failure."""
    ws = compose(docs_checkout=docs, sources={"AcmeCorp/acme-books": code},
                 root=tmp_path / "ws")
    try:
        assert (ws.path / "docs" / "requirements" / "0001-x.md").is_file()
        assert (ws.path / "src" / "acme-books" / "app" / "rules.py").is_file()
        # nothing reaches outside the workspace root
        for p in (ws.docs, *ws.sources.values()):
            assert not p.is_symlink()
            assert str(p).startswith(str(ws.path))
    finally:
        ws.release()


def test_the_docs_copy_survives_the_cache_resetting_underneath(tmp_path, docs):
    """`RepoCache` resets every checkout on its next use. A long agent run reading a live cache
    directory would have the ground move under it mid-answer."""
    ws = compose(docs_checkout=docs, sources={}, root=tmp_path / "ws")
    try:
        (docs / "requirements" / "0001-x.md").write_text("# REQ-0001 — CHANGED\n")
        assert "CHANGED" not in (ws.path / "docs" / "requirements" / "0001-x.md").read_text()
    finally:
        ws.release()


def test_a_missing_source_is_REPORTED_not_silently_omitted(tmp_path, docs):
    """An agent not told a repository is absent will happily conclude things about code it never
    saw — and phrase them with the same confidence as the rest."""
    ws = compose(docs_checkout=docs, sources={"AcmeCorp/acme-front": tmp_path / "nope"},
                 root=tmp_path / "ws")
    try:
        assert ws.sources == {}
        assert "AcmeCorp/acme-front" in ws.missing
        assert "AcmeCorp/acme-front" in ws.layout()
        assert "say so rather than concluding" in ws.layout()
    finally:
        ws.release()


def test_the_layout_names_every_directory_the_agent_can_use(tmp_path, docs, code):
    ws = compose(docs_checkout=docs, sources={"AcmeCorp/acme-books": code},
                 root=tmp_path / "ws")
    try:
        text = ws.layout()
        assert "`docs/`" in text and "src/acme-books/" in text
        assert "AcmeCorp/acme-books" in text
    finally:
        ws.release()


def test_several_sources_are_placed_side_by_side(tmp_path, docs, code):
    """A product spans N repositories — back end, front end, a fleet of services."""
    front = _repo(tmp_path / "front-co", {"index.html": "<html>"})
    ws = compose(docs_checkout=docs,
                 sources={"A/back": code, "A/front": front}, root=tmp_path / "ws")
    try:
        assert set(ws.sources) == {"A/back", "A/front"}
        assert (ws.path / "src" / "front" / "index.html").is_file()
    finally:
        ws.release()


def test_releasing_removes_the_workspace_and_its_worktrees(tmp_path, docs, code):
    ws = compose(docs_checkout=docs, sources={"A/back": code}, root=tmp_path / "ws")
    ws.release()
    assert not ws.path.exists()
    out = subprocess.run(["git", "worktree", "list"], cwd=code,
                         capture_output=True, text=True, check=True)
    assert "/ws/src" not in out.stdout


def test_a_missing_docs_checkout_still_yields_a_usable_workspace(tmp_path, code):
    """Losing the requirements should not lose the ability to say anything at all."""
    ws = compose(docs_checkout=tmp_path / "gone", sources={"A/back": code}, root=tmp_path / "ws")
    try:
        assert ws.docs.is_dir() and "documentation" in ws.missing
        assert ws.sources
    finally:
        ws.release()
