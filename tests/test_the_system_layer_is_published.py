"""The system layer is published in the context repository, the way derived knowledge is (#268).

Against REAL git: the four fixture repositories and the context repository are bare remotes here,
checked out by a real `RepoCache`, and the refresh pushes a real commit. What is held:

  - the layer lands at `.okf/system/`, beside `.okf/repos/` and `docs/`, which do not move;
  - it converges: sources whose declarations did not change publish nothing, whatever their commit;
    a changed declaration publishes once more;
  - the push happens with the product's semaphore held, and a semaphore another write holds costs
    this refresh (`busy`) and pushes nothing;
  - a source that cannot be checked out is named in what is published;
  - the knowledge refresh runs it after the module map, keeps the map's outcome as its own, and
    never lets it fail the refresh;
  - the product role is told where the map is only when it is really there.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
import yaml

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.knowledge import pipeline
from openfactory.knowledge.system import refresh
from openfactory.knowledge.system.render import FILES
from openfactory.product import semaphore
from openfactory.runtime.repo_cache import RepoCache

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "evaluation" / "quayside"
SOURCES = ("quayside-billing", "quayside-freight", "quayside-orders", "quayside-platform")
_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t"}


def _git(cwd: Path, *args: str) -> str:
    import os

    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, env={**os.environ, **_ENV, "HOME": str(cwd)}).stdout


def _remote(src: Path, work: Path, remote: Path, extra: dict[str, str] | None = None) -> Path:
    """A bare remote at `remote` holding `src` (plus `extra` files), on `main`, one commit."""
    shutil.copytree(src, work)
    for rel, text in (extra or {}).items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "seed")
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(remote)], check=True)
    return remote


@pytest.fixture
def product(tmp_path, monkeypatch):
    """The quayside product on one machine: five bare remotes, a registry entry, a cache."""
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    remotes = {name: _remote(FIXTURE / "sources" / name, tmp_path / "work" / name,
                             tmp_path / "remotes" / f"{name}.git") for name in SOURCES}
    remotes["quayside-context"] = _remote(
        FIXTURE / "context", tmp_path / "work" / "quayside-context",
        tmp_path / "remotes" / "quayside-context.git",
        extra={"docs/survey.md": "# Survey\n",
               ".okf/repos/quayside-orders/index.md": "# Knowledge bundle\n"})
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda project, repo="", *, token=None: str(remotes.get(repo, repo)))
    local = {"kind": "local", "repo": "quayside-orders", "options": {}}
    project = Project(name="quayside", repo_path=str(tmp_path / "work" / "quayside-orders"),
                      tracker=ProviderRef(**local), forge=ProviderRef(**local),
                      ci=ProviderRef(kind="none", repo="quayside-orders", options={}),
                      product=ProductConfig(docs_repo="quayside-context"))
    return project, remotes, RepoCache(tmp_path / "cache"), tmp_path


def _published(remote: Path, into: Path) -> Path:
    shutil.rmtree(into, ignore_errors=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(into)], check=True)
    return into


def _commits(remote: Path) -> list[str]:
    return _git(remote, "log", "--format=%s", "main").splitlines()


def _push_change(remote: Path, work: Path, rel: str, text: str) -> None:
    clone = work.parent / f"{work.name}-edit"
    shutil.rmtree(clone, ignore_errors=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    (clone / rel).write_text(text)
    _git(clone, "commit", "-qam", f"edit {rel}")
    _git(clone, "push", "-q", "origin", "main")


def test_the_layer_lands_beside_the_bundles_and_nothing_else_moves(product):
    project, remotes, cache, tmp = product
    assert refresh.refresh_system(project, cache=cache, generated_at="t1") == refresh.PUBLISHED
    seen = _published(remotes["quayside-context"], tmp / "seen")
    assert sorted(p.name for p in (seen / ".okf" / "system").iterdir()) == sorted(FILES)
    assert (seen / "docs" / "survey.md").read_text() == "# Survey\n"
    assert (seen / ".okf" / "repos" / "quayside-orders" / "index.md").is_file()
    system = yaml.safe_load((seen / ".okf" / "system" / "system.yaml").read_text())
    assert {c["name"] for c in system["components"]} == {
        "orders", "billing", "freight", "orders-db", "billing-db", "kafka"}
    assert {s["repo"]: s["commit"] for s in system["sources"]} == {
        name: _git(remotes[name], "rev-parse", "main").strip() for name in SOURCES}
    [head, *_] = _commits(remotes["quayside-context"])
    assert head == f"chore(okf): refresh the system layer @ {system['derived_key']}"
    # the bot wrote it, never the person running the suite
    assert _git(remotes["quayside-context"], "log", "-1", "--format=%an").strip() \
        == "OpenFactory Bot"


def test_unchanged_declarations_publish_nothing_and_a_changed_one_publishes_once(product):
    project, remotes, cache, tmp = product
    assert refresh.refresh_system(project, cache=cache) == refresh.PUBLISHED
    before = _commits(remotes["quayside-context"])
    # a commit that touches nothing the layer reads: a new head, the same map
    _push_change(remotes["quayside-freight"], tmp / "work" / "quayside-freight", "README.md",
                 "# Quayside Freight\n\nRewritten.\n")
    assert refresh.refresh_system(project, cache=cache) == refresh.UNCHANGED
    assert _commits(remotes["quayside-context"]) == before
    # a changed declaration: one more commit, carrying it
    proto = "proto/freight/v1/freight.proto"
    text = (FIXTURE / "sources" / "quayside-freight" / proto).read_text()
    _push_change(remotes["quayside-freight"], tmp / "work" / "quayside-freight", proto,
                 text.replace("rpc StreamRates", "rpc StreamTariffs"))
    assert refresh.refresh_system(project, cache=cache) == refresh.PUBLISHED
    assert len(_commits(remotes["quayside-context"])) == len(before) + 1
    seen = _published(remotes["quayside-context"], tmp / "seen")
    api = yaml.safe_load((seen / ".okf" / "system" / "api.yaml").read_text())
    assert [r["name"] for r in api["grpc"][0]["rpcs"]] == ["QuoteShipment", "StreamTariffs"]


def test_the_push_happens_with_the_product_semaphore_held(product, monkeypatch):
    project, _, cache, _ = product
    held: list[bool] = []
    real = pipeline.publish_dir

    def watching(*a, **k):
        held.append(semaphore.held_here(project))
        return real(*a, **k)

    monkeypatch.setattr(pipeline, "publish_dir", watching)
    assert refresh.refresh_system(project, cache=cache) == refresh.PUBLISHED
    assert held == [True]
    assert not semaphore.held_here(project)


def test_a_semaphore_another_write_holds_costs_this_refresh_and_pushes_nothing(product):
    project, remotes, cache, _ = product
    before = _commits(remotes["quayside-context"])
    taken, release = threading.Event(), threading.Event()

    def another_write():
        with semaphore.held(project):
            taken.set()
            release.wait(10)

    writer = threading.Thread(target=another_write)
    writer.start()
    try:
        assert taken.wait(10)
        assert refresh.refresh_system(project, cache=cache, timeout=0.2) == refresh.BUSY
    finally:
        release.set()
        writer.join(10)
    assert _commits(remotes["quayside-context"]) == before


def test_a_source_that_cannot_be_checked_out_is_named_in_what_is_published(product):
    project, remotes, cache, tmp = product
    shutil.rmtree(remotes["quayside-freight"])
    assert refresh.refresh_system(project, cache=cache) == refresh.PUBLISHED
    seen = _published(remotes["quayside-context"], tmp / "seen")
    system = yaml.safe_load((seen / ".okf" / "system" / "system.yaml").read_text())
    assert {s["repo"]: s["missing"] for s in system["sources"]}["quayside-freight"] \
        == "it could not be checked out"
    assert ("source-unreadable", "quayside-freight") in {
        (n["kind"], n["repo"]) for n in system["not_derived"]}
    # compose still builds freight from that source, so the component keeps where its code is…
    freight = next(c for c in system["components"] if c["name"] == "freight")
    assert (freight["repo"], freight["code_by"]) == ("quayside-freight", "build-context")
    # …and the call into it is said to be blind for that reason, not because freight has no API
    [call] = [n["detail"] for n in system["not_derived"] if "`freight`" in n["detail"]]
    assert "its source, `quayside-freight`, could not be read" in call
    assert ("orders", "freight", "network") in {
        (lk["from"], lk["to"], lk["kind"]) for lk in system["links"]}


def test_a_forge_that_cannot_name_a_source_costs_that_source_and_no_credential(product,
                                                                             monkeypatch):
    project, remotes, cache, _ = product
    real = remotes.copy()

    def naming(project, repo="", *, token=None):
        if repo == "quayside-billing":
            raise ValueError("no forge row for https://bot:tok-planted@forge.invalid/x")
        return str(real.get(repo, repo))

    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for", naming)
    trees, missing = refresh.gather(project, list(SOURCES), token=None, cache=cache)
    assert sorted(t.repo for t in trees) == sorted(set(SOURCES) - {"quayside-billing"})
    assert missing["quayside-billing"].startswith("the forge could not name its address")
    assert "tok-planted" not in missing["quayside-billing"]
    assert all(t.commit == _git(real[t.repo], "rev-parse", "main").strip() for t in trees)


def test_a_project_the_product_link_does_not_hold_for_publishes_nothing(product):
    project, remotes, cache, _ = product
    before = _commits(remotes["quayside-context"])
    stranger = project.model_copy(update={"name": "someone-else"})
    assert refresh.refresh_system(stranger, cache=cache) == refresh.NO_PRODUCT
    assert _commits(remotes["quayside-context"]) == before


def test_unchanged_is_decided_by_the_key_the_context_repository_carries(product):
    """`unchanged` is read from the `system.yaml` published in the context repository the refresh
    just synced — never from a memory of its own. A key edited there by hand is a map that no
    longer matches, and the next refresh publishes over it."""
    project, remotes, cache, tmp = product
    assert refresh.refresh_system(project, cache=cache, generated_at="one") == refresh.PUBLISHED
    seen = _published(remotes["quayside-context"], tmp / "seen")
    system_file = seen / ".okf" / "system" / "system.yaml"
    key = yaml.safe_load(system_file.read_text())["derived_key"]
    assert refresh.refresh_system(project, cache=cache, generated_at="two") == refresh.UNCHANGED
    system_file.write_text(system_file.read_text().replace(key, "0" * 16))
    _git(seen, "commit", "-qam", "a hand edit")
    _git(seen, "push", "-q", "origin", "main")
    assert refresh.refresh_system(project, cache=cache, generated_at="three") \
        == refresh.PUBLISHED
    seen = _published(remotes["quayside-context"], tmp / "seen-again")
    assert yaml.safe_load((seen / ".okf" / "system" / "system.yaml").read_text())[
        "derived_key"] == key


@pytest.mark.parametrize("linked", [".okf", ".okf/system"])
def test_a_link_in_the_context_repository_is_never_written_through(tmp_path, linked):
    """`.okf` — or `.okf/system` — committed to the context repository as a link to somewhere else
    on the worker would make the publisher's `rmtree` and copy land THERE. The shared publisher
    refuses, and whatever the link points at is exactly as it was. The module map's publish goes
    through the same door, so it is held by the same refusal."""
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "system").mkdir(parents=True)
    (elsewhere / "system" / "canary").write_text("still here\n")
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    link = work / linked
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(elsewhere if linked == ".okf" else elsewhere / "system")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "a link")
    remote = tmp_path / "context.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(remote)], check=True)
    before = _commits(remote)
    src = tmp_path / "src"
    src.mkdir()
    (src / "system.yaml").write_text("version: '1'\n")
    done = pipeline.publish_dir(src, str(remote), subpath=Path(".okf") / "system",
                                message="m", what="system layer")
    assert done == pipeline.FAILED
    assert sorted(p.name for p in (elsewhere / "system").iterdir()) == ["canary"]
    assert _commits(remote) == before


# ── the knowledge refresh runs it ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("map_outcome", "runs"), [
    ("published", True), ("unchanged", True), ("failed", True), ("no-repo", True),
    ("off", False), ("no-context", False)])
def test_the_knowledge_refresh_runs_the_layer_after_the_map(monkeypatch, map_outcome, runs):
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    order: list[str] = []
    monkeypatch.setattr(acts, "_do_refresh_knowledge",
                        lambda inp: order.append("map") or map_outcome)
    monkeypatch.setattr(acts, "_refresh_the_system_layer",
                        lambda inp: order.append("system") or "published")
    out = asyncio.run(acts.refresh_knowledge(KnowledgeRefreshInput(project="quayside")))
    assert out == map_outcome
    assert order == (["map", "system"] if runs else ["map"])


def test_a_failing_system_layer_never_fails_the_refresh(monkeypatch, caplog):
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    def boom(inp):
        raise RuntimeError("the layer broke")

    monkeypatch.setattr(acts, "_do_refresh_knowledge", lambda inp: "published")
    monkeypatch.setattr(acts, "_refresh_the_system_layer", boom)
    assert asyncio.run(acts.refresh_knowledge(KnowledgeRefreshInput(project="q"))) == "published"
    assert "system layer refresh failed for q" in caplog.text


def test_the_activity_hands_the_layer_the_registry_project_and_its_credential(monkeypatch):
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    seen = {}
    project = object()

    class _Registry:
        def get(self, name):
            seen["name"] = name
            return project

    monkeypatch.setattr(acts, "ProjectRegistry", _Registry)
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda p: "tok")
    monkeypatch.setattr("openfactory.knowledge.system.refresh.refresh_system",
                        lambda p, *, token: seen.update(project=p, token=token) or "published")
    assert acts._refresh_the_system_layer(KnowledgeRefreshInput(project="quayside")) \
        == "published"
    assert seen == {"name": "quayside", "project": project, "token": "tok"}


# ── the role is told where it is, only when it is there ─────────────────────────────────────────

def _module(root: Path):
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule

    ctx = ProductContext(link=ProductLink(active=True, docs_repo="quayside-context", kind="ok"),
                         docs_path=str(root / "docs"))
    module = ProductModule(Project(name="quayside", repo_path=str(root)), context=ctx)
    module._combined = str(root)
    module._mounted_code = str(root / "src" / "quayside-orders")
    return module


def test_the_role_is_told_where_the_system_map_is_only_when_it_is_there(tmp_path):
    from openfactory.contracts import AgentRunResult
    from openfactory.product.role import ProductRole

    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "quayside-orders").mkdir(parents=True)
    assert "system" not in _module(tmp_path).mounted()
    door = tmp_path / "docs" / ".okf" / "system" / "index.md"
    door.parent.mkdir(parents=True)
    door.write_text("# The system\n")
    mounted = _module(tmp_path).mounted()
    assert mounted["system"] == "docs/.okf/system"

    class _Harness:
        name = "recording"

        def __init__(self):
            self.prompts = []

        def ask(self, *, sandbox, workspace, prompt, phase="ask"):
            self.prompts.append(prompt)
            return AgentRunResult(ok=True, summary="ok")

    from openfactory.adapters.sandbox.base import Workspace

    for given, named in ((mounted, True), ({k: v for k, v in mounted.items() if k != "system"},
                                           False)):
        harness = _Harness()
        ProductRole(harness, mounted=given).answer(
            sandbox=None, workspace=Workspace(path="/tmp", branch="main", base_branch="main"),
            question="quem chama o serviço de frete?")
        assert ("`docs/.okf/system/index.md` maps the whole product" in harness.prompts[0]) \
            is named
