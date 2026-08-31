"""Load framework-owned stack presets (ADR-0001 D-2, layer 2) and the DEPLOYMENT's own defaults.

Two layers live here, and they are not the same thing:

    a PRESET      the platform's opinion about a stack ("python projects lint with ruff"). Opted
                  into, per component, by writing `stack: python`. It only ever runs when a diff
                  reaches that component.
    the FLOOR     the platform's opinion about EVERY project, whatever it is written in. Opted
                  out of, per role, by declaring that role yourself. It runs on every diff.

The second did not exist before `org_defaults/floor.yaml`, which is why "adopt the security preset
across the fleet" meant editing the manifest of every client repository by hand and
why a new client inherited nothing at all.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml

log = logging.getLogger("openfactory.policy.presets")

_PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"

#: The deployment's default gates. `org_defaults/` is where the platform's opinion already lives
#: (engineering.md, tdd.md, roles/*.md), so it is where the opinion that is executable lives too.
ORG_FLOOR_FILE = Path(__file__).resolve().parent.parent / "org_defaults" / "floor.yaml"


def load_preset(stack: str) -> dict:
    """Return the preset for a stack (e.g. 'python'), or {} if none is shipped."""
    path = _PRESETS_DIR / f"{stack}.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def available_stacks() -> list[str]:
    return sorted(p.stem for p in _PRESETS_DIR.glob("*.yaml"))


@lru_cache(maxsize=1)
def floor_document() -> dict | None:
    """The deployment's floor, read and parsed ONCE — or None if this install cannot read it.

    ONE PARSE, BECAUSE TWO GATES TURN ON IT. `org_default_validation` below and
    `protected.floor_protected_paths` both ask this file a question and both turn the answer into a
    merge gate, so the one property worth having structurally rather than by review is that they
    can never disagree about whether the floor is READABLE. This function existed as two
    transcriptions of each other for exactly one review cycle, which is one more than the pair
    below earned: the `ValueError` in the except clause was found by a fleet-wide outage, and a copy
    inherits that fix by luck rather than by construction.

    NONE IS NOT `{}`, and every caller depends on the distinction. `{}` is a deployment that read
    the file and shipped an empty one — a legitimate configuration. `None` is a build that cannot
    read its own floor: the file missing from a wheel, an unparseable edit, a permission error. The
    callers turn `None` into a gate rather than into permission, so a broken install stops the queue
    instead of quietly widening what may run. That is the correct direction for a floor and the
    expensive one for us — and the remedy each caller prints blames OUR install rather than the
    client's repository.

    CACHED FOR THE PROCESS. `Manifest` is constructed on every job, every doctor run and every
    poller tick. A test that edits the file must call `clear_floor_caches()`, which reaches this
    cache and every accessor's — clearing an accessor alone would leave the stale document here.
    """
    try:
        # `encoding="utf-8"` explicitly, not the locale default: a worker container with no locale
        # set reads ASCII, and this file's comments carry non-ASCII characters — the same bytes
        # would then be "unreadable" on the worker and fine on a developer's machine.
        raw = yaml.safe_load(ORG_FLOOR_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.error(
            "OPENFACTORY_FLOOR_UNREADABLE the deployment's floor is missing at %s — no project "
            "inherits a floor gate and no protected path is known, so every project must declare "
            "`test` and `security` itself and every change is treated as touching the verifier. "
            "This file ships inside the `openfactory` package; a build without it is incomplete.",
            ORG_FLOOR_FILE)
        return None
    # `ValueError` IS IN THIS TUPLE FOR ONE MEASURED REASON, and it is the only branch of this
    # function that ever escaped. A `floor.yaml` that is not valid UTF-8 — a truncated or corrupted
    # copy in an image layer — raises `UnicodeDecodeError` (a `ValueError`, not an `OSError`) out
    # of `read_text`, and this function is called from a `Manifest` model validator: the exception
    # came back as `ValidationError: 1 validation error for Manifest`, so a broken INSTALL was
    # reported to the client as a broken `.openfactory/project.yaml` and every project in the fleet
    # stopped loading. Every other unreadable shape already returned None and blamed the install;
    # this one contradicted both halves of that at once.
    except (OSError, ValueError, yaml.YAMLError) as exc:
        log.error(
            "OPENFACTORY_FLOOR_UNREADABLE the deployment's floor at %s could not be read (%s) — "
            "no project inherits a floor gate and no protected path is known until it parses.",
            ORG_FLOOR_FILE, exc)
        return None
    if raw is None:
        # AN EMPTY DOCUMENT IS READ, NOTHING THERE — caught by the guard that asserts the two are
        # different answers. A file holding only comments parses to None, and calling that
        # "unreadable" would report a broken install to a deployment that had deliberately emptied
        # its floor: the same conflation this function exists to prevent, from the other side.
        return {}
    if not isinstance(raw, dict):
        log.error(
            "OPENFACTORY_FLOOR_UNREADABLE %s must be a YAML mapping, not %s.",
            ORG_FLOOR_FILE, type(raw).__name__)
        return None
    return raw


#: Every memoised answer about `floor.yaml`, so ONE call clears all of them. The parse moved down
#: into `floor_document()`, so clearing an accessor alone would leave the stale document in place —
#: and a test that rewrote the floor would read the old one, silently, and only in whichever test
#: happened to run second.
_FLOOR_CACHES: list = [floor_document]


def register_floor_cache(fn) -> None:
    """Register another cache over `floor_document()` so `clear_floor_caches()` reaches it.

    `policy/protected.py` calls this at import time. It cannot be listed above without an import
    cycle, and a cache this module does not know about is a cache a test cannot clear.
    """
    if fn not in _FLOOR_CACHES:
        _FLOOR_CACHES.append(fn)


def clear_floor_caches() -> None:
    """Drop every memoised answer about `floor.yaml`. A test that edits the file must call this."""
    for fn in _FLOOR_CACHES:
        fn.cache_clear()


@lru_cache(maxsize=1)
def org_default_validation() -> dict[str, dict | str] | None:
    """The deployment's default `validate:` gates — `{role: gate}` — or None if unreadable.

    NONE IS NOT `{}` HERE, and the distinction is the whole reason this returns an Option rather
    than a dict. `{}` is a deployment that read the file and deliberately declares no default
    gate. `None` is a build that cannot read its own floor. Collapsing the two would mean the floor
    evaporates in exactly the installation where nobody is watching, silently, and every project
    would pass conformance because the platform forgot what it required — the same shape as the
    empty `validate:` block that made `all([])` a green light over nothing.

    THE FAILURE DIRECTION IS CLOSED, not open — and since the floor became unconditional that is
    not a nicety, it is the whole safety of this function. A None means no gate is merged into any
    manifest, so `floor_reason` refuses every project that does not declare `security` itself, and
    the runner HOLDS it. The remedy `floor_reason` prints in that case names OUR install rather
    than the client's repository, and `policy/conformance.check` turns the same None into an error
    naming this path, so nobody is sent to edit a file that was already right.

    The read and the parse are `floor_document()`'s; this is the accessor for one key of it. A test
    that edits the file must call `clear_floor_caches()`.
    """
    raw = floor_document()
    if raw is None:
        return None
    gates = raw.get("validate")
    if gates is None:
        # READ, NOTHING THERE. A file with no `validate:` block is a deployment that has chosen to
        # ship no default gate; that is a legitimate configuration and it is not an error.
        return {}
    if not isinstance(gates, dict):
        log.error("OPENFACTORY_FLOOR_UNREADABLE %s: `validate:` must be a mapping of role → gate, "
                  "not %s",
                  ORG_FLOOR_FILE, type(gates).__name__)
        return None
    return dict(gates)


# REGISTERED HERE RATHER THAN IN THE LIST ABOVE, because the decorator has to have run first: the
# name is only an `lru_cache` object once Python is past the `def`.
register_floor_cache(org_default_validation)
