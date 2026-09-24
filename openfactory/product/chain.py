"""The traceability chain: request → requirement → ticket → pull request → release, crossed with
concept ↔ component ↔ code (ADR-0052 D23, #268 slice 3).

EACH LINK ALREADY EXISTS SOMEWHERE, AND AN OWNER ANSWERS BY WALKING THEM. A requirement's number
is on the card that executes it (its `## Source` — the one line an executor is told not to go
beyond, `module._cited_requirement`); a card's jobs carry their pull request, their end and the
deploy watch's word; each member's newest release tag is what the production approval calls the
version in production. That is the first chain, and #267's read model holds every link of it
(`product/model.py`: requirements with who asked, the whole board with each card's body, the
finished jobs, the release). The system map holds the second (`knowledge/system/`): which
component a repository's code runs as and what calls it; the bundles and the flows hold which
concept describes which code, and which flow crosses which services. Held as ONE chain, "is
requirement 17 in production, and in which version?" is a lookup rather than a search across four
tools — and so are the other two questions the issue names:

    is REQ-N in production, and in which version?      `Chain.requirement`
    what code serves capability X?                       `Chain.serving`
    if the freight calculation changes, what is touched? `Chain.touched_by`

A VERDICT IS ONLY AS STRONG AS ITS LINK, AND SAYS WHICH LINK IT IS. "In production" is said for a
job that ended `done` — the factory's own lifecycle, which ends there after the production release
was verified — or one merged that the deploy watch saw deployed; "merged" is not "in production",
and a card closed as completed is the board's word, not a release. The version is named only when
the record names it: a client-approved release is tagged `release.version_for(card)`, and when the
newest tag is that one it is said; otherwise the newest tag is said AS the newest tag, never as
this requirement's.

WHAT IT NEVER SAYS: who. The model keeps who asked; the chain says "its requester" or nothing, as
every file of the facts pack does (`model.finish`). A link that could not be read is said as
unread — the pack's rule, kept verbatim.

PURE TEXT OVER WHAT THE TURN ALREADY READ: the model the facts pack was written from, and the
module's `sight` (the bundles, the system map, the flows, the capabilities). It reads nothing
else and never raises for well-formed inputs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

#: How a requirement stands, strongest first — each names the link it rests on.
IN_PRODUCTION = "in production"
MERGED = "merged, not seen in production"
BUILDING = "being built"
ON_THE_BOARD = "on the board, not built"
NO_CARD = "no card executes it"
UNREAD = "unknown — the board or the jobs could not be read"

#: How many requirements, and parts, the file walks before it counts the rest.
LIMIT = 200


@dataclass
class Step:
    """One card executing a requirement, and what became of its work."""

    member: str
    ref: str
    title: str
    state: str
    reason: str
    jobs: list[dict] = field(default_factory=list)
    release: str | None = None


@dataclass
class Trace:
    """One requirement, walked: its cards, its jobs, its verdict — and what carries it."""

    number: int
    title: str
    status: str
    verdict: str
    because: str
    version: str = ""
    steps: list[Step] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    flows: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    code: list[str] = field(default_factory=list)


@dataclass
class Chain:
    """The two chains, joined for one turn."""

    model: object | None
    sight: object | None
    declared: list[str] = field(default_factory=list)
    capabilities: list = field(default_factory=list)

    # ── request → requirement → ticket → pull request → release ────────────────────────────

    def requirement(self, number: int) -> Trace | None:
        """REQ-`number`, walked to production — None when the model holds no such requirement."""
        reqs = getattr(self.model, "requirements", None) or []
        req = next((r for r in reqs if int(r.get("number") or 0) == int(number)), None)
        if req is None:
            return None
        steps = self._steps(int(number))
        verdict, because, version = self._verdict(steps)
        trace = Trace(number=int(number), title=str(req.get("title") or ""),
                      status=str(req.get("status") or ""), verdict=verdict, because=because,
                      version=version, steps=steps)
        from openfactory.knowledge.flows import affected

        trace.sources = affected(_Req(req), self.declared)
        system = getattr(self.sight, "system", None)
        trace.components = sorted(c.name for c in (system.components if system else [])
                                  if c.repo and c.repo in trace.sources)
        for flow in self._flows():
            if int(number) in flow.requirements:
                trace.flows.append(flow.slug)
                trace.code += [c for c in self._code_of(flow.concepts) if c not in trace.code]
        trace.capabilities = [c.slug for c in self.capabilities
                              if int(number) in c.requirements]
        return trace

    def _steps(self, number: int) -> list[Step]:
        from openfactory.product.module import _cited_requirement

        out: list[Step] = []
        for member in getattr(self.model, "members", None) or []:
            history = (self.model.history.get(member) or {})
            cards = ((self.model.meaning.get(member) or {}).get("cards") or {})
            finished = history.get("finished")
            live = (self.model.now.get(member) or {}).get("jobs")
            release = history.get("release")
            for card in cards.values():
                if _cited_requirement(card.get("body") or "") != number:
                    continue
                jobs = [j for j in [*(live or []), *(finished or [])]
                        if str(j.get("issue") or "") == str(card.get("ref"))]
                out.append(Step(member=member, ref=str(card.get("ref")),
                                title=str(card.get("title") or ""),
                                state=str(card.get("state") or ""),
                                reason=str(card.get("state_reason") or ""), jobs=jobs,
                                release=(None if release is None
                                         else str(release.get("latest_tag") or ""))))
        return out

    def _verdict(self, steps: list[Step]) -> tuple[str, str, str]:
        from openfactory.product.release import version_for

        if self.model is None:
            return UNREAD, "the product's read model was not built for this message", ""
        if not steps:
            unread = [g for g in getattr(self.model, "gaps", []) or []
                      if "board could not be read" in g]
            if unread:
                return UNREAD, "; ".join(unread[:2]), ""
            return NO_CARD, "no card on the board cites it in its `## Source`", ""
        best: tuple[int, str, str, str] | None = None
        for step in steps:
            for job in step.jobs:
                state = str((job.get("detail") or {}).get("state") or job.get("state") or "")
                deploy = str(job.get("deploy") or (job.get("detail") or {}).get("deploy") or "")
                when = str(job.get("close_time") or "?")
                if state == "done":
                    tag = step.release or ""
                    exact = tag and tag == version_for(step.ref)
                    version = tag if exact else ""
                    said = (f"{step.member}#{step.ref}'s job ended `done` at {when} — released to "
                            f"production and verified; "
                            + (f"it was released as `{tag}`, the newest release tag"
                               if exact else
                               f"the newest release tag of {step.member} is "
                               f"`{tag or 'unknown'}` (the tag of this release is not on record)"))
                    cand = (0, IN_PRODUCTION, said, version)
                elif state == "merged" and deploy == "deployed":
                    cand = (1, IN_PRODUCTION,
                            f"{step.member}#{step.ref} merged at {when} and the deploy watch saw "
                            f"it deployed; the newest release tag of {step.member} is "
                            f"`{step.release or 'unknown'}`", "")
                elif state == "merged":
                    cand = (2, MERGED, f"{step.member}#{step.ref} merged at {when}; the deploy "
                                       f"watch says {deploy or 'nothing (none is declared)'}", "")
                elif str(job.get("status") or "") == "running":
                    cand = (3, BUILDING, f"{step.member}#{step.ref} has a job running "
                                         f"({state or 'no state yet'})", "")
                else:
                    continue
                if best is None or cand[0] < best[0]:
                    best = cand
        if best is not None:
            return best[1], best[2], best[3]
        first = steps[0]
        closed = (f", closed as {first.reason or 'done'} — the board's word, not a release"
                  if first.state == "closed" else "")
        return ON_THE_BOARD, f"{first.member}#{first.ref} is {first.state or 'on the board'}" \
            f"{closed}; no job of it is on record", ""

    # ── concept ↔ component ↔ code ───────────────────────────────────────────────────────────

    def _flows(self) -> list:
        from openfactory.knowledge.flows import read_flows

        where = getattr(self.sight, "flows", None)
        flows = read_flows(where) if where is not None else None
        return list(flows.flows) if flows is not None else []

    def _code_of(self, links: Iterable) -> list[str]:
        """The code each linked concept cites — `repo` `path:lines` — read from its bundle."""
        from openfactory.knowledge.okf import read_concepts
        from openfactory.product.config import repo_match

        bundles = getattr(self.sight, "bundles", None) or {}
        out: list[str] = []
        for link in links:
            home = next((b for r, b in bundles.items() if repo_match(r, link.repo)), None)
            if home is None:
                out.append(f"`{link.repo}` — {link.title}: its bundle is not published")
                continue
            concept = next((c for c in read_concepts(home)
                            if c.title.strip().lower() == link.title.strip().lower()), None)
            if concept is None:
                out.append(f"`{link.repo}` — {link.title}: no longer in its bundle")
                continue
            out += [f"`{link.repo}` `{s.path}" + (f":{s.lines}`" if s.lines else "`")
                    + f" ({link.title})" for s in concept.sources]
        return out

    def serving(self, name: str) -> dict | None:
        """What code serves the capability or flow `name` (a slug or a title): its components with
        where their code is, its interfaces, and each concept with the code it cites."""
        wanted = (name or "").strip().lower()
        cap = next((c for c in self.capabilities
                    if wanted in (c.slug, c.title.strip().lower())), None)
        flow = next((f for f in self._flows() if wanted in (f.slug, f.title.strip().lower())),
                    None)
        what = cap or flow
        if what is None:
            return None
        system = getattr(self.sight, "system", None)
        comps = {c.name: c for c in (system.components if system else [])}
        return {
            "title": what.title,
            "confirmed": bool(cap is not None and cap.curated),
            "components": [f"{n} — code in `{comps[n].repo}` `{comps[n].code or '.'}`"
                           if n in comps and comps[n].repo else f"{n} — no code declared for it"
                           for n in what.components],
            "interfaces": [f"{i.from_} → {i.to} ({i.kind}, {i.via})" for i in what.interfaces],
            "code": self._code_of(what.concepts)}

    def touched_by(self, name: str) -> dict | None:
        """If the concept or component `name` changes: the components that run it and those that
        call it or receive from it, and the requirements through the flows and capabilities that
        link it — or whose `Affects` names its repository."""
        from openfactory.knowledge.okf import read_concepts

        wanted = (name or "").strip().lower()
        system = getattr(self.sight, "system", None)
        bundles = getattr(self.sight, "bundles", None) or {}
        repo = ""
        concept_title = ""
        for r, home in bundles.items():
            for c in read_concepts(home) if home is not None else []:
                if c.title.strip().lower() == wanted:
                    repo, concept_title = r, c.title
        comps = [c for c in (system.components if system else [])
                 if (repo and c.repo == repo) or c.name.lower() == wanted]
        if not comps and not repo:
            return None
        names = {c.name for c in comps}
        repo = repo or next((c.repo for c in comps if c.repo), "")
        links = list(system.links if system else [])
        # A CALL AND AN EVENT ARE DIFFERENT DEPENDENCIES: a caller breaks when the part's API
        # changes; a receiver of its events breaks when what it announces does
        callers = sorted({f"{lk.from_} ({lk.kind}, {lk.via})" for lk in links
                          if lk.to in names and lk.from_ not in names and lk.kind != "event"})
        hears = sorted({f"{lk.from_} ({lk.kind}, {lk.via})" for lk in links
                        if lk.to in names and lk.from_ not in names and lk.kind == "event"})
        reached = sorted({f"{lk.to} ({lk.kind}, {lk.via})" for lk in links
                          if lk.from_ in names and lk.kind == "event"})
        reqs: set[int] = set()
        for flow in self._flows():
            if any(lk.title == concept_title and lk.repo == repo for lk in flow.concepts) \
                    or names & set(flow.components):
                reqs.update(flow.requirements)
        for cap in self.capabilities:
            if any(lk.title == concept_title for lk in cap.concepts) or names & set(
                    cap.components):
                reqs.update(cap.requirements)
        from openfactory.knowledge.flows import affected

        for r in getattr(self.model, "requirements", None) or []:
            if repo and repo in affected(_Req(r), self.declared):
                reqs.add(int(r.get("number") or 0))
        return {"repo": repo, "concept": concept_title, "components": sorted(names),
                "called_by": callers, "hears_from": hears, "sends_to": reached,
                "requirements": sorted(reqs)}

    # ── the file ──────────────────────────────────────────────────────────────────────────────

    def render(self, *, docs: str = "docs") -> str:
        lines = ["# The chain — from a request to production, and from a flow to the code", "",
                 "The platform's own records, joined for this message: request → requirement → "
                 "card → job and pull request → release, crossed with concept ↔ component ↔ code. "
                 "Every verdict names the link it rests on; a link that could not be read is said, "
                 "never read as absent. Nobody is named: a requirement's requester is its "
                 "requester.", "", "## Is each requirement in production?", ""]
        reqs = getattr(self.model, "requirements", None)
        if self.model is None or reqs is None:
            lines.append("- The product's read model could not be built for this message — the "
                         "board, the jobs and the releases were not read; say so.")
        elif not reqs:
            lines.append("- This product has no requirements written down yet.")
        for r in (reqs or [])[:LIMIT]:
            trace = self.requirement(int(r.get("number") or 0))
            if trace is None:
                continue
            lines += [f"### REQ-{trace.number:04d} — {trace.title} ({trace.status})",
                      f"- **{trace.verdict}** — {trace.because}"
                      + (f"; version `{trace.version}`" if trace.version else "")]
            for step in trace.steps:
                pulls = sorted({str((j.get("action") or {}).get("pr_url")
                                    or (j.get("detail") or {}).get("pr_url") or "")
                                for j in step.jobs} - {""})
                lines.append(f"- card {step.member}#{step.ref} «{step.title}» — "
                             f"{step.state or '?'}{':' + step.reason if step.reason else ''}; "
                             f"{len(step.jobs)} job(s)"
                             + (f"; pull request(s): {', '.join(pulls)}" if pulls else ""))
            if trace.sources:
                lines.append("- crosses " + ", ".join(f"`{s}`" for s in trace.sources)
                             + (f" — components {', '.join(trace.components)}"
                                if trace.components else ""))
            for slug in trace.capabilities:
                lines.append(f"- capability `{docs}/capabilities/{slug}.md`")
            for slug in trace.flows:
                lines.append(f"- observed flow `{slug}` — `{docs}/.okf/flows/flows.yaml`")
            lines += [f"- code: {c}" for c in trace.code]
            lines.append("")
        lines += ["## What code serves each capability and flow", ""]
        names = [c.slug for c in self.capabilities] + [f.slug for f in self._flows()
                                                        if f.slug not in {c.slug for c in
                                                                          self.capabilities}]
        if not names:
            lines += ["- No capability is confirmed and no flow across the sources is observed "
                      "yet.", ""]
        for name in names[:LIMIT]:
            got = self.serving(name) or {}
            lines += [f"### {got.get('title', name)} — "
                      + ("confirmed by a person of the product" if got.get("confirmed")
                         else "observed, not confirmed")]
            lines += [f"- component {c}" for c in got.get("components", [])]
            lines += [f"- interface {i}" for i in got.get("interfaces", [])]
            lines += [f"- code: {c}" for c in got.get("code", [])]
            lines.append("")
        lines += ["## If a part changes — what it touches", ""]
        system = getattr(self.sight, "system", None)
        parts = [c.name for c in (system.components if system else []) if c.repo]
        if not parts:
            lines += ["- No system map is published, so what a change touches across services "
                      "cannot be walked here.", ""]
        for name in parts[:LIMIT]:
            got = self.touched_by(name) or {}
            lines.append(f"### component `{name}` — code in `{got.get('repo') or '?'}`")
            lines.append("- called by: " + (", ".join(got.get("called_by") or []) or "nobody "
                                            "declared"))
            if got.get("hears_from"):
                lines.append("- receives the events of: " + ", ".join(got["hears_from"]))
            if got.get("sends_to"):
                lines.append("- its events reach: " + ", ".join(got["sends_to"]))
            lines.append("- requirements touched: " + (", ".join(
                f"REQ-{n:04d}" for n in got.get("requirements") or []) or "none that names it"))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


class _Req:
    """A requirement row of the model, shaped like `corpus.Requirement` for `flows.affected`."""

    def __init__(self, row: dict) -> None:
        self.affects = list(row.get("affects") or [])


def build(model, sight, *, declared: list[str], docs_root: Path | None) -> Chain:
    """The chain of one turn: the model it was handed and the sight the module took."""
    from openfactory.product.capabilities import load_capabilities

    caps, _ = load_capabilities(docs_root)
    return Chain(model=model, sight=sight, declared=list(declared), capabilities=caps)


__all__ = ["BUILDING", "IN_PRODUCTION", "MERGED", "NO_CARD", "ON_THE_BOARD", "UNREAD", "Chain",
           "Step", "Trace", "build"]
