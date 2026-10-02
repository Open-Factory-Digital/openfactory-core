"""A change's own shape, previewed once a product admin has read it and allowed it (#348).

THE RULE THIS IS AN EXCEPTION TO (ADR-0050 D3). A preview's shape is read from the base branch,
never from the change: the compose file lives in the repository the agent edits, and running the
change's own would run whatever the change declared. So a change whose point IS the shape (a new
`redis` service, a new dependency between services, a new environment value) was previewed without
its point, and seen running only after it merged.

THE EXCEPTION, AND EVERYTHING THAT BOUNDS IT:

  · A PERSON UNLOCKS IT. A product admin reads the change's shape (the pull request lists every
    file a preview would read, with a hash) and allows it, for one unit. The agent never decides it,
    and nothing allows it by default.
  · BOUND TO WHAT WAS READ. The allowance names the shape's DIGEST: the block and every file the
    shape reads, `extends:` included. A push that changes any of them is a different digest, and the
    preview goes back to the base's shape until somebody looks again.
  · THE SAME ADMISSION. The change's files are laid over the base tree in the preview's own work
    directory and read from there by the one reader (`read.shape`): the same pre-scan, the same
    compose CLI, the same key-by-key admission. A key the base's shape would be refused for is
    refused here by name.
  · D4 STILL HOLDS. Laid over the base tree, the change's shape still runs the change only where the
    change touched, and the base everywhere else.
  · SAID. The card's preview says which shape ran, whose allowance it was, and its digest.

A product's shape (`.openfactory/product.yaml` in the context repository) has no exception yet: a
change to it is previewed with the base's, as before.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import posixpath
from dataclasses import dataclass
from datetime import UTC, datetime

from openfactory.contracts.manifest import PreviewConfig
from openfactory.preview.plan import Layout, Refused

log = logging.getLogger("openfactory.preview.own")

#: The metrics-sink kind an allowance is recorded under: one row per allowance, the newest wins.
KIND = "preview_shape"


@dataclass(frozen=True)
class OwnShape:
    """The change's own shape: its block, every file it reads, and their digest."""

    digest: str
    cfg: PreviewConfig
    texts: dict[str, str]


def digest(cfg: PreviewConfig, texts: dict[str, str]) -> str:
    """One hash over the block and every file the shape reads, by its layout-relative path.

    THE BLOCK IS IN IT, not only the files: `expose`, `data` and `exclude` decide what runs and what
    a person can reach as much as the compose file does."""
    files = {p: hashlib.sha256(t.encode()).hexdigest() for p, t in sorted(texts.items())}
    body = json.dumps({"preview": cfg.model_dump(mode="json"), "files": files}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def short(d: str) -> str:
    """The digest as a person compares it: the first twelve characters."""
    return d[:12]


def of_the_change(layout: Layout, *, tree: str, change_cfg: PreviewConfig | None,
                  of: str = "this preview") -> OwnShape | str:
    """The change's own shape, or why it cannot be read — a sentence; the base's shape is then the
    one previewed, as before.

    Read from `<workdir>/change/<tree>`, inside that checkout only, and NEVER handed to the compose
    CLI here: this measures what an allowance would name."""
    from openfactory.preview.read import texts_of

    if change_cfg is None:
        return ("the change has no `preview:` block, so it has no shape of its own to run — it is "
                "previewed with the base's")
    if tree not in layout.trees or not layout.trees[tree].has_change:
        return "the repository the shape lives in has no change in this unit"
    read = texts_of(layout, change_cfg, tree=tree, side="change", of=of)
    if isinstance(read, Refused):
        return "the change's own shape cannot be read: " + " ".join(read.reasons)
    texts, _found = read
    return OwnShape(digest=digest(change_cfg, texts), cfg=change_cfg, texts=texts)


def overlay(layout: Layout, *, tree: str, texts: dict[str, str]) -> str:
    """Lay the change's shape files over the base tree of the preview's own work directory, so the
    one reader reads them — `""` when laid, or why not (the base's shape is then the one run).

    EVERY WRITE STAYS IN THE TREE. A path is written only when it resolves under
    `<workdir>/base/<tree>` with every directory on the way real and inside it; whatever is at the
    path is replaced, never followed, so a link the base committed there cannot carry the write out
    of the work directory."""
    side_all = os.path.realpath(posixpath.join(layout.workdir, "base"))
    root = os.path.realpath(layout.root(tree, "base"))
    for rel, text in texts.items():
        dest = posixpath.normpath(posixpath.join(side_all, rel))
        if not dest.startswith(root + os.sep):
            return (f"`{rel}` is outside the repository the shape lives in, so the change's own "
                    f"shape is not laid over the base")
        here = root
        for part in posixpath.relpath(posixpath.dirname(dest), root).split("/"):
            if part in ("", "."):
                continue
            here = posixpath.join(here, part)
            if os.path.islink(here) or (os.path.lexists(here) and not os.path.isdir(here)):
                return (f"a directory on the way to `{rel}` is a link or a file on the base, so "
                        f"the change's own shape is not laid over it")
            if not os.path.lexists(here):
                os.mkdir(here)
        if os.path.isdir(dest) and not os.path.islink(dest):
            return f"`{rel}` is a directory on the base, so the change's own shape is not laid"
        if os.path.lexists(dest):
            os.unlink(dest)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                     0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    return ""


# ── the allowance ────────────────────────────────────────────────────────────────────────────────


def allow_shape(project: str, token: str, shape_digest: str, by: str) -> bool:
    """Record that `by` allowed the shape `shape_digest` for one unit's preview. Best-effort and
    said: an allowance that did not land is one the next start does not find, and the card says it
    is previewed with the base's."""
    try:
        from openfactory.observability.metrics import MetricRecord
        from openfactory.observability.registry import deployment_metrics_sink

        return bool(deployment_metrics_sink().record(MetricRecord(
            project=project, ticket=str(token), ts=datetime.now(UTC).isoformat(), kind=KIND,
            role="allowed", extra={"unit": str(token), "digest": shape_digest, "by": by})))
    except Exception as exc:  # noqa: BLE001
        log.warning("[%s] could not record the allowance of %s's own shape (%s)", project, token,
                    exc)
        return False


def allowed(project: str, token: str) -> tuple[str, str] | None:
    """`(digest, who allowed it)` — the newest allowance for one unit, or None."""
    from openfactory.observability.query import records_of_kind

    try:
        rows = [r for r in records_of_kind(project, KIND)
                if str((r.get("extra") or {}).get("unit", "")) == str(token)]
    except Exception as exc:  # noqa: BLE001 — an unreadable store allows nothing
        log.warning("[%s] could not read the allowances of %s (%s)", project, token, exc)
        return None
    if not rows:
        return None
    extra = max(rows, key=lambda r: str(r.get("ts", ""))).get("extra") or {}
    d = str(extra.get("digest") or "")
    return (d, str(extra.get("by") or "")) if d else None
