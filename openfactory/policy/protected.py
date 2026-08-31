"""Paths the agent may not change without a person — the verifier's own inputs.

THE HOLE THIS CLOSES. The agent holds `Edit`/`Write` over the whole workspace
(`_DEFAULT_TOOLS`, `orchestrator/context.py`) and nothing deterministic stopped it from editing
the things that DECIDE whether it passed: coverage thresholds, CI configuration, and
`.openfactory/project.yaml` itself — the file naming the gates it must survive. `roles/executor.md`
spends a paragraph asking it not to. That paragraph is the weak form of a rule, and this platform's
whole thesis is that the weak form does not hold.

`.github/workflows/**` looked protected and was protected at the WRONG MOMENT: the forge rejects
the push, so the agent edits freely, works, and the work is lost at the end. A guard that fires
after the expensive part is a guard that costs more than the defect it catches.

THE DISTINCTION THAT KEEPS THIS FROM BREAKING ORDINARY WORK, and it is the one the executor prompt
could never draw: a protected path is not forbidden, it is HUMAN-GATED. A ticket that legitimately
needs to raise a coverage floor or add a workflow is a ticket a person signs off — which is what
this platform already means by `merge_policy: human`. Nothing is refused, nothing is lost, and the
change simply cannot merge by itself.

THE LIST ONLY EVER GROWS, and it grows in one direction. The deployment's floor is inherited by
every project; a project may ADD to it and cannot subtract, exactly like `validate:` gates and for
the same reason `floor.yaml` states about itself: *"there is deliberately no deployment-wide off
switch, because an off switch for the floor is the first thing that gets set."* A project that
believes a floor entry is wrong argues with the deployment, not with its own manifest.

WHAT IS DELIBERATELY NOT HERE. Coverage thresholds live INSIDE files that also carry legitimate,
frequent edits — `fail_under` in `pyproject.toml` sits beside the dependency list. Protecting the
file would human-gate every dependency bump, which is the fix doing more damage than the defect;
protecting the SETTING needs a content-level guard that reads the diff hunk, not the path. So the
floor holds only paths whose every edit is a change to the verifier, and the threshold half is
named here as open rather than quietly counted as done.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import yaml

from openfactory.contracts.manifest import Manifest
from openfactory.policy.presets import ORG_FLOOR_FILE

log = logging.getLogger("openfactory.policy.protected")

#: Kept on the assessment for a pull request body a person reads, so a change that moved four
#: hundred files does not print four hundred lines. The count stays exact either way.
MAX_SHOWN = 12


@lru_cache(maxsize=1)
def floor_protected_paths() -> tuple[str, ...] | None:
    """The deployment's protected globs, or None if its floor cannot be read.

    NONE IS NOT `()`, and the difference is the whole safety of this function. `()` is a deployment
    that read the file and declares no protected path. `None` is a build that cannot read its own
    floor — the file missing from a wheel, an unparseable edit, a permission error — and the caller
    turns that into a human gate rather than into permission. A broken install stops the queue
    instead of quietly widening what may merge, which is the correct direction for a floor and the
    expensive one for us.

    CACHED FOR THE PROCESS, like `org_default_validation` beside it, for the same reason and with
    the same caveat: a test that edits the file must call `floor_protected_paths.cache_clear()`.
    """
    try:
        raw = yaml.safe_load(ORG_FLOOR_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        log.error(
            "OPENFACTORY_FLOOR_UNREADABLE the deployment's protected paths at %s could not be read "
            "(%s) — every change is treated as touching the verifier until this file parses.",
            ORG_FLOOR_FILE, exc)
        return None
    if raw is None:
        # READ, NOTHING THERE. A file holding only comments is a deployment that ships no floor
        # entry; that is a configuration, not a broken install.
        return ()
    if not isinstance(raw, dict):
        log.error("OPENFACTORY_FLOOR_UNREADABLE %s must be a YAML mapping, not %s.",
                  ORG_FLOOR_FILE, type(raw).__name__)
        return None
    declared = raw.get("protected_paths")
    if declared is None:
        return ()
    if not isinstance(declared, list) or not all(isinstance(p, str) for p in declared):
        log.error("OPENFACTORY_FLOOR_UNREADABLE %s: `protected_paths:` must be a list of globs, "
                  "not %s", ORG_FLOOR_FILE, type(declared).__name__)
        return None
    return tuple(p.strip() for p in declared if p.strip())


def effective_protected_paths(manifest: Manifest) -> tuple[str, ...] | None:
    """The floor plus whatever this project added. None propagates — an unreadable floor is not a
    project with no protected paths, and the two must not arrive at the caller as one answer."""
    floor = floor_protected_paths()
    if floor is None:
        return None
    own = tuple(p.strip() for p in (getattr(manifest, "protected_paths", None) or []) if p.strip())
    out: list[str] = []
    for glob in (*floor, *own):
        if glob not in out:
            out.append(glob)
    return tuple(out)


def violations(diff_paths: list[str] | None, manifest: Manifest) -> tuple[str, ...]:
    """Which changed paths are the verifier's own inputs. Pure, total, and never raises.

    An empty diff is not a violation: nothing changed, so nothing reached the verifier. That is the
    same reading `risk.assess` gives an empty diff, and for the same reason — there is no silence
    to catch where there was no change.
    """
    from openfactory.orchestrator.validation import _touches

    paths = [p for p in (diff_paths or []) if p]
    if not paths:
        return ()
    globs = effective_protected_paths(manifest)
    if globs is None:
        # THE UNREADABLE FLOOR, ARRIVING AS A GATE RATHER THAN AS PERMISSION. Every changed path is
        # reported, because the platform cannot say which of them were protected and the honest
        # answer to "may this merge by itself" is no.
        return tuple(sorted(paths)[:MAX_SHOWN])
    hit = [p for p in paths if any(_touches(p, g) for g in globs)]
    return tuple(sorted(hit)[:MAX_SHOWN])


def reason(hits: tuple[str, ...]) -> str:
    """One line for the pull request body. A gate that refuses without naming what it refused is a
    gate nobody can argue with, and every other gate in this platform names its reason."""
    if not hits:
        return ""
    shown = ", ".join(f"`{p}`" for p in hits)
    return (f"this change edits the verifier's own inputs ({shown}) — it is human-gated by "
            f"definition, because the thing being measured cannot also move the ruler")
