"""A preview of a PRODUCT of several repositories — its shape, its layout, and the repositories it
may never reach (ADR-0050 D3, D5; the design on #265, §2.2, §3.1, §6.3–§6.4, §8).

THE SHAPE LIVES IN THE CONTEXT REPOSITORY. A product of a front end and a back end has no one
repository whose manifest could say how the whole runs, so `.openfactory/product.yaml` says it:
`preview:` names a compose file — in the context repository itself, or in one of `sources:` — and
the four fields a repository's own block carries. It is read like every shape: from the BASE
branch, from the unit's own fresh checkout of it, never through a link out of that checkout.

THE LAYOUT MAKES `../web` TRUE. Every repository the unit needs is checked out side by side under
its short name — `<workdir>/base/{web, api, shop-context}` — so a compose file's `../web` names the
`web` repository exactly as it does on a developer's laptop. A directory that is not a repository's
short name is named in `dirs:`.

THE BOUNDARY IS `sources:`, AND IT IS CHECKED WHERE EVERY PATH IS DECIDED. The context repository
is bot-written (§6.4): a line in it must not be able to point a preview at a repository the
product does not own. So every repository a preview may check out is a MEMBER — the context
repository itself, or one listed in the `sources:` the same file declares, which the product module
has already reconciled with the registry — and nothing else is checked out, built or mounted:

- `compose.repository` and every `dirs:` value must be a member;
- a `../<dir>` in the compose files that names no member is refused by name, before anything
  outside the layout is cloned, and again when the files are read;
- the plan verifies that every tree on disk is the member its directory names.

ONE SHAPE PER PROJECT. A product whose `product.yaml` declares `preview:` AND a source whose own
manifest declares one is refused, naming both: the posture `resolve_product_link` takes on two
declarations that disagree — off, and said — never a guess at which one was meant.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable

import yaml
from pydantic import BaseModel, ConfigDict

from openfactory import namespace
from openfactory.contracts.manifest import PreviewConfig
from openfactory.contracts.product import ProductDocs, ProductPreview
from openfactory.preview.plan import Layout, Refused
from openfactory.preview.read import PRODUCT_REMEDY, _read_inside, prescan
from openfactory.product.config import normalize_repo, repo_match

#: `.openfactory/product.yaml`, at the root of the context repository
PRODUCT_YAML = namespace.PRODUCT_MANIFEST


def short(repo: str) -> str:
    """The directory a repository is checked out under when nothing names another: its short
    name, `acme/web` → `web` — the same spelling a single repository's layout uses."""
    last = (repo or "").rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]+", "-", last).strip(".-")


def member(repo: str, members: Iterable[str]) -> str:
    """The spelling in `members` that names `repo`, or "" when none does — matched the way the
    product module matches its own membership (`repo_match`), so a bare Azure name and its
    qualified spelling are one repository and two different owners are two."""
    for m in members:
        if repo_match(repo, m):
            return m
    return ""


def read_docs(root: str) -> tuple[ProductDocs | None, str]:
    """`.openfactory/product.yaml` from a CHECKOUT of the context repository — `(docs, error)`.

    Read only when it is a file inside `root` once every link is followed: the context repository
    is written by automation, and a `product.yaml` that is a link to a file of the worker's is not
    the repository's file. Parsed by the product module's own parser, so a preview and the module
    never disagree about what the file says."""
    from openfactory.product.loader import parse_docs_manifest

    text = _read_inside(root, posixpath.join(root, PRODUCT_YAML))
    if text is None:
        return None, (f"`{PRODUCT_YAML}` is not a file of the context repository's base branch")
    return parse_docs_manifest(text)


class ProductShape(BaseModel):
    """How one product is previewed: the block, and the directory every member is checked out
    under. `members` is the WHOLE set a preview of it may ever check out — the context repository
    and its `sources:` — keyed by directory."""

    model_config = ConfigDict(frozen=True)

    context: str
    context_dir: str
    #: the directory of the repository the compose file lives in
    shape_dir: str
    #: directory → repository, for every member
    members: dict[str, str]
    preview: ProductPreview

    def dir_of(self, repo: str) -> str:
        """The directory `repo` is checked out under, or "" when it is not a member."""
        return next((d for d, r in self.members.items() if repo_match(repo, r)), "")

    def config(self) -> PreviewConfig:
        """The block as the assembler reads every shape: compose files, what is opened, how data
        is made, what is left out — the paths relative to the compose file's own repository."""
        p = self.preview
        return PreviewConfig(compose=list(p.compose.paths), expose=dict(p.expose),
                             data=dict(p.data), exclude=list(p.exclude))


def _named(repos: Iterable[str]) -> str:
    return ", ".join(f"`{r}`" for r in repos) or "none"


def shape_of(docs: ProductDocs, *, context: str) -> ProductShape | Refused | None:
    """The product's preview shape from its declaration — None when it declares no `preview:`,
    or every reason it cannot be used. `context` is the context repository as the registry
    authorizes it (the product module's `docs_repo`)."""
    if docs.preview_error:
        return Refused(reasons=(docs.preview_error + ".",))
    pp = docs.preview
    if pp is None:
        return None
    sources = [s for s in docs.sources if normalize_repo(s)]
    refused: list[str] = []
    repo = pp.compose.repository.strip()
    if repo and not member(repo, sources):
        refused.append(f"`preview.compose.repository` in `{PRODUCT_YAML}` names `{repo}`, which "
                       f"is not a repository of this product ({_named(sources)}) — a preview "
                       f"reads its shape from a repository of the product, or from the context "
                       f"repository itself (leave `repository` out).")
    named: dict[str, str] = {}
    for d, target in pp.dirs.items():
        found = member(target, [*sources, context])
        if not found:
            refused.append(f"`preview.dirs` in `{PRODUCT_YAML}` maps `{d}` to `{target}`, which "
                           f"is not a repository of this product ({_named(sources)}).")
            continue
        if found in named.values():
            refused.append(f"`preview.dirs` in `{PRODUCT_YAML}` gives `{found}` two directory "
                           f"names — one repository is checked out once.")
            continue
        named[d] = found
    members: dict[str, str] = {}
    for repo_ in [context, *sources]:
        if any(repo_match(repo_, m) for m in members.values()):
            continue
        d = next((k for k, v in named.items() if v == repo_), "") or short(repo_)
        if d in members:
            refused.append(f"`{members[d]}` and `{repo_}` would both be checked out as `{d}` — "
                           f"name one of them in `preview.dirs` of `{PRODUCT_YAML}`.")
            continue
        members[d] = repo_
    if refused:
        return Refused(reasons=tuple(refused))
    holder = member(repo, sources) if repo else context
    shape_dir = next(d for d, r in members.items() if repo_match(r, holder))
    context_dir = next(d for d, r in members.items() if repo_match(r, context))
    return ProductShape(context=context, context_dir=context_dir, shape_dir=shape_dir,
                        members=members, preview=pp)


def reached(shape: ProductShape, root: str) -> tuple[str, ...] | Refused:
    """The directories the product's compose files reach — `../api` → `api` — read from the base
    checkout of the repository they live in (`root`), before any other repository is cloned. A
    `../<dir>` that names no member is refused BY NAME, so nothing outside `sources:` is ever
    checked out on a guess; `read.shape` checks the same again once every tree is on disk."""
    texts: dict[str, str] = {}
    for f in shape.preview.compose.paths:
        text = _read_inside(root, posixpath.join(root, f))
        if text is None:
            return Refused(reasons=(f"`{f}` is not a file of `{shape.members[shape.shape_dir]}`'s "
                                    f"base branch — `preview.compose` in `{PRODUCT_YAML}` names "
                                    f"it, and a preview reads the base branch's files only.",))
        texts[posixpath.normpath(posixpath.join(shape.shape_dir, f))] = text
    found = prescan(texts, layout_dirs=shape.members, of="this product", remedy=PRODUCT_REMEDY)
    if found.refused:
        return Refused(reasons=found.refused)
    return tuple(found.dirs)


def strangers(layout: Layout, shape: ProductShape) -> list[str]:
    """Every tree on disk that is NOT the member its directory names — the plan's last word on
    the boundary, whatever put the tree there."""
    out = []
    for d, tree in layout.trees.items():
        expected = shape.members.get(d)
        if not expected or not repo_match(tree.repo, expected):
            out.append(f"`{tree.repo}` is checked out as `{d}`, which is not a repository of this "
                       f"product under that name ({_named(shape.members.values())}) — nothing of "
                       f"it is built or mounted.")
    return out


def _declares_preview(root: str, rel: str) -> bool:
    text = _read_inside(root, posixpath.join(root, rel))
    if text is None:
        return False
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    return isinstance(data, dict) and data.get("preview") is not None


def both_declared(layout: Layout, *, manifests: Iterable[str]) -> str:
    """Why this product has TWO shapes — its `product.yaml` and a source's own manifest both
    declare `preview:` — or "". Every source tree of the layout is read at its base; the context
    repository's own manifest is not a source's."""
    rels = list(dict.fromkeys(m for m in manifests if m))
    twice = sorted(tree.repo for d, tree in layout.trees.items()
                   if d != layout.context
                   and any(_declares_preview(layout.root(d, "base"), rel) for rel in rels))
    if not twice:
        return ""
    return (f"two shapes: `{PRODUCT_YAML}` and {' and '.join(f'`{r}`' for r in twice)}'s "
            f"manifest both declare `preview:` — keep one. A product of several repositories is "
            f"previewed from `{PRODUCT_YAML}`; remove the block from the "
            f"{'manifest' if len(twice) == 1 else 'manifests'}, or the one in `{PRODUCT_YAML}`.")
