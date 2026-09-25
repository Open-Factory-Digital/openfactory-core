"""A flow that crosses services, observed by the pipeline — and a concept of its own (ADR-0052 D19,
#268 slice 3).

A QUESTION A CLIENT ASKS IS ABOUT A FLOW, AND A FLOW SPANS SERVICES. "Is the freight on the
invoice?" is the orders service fixing a quote from the freight service and the billing service
reading it back from orders. Each bundle describes its own repository; nothing joined the parts,
so the role answered about each and left the person to add them up. This module joins them —
deterministically, from what the platform already holds, with no model:

    a requirement          whose `Affects` names two or more of the product's sources — the
                           product's own statement that something crosses repositories. Only one
                           that is `accepted` (a promise) or `observed` (read off the code): a
                           `proposed` one may not be built, and a flow of unbuilt code is a guess
    its components         the system map's components whose code lives in those sources (D17)
    its interfaces         the system map's links between those components, each cited
    its concepts           the concepts of those sources' bundles that NAME ANOTHER PART OF THE
                           FLOW — a source or a component of it — in their `Depends on` or
                           `Consumed by`: the concept is about the crossing, in its own words

and writes each flow as a CONCEPT of type `flow` whose sources are its concepts' sources, each
naming its repository — so the one file a role opens walks the flow with citations into every
service, and is checked at turn time source by source against the repository each names
(`check.check_across`). What an observation could not link is said: a source of the flow with no
bundle, or with no concept naming another part of it.

AN OBSERVATION, NOT A CAPABILITY. What this writes is what the code and the declarations show, as
every concept is — `draft`, a machine's reading, promising nothing. The capability — "this is how
the product is organised; checkout IS the web, orders and payments" — is the product's, and it is
curated truth only once a person of the product confirms it (`product/capabilities.py`). Nothing
here is read as that confirmation.

WHERE: `.okf/flows/` in the context repository — `flows.yaml` (the observations, structured, with
a `derived_key`), `concepts/flow/<slug>.md`, `okf.yaml` and `index.md` — beside `.okf/system/` and
`.okf/repos/`, and written by the system refresh through `publish_dir` like them: derived
knowledge, published by the pipeline, never by a role. It belongs to no one source, and one
directory under `.okf/` keeps it out of the way of the front door onboarding writes at the root.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from openfactory.knowledge.contracts import Concept, ConceptSource, Gap, OkfManifest

_MODEL = ConfigDict(extra="ignore", populate_by_name=True)

FLOWS_DIRNAME = "flows"
FLOWS_FILE = "flows.yaml"
FLOW_TYPE = "flow"
BUNDLE_KIND = "product-flows"
#: Who observed it — a machine event, never a signature (`Concept.generated_by`).
OBSERVER = "machine:knowledge-flows"
#: The gap kind for what an observation could not link.
NOT_LINKED = "not-linked"
#: The requirement statuses a flow is observed from — a promise, or a reading of the code.
FROM_STATUSES = ("accepted", "observed")

SCOPE_LIMIT = (
    "Observed by a machine from the product's requirements, its system map and its per-source "
    "bundles: each flow is a requirement that names several repositories, the components and "
    "interfaces between them, and the concepts of each that name another part of it. It is a "
    "reading of what the code does, never a specification, and never the product's capability "
    "until a person of the product confirms one.")


class ConceptLink(BaseModel):
    """A concept of one source's bundle, as a flow or a capability links it: the repository, the
    concept's title, and its file in the context repository (`.okf/repos/<source>/concepts/…`)."""

    model_config = _MODEL

    repo: str
    title: str
    path: str = ""


class InterfaceLink(BaseModel):
    """One declared interface of the system map a flow crosses: `from` talks to `to`."""

    model_config = _MODEL

    from_: str = Field(alias="from")
    to: str
    kind: str
    via: str = ""
    #: where the system map says so — `repo` `path:line`, as written
    cited: list[str] = Field(default_factory=list)

    def same(self, other: InterfaceLink) -> bool:
        return (self.from_, self.to, self.kind) == (other.from_, other.to, other.kind)


class Flow(BaseModel):
    """One observed flow: the requirement it is, what carries it, and its concept's file."""

    model_config = _MODEL

    slug: str
    title: str
    requirements: list[int] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    interfaces: list[InterfaceLink] = Field(default_factory=list)
    concepts: list[ConceptLink] = Field(default_factory=list)
    #: the flow's own concept, relative to `.okf/flows/`
    concept: str = ""
    #: what the observation could not link, in a sentence each
    not_linked: list[str] = Field(default_factory=list)


class Flows(BaseModel):
    """`flows.yaml`: every observed flow, and the key the refresh converges on."""

    model_config = _MODEL

    version: str = "1"
    derived_key: str = ""
    generated_at: str = ""
    scope_limit: str = SCOPE_LIMIT
    flows: list[Flow] = Field(default_factory=list)

    def by_slug(self, slug: str) -> Flow | None:
        wanted = (slug or "").strip().lower()
        return next((f for f in self.flows if f.slug == wanted), None)


# ── observing ───────────────────────────────────────────────────────────────────────────────────

def affected(requirement, sources: Iterable[str]) -> list[str]:
    """The declared sources a requirement's `Affects` names, in declaration order. An entry may
    hold several names — "`orders`, `billing`" is one bullet — and each is matched as a repository
    reference (`repo_match`), never as a substring."""
    from openfactory.product.config import repo_match

    said = [part.strip().strip("`*").strip() for item in (getattr(requirement, "affects", None)
                                                          or ())
            for part in re.split(r"[,;]", str(item))]
    return [s for s in sources if any(p and repo_match(p, s) for p in said)]


def _named(text: str) -> list[str]:
    """The items of a concept file's `Depends on` and `Consumed by` sections — what the concept
    says, in its own words, it is joined to."""
    out: list[str] = []
    for heading in ("Depends on", "Consumed by"):
        m = re.search(rf"^##\s+{heading}\s*\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
        if m:
            out += [ln.strip()[1:].strip().strip("`") for ln in m.group(1).splitlines()
                    if ln.strip().startswith(("-", "*"))]
    return [x for x in out if x]


def _joins(named: list[str], others: set[str]) -> bool:
    """Whether any name a concept gives is one of `others` — a repository or a component of the
    flow — as a whole word, never as a part of a longer one."""
    from openfactory.product.config import repo_match

    for item in named:
        for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]*", item):
            if any(repo_match(word, o) or word.lower() == o.lower() for o in others):
                return True
    return False


def _concepts_of(bundle: Path | None) -> list[tuple[Concept, str, list[str]]]:
    """`(concept, its file in the context repository, what it names)` for every concept of one
    bundle — the bundle being `.okf/repos/<source>/` of that repository."""
    from openfactory.knowledge.okf import assign_paths, read_concepts
    from openfactory.knowledge.pipeline import OKF_DIRNAME, OKF_REPOS_DIRNAME
    from openfactory.knowledge.system.tree import read_text

    if bundle is None:
        return []
    out = []
    for concept, rel in assign_paths(read_concepts(bundle)):
        # through the tree's reader, like every file of a checkout: never through a link
        text = read_text(Path(bundle), rel.as_posix()).text or ""
        home = f"{OKF_DIRNAME}/{OKF_REPOS_DIRNAME}/{Path(bundle).name}/{rel.as_posix()}"
        out.append((concept, home, _named(text)))
    return out


def observe(requirements: Iterable, *, sources: list[str], bundles: Mapping[str, Path | None],
            system=None, generated_at: str = "") -> tuple[Flows, list[Concept]]:
    """Every flow the requirements, the system map and the bundles show — and its concept.

    `sources` is the product's `sources:` in declaration order; `bundles` maps each to its bundle
    in the context repository (None when it has none); `system` is the derived `SystemMap`, or None
    when there is none yet (then no component or interface is linked, and each flow says so)."""
    from openfactory.knowledge.okf import slug

    flows: list[Flow] = []
    concepts: list[Concept] = []
    reqs = sorted((r for r in requirements
                   if getattr(r, "status", "") in FROM_STATUSES
                   and getattr(r, "superseded_by", None) is None),
                  key=lambda r: int(getattr(r, "number", 0) or 0))
    for req in reqs:
        crossed = affected(req, sources)
        if len(crossed) < 2:
            continue
        components = sorted(c.name for c in (system.components if system else [])
                            if c.repo and c.repo in crossed)
        interfaces = [
            InterfaceLink(**{"from": lk.from_}, to=lk.to, kind=lk.kind, via=lk.via,
                          cited=[f"`{s.repo}` `{s.path}" + (f":{s.line}`" if s.line else "`")
                                 for s in lk.sources])
            for lk in (system.links if system else [])
            if lk.from_ in components and lk.to in components]
        interfaces.sort(key=lambda i: (i.from_, i.to, i.kind, i.via))
        links: list[ConceptLink] = []
        sourced: list[ConceptSource] = []
        missing: list[str] = []
        for repo in crossed:
            bundle = bundles.get(repo)
            if bundle is None:
                missing.append(f"`{repo}` has no knowledge bundle published — what it does in this "
                               f"flow is not described")
                continue
            here = {c.name for c in (system.components if system else []) if c.repo == repo}
            others = ({r for r in crossed if r != repo}
                      | {c for c in components if c not in here})
            joined = [(c, rel) for c, rel, named in _concepts_of(bundle) if _joins(named, others)]
            if not joined:
                missing.append(f"no concept of `{repo}` names another part of this flow")
            for concept, rel in joined:
                links.append(ConceptLink(repo=repo, title=concept.title, path=rel))
                for s in concept.sources:
                    if not any(x.repo == repo and x.path == s.path for x in sourced):
                        sourced.append(s.model_copy(update={"repo": repo}))
        if system is None:
            missing.append("no system map is published — its components and interfaces are not "
                           "linked")
        elif not interfaces:
            missing.append("the system map declares no interface between its components")
        links.sort(key=lambda c: (c.repo, c.title))
        flow = Flow(slug=f"{int(req.number):04d}-{slug(req.title or req.slug)}",
                    title=req.title or req.slug, requirements=[int(req.number)], sources=crossed,
                    components=components, interfaces=interfaces, concepts=links,
                    not_linked=missing)
        flows.append(flow)
        concepts.append(_concept_of(flow, sourced, generated_at=generated_at))
    from openfactory.knowledge.okf import assign_paths

    where = {c.title: rel.as_posix() for c, rel in assign_paths(concepts)}
    for flow in flows:
        flow.concept = where.get(flow.title, "")
    out = Flows(generated_at=generated_at, flows=flows)
    return out.model_copy(update={"derived_key": derived_key(out)}), concepts


def _concept_of(flow: Flow, sources: list[ConceptSource], *, generated_at: str) -> Concept:
    """The flow as a concept: it walks the flow, and cites what each part's concept cites."""
    reqs = ", ".join(f"REQ-{n:04d}" for n in flow.requirements)
    steps = [f"{i.from_} → {i.to} over {i.kind} ({i.via})" + (f" — {'; '.join(i.cited)}"
                                                             if i.cited else "")
             for i in flow.interfaces]
    return Concept(
        type=FLOW_TYPE, title=flow.title,
        description=f"{reqs} across {', '.join(f'`{s}`' for s in flow.sources)}",
        status="draft", generated_by=OBSERVER, generated_at=generated_at,
        sources=sources,
        what_it_does=(f"The flow {reqs} names, as the code carries it across "
                      f"{len(flow.sources)} repositories: "
                      + (", ".join(flow.components) or "no component the system map declares")
                      + ". Open each part's concept for what it does, and its code to confirm."),
        behaviour=steps,
        depends_on=[f"`{c.repo}` — {c.title} (`{c.path}`)" for c in flow.concepts],
        caveats=list(flow.not_linked))


def derived_key(flows: Flows) -> str:
    """The observations' identity with the clock and the key itself blanked. The concepts'
    fingerprints are inside it on purpose: a part whose code moved is a flow to publish again."""
    data = flows.model_dump(by_alias=True, mode="json")
    data["generated_at"] = ""
    data["derived_key"] = ""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ── writing and reading ─────────────────────────────────────────────────────────────────────────

def _dump(data: object) -> str:
    return yaml.safe_dump(data, sort_keys=True, default_flow_style=False, allow_unicode=True,
                          width=100)


def write_flows(flows: Flows, concepts: list[Concept], into: str | Path) -> list[Path]:
    """`.okf/flows/` as files INTO `into`: `flows.yaml`, the concepts, `okf.yaml` and `index.md` —
    what the observations could not link written as the bundle's own gaps, first in its index."""
    from openfactory.knowledge.okf import OKF_INDEX_FILE, render_index, write_okf

    out = Path(into)
    out.mkdir(parents=True, exist_ok=True)
    gaps = [Gap(kind=NOT_LINKED, path=flow.concept, detail=f"{flow.title}: {why}")
            for flow in flows.flows for why in flow.not_linked]
    manifest = OkfManifest(bundle_kind=BUNDLE_KIND, generated_at=flows.generated_at,
                           gaps=gaps, scope_limit=SCOPE_LIMIT)
    written = write_okf(out, manifest=manifest, concepts=concepts)
    (out / OKF_INDEX_FILE).write_text(render_index(manifest, concepts), encoding="utf-8")
    (out / FLOWS_FILE).write_text(_dump(flows.model_dump(by_alias=True, mode="json")),
                                  encoding="utf-8")
    return sorted([*written, out / OKF_INDEX_FILE, out / FLOWS_FILE])


def read_flows(flows_dir: str | Path | None) -> Flows | None:
    """`flows.yaml` of the directory at `flows_dir`, or None when there is none to read. Read
    through `tree.read_text`, like every file of a checkout: a `flows.yaml` somebody replaced with
    a link out of the context repository is not followed."""
    from openfactory.knowledge.system.tree import read_text

    if flows_dir is None:
        return None
    got = read_text(Path(flows_dir), FLOWS_FILE)
    if got.text is None:
        return None
    try:
        data = yaml.safe_load(got.text)
        return Flows(**data) if isinstance(data, dict) else None
    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
        return None


__all__ = ["BUNDLE_KIND", "FLOWS_DIRNAME", "FLOWS_FILE", "FLOW_TYPE", "NOT_LINKED", "OBSERVER",
           "SCOPE_LIMIT", "ConceptLink", "Flow", "Flows", "InterfaceLink", "affected",
           "derived_key", "observe", "read_flows", "write_flows"]
