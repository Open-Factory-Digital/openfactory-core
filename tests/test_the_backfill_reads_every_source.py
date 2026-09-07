"""The backfill reads every source repository the product declares (defects ledger #9).

`onboard_product_context` receives the whole `sources` list and `plan()` writes them all into
`product.yaml` — and `_backfill` cloned `repo_of(project)` alone. A front-end-plus-back-end
product got a context describing half its system and ONE folder under `.okf/repos/`, and the
second repository's documents were silently skipped by `write_documents`' never-overwrite rule.
Measured before the fix, on this file's own fixture: `.okf/repos/acme--web/` did not exist and
`docs/levantamento.md` named `acme/api` only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.contracts.project import ProductConfig, Project, ProviderRef
from openfactory.knowledge.bundle import MODULES_FILE
from openfactory.knowledge.pipeline import okf_subpath
from openfactory.onboarding import context as ctx
from openfactory.onboarding import onboard as ob


def _bare(tmp_path: Path, name: str, *, seed: dict[str, str] | None = None) -> Path:
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True,
                   capture_output=True)
    if seed:
        work = tmp_path / f"seed-{name}"
        work.mkdir()
        for rel, body in seed.items():
            target = work / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        for args in (["init", "-b", "main"], ["add", "-A"],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed"],
                     ["remote", "add", "origin", str(bare)], ["push", "-u", "origin", "main"]):
            subprocess.run(["git", *args], cwd=work, check=True, capture_output=True)
    return bare


class _Forge:
    def pr_for_head(self, head, *, repo=""):
        return ""

    def list_branches(self, repo="", *, prefix=""):
        return []

    def open_pr(self, *, head, base, title, body, repo=""):
        return f"https://github.com/{repo}/pull/2"

    def push_remote(self):
        return None


def _project() -> Project:
    return Project(name="dsk", repo_path="https://github.com/acme/api.git",
                   tracker=ProviderRef(kind="github", repo="acme/api"),
                   forge=ProviderRef(kind="github", repo="acme/api"),
                   product=ProductConfig(docs_repo="acme/dsk-context"), language="pt-BR")


API = {"pkg/app.py": "def main():\n    return 1\n",
       "pkg/billing/rules.py": "def charge():\n    return 1\n"}
WEB = {"src/pages/home.ts": "export const home = () => 1;\n",
       "src/pages/cart.ts": "export const cart = () => 2;\n"}


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Two source repositories, a context repository born empty, no harness credential."""
    origins: dict[str, Path] = {
        "acme/api": _bare(tmp_path, "api", seed=API),
        "acme/web": _bare(tmp_path, "web", seed=WEB),
        "acme/dsk-context": _bare(tmp_path, "ctx"),
    }
    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                        lambda *a, **kw: _Forge())
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda view, repo, token=None: str(origins.get(repo, tmp_path / "gone")))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return origins


def _published(bare: Path) -> dict[str, str]:
    tree = subprocess.run(["git", "ls-tree", "-r", "--name-only", "main"], cwd=bare,
                          capture_output=True, text=True, check=True).stdout.split()
    return {path: subprocess.run(["git", "show", f"main:{path}"], cwd=bare,
                                 capture_output=True, text=True, check=True).stdout
            for path in tree}


API_HOME, WEB_HOME = okf_subpath("acme/api"), okf_subpath("acme/web")


# ── every source, its own folder ────────────────────────────────────────────────────────────────

def test_each_source_gets_its_own_bundle_folder(wired):
    out = ob.onboard_product_context(_project(), sources=["acme/api", "acme/web"])

    assert out.ok, out.detail
    shown = _published(wired["acme/dsk-context"])
    for home in (API_HOME, WEB_HOME):
        assert f"{home}/{MODULES_FILE}" in shown, f"no map under {home}: {sorted(shown)}"
        assert f"{home}/okf.yaml" in shown, f"no concepts manifest under {home}"
        assert f"{home}/inventory.json" in shown, f"no inventory under {home}"
    door = shown[".okf/index.md"]
    assert "acme/api" in door and "acme/web" in door, f"the front door lists one bundle: {door}"
    assert "src/pages" in shown[f"{WEB_HOME}/{MODULES_FILE}"], "the web map describes the api"
    assert "pkg/billing" in shown[f"{API_HOME}/{MODULES_FILE}"]


def test_the_documents_describe_the_whole_product_one_section_per_repository(wired):
    out = ob.onboard_product_context(_project(), sources=["acme/api", "acme/web"])

    assert out.ok, out.detail
    shown = _published(wired["acme/dsk-context"])
    survey = shown["docs/levantamento.md"]
    assert "## acme/api" in survey and "## acme/web" in survey, survey[:600]
    assert survey.index("## acme/api") < survey.index("## acme/web"), "declared order"
    assert survey.count("\n# ") == 0 and survey.startswith("# "), "one title, then sections"
    assert "pkg/billing" in survey and "src/pages" in survey, "one repository's survey is missing"
    for path in ("docs/glossario.md", "docs/perguntas-abertas.md"):
        assert "## acme/api" in shown[path] and "## acme/web" in shown[path], path


def test_the_questions_of_every_source_are_carried_under_their_own_subject(wired, monkeypatch):
    from openfactory.onboarding import questions as q

    seen: list[str] = []
    real = q.carry
    monkeypatch.setattr(q, "carry", lambda repo, **kw: seen.append(repo) or real(repo, **kw))
    monkeypatch.setattr("openfactory.memory.store.read", lambda project, **kw: [])
    monkeypatch.setattr("openfactory.memory.store.write", lambda project, loops, **kw: len(loops))

    assert ob.onboard_product_context(_project(), sources=["acme/api", "acme/web"]).ok
    assert seen == ["acme/api", "acme/web"], seen


def test_the_outcome_names_each_source_and_what_it_spent(wired):
    out = ob.onboard_product_context(_project(), sources=["acme/api", "acme/web"])
    assert out.backfill.startswith("acme/api: ") and "; acme/web: " in out.backfill, out.backfill


# ── a source that cannot be read ────────────────────────────────────────────────────────────────

def test_a_source_that_cannot_be_cloned_is_named_and_does_not_stop_the_others(wired):
    out = ob.onboard_product_context(_project(), sources=["acme/gone", "acme/api"])

    assert out.ok, out.detail
    assert out.backfill.startswith("acme/gone: skipped, could not clone"), out.backfill
    assert "; acme/api: " in out.backfill
    shown = _published(wired["acme/dsk-context"])
    assert f"{API_HOME}/{MODULES_FILE}" in shown, "the readable source was not read"
    assert not any(p.startswith(str(okf_subpath("acme/gone"))) for p in shown), (
        "a folder was published for a repository nobody read")
    assert "## acme/gone" not in shown["docs/levantamento.md"]


def test_nothing_readable_is_a_skipped_backfill_with_every_reason(wired):
    out = ob.onboard_product_context(_project(), sources=["acme/gone", "acme/lost"])
    assert "acme/gone: skipped, could not clone" in out.backfill
    assert "acme/lost: skipped, could not clone" in out.backfill
    assert out.documents == []


# ── a single source is what it was ──────────────────────────────────────────────────────────────

def test_a_single_source_product_is_byte_for_byte_what_it_was(wired):
    out = ob.onboard_product_context(_project(), sources=["acme/api"])

    assert out.ok, out.detail
    assert not out.backfill.startswith("acme/api:") and "acme/api: " not in out.backfill, (
        f"the single-source sentence gained a prefix: {out.backfill}")
    shown = _published(wired["acme/dsk-context"])
    assert "## acme/api" not in shown["docs/levantamento.md"], "no section for one repository"
    assert f"{API_HOME}/{MODULES_FILE}" in shown
    assert not any(p.startswith(str(WEB_HOME)) for p in shown)


def test_no_source_declared_means_the_default_repository_as_before(wired):
    out = ob.onboard_product_context(_project(), sources=[])
    assert out.ok, out.detail
    assert f"{API_HOME}/{MODULES_FILE}" in _published(wired["acme/dsk-context"])


def test_a_clone_that_failed_the_single_source_way_keeps_its_sentence(wired):
    out = ob.onboard_product_context(_project(), sources=["acme/gone"])
    assert out.backfill.startswith("skipped: could not clone the source repository ("), out.backfill


# ── the merge, on its own ───────────────────────────────────────────────────────────────────────

def _proposal(label: str, docs: dict[str, str]) -> ctx.ContextProposal:
    return ctx.ContextProposal(repo=f"/tmp/{label}", label=label, documents=[
        ctx.ContextDocument(path=path, title=path, body=body, kind="survey", from_model=False)
        for path, body in docs.items()])


def test_the_merge_keeps_one_title_and_demotes_each_repository_s_own_headings():
    api = _proposal("acme/api", {"docs/x.md": "# Levantamento\n\n## Módulos\n\n- pkg\n",
                                 "docs/only-api.md": "# Só a API\n\ntexto\n"})
    web = _proposal("acme/web", {"docs/x.md": "# Levantamento\n\n## Módulos\n\n```\n# not a "
                                              "heading\n```\n- src\n"})
    merged = {d.path: d.body for d in ob._merge_documents([api, web]).documents}
    assert merged["docs/x.md"] == (
        "# Levantamento\n\n## acme/api\n\n### Módulos\n\n- pkg\n\n## acme/web\n\n### Módulos\n\n"
        "```\n# not a heading\n```\n- src\n"), merged["docs/x.md"]
    assert merged["docs/only-api.md"] == "# Só a API\n\ntexto\n", "a path one source has is kept"


def test_one_proposal_is_returned_untouched():
    api = _proposal("acme/api", {"docs/x.md": "# T\n\nbody\n"})
    assert ob._merge_documents([api]) is api


def test_a_document_without_a_title_line_gets_one_from_its_title():
    a = _proposal("a/a", {"d.md": "texto a\n"})
    b = _proposal("b/b", {"d.md": "texto b\n"})
    (doc,) = ob._merge_documents([a, b]).documents
    assert doc.body.startswith("# d.md\n\n## a/a\n\ntexto a\n\n## b/b\n\ntexto b"), doc.body
