"""The combined view must NOT be a temp directory per message.

`ProductModule` is constructed fresh for every Slack message on purpose — one conversation must
not carry another's state. The first version of the two-repo mount called `tempfile.mkdtemp()`
inside it, which meant one directory per message that nothing ever removed: 33 of them accumulated
during a single afternoon of local testing. Tiny and unbounded is the exact shape of a disk-full
incident, and the worker is long-lived.

This test pinned the property that made the leak impossible rather than the cleanup that would have
managed it: N modules over the same project resolve to ONE path.

AND THEN ONE PATH BECAME THE DEFECT (#266 slice 2, ADR-0051 D11). With conversations in parallel,
one turn recomposing that one path reset what another turn's agent was reading: the documentation
copied over in place, a source worktree replaced, the facts pack cleared. The stable path stays —
as the CACHE, still one per project and still not checked out again on an unchanged turn — and each
turn reads a view of its own made from it with hard links, removed when the turn ends. What is
pinned now: one cached view, no view left behind by a released turn, no two turns sharing one, and
a rebuild of the cache that leaves a running turn's files exactly as they were.
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
from openfactory.product.sources import Checkout


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
    # THE PRODUCT DECLARES ITS SOURCE (#268): a source is mounted because `sources:` names it
    (docs / ".openfactory").mkdir()
    (docs / ".openfactory" / "product.yaml").write_text("product: books\nsources: [a/b]\n")
    code.mkdir(parents=True)
    (code / "app.py").write_text("print('hi')\n")
    _git(["init", "-q", "-b", "main"], cwd=code)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], cwd=code)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"], cwd=code)
    monkeypatch.setattr(ProductModule, "context",
                        lambda self: SimpleNamespace(docs_path=docs))
    monkeypatch.setattr(ProductModule, "_source_checkout",
                        lambda self, repo, spelling="", own=False: Checkout(path=code))
    monkeypatch.setattr(ProductModule, "_source_repo", lambda self: "a/b")
    return docs, code


def _view(project, checkouts):
    m = ProductModule(project)
    m._workspace()
    return Path(m._combined)


def test_ten_messages_leave_ONE_cached_view_and_no_turn_behind(checkouts, tmp_path):
    """Ten fresh modules — ten messages, each released when its turn ends as the engine releases
    it — and the cache root holds one cached view, not ten, and not one turn's view is left."""
    for _ in range(10):
        module = ProductModule(_project())
        module._workspace()
        module.release()

    views = list((tmp_path / "cache").glob("*-view"))
    assert len(views) == 1, f"{len(views)} view directories for one project: {views}"
    left = list((tmp_path / "cache" / "books-turns").iterdir())
    assert not left, f"a released turn left its view behind: {left}"


def test_two_turns_at_once_never_share_a_view(checkouts):
    """#266 slice 2's acceptance, ADR-0051 D11: two turns alive at the same time read two
    directories — neither is the cache, and neither is the other's."""
    first, second = ProductModule(_project()), ProductModule(_project())
    first._workspace()
    second._workspace()

    assert first._combined != second._combined, "two concurrent turns share one workspace"
    cache = Path(first._combined).parent.parent / "books-view"
    assert Path(first._combined) != cache and Path(second._combined) != cache, (
        "a turn reads the cached view another turn recomposes in place")
    for module in (first, second):
        assert (Path(module._combined) / module.mounted()["code"] / "app.py").is_file()


def test_a_cache_REBUILT_under_a_running_turn_leaves_that_turn_s_files_as_they_were(checkouts):
    """THE DEFECT, driven. A turn is reading; the source moves and a second turn's compose rebuilds
    the cached worktree. The first turn still reads what it started with — its files are links to
    the old content, which a rebuild unlinks and never rewrites — while the second reads the new.
    Before the slice both turns read the one root, and the first saw its files replaced mid-read."""
    running = ProductModule(_project())
    running._workspace()
    mine = Path(running._combined) / running.mounted()["code"] / "app.py"
    _docs, code = checkouts
    (code / "app.py").write_text("print('novo')\n")
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], cwd=code)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "moved"], cwd=code)

    later = ProductModule(_project())
    later._workspace()

    assert mine.read_text() == "print('hi')\n", "a rebuild of the cache reached a running turn"
    theirs = Path(later._combined) / later.mounted()["code"] / "app.py"
    assert theirs.read_text() == "print('novo')\n"


def test_eight_turns_composing_at_once_each_get_a_whole_view_of_their_own(checkouts):
    """The lock, under real concurrency: eight threads compose at the same moment, and each comes
    back with a view of its own holding every file — none half-linked from a root another thread
    was rebuilding, none shared."""
    import threading

    views: list[Path] = []
    errors: list[BaseException] = []

    def _turn() -> None:
        try:
            module = ProductModule(_project())
            module._workspace()
            views.append(Path(module._combined) / module.mounted()["code"])
        except BaseException as exc:  # noqa: BLE001 — collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=_turn) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, errors
    assert len(set(views)) == 8, f"turns shared a view: {views}"
    assert all((v / "app.py").read_text() == "print('hi')\n" for v in views)


def test_a_release_removes_only_the_view_the_module_made_itself(checkouts, tmp_path):
    """A view somebody HANDED the module — a fixture, a caller that set it — is not the module's
    to delete: `release` leaves it exactly as it was and forgets nothing."""
    handed = tmp_path / "handed"
    handed.mkdir()
    (handed / "keep.md").write_text("mine\n")
    module = ProductModule(_project())
    module._combined = str(handed)

    module.release()

    assert (handed / "keep.md").is_file()
    assert module._combined == str(handed)


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


def test_the_UNCHANGED_turn_does_not_check_anything_out_again(checkouts, tmp_path):
    """This runs on every client message. Rebuilding the worktree each time would be a checkout per
    message — the cost argument that made the old symlink view look right in the first place. The
    CACHED worktree is what must not move; each turn's own view is links to it, not a checkout."""
    cached = tmp_path / "cache" / "books-view" / "src" / "b"
    first = _view(_project(), checkouts)
    stamp = cached.stat().st_mtime_ns

    again = _view(_project(), checkouts)

    assert again != first, "two turns were handed one view"
    assert cached.stat().st_mtime_ns == stamp, (
        "the source was checked out again for a cache that had not moved")
    assert (again / "src" / "b" / "app.py").stat().st_ino == (cached / "app.py").stat().st_ino, (
        "the turn's view copied the source instead of linking it")
