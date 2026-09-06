"""Where per-job artifacts live, shared by the CLI (writer) and the API (reader)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from openfactory.contracts.project import Project

#: What may appear in a filename. Everything else becomes `_` and forces the digest below.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")

#: Leaves room for the `-events.jsonl` suffix inside the common 255-byte filename limit.
_MAX_STEM = 200


def project_log_dir(project: Project) -> Path:
    """Where this project's job journals live.

    `OPENFACTORY_LOG_DIR` is the DEPLOYMENT's answer, and it should be the answer everywhere: a
    journal is
    the installation's operational record, with exactly the lifetime of the registry and the
    metrics database — both of which already live under `/var/lib/openfactory` for that reason.

    IT USED TO BE DERIVED FROM `repo_path`, i.e. from where the CLIENT's code happens to sit, and
    three things followed. The panel could never tail a local job: compose mounts a volume at a
    path the journal is never written to, so it was empty on every deployment. A rate-limit-paused
    job was never resumed, because `scheduler.ready_to_resume` globs this directory and an absent
    one returns `[]` for ever — a permanent pause, silently. And a project registered with a clone
    URL (which `--help` invites) wrote into a directory literally named `https:`.

    UNSET KEEPS TODAY'S BEHAVIOUR **for a checkout**, deliberately: no deployed installation
    moves and no journal in flight is orphaned. Compose sets the variable; that is the whole
    migration.

    UNSET FOR A URL-REGISTERED PROJECT HAS NO BEHAVIOUR TO KEEP, which is the half this
    docstring described and did not fix (found as debris, 2026-08-14: `./https:/github.com/o/`
    directories in a repository root, written by real product code under test). `Path(url)`
    collapses `https://` to `https:/` and the journal lands in a directory named after a
    protocol, relative to whatever the process's working directory happens to be — the panel
    cannot tail it, `ready_to_resume` globs an absent directory and pauses for ever, and nobody
    finds it. There is nothing to preserve there, so it resolves where every other piece of
    this installation's state lives.
    """
    import os

    configured = (os.environ.get("OPENFACTORY_LOG_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser() / project.name

    from openfactory.factory import looks_like_a_clone_url

    raw = (project.repo_path or "").strip()
    if not raw or looks_like_a_clone_url(raw):
        # BESIDE THE REGISTRY THIS PROCESS ACTUALLY DRIVES — resolved through `ProjectRegistry`
        # rather than the default constant, so a deployment (or a test) that redirects its
        # registry redirects its journals with it, instead of writing into somebody's home.
        from openfactory.registry import ProjectRegistry

        return ProjectRegistry().path.parent / "logs" / project.name
    return Path(raw).expanduser().parent / ".openfactory-logs" / project.name


def project_memory_dir(project: Project) -> Path:
    """Where this project's memory INDEX lives (#33 hole 3) — beside its journals, for the same
    reason they live where they do: it is the installation's derived state, rebuildable from the
    stores it indexes, with exactly the lifetime of the registry and the metrics database."""
    return project_log_dir(project) / "memory"


def journal_stem(issue: str) -> str:
    """A ticket ref turned into exactly one safe filename component.

    A ref is the PROVIDER's string — `412` on GitHub, `CONT-412` on Jira, whatever Azure DevOps
    decides next — so this cannot assume a shape. It only has to guarantee two things, and the
    second is the one a naive sanitiser loses while fixing the first:

        it cannot escape     no input yields a path component, a parent reference, or a hidden file
        it stays injective   two different refs never land on one journal

    Mapping every unsafe character to `_` gives the first and quietly breaks the second: `a/b` and
    `a_b` become the same file, and one job starts reading another's events with nothing reporting
    it. So a digest of the ORIGINAL ref is appended whenever sanitising changed anything — which
    also means a ref that was already safe keeps the name it has always had. That matters: every
    journal on disk today is `<number>-events.jsonl`, and renaming those would orphan the panel's
    history for every job ever run.

    Why sanitise rather than reject: this is reached from the box mid-job and has no way to report
    a refusal. A job that died for a filename would be a far worse outcome than an ugly one. The
    REFUSING is `api/app.py`'s business, at the door, where there is somebody to tell.
    """
    raw = (issue or "").lstrip("#")
    slug = _UNSAFE.sub("_", raw).lstrip(".-")  # ".." and ".hidden"; a leading "-" reads as a flag
    if not slug or slug != raw or len(slug.encode()) > _MAX_STEM:
        # Digest the ORIGINAL, so "#" and "" — which both strip to nothing — stay distinct.
        digest = hashlib.sha256((issue or "").encode()).hexdigest()[:12]
        stem = slug.encode()[:_MAX_STEM].decode(errors="ignore")
        return f"{stem}-{digest}" if stem else digest
    return slug


def events_file(project: Project, issue: str) -> Path:
    return project_log_dir(project) / f"{journal_stem(issue)}-events.jsonl"
