"""Assembling the product context: fetch the two declarations, reconcile them, load the corpus.

Everything here is I/O around the pure decision in `config.py`. It keeps that split deliberately:
the function that decides whether an agent may write into a client's requirements is testable
without a network, and this module is only the plumbing that feeds it.

NOTHING HERE RAISES. The product module is one surface of a factory that must keep running: a
documentation repo that is unreachable, a `product.yaml` with a typo, a requirements folder somebody
renamed — each turns the module OFF with a sentence saying which file to fix, and the rest of the
factory never notices. An exception escaping into the Slack listener would take a project's whole
channel down for a YAML typo.
"""

from __future__ import annotations

import logging

import yaml
from pydantic import BaseModel, Field, ValidationError

from openfactory import namespace
from openfactory.contracts.product import ProductDocs
from openfactory.product.config import ProductLink, resolve_product_link
from openfactory.product.corpus import Corpus, load_corpus
from openfactory.product.domain import Domain, load_domain

log = logging.getLogger("openfactory.product")

#: `.openfactory/product.yaml` at the root of the documentation repo. A documentation repository
#: still on the directory's retired name is refused by name (see `openfactory/namespace.py`), and
#: the refusal is this module's OFF reason — never a silent "missing".
DOCS_MANIFEST = namespace.PRODUCT_MANIFEST

#: cache key suffix for a project's documentation repo. The cache is keyed by an arbitrary name, so
#: one project can keep its code and its documentation checked out side by side.
DOCS_CACHE_SUFFIX = "--docs"

#: Where learned facts and vocabulary live, beside the requirements but never mixed with them: one
#: folder holds what we DECIDED, the other what we were TOLD.
DOMAIN_DIRNAME = "domain"


class ProductContext(BaseModel):
    """Everything the product role needs to reason, or the reason it cannot.

    `available` is the single thing callers branch on; `link.reason` is what they SHOW. A module
    that is off without saying why is indistinguishable from one nobody enabled."""

    link: ProductLink
    corpus: Corpus = Field(default_factory=Corpus)
    #: what the role has LEARNED about the business — facts and vocabulary, never promises
    domain: Domain = Field(default_factory=Domain)
    docs_path: str = ""
    docs_commit: str = ""
    #: where the requirements live inside the docs repo — carried so a writer never has to re-read
    #: the manifest to find out where to put a file
    requirements_dir: str = "requirements"

    @property
    def available(self) -> bool:
        return self.link.active

    @property
    def reason(self) -> str:
        return self.link.reason

    def health(self) -> str:
        """One line for a human — the panel, a log, an answer in Slack.

        THE WARNINGS BELONG HERE, and until now they belonged nowhere. `ProductLink.warnings` was
        appended to in three places and read by NOTHING: a project whose source repo never declares
        where its requirements live, or whose declared admin is not a member of that repo, produced
        a warning that lived in memory and was garbage-collected. Every place that computes one
        believes somebody will see it; nobody did.

        Appended to the READY line rather than turned into an error, because none of them stops the
        module — that is what makes them warnings, and what made them easy to leave unread.
        """
        if not self.available:
            return f"product module unavailable: {self.reason}"
        out = (f"product module ready on {self.link.docs_repo} — {self.corpus.summary()}"
               + (f" · glossário: {self.domain.summary()}" if self.domain.facts else ""))
        warnings = list(getattr(self.link, "warnings", None) or [])
        if warnings:
            out += f" · {len(warnings)} aviso(s) de configuração: " + " | ".join(warnings)
        return out


def _read_docs_manifest(path) -> tuple[ProductDocs | None, str]:
    """`(docs, error)` — never an exception. A malformed manifest must produce a message naming the
    file, not a traceback in a Slack listener."""
    try:
        manifest = namespace.resolve(path, DOCS_MANIFEST)
    except namespace.RetiredNamespace as exc:
        # THE RETIRED NAME IS A REASON, NOT A MISSING FILE. Folding it into "missing" would tell
        # the operator to create a file beside one that already exists under the old name.
        return None, str(exc)
    if not manifest.is_file():
        return None, f"{DOCS_MANIFEST} is missing from the repository root"
    try:
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return None, f"{DOCS_MANIFEST} is not valid YAML: {str(exc)[:200]}"
    except OSError as exc:
        return None, f"{DOCS_MANIFEST} could not be read: {exc}"
    if not isinstance(data, dict):
        return None, f"{DOCS_MANIFEST} must be a mapping, not {type(data).__name__}"
    try:
        return ProductDocs(**data), ""
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", ())) or "?"
        return None, f"{DOCS_MANIFEST} is invalid at {field!r}: {first.get('msg', 'unknown')}"


def _source_claim(project) -> str | None:
    """The `docs_repo:` the source repo declares, or None. Best-effort by design: the registry is
    the authority, so a manifest we cannot read costs a warning, never the module."""
    try:
        from openfactory.loader import load_manifest

        return getattr(load_manifest(project), "docs_repo", None)
    except Exception as exc:  # noqa: BLE001 — a claim is optional; the registry authorizes
        log.debug("product: no source claim for %s (%s)", getattr(project, "name", "?"), exc)
        return None


def _head(path) -> str:
    import subprocess

    try:
        p = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=15, check=False)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception as exc:  # noqa: BLE001 — no HEAD is survivable; a silent one is not
        # The HEAD is what staleness is judged against. Without it the corpus looks permanently
        # fresh, which is the failure mode that reads as "everything is fine" forever.
        log.warning("could not read HEAD of %s (%s) — the corpus cannot be checked for staleness",
                    path, exc)
        return ""


def load_product_context(
    project,
    *,
    token: str | None = None,
    cache=None,
    source_claim: str | None = None,
) -> ProductContext:
    """The product context for one project — or an inactive one carrying why.

    `source_claim` overrides reading the source manifest (the caller often already has it, and a
    second checkout to re-read one line is exactly the waste this module is trying to avoid)."""
    cfg = getattr(project, "product", None)
    if cfg is None or not getattr(cfg, "enabled", True):
        # the common case by far: no network, no clone, no cost. Most projects never enable this.
        return ProductContext(link=resolve_product_link(project=project))

    claim = source_claim if source_claim is not None else _source_claim(project)

    try:
        # THROUGH THE FORGE REGISTRY, NOT `entrypoint.clone_url`. That helper spells `github.com`
        # as a literal, so on an Azure Repos deployment this cloned
        # `https://github.com/fx-dsk-context.git` — a 404, or worse somebody else's repository of
        # that name — and every product question for that client was answered "I cannot see the
        # requirements" with the host it looked on named nowhere. `clone_url_for` asks the project's
        # own forge, which also settles the credential: it hands the ADO adapter its own PAT rather
        # than the GitHub token every caller on this path carries (see the registry's Azure row).
        from openfactory.adapters.forge.registry import clone_url_for
        from openfactory.runtime.repo_cache import RepoCache

        cache = cache or RepoCache()
        # THE BRANCH THE REGISTRY NAMES, or none — `cfg.docs_branch` reads `main` whether a client
        # declared it or left the field alone, and onboarding keeps a reused context repository on
        # ITS own default branch. A `master` context repo was cloned at a branch it does not have.
        path = cache.sync(f"{project.name}{DOCS_CACHE_SUFFIX}",
                          clone_url_for(project, cfg.docs_repo, token=token),
                          cfg.declared_docs_branch)
    except Exception as exc:  # noqa: BLE001 — a checkout problem turns the module off, never up
        return ProductContext(link=resolve_product_link(
            project=project, manifest_docs_repo=claim, docs=None,
            docs_error=f"the documentation repo could not be checked out ({str(exc)[:160]})"))

    if path is None:
        return ProductContext(link=resolve_product_link(
            project=project, manifest_docs_repo=claim, docs=None,
            docs_error=f"could not check out {cfg.docs_repo} (branch {cfg.docs_branch!r})"))

    docs, error = _read_docs_manifest(path)
    link = resolve_product_link(project=project, manifest_docs_repo=claim,
                                docs=docs, docs_error=error)
    if not link.active or docs is None:
        return ProductContext(link=link, docs_path=str(path), docs_commit=_head(path))

    corpus = load_corpus(path / docs.requirements_dir)
    domain = load_domain(path / DOMAIN_DIRNAME)
    return ProductContext(link=link, corpus=corpus, domain=domain, docs_path=str(path),
                          docs_commit=_head(path), requirements_dir=docs.requirements_dir)
