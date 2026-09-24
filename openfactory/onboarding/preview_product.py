"""Propose how a PRODUCT of several repositories is previewed — in its context repository, on a
pull request of its own (ADR-0050 D12; the design on #265, §4.1(d), §6.4, S6 and S7).

`preview_propose.py` drafts one repository's preview into that repository. A product of a front
end and a back end has no one repository to put it in: how the whole runs is said in the CONTEXT
repository — a compose file at `.openfactory/preview.compose.yml` that builds each source from
`../../<short name>`, and the `preview:` block of `.openfactory/product.yaml` that names it — the
two files a preview of the product reads (`openfactory/preview/product.py`).

EVERY SOURCE IS READ, NONE IS WRITTEN. Each repository of `sources:` is cloned and read by the one
reader (`infer_preview`): its Dockerfiles, their `EXPOSE`, the stores its dependencies name. What
they say is COMBINED — each service's build context re-rooted beside the others, every citation
prefixed with the directory it was read in — and the tiers decide what is written exactly as they
do for one repository (`draft`). S7 is the other case: a source that already carries the compose
file for the whole product gets no second file, only the block that points at it.

ALWAYS A PULL REQUEST, never a commit — even on a context repository onboarding committed straight
to while it was empty. The context repository is written by automation (`land_open_proposals`,
`record_fact`, the knowledge pipeline), and the shape of a product is what decides which code runs
on the operator's daemon: a person merges it (§6.4). Nothing here builds or runs what it drafts.

ONE SHAPE PER PRODUCT. A source whose own manifest already declares `preview:` refuses the product's
draft by name: two shapes is what a preview refuses (`preview/product.py::both_declared`), and a
proposal must not be the thing that creates them.
"""

from __future__ import annotations

import logging
import posixpath
import shutil
from pathlib import Path
from typing import Any

from openfactory import namespace
from openfactory.onboarding.infer import OBSERVED, Evidence, Proposal
from openfactory.onboarding.preview_infer import DRAFT_COMPOSE, PreviewProposal, infer_preview
from openfactory.onboarding.preview_propose import (
    BRANCH,
    Draft,
    Outcome,
    _first_error,
    draft,
    pr_body,
)

log = logging.getLogger("openfactory.onboarding.preview_product")

PRODUCT_YAML = namespace.PRODUCT_MANIFEST


def _short(repo: str) -> str:
    from openfactory.preview.product import short

    return short(repo)


def _cited(evidence: list[Evidence], side: str) -> list[Evidence]:
    """The same citations, as `<directory>/<path>` — a product's pull request cites files of
    several repositories, and `Dockerfile:3` alone would not say whose."""
    return [e.model_copy(update={"path": f"{side}/{e.path}"}) for e in evidence]


def combine(readings: list[tuple[str, PreviewProposal]], *, product: str,
            context: str) -> PreviewProposal:
    """ONE reading of the product from one reading per source (`(repository, reading)`, in the
    order `sources:` lists them): the sources' services side by side, every build context
    re-rooted from the context repository's `.openfactory/` to `../../<short name>/…`.

    What cannot be combined is ASKED, never guessed: a source with no Dockerfile, two sources
    needing a store of one name, two services of one name."""
    sides = {_short(repo): repo for repo, _ in readings}
    out = PreviewProposal(repo=context, name=product, case="nothing",
                          compose=Proposal(field="preview.compose"), sides=sides)
    taken: dict[str, str] = {}
    evidence: list[Evidence] = []
    for repo, found in readings:
        side = _short(repo)
        if found.case in ("draft", "nothing"):
            out.questions.append(
                f"`{repo}` has no Dockerfile, so nothing of it is drafted as a service — add one "
                f"to `{repo}` (or a service that builds it to `{DRAFT_COMPOSE}`), then propose "
                f"again.")
            continue
        if found.case == "compose":
            named = ", ".join(f"`{f}`" for f in found.compose.value or []) or "a compose file"
            out.questions.append(
                f"`{repo}` has its own compose file ({named}) beside other sources that need "
                f"drafting — which describes the product? Point `preview.compose` of "
                f"`{PRODUCT_YAML}` at it by hand, or draft the rest into it.")
            continue
        for svc in found.services:
            if svc.name in taken:
                if svc.kind == "store" and (svc.image == next(
                        (s.image for s in out.services if s.name == svc.name), None)):
                    continue  # one store of one image serves both
                out.questions.append(
                    f"`{taken[svc.name]}` and `{repo}` both need a service named `{svc.name}` — "
                    f"the first is drafted; name the other in `{DRAFT_COMPOSE}` yourself.")
                continue
            taken[svc.name] = repo
            moved = svc.model_copy(update={
                "evidence": _cited(svc.evidence, side), "quoted": _cited(svc.quoted, side),
                "environment": [e.model_copy(update={"evidence": _cited(e.evidence, side)})
                                for e in svc.environment]})
            if svc.kind == "build":
                inner = posixpath.normpath(posixpath.join(".openfactory", svc.context))
                moved = moved.model_copy(update={
                    "context": posixpath.normpath(posixpath.join("..", "..", side, inner))})
                evidence += moved.evidence
            out.services.append(moved)
        for field in ("expose", "data"):
            for name, p in getattr(found, field).items():
                if taken.get(name) == repo:
                    getattr(out, field)[name] = p.model_copy(update={
                        "evidence": _cited(p.evidence, side)})
        out.questions += [f"`{repo}`: {q}" for q in found.questions]
        out.flags += [f.model_copy(update={"path": f"{side}/{f.path}"}) for f in found.flags]
        out.registry += [r.model_copy(update={"path": f"{side}/{r.path}"})
                         for r in found.registry]
        out.notes += [f"`{repo}`: {n}" for n in found.notes]
        out.read += [f"{side}/{r}" for r in found.read]
        out.host_check = out.host_check or found.host_check
    if any(s.kind == "build" for s in out.services):
        out.case = "dockerfiles"
        out.compose = Proposal(field="preview.compose", value=[DRAFT_COMPOSE],
                               confidence=OBSERVED, evidence=evidence[:1])
    out.questions = list(dict.fromkeys(out.questions))
    return out


def product_block(block: dict[str, Any], *, repository: str = "") -> dict[str, Any]:
    """A drafted block in the shape `product.yaml` reads (`ProductPreview`): the compose file
    named in the context repository — or in `repository`, for S7 — and the fields as drafted."""
    compose = block.get("compose") or []
    out: dict[str, Any] = {"compose": ({"repository": repository, "paths": list(compose)}
                                       if repository else
                                       (compose[0] if len(compose) == 1 else list(compose)))}
    for key in ("expose", "data", "exclude", "dirs"):
        if block.get(key):
            out[key] = block[key]
    return out


def _compose_source(readings: list[tuple[str, PreviewProposal]]
                    ) -> tuple[str, PreviewProposal] | None:
    """The one source that already carries a compose file for the product (S7), when exactly one
    does and no other declares anything a draft would add."""
    composed = [(r, p) for r, p in readings if p.case == "compose" and not p.overrides]
    return composed[0] if len(composed) == 1 else None


def _dirs_asked(repo: str, found: PreviewProposal, checkout: Path,
                members: dict[str, str]) -> list[str]:
    """For S7: every `../<dir>` the source's compose file reaches that no member's short name
    answers — asked, because which repository it is cannot be read from the file."""
    from openfactory.preview.read import _read_inside, prescan

    side = _short(repo)
    texts = {}
    for rel in found.compose.value or []:
        text = _read_inside(str(checkout), str(checkout / rel))
        if text is not None:
            texts[posixpath.join(side, rel)] = text
    reached = prescan(texts).dirs
    return [f"`{repo}`'s compose file reaches `../{d}`, which is not the short name of any "
            f"repository of this product ({', '.join(f'`{m}`' for m in sorted(members))}) — "
            f"answer with `--set preview.dirs.{d}=<owner/name>`."
            for d in reached if d not in members]


def draft_product(readings: list[tuple[str, PreviewProposal]], *, product: str, context: str,
                  accept: bool = False, answers: dict[str, Any] | None = None,
                  checkouts: dict[str, Path] | None = None) -> tuple[PreviewProposal, Draft]:
    """The product's draft: what is written into the context repository, and the reading it is
    written from. Refused (`Draft.refusal`) when a source already declares its own `preview:`."""
    from pydantic import ValidationError

    from openfactory.contracts.product import ProductPreview

    declared = [repo for repo, p in readings if p.case == "declared"]
    if declared:
        return (PreviewProposal(repo=context, name=product, case="declared",
                                compose=Proposal(field="preview")),
                Draft(refusal=f"{' and '.join(f'`{r}`' for r in declared)} already "
                              f"{'declares' if len(declared) == 1 else 'declare'} `preview:` in "
                              f"{'its' if len(declared) == 1 else 'their'} own manifest — a "
                              f"product previewed from `{PRODUCT_YAML}` too would have two "
                              f"shapes, which a preview refuses. Remove it there first, or keep "
                              f"previewing that repository on its own."))
    answers = dict(answers or {})
    asked = dict(answers.get("preview") or {})
    dirs = asked.pop("dirs", None) or {}
    answers = {**answers, "preview": asked} if asked else {k: v for k, v in answers.items()
                                                           if k != "preview"}
    s7 = _compose_source(readings)
    if s7 is not None:
        repo, found = s7
        members = {_short(r): r for r, _ in readings}
        reading = found.model_copy(update={"sides": members})
        out = draft(reading, accept=accept, answers=answers)
        out = out.model_copy(update={"files": {}})   # the client's compose file is untouched
        asked_dirs = _dirs_asked(repo, found, (checkouts or {}).get(repo, Path(".")), members)
        if dirs:
            asked_dirs = []
        reading.questions = [*asked_dirs, *reading.questions]
        if out.block is not None:
            out.block = product_block({**out.block, "dirs": dirs}, repository=repo)
    else:
        reading = combine(readings, product=product, context=context)
        out = draft(reading, accept=accept, answers=answers)
        if out.block is not None:
            out.block = product_block({**out.block, "dirs": dirs})
    if out.block is not None:
        try:
            ProductPreview.model_validate(out.block)
        except ValidationError as exc:
            return reading, Draft(refusal=f"the `preview:` block would not validate in "
                                          f"`{PRODUCT_YAML}`: {_first_error(exc)}")
    return reading, out


def propose_product(project, *, accept: bool = False,
                    answers: dict[str, Any] | None = None) -> Outcome:
    """Draft how this product is previewed, from every source of its `product.yaml`, and propose
    it on `openfactory/preview` in its CONTEXT repository — one pull request, a person merges it."""
    from openfactory.adapters.forge.registry import clone_url_for
    from openfactory.onboarding.propose_manifest import (
        already_proposed,
        clone_for_proposal,
        default_branch,
        propose,
        scrub,
    )
    from openfactory.preview.product import read_docs
    from openfactory.product.onboard import (
        _context_token,
        context_clone_url,
        context_forge,
        plan,
    )

    cfg = getattr(project, "product", None)
    context = str(getattr(cfg, "docs_repo", "") or "")
    if not context:
        return Outcome(detail=(f"`{project.name}` has no context repository (no `product:` in "
                               f"its registry entry), so there is no product to preview — "
                               f"`openfactory preview propose {project.name}` drafts one "
                               f"repository's. Nothing was written."))
    raw = str(getattr(project, "repo_path", "") or "")
    if not ("://" in raw or raw.startswith("git@")):
        return Outcome(repo=context, detail=(
            "a product's preview is proposed through its forge, and this project is registered "
            "on the one-machine kind — write `.openfactory/preview.compose.yml` and the "
            f"`preview:` block of `{PRODUCT_YAML}` in the context repository yourself, and "
            "commit them. Nothing was written."))
    forge = context_forge(project)
    found = already_proposed(forge, context, BRANCH)
    if found is None:
        return Outcome(repo=context, detail=(
            f"could not ask `{context}` whether a preview is already proposed, so nothing was "
            f"proposed — asking again in a moment is safer than opening a second pull request."))
    if found:
        return Outcome(ok=True, repo=context, url=found, existed=True,
                       detail=f"a preview of the product is already proposed at {found} — "
                              f"merge or close it first.")
    try:
        url = context_clone_url(project, context)
    except Exception as exc:  # noqa: BLE001 — the message is the finding
        return Outcome(repo=context, detail=f"could not compose a clone URL for `{context}`: "
                                            f"{scrub(str(exc))[:200]}")
    checkout, why = clone_for_proposal(clone_url=url)
    if checkout is None:
        return Outcome(repo=context, detail=f"could not clone `{context}`: {why}")
    clones: dict[str, Path] = {}
    try:
        docs, error = read_docs(str(checkout))
        if docs is None:
            return Outcome(repo=context, detail=(
                f"`{context}` has no readable `{PRODUCT_YAML}` ({error}) — `openfactory product "
                f"init {project.name}` writes it; propose the preview once that is merged. "
                f"Nothing was written."))
        if docs.preview is not None or docs.preview_error:
            return Outcome(repo=context, detail=(
                f"`{PRODUCT_YAML}` already declares `preview:` — edit it in the repository; a "
                f"proposal never overwrites what a person wrote."))
        sources = [s for s in docs.sources if s]
        if not sources:
            return Outcome(repo=context, detail=(
                f"`{PRODUCT_YAML}` lists no `sources:`, so there is nothing to read a product's "
                f"preview from. Nothing was written."))
        token = _context_token(project)
        readings: list[tuple[str, PreviewProposal]] = []
        for repo in sources:
            try:
                there, why = clone_for_proposal(
                    clone_url=clone_url_for(project, repo, token=token))
            except Exception as exc:  # noqa: BLE001 — an unaddressable source is said
                there, why = None, scrub(str(exc))[:200]
            if there is None:
                return Outcome(repo=context, detail=f"could not clone `{repo}` to read it: {why}. "
                                                    f"Nothing was written.")
            clones[repo] = there
            readings.append((repo, infer_preview(there, name=_short(repo))))
        reading, out = draft_product(readings, product=project.name, context=context,
                                     accept=accept, answers=answers, checkouts=clones)
        if out.refusal:
            return Outcome(repo=context, detail=out.refusal + " Nothing was written.",
                           questions=reading.questions)
        if out.block is None and not out.files:
            return Outcome(ok=True, repo=context, nothing=True, questions=reading.questions,
                           detail=("nothing could be drafted for the product — "
                                   + (reading.questions[0] if reading.questions else
                                      "its repositories say nothing about how they run")
                                   + " Nothing was written."))
        clash = sorted(p for p in out.files if (checkout / p).exists())
        if clash:
            return Outcome(repo=context, detail=(
                f"{', '.join(f'`{p}`' for p in clash)} already exists in `{context}` — a "
                f"proposal never overwrites a file of yours. Nothing was written."))
        paths: list[str] = []
        comments_kept = True
        if out.block is not None:
            before = (checkout / PRODUCT_YAML).read_text(encoding="utf-8")
            onboarded = plan(project, checkout, preview=out.block)
            if onboarded.refusal:
                return Outcome(repo=context, detail=onboarded.refusal)
            (checkout / PRODUCT_YAML).write_text(onboarded.product_yaml, encoding="utf-8")
            paths.append(PRODUCT_YAML)
            header = {ln for ln in onboarded.product_yaml.splitlines() if ln.startswith("#")}
            comments_kept = not [ln for ln in before.splitlines()
                                 if ln.lstrip().startswith("#") and ln not in header]
        for rel, body in out.files.items():
            target = checkout / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
            paths.append(rel)
        body = pr_body(reading, out, project=project.name, repo=context,
                       comments_kept=comments_kept)
        base = default_branch(checkout)
        result = propose(
            checkout=checkout, manifest_path=paths[0], repo=context, clone_url=url, base=base,
            forge=forge, project_name=project.name, branch=BRANCH, extra_paths=paths[1:],
            title=f"OpenFactory: a preview of the product {project.name}", body=body,
            message=(f"chore: propose how OpenFactory previews the product {project.name}\n\n"
                     f"Drafted from its repositories' own files and never built or run; a "
                     f"person merges it."))
        return Outcome(ok=result.ok, repo=context, url=result.url, existed=result.existed,
                       base=base, body=body, questions=reading.questions,
                       detail=result.detail.replace("the manifest", "the preview"))
    finally:
        shutil.rmtree(checkout, ignore_errors=True)
        for there in clones.values():
            shutil.rmtree(there, ignore_errors=True)
