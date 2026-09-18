"""`product init --write` writes a `sources:` list that the product link's OWN check accepts.

THE COMMAND AND THE CHECK DISAGREED ABOUT WHAT A REPOSITORY IS. `product init` kept a candidate
source only when it contained a `/` — the `owner/name` shape of one forge — while the membership
check the file must then pass (`resolve_product_link`) asks for `_source_repo(project)`, read by
`normalize_repo`, which reads one to three segments. On a forge whose registry row names its
repository bare (Azure Repos: `forge: {repo: their-app, options: {organization, project}}`) the
project's own repository was dropped, and so was every bare `--source`. The command wrote

    sources: []

and the link it had just proposed refused its own project: *"their-app is not listed in
`sources:` … (it lists nothing)"*. Reported from a real deployment, and checked there by calling
`resolve_product_link` on the same project: `sources: []` → `conflict`, `sources: [<repo>]` → `ok`.

WHAT THE SLASH WAS STANDING IN FOR. It dropped the local board's bare project name, which is not
code — but it dropped it for how it is SPELLED, not for WHOSE it is, so it also dropped the forge's
bare repository, and it let a GitHub tracker's separate issues repository in because that one
happens to be spelled with a slash. The sibling `openfactory onboard` learned the same lesson on
2026-08-13 ("no `"/" in r` filter … never BOTH axes"); this command never followed.

READS THE THING. Each case runs the real command against a real bare git repository standing in
for the context repository, reads the file back from the branch it pushed with the loader's own
reader, and hands it to the check. Only the two seams that leave the machine are doubled: the
forge (which would clone from and open a pull request on a hosted service) and the registry.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfactory.cli import app

_GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *_GIT_ID, *args], cwd=cwd, capture_output=True, text=True,
                          check=True, timeout=60)


class _Forge:
    """Clones from a local bare repository and records the review request it is asked to open."""

    def __init__(self, url: str):
        self.url = url
        self.opened: list[dict] = []

    def clone_url(self, repo, *, token=None):
        return self.url

    def open_pr(self, *, head, base, title, body, repo=""):
        self.opened.append({"head": head, "base": base, "repo": repo})
        return "https://forge.invalid/pr/1"


class _Registry:
    def __init__(self, project):
        self._project = project

    def get(self, name):
        return self._project


def _project(*, forge: tuple[str, str], tracker: tuple[str, str],
             docs_repo: str = "acme-context"):
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    return Project(
        name="acme", repo_path="/t",
        forge=ProviderRef(kind=forge[0], repo=forge[1]),
        tracker=ProviderRef(kind=tracker[0], repo=tracker[1]),
        product=ProductConfig(docs_repo=docs_repo),
    )


#: The registry row of a project on a forge that names repositories bare, with its cards on a
#: local board — the pairing the report came from.
_BARE = {"forge": ("azure_devops", "their-app"), "tracker": ("local", "acme")}
#: The GitHub shape, where tracker and forge are the same `owner/name`.
_GITHUB = {"forge": ("github", "acme-corp/their-app"), "tracker": ("github", "acme-corp/their-app")}


@pytest.fixture
def init(tmp_path, monkeypatch):
    """Run `product init <project> --write [--source …]` for a project; answer what it wrote.

    Returns `(result, sources, link, forge)` — `sources` is the list as written in the pushed
    file (None when nothing was pushed) and `link` the check's verdict on it."""
    from openfactory import registry as registry_module
    from openfactory.adapters.forge import registry as forge_registry
    from openfactory.product import onboard

    bare = tmp_path / "context.git"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    _git("init", "-q", "-b", "main", str(seed))
    (seed / "README.md").write_text("the client's context repository\n", encoding="utf-8")
    _git("add", "README.md", cwd=seed)
    _git("commit", "-q", "-m", "seed", cwd=seed)
    _git("push", "-q", str(bare), "main", cwd=seed)

    def _run(*, forge, tracker, sources=()):
        from openfactory.product.config import resolve_product_link
        from openfactory.product.loader import _read_docs_manifest

        project = _project(forge=forge, tracker=tracker)
        double = _Forge(str(bare))
        monkeypatch.setattr(forge_registry, "build_forge", lambda *a, **kw: double)
        monkeypatch.setattr(registry_module, "ProjectRegistry", lambda: _Registry(project))
        monkeypatch.setattr(onboard, "_context_token", lambda p: None)

        argv = ["product", "init", "acme", "--write"]
        for s in sources:
            argv += ["--source", s]
        result = CliRunner().invoke(app, argv)

        branch = onboard.proposal_branch("acme")
        pushed = subprocess.run(["git", "-C", str(bare), "rev-parse", "--verify", "-q",
                                 f"refs/heads/{branch}"], capture_output=True, text=True)
        if pushed.returncode != 0:
            return result, None, None, double
        checkout = tmp_path / f"read-{len(list(tmp_path.glob('read-*')))}"
        _git("clone", "-q", "-b", branch, str(bare), str(checkout))
        docs, error = _read_docs_manifest(checkout)
        assert docs is not None, f"the file the command pushed could not be read back: {error}"
        link = resolve_product_link(project=project, manifest_docs_repo="acme-context", docs=docs)
        return result, list(docs.sources), link, double

    return _run


def test_on_a_forge_that_names_repositories_BARE_the_file_written_is_accepted_by_its_own_check(
        init):
    """The report, exactly. Before: `sources: []`, and the link refused the project that had just
    proposed it."""
    result, sources, link, forge = init(**_BARE)

    assert result.exit_code == 0, result.output
    assert sources is not None, f"nothing was pushed: {result.output}"
    assert "their-app" in sources, (
        f"the project's own repository was dropped from `sources:` because of how it is spelled: "
        f"{sources}")
    assert link.kind == "ok", f"the file the command wrote is refused by its own check: {link}"
    assert forge.opened, "no review request was opened"


@pytest.mark.parametrize("given", ["other-svc", "Proj/other-svc", "client-org/Proj/other-svc"])
def test_every_source_the_operator_names_is_kept_however_the_forge_spells_it(init, given):
    """`--source` is how a product that spans several repositories says so. A bare name was
    silently dropped; a qualified one was kept, but beside a `sources:` that had lost the
    project's own repository, so the file was refused all the same — no argument produced a
    working file."""
    result, sources, link, _ = init(**_BARE, sources=[given])

    assert result.exit_code == 0, result.output
    assert sources is not None, f"nothing was pushed: {result.output}"
    assert given in sources, f"--source {given!r} was dropped: {sources}"
    assert "their-app" in sources, f"the project's own repository was dropped: {sources}"
    assert link.kind == "ok", f"the file the command wrote is refused by its own check: {link}"


@pytest.mark.parametrize("tracker", [
    ("local", "acme"),                      # the local board's name is the project's
    ("azure_devops", "Proj"),               # an Azure Boards row names the Azure PROJECT
    ("github", "acme-corp/their-issues"),   # GitHub issues kept in a repository of their own
], ids=["local-board", "azure-boards-project", "github-issues-repository"])
def test_the_trackers_repository_is_not_a_source_whatever_its_spelling(init, tracker):
    """`sources:` is the set of repositories holding the product's CODE — the check's own
    `_source_repo` reads the forge and falls back to the tracker only when there is no forge.
    The slash rule dropped the first two for being bare and let the third in for having a
    slash; it is the TRACKER's in all three."""
    result, sources, link, _ = init(forge=("azure_devops", "their-app"), tracker=tracker)

    assert result.exit_code == 0, result.output
    assert sources is not None, f"nothing was pushed: {result.output}"
    assert tracker[1] not in sources, (
        f"the tracker's {tracker[1]!r} was written as a source of code: {sources}")
    assert sources == ["their-app"], f"the forge's own repository was dropped: {sources}"
    assert link.kind == "ok", link


def test_the_owner_name_shape_is_unchanged(init):
    """The case the slash rule was written for keeps working exactly as it did."""
    result, sources, link, _ = init(**_GITHUB, sources=["acme-corp/their-api"])

    assert result.exit_code == 0, result.output
    assert sources == ["acme-corp/their-api", "acme-corp/their-app"], sources
    assert link.kind == "ok", link


def test_one_repository_named_twice_is_written_once(init):
    """The project's own repository given again as `--source`, in another case: the check reads
    both as one coordinate, so the file lists it once — in the registry's spelling."""
    result, sources, link, _ = init(**_BARE, sources=["Their-App"])

    assert result.exit_code == 0, result.output
    assert sources == ["their-app"], sources
    assert link.kind == "ok", link


def test_a_source_that_is_not_a_repository_reference_is_refused_by_name_and_nothing_is_pushed(
        init):
    """A `--source` the check cannot read would be written, then reported by the link as a member
    it cannot vouch for — or, under the slash rule, dropped without a word. Neither is what the
    person who typed it asked for; the command stops before touching the client's repository and
    names the argument."""
    result, sources, _, forge = init(**_BARE, sources=["not a repository"])

    assert result.exit_code == 2, result.output
    assert "not a repository" in result.output, (
        f"the refusal does not name the argument it refused: {result.output}")
    assert sources is None, f"a branch was pushed despite the refusal: {sources}"
    assert forge.opened == [], "a review request was opened despite the refusal"
