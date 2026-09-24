"""What the product role can see of the map this turn — checked against the code — and what it
cannot, said out loud (ADR-0052 D20–D22, #268 slice 3).

THE CODE IS THE GROUND TRUTH (D20). Concepts are a snapshot, published every six hours and after a
merge; the code mounted for this turn is what runs. So before the role is asked anything, every
concept of every source's bundle is re-derived against the tree mounted for THAT source, with the
check the tech-lead already runs (`check_concepts`, ADR-0045's fingerprint) — and the flows that
cross services (`.okf/flows/`) source by source against the repository each source names
(`check_across`). A concept whose bytes moved is NAMED STALE in the prompt, the bound grades a
reading that cites it no higher than `média`, and the answer says so. It is never used as current.

BLIND SPOTS, SAID OUT LOUD (D21). An answer that does not say where it is thin gives confidence
exactly where it is not due. The prompt carries, bounded and with the cut counted:

    a source with no knowledge bundle, or whose code could not be mounted
    a source's code that no concept describes — from its bundle's own inventory and coverage
    the gaps a bundle records itself (`okf.yaml`)
    what the system map could not derive (`.okf/system/system.yaml`, `not_derived`)
    every concept found stale this turn

THE GAP SIGNAL (D22) is judged here too: the code a turn read, mapped back to the source it lies in,
and judged by the knowledge gate's own ladder (`gate.judge`) — only a file of a kind nothing
excuses that nothing describes is `no-concept`. Raising the request is the module's
(`knowledge/requests.py`); nothing here writes anywhere.

ONLY WHAT `sources:` DECLARES, ONLY INSIDE WHAT WAS MOUNTED. Every bundle is found for a declared
source (`sources.bundle_home`), every check reads inside the tree mounted for the repository the
concept names (`check._check_source` refuses a path that leaves it), and a path the turn read is
mapped to a source only when it resolves inside that source's mount.

PURE READING, NEVER RAISING. It runs in the orchestrator's process, on the absolute paths the
module holds; the prompt is handed text, never a path to test.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("openfactory.product")

#: The blind-spot section's bound: lines, and characters over all of them. Past it, the cut is
#: counted on the last line and every file behind it is named — never a silence.
MAX_LINES = 14
MAX_CHARS = 2600
#: How many paths a line names before it counts the rest.
NAMED = 3


@dataclass(frozen=True)
class Stale:
    """A concept the turn's check found no longer matching the code mounted for it."""

    repo: str
    title: str
    verdict: str
    detail: str


@dataclass
class Sight:
    """The turn's reading of the map: every bundle checked, what is stale, what is blind."""

    #: `repo → its bundle`, `None` for a declared source with none
    bundles: dict[str, Path | None] = field(default_factory=dict)
    #: `repo → the tree mounted for it`
    mounts: dict[str, Path] = field(default_factory=dict)
    stale: list[Stale] = field(default_factory=list)
    #: the blind-spot lines, bounded; `left_out` counts what the bound dropped
    blind: list[str] = field(default_factory=list)
    left_out: int = 0
    #: the capability section's lines (`capabilities.prompt_lines`)
    capabilities: list[str] = field(default_factory=list)
    #: `slug → every link of that capability that no longer holds`
    dangling: dict[str, list[str]] = field(default_factory=dict)
    #: the flows' directory, when there is one to cite from
    flows: Path | None = None
    #: the published system map, when there is one
    system: object | None = None

    @property
    def broken_titles(self) -> frozenset[str]:
        """The titles of every concept found stale this turn, folded — what the bound reads."""
        return frozenset(s.title.strip().lower() for s in self.stale)


def read_system(docs_root: Path | None):
    """The published system map (`.okf/system/system.yaml`) as a `SystemMap`, or None."""
    import yaml

    from openfactory.knowledge.okf import OKF_DIRNAME
    from openfactory.knowledge.system.contracts import SystemMap
    from openfactory.knowledge.system.render import SYSTEM_DIRNAME, SYSTEM_FILE
    from openfactory.knowledge.system.tree import read_text

    if docs_root is None:
        return None
    got = read_text(Path(docs_root), f"{OKF_DIRNAME}/{SYSTEM_DIRNAME}/{SYSTEM_FILE}")
    if got.text is None:
        return None
    try:
        data = yaml.safe_load(got.text)
        return SystemMap(**data) if isinstance(data, dict) else None
    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
        log.warning("the system map at %s could not be read — it is treated as absent", docs_root)
        return None


def bundles_of(docs_root: Path, repos: Iterable[str]) -> dict[str, Path | None]:
    """Every declared source's bundle in the context repository — the folder `bundle_home` finds,
    when it holds concepts' front door — and None for one that has none."""
    from openfactory.knowledge.okf import OKF_INDEX_FILE
    from openfactory.product.sources import bundle_home

    out: dict[str, Path | None] = {}
    for repo in repos:
        home = bundle_home(docs_root, repo)
        out[repo] = home if home is not None and (home / OKF_INDEX_FILE).is_file() else None
    return out


def look(*, docs_root: Path | None, root: Path | None, mounts, docs_rel: str = "docs") -> Sight:
    """The turn's sight. `docs_root` is the context repository in the turn's view, `root` the
    view the role stands in, `mounts` the module's `sources.Mount`s (None: nothing is known of the
    sources, and nothing is checked), `docs_rel` where the documentation is relative to `root`."""
    from openfactory.knowledge.check import check_across, check_concepts
    from openfactory.knowledge.flows import FLOWS_DIRNAME, read_flows
    from openfactory.knowledge.okf import OKF_DIRNAME, OKF_INDEX_FILE
    from openfactory.product import capabilities as caps
    from openfactory.product.sources import declared

    sight = Sight()
    if docs_root is None or root is None:
        return sight
    repos = declared(docs_root).repos
    sight.bundles = bundles_of(docs_root, repos)
    sight.mounts = {m.repo: Path(root) / m.path for m in (mounts or []) if m.path}
    missing = {m.repo: m.why for m in (mounts or []) if not m.path}
    for repo, bundle in sight.bundles.items():
        tree = sight.mounts.get(repo)
        if bundle is None or tree is None:
            continue
        report = check_concepts(bundle, tree)
        for c in report.broken:
            bad = next((s for s in c.sources if s.verdict == c.verdict), None)
            sight.stale.append(Stale(repo, c.title, c.verdict,
                                     f"`{bad.path}` — {bad.detail}" if bad else ""))
    flows_dir = Path(docs_root) / OKF_DIRNAME / FLOWS_DIRNAME
    flows = read_flows(flows_dir) if (flows_dir / OKF_INDEX_FILE).is_file() else None
    if flows is not None:
        sight.flows = flows_dir
        for c in check_across(flows_dir, sight.mounts).broken:
            bad = next((s for s in c.sources if s.verdict == c.verdict), None)
            sight.stale.append(Stale("", c.title, c.verdict,
                                     f"`{bad.path}` — {bad.detail}" if bad else ""))
    sight.system = read_system(docs_root)
    found, findings = caps.load_capabilities(docs_root)
    for finding in findings:
        log.warning("OPENFACTORY_PRODUCT_CAPABILITY_FINDING slug=%s code=%s — %s", finding.slug,
                    finding.code, finding.message)
    for cap in found:
        broken = caps.dangling(cap, bundles=sight.bundles, system=sight.system, flows=flows)
        if broken:
            sight.dangling[cap.slug] = broken
            log.warning("OPENFACTORY_PRODUCT_CAPABILITY_DANGLING slug=%s links=%d — %s", cap.slug,
                        len(broken), "; ".join(broken)[:400])
    sight.capabilities = caps.prompt_lines(found, flows, docs=docs_rel, broken=sight.dangling)
    lines = _blind(sight, repos, missing, docs_rel=docs_rel)
    sight.blind, sight.left_out = _bounded(lines)
    return sight


def _blind(sight: Sight, repos: list[str], missing: dict[str, str], *, docs_rel: str) -> list[str]:
    """Every blind spot, in the order a reader needs them: what could not be seen at all, what is
    stale, what no concept covers, what the bundles and the map say they could not establish."""
    from openfactory.knowledge.contracts import ANSWERED

    out: list[str] = []
    for repo in repos:
        if repo in missing:
            out.append(f"`{repo}`: its code could not be opened this turn ({missing[repo]}) — "
                       f"nothing about what it does can be checked")
    for s in sight.stale:
        where = f"`{s.repo}` — " if s.repo else "the flow "
        out.append(f"{where}'{s.title}' is STALE: it no longer matches the code mounted this turn "
                   f"({s.verdict}: {s.detail}) — read it as history, never as what the code does "
                   f"today, and open the code")
    for repo in repos:
        bundle = sight.bundles.get(repo)
        if bundle is None:
            out.append(f"`{repo}` has no knowledge bundle yet — what you say about it comes from "
                       f"reading its code now: say so, and at best medium confidence")
            continue
        uncovered, total = _uncovered(bundle)
        if uncovered:
            shown = ", ".join(f"`{p}`" for p in uncovered[:NAMED])
            more = f" and {len(uncovered) - NAMED} more" if len(uncovered) > NAMED else ""
            out.append(f"`{repo}`: {len(uncovered)} of its {total} file(s) that need a concept "
                       f"have none ({shown}{more}) — an answer resting on them rests on code "
                       f"read now, medium confidence at best")
        from openfactory.knowledge.okf import read_manifest

        manifest = read_manifest(bundle)
        open_gaps = [g for g in (manifest.gaps if manifest else []) if g.status != ANSWERED]
        if open_gaps:
            kinds = sorted({g.kind for g in open_gaps})
            rel = bundle.name
            out.append(f"`{repo}`: its bundle records {len(open_gaps)} thing(s) it could not "
                       f"establish ({', '.join(kinds)}) — `{docs_rel}/.okf/repos/{rel}/index.md` "
                       f"lists them first")
    system = sight.system
    if system is not None and system.not_derived:
        by_kind: dict[str, int] = {}
        for n in system.not_derived:
            by_kind[n.kind] = by_kind.get(n.kind, 0) + 1
        said = ", ".join(f"{k} {v}" for k, v in sorted(by_kind.items()))
        first = "; ".join(n.detail for n in system.not_derived[:2])
        out.append(f"the system map could not derive {len(system.not_derived)} thing(s) ({said}) "
                   f"— e.g. {first} — `{docs_rel}/.okf/system/index.md` lists every one; never "
                   f"conclude a part of the system is absent because the map does not show it")
    return out


def _uncovered(bundle: Path) -> tuple[list[str], int]:
    """The files of the bundle's inventory that are owed a concept and cited by none, and how many
    are owed one at all — from the bundle's own tables: a kind the coverage excuses owes nothing."""
    from openfactory.knowledge.inventory import WHY_NOT, read_inventory
    from openfactory.knowledge.okf import read_concepts, read_manifest

    inventory = read_inventory(bundle)
    if inventory is None:
        return [], 0
    manifest = read_manifest(bundle)
    excused = {row.kind for row in (manifest.coverage if manifest else []) if row.excused}
    if not excused:
        excused = {kind for kind, (_reason, ok) in WHY_NOT.items() if ok}
    cited = {s.path for c in read_concepts(bundle) for s in c.sources}
    owed = [r.path for r in inventory.files if r.kind not in excused]
    return sorted(p for p in owed if p not in cited), len(owed)


def _bounded(lines: list[str]) -> tuple[list[str], int]:
    out: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        if len(out) >= MAX_LINES or used + len(line) > MAX_CHARS:
            return out, len(lines) - i
        out.append(line)
        used += len(line)
    return out, 0


# ── the code a turn read, and what no concept covers ──────────────────────────────────────────────

def where_read(paths: Iterable[str], *, root: Path | None, mounts: dict[str, Path]
               ) -> list[tuple[str, str]]:
    """`(repo, path inside it)` for every path the turn read that lies in a mounted source — as
    the role writes it (`src/<repo>/…` from where it stands) or as a harness reports it (absolute,
    in the view) — once each. A path outside every mount, or that is not a regular file in it, is
    dropped: it is not a source's code."""
    import os

    if root is None or not mounts:
        return []
    base = Path(root).resolve()
    bases = {os.path.normpath(str(root)), str(base)}
    trees = {repo: Path(tree).resolve() for repo, tree in mounts.items()}
    out: list[tuple[str, str]] = []
    for raw in paths:
        text = str(raw or "").strip().strip("`")
        text = text.rsplit(":", 1)[0] if _has_line(text) else text
        if not text:
            continue
        candidate = Path(text) if Path(text).is_absolute() else base / text
        # NOT EVEN RESOLVED when it names a place outside the view: nothing outside `sources:`
        # is looked at, a link's target included
        lexical = os.path.normpath(str(candidate))
        if not any(lexical.startswith(b.rstrip(os.sep) + os.sep) for b in bases):
            continue
        try:
            real = candidate.resolve()
        except (OSError, RuntimeError):
            continue
        for repo, tree in trees.items():
            if tree in real.parents and real.is_file():
                hit = (repo, real.relative_to(tree).as_posix())
                if hit not in out:
                    out.append(hit)
                break
    return out


def _has_line(text: str) -> bool:
    head, _, tail = text.rpartition(":")
    return bool(head) and bool(tail) and tail.replace("-", "").isdigit()


def uncovered(read: list[tuple[str, str]], sight: Sight) -> list[tuple[str, str]]:
    """Of the code a turn read, what no concept covers — judged by the knowledge gate's own ladder
    against the bundle of the source it lies in and the tree mounted for it: `no-concept` only,
    never a file its kind excuses, a file the inventory never saw, or a source with no bundle (that
    is a backfill owed, said in the blind spots, not a file to describe)."""
    from openfactory.knowledge.gate import NO_CONCEPT, judge

    out: list[tuple[str, str]] = []
    by_repo: dict[str, list[str]] = {}
    for repo, path in read:
        by_repo.setdefault(repo, []).append(path)
    for repo, paths in by_repo.items():
        bundle, tree = sight.bundles.get(repo), sight.mounts.get(repo)
        if bundle is None or tree is None:
            continue
        try:
            report = judge(bundle, tree, paths)
        except Exception as exc:  # noqa: BLE001 — a judgement is a measurement, never the answer
            log.warning("could not judge what the turn read in %s (%s)", repo, exc)
            continue
        out += [(repo, f.path) for f in report.files if f.verdict == NO_CONCEPT]
    return out


__all__ = ["MAX_CHARS", "MAX_LINES", "Sight", "Stale", "bundles_of", "look", "read_system",
           "uncovered", "where_read"]
