"""The product's business capabilities: a flow, and what carries it across the sources — curated
truth only once a person of the product confirms it (ADR-0052 D19, #268 slice 3).

A CAPABILITY IS THE PRODUCT'S WORD FOR A FLOW. "Checkout is the web front end, orders and payments"
is a statement about how the product is organised, and the factory will argue from it: which
services a change to the flow touches, which code serves it, whether what a client reports breaks
it. So it is held to the discipline the corpus holds a requirement to — `observed` is not
`accepted` — and the glossary a fact to — `aprendido` is not `confirmado`:

    observed    a machine's reading of which parts carry a flow: the knowledge pipeline's
                observations at `.okf/flows/` (`knowledge/flows.py`), and any capability file a
                person wrote without a confirmation. Usable as evidence, said as observed, never
                stated as how the product is organised.
    confirmed   a person of the product said so — `confirmed_by` and `confirmed_at` recorded, by
                the one act that writes them (`ProductModule.confirm_capability`, gated like every
                write by `may_act`) or by that person's own commit to the file. Curated truth.
    retired     taken back; kept as the record, never read as current.

A status of `confirmed` with nobody or no date beside it is not a confirmation: it is read as
`observed` and named as a finding — an acceptance nobody can attribute is not one (`corpus.py`).

WHERE IT IS WRITTEN: `capabilities/<slug>.md` in the context repository — at the product level,
beside `requirements/` and `domain/` (ADR-0052 D14: "product — the requirements, the glossary and
the business capabilities"), and NOT under `.okf/`, which the pipeline rewrites on every refresh
and which holds what the code does rather than what the product is. YAML front matter for what a
machine checks (the links, the status, who and when) and prose for people — a concept's shape
(`okf.render_concept`), so a person can correct one by hand.

A LINK TO SOMETHING THAT NO LONGER EXISTS IS REPORTED (`dangling`). A capability is curated and
the code is not: a concept retitled by a renewal, a component the map no longer derives, an
interface nobody declares any more, the observation it was confirmed from gone. Each is said —
in the prompt, in the chain, in the log — and never repaired here: which link is now right is
the person's to decide, not a machine's to guess.

WHAT A CAPABILITY NEVER CARRIES INTO A PROMPT: who confirmed it. The file keeps the person for
whoever maintains it; a conversation hears that a person of the product confirmed it, and when
(ADR-0051 D9 — nobody is named across conversations).
"""

from __future__ import annotations

import logging
import re
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from openfactory.knowledge.flows import ConceptLink, Flow, Flows, InterfaceLink

log = logging.getLogger("openfactory.product")

CAPABILITIES_DIR = "capabilities"
OBSERVED, CONFIRMED, RETIRED = "observed", "confirmed", "retired"
_KNOWN = (OBSERVED, CONFIRMED, RETIRED)
#: How many capabilities the prompt names, of each kind, before it says how many more there are.
PROMPT_LIMIT = 12

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,95}$")


class Finding(BaseModel):
    level: str
    code: str
    slug: str
    message: str


class Capability(BaseModel):
    """One business capability, as its file says it."""

    slug: str
    title: str
    status: str = OBSERVED
    requirements: list[int] = Field(default_factory=list)
    #: the observed flow (`.okf/flows/flows.yaml`) it was confirmed from — "" for one a person wrote
    flow: str = ""
    sources: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    interfaces: list[InterfaceLink] = Field(default_factory=list)
    concepts: list[ConceptLink] = Field(default_factory=list)
    proposed_by: str = ""
    proposed_at: str = ""
    confirmed_by: str = ""
    confirmed_at: str = ""
    summary: str = ""
    path: str = ""

    @property
    def curated(self) -> bool:
        """Whether this is the product's truth: confirmed, by somebody, on a day."""
        return self.status == CONFIRMED and bool(self.confirmed_by.strip()
                                                 and self.confirmed_at.strip())


def path_for(slug: str) -> str:
    return f"{CAPABILITIES_DIR}/{slug}.md"


def is_slug(slug: str) -> bool:
    """Whether `slug` can name a capability file: lower-case words joined by hyphens, and nothing
    that could climb out of `capabilities/` — the slug is typed by a person, and the file it names
    is written."""
    return bool(_SLUG.match(slug or ""))


# ── the file ────────────────────────────────────────────────────────────────────────────────────

def render_capability(cap: Capability) -> str:
    """One capability as front matter plus prose — deterministic, keys sorted."""
    head: dict[str, object] = {"title": cap.title, "status": cap.status}
    for key in ("requirements", "flow", "sources", "components", "proposed_by", "proposed_at",
                "confirmed_by", "confirmed_at"):
        value = getattr(cap, key)
        if value:
            head[key] = value
    if cap.interfaces:
        head["interfaces"] = [{k: v for k, v in i.model_dump(by_alias=True).items() if v}
                              for i in cap.interfaces]
    if cap.concepts:
        head["concepts"] = [{k: v for k, v in c.model_dump().items() if v} for c in cap.concepts]
    body = yaml.safe_dump(head, sort_keys=True, default_flow_style=False, allow_unicode=True,
                          width=100).rstrip()
    lines = ["---", body, "---", "", f"# {cap.title}", ""]
    if cap.summary.strip():
        lines += [cap.summary.strip(), ""]
    return "\n".join(lines).rstrip() + "\n"


def parse_capability(text: str, *, path: str) -> tuple[Capability | None, list[Finding]]:
    """One capability file. Never raises: an unreadable one is a finding, and one bad file must
    not cost the rest."""
    slug = Path(path).stem
    match = _FRONTMATTER.match(text or "")
    if match is None:
        return None, [Finding(level="error", code="no-front-matter", slug=slug,
                              message="no front matter — nothing says what it links")]
    try:
        head = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        return None, [Finding(level="error", code="unreadable", slug=slug,
                              message=f"its front matter is not YAML ({str(exc)[:120]})")]
    if not isinstance(head, dict):
        return None, [Finding(level="error", code="unreadable", slug=slug,
                              message="its front matter is not a mapping")]
    findings: list[Finding] = []
    status = str(head.get("status") or OBSERVED).strip().lower()
    if status not in _KNOWN:
        findings.append(Finding(level="error", code="status-unknown", slug=slug,
                                message=f"status {status!r} is not one of {', '.join(_KNOWN)}; "
                                        f"read as {OBSERVED!r}"))
        status = OBSERVED
    try:
        cap = Capability(
            slug=slug, title=str(head.get("title") or slug), status=status,
            requirements=[int(n) for n in head.get("requirements") or []],
            flow=str(head.get("flow") or ""),
            sources=[str(s) for s in head.get("sources") or []],
            components=[str(c) for c in head.get("components") or []],
            interfaces=[InterfaceLink(**i) for i in head.get("interfaces") or []
                        if isinstance(i, dict)],
            concepts=[ConceptLink(**c) for c in head.get("concepts") or [] if isinstance(c, dict)],
            proposed_by=str(head.get("proposed_by") or ""),
            proposed_at=str(head.get("proposed_at") or ""),
            confirmed_by=str(head.get("confirmed_by") or ""),
            confirmed_at=str(head.get("confirmed_at") or ""),
            summary=_prose(match.group(2)), path=path)
    except (TypeError, ValueError) as exc:
        return None, findings + [Finding(level="error", code="unreadable", slug=slug,
                                         message=f"a link could not be read ({str(exc)[:120]})")]
    if cap.status == CONFIRMED and not cap.curated:
        # NOT A CONFIRMATION: nobody, or no day, beside the word. Read as observed, and said.
        findings.append(Finding(level="error", code="unattributed", slug=slug,
                                message="`confirmed` with nobody or no date recorded — read as "
                                        "observed until a person confirms it"))
        cap = cap.model_copy(update={"status": OBSERVED})
    return cap, findings


def _prose(body: str) -> str:
    lines = [ln for ln in (body or "").strip().splitlines() if not ln.startswith("# ")]
    return "\n".join(lines).strip()


def load_capabilities(docs_root: str | Path | None) -> tuple[list[Capability], list[Finding]]:
    """Every capability under `capabilities/` of the context repository at `docs_root`. A missing
    directory is none — the normal state of a product nobody has confirmed a flow of yet. Read
    through `tree.read_text`: a capability file that is a link out of the repository is not
    followed."""
    from openfactory.knowledge.system.tree import read_text

    if docs_root is None:
        return [], []
    folder = Path(docs_root) / CAPABILITIES_DIR
    if not folder.is_dir() or folder.is_symlink():
        return [], []
    caps: list[Capability] = []
    findings: list[Finding] = []
    for entry in sorted(folder.iterdir()):
        if entry.suffix != ".md" or not _SLUG.match(entry.stem):
            continue
        got = read_text(Path(docs_root), path_for(entry.stem))
        if got.text is None:
            findings.append(Finding(level="error", code="unreadable", slug=entry.stem,
                                    message=f"could not be read ({got.why})"))
            continue
        cap, found = parse_capability(got.text, path=path_for(entry.stem))
        findings += found
        if cap is not None:
            caps.append(cap)
    return caps, findings


def from_flow(flow: Flow, *, confirmed_by: str, confirmed_at: str) -> Capability:
    """The observation `flow`, confirmed by a person — its links frozen as they were seen."""
    from openfactory.knowledge.flows import OBSERVER

    return Capability(slug=flow.slug, title=flow.title, status=CONFIRMED,
                      requirements=list(flow.requirements), flow=flow.slug,
                      sources=list(flow.sources), components=list(flow.components),
                      interfaces=[i.model_copy(update={"cited": []}) for i in flow.interfaces],
                      concepts=list(flow.concepts), proposed_by=OBSERVER,
                      confirmed_by=confirmed_by, confirmed_at=confirmed_at,
                      summary=("Confirmed from the flow the knowledge pipeline observed for "
                               + ", ".join(f"REQ-{n:04d}" for n in flow.requirements)
                               + f" (`.okf/flows/{flow.concept}`)."))


# ── what no longer exists ───────────────────────────────────────────────────────────────────────

def dangling(cap: Capability, *, bundles: Mapping[str, Path | None], system=None,
             flows: Flows | None = None) -> list[str]:
    """Every link of `cap` to something that no longer exists, in a sentence each — `[]` when all
    of them hold. `bundles` maps each declared source to its bundle (None when it has none);
    `system` is the published `SystemMap` (None: components and interfaces are not checked, and
    that is said once)."""
    from openfactory.knowledge.okf import concept_path, read_concepts
    from openfactory.product.config import repo_match

    out: list[str] = []
    read: dict[str, list] = {}
    for link in cap.concepts:
        home = next((b for r, b in bundles.items() if repo_match(r, link.repo)), None)
        if home is None:
            out.append(f"the concept `{link.repo}` — {link.title}: that source has no knowledge "
                       f"bundle any more, or is no longer declared")
            continue
        concepts = read.setdefault(link.repo, read_concepts(home))
        wanted = link.title.strip().lower()
        if not any(c.title.strip().lower() == wanted
                   or (link.path and link.path.endswith(concept_path(c).as_posix()))
                   for c in concepts):
            out.append(f"the concept `{link.repo}` — {link.title} no longer exists")
    if system is None:
        if cap.components or cap.interfaces:
            out.append("its components and interfaces could not be checked: no system map is "
                       "published")
    else:
        names = {c.name for c in system.components}
        out += [f"the component `{name}` is no longer on the system map"
                for name in cap.components if name not in names]
        declared = [(lk.from_, lk.to, lk.kind) for lk in system.links]
        out += [f"the interface {i.from_} → {i.to} ({i.kind}) is no longer declared"
                for i in cap.interfaces if (i.from_, i.to, i.kind) not in declared]
    if cap.flow and flows is not None and flows.by_slug(cap.flow) is None:
        out.append(f"the flow it was confirmed from (`{cap.flow}`) is no longer observed")
    return out


# ── the prompt ──────────────────────────────────────────────────────────────────────────────────

def prompt_lines(caps: list[Capability], flows: Flows | None, *, docs: str,
                 broken: Mapping[str, list[str]], limit: int = PROMPT_LIMIT) -> list[str]:
    """What the role is told about the product's capabilities: the confirmed ones as the
    product's, the observed ones as observations — bounded, the cut counted, and each dangling link
    said beside the capability it breaks. `docs` is where the context repository is, relative to
    the root the role stands in."""
    curated = [c for c in caps if c.curated]
    taken = {c.slug for c in caps} | {c.flow for c in caps if c.flow}
    observed = [c for c in caps if c.status == OBSERVED]
    unconfirmed = [f for f in (flows.flows if flows else []) if f.slug not in taken]
    if not curated and not observed and not unconfirmed:
        return []
    lines = ["", "# The product's business capabilities, across its sources", "",
             "A capability names one business flow and what carries it across the repositories — "
             "the concepts, the components and the interfaces between them. Open the files the "
             "question needs; the code says what is true."]
    if curated:
        lines += ["", "**Confirmed by a person of the product** — you may say this is how the "
                      "product is organised:"]
        for cap in curated[:limit]:
            lines.append(f"- **{cap.title}** — `{docs}/{cap.path}`"
                         + _carried(cap.requirements, cap.components, cap.concepts)
                         + f"; confirmed on {cap.confirmed_at}")
            lines += [f"  - a link that no longer holds: {why} — say so if you rely on it; a "
                      f"person has to correct the capability" for why in broken.get(cap.slug, [])]
        if len(curated) > limit:
            lines.append(f"- and {len(curated) - limit} more under `{docs}/{CAPABILITIES_DIR}/`")
    if observed or unconfirmed:
        lines += ["", "**Observed, NOT confirmed by anybody** — a machine's reading of which parts "
                      "carry a flow. Use it as evidence of where to look, say it is observed, and "
                      "never present it as how the product is organised:"]
        shown = 0
        for cap in observed:
            if shown >= limit:
                break
            shown += 1
            lines.append(f"- {cap.title} — `{docs}/{cap.path}`"
                         + _carried(cap.requirements, cap.components, cap.concepts))
            lines += [f"  - a link that no longer holds: {why}" for why in broken.get(cap.slug,
                                                                                       [])]
        for flow in unconfirmed:
            if shown >= limit:
                break
            shown += 1
            lines.append(f"- {flow.title} — its flow concept `{docs}/.okf/flows/{flow.concept}`"
                         + _carried(flow.requirements, flow.components, flow.concepts)
                         + (f"; not linked: {'; '.join(flow.not_linked)}" if flow.not_linked
                            else ""))
        rest = len(observed) + len(unconfirmed) - shown
        if rest > 0:
            lines.append(f"- and {rest} more in `{docs}/.okf/flows/index.md`")
    return lines


def _carried(requirements, components, concepts) -> str:
    parts = []
    if requirements:
        parts.append(", ".join(f"REQ-{int(n):04d}" for n in requirements))
    if components:
        parts.append("components " + ", ".join(components))
    if concepts:
        parts.append("concepts " + ", ".join(f"`{c.repo}` — {c.title}" for c in concepts))
    return (" — " + "; ".join(parts)) if parts else ""


# ── the write: a person's confirmation ──────────────────────────────────────────────────────────

def confirm_in_repository(*, docs_repo: str, clone_url: str, slug: str, flow: Flow | None,
                          confirmed_by: str, base: str = "main", today: str | None = None):
    """Record that a person confirmed the capability `slug` — THE ONLY ACT THAT MAKES ONE CURATED.

    A file already under `capabilities/` is flipped to `confirmed` with who and when, its links
    kept as the person wrote them; with none, the observation `flow` is written as the capability,
    confirmed. Committed straight to the documentation branch, as an acceptance is
    (`authoring.accept_requirement`): what changes is one status, because an authorised person
    said so. Never raises past its clone: every refusal is a `WriteResult` with a sentence."""
    import shutil

    from openfactory.product.authoring import WriteResult, _git, _scrub

    if not is_slug(slug):
        return WriteResult(ok=False, detail="esse nome não é o de uma capacidade")
    day = today or datetime.now(UTC).date().isoformat()
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-capability-"))
    rel = path_for(slug)
    try:
        rc, out = _git(["clone", "--depth", "1", "--branch", base, clone_url, str(tmp)])
        if rc != 0:
            return WriteResult(ok=False,
                               detail=f"could not clone {docs_repo}: {_scrub(out)[-200:]}")
        target = tmp / rel
        if target.is_symlink():
            return WriteResult(ok=False, ref=rel, detail="o arquivo dessa capacidade é um link — "
                                                         "não escrevo através dele")
        if target.is_file():
            cap, _ = parse_capability(target.read_text(encoding="utf-8"), path=rel)
            if cap is None:
                return WriteResult(ok=False, ref=rel,
                                   detail="não consegui ler o arquivo dessa capacidade")
            if cap.curated:
                return WriteResult(ok=True, ref=rel, existed=True,
                                   detail="essa capacidade já estava confirmada")
            if cap.status == RETIRED:
                return WriteResult(ok=False, ref=rel,
                                   detail="essa capacidade foi aposentada — confirmar de novo é "
                                          "uma decisão a registrar por escrito, não um sim")
            cap = cap.model_copy(update={"status": CONFIRMED, "confirmed_by": confirmed_by,
                                         "confirmed_at": day})
        elif flow is not None:
            cap = from_flow(flow, confirmed_by=confirmed_by, confirmed_at=day)
        else:
            return WriteResult(ok=False, ref=rel,
                               detail="não encontrei essa capacidade entre as observadas nem "
                                      "entre as escritas")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_capability(cap.model_copy(update={"path": rel})),
                          encoding="utf-8")
        _git(["add", "--", rel], cwd=tmp)
        rc, out = _git(["commit", "-m", f"capacidade {slug}: confirmada por {confirmed_by}"],
                       cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False, detail=f"nothing to commit: {_scrub(out)[-200:]}")
        rc, out = _git(["push", clone_url, f"HEAD:{base}"], cwd=tmp)
        if rc != 0:
            return WriteResult(ok=False, detail=f"o repositório não aceita registro direto "
                                                f"({_scrub(out)[-120:]})")
        return WriteResult(ok=True, ref=rel)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


__all__ = ["CAPABILITIES_DIR", "CONFIRMED", "OBSERVED", "RETIRED", "Capability", "Finding",
           "confirm_in_repository", "dangling", "from_flow", "is_slug", "load_capabilities",
           "parse_capability", "path_for", "prompt_lines", "render_capability"]
