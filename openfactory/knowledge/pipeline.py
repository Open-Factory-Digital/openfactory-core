"""The Knowledge Pipeline (§11) — publish the bundle, and hand it to a job.

Phase 2's job is to make the map a real, versioned artifact of the CLIENT repo (§22 D-1/D-2)
without disturbing that repo's normal life. Three functions:

- `publish_bundle`   — push the freshly built bundle to the client repo, post-merge.
- `fetch_published_bundle` — pull the published bundle down for a job to consume.
- `KNOWLEDGE_BRANCH` — where it lives, and why it is not `main`.

**Why a dedicated branch and not `main`.** §22 D-2 left this open and leaned toward `main`
("cleanest — the agent's clone already has it"). Implementing it showed `main` is the wrong
target, for three reasons that have nothing to do with branch protection:

1. **It would trigger the client's deploy.** A project's own CI deploys on push to `main`
   (ADR-0005 watches exactly that). Committing a derived YAML map there fires a real deployment
   for a change that touches no product code — waste, and noise in the deploy history.
2. **It would starve in-flight PRs.** Every commit to `main` puts open PRs BEHIND, and the merge
   loop then spends rebases catching them up (`_REBASE_MAX` exists because a busy base already
   starves jobs). The pipeline would be manufacturing that starvation on every merge.
3. **It needs no protection exemption.** A dedicated branch works whether or not the bot can
   push to a protected `main` — so the capability question stops being load-bearing.

The branch is `openfactory-knowledge` (platform-prefixed, so it cannot collide with a client
branch
that happens to be called `knowledge`), it holds ONLY the `knowledge/` directory, and it
accumulates one commit per source-changing merge — so "what was the map at commit X?" stays
answerable, which was the point of persisting at all.

Everything here is best-effort and never raises at the caller: knowledge is an accelerator, so a
git hiccup must degrade the map, never fail a merged job or a running ticket. Tokened URLs are
redacted from every log line.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from openfactory.knowledge.bundle import BUNDLE_DIRNAME, MANIFEST_FILE, MODULES_FILE

_log = logging.getLogger("openfactory.knowledge.pipeline")

# Platform-owned, so it can never collide with a client branch named `knowledge`.
KNOWLEDGE_BRANCH = "openfactory-knowledge"

_GIT_TIMEOUT = 180


def _redact(text: str) -> str:
    """Strip `user:token@` credentials out of anything we log."""
    return re.sub(r"(https://)[^@/\s]+@", r"\1***@", text or "")


def _git(
    *args: str, cwd: Path | None = None, author: tuple[str, str] | None = None
) -> tuple[int, str]:
    """Run one git command. Returns (returncode, combined output) — never raises, so every
    caller can branch on the code instead of guarding a try."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if author:
        name, email = author
        env.update({
            "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
        })
    try:
        p = subprocess.run(
            ["git", *args], cwd=str(cwd) if cwd else None, capture_output=True, text=True,
            timeout=_GIT_TIMEOUT, env=env, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, _redact(str(exc))
    return p.returncode, _redact((p.stdout or "") + (p.stderr or ""))


def _scrub_remote(repo: Path) -> None:
    """Remove the tokened URL from a throwaway clone's `.git/config`. These checkouts are
    short-lived, but a token on disk is a token on disk — same hygiene as the tech-lead's
    diagnosis clone."""
    _git("remote", "set-url", "origin", "https://invalid.local/scrubbed.git", cwd=repo)


def _has_bundle(d: Path) -> bool:
    return (d / MODULES_FILE).is_file() and (d / MANIFEST_FILE).is_file()


def generate_bundle_for(repo_path: Path) -> Path | None:
    """Build this checkout's module map into a fresh temp directory, and return it (ADR-0023).

    THE MAP IS DERIVED, SO IT IS DERIVED WHERE THE CHECKOUT IS. `build_bundle` is a pure function
    of the tree — 0.24s for 215 files, measured — so a map generated here describes exactly the
    code the agent is about to read. Nothing can drift between generation and use, which is what
    makes the checksum comparison, the staleness detector and the whole refresh-trigger question
    unnecessary on this path.

    OUTSIDE the workspace, always. A bundle written into the agent's tree would be picked up by
    `git add -A` and every client pull request would carry a copy of the map.

    `None` when the tree yields nothing worth mapping — the caller degrades to no injection."""
    from openfactory.knowledge.bundle import build_bundle, write_bundle

    repo_path = Path(repo_path)
    bundle = build_bundle(repo_path, commit=_head_commit(repo_path))
    if not bundle.module_map.modules:
        _log.info("knowledge: %s produced no modules — nothing to inject", repo_path)
        return None

    # SAME SHAPE the fetched path returns — `<tmp>/pub/knowledge`, two levels down — because
    # `discard_fetched_bundle` computes the temp root from it. Returning a different layout was
    # my first version and it silently leaked a directory per job while the injection read
    # nothing: the caller looked for `manifest.yaml` where `write_bundle` had put `knowledge/`.
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-knowledge-"))
    pub = tmp / "pub"
    pub.mkdir(parents=True, exist_ok=True)
    # `force=True`: write_bundle normally skips when the DERIVED content is unchanged, which is
    # right when publishing to a branch (it stops a refresh triggered by the previous refresh
    # from looping). Here the directory is new every time, so the comparison has nothing to
    # compare against and skipping would leave the caller with nothing.
    written = write_bundle(bundle, pub, force=True)
    if written is None:
        shutil.rmtree(tmp, ignore_errors=True)
        _log.warning("knowledge: the bundle was generated but not written — no map this run")
        return None
    return pub / BUNDLE_DIRNAME


def _head_commit(repo_path: Path) -> str:
    """The commit this checkout is on — provenance for the artefact, not a freshness check.

    Nothing depends on it being right: the map is generated from the tree itself, so a repo with
    no git metadata still produces a usable map with an empty stamp."""
    import subprocess

    try:
        p = subprocess.run(["git", "-C", str(repo_path), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=15, check=False)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception as exc:  # noqa: BLE001 — a stamp, never a gate
        _log.info("knowledge: could not read HEAD of %s (%s) — the map is still valid, its "
                 "provenance stamp will just be empty", repo_path, exc)
        return ""


def fetch_published_bundle(remote_url: str, *, branch: str = KNOWLEDGE_BRANCH) -> Path | None:
    """Download the published bundle and return the directory holding `modules.yaml` +
    `manifest.yaml`, or None when there is nothing published (or anything goes wrong).

    **The caller owns the returned directory's PARENT and must delete it** — it is a temp
    checkout, and leaking one per job fills the worker's disk.

    Note this deliberately returns a directory OUTSIDE any job workspace. The bundle must never
    be planted inside the agent's tree: `git add -A` would sweep it into the ticket's commit and
    every PR would carry a copy of the map. It is data we hand to the injector, not a file we
    leave lying in the agent's checkout."""
    if not remote_url:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-knowledge-"))
    rc, out = _git("clone", "--depth", "1", "--single-branch", "--branch", branch,
                   remote_url, str(tmp / "pub"))
    if rc != 0:
        # No published bundle yet (the branch doesn't exist) is the NORMAL first-run state, not
        # an error: the job simply runs without a map until the first post-merge refresh.
        _log.info("knowledge: no published bundle on %s (%s)", branch, out.strip()[:200])
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    _scrub_remote(tmp / "pub")
    bundle_dir = tmp / "pub" / BUNDLE_DIRNAME
    if not _has_bundle(bundle_dir):
        _log.warning("knowledge: %s has no %s/ bundle — ignoring", branch, BUNDLE_DIRNAME)
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    return bundle_dir


def discard_fetched_bundle(bundle_dir: Path | None) -> None:
    """Delete the temp checkout `fetch_published_bundle` created. Callers pass back exactly what
    they were given; the layout of the throwaway dir stays this module's business (before, two
    call sites each hand-computed `bundle_dir.parent.parent`, which is the kind of coupling that
    silently starts deleting the wrong thing the day the layout changes)."""
    if bundle_dir is None:
        return
    root = bundle_dir.parent.parent  # <tmp>/pub/knowledge → <tmp>
    if root.name.startswith("openfactory-knowledge"):  # only rmtree OUR OWN
        shutil.rmtree(root, ignore_errors=True)


def _stage_bundle(pub: Path, bundle_dir: Path, branch: str, remote_url: str) -> bool:
    """Put `bundle_dir` on the knowledge branch's tip inside the fresh checkout `pub`, staged and
    ready to commit. False if git wouldn't cooperate."""
    # A previous attempt may have left a partial directory behind; `git init` into one that has a
    # half-written `.git` is a worse state than starting over.
    shutil.rmtree(pub, ignore_errors=True)
    rc, _ = _git("clone", "--depth", "1", "--single-branch", "--branch", branch,
                 remote_url, str(pub))
    if rc != 0:
        # First publish: create the branch from nothing. It holds ONLY the bundle, so an empty
        # init (not a branch off main) is exactly right — no client code is carried, and nothing
        # on this branch can ever conflict with theirs.
        pub.mkdir(parents=True, exist_ok=True)
        if _git("init", "-q", "-b", branch, str(pub))[0] != 0:
            return False
        if _git("remote", "add", "origin", remote_url, cwd=pub)[0] != 0:
            return False
    dest = pub / BUNDLE_DIRNAME
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(bundle_dir, dest)
    return _git("add", "-A", BUNDLE_DIRNAME, cwd=pub)[0] == 0


def publish_bundle(
    bundle_dir: Path, remote_url: str, *, source_commit: str = "",
    branch: str = KNOWLEDGE_BRANCH,
    author: tuple[str, str] = ("openfactory-bot", "openfactory-bot@local"),
) -> bool:
    """Commit `bundle_dir`'s contents onto the knowledge branch and push. True when a new commit
    landed, False when there was nothing to publish or anything failed (best-effort).

    The branch accumulates history — we clone its tip when it exists and commit on top — so each
    refresh is one commit stamped with the source commit it describes.

    A push rejected as non-fast-forward means someone published between our clone and our push.
    We re-clone the new tip and re-apply ONCE: without that, the loser's map is silently dropped
    and the project sits on a stale map until the next source-changing merge happens to come
    along — silent staleness is precisely what §12 is built to avoid."""
    if not (remote_url and _has_bundle(bundle_dir)):
        return False
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-knowledge-pub-"))
    pub = tmp / "pub"
    stamp = (source_commit or "unknown")[:12]
    try:
        for attempt in (1, 2):
            if not _stage_bundle(pub, bundle_dir, branch, remote_url):
                return False
            # No diff → nothing to publish. The caller normally already knows this (write_bundle
            # returns None on unchanged sources), but checking here too means this function alone
            # cannot manufacture an empty commit that re-triggers the pipeline.
            if _git("diff", "--cached", "--quiet", cwd=pub)[0] == 0:
                _log.info("knowledge: published bundle already current — nothing to push")
                return False
            rc, out = _git("commit", "-q", "-m",
                           f"chore(knowledge): refresh module map @ {stamp}",
                           cwd=pub, author=author)
            if rc != 0:
                _log.warning("knowledge: commit failed (%s)", out.strip()[:200])
                return False
            rc, out = _git("push", "origin", f"HEAD:refs/heads/{branch}", cwd=pub)
            if rc == 0:
                _log.info("knowledge: published module map @ %s to %s", stamp, branch)
                return True
            if attempt == 1:
                _log.info("knowledge: push to %s rejected — re-basing on the new tip (%s)",
                          branch, out.strip()[:160])
                continue
            _log.warning("knowledge: push to %s failed (%s)", branch, out.strip()[:300])
        return False
    finally:
        # ALWAYS — this checkout has a tokened remote and lives on a worker with finite disk.
        shutil.rmtree(tmp, ignore_errors=True)
