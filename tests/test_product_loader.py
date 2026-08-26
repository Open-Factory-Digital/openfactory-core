"""Assembling the product context from two real git repositories.

Real repos rather than fakes: the thing being tested is that a documentation repository laid out the
way a client's actually is produces a usable context — and the failures worth catching (a missing
manifest, a renamed folder, a YAML typo) are all filesystem-shaped.

The contract every one of these asserts: **nothing raises**. The product module is one surface of a
factory that must keep running, and an exception escaping into a Slack listener would take a
project's whole channel down over a typo in a YAML file.
"""

from __future__ import annotations

import subprocess

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product import load_product_context
from openfactory.runtime.repo_cache import RepoCache

SRC = "AcmeCorp/acme-books"
DOCS = "AcmeCorp/acme-books-documentation"

REQ = """# REQ-0001 — Recurring-payment proposals

- **Status:** accepted
- **Asked by:** Alice
- **Date:** 2026-07-26

## Decisions taken during execution

| date | decision | where it came from |
|---|---|---|
| 2026-07-26 | weekly only for v1 | #504 |
"""


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _repo(path, files: dict[str, str]):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", cwd=path)
    _git("config", "user.email", "t@t", cwd=path)
    _git("config", "user.name", "t", cwd=path)
    for rel, body in files.items():
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    _git("add", "-A", cwd=path)
    _git("commit", "-qm", "seed", cwd=path)
    return path


@pytest.fixture
def docs_repo(tmp_path):
    return _repo(tmp_path / "docs", {
        ".openfactory/product.yaml": f"product: books\nsources:\n  - {SRC}\n",
        "requirements/0001-recurring.md": REQ,
    })


@pytest.fixture
def ctx(tmp_path, docs_repo, monkeypatch):
    """Load a context against the fixture repos, with the clone URL pointing at a local path."""
    cache = RepoCache(root=tmp_path / "cache")
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda project, repo="", *, token=None: str(docs_repo))

    def _load(**kw):
        product = kw.pop("product", {"docs_repo": DOCS})
        project = Project(
            name=kw.pop("name", "books"), repo_path=str(tmp_path / "code"),
            tracker={"kind": "github", "repo": SRC},
            product=ProductConfig(**product) if product is not None else None,
        )
        return load_product_context(project, cache=cache,
                                    source_claim=kw.pop("source_claim", DOCS), **kw)

    return _load


# ── the happy path ──────────────────────────────────────────────────────────────────────────────

def test_a_configured_product_loads_its_corpus(ctx):
    c = ctx()
    assert c.available is True
    assert c.link.docs_repo == DOCS.lower()
    assert [r.number for r in c.corpus.requirements] == [1]
    assert c.corpus.by_number(1).title == "Recurring-payment proposals"
    assert c.docs_commit  # the exact commit the requirements were read from


def test_the_health_line_says_what_a_human_needs(ctx):
    assert "requirements" in ctx().health()
    assert "unavailable" in ctx(product=None).health()


def test_a_custom_requirements_dir_is_honoured(tmp_path, monkeypatch):
    """A client may lay its repository out differently; `requirements_dir` is why that is data."""
    repo = _repo(tmp_path / "docs2", {
        ".openfactory/product.yaml": f"product: books\nsources: [{SRC}]\nrequirements_dir: specs\n",
        "specs/0002-thing.md": "# REQ-0002 — thing\n\n- **Status:** proposed\n",
    })
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda p, r="", *, token=None: str(repo))
    project = Project(name="books", repo_path=str(tmp_path / "c"),
                      tracker={"kind": "github", "repo": SRC},
                      product=ProductConfig(docs_repo=DOCS))
    c = load_product_context(project, cache=RepoCache(root=tmp_path / "cache"), source_claim=DOCS)
    assert [r.number for r in c.corpus.requirements] == [2]


# ── the module stays off rather than guessing ───────────────────────────────────────────────────

def test_a_project_without_the_module_does_no_io_at_all(tmp_path):
    """The common case by far — most projects never enable this, and none of them should pay a
    clone to discover that."""
    class _Explode:
        def sync(self, *a, **k):
            raise AssertionError("must not touch the network for a project without the module")

    project = Project(name="x", repo_path=str(tmp_path))
    assert load_product_context(project, cache=_Explode()).available is False


def test_an_unreachable_docs_repo_turns_the_module_off_with_a_reason(tmp_path, monkeypatch):
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda p, r="", *, token=None: str(tmp_path / "nope"))
    project = Project(name="books", repo_path=str(tmp_path), product=ProductConfig(docs_repo=DOCS))
    c = load_product_context(project, cache=RepoCache(root=tmp_path / "cache"), source_claim=DOCS)
    assert c.available is False and "could not check out" in c.reason


def test_a_docs_repo_with_no_manifest_reports_the_missing_file(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "bare", {"README.md": "nothing here"})
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda p, r="", *, token=None: str(repo))
    project = Project(name="books", repo_path=str(tmp_path), product=ProductConfig(docs_repo=DOCS))
    c = load_product_context(project, cache=RepoCache(root=tmp_path / "cache"), source_claim=DOCS)
    assert c.available is False and ".openfactory/product.yaml" in c.reason and "missing" in c.reason


@pytest.mark.parametrize("body,expect", [
    ("product: [unclosed\n", "not valid YAML"),
    ("just a string\n", "must be a mapping"),
    ("sources: [a/b]\n", "invalid at 'product'"),
])
def test_a_malformed_manifest_names_the_problem_instead_of_raising(tmp_path, monkeypatch,
                                                                   body, expect):
    repo = _repo(tmp_path / f"bad{abs(hash(body))}", {".openfactory/product.yaml": body})
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda p, r="", *, token=None: str(repo))
    project = Project(name="books", repo_path=str(tmp_path), product=ProductConfig(docs_repo=DOCS))
    c = load_product_context(project, cache=RepoCache(root=tmp_path / "cache"), source_claim=DOCS)
    assert c.available is False and expect in c.reason


def test_a_renamed_requirements_folder_is_visible_rather_than_looking_empty(tmp_path, monkeypatch):
    """An empty corpus and a mis-pointed one look identical from the outside — and the second is
    how a product role would confidently say "there are no requirements about that"."""
    repo = _repo(tmp_path / "moved", {
        ".openfactory/product.yaml": f"product: books\nsources: [{SRC}]\nrequirements_dir: reqs\n",
        "requirements/0001-x.md": REQ,
    })
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda p, r="", *, token=None: str(repo))
    project = Project(name="books", repo_path=str(tmp_path),
                      tracker={"kind": "github", "repo": SRC},
                      product=ProductConfig(docs_repo=DOCS))
    c = load_product_context(project, cache=RepoCache(root=tmp_path / "cache"), source_claim=DOCS)
    assert c.available is True                       # the link is fine; the corpus is not
    assert c.corpus.requirements == []
    assert any(f.code == "no-directory" for f in c.corpus.findings)


def test_the_membership_check_runs_against_the_REAL_manifest(tmp_path, monkeypatch):
    """The end-to-end version of the inconsistency the two-way declaration exists to catch."""
    repo = _repo(tmp_path / "other", {
        ".openfactory/product.yaml": "product: books\nsources: [AcmeCorp/something-else]\n",
    })
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda p, r="", *, token=None: str(repo))
    project = Project(name="books", repo_path=str(tmp_path),
                      tracker={"kind": "github", "repo": SRC},
                      product=ProductConfig(docs_repo=DOCS))
    c = load_product_context(project, cache=RepoCache(root=tmp_path / "cache"), source_claim=DOCS)
    assert c.available is False and c.link.kind == "conflict"


def test_a_missing_source_claim_only_warns(ctx):
    c = ctx(source_claim=None)
    assert c.available is True and c.link.warnings


def test_a_source_claiming_a_different_repo_stops_the_module(ctx):
    c = ctx(source_claim="attacker/elsewhere")
    assert c.available is False and c.link.kind == "conflict"


def test_a_cache_that_explodes_is_contained(tmp_path):
    """Any unexpected failure in the checkout layer turns the module off — it must never surface as
    a traceback in a Slack listener."""
    class _Boom:
        def sync(self, *a, **k):
            raise RuntimeError("disk on fire")

    project = Project(name="books", repo_path=str(tmp_path), product=ProductConfig(docs_repo=DOCS))
    c = load_product_context(project, cache=_Boom(), source_claim=DOCS)
    assert c.available is False and "disk on fire" in c.reason
