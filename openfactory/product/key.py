"""The product a registry project belongs to: the one key the product role, its conversations, its
memory and its semaphore share (ADR-0051, "The boundary is the product").

The product is the context repository ADR-0019 §8 already makes people declare: the registry's
`product.docs_repo`, normalised by `config.normalize_repo`. Two registry projects that point at one
context repository are ONE product. They share one role, one memory and one semaphore, so a
requirement number minted from one is seen by the other before it mints its own.

A registry project with no `product:` section, or whose `docs_repo` does not normalise, is a product
of one: its own name. The registry is the authorisation; a source repository's `docs_repo:` claim
confirms it and never redirects it, so the claim is not read here.

The two spellings cannot collide. A repository key always carries `repo:` and a project key
`project:`, so a project named like a repository is still its own product.
"""

from __future__ import annotations

import hashlib
import re

from openfactory.contracts.project import Project
from openfactory.product.config import normalize_repo

#: How much of the readable part a slug keeps; the digest after it is what makes it unique.
_SLUG_READABLE = 48


def product_key(project: Project) -> str:
    """`repo:<coordinate>` for a project linked to a context repository, else `project:<name>`."""
    link = project.product
    repo = normalize_repo(link.docs_repo) if link is not None else ""
    return f"repo:{repo}" if repo else f"project:{project.name}"


def product_slug(key: str) -> str:
    """The key in a spelling a file name, a lock name or a workflow id can carry.

    Every run of characters outside `[a-z0-9]` becomes one `-`, and a short digest of the EXACT key
    follows, so `repo:acme/docs` and `project:acme-docs`, which read alike, never share a lock."""
    readable = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")[:_SLUG_READABLE].rstrip("-")
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return f"{readable or 'product'}-{digest}"
