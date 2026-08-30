"""The context box: create-or-use the repository, backfill it server-side, propose it — one PR.

The second half of the operator's box design — a box over the context repository, creating it
where there is none, where the prose backfill happens — with the both-shapes rule an enterprise
client added: some projects already keep a documentation repository (USED, never replaced), some
have none (CREATED, in their own organisation). What these hold:

  1. a declared docs repo is cloned and used — nothing is created;
  2. an undeclared one is created THROUGH the extracted leg and the project is RE-READ (the
     stale-object defect's third sighting, prevented);
  3. the backfill runs server-side and says WHICH mode it took — deterministic with the why
     when no harness credential is present, never a silent downgrade;
  4. the PR carries product.yaml + the backfill documents, and the third declaration (each
     source repo's `docs_repo:` line) stays a printed todo — deliberately human;
  5. every temporary clone is removed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
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
    def __init__(self):
        self.opened: list[dict] = []
        self.created: list[str] = []

    def pr_for_head(self, head, *, repo=""):
        return ""

    def list_branches(self, repo="", *, prefix=""):
        return []

    def open_pr(self, *, head, base, title, body, repo=""):
        self.opened.append({"head": head, "base": base, "title": title, "body": body,
                            "repo": repo})
        return f"https://github.com/{repo}/pull/2"

    def create_repository(self, *, name, private=True, description=""):
        self.created.append(name)
        return f"acme/{name}", True

    def push_remote(self):
        return None


def _project(docs_repo: str = "") -> Project:
    return Project(name="dsk", repo_path="https://github.com/acme/api.git",
                   tracker=ProviderRef(kind="github", repo="acme/api"),
                   forge=ProviderRef(kind="github", repo="acme/api"),
                   product=ProductConfig(docs_repo=docs_repo) if docs_repo else None)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    origins: dict[str, Path] = {}
    forge = _Forge()
    recorded: list[tuple[str, str]] = []

    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                        lambda *a, **kw: forge)
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda view, repo, token=None: str(origins[repo]))

    class _Registry:
        def __init__(self):
            self._project = None

        def get(self, name):
            if self._project is None:
                raise KeyError(name)
            return self._project

        def set_docs_repo(self, name, docs_repo):
            recorded.append((name, docs_repo))
            self._project = _project(docs_repo)

    reg = _Registry()
    monkeypatch.setattr("openfactory.registry.ProjectRegistry", lambda: reg)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return origins, forge, recorded


def test_a_declared_context_repo_is_USED_never_created(tmp_path, wired):
    origins, forge, recorded = wired
    origins["acme/api"] = _bare(tmp_path, "api",
                                seed={"pkg/app.py": "def main():\n    return 1\n"})
    origins["acme/dsk-context"] = _bare(
        tmp_path, "ctx", seed={".openfactory/product.yaml":
                               "product: dsk\nsources: [acme/api]\n"})

    out = ob.onboard_product_context(_project("acme/dsk-context"), sources=["acme/api"])

    assert out.ok, out.detail
    assert forge.created == [], "a repository was created over one the client already had"
    assert recorded == [], "the registry was rewritten for a repo it already named"


def test_an_undeclared_context_repo_is_created_recorded_and_the_project_reread(tmp_path, wired):
    origins, forge, recorded = wired
    origins["acme/api"] = _bare(tmp_path, "api",
                                seed={"pkg/app.py": "def main():\n    return 1\n"})
    origins["acme/dsk-context"] = _bare(tmp_path, "ctx")  # born empty, like a created repo

    out = ob.onboard_product_context(_project(), sources=["acme/api"])

    assert out.ok, out.detail
    assert out.created
    assert forge.created == ["dsk-context"], "the name must be derived, never free text"
    assert recorded == [("dsk", "acme/dsk-context")], "created and NOT recorded is theatre"


def test_the_pr_carries_declaration_backfill_and_the_human_todo(tmp_path, wired):
    """A context repo WITH history gets the review shape: a branch, a PR, its base untouched."""
    origins, forge, _ = wired
    origins["acme/api"] = _bare(tmp_path, "api",
                                seed={"pkg/app.py": "def main():\n    return 1\n"})
    origins["acme/dsk-context"] = _bare(tmp_path, "ctx", seed={"README.md": "docs live here\n"})

    out = ob.onboard_product_context(_project("acme/dsk-context"), sources=["acme/api"])

    assert out.ok, out.detail
    assert out.documents, "the backfill wrote nothing"
    assert out.todo, "the source repo's docs_repo: line must stay a printed todo"
    shown = subprocess.run(["git", "show", "--name-only", "--format=",
                            "openfactory/onboard-dsk"],
                           cwd=origins["acme/dsk-context"], capture_output=True, text=True)
    assert ".openfactory/product.yaml" in shown.stdout
    assert any(d in shown.stdout for d in out.documents), (
        f"the backfill documents are not in the pushed commit: {shown.stdout}")
    assert forge.opened and forge.opened[0]["base"] == "main", (
        "the PR must target the repository's own base")


def test_a_repo_born_empty_gets_its_first_commit_on_the_base_not_a_zero_diff_pr(tmp_path,
                                                                                wired):
    """No PR is possible against a base with no commits — the forge refuses it. The declaration
    IS the empty repository's first content, pushed plainly to the base and said in those words
    (adversarial review, 2026-08-13)."""
    origins, forge, _ = wired
    origins["acme/api"] = _bare(tmp_path, "api",
                                seed={"pkg/app.py": "def main():\n    return 1\n"})
    origins["acme/dsk-context"] = _bare(tmp_path, "ctx")  # born empty, like a created repo

    out = ob.onboard_product_context(_project("acme/dsk-context"), sources=["acme/api"])

    assert out.ok, out.detail
    assert not forge.opened, "a pull request was attempted against a commitless base"
    assert "first commit" in out.detail, out.detail
    shown = subprocess.run(["git", "show", "--name-only", "--format=", "main"],
                           cwd=origins["acme/dsk-context"], capture_output=True, text=True)
    assert ".openfactory/product.yaml" in shown.stdout
    assert any(d in shown.stdout for d in out.documents), (
        f"the backfill documents are not on the base: {shown.stdout}")


def test_an_open_context_review_is_found_not_force_pushed_over(tmp_path, wired):
    """--force onto a branch with an OPEN review destroys the reviewer's commits — the port is
    asked first, and an open proposal is RETURNED, its branch untouched (adversarial review,
    2026-08-13)."""
    origins, forge, _ = wired
    origins["acme/api"] = _bare(tmp_path, "api",
                                seed={"pkg/app.py": "def main():\n    return 1\n"})
    origins["acme/dsk-context"] = _bare(tmp_path, "ctx", seed={"README.md": "docs\n"})
    forge.pr_for_head = lambda head, repo="": "https://github.com/acme/dsk-context/pull/9"
    forge.pr_status = lambda *, pr, repo="": "active"

    before = subprocess.run(["git", "rev-parse", "main"], cwd=origins["acme/dsk-context"],
                            capture_output=True, text=True).stdout

    out = ob.onboard_product_context(_project("acme/dsk-context"), sources=["acme/api"])

    assert out.ok, out.detail
    assert out.pr == "https://github.com/acme/dsk-context/pull/9"
    assert not forge.opened, "a second review was opened over the existing one"
    after = subprocess.run(["git", "rev-parse", "main"], cwd=origins["acme/dsk-context"],
                           capture_output=True, text=True).stdout
    assert before == after, "the repository was pushed to despite the open review"


def test_without_a_harness_credential_the_backfill_says_deterministic_and_why(tmp_path, wired):
    origins, _, _ = wired
    origins["acme/api"] = _bare(tmp_path, "api",
                                seed={"pkg/app.py": "def main():\n    return 1\n"})
    origins["acme/dsk-context"] = _bare(tmp_path, "ctx")

    out = ob.onboard_product_context(_project("acme/dsk-context"), sources=["acme/api"])

    assert out.backfill.startswith("deterministic"), out.backfill
    assert "credential" in out.backfill, "the WHY of the downgrade must be stated"
    # STRENGTHENED 2026-08-29: "no credential" is a diagnosis, not a remedy. Until this line the
    # sentence could not say WHICH credential, because the check was two hardcoded Anthropic
    # variables while the harness came from `harness_kind(project, "techlead")` — so a `codex`
    # deployment was told it had no credential and never which one to set.
    assert "ANTHROPIC_API_KEY" in out.backfill or "CLAUDE_CODE_OAUTH_TOKEN" in out.backfill, \
        "the downgrade must name the variable that would fix it, not just its absence"


def test_every_temporary_clone_is_removed(tmp_path, wired, monkeypatch):
    origins, _, _ = wired
    origins["acme/api"] = _bare(tmp_path, "api",
                                seed={"pkg/app.py": "def main():\n    return 1\n"})
    origins["acme/dsk-context"] = _bare(tmp_path, "ctx")
    made: list[Path] = []
    import tempfile as real_tempfile

    real_mkdtemp = real_tempfile.mkdtemp

    def _remember(*a, **kw):
        path = real_mkdtemp(*a, **kw)
        if "openfactory-" in path:
            made.append(Path(path))
        return path

    monkeypatch.setattr("tempfile.mkdtemp", _remember)
    ob.onboard_product_context(_project("acme/dsk-context"), sources=["acme/api"])

    assert made, "nothing was cloned, so this proves nothing"
    leaked = [p for p in made if p.exists()]
    assert not leaked, f"temporary clones survived: {leaked}"
