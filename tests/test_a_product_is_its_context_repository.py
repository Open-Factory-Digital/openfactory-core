"""Two registry projects of one product are one product (ADR-0051, "The boundary is the product").

The product role, its conversations, its memory and its semaphore are keyed by what this returns.
The failure it prevents is quiet: two registry projects pointing at one context repository keyed
apart get two minds and two locks, and both mint the same requirement number into one corpus.
"""

from __future__ import annotations

import re

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product.key import product_key, product_slug

DOCS = "AcmeCorp/acme-books-documentation"


def _project(name: str, docs_repo: str | None = DOCS) -> Project:
    return Project(
        name=name,
        repo_path=f"/work/{name}",
        tracker={"kind": "github", "repo": f"AcmeCorp/{name}"},
        product=ProductConfig(docs_repo=docs_repo) if docs_repo is not None else None,
    )


def test_two_registry_projects_of_one_context_repository_are_one_product():
    front, back = _project("books-web"), _project("books-api")
    assert product_key(front) == product_key(back) == "repo:acmecorp/acme-books-documentation"


def test_the_coordinate_is_normalised_so_a_spelling_does_not_split_a_product():
    pasted = _project("books-api", "https://github.com/AcmeCorp/acme-books-documentation.git")
    assert product_key(pasted) == product_key(_project("books-web"))


def test_different_context_repositories_are_different_products():
    assert product_key(_project("a", "AcmeCorp/one")) != product_key(_project("b", "AcmeCorp/two"))


def test_a_project_without_a_product_link_is_a_product_of_one():
    assert product_key(_project("books", None)) == "project:books"
    assert product_key(_project("books", None)) != product_key(_project("shop", None))


def test_an_unreadable_docs_repo_does_not_merge_projects_into_one_empty_product():
    # `normalize_repo` answers "" for a coordinate no provider addresses; "" must not become a key
    # two unrelated projects share.
    bad = "a/b/c/d/e"
    assert product_key(_project("one", bad)) == "project:one"
    assert product_key(_project("two", bad)) == "project:two"


def test_a_project_named_like_a_repository_is_not_that_repository():
    named = _project("acmecorp/acme-books-documentation", None)
    assert product_key(named) != product_key(_project("books-web"))


def test_the_slug_is_safe_for_a_file_name_and_unique_per_exact_key():
    keys = ["repo:acme/docs", "project:acme-docs", "repo:Acme/Docs", "project:a b"]
    slugs = [product_slug(k) for k in keys]
    assert len(set(slugs)) == len(keys)
    assert all(re.fullmatch(r"[a-z0-9-]+", s) for s in slugs)
    assert product_slug("repo:acme/docs") == product_slug("repo:acme/docs")
