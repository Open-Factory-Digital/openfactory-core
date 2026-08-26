"""The directory this platform claims inside a CLIENT's repository, and the branches it mints there.

The product is OpenFactory and the folder it writes into a client's repository is `.openfactory/`
(the product owner, 2026-08-07: everything lives under `.openfactory`). The folder used to carry an
acronym, and for a while this module was a MIGRATION: readers answered to both names, writers
emitted only the new one. That code left on 2026-08-25, with the decision that the public
repository has no old installation to migrate — the one deployment that ran under the former name
renamed its own files.

WHAT REMAINS OF THE OLD NAME IS A REFUSAL, NOT A READ. A repository that still carries the retired
directory and nothing under the new one is refused BY NAME, with the sentence saying what to rename.
The alternative — a reader that simply does not look there — would report "no manifest" to a
repository that plainly has one, and the person reading that would go looking for a typo in a file
the platform never opened. That is the absence-read-as-compliance class, and a rename is exactly
where it breeds.

AN EXPLICIT PATH IS NEVER OVERRIDDEN. `Project.manifest_path` exists so a client can put the file
where their conventions say; the refusal below applies only to OUR default location, because the
retired name has a twin only there.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("openfactory.namespace")

#: The directory this platform claims inside a client's repository.
DIR = ".openfactory"

#: The prefix of every branch this platform mints in a client's repository — the job branches
#: (`openfactory/<ticket>`), the onboarding proposal, the environment rehearsal, the box proof.
#: The most visible name the product has: it is born in EVERY pull request on the client's own
#: repository, which is why it carries the product's name and not an acronym the client never
#: chose (#106 item 5).
BRANCH_PREFIX = "openfactory"


def job_branch(ticket_id: str) -> str:
    """The branch a job for `ticket_id` works on — the one name every job is known by.

    Recalculated from the ticket id on every entry, so a repair or a resume finds the branch the
    open pull request tracks without anybody storing it."""
    return f"{BRANCH_PREFIX}/{str(ticket_id).lstrip('#')}"


#: The two files that live in it, as the defaults every caller starts from.
MANIFEST = f"{DIR}/project.yaml"
PRODUCT_MANIFEST = f"{DIR}/product.yaml"

#: The directory's RETIRED name. Named here, once, for one purpose: to refuse a repository still
#: on it with a sentence, instead of reporting "no manifest" to somebody looking at one. Nothing
#: reads under it; the guard in `tests/test_the_namespace_is_the_products_name.py` holds this to
#: be the only module that spells it.
RETIRED_DIR = ".sdlc"


class RetiredNamespace(FileNotFoundError):
    """A repository still on the retired directory name, and nothing under the current one.

    A `FileNotFoundError` on purpose: to every caller that already handles a missing manifest, this
    IS a missing manifest — the only difference is that the sentence says what to rename, which is
    the difference between a client fixing it in a minute and hunting a typo in a file the platform
    never opened."""


def _retired_twin(relative: str) -> str:
    """The same path under the retired directory name, or `""` when it is not one of ours."""
    # `removeprefix("./")`, NOT `lstrip("./")`. `lstrip` takes a SET of characters and eats every
    # leading `.` or `/` there is — `.openfactory/project.yaml` became `openfactory/…`, matched
    # nothing, and every project fell through to "no manifest" (34 tests red, the day the rename
    # landed). Kept as a comment because the two names still differ by a leading dot.
    rel = str(relative).replace("\\", "/").removeprefix("./")
    if rel == DIR or rel.startswith(f"{DIR}/"):
        return RETIRED_DIR + rel[len(DIR):]
    return ""


def resolve(root: Path, relative: str, *, project: str = "") -> Path:
    """The path to read — and a refusal, by name, when only the retired twin is there.

    Returns `root / relative` whether or not it exists: "missing" is then reported in the name we
    use, and a client reading the error is told what to create. The one thing this never does is
    answer with the retired path or pretend it did not see it.
    """
    new = root / relative
    if new.exists():
        return new
    old_rel = _retired_twin(relative)
    if old_rel and (root / old_rel).exists():
        raise RetiredNamespace(
            f"project {project or root.name!r} has no manifest at {new} — it has one at "
            f"`{old_rel}`, which is this platform's former name and is not read. Rename the "
            f"directory `{RETIRED_DIR}/` to `{DIR}/` in that repository; nothing under "
            f"`{RETIRED_DIR}/` is read.")
    return new


def operator_path(filename: str) -> Path:
    """The operator's file under `~/.openfactory/` — the registry, the approver store, the resume
    handles.

    Called from the composition points that resolve these paths (`ProjectRegistry.__init__`,
    `approvals.store_path`), never at import — the house has paid for import-time side effects
    before. An explicit override (env var, argument) bypasses this entirely: an explicit path is
    never second-guessed."""
    return Path.home() / DIR / filename


#: Where a process leaves the build it runs from, for the OTHER halves of the deployment to read
#: (#135). One file per ROLE — `build-worker.json`, `build-panel.json`.
#:
#: HALF A STACK CAN BE STALE AND NOTHING SAYS SO. `build_stamp()` answers "which code am I", and
#: every surface that prints it prints its OWN — so the worker's doctor line said one build while
#: the panel served a page from a build twenty-eight hours older, and the operator read the old
#: page reporting the old state with no way to tell (pilot, 2026-08-17: I had told him to rebuild
#: only the worker, and the fix he was looking for lived in the panel).
#:
#: PER ROLE, AND SYMMETRIC, because the stale half is whichever one you did not rebuild — naming a
#: file after the role that happened to be fresh in the first episode would bake this deployment's
#: accident into the product. Every process that serves a surface announces; every surface can name
#: the ones that disagree with it, including roles that do not exist yet.
BUILD_FILE = "build-{role}.json"


def announce_build(role: str, *, where: str = "") -> str:
    """Record THIS process's build under `role`, in the shared state directory. Returns the stamp.

    Best-effort: a deployment whose state directory is read-only still boots — it simply cannot say
    what it is running, which is where this started, so the failure is logged rather than raised."""
    import json

    stamp, built = build_stamp()
    if not stamp:
        # NOT A BUILT IMAGE — a checkout, where the code on disk IS the code running and there are
        # no separate halves to disagree. Announcing here would mean creating
        # `/var/lib/openfactory` on somebody's laptop (or logging a permission warning on every
        # boot when that fails) to record that we are nothing in particular.
        return ""
    root = _state_dir(where)
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / BUILD_FILE.format(role=role)).write_text(
            json.dumps({"stamp": stamp, "built_at": built}), encoding="utf-8")
    except OSError as exc:
        log.warning("could not record this %s's build for the rest of the deployment to read (%s) "
                    "— a stale half beside a fresh one will stay invisible", role, exc)
        return ""
    return stamp


def announced_builds(*, where: str = "") -> dict[str, tuple[str, str]]:
    """`{role: (stamp, built_at)}` for every half that has announced. Empty when none has.

    EMPTY IS NOT A DISAGREEMENT. A deployment whose other half predates this, or whose halves do
    not share a state directory, has told us nothing — and nothing is what a caller must be able to
    distinguish from "told us, and it differs"."""
    import json

    found: dict[str, tuple[str, str]] = {}
    root = _state_dir(where)
    try:
        files = sorted(root.glob(BUILD_FILE.format(role="*")))
    except OSError:
        return found
    prefix, suffix = BUILD_FILE.split("{role}")
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # a half-written file is one we have not been told about yet
        role = f.name[len(prefix):-len(suffix)] if suffix else f.name[len(prefix):]
        found[role] = (str(data.get("stamp") or ""), str(data.get("built_at") or ""))
    return found


def _state_dir(where: str = "") -> Path:
    """The directory the halves of this deployment share. Compose mounts it into both."""
    return Path(where or os.environ.get("OPENFACTORY_STATE_DIR") or "/var/lib/openfactory")


def build_disagreement(role: str, *, where: str = "") -> dict[str, tuple[str, str]]:
    """The halves whose build differs from THIS process's, `{role: (stamp, built_at)}`.

    Empty means either "everybody agrees" or "there is nothing to compare" — callers that need to
    tell those apart (the panel's banner does; it must not cry wolf) check `build_stamp()` and
    `announced_builds()` themselves."""
    mine, _ = build_stamp()
    if not mine:
        return {}
    return {r: v for r, v in announced_builds(where=where).items()
            if r != role and v[0] and v[0] != mine}


def build_stamp() -> tuple[str, str]:
    """`(code-hash, built-at)` for the image this process runs from — `("", "")` outside one.

    THE QUESTION NOBODY COULD ANSWER (2026-08-14). The compose worker BAKES the package, so
    `git pull && docker compose up -d` restarts the previous build and every command inside
    keeps answering from it — silently, indistinguishably. The pilot operator ran the same
    diagnostic three times against fixes that were on his disk and not in his worker, and
    neither he nor I could tell from the output; I had told him the rebuild was optional, which
    was wrong. A running deployment must be able to say WHICH code it is.

    Read from a file the image writes at build time (`docker/worker.Dockerfile`). Absent means
    "not a built image" — a laptop checkout, where the code on disk IS the code running — and
    that is reported as such rather than invented."""
    import json
    from pathlib import Path

    try:
        data = json.loads(Path("/etc/openfactory/build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", ""
    return str(data.get("code") or ""), str(data.get("built_at") or "")


# ── whether the halves of this deployment agree, as a REPORT ─────────────────────────────────
#
# MOVED OUT OF `api/app.py` (#144). Which code each half runs is a fact about the deployment,
# not about the web layer — the floor's ladder, the CLI and any channel need the same answer,
# and a second copy is how two surfaces come to disagree about what is even running.
def build_agreement(role: str = "panel") -> dict:
    """Which code each half of this deployment runs, and whether they agree (#135).

    A COMPOSE STACK IS TWO IMAGES, and both BAKE the package. `docker compose up -d --build worker`
    leaves the panel serving whatever it was built from — so on 2026-08-17 the pilot rebuilt,
    pressed
    F5, and read a page from an image twenty-eight hours older, reporting the older world. `docker
    ps`
    said `Up 28 hours` beside `Up 2 minutes`, and nothing on the screen he was actually looking at
    could say it. He spent the round believing a fix had not worked.

    Each process could only ever print its OWN stamp, which is why this needs the state volume both
    of them mount: the worker WRITES its build there at boot, and the panel reads it back here.

    THREE ANSWERS, and the third is not a failure:

        agree = True    both halves report the same build
        agree = False   they differ — PROVEN, and the panel says so in the loudest place it has
        agree = None    it cannot be established, and no claim is made. Either this is not a built
                        image at all (a checkout: one tree, no halves to disagree) or the worker
                        has not announced — an older worker, or a deployment whose halves do not
                        share a state directory. Silence beats a false alarm on a working stack,
                        and beats a false all-clear on a split one.
    """
    mine, mine_at = build_stamp()
    others = {r: v for r, v in announced_builds().items() if r != role and v[0]}
    if not mine or not others:
        agree: bool | None = None
    else:
        agree = all(stamp == mine for stamp, _ in others.values())
    return {
        "role": role, "stamp": mine, "built_at": mine_at, "agree": agree,
        "others": {r: {"stamp": s, "built_at": b} for r, (s, b) in sorted(others.items())},
    }
