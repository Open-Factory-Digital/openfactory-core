"""The combined view must NOT be a temp directory per message.

`ProductModule` is constructed fresh for every Slack message on purpose — one conversation must
not carry another's state. The first version of the two-repo mount called `tempfile.mkdtemp()`
inside it, which meant one directory per message that nothing ever removed: 33 of them accumulated
during a single afternoon of local testing. Tiny and unbounded is the exact shape of a disk-full
incident, and the worker is long-lived.

This test pins the property that makes the leak impossible rather than the cleanup that would have
managed it: N modules over the same project resolve to ONE path.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.product.module import ProductModule


def _project():
    return Project(name="books", repo_path="/t",
                   tracker=ProviderRef(kind="github", repo="a/b"),
                   forge=ProviderRef(kind="github", repo="a/b"),
                   product=ProductConfig(docs_repo="a/docs", channel_id="C0",
                                         agent_name="Nina"))


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


@pytest.fixture()
def checkouts(tmp_path, monkeypatch):
    """A REAL git checkout for the source, because the mount is a real worktree now.

    An empty `.git/` directory was enough while the view was two symlinks — nothing ever asked the
    checkout a question. It is not enough now, and that is the point: the mount either produces
    openable files or it reports that it could not, and a fake that cannot answer `rev-parse`
    would be testing neither."""
    docs, code = tmp_path / "cache" / "docs", tmp_path / "cache" / "code"
    docs.mkdir(parents=True)
    (docs / "0001-x.md").write_text("# REQ-0001\n")
    code.mkdir(parents=True)
    (code / "app.py").write_text("print('hi')\n")
    _git(["init", "-q", "-b", "main"], cwd=code)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], cwd=code)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"], cwd=code)
    monkeypatch.setattr(ProductModule, "context",
                        lambda self: SimpleNamespace(docs_path=docs))
    monkeypatch.setattr(ProductModule, "_source_checkout", lambda self: code)
    monkeypatch.setattr(ProductModule, "_source_repo", lambda self: "a/b")
    return docs, code


def _view(project, checkouts):
    m = ProductModule(project)
    m._workspace()
    return Path(m._combined)


def test_ten_messages_produce_ONE_view_directory(checkouts, tmp_path):
    """Ten fresh modules — ten messages — and the cache root holds one view, not ten."""
    roots = {_view(_project(), checkouts) for _ in range(10)}

    assert len(roots) == 1, f"a directory per message is a leak: {roots}"
    views = list((tmp_path / "cache").glob("*-view"))
    assert len(views) == 1, f"{len(views)} view directories for one project: {views}"


def test_both_repositories_are_reachable_through_it(checkouts):
    """The whole point of the mount: the agent can open documentation AND code."""
    module = ProductModule(_project())
    module._workspace()
    root, where = Path(module._combined), module.mounted()

    assert (root / where["docs"] / "0001-x.md").is_file(), where
    assert (root / where["code"] / "app.py").is_file(), where


def test_NOTHING_the_agent_opens_is_a_pointer_out_of_the_tree(checkouts):
    """BOARD #1, and the reason this mount was rebuilt.

    `product/workspace.py` said it in its own docstring before any of this happened: *"a confined
    sandbox will not follow a link that leaves its root, so a symlinked layout would reproduce
    exactly the failure this exists to avoid."* Codex's `-s read-only` confines the process and
    Claude's tool allowlist does not, so the old two-symlink root read everything on one engine and
    NOTHING on another — with answers still arriving either way. Agnosticism is one of the three
    sentences this product is sold on, so this is not a tidiness rule."""
    module = ProductModule(_project())
    module._workspace()
    root = Path(module._combined)

    escaping = [p for p in root.rglob("*")
                if p.is_symlink() and not os.path.realpath(p).startswith(os.path.realpath(root))]
    assert not escaping, f"the agent's root still points outside itself: {escaping}"

    where = module.mounted()
    for key in ("docs", "code"):
        target = root / where[key]
        assert target.is_dir() and not target.is_symlink(), f"{key} is not real content: {target}"


def test_a_view_the_cache_MOVED_PAST_is_rebuilt_not_served_stale(checkouts):
    """A deploy moves the cache; a message arrives while the source is one commit ahead. Serving
    what was mounted last week is worse than serving nothing: the agent reads it, cites the file,
    and is confidently wrong about the product's behaviour today."""
    _view(_project(), checkouts)
    _docs, code = checkouts
    (code / "app.py").write_text("print('novo')\n")
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], cwd=code)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "moved"], cwd=code)

    module = ProductModule(_project())
    module._workspace()
    root, where = Path(module._combined), module.mounted()

    assert (root / where["code"] / "app.py").read_text() == "print('novo')\n", (
        "the agent was handed a checkout the cache had already moved past")


def test_the_UNCHANGED_turn_does_not_check_anything_out_again(checkouts):
    """This runs on every client message. Rebuilding the worktree each time would be a checkout per
    message — the cost argument that made the old symlink view look right in the first place."""
    first = _view(_project(), checkouts)
    stamp = (first / "src" / "b").stat().st_mtime_ns

    again = _view(_project(), checkouts)

    assert again == first
    assert (again / "src" / "b").stat().st_mtime_ns == stamp, (
        "the source was checked out again for a cache that had not moved")
