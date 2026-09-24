"""The steps a started preview goes through, one function each — what `PreviewWorkflow`'s
activities run (ADR-0050 D6, D10; the design on #265, §5.2 and §5.5).

`materialise → plan → up`, then a `watch` every minute while it lives, and `logs → down` before it
ends — whether it ends because its time is up, because somebody stopped it, or because somebody
asked for a rebuild. Each step writes the record the panel reads (the worker writes, the panel
reads: the panel holds no docker socket), so a card always says where its preview is and, when
it is nowhere, why.

WHY THESE LIVE HERE AND NOT IN THE ACTIVITIES. An activity is the engine's unit of retry and of
timeout; what it DOES is a question about previews, and answering it with the engine out of the
room is what lets every rule below be a test with a faked runtime and a faked forge. The
activities are the thin half: a heartbeat, a timeout, the runtime built from the deployment's kind.

EVERY `up` IS PRECEDED BY A FRESH MATERIALISE, and every materialise by the unit's old stack
taken down (logs first). Two things depend on it: admission judges the trees on disk, so a tree a
container could have rewritten since is never mounted again; and a unit's volumes are named after
it, so a second start on top of the first would inherit its data — "fresh by construction" (D4) is
only true of a stack that was not there before.

NOTHING HERE RAISES PAST A STEP. A refusal is a record (`failed`, with every reason) and a return
value; a step that cannot write its record says so in the log and still answers, because a preview
the panel cannot see is a line in a log, never a stuck workflow.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from openfactory import preview
from openfactory.adapters.preview import compose
from openfactory.preview import demand
from openfactory.preview.plan import Layout, PreviewPlan, PreviewUp, Refused

log = logging.getLogger("openfactory.preview.steps")

#: What `watch` answers. `running`: the unit is up. `failed`: an exposed service stopped and the
#: record says so; the stack is kept for a person to read and the reaper ends it. `gone`: nothing
#: of the unit is on the daemon any more — somebody else ended it.
RUNNING, FAILED, GONE = "running", "failed", "gone"


class World:
    """What the steps read and write besides the runtime: the record store, the forge, the clock.
    One object so a test hands in doubles once; the defaults are the deployment's own."""

    def __init__(self, *, record: Callable[[preview.Preview], object] = preview.record,
                 latest: Callable[[str, str], preview.Preview | None] = preview.latest,
                 forge_of: Callable | None = None, clock: Callable[[], float] = time.time,
                 cap: int | None = None) -> None:
        self.record, self.latest, self.clock = record, latest, clock
        self._forge_of = forge_of
        self.cap = cap

    def forge(self, project):
        """The project's forge — the worker's own construction when the activities hand it in
        (`activities._forge_for`, the one place the worker builds a forge), else the panel's."""
        return (self._forge_of or demand._forge_of)(project)

    def was(self, project: str, token: str) -> preview.Preview | None:
        try:
            return self.latest(project, token)
        except Exception as exc:  # noqa: BLE001 — an unreadable store is a fresh record, said
            log.warning("OPENFACTORY_PREVIEW could not read the record of %s %s (%s)", project,
                        token, exc)
            return None

    def write(self, project: str, token: str, state: str, **update) -> preview.Preview:
        """The newest record of the unit, moved to `state` with `update` — everything it already
        said (its cards, its pull requests, who started it) carried over."""
        was = self.was(project, token)
        base = was or preview.Preview(project=project, unit=token, state=state,
                                      kind="requirement" if token.startswith("req") else "card",
                                      cards=() if token.startswith("req") else (token,))
        new = base.model_copy(update={"state": state, **update})
        try:
            self.record(new)
        except Exception as exc:  # noqa: BLE001 — the promise above: never past a step
            log.warning("OPENFACTORY_PREVIEW could not record %s %s as %s (%s)", project, token,
                        state, exc)
        return new


def names(project, token: str) -> tuple[str, str, str]:
    """(compose project, work directory, log directory) of one unit — derived, never read."""
    return (preview.compose_project(project.name, token),
            compose.workdir_for(project.name, token), compose.log_dir_for(project.name, token))


def clear(project, token: str, runtime) -> list[str]:
    """Whatever of the unit is still on the daemon, taken down — its logs kept first."""
    cp, workdir, log_dir = names(project, token)
    if runtime.watch(cp) is None:
        return []
    runtime.logs(cp, log_dir)
    return runtime.down(cp, workdir)


# ── 1. materialise ───────────────────────────────────────────────────────────────────────────────


def materialise(project, token: str, *, runtime, world: World, started_by: str = ""
                ) -> Layout | Refused:
    """The unit's trees on disk, fresh — base at its tip, the change at the head the forge holds
    — or every reason not. Records `starting` first, so the card says so from the first second."""
    name = project.name
    was = world.was(name, token)
    unit = demand.unit_for(name, token, was)
    now = int(world.clock())
    # A FRESH START SAYS NOTHING THE LAST ONE SAID: what it ran, what it noted, what was stale.
    world.write(name, token, preview.STARTING, started_by=started_by, started_at=now,
                kind=unit.kind, why="", ended_at=0, expires_at=0, stale=(), services={},
                health={}, from_change={}, commits={}, heads={}, images={}, base_moved={},
                notes=(), log_dir="")

    def refused(why: str) -> Refused:
        world.write(name, token, preview.FAILED, why=why, ended_at=int(world.clock()))
        return Refused(reasons=(why,))

    try:
        forge = world.forge(project)
        found, why = demand.branches_of(token, was, forge)
        if why:
            return refused(why)
        live, why = demand.open_changes(found, forge)
    except Exception as exc:  # noqa: BLE001 — a forge that cannot answer is a refusal, said
        return refused(f"the forge could not be asked about this unit's pull requests: "
                       f"{demand.redact(str(exc))[:200]}")
    if live is None:
        return refused(why)
    if not live:
        return refused("this unit has no open pull request — a preview shows a change, and there "
                       "is none to show yet.")
    if len(live) > 1:
        # ONE CHANGE TREE PER REPOSITORY. Two open pull requests of one unit in the project's
        # repository cannot both be checked out beside its base; the siblings of a requirement
        # across repositories are the multi-repository slice (the design's §6.2).
        return refused(f"{len(live)} pull requests of this unit are open "
                       f"({', '.join(sorted(live))}) in one repository — a preview of several "
                       f"changes to one repository is not assembled; merge or close all but one.")
    world.write(name, token, preview.STARTING, pr_urls=tuple(live),
                branches={**(was.branches if was else {}), **live})
    clear(project, token, runtime)
    url, branch = next(iter(live.items()))
    sources = compose.sources_of(project)
    trees = [s.model_copy(update={"branch": branch, "pr_url": url}) if i == 0 else s
             for i, s in enumerate(sources)]
    try:
        remote = forge.push_remote()
    except Exception as exc:  # noqa: BLE001 — the tokenless source is the fallback, said
        log.warning("OPENFACTORY_PREVIEW the forge named no remote to fetch %s from (%s) — "
                    "fetching from the registered source", url, demand.redact(str(exc)[:160]))
        remote = None
    layout = compose.materialise(unit, project, trees=trees,
                                 fetch={t.repo: remote for t in trees if remote})
    if isinstance(layout, Refused):
        return refused(" ".join(layout.reasons))
    return layout


# ── 2. plan ─────────────────────────────────────────────────────────────────────────────────────


def plan(project, token: str, layout: Layout, *, runtime, world: World) -> PreviewPlan | Refused:
    """The admitted plan, or every reason not — the cap and the per-unit budget among them. A
    refusal takes the fresh work directory with it: nothing ran, and nothing is kept."""
    name = project.name
    cp, workdir, _log_dir = names(project, token)
    was = world.was(name, token)
    unit = demand.unit_for(name, token, was)
    cap = world.cap if world.cap is not None else demand.max_previews()
    why = demand.over_cap(runtime.running(), mine=cp, cap=cap)
    if why:
        planned: PreviewPlan | Refused = Refused(reasons=(why,))
    else:
        planned = compose.plan(layout, unit, project, now=world.clock())
    if isinstance(planned, Refused):
        world.write(name, token, preview.FAILED, why=" ".join(planned.reasons),
                    notes=tuple(planned.notes), ended_at=int(world.clock()))
        runtime.down(cp, layout.workdir or workdir)
    return planned


# ── 3. up ───────────────────────────────────────────────────────────────────────────────────────


def _base_moved(layout: Layout) -> dict[str, str]:
    return {t.repo: f"branched from {t.merge_base[:7]}, now {t.base_commit[:7]}"
            for t in layout.trees.values()
            if t.has_change and t.merge_base and t.base_commit and t.merge_base != t.base_commit}


def up(project, token: str, planned: PreviewPlan, *, runtime, world: World) -> PreviewUp:
    """Bring the plan up; `live` with everything a card says about it, or `failed` with why. A
    failed stack is KEPT for a person to read (the reaper takes it down after the operator's
    `keep_failed_minutes`) — unless nothing of it reached the daemon, when there is nothing to
    read but the build log, which is already kept."""
    name = project.name
    result = runtime.up(planned)
    if result.ok:
        said = dict(
            services=dict(result.services), health=dict(result.health),
            from_change=dict(planned.from_change), commits=dict(planned.commits),
            heads={t.pr_url: t.change_commit for t in planned.layout.trees.values()
                   if t.has_change and t.pr_url},
            images=dict(result.images), base_moved=_base_moved(planned.layout),
            notes=tuple(dict.fromkeys([*planned.notes, *result.notes])), log_dir=result.log_dir,
            expires_at=int(planned.expires_at), why="", stale=())
        if planned.pr_urls:
            said["pr_urls"] = tuple(planned.pr_urls)
        world.write(name, token, preview.LIVE, **said)
        return result
    world.write(name, token, preview.FAILED, why=result.why, log_dir=result.log_dir,
                notes=tuple(planned.notes), ended_at=int(world.clock()))
    if runtime.watch(planned.compose_project) is None:
        runtime.down(planned.compose_project, planned.workdir)
    return result


# ── 4. watch ────────────────────────────────────────────────────────────────────────────────────


def _tails(log_dir: str, services, n: int = 5) -> str:
    out = []
    for svc in services:
        path = os.path.join(log_dir, f"{svc}.log")
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = [ln.rstrip() for ln in fh.read().splitlines() if ln.strip()]
        except OSError:
            continue
        if lines:
            out.append(f"{svc}:\n" + "\n".join(lines[-n:]))
    return "\n".join(out)


def watch(project, token: str, *, runtime, world: World) -> str:
    """One look at a live unit. An exposed service that stopped makes the record `failed` with
    the last lines of the exposed services' logs; nothing on the daemon means somebody else ended
    it."""
    name = project.name
    cp, _workdir, log_dir = names(project, token)
    seen = runtime.watch(cp)
    was = world.was(name, token)
    if seen is None:
        if was is not None and was.state == preview.LIVE:
            world.write(name, token, preview.ENDED, why="it is no longer on the daemon",
                        ended_at=int(world.clock()))
        return GONE
    if seen.state == "running":
        return RUNNING
    runtime.logs(cp, log_dir)
    tail = _tails(log_dir, (was.ordered() if was else ()))
    world.write(name, token, preview.FAILED, log_dir=log_dir, ended_at=int(world.clock()),
                why="an exposed service stopped — its log is kept until the preview is taken "
                    "down" + (f":\n{tail}" if tail else "."))
    return FAILED


# ── 5. logs, then down ─────────────────────────────────────────────────────────────────────────


def logs(project, token: str, *, runtime) -> list[str]:
    """Every service's log, kept — BEFORE any down, always: a stack taken down first leaves
    nobody able to say why it failed."""
    cp, _workdir, log_dir = names(project, token)
    return runtime.logs(cp, log_dir)


def down(project, token: str, *, runtime, world: World, why: str, record: bool = True
         ) -> list[str]:
    """Take the unit down and, unless it is about to start again (a rebuild), record it `ended`
    with why — never over a record somebody else already ended."""
    cp, workdir, log_dir = names(project, token)
    removed = runtime.down(cp, workdir)
    if record:
        was = world.was(project.name, token)
        if was is None or was.state != preview.ENDED:
            world.write(project.name, token, preview.ENDED, why=why, log_dir=log_dir,
                        ended_at=int(world.clock()))
    return removed
