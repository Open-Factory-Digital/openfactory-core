"""The published documents name the repository and keep their accents — two things a reader saw
in the first live backfill (2026-09-06) that no test had seen.

1. `okf.slug` kept only `[a-z0-9]`, so a Portuguese title lost every accented LETTER, not just
   the accent: *Superfície HTTP/WebSocket* was filed as `superf-cie-http-websocket`, *Ecrãs
   (páginas React)* as `ecr-s-p-ginas-react`. A filename nobody can sound out is one nobody types,
   links or greps for — and a client's language is the ordinary case for a concept's title.
2. `RepoSurvey.repo` is the checkout path, and it was published as the repository's NAME: the
   survey's first line read ``repositório: `/tmp/openfactory-manifest-kqiq7mmx` `` and every
   agent document's header cited the same temp directory. The name a reader knows is the declared
   one (`acme/api`); the caller that cloned the repository has it, and now hands it over.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.knowledge.okf import slug
from openfactory.onboarding import context as ctx
from openfactory.onboarding import onboard as ob

# ── 1. the slug ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("title, expected", [
    ("Superfície HTTP/WebSocket do Event Manager", "superficie-http-websocket-do-event-manager"),
    ("Ecrãs do Event Manager (páginas React)", "ecras-do-event-manager-paginas-react"),
    ("Euronext Event Manager — aplicação web (PWA)", "euronext-event-manager-aplicacao-web-pwa"),
    ("Règles de facturation", "regles-de-facturation"),
])
def test_an_accented_letter_is_folded_to_its_base_never_cut_out(title, expected):
    assert slug(title) == expected


def test_the_slug_still_collapses_and_never_comes_back_empty():
    assert slug("  Billing   rules!! ") == "billing-rules"
    assert slug("") == "untitled"
    assert slug("日本語") == "untitled", "a script with no Latin base is what it always was"


# ── 2. the name ───────────────────────────────────────────────────────────────────────────────


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    return tmp_path


def test_the_survey_carries_the_declared_name_and_falls_back_to_the_folder(tmp_path):
    repo = _repo(tmp_path)

    named = ctx.survey(repo, label="acme/api")
    unnamed = ctx.survey(repo)

    assert named.label == "acme/api"
    assert unnamed.label == repo.name, "with no name declared the folder's own name is the label"
    assert unnamed.label != str(repo), "the full path is never the label"


def test_the_survey_document_names_the_repository_not_the_checkout(tmp_path):
    s = ctx.survey(_repo(tmp_path), label="acme/api")

    text = ctx.render_survey(s, language="pt-BR")

    assert "`acme/api`" in text, "the repository line does not name the repository"
    assert str(tmp_path) not in text, "the checkout path leaked into a published document"


def test_every_agent_document_header_names_the_repository_not_the_checkout(tmp_path):
    s = ctx.survey(_repo(tmp_path), label="acme/api")

    header = "\n".join(ctx._doc_header(s, ctx._words("pt-BR")))

    assert "`acme/api`" in header
    assert str(tmp_path) not in header


def test_the_report_names_the_repository_not_the_checkout(tmp_path):
    s = ctx.survey(_repo(tmp_path), label="acme/api")
    proposal = ctx.propose_context(s, ask=None)

    report = ctx.render_context_report(proposal)

    assert "context proposal · acme/api" in report, report.splitlines()[0]


# ── 3. the caller hands the name over ────────────────────────────────────────────────────────


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


def test_the_backfill_publishes_the_declared_name_never_its_temp_clone(tmp_path, monkeypatch):
    origins = {
        "acme/api": _bare(tmp_path, "api", seed={"pkg/app.py": "def main():\n    return 1\n"}),
        "acme/dsk-context": _bare(tmp_path, "ctx"),
    }
    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                        lambda *a, **kw: _Forge())
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda view, repo, token=None: str(origins[repo]))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    project = Project(name="dsk", repo_path="https://github.com/acme/api.git",
                      tracker=ProviderRef(kind="github", repo="acme/api"),
                      forge=ProviderRef(kind="github", repo="acme/api"),
                      product=ProductConfig(docs_repo="acme/dsk-context"))

    out = ob.onboard_product_context(project, sources=["acme/api"])

    assert out.ok, out.detail
    ctx_bare = origins["acme/dsk-context"]
    tree = subprocess.run(["git", "ls-tree", "-r", "--name-only", "main"], cwd=ctx_bare,
                          capture_output=True, text=True, check=True).stdout.split()
    documents = {path: subprocess.run(["git", "show", f"main:{path}"], cwd=ctx_bare,
                                      capture_output=True, text=True, check=True).stdout
                 for path in tree if path.endswith(".md")}
    assert documents, f"no document was published: {tree}"
    assert any("`acme/api`" in text for text in documents.values()), (
        f"no published document names the repository: {sorted(documents)}")
    leaked = [path for path, text in documents.items()
              if "openfactory-manifest-" in text or "/tmp/" in text]
    assert not leaked, f"the temp clone's path was published as the repository's name: {leaked}"
