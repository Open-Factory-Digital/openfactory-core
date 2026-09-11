"""The Knowledge Pipeline (§11) — publish the bundle, and hand it to a job.

Publishes the freshly built module map into the project's CONTEXT repository (`<project>-context`,
ADR-0045 §6 — the bundle's home, and why it is not the client's `main`), never into the client's
own source repository. Three things, one of them
in two shapes:

- `publish_bundle`   — push the freshly built bundle to the context repo, post-merge.
- `fetch_bundle`     — pull the published bundle down for a consumer, and say WHICH empty it hit
                       when there is none; `fetch_published_bundle` is its path-only form, for the
                       callers to which both empties mean the same thing.
- `okf_subpath`      — where inside the context repo one source's bundle lives, and why.

**UPDATE: this used to publish to an orphan branch (`openfactory-knowledge`) inside the CLIENT's
own repository, for three reasons that have nothing to do with branch protection — pushing to
`main` fires the client's deploy (ADR-0005), it starves in-flight PRs, and it needs push rights on
a possibly-protected branch. None of those three reasons apply to a context repository the
platform itself created (`product/onboard.py::create_context_repository`) and already writes
human-reviewed onboarding docs into (`onboarding/context.py::write_documents`) — so the bundle
moved there instead, onto that repository's own default branch, alongside `docs/`
(`docs/knowledge-layer.md` D-2/D-6 carry the full history and the reasoning kept below for why the
client's own repo is never written to at all).**

`okf_subpath` names one folder per source repository (`.okf/repos/<owner>--<name>/`, D-2), so a
multirepo product's several sources never collide, and it accumulates one commit per
source-changing merge — so "what was the map at commit X?" stays answerable, which was the point
of persisting at all.

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
from typing import NamedTuple

from openfactory.knowledge.bundle import BUNDLE_DIRNAME, MANIFEST_FILE, MODULES_FILE
from openfactory.runtime.repo_cache import current_branch

_log = logging.getLogger("openfactory.knowledge.pipeline")

#: D-3: `.okf/`, not `knowledge/`. D-2: one folder per source, under `repos/`.
OKF_DIRNAME = ".okf"
OKF_REPOS_DIRNAME = "repos"

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


def okf_subpath(source_repo: str) -> Path:
    """`.okf/repos/<flattened source>` — where inside the CONTEXT repository one source repo's
    bundle lives (D-2: one folder per source; D-3: `.okf/`, not `knowledge/`).

    Flattened the same way `runtime.card_repo._checkout_key` already disambiguates two
    repositories of the same bare name in a multirepo product (`owner/name` -> `owner--name`) —
    without that helper's project-name prefix, which exists for a cache SHARED across projects and
    is redundant here: this path already lives inside one project's own context repository."""
    flat = (source_repo or "unknown").strip().strip("/").replace("/", "--")
    return Path(OKF_DIRNAME) / OKF_REPOS_DIRNAME / flat


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


class Fetched(NamedTuple):
    """What a fetch ESTABLISHED — the bundle, or which of the two empties it hit.

    THE TWO WAYS TO COME BACK WITH NOTHING ARE DIFFERENT FACTS, and until a consumer had to tell
    them apart both collapsed into `None`. "Nothing has ever been published" is the normal state of
    every project before its first backfill and is worth no words to anybody; "the context
    repository could not be read" is a FAILED READ, and a consumer that renders the second as the
    first tells its reader this project has no map — a claim about the client's codebase produced
    by a read that failed, which is the shape this repository names by memory.

    `unreadable` is non-empty for that second case only, and it is a sentence a person can read.
    """

    path: Path | None
    unreadable: str = ""


def fetch_published_bundle(remote_url: str, *, subpath: Path) -> Path | None:
    """`fetch_bundle`'s directory, for the callers to which both empties mean the same thing.

    Publishing is one: a refresh that cannot read what is live rebuilds from a tree without it and
    compares against nothing, exactly as a first-ever publish does. A caller that SHOWS the absence
    to a reader wants `fetch_bundle` instead — that reader has to be told which empty it is.
    """
    return fetch_bundle(remote_url, subpath=subpath).path


def fetch_bundle(remote_url: str, *, subpath: Path) -> Fetched:
    """Download the published bundle from `subpath` inside the CONTEXT repository and return the
    directory holding `modules.yaml` + `manifest.yaml` — or, when there is none, whether that was
    an absence or a read that failed.

    **The caller owns the returned directory's PARENT and must delete it via
    `discard_fetched_bundle`** — it is a temp checkout, and leaking one per job fills the worker's
    disk.

    CLONES WITHOUT A BRANCH NAME, DELIBERATELY. The context repository's default branch is not a
    constant the way the old orphan branch was — guessing one and reacting to a failed
    `--branch <guess>` clone by starting an orphan history would treat "the branch exists under a
    different name" identically to "nothing has ever been published", and the next publish would
    then try to push disconnected history onto a real branch — rejected forever, silently
    degrading every future refresh to failure. A plain clone succeeds for any reachable repository
    regardless of its branch name or whether it has any commits yet; `current_branch` then tells
    apart "born-empty, nothing published" from "has history".

    Note this deliberately returns a directory OUTSIDE any job workspace. The bundle must never
    be planted inside the agent's tree: `git add -A` would sweep it into the ticket's commit and
    every PR would carry a copy of the map. It is data we hand to the injector, not a file we
    leave lying in the agent's checkout."""
    if not remote_url:
        # NOT A FAILED READ. No context repository was named, so nothing was attempted — the state
        # of a project onboarded before context repositories existed.
        return Fetched(None)
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-knowledge-"))
    pub = tmp / "pub"
    rc, out = _git("clone", "--depth", "1", remote_url, str(pub))
    if rc != 0:
        _log.info("knowledge: could not clone the context repository (%s)", out.strip()[:200])
        shutil.rmtree(tmp, ignore_errors=True)
        # THE ONE UNREADABLE. Everything below this line distinguishes shapes of "published
        # nothing"; a clone that did not come back establishes nothing at all about the bundle.
        return Fetched(None, "the context repository could not be read")
    if not current_branch(pub):
        # A context repository with no commits at all — nothing has ever been published, the
        # NORMAL first-run state, not an error.
        _log.info("knowledge: the context repository has no commits yet — nothing published")
        shutil.rmtree(tmp, ignore_errors=True)
        return Fetched(None)
    _scrub_remote(pub)
    bundle_dir = pub / subpath
    if not _has_bundle(bundle_dir):
        _log.info("knowledge: %s has no bundle yet — ignoring", subpath)
        shutil.rmtree(tmp, ignore_errors=True)
        return Fetched(None)
    return Fetched(bundle_dir)


def discard_fetched_bundle(bundle_dir: Path | None) -> None:
    """Delete the temp checkout `fetch_published_bundle` (or `generate_bundle_for`) created.
    Callers pass back exactly what they were given; the layout of the throwaway dir stays this
    module's business.

    WALKS UP RATHER THAN ASSUMING A FIXED DEPTH. `bundle_dir` sits two segments under its temp
    root for a locally-generated bundle (`<tmp>/pub/knowledge`) and four for a fetched one
    (`<tmp>/pub/.okf/repos/<source>`) — a single computed hop count stopped matching the day the
    context-repo relocation added two more path segments, which would have leaked one temp
    directory per job (a disk-fill regression, not a crash — the kind nobody notices until the
    disk is full). Walking finds `<tmp>` regardless of how many segments sit under it, and stops
    at the FIRST match so it can never wander into an unrelated ancestor directory."""
    if bundle_dir is None:
        return
    for ancestor in (bundle_dir, *bundle_dir.parents):
        if ancestor.name.startswith("openfactory-knowledge"):  # only rmtree OUR OWN
            shutil.rmtree(ancestor, ignore_errors=True)
            return


def _stage_bundle(pub: Path, bundle_dir: Path, subpath: Path, remote_url: str) -> tuple[bool, str]:
    """Put `bundle_dir` at `subpath` inside the context repository's checkout `pub`, staged and
    ready to commit. Returns `(ok, branch)` — the caller needs the discovered branch name for the
    push refspec, since (unlike the old orphan branch) it isn't known in advance; see
    `fetch_published_bundle` for why guessing one is unsafe."""
    shutil.rmtree(pub, ignore_errors=True)
    if _git("clone", "--depth", "1", remote_url, str(pub))[0] != 0:
        return False, ""
    branch = current_branch(pub)
    if not branch:
        # An unborn HEAD — the context repository exists but has no commits yet. `-B` creates the
        # branch and the checkout together, the same convention onboarding's own context-repo
        # writer already uses for a born-empty repository (`onboarding/onboard.py`).
        branch = "main"
        if _git("checkout", "-B", branch, cwd=pub)[0] != 0:
            return False, ""
    dest = pub / subpath
    dest.parent.mkdir(parents=True, exist_ok=True)  # `.okf/repos/` may not exist yet
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(bundle_dir, dest)
    return _git("add", "-A", str(subpath), cwd=pub)[0] == 0, branch


def publish_bundle(
    bundle_dir: Path, remote_url: str, *, subpath: Path, source_commit: str = "",
    author: tuple[str, str] = ("openfactory-bot", "openfactory-bot@local"),
) -> bool:
    """Commit `bundle_dir`'s contents at `subpath` inside the context repository's default branch
    and push. True when a new commit landed, False when there was nothing to publish or anything
    failed (best-effort).

    NEVER `--force`. A push rejected as non-fast-forward means someone else committed to this
    branch between our clone and our push — another source's refresh in the same multirepo
    project, or a human merging the onboarding docs PR onto the same branch `.okf/` now shares
    with `docs/`. We re-clone the new tip and re-apply ONCE: without that, the loser's map is
    silently dropped and the project sits on a stale map until the next refresh happens to come
    along — silent staleness is precisely what §12 is built to avoid, and a plain push with retry
    is what keeps this safe to share a branch with content this module does not own."""
    if not (remote_url and _has_bundle(bundle_dir)):
        return False
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-knowledge-pub-"))
    pub = tmp / "pub"
    stamp = (source_commit or "unknown")[:12]
    try:
        for attempt in (1, 2):
            ok, branch = _stage_bundle(pub, bundle_dir, subpath, remote_url)
            if not ok:
                return False
            # No diff → nothing to publish. The caller normally already knows this (write_bundle
            # returns None on unchanged sources), but checking here too means this function alone
            # cannot manufacture an empty commit that re-triggers the pipeline.
            if _git("diff", "--cached", "--quiet", cwd=pub)[0] == 0:
                _log.info("knowledge: published bundle already current — nothing to push")
                return False
            rc, out = _git("commit", "-q", "-m",
                           f"chore(okf): refresh module map @ {stamp}",
                           cwd=pub, author=author)
            if rc != 0:
                _log.warning("knowledge: commit failed (%s)", out.strip()[:200])
                return False
            rc, out = _git("push", "origin", f"HEAD:refs/heads/{branch}", cwd=pub)
            if rc == 0:
                _log.info("knowledge: published module map @ %s to %s", stamp, subpath)
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
