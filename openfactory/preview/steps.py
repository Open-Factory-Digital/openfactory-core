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
from openfactory.preview import demand, siblings
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
                 cap: int | None = None, product_of: Callable | None = None,
                 board_of: Callable | None = None, source_of: Callable | None = None) -> None:
        self.record, self.latest, self.clock = record, latest, clock
        self._forge_of = forge_of
        self.cap = cap
        #: the project's product context (`demand.product_context`) — its board and its
        #: `sources:` are what a requirement's siblings are found in and bounded by
        self.product = product_of or demand.product_context
        #: `(tickets, error)` of the product's board (`product/board.py::read_board`)
        self.board = board_of or _read_board
        #: `(project, repository, directory) -> TreeSource` for a member that is not the
        #: project's own repository (`compose.source_for`)
        self.source = source_of or (lambda project, repo, dir: compose.source_for(project, repo,
                                                                                  dir=dir))

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


def _read_board(project):
    from openfactory.product.board import read_board

    return read_board(project)


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


def _own(project, repo: str) -> bool:
    """Whether `repo` is the project's own repository — a change the job path left unqualified
    (`""`) is, by C-18's rule."""
    from openfactory.adapters.forge.registry import repo_of
    from openfactory.product.config import repo_match

    own = repo_of(project) or ""
    return not repo or not own or repo == own or bool(repo_match(repo, own))


def _changes(project, token: str, was, forge, *, ctx, world: World) -> siblings.Changes:
    """The unit's open pull requests and what is missing from it. A requirement's are its
    siblings on the product's board, bounded by `sources:` (§6.2) — or, when the board or the
    product cannot be read, the cards that offered themselves, and the card says so."""
    from openfactory.adapters.forge.registry import repo_of

    default = repo_of(project) or ""
    if not token.startswith("req"):
        return siblings.of_record(token, was, forge, default_repo=default)
    number = int(token[3:])
    docs = getattr(ctx, "docs", None)
    if getattr(ctx, "available", False) and docs is not None:
        tickets, error = world.board(project)
        if not error:
            return siblings.of_requirement(number, tickets, sources=docs.sources,
                                           default_repo=default, forge=forge)
        said = f"the board could not be read ({error})"
    else:
        said = f"the product module is off — {getattr(ctx, 'reason', '') or 'it is not enabled'}"
    found = siblings.of_record(token, was, forge, default_repo=default)
    return found.model_copy(update={"missing": (
        f"{said}: REQ-{number:04d} is previewed with the cards that reached their pull request "
        f"here, and any other card of it is not in this preview.", *found.missing)})


def _shape(ctx, project):
    """The product's preview shape when the product module is on and `product.yaml` declares one;
    None for a project previewed from its own repository's `preview:`; `Refused` when the product
    declares a shape that cannot be used."""
    from openfactory.preview.product import shape_of

    docs = getattr(ctx, "docs", None)
    if not getattr(ctx, "available", False) or docs is None:
        return None
    context = str(getattr(getattr(project, "product", None), "docs_repo", "") or
                  getattr(getattr(ctx, "link", None), "docs_repo", ""))
    return shape_of(docs, context=context)


def _bounded(project, changes, shape) -> tuple[list, list[str]]:
    """The changes a preview may hold, and a sentence for each it may not: a PRODUCT's must be in
    one of its members; a single repository's in that repository. A card of another product is
    never joined — its pull request is not even fetched."""
    kept, out = [], []
    for c in changes:
        ref = c.card or c.url
        if shape is not None and not shape.dir_of(c.repo):
            out.append(f"{ref}'s change is in `{c.repo}`, which is not a repository of this "
                       f"product — not included.")
        elif shape is None and not _own(project, c.repo):
            out.append(f"{ref}'s change is in `{c.repo}`, and this preview is of "
                       f"`{project.name}`'s own repository — not included.")
        else:
            kept.append(c)
    return kept, out


def materialise(project, token: str, *, runtime, world: World, started_by: str = ""
                ) -> Layout | Refused:
    """The unit's trees on disk, fresh — base at its tip, the change at the head the forge holds
    — or every reason not. Records `starting` first, so the card says so from the first second.

    A requirement's trees are EVERY repository its layout needs, side by side (§6.3): each
    sibling's pull request in `change/` of its own repository, every other repository the product's
    compose file reaches at its base — and `missing` says, card by card, what is not in it."""
    name = project.name
    was = world.was(name, token)
    unit = demand.unit_for(name, token, was)
    now = int(world.clock())
    alone = (was.alone,) if was is not None and was.alone else ()
    # A FRESH START SAYS NOTHING THE LAST ONE SAID: what it ran, what it noted, what was stale.
    world.write(name, token, preview.STARTING, started_by=started_by, started_at=now,
                kind=unit.kind, why="", ended_at=0, expires_at=0, stale=(), services={},
                health={}, from_change={}, commits={}, heads={}, images={}, base_moved={},
                missing=alone,
                notes=(), log_dir="")

    def refused(why: str, missing: tuple[str, ...] = ()) -> Refused:
        world.write(name, token, preview.FAILED, why=why, ended_at=int(world.clock()),
                    **({"missing": missing} if missing else {}))
        return Refused(reasons=(why,))

    try:
        forge = world.forge(project)
        ctx = world.product(project)
        found = _changes(project, token, was, forge, ctx=ctx, world=world)
    except Exception as exc:  # noqa: BLE001 — a forge that cannot answer is a refusal, said
        return refused(f"the forge could not be asked about this unit's pull requests: "
                       f"{demand.redact(str(exc))[:200]}")
    if found.why or found.open is None:
        return refused(found.why or "the forge could not be asked about this unit's pull "
                                    "requests.", (*alone, *found.missing))
    shape = _shape(ctx, project)
    if isinstance(shape, Refused):
        return refused(" ".join(shape.reasons), (*alone, *found.missing))
    live, out = _bounded(project, found.open, shape)
    missing = (*alone, *found.missing, *out)
    if not live:
        return refused("this unit has no open pull request — a preview shows a change, and there "
                       "is none to show yet.", missing)
    per_repo: dict[str, list[str]] = {}
    for c in live:
        per_repo.setdefault(shape.dir_of(c.repo) if shape else "", []).append(c.url)
    for urls in per_repo.values():
        if len(urls) > 1:
            # ONE CHANGE TREE PER REPOSITORY. Two open pull requests of one unit in one repository
            # cannot both be checked out beside its base; across repositories they are siblings,
            # each in its own tree (§6.3).
            return refused(f"{len(urls)} pull requests of this unit are open "
                           f"({', '.join(sorted(urls))}) in one repository — a preview of several "
                           f"changes to one repository is not assembled; merge or close all but "
                           f"one.", missing)
    world.write(name, token, preview.STARTING, pr_urls=tuple(c.url for c in live),
                branches={**(was.branches if was else {}), **{c.url: c.branch for c in live}},
                repos={**(was.repos if was else {}), **{c.url: c.repo for c in live}},
                missing=missing)
    clear(project, token, runtime)
    if shape is None:
        layout = _single(project, unit, live[0], forge)
    else:
        layout = _product(project, unit, live, forge, shape=shape, ctx=ctx, world=world)
    if isinstance(layout, Refused):
        return refused(" ".join(layout.reasons))
    return layout


def _remote(forge, project, repo: str, url: str) -> str | None:
    """The URL a change's branch is fetched from — an argument of git, never stored — or None, and
    the tokenless registered source is the fallback, said."""
    try:
        if _own(project, repo):
            return forge.push_remote()
        return demand.remote_for(project, forge, repo) or None
    except Exception as exc:  # noqa: BLE001 — the tokenless source is the fallback, said
        log.warning("OPENFACTORY_PREVIEW the forge named no remote to fetch %s from (%s) — "
                    "fetching from the registered source", url, demand.redact(str(exc)[:160]))
        return None


def _single(project, unit, change, forge) -> Layout | Refused:
    """One repository — the project's own — at its base, with the change beside it."""
    url, branch = change.url, change.branch
    sources = compose.sources_of(project)
    trees = [s.model_copy(update={"branch": branch, "pr_url": url}) if i == 0 else s
             for i, s in enumerate(sources)]
    remote = _remote(forge, project, "", url)
    return compose.materialise(unit, project, trees=trees,
                               fetch={t.repo: remote for t in trees if remote})


def _product(project, unit, live, forge, *, shape, ctx, world: World) -> Layout | Refused:
    """A product's layout: the context repository, the project's own repository (whose manifest
    could declare a second shape), the repository the compose file lives in and every repository
    with a change — then whatever the compose file reaches, and nothing it does not."""
    from openfactory.adapters.forge.registry import repo_of
    from openfactory.preview.product import reached

    changes = {shape.dir_of(c.repo): c for c in live}

    def source(d: str):
        repo = shape.members[d]
        if d == shape.context_dir:
            cfg = getattr(project, "product", None)
            s = compose.TreeSource(repo=repo, dir=d, source=str(getattr(ctx, "docs_path", "")),
                                   base_branch=str(getattr(cfg, "declared_docs_branch", "") or ""))
        elif _own(project, repo):
            s = compose.sources_of(project)[0]
        else:
            s = world.source(project, repo, d)
        # EVERY TREE UNDER THE MEMBER'S OWN SPELLING AND DIRECTORY: what the plan re-judges, and
        # what `fetch` is keyed by — whatever spelling the registry or a checkout used for it
        c = changes.get(d)
        return s.model_copy(update={"repo": repo, "dir": d,
                                    **({"branch": c.branch, "pr_url": c.url} if c else {})})

    own = shape.dir_of(repo_of(project) or "")
    first = list(dict.fromkeys(d for d in (shape.context_dir, own, shape.shape_dir, *changes)
                               if d))
    fetch = {shape.members[d]: r for d, c in changes.items()
             if (r := _remote(forge, project, c.repo, c.url))}

    def sources(dirs) -> list | Refused:
        # A member that cannot be fetched is a refusal said on the card, never a step that dies
        try:
            return [source(d) for d in dirs]
        except Exception as exc:  # noqa: BLE001 — the reason is the finding
            return Refused(reasons=(f"a repository of the product could not be fetched to check "
                                    f"out: {demand.redact(str(exc))[:200]}",))

    def more(layout: Layout):
        dirs = reached(shape, layout.root(shape.shape_dir, "base"))
        if isinstance(dirs, Refused):
            return dirs
        return sources(d for d in dirs if d not in layout.trees)

    trees = sources(first)
    if isinstance(trees, Refused):
        return trees
    return compose.materialise(unit, project, trees=trees, fetch=fetch,
                               more=more, context=shape.context_dir)


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
