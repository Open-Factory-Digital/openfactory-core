"""Onboarding a product whose CONTEXT REPOSITORY ALREADY EXISTS (C-36, #77).

WHY THIS EXISTS. The factory requires a context repository of every project — and the second
external client (Deskline) arrived with one it had written long before meeting us, with its
own structure and its own numbering (`docs/decisoes/DEC-001-…`). That is the GOOD case, and it
was the one nothing covered.

The refusal half was already right: `product/config.py` keeps the module off, in a sentence, until
the docs repo carries `.openfactory/product.yaml`, and demands the declaration in BOTH directions so
a
source repo cannot redirect where its requirements are written. What did not exist was any step
that gets a client there. `openfactory init` converges the registry, the board and the SOURCE repo's
manifest; the string `product.yaml` did not appear once in the CLI. For Deskline that left
four files across three repositories to be hand-written, and an incomplete `sources:` produced a
refusal somebody had to decode — which is exactly where *no developer needed* leaks.

TWO RULES THIS MODULE IS BUILT AROUND.

**The context repository belongs to the CLIENT.** Everything here merges rather than replaces: an
existing `requirements_dir` is honoured, existing `sources:` are kept, unknown keys survive
untouched. A tool that tidies somebody else's repository on first contact has not onboarded them,
it has overwritten them.

**Say where the writing will go, and refuse a folder that already means something.** Pointed at a
directory holding `DEC-001-…`, `load_corpus` answers *zero requirements, next number 1* — no
error, and then `0001-…md` lands beside `DEC-001-…md` with two numbering schemes living quietly in
one folder. Absence of OUR convention is not absence of A convention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from openfactory import namespace

#: What `authoring` writes: `requirements/0007-editar-conciliado.md`. A file that does not match
#: is somebody else's document, whatever else it is.
_OURS = re.compile(r"^\d{4}-")

PRODUCT_YAML = namespace.PRODUCT_MANIFEST
DEFAULT_REQUIREMENTS_DIR = "requirements"


@dataclass
class OnboardPlan:
    """What onboarding this product would do, before anything is written."""

    docs_repo: str
    requirements_dir: str
    #: the full `.openfactory/product.yaml` to write — already merged with whatever was there
    product_yaml: str = ""
    #: nothing to do: the docs repo already says exactly this
    already_correct: bool = False
    #: non-empty means DO NOT WRITE, and this sentence says why in the operator's terms
    refusal: str = ""
    #: what a human still has to do elsewhere (the source repos' own manifests)
    todo: list[str] = field(default_factory=list)


def _existing(path: Path) -> dict:
    """What the declaration at `path` says today — `{}` when there is none, or none we can read.

    `path` comes from `namespace.resolve`, never from a join: the resolver is the ONE reader that
    knows a docs repository still on the directory's retired name HAS a declaration, and `plan`
    refuses that repository before this is ever asked."""
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def foreign_documents(docs_root: Path, requirements_dir: str) -> list[str]:
    """Markdown files in the requirements folder that this platform did not write.

    The check `load_corpus` cannot make: it reads OUR files and reports what it found, so a folder
    full of somebody else's numbered documents comes back empty and the next requirement lands on
    top of their scheme."""
    folder = docs_root / requirements_dir.strip("/")
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.glob("*.md") if not _OURS.match(p.name))


def plan(project, docs_root: Path, *, sources: list[str] | None = None) -> OnboardPlan:
    """What it would take for this product's context repo to satisfy the module's own gate.

    Reads a CLONE — never the live repo — so the caller decides whether anything is pushed."""
    cfg = getattr(project, "product", None)
    docs_repo = (getattr(cfg, "docs_repo", "") or "").strip()
    if not docs_repo:
        return OnboardPlan(
            docs_repo="", requirements_dir="",
            refusal=(f"{project.name} has no `product:` section in the registry, so there is no "
                     "context repository to onboard. Add `product: {docs_repo: owner/name}` to "
                     "its registry entry first — which repository holds a client's requirements "
                     "is an operator's decision, not something to infer."))

    try:
        # THE ONE READER DECIDES WHETHER THIS REPOSITORY DECLARES A PRODUCT. `exists()` on the
        # current name alone read a context repository still on the directory's retired name as
        # "nothing declared" and this plan wrote — or proposed as a pull request — a second
        # declaration beside the one it has, while `product/loader._read_docs_manifest` refused
        # that same repository by name (review, 2026-08-25). The refusal is the loader's own
        # sentence, and it is this plan's `refusal`: both callers stop on it and write nothing.
        declared = namespace.resolve(docs_root, PRODUCT_YAML, project=project.name)
    except namespace.RetiredNamespace as exc:
        return OnboardPlan(docs_repo=docs_repo, requirements_dir="", refusal=str(exc))
    current = _existing(declared)
    # THE CLIENT'S CHOICE WINS when they have already made one.
    requirements_dir = str(current.get("requirements_dir")
                           or getattr(cfg, "requirements_dir", "")
                           or DEFAULT_REQUIREMENTS_DIR).strip("/")

    strangers = foreign_documents(docs_root, requirements_dir)
    if strangers:
        shown = ", ".join(strangers[:3]) + ("…" if len(strangers) > 3 else "")
        return OnboardPlan(
            docs_repo=docs_repo, requirements_dir=requirements_dir,
            refusal=(f"`{requirements_dir}/` already holds documents this platform did not write "
                     f"({shown}). Requirements are numbered `0001-…md` and would land beside them, "
                     f"leaving two numbering schemes in one folder with nothing to tell them "
                     f"apart. Point `requirements_dir` at a folder of its own in "
                     f"{PRODUCT_YAML} — the rest of the repository is untouched either way."))

    wanted_sources = sorted({s for s in (sources or []) if s})
    merged_sources = sorted({*(current.get("sources") or []), *wanted_sources})
    # EVERYTHING ELSE THE CLIENT HAD SURVIVES. This is their repository; a key we do not
    # recognise is far likelier to be theirs on purpose than a mistake to clean up.
    merged = {**current, "product": project.name, "sources": merged_sources,
              "requirements_dir": requirements_dir}

    already = (current.get("product") == project.name
               and sorted(current.get("sources") or []) == merged_sources
               and str(current.get("requirements_dir") or "") == requirements_dir)

    todo = [
        f"{src}: add `docs_repo: {docs_repo}` to its `{namespace.MANIFEST}` — without it the "
        f"module still runs, but anyone cloning that repo has no way to find its requirements"
        for src in wanted_sources
    ]
    return OnboardPlan(
        docs_repo=docs_repo, requirements_dir=requirements_dir,
        product_yaml=_render(merged), already_correct=already, todo=todo,
    )


def _render(data: dict) -> str:
    """The file, with a header saying who wrote it and why it is here.

    A generated file in somebody else's repository owes them an explanation — otherwise the next
    person to open it has to guess whether it is safe to edit."""
    body = yaml.safe_dump(data, sort_keys=True, allow_unicode=True)
    return (
        f"# {namespace.PRODUCT_MANIFEST} — how OpenFactory finds this product's requirements.\n"
        "# Written by `openfactory product init`; safe to edit by hand.\n"
        "#\n"
        "# `sources:` must list EVERY repository implementing this product: the product role\n"
        "# reasons over the whole set, and one missing from it is invisible to it.\n"
        f"{body}"
    )


def proposal_branch(project_name: str) -> str:
    """The branch the onboarding proposal rides on: `openfactory/onboard-<project>`.

    ONE NAME PER PROJECT, recalculated rather than stored, so a retry after a partial failure
    finds its own earlier push and the open review request on it (`already_proposed` asks the
    forge before anything is pushed) instead of opening a second one. The job-branch rule
    (`JobRunner._job_branch`), applied to the one other branch this platform proposes in
    somebody else's repository."""
    return f"{namespace.BRANCH_PREFIX}/onboard-{project_name}"


def _context_token(project) -> str | None:
    """The credential for acts on the CONTEXT repository, in the order that works.

    Per-project forge credential first (an ADO project resolves AZURE_DEVOPS_PAT here). Then the
    TRACKER's, but only when both axes are the same vendor — a credential is scoped to a vendor,
    so same-vendor is the whole condition and naming one vendor here would be this pilot's
account leaking into the product (the operator, 2026-08-14: *"it matters that any change be
    aimed at the PRODUCT and not at my
    specific case"*). What the borrow
    buys, measured: a personal-account GitHub deployment is REQUIRED to hold a classic PAT for
    its board, and that PAT is the only credential that can create or reach a repository on a
    user account, where an App installation token cannot by any route. A MIXED deployment never
    borrows — a Jira token on a GitHub call is the 401-that-looks-like-revocation."""
    from openfactory.credentials import (
        deployment_forge_token,
        forge_token_for,
        tracker_token_for,
    )

    token = forge_token_for(project)
    if not token:
        kinds = {axis.kind for axis in (getattr(project, "forge", None),
                                        getattr(project, "tracker", None)) if axis is not None}
        if len(kinds) == 1:
            token = tracker_token_for(project)
    return token or deployment_forge_token(project)


def context_reachability(project, docs_repo: str) -> tuple[bool, str]:
    """Can this deployment actually READ `docs_repo` — with every credential that will try?

    DECLARED IS NOT REACHED, and the gap between them is silent for hours. The onboarding half
    (create, backfill, propose) resolves `_context_token`; the product role at RUNTIME resolves
    its own (`forge_token_for` or the App mint). On a personal GitHub account those are
    different credentials, so a repository created and backfilled by the PAT can sit outside
    the App installation's repository selection — every product question then answers "I cannot
    see the requirements", long after the onboarding said ✓ (measured 2026-08-13).

    Both routes are probed, deduped by the URL they resolve to (Azure signs its own PAT into
    the URL, so its two routes collapse into one). `ls-remote` because it is the cheapest thing
    that proves exactly what matters — that the credential can read this repository — and it is
    the same read every later clone begins with."""
    from openfactory.adapters.forge.registry import clone_url_for
    from openfactory.credentials import deployment_forge_token, forge_token_for
    from openfactory.onboarding.propose_manifest import _git, scrub

    routes: list[tuple[str, str]] = []
    for label, token in (("the onboarding credential", _context_token(project)),
                         ("the product role's runtime credential",
                          forge_token_for(project) or deployment_forge_token(project))):
        try:
            url = clone_url_for(project, docs_repo, token=token)
        except Exception as exc:  # noqa: BLE001 — an unaddressable repo is the answer, not a crash
            return False, f"{label} cannot even address it — {scrub(str(exc))[:200]}"
        if not any(url == seen for _, seen in routes):
            routes.append((label, url))

    for label, url in routes:
        rc, out = _git(["ls-remote", "--heads", url])
        if rc != 0:
            return False, f"{label} cannot read it — {scrub(out).strip()[-240:]}"
    return True, ""


def context_forge(project):
    """The forge this deployment drives, for acts on the CONTEXT repository.

    Built from the project because the context repository lives on the same vendor as its code
    — the registry has no separate axis for it, and a deployment whose code is on Azure Repos
    does not keep requirements on GitHub."""
    from openfactory.adapters.forge.registry import build_forge

    # The Azure row of build_forge ignores the caller's token either way, which is what keeps
    # a GitHub credential out of a dev.azure.com call (the review's blocker class).
    return build_forge(project, token=_context_token(project))


def context_clone_url(project, docs_repo: str) -> str:
    """The context repository's clone URL — the right host AND the right credential.

    Through `clone_url_for`, the one place where the adapter's own credential wins over the
    caller's; the pre-commit adversarial review (2026-08-12) caught both halves of the previous
    shape — a `github.com` literal, and the GitHub-only ambient token sent to dev.azure.com."""
    from openfactory.adapters.forge.registry import clone_url_for

    # the same resolution context_forge uses, for the same reasons — including the PAT borrow:
    # a repository just created on a personal account is reachable by the PAT that created it,
    # while the App installation may not even list it (adversarial review + pilot, 2026-08-13)
    return clone_url_for(project, docs_repo, token=_context_token(project))


def create_context_repository(project, name: str) -> tuple[str, bool]:
    """Create (or find) this project's context repository and RECORD it. `(repo, created)`.

    THE FORGE IS ASKED, NOT ASSUMED. `RepositoryCreatingForge` is a separate protocol precisely
    so a deployment whose forge cannot — or may not — create repositories says so here, in one
    sentence (a `ValueError` the caller renders), instead of failing halfway through an
    onboarding with a provider's own error.

    THE NAME IS DERIVED, not chosen by whoever typed the command: `<project>-context`, in the
    organisation/project the code already lives in. A repository in a client's organisation is
    not a place to accept free text from a caller.

    RECORDED, OR THE CREATION IS THEATRE: the product module stays off until the registry names
    the repository, so an onboarding that made one and did not write it down leaves the client
    with an empty repository and a role that still refuses to speak. Callers must RE-READ the
    project after this returns — the object they hold predates the record (the stale-object
    defect the v2 verification pass reproduced, 2026-08-10).

    Extracted from the CLI (2026-08-13) so the `onboard` verb can drive it; the CLI wraps it and
    keeps its exit codes."""
    from openfactory.adapters.forge.base import RepositoryCreatingForge
    from openfactory.registry import ProjectRegistry

    forge = context_forge(project)
    if not isinstance(forge, RepositoryCreatingForge):
        raise ValueError(
            f"this deployment's forge ({type(forge).__name__}) cannot create a repository, so "
            f"make the context repository by hand and declare it: "
            f"`openfactory product declare {getattr(project, 'name', '<project>')} "
            f"<owner/repo>`.")
    try:
        repo, created = forge.create_repository(
            name=f"{name}-context",
            description=f"Requirements and context for {name}, read by OpenFactory.")
    except (RuntimeError, ValueError) as exc:
        # A CREDENTIAL THAT MAY NOT CREATE IS THE NORMAL ENTERPRISE SHAPE, not an exception:
        # the operator, on the next client (2026-08-14) — *"I will have to create this by hand
        # in DevOps… we will not be able to do the creation via az cli"*. Whatever
        # the vendor said stays (it is the diagnosis), but a refusal that ends there leaves
        # somebody holding a provider's 403 and no way forward. The product-layer fallback is
        # stated HERE and exactly once — adapters that already name it are not doubled.
        if "product declare" in str(exc):
            raise
        raise type(exc)(
            f"{exc}\n"
            f"  OpenFactory requires a context repository, and this credential could not make "
            f"one. Create it yourself — the portal, your provisioning process, however your "
            f"company does it — and declare it: `openfactory product declare "
            f"{getattr(project, 'name', '<project>')} <repo>`, then re-run. Nothing else about "
            f"the onboarding changes; a declared repository is USED, never replaced."
        ) from exc
    ProjectRegistry().set_docs_repo(name, repo)
    return repo, created
