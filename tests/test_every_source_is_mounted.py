"""Every source the product declares is mounted for the product role — sparse, fetched when a turn
mounts it, read-only, and nothing outside `sources:` (#268 slice 1; ADR-0052 D14, D16, D18, D20).

THE BED IS THE MULTI-REPOSITORY FIXTURE OF THE BATTERY (`tests/fixtures/evaluation/harbourline/`):
one context repository and four source repositories, made real git repositories here and served
over `file://` with filters allowed — which is what lets the caches be PARTIAL clones, as they are
against a real forge. The loader, the module, the workspace, the cache and git are real; the
model is a stub harness that drives the role's own tools (the sandbox's `run`) at the paths the
prompt names. So "the role can open code in every source" is measured the way the role opens it.

What is pinned:

  1. every declared source is in the turn's view, and the role opens a file in each;
  2. a source that cannot be mounted is named in the prompt with why — not authorised,
     unreachable, not declared — and "could not mount" never reads as "nothing there";
  3. nothing outside `sources:` is ever fetched or placed, and no credential reaches a path, a
     prompt or a log;
  4. the checkout is partial and sparse, made on the first turn and not again;
  5. the confidence bound reads every source's bundle;
  6. the module map is named only when it matches the code it describes, and the onboarding
     documents are named.
"""

from __future__ import annotations

import http.server
import logging
import os
import re
import shutil
import stat
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from openfactory.contracts import AgentRunResult
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.product import sources as mount
from openfactory.product.module import ProductModule

FIXTURE = Path(__file__).parent / "fixtures" / "evaluation" / "harbourline"

#: The product's four source repositories, and where the fixture keeps each.
REPOS = {"harbourline": "source",
         "harbourline-pricing": "sources/harbourline-pricing",
         "harbourline-tracking": "sources/harbourline-tracking",
         "harbourline-web": "sources/harbourline-web"}

#: One file per source, and a line only that file holds.
OPENS = {"harbourline": ("harbourline/bookings.py", "QUOTE_VALID_FOR = timedelta(hours=48)"),
         "harbourline-pricing": ("pricing/freight.py", "VOLUMETRIC_KG_PER_M3 = 333"),
         "harbourline-tracking": ("tracking/eta.py", "DELAY_WORTH_TELLING = timedelta(hours=6)"),
         "harbourline-web": ("src/quote.ts", "export async function requestQuote")}

#: A credential shaped like the forge's, planted in a clone URL. It may appear nowhere.
SECRET = "ghp_q268SECRETSECRETSECRETSECRET"


# ── the bed ─────────────────────────────────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})
    return done.stdout


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def _repository(src: Path, dest: Path) -> Path:
    """`src` as a git repository at `dest`, one commit on `main`, serving partial clones."""
    shutil.copytree(src, dest)
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "config", "user.name", "fixture")
    _git(dest, "config", "user.email", "fixture@example.invalid")
    _git(dest, "config", "commit.gpgsign", "false")
    _git(dest, "config", "uploadpack.allowFilter", "true")
    _git(dest, "config", "uploadpack.allowAnySHA1InWant", "true")
    _commit(dest, "the fixture")
    return dest


class _Checkouts:
    """The loader's cache, answering the context repository's key with the fixture's own — the
    battery's `_FixtureCheckouts`."""

    def __init__(self, context: Path) -> None:
        from openfactory.runtime.repo_cache import RepoCache

        self._cache, self._context = RepoCache(), context

    def sync(self, project: str, clone_url: str, base_branch: str = ""):
        from openfactory.product.loader import DOCS_CACHE_SUFFIX

        url = str(self._context) if project.endswith(DOCS_CACHE_SUFFIX) else clone_url
        return self._cache.sync(project, url, base_branch)


@dataclass
class Bed:
    tmp: Path
    cache: Path
    repos: dict[str, Path]
    context: Path
    urls: dict[str, str]
    asked: list[str]
    project: Project

    def ctx(self):
        from openfactory.product.loader import load_product_context

        return load_product_context(self.project, cache=_Checkouts(self.context))

    def module(self, agent=None) -> ProductModule:
        return ProductModule(self.project, context=self.ctx(), agent=agent)

    def masters(self) -> dict[str, Path]:
        root = self.cache / ".masters"
        return {p.name.split("--source--", 1)[1]: p for p in sorted(root.glob("*--source--*"))} \
            if root.is_dir() else {}


@pytest.fixture()
def bed(tmp_path, monkeypatch) -> Bed:
    cache = tmp_path / "cache"
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(cache))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "null")
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    # the read model is #267's, and reads the engine; nothing here is about it
    monkeypatch.setattr("openfactory.product.module._the_read_model", lambda module, root: {})
    made = tmp_path / "repositories"
    repos = {name: _repository(FIXTURE / rel, made / name) for name, rel in REPOS.items()}
    context = _repository(FIXTURE / "context", made / "harbourline-context")
    urls = {name: f"file://{path}" for name, path in repos.items()}
    asked: list[str] = []

    def clone_url(self, repo):
        asked.append(repo)
        return urls.get(repo, f"file://{tmp_path}/nowhere/{repo}")

    monkeypatch.setattr(ProductModule, "_clone_url", clone_url)
    local = {"kind": "local", "repo": "harbourline", "options": {}}
    project = Project(name="harbourline", repo_path=str(repos["harbourline"]),
                      tracker=ProviderRef(**local), forge=ProviderRef(**local),
                      ci=ProviderRef(kind="none", repo="harbourline", options={}),
                      product=ProductConfig(docs_repo="harbourline-context", admins=["ines"]))
    return Bed(tmp=tmp_path, cache=cache, repos=repos, context=context, urls=urls, asked=asked,
               project=project)


def _declare(bed: Bed, *repos: str) -> None:
    """The context repository's `sources:`, rewritten and committed."""
    manifest = bed.context / ".openfactory" / "product.yaml"
    manifest.write_text("product: harbourline\nrequirements_dir: requirements\nsources:\n"
                        + "".join(f"  - {r}\n" for r in repos), encoding="utf-8")
    _commit(bed.context, "the product's sources, again")


class _Recording:
    """A harness that only records the prompt."""

    name = "recording"

    def __init__(self, answer: str = "ok") -> None:
        self.prompts: list[str] = []
        self.answer = answer

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        return AgentRunResult(ok=True, summary=self.answer)


class _Reader(_Recording):
    """A harness that DOES what the role is told: for every source the prompt lists, it lists the
    directory and opens a file in it — through the sandbox's `run`, at the root it was handed.
    Nothing here knows where the sources are except the prompt."""

    LISTED = re.compile(r"^  - `(src/[^`]+)/` — the repository `([^`]+)`", re.MULTILINE)

    def __init__(self) -> None:
        super().__init__("I read the code of every repository.")
        self.opened: dict[str, tuple[str, str]] = {}

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        for where, repo in self.LISTED.findall(prompt):
            code, listing = sandbox.run(
                workspace=workspace, timeout=30,
                command=f"find {where} -type f \\( -name '*.py' -o -name '*.ts' \\) | sort")
            files = [f for f in listing.split() if f.strip()]
            wanted = OPENS[repo][0]
            path = next((f for f in files if f.endswith(wanted)), files[0] if files else "")
            if code == 0 and path:
                rc, text = sandbox.run(workspace=workspace, command=f"cat {path}", timeout=30)
                if rc == 0:
                    self.opened[repo] = (path, text)
        return super().ask(sandbox=sandbox, workspace=workspace, prompt=prompt, phase=phase)


def _secret_server() -> tuple[http.server.HTTPServer, str]:
    """A forge that refuses every credential it is shown — `401` to every request."""

    class Refuses(http.server.BaseHTTPRequestHandler):
        def _no(self) -> None:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="forge"')
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_POST = _no

        def log_message(self, *args) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Refuses)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://x-access-token:{SECRET}@127.0.0.1:{server.server_address[1]}/o/r.git"


def _closed_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── 1. every declared source is in the turn's view, and the role opens code in each ────────────

def test_the_turns_view_holds_code_from_every_declared_source(bed):
    module = bed.module()
    module._workspace()
    root = Path(module._combined)

    held = {m.repo: m for m in module.mounts()}
    assert sorted(held) == sorted(REPOS), held
    assert all(m.path and not m.why for m in held.values()), held
    for repo, (rel, line) in OPENS.items():
        assert line in (root / held[repo].path / rel).read_text(), (repo, held[repo].path)
    assert held["harbourline"].own and not held["harbourline-pricing"].own
    assert Path(module._turn_view) == root, "the role read a shared view, not its turn's own"


def test_the_role_opens_a_file_in_every_source_with_its_own_tools(bed):
    """The acceptance, driven: the stub harness finds the sources where the prompt says they are,
    lists each through the sandbox, and opens a file — and what it read is the fixture's code."""
    reader = _Reader()
    answer = bed.module(agent=reader).answer("where is the freight price computed?")

    assert answer.ok, answer
    assert sorted(reader.opened) == sorted(REPOS), reader.opened
    for repo, (path, text) in reader.opened.items():
        rel, line = OPENS[repo]
        assert path.endswith(rel) and line in text, (repo, path)
        assert text == (FIXTURE / REPOS[repo] / rel).read_text()


def test_every_source_is_named_in_the_prompt_with_the_repository_it_is(bed):
    harness = _Recording()
    bed.module(agent=harness).answer("what repositories is the product made of?")
    prompt = harness.prompts[0]

    for repo in REPOS:
        assert re.search(rf"`src/{re.escape(repo)}/` — the repository `{repo}`", prompt), repo
    assert "this project's own" in prompt
    assert "could NOT be opened" not in prompt, "a whole product reads as a partial one"


# ── 2. a source that cannot be mounted is named, with why ──────────────────────────────────────

def test_a_source_the_credential_may_not_read_is_named_as_not_authorised(bed):
    server, url = _secret_server()
    try:
        bed.urls["harbourline-tracking"] = url
        harness = _Recording()
        module = bed.module(agent=harness)
        module.answer("when does the tracking service tell a shipper about a delay?")
    finally:
        server.shutdown()
    prompt = harness.prompts[0]

    assert f"- `harbourline-tracking` — {mount.NOT_AUTHORISED}" in prompt
    assert "could NOT be opened for this conversation" in prompt
    assert "never conclude anything about code you did not see" in prompt
    # the other three are still there: one source's trouble never costs the others
    assert all(f"`src/{r}/`" in prompt for r in REPOS if r != "harbourline-tracking")
    assert "`src/harbourline-tracking/`" not in prompt


def test_a_source_whose_forge_cannot_be_reached_is_named_as_unreachable(bed):
    bed.urls["harbourline-web"] = f"http://127.0.0.1:{_closed_port()}/acme/web.git"
    harness = _Recording()
    bed.module(agent=harness).answer("what does the quote page show?")

    assert f"- `harbourline-web` — {mount.UNREACHABLE}" in harness.prompts[0]


def test_a_source_that_does_not_exist_is_named_as_not_found(bed):
    bed.urls["harbourline-pricing"] = f"file://{bed.tmp}/gone/pricing.git"
    harness = _Recording()
    bed.module(agent=harness).answer("how is freight priced?")

    assert f"- `harbourline-pricing` — {mount.NOT_FOUND}" in harness.prompts[0]


def test_the_team_hears_of_a_missing_source_as_the_prompt_says_it_already_has(bed, monkeypatch):
    """The prompt tells the role "the team already knows" when code is missing — so the factory's
    impediment opens for ANY declared source that could not be mounted, not only the project's own,
    and closes on the turn where none is missing. One verdict per turn."""
    from openfactory.ops.impediment import PRODUCT_NO_CODE
    from openfactory.product import module as product_module

    filed: list[tuple[str, bool, str]] = []
    monkeypatch.setattr(product_module, "_tell_the_factory",
                        lambda project, cause, detail, *, ok: filed.append((cause, ok, detail)))
    bed.urls["harbourline-web"] = f"file://{bed.tmp}/gone/web.git"
    bed.module()._workspace()
    said = [(ok, detail) for cause, ok, detail in filed if cause == PRODUCT_NO_CODE]

    assert len(said) == 1 and said[0][0] is False, said
    assert f"harbourline-web: {mount.NOT_FOUND}" in said[0][1]

    filed.clear()
    bed.urls["harbourline-web"] = f"file://{bed.repos['harbourline-web']}"
    bed.module()._workspace()
    assert [(c, ok) for c, ok, _ in filed if c == PRODUCT_NO_CODE] == [(PRODUCT_NO_CODE, True)]


def test_the_projects_own_repository_is_named_when_the_product_does_not_declare_it(bed):
    """The boundary, said: the registry names `harbourline`, `sources:` does not — so it is named
    as not declared, and the role is told so rather than told the product has no bookings code."""
    _declare(bed, "harbourline-pricing", "harbourline-web")
    module = bed.module()
    module._workspace()
    held = {m.repo: m for m in module.mounts()}

    assert held["harbourline"].why == mount.NOT_DECLARED and not held["harbourline"].path
    role_text = "\n".join(module._role()._sources_section())
    assert f"- `harbourline` — {mount.NOT_DECLARED}" in role_text


def test_an_entry_that_names_no_repository_is_named_and_never_fetched(bed):
    _declare(bed, "harbourline", "not a repository/at all/four/deep")
    module = bed.module()
    module._workspace()
    missing = {m.repo: m.why for m in module.mounts() if not m.path}

    assert list(missing.values()) == [mount.UNREADABLE_ENTRY], missing
    assert bed.asked == ["harbourline"], "an unreadable entry was handed to the forge"


# ── 3. nothing outside `sources:`, and no credential anywhere ──────────────────────────────────

def test_nothing_outside_sources_is_ever_fetched_or_placed(bed):
    """`harbourline` is the registry's own repository; the product declares two others. Only
    those two are asked of the forge, cloned, and placed — the project's own included in the
    boundary like any other."""
    _declare(bed, "harbourline-pricing", "harbourline-web")
    module = bed.module()
    module._workspace()
    root = Path(module._combined)

    assert sorted(bed.asked) == ["harbourline-pricing", "harbourline-web"], bed.asked
    assert sorted(p.name for p in (root / "src").iterdir()) == ["harbourline-pricing",
                                                                "harbourline-web"]
    assert sorted(bed.masters()) == ["harbourline-pricing", "harbourline-web"]


def test_a_source_the_product_stops_declaring_leaves_the_shared_view_too(bed):
    """A worktree left under the stable root would be read by a turn that fell back to it — a
    repository outside `sources:`, one fallback away."""
    first = bed.module()
    first._workspace()
    shared = bed.cache / "harbourline-view" / "src"
    assert (shared / "harbourline-web").is_dir()

    _declare(bed, "harbourline", "harbourline-pricing", "harbourline-tracking")
    later = bed.module()
    later._workspace()

    assert not (shared / "harbourline-web").exists()
    assert not (Path(later._combined) / "src" / "harbourline-web").exists()


def test_a_url_in_sources_is_cloned_from_the_projects_forge_not_from_its_host(monkeypatch):
    """The declaration names a repository; the forge chooses the host. A URL somebody wrote into
    the context repository is read for the coordinate it names, and never handed to git."""
    from openfactory.contracts.product import ProductDocs

    docs = ProductDocs(product="p", sources=["https://tok@evil.example/Acme/Web.git",
                                             "Acme/API", "acme/jobs?host=evil.example",
                                             "a/b/c/d/e"])
    monkeypatch.setattr("openfactory.product.loader._read_docs_manifest",
                        lambda path: (docs, ""))
    got = mount.declared("/anywhere")

    assert got.sources == (("acme/web", "acme/web"), ("acme/api", "Acme/API"),
                           ("acme/jobs", "acme/jobs")), got
    assert list(got.refused) == ["a/b/c/d/e"]
    assert "tok" not in repr(got) and "evil.example" not in repr(got)


def test_no_credential_reaches_a_path_a_prompt_a_log_or_the_disk(bed, caplog):
    """A clone URL carries the token. The prompt gets a fixed sentence, the log a scrubbed one,
    the cache persists the public URL — and nothing under the cache is named after it."""
    bed.urls["harbourline-pricing"] = bed.urls["harbourline-pricing"].replace(
        "file://", f"file://x-access-token:{SECRET}@")
    server, url = _secret_server()
    bed.urls["harbourline-tracking"] = url
    harness = _Recording()
    try:
        with caplog.at_level(logging.DEBUG):
            bed.module(agent=harness).answer("how is freight priced?")
    finally:
        server.shutdown()

    assert SECRET not in harness.prompts[0]
    assert SECRET not in caplog.text
    for where, dirs, files in os.walk(bed.cache):
        for name in dirs + files:
            assert SECRET not in name, os.path.join(where, name)
            path = Path(where) / name
            if path.is_file() and not path.is_symlink():
                assert SECRET.encode() not in path.read_bytes(), path


# ── 4. partial, sparse, and made once ──────────────────────────────────────────────────────────

def _missing_objects(master: Path, rev: str = "--all") -> set[str]:
    listed = _git(master, "rev-list", "--objects", "--missing=print", rev)
    return {line[1:] for line in listed.splitlines() if line.startswith("?")}


def _blob(repo: Path, rev: str, path: str) -> str:
    return _git(repo, "rev-parse", f"{rev}:{path}").strip()


def test_nothing_is_cloned_before_a_turn_mounts_the_sources(bed):
    module = bed.module()
    assert bed.masters() == {}, "a source was fetched before any turn needed it"
    module._workspace()
    assert sorted(bed.masters()) == sorted(REPOS)


def test_every_source_is_a_partial_clone_that_never_fetched_its_history(bed):
    """The history's blobs are most of a long-lived repository's weight, and none is fetched."""
    pricing = bed.repos["harbourline-pricing"]
    old = _blob(pricing, "HEAD", "pricing/freight.py")
    (pricing / "pricing" / "freight.py").write_text(
        (pricing / "pricing" / "freight.py").read_text().replace("0.42", "0.44"))
    _commit(pricing, "a new rate on the Brazil lane")

    bed.module()._workspace()
    masters = bed.masters()

    for repo, master in masters.items():
        assert _git(master, "config", "--get", "remote.origin.promisor").strip() == "true", repo
    assert old in _missing_objects(masters["harbourline-pricing"]), (
        "the old freight.py was fetched — the clone is whole, not partial")


def test_the_web_front_ends_pictures_and_font_are_left_out_and_never_fetched(bed):
    module = bed.module()
    module._workspace()
    web = next(m for m in module.mounts() if m.repo == "harbourline-web")
    master = bed.masters()["harbourline-web"]
    origin = bed.repos["harbourline-web"]

    assert web.left_out == ("assets",), web
    assert not (Path(module._combined) / web.path / "assets").exists()
    assert (Path(module._combined) / web.path / "src" / "quote.ts").is_file()
    assert {_blob(origin, "HEAD", "assets/images/logo.png"),
            _blob(origin, "HEAD", "assets/fonts/harbour.woff2")} <= _missing_objects(master)
    prompt = "\n".join(module._role()._sources_section())
    assert "left out of this checkout" in prompt and "`assets/`" in prompt


def test_the_next_turn_clones_nothing_and_fetches_no_object(bed):
    first = bed.module()
    first._workspace()
    first.release()
    before = {repo: (m.stat().st_ino, sorted(p.name for p in (m / ".git/objects/pack").iterdir()))
              for repo, m in bed.masters().items()}

    later = bed.module()
    later._workspace()

    after = {repo: (m.stat().st_ino, sorted(p.name for p in (m / ".git/objects/pack").iterdir()))
             for repo, m in bed.masters().items()}
    assert after == before, "a source was cloned again, or fetched objects, with nothing moved"
    assert all(m.path for m in later.mounts())


def test_a_source_that_moved_is_up_to_date_on_the_next_turn_and_still_partial(bed):
    bed.module()._workspace()
    tracking = bed.repos["harbourline-tracking"]
    eta = tracking / "tracking" / "eta.py"
    eta.write_text(eta.read_text().replace("hours=6", "hours=4"))
    _commit(tracking, "four hours is late enough")

    later = bed.module()
    later._workspace()
    held = {m.repo: m for m in later.mounts()}

    assert "hours=4" in (Path(later._combined) / held["harbourline-tracking"].path
                         / "tracking" / "eta.py").read_text()
    assert _git(bed.masters()["harbourline-tracking"], "config", "--get",
                "remote.origin.promisor").strip() == "true"


# ── read-only, and nothing leading out ─────────────────────────────────────────────────────────

def test_a_mounted_source_is_read_only(bed):
    module = bed.module()
    module._workspace()
    for m in module.mounts():
        for where, _dirs, files in os.walk(Path(module._combined) / m.path):
            for name in files:
                mode = os.stat(os.path.join(where, name)).st_mode
                assert not mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH), (m.repo, name)


def test_no_read_follows_a_link_out_of_its_tree(bed):
    """A repository can hold a link to anywhere: an absolute one, one that climbs out, one into
    another client's checkout. Only a link that stays inside its own tree reaches the view — and
    no `.git` pointer into the cache does either."""
    for repo, name in ((bed.repos["harbourline-pricing"], "pricing"), (bed.context, "docs")):
        (repo / "etc-hosts").symlink_to("/etc/hosts")
        (repo / "climbs").symlink_to("../../..")
        (repo / "stays").symlink_to("README.md" if name == "pricing" else "domain/glossary.md")
        _commit(repo, "links")
    module = bed.module()
    module._workspace()
    root = Path(module._combined)
    pricing = root / next(m.path for m in module.mounts() if m.repo == "harbourline-pricing")

    for tree in (pricing, root / "docs"):
        assert not os.path.lexists(tree / "etc-hosts") and not os.path.lexists(tree / "climbs")
        assert (tree / "stays").is_symlink() and (tree / "stays").read_text()
    escaping = [p for p in root.rglob("*") if p.is_symlink()
                and os.path.commonpath([os.path.realpath(p), os.path.realpath(root)])
                != os.path.realpath(root)]
    assert not escaping, escaping
    assert not any(p.name == ".git" for p in (root / "src").rglob("*")), "a pointer into the cache"


# ── 5. the bound reads every source's bundle ───────────────────────────────────────────────────

def test_the_bound_reads_every_sources_bundle(bed):
    """`Chargeable weight` is the pricing service's concept, published in its own folder. A bound
    that read the registry project's bundle alone graded it "not in the bundle"."""
    from openfactory.product.reading import ALTA

    module = bed.module(agent=_Recording("It works like this.\n[[USO: Chargeable weight]]"))
    answer = module.answer("is a light, bulky pallet charged on its weight?")
    homes = [p.name for p in module._okf_dirs()]

    assert homes == ["harbourline", "harbourline-pricing"], homes
    assert answer.reading.confidence == ALTA, (answer.reading.confidence,
                                               answer.reading.bounded_by)
    assert answer.reading.verified["concepts"] == {"Chargeable weight": "fresh"}


def test_a_concept_no_source_publishes_is_still_graded_missing(bed):
    from openfactory.product.reading import BAIXA

    module = bed.module(agent=_Recording("It works like this.\n[[USO: Delay notices]]"))
    answer = module.answer("when is a shipper told about a delay?")

    assert answer.reading.confidence == BAIXA
    assert answer.reading.verified["concepts"] == {"Delay notices": "missing"}


# ── 6. the map, checked, and the onboarding documents, named ───────────────────────────────────

def test_the_module_maps_are_named_only_after_they_were_checked(bed):
    harness = _Recording()
    bed.module(agent=harness).answer("which module computes the chargeable weight?")
    prompt = harness.prompts[0]

    for repo in ("harbourline", "harbourline-pricing", "harbourline-web"):
        assert (f"`{repo}`: `docs/.okf/repos/{repo}/modules.yaml` — checked, it matches "
                f"`src/{repo}/`") in prompt, repo
    assert f"`harbourline-tracking`: {mount.NO_MAP}" in prompt


def test_a_map_the_code_moved_past_is_not_given(bed):
    pricing = bed.repos["harbourline-pricing"]
    (pricing / "pricing" / "discounts.py").write_text("def loyalty(freight): return freight\n")
    _commit(pricing, "a module the map has never seen")
    harness = _Recording()
    bed.module(agent=harness).answer("which module computes the chargeable weight?")
    prompt = harness.prompts[0]

    assert f"`harbourline-pricing`: {mount.MAP_STALE}" in prompt
    assert "`docs/.okf/repos/harbourline-pricing/modules.yaml` — checked" not in prompt
    assert "`docs/.okf/repos/harbourline/modules.yaml` — checked" in prompt


def test_the_onboarding_documents_are_named_in_the_prompt(bed):
    harness = _Recording()
    bed.module(agent=harness).answer("how do the services talk to each other?")
    prompt = harness.prompts[0]

    for path in ("docs/docs/architecture/", "docs/docs/invariants.md",
                 "docs/docs/open-questions.md", "docs/docs/survey.md"):
        assert f"- `{path}` — " in prompt, path


# ── the pieces, alone ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("said, why", [
    ("fatal: Authentication failed for 'https://github.com/o/r.git/'", mount.NOT_AUTHORISED),
    ("fatal: unable to access 'https://x/': The requested URL returned error: 403",
     mount.NOT_AUTHORISED),
    ("fatal: could not read Username for 'https://github.com': terminal prompts disabled",
     mount.NOT_AUTHORISED),
    ("remote: Repository not found.\nfatal: repository 'https://github.com/o/r.git/' not found",
     mount.NOT_FOUND),
    ("remote: TF401019: The Git repository with name or identifier r does not exist",
     mount.NOT_FOUND),
    ("fatal: Remote branch develop not found in upstream origin", mount.NO_BRANCH),
    ("fatal: unable to access 'https://x/': Could not resolve host: x", mount.UNREACHABLE),
    ("fatal: unable to access 'http://127.0.0.1:9/': Failed to connect to 127.0.0.1 port 9",
     mount.UNREACHABLE),
    ("something git has never said", mount.NOT_CHECKED_OUT),
])
def test_what_git_said_becomes_one_fixed_sentence(said, why):
    assert mount.why_not(said) == why


@pytest.mark.parametrize("paths, cone, left_out", [
    (["README.md", "src/a.py", "lib/b.py"], None, []),
    (["README.md", "src/a.ts", "assets/logo.png", "assets/f.woff2"], ["src"], ["assets"]),
    (["web/index.html", "web/img/a.png", "api/x.py"], None, []),
    (["web/src/a.ts", "web/img/a.png", "api/x.py"], ["api", "web/src"], ["web/img"]),
    (["README.md", "media/v.mp4"], [], ["media"]),
])
def test_the_cone_leaves_out_only_directories_of_weight(paths, cone, left_out):
    from openfactory.runtime.repo_cache import sparse_cone

    assert sparse_cone(paths) == (cone, left_out)


def test_the_credential_rides_in_the_environment_and_the_public_url_is_what_git_keeps(monkeypatch):
    """What git may write down is the public URL; the credentialed one is a rewrite held in the
    environment of the git processes alone — and a deployment's own `GIT_CONFIG_*` entries stay."""
    from openfactory.runtime.repo_cache import _credential_env

    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    url = f"https://x-access-token:{SECRET}@github.com/acme/web.git"
    public, env = _credential_env(url)

    assert public == "https://github.com/acme/web.git"
    assert env["GIT_CONFIG_COUNT"] == "2" and "GIT_CONFIG_KEY_0" not in env
    assert env["GIT_CONFIG_KEY_1"] == f"url.{url}.insteadOf"
    assert env["GIT_CONFIG_VALUE_1"] == public and env["GIT_TERMINAL_PROMPT"] == "0"
    assert _credential_env("https://github.com/acme/web.git")[1] == {"GIT_TERMINAL_PROMPT": "0"}


def test_what_git_said_is_kept_without_the_credential_and_logged_without_it(tmp_path, caplog):
    from openfactory.runtime.repo_cache import SparseRepoCache

    cache = SparseRepoCache(tmp_path)
    with caplog.at_level(logging.WARNING):
        cache._failed("acme--source--web", f"fatal: unable to access 'http://x-access-token:"
                                           f"{SECRET}@forge.example/acme/web.git/': The "
                                           f"requested URL returned error: 403")

    assert SECRET not in cache.failure and "forge.example" in cache.failure
    assert SECRET not in caplog.text
    assert mount.why_not(cache.failure) == mount.NOT_AUTHORISED


def test_two_sources_of_one_name_are_never_placed_over_each_other():
    from openfactory.product.workspace import _placements

    assert _placements(["acme/web", "partner/web", "acme/api"]) == {
        "acme/web": "acme--web", "partner/web": "partner--web", "acme/api": "api"}
