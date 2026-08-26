"""The harness toolbox: framework-owned binaries, mounted into a client's box (ADR-0037 D2).

WHY IT EXISTS. Under D1 the box is built from the CLIENT's image, so the harness cannot live in it
— we do not control that image and would not want to ask a client to rebuild theirs every time we
pin a new agent CLI. The harness is therefore delivered separately: a directory the worker owns,
mounted read-only at a fixed absolute path, with `SandboxAdapter.harness_path` (D2a) naming the
entry so nothing depends on `PATH` inside an image whose `/etc/profile` we did not write.

WHY IT IS NOT ONE IMAGE PER HARNESS. That is stack × harness images, and three harnesses over five
stacks is fifteen artefacts somebody maintains. Injection makes `harness: {executor: codex,
reviewer: claude_code}` pure configuration — rotating between them, or mixing per role, never
touches an image. That property is what the product is sold on.

WHAT IS ACTUALLY IN IT, measured rather than assumed (the first draft of ADR-0037 assumed all three
were self-contained natives; only `claude` is):

    claude   a native ELF, executed directly
    codex    a `#!/usr/bin/env node` shim over a vendored binary
    kimi     an ESM bundle — Node, always

so the toolbox carries a **Node runtime** too, and the entry for the Node-based harnesses is a
wrapper that names both the runtime and the script absolutely. ~50 MB of Node beside three
harnesses is noise, and going through it uniformly removes a per-harness branch that would work
for two and silently not the third.

THE VARIANT IS A PROPERTY OF THE CLIENT'S IMAGE, NOT OF THE WORKER. `ldd` on the `claude` ELF shows
`ld-linux-<arch>.so.1` — glibc. An Alpine or musl-based client image cannot exec it, and the
failure is the dynamic loader's *no such file or directory*, which names the wrong thing and sends
somebody looking for a missing file that is right there. So a toolbox is stamped with the triple it
was built for, and `openfactory box prove` (D3) is what compares that against the image before a
ticket
ever runs.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
from pathlib import Path

log = logging.getLogger("openfactory.toolbox")

#: Where the built toolbox is baked into the worker image.
SOURCE = Path(os.environ.get("OPENFACTORY_TOOLBOX_SOURCE") or "/opt/openfactory-toolbox-src")

#: Where the worker keeps the copy it mounts into boxes. A named docker volume in compose —
#: NOT a worker-local path, because a `-v` issued by a containerised worker is resolved by the
#: HOST daemon, where a path inside the worker does not exist. Docker would create an empty
#: directory and the box would get an empty toolbox, in silence.
LIVE = Path(os.environ.get("OPENFACTORY_TOOLBOX") or "/var/lib/openfactory-toolbox")

#: Written beside the binaries so a reader — and `box prove` — can tell what this toolbox IS
#: without running anything in it.
STAMP = "toolbox.json"


def variant() -> str:
    """The `<os>-<arch>-<libc>` this toolbox was built for.

    Keyed off the machine that BUILT it. `box prove` compares it against the client's image, which
    is the one that has to execute these bytes — the two are the same only by coincidence."""
    machine = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        platform.machine(), platform.machine() or "unknown"
    )
    libc = "musl" if (Path("/lib/ld-musl-x86_64.so.1").exists()
                      or Path("/lib/ld-musl-aarch64.so.1").exists()) else "glibc"
    return f"{platform.system().lower()}-{machine}-{libc}"


def read_stamp(root: Path | None = None) -> dict:
    """What a toolbox says about itself, or `{}` when there is none.

    Never raises: this is read on the worker's boot path and by a diagnostic, and a malformed
    stamp must degrade into "no toolbox" rather than take either down."""
    path = (root or LIVE) / STAMP
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("the toolbox stamp at %s is unreadable (%s) — treating it as absent", path,
                    exc)
        return {}
    return data if isinstance(data, dict) else {}


def is_populated(root: Path | None = None) -> bool:
    """Whether a usable toolbox is already in place, so a restart is not a re-copy.

    Checks the STAMP rather than the directory: a half-finished copy has files in it and is not a
    toolbox. The stamp is written last, so its presence means the copy completed."""
    stamp = read_stamp(root)
    return bool(stamp.get("harnesses")) and stamp.get("variant") == variant()


def populate(*, source: Path | None = None, live: Path | None = None,
             force: bool = False) -> dict:
    """Copy the baked toolbox into the volume the boxes mount. Idempotent; returns the stamp.

    CALLED ON THE WORKER'S BOOT PATH, so it must be quiet and safe to run every time: an already
    populated volume of the right variant is left alone. `force` is for a harness version bump,
    where the stamp differs and the copy should happen.

    THE STAMP IS WRITTEN LAST, and that is the whole crash-safety story. A worker killed mid-copy
    leaves a directory with some binaries and no stamp; the next boot reads no stamp, calls it
    unpopulated, and copies again. There is no state in which a partial toolbox looks complete.
    """
    src = source or SOURCE
    dst = live or LIVE

    if not src.is_dir():
        # Not an error: a development worker, or an image built without the toolbox stage. The
        # boxes will then find nothing at the mount point, which `openfactory box prove` reports by
        # name.
        log.info("no baked toolbox at %s — boxes will have none (this is a build-time choice)",
                 src)
        return {}

    if not force and is_populated(dst):
        log.debug("toolbox already present at %s (%s)", dst, variant())
        return read_stamp(dst)

    # A TOP-LEVEL NON-DIRECTORY ENTRY, not "an executable file". The real `claude` entry is a
    # symlink to the IN-BOX mount point, so at copy time it is DANGLING — `is_file()` and
    # `os.access(X_OK)` are both False for it, and the stamp would have listed `codex, kimi` and
    # silently omitted the main harness. `box prove` reports this list to a human.
    harnesses = sorted(e.name for e in src.iterdir()
                       if not e.is_dir() and e.name != STAMP)
    dst.mkdir(parents=True, exist_ok=True)
    (dst / STAMP).unlink(missing_ok=True)  # invalidate FIRST: a stale stamp over new bytes lies
    for entry in src.iterdir():
        target = dst / entry.name
        # REPLACE, never merge onto what is there. A crashed run leaves entries behind, and
        # `shutil.copy2(..., follow_symlinks=False)` raises FileExistsError when the target symlink
        # already exists — which is exactly what the real worker hit: the `claude` entry is a
        # symlink into `pkg/`, so every boot failed on the first entry and the volume sat at 95 MB
        # of a 701 MB toolbox for ever, with `codex`, `kimi` and `pkg` never copied at all.
        #
        # Removing first also makes a version bump exact rather than a merge, so a file dropped
        # from a newer toolbox does not linger from the older one.
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        if entry.is_dir():
            shutil.copytree(entry, target, symlinks=True)
        else:
            # `follow_symlinks=False` keeps the entry a LINK. Following it would copy a 260 MB
            # binary to the top level and leave `pkg` unreferenced — twice the disk, and an entry
            # that no longer points at the package it came from. The link targets the IN-BOX mount
            # point, so it is dangling here and resolves where it is mounted.
            shutil.copy2(entry, target, follow_symlinks=False)
            if not target.is_symlink():
                target.chmod(target.stat().st_mode | 0o111)

    stamp = {"variant": variant(), "harnesses": harnesses}
    (dst / STAMP).write_text(json.dumps(stamp, indent=2, sort_keys=True))
    log.info("toolbox populated at %s — %s (%s)", dst, ", ".join(harnesses) or "nothing",
             stamp["variant"])
    return stamp
