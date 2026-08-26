"""A sync must never destroy the tree a previous caller is still reading.

THE RACE THIS PINS. `RepoCache.sync` used to `checkout -f` + `reset --hard` + `clean -fdx` — or
`rmtree` + reclone — the very directory it had handed to the previous caller. The per-key lock
covered sync-vs-sync only: the baseline survey reads its checkout for MINUTES, every conversational
message re-syncs the same key through the view symlink, and the factory advances origin/main
continuously — so the reader saw a torn half-old/half-new tree (a survey describing code that never
existed in any commit) or files vanishing mid-read.

The contract now: the served path is stable, its content only ever changes by atomic swap, and a
displaced tree survives a grace window so a reader anchored to it (open fd, cwd) keeps a complete,
self-consistent view. Real git against real local repositories, like the credentials tests: the
property is about inodes and directory swaps, which a fake cannot witness.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

import pytest

import openfactory.runtime.repo_cache as rc
from openfactory.runtime.repo_cache import RepoCache


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def origin(tmp_path):
    src = tmp_path / "origin"
    src.mkdir()
    _git("init", "-q", "-b", "main", cwd=src)
    _git("config", "user.email", "t@t", cwd=src)
    _git("config", "user.name", "t", cwd=src)
    (src / "app.py").write_text("x = 1\n")
    (src / "keep.py").write_text("stay\n")
    _git("add", "-A", cwd=src)
    _git("commit", "-qm", "first", cwd=src)
    return src


def _advance(origin, text="x = 2\n"):
    (origin / "app.py").write_text(text)
    _git("add", "-A", cwd=origin)
    _git("commit", "-qm", "advance", cwd=origin)


def _read_via(dir_fd: int, name: str) -> str:
    fd = os.open(name, os.O_RDONLY, dir_fd=dir_fd)
    try:
        return os.read(fd, 4096).decode()
    finally:
        os.close(fd)


def test_a_reader_holding_the_old_tree_survives_a_refresh(tmp_path, origin):
    """THE finding. A reader anchored to the checkout (dirfd stands in for an agent's cwd) must
    keep reading the complete OLD tree after a newer sync refreshed the key — not a reset-in-place
    mixture, not ENOENT from an rmtree."""
    cache = RepoCache(root=tmp_path / "cache")
    served = cache.sync("proj", str(origin), "main")
    assert served is not None
    reader = os.open(served, os.O_RDONLY)
    try:
        _advance(origin)
        refreshed = cache.sync("proj", str(origin), "main")

        assert refreshed == served, "the served path must stay stable for every caller"
        assert (refreshed / "app.py").read_text() == "x = 2\n", "the next caller must see base"
        # the prior reader's whole view is still the tree it was handed
        assert _read_via(reader, "app.py") == "x = 1\n", \
            "the checkout was mutated under a reader that was still using it"
        assert _read_via(reader, "keep.py") == "stay\n"
    finally:
        os.close(reader)


def test_a_scribblers_leftovers_never_vanish_under_the_reader_that_made_them(tmp_path, origin):
    """The next caller must get a tree IDENTICAL to base (never merged into), but discarding the
    scribble must not delete files out from under whoever is still working over the old view —
    that is `clean -fdx` racing a live agent, the exact vanishing-files half of the defect."""
    cache = RepoCache(root=tmp_path / "cache")
    served = cache.sync("proj", str(origin), "main")
    (served / "stray.txt").write_text("left behind\n")
    reader = os.open(served, os.O_RDONLY)
    try:
        refreshed = cache.sync("proj", str(origin), "main")

        assert not (refreshed / "stray.txt").exists(), "the scribble reached the next reader"
        assert (refreshed / "app.py").read_text() == "x = 1\n"
        assert _read_via(reader, "stray.txt") == "left behind\n", \
            "a file was deleted under the reader still holding the old tree"
    finally:
        os.close(reader)


def test_an_unchanged_sync_leaves_the_served_tree_completely_untouched(tmp_path, origin):
    """The routine case — a message every 30-120s against an unmoved origin — must not churn the
    checkout at all: same directory inode, so nothing a concurrent reader holds is ever swapped
    for no reason (and nothing accumulates per message)."""
    cache = RepoCache(root=tmp_path / "cache")
    served = cache.sync("proj", str(origin), "main")
    before = os.stat(served).st_ino

    again = cache.sync("proj", str(origin), "main")

    assert again == served
    assert os.stat(again).st_ino == before, "a no-change sync replaced the tree for nothing"


def test_a_displaced_tree_is_removed_once_its_grace_expires(tmp_path, origin, monkeypatch):
    """The old view survives for a WINDOW, not forever — a worker that never restarts cannot park
    a tree per upstream commit for its whole life. Grace zero stands in for 'the window passed'."""
    monkeypatch.setattr(rc, "_TRASH_GRACE_SECONDS", 0)
    cache = RepoCache(root=tmp_path / "cache")
    cache.sync("proj", str(origin), "main")

    _advance(origin)
    cache.sync("proj", str(origin), "main")
    _advance(origin, "x = 3\n")
    cache.sync("proj", str(origin), "main")

    trash = tmp_path / "cache" / ".trash"
    parked = list(trash.iterdir()) if trash.is_dir() else []
    assert parked == [], f"displaced trees outlived their grace: {parked}"


def test_within_the_grace_window_the_displaced_tree_is_parked_not_deleted(tmp_path, origin):
    cache = RepoCache(root=tmp_path / "cache")
    cache.sync("proj", str(origin), "main")
    _advance(origin)
    cache.sync("proj", str(origin), "main")

    trash = tmp_path / "cache" / ".trash"
    parked = list(trash.iterdir()) if trash.is_dir() else []
    assert len(parked) == 1, "the displaced tree was deleted while a reader could still hold it"
    assert (parked[0] / "app.py").read_text() == "x = 1\n", "the parked tree is not the old view"


def test_concurrent_syncs_of_one_key_all_serve_a_complete_current_tree(tmp_path, origin):
    """Sync-vs-sync stays serialized by the per-key lock — overlapping poller ticks must corrupt
    nothing and every caller must come back with base's content."""
    cache = RepoCache(root=tmp_path / "cache")
    cache.sync("proj", str(origin), "main")
    _advance(origin)
    results: list[Path | None] = []

    def _one():
        results.append(cache.sync("proj", str(origin), "main"))

    threads = [threading.Thread(target=_one) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(p is not None for p in results), results
    assert all((p / "app.py").read_text() == "x = 2\n" for p in results)
