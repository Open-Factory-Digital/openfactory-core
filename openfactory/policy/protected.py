"""Paths the agent may not change without a person — the verifier's own inputs.

THE HOLE THIS CLOSES. The agent holds `Edit`/`Write` over the whole workspace
(`_DEFAULT_TOOLS`, `orchestrator/context.py`) and nothing deterministic stopped it from editing
the things that DECIDE whether it passed: coverage thresholds, CI configuration, and
`.openfactory/project.yaml` itself — the file naming the gates it must survive, and now also the
PROFILE, the class the project is judged as. `roles/executor.md` spends a paragraph asking it not
to. That paragraph is the weak form of a rule, and this platform's whole thesis is that the weak
form does not hold.

THE DISTINCTION THAT KEEPS THIS FROM BREAKING ORDINARY WORK, and it is the one the executor prompt
could never draw: a protected path is not forbidden, it is HUMAN-GATED. A ticket that legitimately
needs to raise a coverage floor is a ticket a person signs off — which is what this platform
already means by `merge_policy: human`. Nothing is refused, nothing is lost, and the change simply
cannot merge by itself.

THE LIST ONLY EVER GROWS, and it grows in one direction. The deployment's floor is inherited by
every project; a project may ADD to it and cannot subtract, exactly like `validate:` gates and for
the same reason `floor.yaml` states about itself: *"there is deliberately no deployment-wide off
switch, because an off switch for the floor is the first thing that gets set."* A project that
believes a floor entry is wrong argues with the deployment, not with its own manifest.

`.github/workflows/**` IS NOT HERE, AND ITS ABSENCE IS MEASURED RATHER THAN AN OVERSIGHT. The first
revision of this module protected it and claimed to be catching the edit "before the expensive part
rather than after it". Both halves were wrong, and review on #18 measured it: `_commit` reverts
every `.github/workflows/**` change BEFORE the commit (`machine.py`, `git checkout -- .github/
workflows; git clean -fdq`), and `sandbox.diff_paths` reads `base..HEAD` — committed history. A
workflow path can never appear in the diff this gate is asked about, so the entry gated nothing and
its test was green over dead configuration. The premise was already handled too: the strip is
announced on the ticket and `_pr_body` prints a `## ⚠️ CI/workflow changes NOT included` section
listing every dropped file as an explicit human to-do. And this gate is `should_auto_merge`, which
runs after the agent has worked, after the strip and after the push — later than everything the
claim criticised. A guard that cannot fire is worse than a missing one: it is a line an operator
reads as protection.

WHAT IS DELIBERATELY NOT HERE EITHER. Coverage thresholds live INSIDE files that also carry
legitimate, frequent edits — `fail_under` in `pyproject.toml` sits beside the dependency list.
Protecting the file would human-gate every dependency bump, which is the fix doing more damage than
the defect; protecting the SETTING needs a content-level guard that reads the diff hunk, not the
path. So the floor holds only paths whose every edit is a change to the verifier, and the threshold
half is named here as open rather than quietly counted as done.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from openfactory.contracts.manifest import Manifest
from openfactory.policy.presets import (
    ORG_FLOOR_FILE,
    floor_document,
    register_floor_cache,
)

log = logging.getLogger("openfactory.policy.protected")

#: How many paths a reader is shown. Kept for a pull request body a person reads, so a change that
#: moved four hundred files does not print four hundred lines. THE TRUNCATION BELONGS TO THE
#: READER AND NOT TO THE MEASUREMENT: `violations()` returns every hit, `RunResult.protected_count`
#: carries the true number, and `protected_hits` carries this many. The first revision truncated
#: inside the measurement and kept no count, so a change touching forty protected files reported
#: twelve and the number was gone — the same defect `undeclared_paths`/`undeclared_count` was
#: split to avoid, and it is split the same way here.
MAX_SHOWN = 12


@lru_cache(maxsize=1)
def floor_protected_paths() -> tuple[str, ...] | None:
    """The deployment's protected globs, or None if its floor cannot be read.

    NONE IS NOT `()`, and the difference is the whole safety of this function. `()` is a deployment
    that read the file and declares no protected path. `None` is a build that cannot read its own
    floor, and the caller turns that into a human gate rather than into permission — a broken
    install stops the queue instead of quietly widening what may merge.

    The read and the parse are `presets.floor_document()`'s, shared with `org_default_validation`
    so the two gates that turn on this file can never disagree about whether it is READABLE. A test
    that edits the file must call `presets.clear_floor_caches()`.
    """
    raw = floor_document()
    if raw is None:
        return None
    declared = raw.get("protected_paths")
    if declared is None:
        # READ, NOTHING THERE. A floor with no `protected_paths:` block is a deployment that ships
        # no protected path; that is a configuration, not a broken install.
        return ()
    if not isinstance(declared, list) or not all(isinstance(p, str) for p in declared):
        log.error("OPENFACTORY_FLOOR_UNREADABLE %s: `protected_paths:` must be a list of globs, "
                  "not %s", ORG_FLOOR_FILE, type(declared).__name__)
        return None
    return tuple(p.strip() for p in declared if p.strip())


register_floor_cache(floor_protected_paths)


def effective_protected_paths(manifest: Manifest) -> tuple[str, ...] | None:
    """The floor plus whatever this project added. None propagates — an unreadable floor is not a
    project with no protected paths, and the two must not arrive at the caller as one answer."""
    floor = floor_protected_paths()
    if floor is None:
        return None
    own = tuple(p.strip() for p in manifest.protected_paths if p.strip())
    out: list[str] = []
    for glob in (*floor, *own):
        if glob not in out:
            out.append(glob)
    return tuple(out)


def floor_unreadable(manifest: Manifest) -> bool:
    """Whether this install could not read its own floor — a SEPARATE FACT from a violation.

    IT IS ASKED SEPARATELY BECAUSE THE TWO ARE DIFFERENT SENTENCES TO A HUMAN. The first revision
    of `violations()` answered an unreadable floor by returning the alphabetically first twelve
    CHANGED paths: it gated correctly, and every reader downstream — the pull request body, the
    durable `RunResult` — then said a real change had touched the verifier's own inputs when what
    had actually happened was that OUR install was broken. That is the `None`-is-not-`()`
    distinction this module opens with, collapsed one layer down, and it sends a person to the
    wrong file with the wrong sentence.
    """
    return effective_protected_paths(manifest) is None


def violations(diff_paths: list[str] | None, manifest: Manifest) -> tuple[str, ...]:
    """Which changed paths are the verifier's own inputs. Pure, total, and never raises.

    EVERY hit, untruncated and sorted — see `MAX_SHOWN`. An empty diff is not a violation: nothing
    changed, so nothing reached the verifier. That is the same reading `risk.assess` gives an empty
    diff, and for the same reason — there is no silence to catch where there was no change.

    An unreadable floor returns `()` HERE and is reported by `floor_unreadable` instead. It still
    gates; it is simply not a finding about the client's change, and the caller reads both.
    """
    from openfactory.orchestrator.validation import _touches

    paths = [p for p in (diff_paths or []) if p]
    if not paths:
        return ()
    globs = effective_protected_paths(manifest)
    if globs is None:
        return ()
    return tuple(sorted(p for p in paths if any(_touches(p, g) for g in globs)))


def reason(hits: tuple[str, ...], total: int | None = None, *,
           unreadable_floor: bool = False) -> str:
    """One line for the pull request body. A gate that refuses without naming what it refused is a
    gate nobody can argue with, and every other gate in this platform names its reason.

    `total` is the true number of hits when `hits` has been truncated to `MAX_SHOWN`; leaving it
    out means `hits` is all there was.
    """
    if unreadable_floor:
        # BLAME THE RIGHT PARTY. `floor_reason` and `org_default_validation` already say this shape
        # of sentence for the same situation: nothing here is a finding about the client's code.
        return ("this deployment could not read its own protected-path floor, so nothing can be "
                "cleared to merge by itself — that is OUR install and not this repository; the "
                "job log carries `OPENFACTORY_FLOOR_UNREADABLE` and the path that would not parse")
    if not hits:
        return ""
    shown = ", ".join(f"`{p}`" for p in hits[:MAX_SHOWN])
    more = (total or len(hits)) - len(hits[:MAX_SHOWN])
    if more > 0:
        shown += f", and {more} more"
    return (f"this change edits the verifier's own inputs ({shown}) — it is human-gated by "
            f"definition, because the thing being measured cannot also move the ruler")
