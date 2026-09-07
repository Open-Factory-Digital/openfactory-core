"""The reading is bound against the bundle that exists — the per-source folder, not the front door.

FOUND BY REVIEW (2026-09-06), while designing a plan that would have trusted the grade. Since D-2 a
source repository's concepts live at `.okf/repos/<owner--name>/concepts/`; the root `.okf/index.md`
is the FRONT DOOR `_front_door` writes to list those folders, and no concept sits beside it. The
product role's `_okf_dir()` returned that root, so `reading.bound` read an empty `concepts/` and
graded every citation `baixa` — on every project, against every bundle the platform itself had
published. The third reading (#59) could never reach `alta` in production while every test that
planted a bundle by hand at the root stayed green.

The same mistake one layer down: the job's gate resolved the bundle's subpath from the PROJECT's
default repository, so a card of a multi-repo product's second repository was judged against the
first one's concepts — every file dark for the wrong reason. `_okf_home` now takes the card's repo.
"""

from __future__ import annotations

from pathlib import Path

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.knowledge.contracts import Concept, ConceptSource, OkfManifest
from openfactory.knowledge.okf import OKF_DIRNAME, OKF_INDEX_FILE, write_okf
from openfactory.knowledge.pipeline import okf_subpath
from openfactory.product.corpus import Corpus
from openfactory.product.module import ProductModule
from openfactory.product.reading import ALTA, BAIXA, bound
from openfactory.product.role import Reading


def _project() -> Project:
    return Project(name="dsk", repo_path="https://github.com/acme/api.git",
                   tracker=ProviderRef(kind="github", repo="acme/api"),
                   forge=ProviderRef(kind="github", repo="acme/api"),
                   product=ProductConfig(docs_repo="acme/dsk-context"))


def _module(root: Path) -> ProductModule:
    mod = ProductModule.__new__(ProductModule)
    mod.project = _project()
    mod._combined = str(root)
    return mod


def _published_layout(root: Path) -> Path:
    """Exactly what the onboarding publishes: a front door at the root, the concepts one folder
    down, under the source repository's own name."""
    docs = root / "docs"
    (docs / OKF_DIRNAME).mkdir(parents=True)
    (docs / OKF_DIRNAME / OKF_INDEX_FILE).write_text("# What the code says\n\n- [acme/api](repos/"
                                                     "acme--api/index.md)\n", encoding="utf-8")
    home = docs / okf_subpath("acme/api")
    write_okf(home, manifest=OkfManifest(source_commit="c1"), concepts=[
        Concept(type="policy", title="Billing rules", description="d", what_it_does="w",
                sources=[ConceptSource(repo="acme/api", path="billing/rules.py", commit="c1",
                                       fingerprint="", lines="1-2")])])
    (home / OKF_INDEX_FILE).write_text("# acme/api\n", encoding="utf-8")
    return home


def test_the_bound_reads_the_per_source_folder_not_the_front_door(tmp_path):
    home = _published_layout(tmp_path)
    mod = _module(tmp_path)

    assert mod._okf_dir() == home, "the bound must read where the concepts are"
    reading = bound(Reading(kind="misuse", concepts=["Billing rules"]),
                    bundle_dir=mod._okf_dir(), corpus=Corpus(requirements=[]))
    assert reading.confidence == ALTA, (reading.confidence, reading.bounded_by)


def test_the_front_door_alone_grades_baixa_which_is_what_every_project_read_until_now(tmp_path):
    """The measurement behind the fix: bound against the root, the same citation is `baixa`."""
    _published_layout(tmp_path)
    reading = bound(Reading(kind="misuse", concepts=["Billing rules"]),
                    bundle_dir=tmp_path / "docs" / OKF_DIRNAME, corpus=Corpus(requirements=[]))
    assert reading.confidence == BAIXA


def test_a_bundle_written_at_the_root_is_still_read(tmp_path):
    """A project-context bundle, or one a test planted by hand, sits at the root with its own
    `concepts/` — the fallback keeps those readable; a bare front door with nothing beside it is
    reported as the door it is."""
    docs = tmp_path / "docs"
    write_okf(docs / OKF_DIRNAME, manifest=OkfManifest(), concepts=[
        Concept(type="policy", title="Root rules", description="d")])
    (docs / OKF_DIRNAME / OKF_INDEX_FILE).write_text("# root\n", encoding="utf-8")
    assert _module(tmp_path)._okf_dir() == docs / OKF_DIRNAME


def test_nothing_mounted_is_none(tmp_path):
    assert _module(tmp_path)._okf_dir() is None


def test_the_gate_resolves_the_bundle_from_the_cards_repository(monkeypatch):
    from openfactory.orchestrator.machine import JobRunner

    runner = JobRunner.__new__(JobRunner)
    runner.project = _project()
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda project, repo, token="": f"https://x/{repo}.git")
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda project: "t")

    url, default = runner._okf_home()
    runner._card_repo = "acme/web"          # what _knowledge_gate sets from the card
    _url, web = runner._okf_home()

    assert default == okf_subpath("acme/api"), "no card: the project's default repository"
    assert web == okf_subpath("acme/web"), "a card of the second repository: its own folder"
    assert url == _url and url.endswith("acme/dsk-context.git")
