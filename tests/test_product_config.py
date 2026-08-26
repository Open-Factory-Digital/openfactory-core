"""The reconciliation that decides whether the product module may run — ADR-0019 §8.

This is the function that decides whether an agent may write into a client's requirements, so it is
tested exhaustively rather than representatively. The failure it exists to prevent is not a crash:
it is a product role authoring confident, well-formatted requirements into the wrong product's
repository, with nobody seeing a stack trace.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.product import ProductConfig, ProductDocs
from openfactory.contracts.project import Project
from openfactory.product import normalize_repo, resolve_product_link

DOCS = "AcmeCorp/acme-books-documentation"
SRC = "AcmeCorp/acme-books"


def _project(**kw):
    cfg = kw.pop("product", {"docs_repo": DOCS})
    return Project(
        name=kw.pop("name", "books"),
        repo_path="/work/books",
        tracker={"kind": "github", "repo": kw.pop("repo", SRC)},
        product=ProductConfig(**cfg) if cfg is not None else None,
        **kw,
    )


def _docs(**kw) -> ProductDocs:
    return ProductDocs(product=kw.pop("product", "books"),
                       sources=kw.pop("sources", [SRC]), **kw)


def _link(**kw):
    return resolve_product_link(project=kw.pop("project", _project()),
                                docs=kw.pop("docs", _docs()), **kw)


# ── repo references ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("written", [
    "AcmeCorp/acme-books",
    "acmecorp/ACME-BOOKS",
    "git@github.com:AcmeCorp/acme-books.git",
    "https://github.com/AcmeCorp/acme-books",
    "https://github.com/AcmeCorp/acme-books.git",
    "ssh://git@github.com/AcmeCorp/acme-books.git",
    "  AcmeCorp/acme-books/  ",
])
def test_a_repo_is_the_same_repo_however_it_was_written(written):
    """People paste clone URLs into config files. A link that failed to match because one side said
    `git@github.com:...` would surface as a MEMBERSHIP INCONSISTENCY — the most alarming failure
    this module has — over a purely cosmetic difference."""
    assert normalize_repo(written) == "acmecorp/acme-books"


@pytest.mark.parametrize("junk", [
    "", None, "   ",
    "one/two/three/four",     # deeper than any provider addresses a repository
    "git@github.com",         # a real typo out of a client's `.sdlc/project.yaml`
    "a repo with spaces",
    "..",
])
def test_an_unusable_reference_is_empty_not_a_guess(junk):
    assert normalize_repo(junk) == ""


def test_a_bare_repository_name_is_a_reference_because_azure_repos_writes_it_that_way():
    """`not-a-repo` USED TO BE THIS SUITE'S EXAMPLE OF JUNK, and that was GitHub's shape wearing
    the name of a general rule. Azure Repos nests `organization/project/repository` and puts the
    first two in the provider's `options`, so every Azure row in a registry names its repository
    with ONE segment — `forge: {repo: fx-ado, options: {organization: …, project: …}}`.

    Rejecting it emptied `authorized`, which turns the whole module off, and emptied the
    `sources:` membership set, which is worse: the check that stops one client's requirements
    being written from another's code then compares against nothing and passes."""
    assert normalize_repo("fx-dsk-context") == "fx-dsk-context"


# ── enablement ──────────────────────────────────────────────────────────────────────────────────

def test_no_product_section_means_the_module_simply_is_not_there():
    """Opt-in per client: a project without the section does not have the module, and that is not
    an error — most projects will never enable it."""
    link = _link(project=_project(product=None))
    assert link.active is False and link.kind == "off"
    assert "not enabled" in link.reason


def test_the_module_can_be_switched_off_without_losing_its_configuration():
    link = _link(project=_project(product={"docs_repo": DOCS, "enabled": False}))
    assert link.active is False and link.kind == "off"


def test_enabled_with_an_unusable_docs_repo_is_a_config_error_not_a_silent_off():
    """`off` and `broken` need different humans. Reporting both as "not enabled" is how a
    misconfiguration survives for weeks."""
    # deeper than any provider addresses a repository — a bare `nonsense` is now a legitimate
    # Azure Repos reference, so the example had to become one no provider could mean
    link = _link(project=_project(product={"docs_repo": "one/two/three/four"}))
    assert link.active is False and link.kind == "config"
    assert "docs_repo" in link.reason


# ── the claim may confirm, never redirect ───────────────────────────────────────────────────────

def test_a_source_repo_cannot_redirect_where_its_requirements_are_written():
    """THE SECURITY PROPERTY. Anyone with write access to a source repo could otherwise point the
    product role at any repository by editing one line."""
    link = _link(manifest_docs_repo="attacker/elsewhere")
    assert link.active is False and link.kind == "conflict"
    assert "attacker/elsewhere" in link.reason and "authorizes" in link.reason


def test_a_matching_claim_activates_with_no_warnings():
    link = _link(manifest_docs_repo=f"git@github.com:{DOCS}.git")
    assert link.active is True and link.kind == "ok"
    assert link.docs_repo == DOCS.lower()
    assert link.warnings == []


def test_no_claim_still_runs_but_says_discoverability_was_lost():
    """The registry authorizes, so the module works — but anyone cloning the source repo now has no
    way to find its requirements, which is the whole point of the source→docs pointer."""
    link = _link(manifest_docs_repo=None)
    assert link.active is True
    assert any("no way to find its requirements" in w for w in link.warnings)


def test_a_malformed_claim_is_ignored_with_a_warning_not_treated_as_a_conflict():
    """A typo in the client's file must not take the module offline: the registry already said
    which repo is authorized, and a mangled claim adds no information either way."""
    link = _link(manifest_docs_repo="git@github.com")
    assert link.active is True
    assert any("unreadable `docs_repo`" in w for w in link.warnings)


# ── the documentation repo must agree ───────────────────────────────────────────────────────────

def test_an_unreadable_docs_manifest_turns_the_module_off_rather_than_assuming():
    link = _link(docs=None, docs_error="404")
    assert link.active is False and link.kind == "config"
    assert "product.yaml" in link.reason and "404" in link.reason


def test_a_docs_repo_for_a_DIFFERENT_product_is_refused_as_an_isolation_breach():
    link = _link(docs=_docs(product="fink"))
    assert link.active is False and link.kind == "conflict"
    assert "fink" in link.reason and "isolation" in link.reason


def test_a_source_missing_from_the_membership_set_is_the_inconsistency_the_design_exists_to_catch():
    """Authorized to use the corpus, but not listed as part of it. A one-way pointer would have
    failed silently here; two independent declarations make the disagreement detectable."""
    link = _link(docs=_docs(sources=["AcmeCorp/some-other-service"]))
    assert link.active is False and link.kind == "conflict"
    assert "sources:" in link.reason
    assert "acmecorp/some-other-service" in link.reason  # says what it DOES list


def test_membership_matches_across_notations():
    link = _link(docs=_docs(sources=[f"https://github.com/{SRC}.git"]))
    assert link.active is True


def test_one_of_several_member_repos_is_enough_because_a_product_spans_N():
    link = _link(docs=_docs(sources=["AcmeCorp/acme-front", SRC, "AcmeCorp/acme-jobs"]))
    assert link.active is True


def test_the_product_name_comparison_ignores_case_and_padding():
    link = _link(project=_project(name=" Books "), docs=_docs(product="books"))
    assert link.active is True


# ── the reason is always present ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case", [
    {"project": _project(product=None)},
    {"project": _project(product={"docs_repo": ""})},
    {"docs": None},
    {"docs": _docs(product="fink")},
    {"docs": _docs(sources=[])},
    {"manifest_docs_repo": "someone/else"},
])
def test_every_inactive_verdict_explains_itself(case):
    """An inactive module that cannot say WHY is indistinguishable from one nobody enabled."""
    link = _link(**case)
    assert link.active is False
    assert len(link.reason) > 30, link.reason


# ── the two declarations are real fields, not prose in an ADR ───────────────────────────────────

def test_a_source_repo_can_actually_declare_its_docs_repo():
    """`.sdlc/project.yaml` forbids unknown keys (a typo must fail loud, D-1/D-3), so without the
    field a client declaring `docs_repo:` would not merely be ignored — its manifest would fail to
    load and every job on that repo would stop."""
    from openfactory.contracts.manifest import Manifest

    assert Manifest(docs_repo=DOCS).docs_repo == DOCS
    assert Manifest().docs_repo is None


def test_the_claim_from_a_real_manifest_reconciles_against_the_registry():
    from openfactory.contracts.manifest import Manifest

    m = Manifest(docs_repo=f"https://github.com/{DOCS}.git")
    link = resolve_product_link(project=_project(), manifest_docs_repo=m.docs_repo, docs=_docs())
    assert link.active is True and link.warnings == []
