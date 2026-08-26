"""The worker's repo cache must not leave a live token on disk.

`git clone https://x-access-token:<TOKEN>@github.com/...` persists that URL in `.git/config`, and
agents DO run over this cache — the pre-flight sizer explores it. A sizer's input is ticket text,
which anyone able to file an issue can write, so a ticket instructing it to read `.git/config` and
repeat what it finds would put a live GitHub App token into a public comment.

Real git against a real local repository: the point is what ends up in `.git/config`, and a fake
cannot tell us that.
"""

from __future__ import annotations

import subprocess

import pytest

from openfactory.runtime.repo_cache import RepoCache

TOKEN = "ghs_averysecrettokenvalue"


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def origin(tmp_path):
    """A local repository standing in for the forge, reachable over a credentialed URL."""
    src = tmp_path / "origin"
    src.mkdir()
    _git("init", "-q", "-b", "main", cwd=src)
    _git("config", "user.email", "t@t", cwd=src)
    _git("config", "user.name", "t", cwd=src)
    (src / "README.md").write_text("one\n")
    _git("add", "-A", cwd=src)
    _git("commit", "-qm", "first", cwd=src)
    return src


#: what a real clone URL looks like. git only accepts userinfo over http(s), so it cannot be used
#: to clone a local fixture — the security property is therefore proven directly against `git
#: config`, and the wiring is proven separately on both code paths.
CRED_URL = f"https://x-access-token:{TOKEN}@github.com/AcmeCorp/acme-books.git"


def _config(path) -> str:
    return (path / ".git" / "config").read_text()


def test_scrubbing_removes_the_credential_from_a_real_git_config(tmp_path, origin):
    """THE security property: after this, an agent that reads `.git/config` finds no token."""
    from openfactory.runtime.repo_cache import _scrub_remote

    cache = RepoCache(root=tmp_path / "cache")
    path = cache.sync("proj", str(origin), "main")
    _git("remote", "set-url", "origin", CRED_URL, cwd=path)
    assert TOKEN in _config(path)

    _scrub_remote(path, CRED_URL)

    cfg = _config(path)
    assert TOKEN not in cfg and "x-access-token" not in cfg
    assert "github.com/AcmeCorp/acme-books.git" in cfg  # still points at the right repo


def test_scrubbing_is_a_no_op_when_there_was_no_credential(tmp_path, origin):
    from openfactory.runtime.repo_cache import _scrub_remote

    cache = RepoCache(root=tmp_path / "cache")
    path = cache.sync("proj", str(origin), "main")
    before = _config(path)
    _scrub_remote(path, str(origin))
    assert _config(path) == before


def test_BOTH_sync_paths_scrub_not_just_the_clone(tmp_path, origin, monkeypatch):
    """A worker keeps its cache across many syncs, so scrubbing only on clone would leave an
    already-poisoned checkout holding a token until the next deploy."""
    import openfactory.runtime.repo_cache as rc

    calls: list[str] = []
    real = rc._scrub_remote
    monkeypatch.setattr(rc, "_scrub_remote", lambda p, u: (calls.append(str(p)), real(p, u))[1])

    cache = rc.RepoCache(root=tmp_path / "cache")
    cache.sync("proj", str(origin), "main")   # clone path
    assert calls, "the clone path never scrubbed"
    calls.clear()
    cache.sync("proj", str(origin), "main")   # reuse path
    assert calls, "the reuse path never scrubbed — a pre-existing cache would stay poisoned"


def test_the_checkout_still_tracks_the_remote_after_scrubbing(tmp_path, origin):
    """Fetching by explicit URL only moves FETCH_HEAD unless a refspec is given — and the reset
    below uses `origin/<base>`, so getting this wrong would silently serve a stale tree while
    looking perfectly healthy."""
    cache = RepoCache(root=tmp_path / "cache")
    cache.sync("proj", str(origin), "main")

    (origin / "README.md").write_text("two\n")
    _git("add", "-A", cwd=origin)
    _git("commit", "-qm", "second", cwd=origin)

    path = cache.sync("proj", str(origin), "main")
    assert (path / "README.md").read_text() == "two\n"


def test_a_local_change_in_the_cache_is_discarded_not_merged(tmp_path, origin):
    """A cache must be IDENTICAL to base, never merged into: an agent that left a file behind must
    not become the next reader's context."""
    cache = RepoCache(root=tmp_path / "cache")
    path = cache.sync("proj", str(origin), "main")
    (path / "README.md").write_text("locally edited\n")
    (path / "stray.txt").write_text("left behind\n")

    path = cache.sync("proj", str(origin), "main")
    assert (path / "README.md").read_text() == "one\n"
    assert not (path / "stray.txt").exists()


def test_a_corrupt_cache_is_recloned_rather_than_failing(tmp_path, origin):
    cache = RepoCache(root=tmp_path / "cache")
    path = cache.sync("proj", str(origin), "main")
    (path / ".git" / "HEAD").write_text("garbage")

    path = cache.sync("proj", str(origin), "main")
    assert path is not None and (path / "README.md").exists()


def test_an_unreachable_repo_degrades_to_None_and_never_raises(tmp_path):
    """The caller's contract: a cache problem must not block the pipeline — the sizing gate falls
    back to judging from ticket text alone."""
    cache = RepoCache(root=tmp_path / "cache")
    assert cache.sync("proj", str(tmp_path / "does-not-exist"), "main") is None


def test_distinct_keys_keep_distinct_checkouts(tmp_path, origin):
    """One project keeps several repos cached — its code and its documentation repo — and they must
    not overwrite each other."""
    cache = RepoCache(root=tmp_path / "cache")
    code = cache.sync("books", str(origin), "main")
    docs = cache.sync("books--docs", str(origin), "main")
    assert code is not None and docs is not None and code != docs


def test_a_failed_sync_message_never_contains_the_token(tmp_path, capsys):
    """An error string exists to be pasted somewhere."""
    cache = RepoCache(root=tmp_path / "cache")
    assert cache.sync("proj", f"https://x-access-token:{TOKEN}@127.0.0.1:1/nope.git", "main") is None
    assert TOKEN not in capsys.readouterr().out
