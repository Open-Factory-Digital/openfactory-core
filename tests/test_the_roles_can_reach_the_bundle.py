"""The bundle reaches the two roles that have questions about the code — the PO and the tech-lead.

WIRING THESE TWO IS WHY THE BUNDLE WAS BUILT, and until this change it reached the coding agent
and nobody else: `openfactory/product/` and `openfactory/techlead/` contained ZERO reads of it,
while `product/role.py` cited the knowledge layer as its own precedent for injecting context
deterministically. A map nobody with a question can open answers none of them.

THE TWO ROLES REACH IT DIFFERENTLY, AND THE DIFFERENCE IS NOT A STYLE CHOICE. The product role's
context repository is already mounted for it, so the concepts are on its disk before it is asked
anything — it only ever needed to be TOLD. The tech-lead clones the SOURCE repository, and the
concepts live in the CONTEXT one, so its copy has to be fetched and carried into the fact pack.

AND EACH HALF HAS ITS OWN WAY OF LYING QUIETLY, which is what most of this file guards:

  - the PO's section is composed in the ORCHESTRATOR's process, where every path in `mounted` is
    relative to a workspace root this process is not standing in. A check made here answers about
    the worker's cwd — False everywhere — so the section would be dead on every project while
    reading as wired. `module.py::mounted` answers it where the absolute path is.
  - the tech-lead's fetch can come back empty two ways, and they are different facts. "Nothing has
    ever been published" is every project before its first backfill and is worth no words; "the
    context repository could not be read" is a failed read, and rendering it as the first tells a
    reader this codebase has no map — a claim produced by a read that failed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.knowledge.pipeline import Fetched, okf_subpath
from openfactory.product.role import ProductRole
from openfactory.techlead import pack
from openfactory.util import scratch


class _Agent:
    name = "fake"


def _mounted_with_bundle() -> dict[str, str]:
    return {"docs": "docs", "code": "code", "okf": "docs/.okf"}


# ── 1. the product role is TOLD, and only when it is true ───────────────────────────────────────

def test_the_section_names_the_index_when_the_bundle_is_mounted():
    role = ProductRole(_Agent(), mounted=_mounted_with_bundle())

    text = "\n".join(role._bundle_section())

    assert "docs/.okf/index.md" in text, "the role is told it has a bundle and not where it is"
    assert "file:line" in text, (
        "the one property that makes a concept checkable is not stated — a role told 'here are "
        "some claims' has no reason to prefer them to its own guess")


def test_a_project_with_no_bundle_is_told_NOTHING():
    """The defect `_sources_section` was written for, one artifact along: a role told it holds
    something it does not either guesses or refuses, and both cost a conversation. Every project
    is in this state until its first backfill."""
    role = ProductRole(_Agent(), mounted={"docs": "docs", "code": "code"})

    assert role._bundle_section() == []


def test_the_MOUNT_decides_and_not_the_process_cwd(monkeypatch, tmp_path):
    """THE HALF THAT WOULD HAVE BEEN DEAD IN PRODUCTION AND GREEN IN THE SUITE. `mounted` holds
    paths relative to the workspace root the AGENT stands in; this code runs in the orchestrator.
    A `Path(docs) / ".okf"` check here is answered by whatever directory the worker happens to be
    in — so a bundle that IS mounted reads as absent, on every project, silently.

    Pinned from the other side too: a `.okf/` that exists under THIS process's cwd must not
    conjure a section for a role whose workspace has none.
    """
    (tmp_path / "docs" / ".okf").mkdir(parents=True)
    (tmp_path / "docs" / ".okf" / "index.md").write_text("# door\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    role = ProductRole(_Agent(), mounted={"docs": "docs", "code": "code"})

    assert role._bundle_section() == [], (
        "the section is deciding from the orchestrator's own disk — which means on the real path "
        "it decides from a directory that has nothing to do with the project")


def test_the_boundary_is_STATED_because_it_is_the_load_bearing_half():
    """A concept says what the code DOES; a requirement says what MUST be true. `brownfield.py`
    already carries the cost of confusing them — *"turning the second into the first freezes bugs
    into promises: once a behaviour is an accepted requirement the factory DEFENDS it"* — so the
    section says the tier out loud, the way the domain glossary already does for its own facts."""
    text = "\n".join(ProductRole(_Agent(), mounted=_mounted_with_bundle())._bundle_section())

    assert "never turn a concept into an accepted requirement" in text
    assert "REQUIREMENT wins" in text, (
        "the role is handed two sources that can disagree and no rule for which one loses")
    assert "promises nothing" in text.lower()


def test_the_section_reaches_the_PROMPT():
    """BUILT-TESTED-REACHED-BY-NOTHING is this codebase's signature defect, and a section asserted
    only through its own method is exactly the shape it takes."""
    role = ProductRole(_Agent(), mounted=_mounted_with_bundle())

    prompt = role._prompt("write the requirements", "the body")

    assert "docs/.okf/index.md" in prompt


def test_mounted_reports_the_bundle_only_when_the_door_is_ON_DISK(tmp_path):
    """The absolute check, in the one place that holds an absolute path. `mounted` already makes
    this promise about the source code — *"a prompt that describes what is mounted cannot lie"* —
    and the bundle is the same promise one key along."""
    from openfactory.product.module import ProductModule

    root = tmp_path / "ws"
    (root / "docs").mkdir(parents=True)
    (root / "code").mkdir()
    fake = SimpleNamespace(_workspace=lambda: None, _combined=str(root),
                           _mounted_code=str(root / "code"))

    assert "okf" not in ProductModule.mounted(fake), "a bundle nobody published was announced"

    (root / "docs" / ".okf").mkdir()
    (root / "docs" / ".okf" / "index.md").write_text("# door\n", encoding="utf-8")

    assert ProductModule.mounted(fake)["okf"] == str(Path("docs") / ".okf"), (
        "the bundle is on disk and the prompt will not mention it")


# ── 2. the tech-lead's pack carries it WHOLE ────────────────────────────────────────────────────

def _root(tmp_path: Path) -> Path:
    (tmp_path / ".git" / "info").mkdir(parents=True)
    return tmp_path


def _bundle(tmp_path: Path) -> Path:
    """A bundle in the shape `fetch_bundle` returns one: an index beside the files it links."""
    here = tmp_path / "fetched"
    (here / "concepts" / "policy").mkdir(parents=True)
    (here / "index.md").write_text("# Knowledge bundle\n\n- [Billing](concepts/policy/b.md)\n",
                                   encoding="utf-8")
    (here / "concepts" / "policy" / "b.md").write_text("# Billing\n", encoding="utf-8")
    (here / "manifest.yaml").write_text("bundle_kind: source-repo\n", encoding="utf-8")
    return here


def test_the_pack_carries_the_bundle_WHOLE_and_names_it(tmp_path):
    """WHOLE, because the index's links are relative: a partial copy hands the role an index whose
    entries do not open. NAMED, because a file copied in and not listed in the manifest is a fact
    the role never learns it has — the same silence the manifest exists to prevent."""
    into = pack.write_pack(_root(tmp_path / "ws"), floor="# Floor\nrunning", board="", thread="",
                           comments={}, verdicts={}, bundle=_bundle(tmp_path))

    assert (into / "okf" / "index.md").is_file()
    assert (into / "okf" / "concepts" / "policy" / "b.md").is_file(), (
        "the index came without what it links — every entry in it is a dead end")
    assert f"{into.name}/okf/index.md" in (into / "README.md").read_text(encoding="utf-8")


def test_a_pack_with_no_bundle_says_nothing_about_one(tmp_path):
    into = pack.write_pack(_root(tmp_path / "ws"), floor="# Floor\nrunning", board="", thread="",
                           comments={}, verdicts={}, bundle=None)

    assert not (into / "okf").exists()
    assert "okf" not in (into / "README.md").read_text(encoding="utf-8")


def test_a_bundle_path_that_is_not_there_costs_the_bundle_and_not_the_pack(tmp_path):
    """The pack is the tech-lead's whole prompt once the inline render is shrunk. A missing
    directory must not take the floor, the board and the verdicts down with it."""
    into = pack.write_pack(_root(tmp_path / "ws"), floor="# Floor\nrunning", board="", thread="",
                           comments={}, verdicts={}, bundle=tmp_path / "never-fetched")

    assert into is not None and (into / "floor.md").is_file()
    assert not (into / "okf").exists()


# ── 3. the fetch, and the two ways of coming back with nothing ──────────────────────────────────

class _Project:
    name = "demo"
    repo_path = "/tmp/demo"
    forge = SimpleNamespace(repo="acme/api", kind="github")
    tracker = SimpleNamespace(repo="acme/api")
    product = SimpleNamespace(docs_repo="acme/api-context")


def _no_credentials(monkeypatch) -> None:
    import openfactory.credentials as creds
    from openfactory.adapters.forge import registry

    monkeypatch.setattr(creds, "forge_token_for", lambda p: "tok")
    monkeypatch.setattr(creds, "deployment_forge_token", lambda p: "tok")
    monkeypatch.setattr(registry, "clone_url_for",
                        lambda p, repo, token=None: f"https://x:{token}@example.invalid/{repo}")


def test_a_project_with_no_context_repository_reports_no_gap(monkeypatch):
    """AN ABSENCE IS NOT A GAP. Every project is in this state before its first backfill, and a
    warning printed on all of them is a warning nobody reads."""
    from openfactory.knowledge import pipeline
    from openfactory.techlead import conversation

    _no_credentials(monkeypatch)
    monkeypatch.setattr(pipeline, "fetch_bundle", lambda *a, **k: pytest.fail(
        "a project with no context repository paid for a clone"))
    project = _Project()
    project.product = SimpleNamespace(docs_repo="")

    assert conversation._bundle_for(project) == (None, [])


def test_nothing_published_yet_is_also_not_a_gap(monkeypatch):
    from openfactory.knowledge import pipeline
    from openfactory.techlead import conversation

    _no_credentials(monkeypatch)
    monkeypatch.setattr(pipeline, "fetch_bundle", lambda *a, **k: Fetched(None))

    assert conversation._bundle_for(_Project()) == (None, [])


def test_a_read_that_FAILED_becomes_a_named_gap(monkeypatch):
    """UNREADABLE IS NOT ABSENCE, and this is the seam where the two used to collapse into one
    `None`. Handed no `okf/` and told nothing, the tech-lead resolves it as "this codebase has no
    map" — a claim about the client's project made from a clone that never came back."""
    from openfactory.knowledge import pipeline
    from openfactory.techlead import conversation

    _no_credentials(monkeypatch)
    monkeypatch.setattr(pipeline, "fetch_bundle",
                        lambda *a, **k: Fetched(None, "the context repository could not be read"))

    got, gaps = conversation._bundle_for(_Project())

    assert got is None and len(gaps) == 1
    assert "could not be read" in gaps[0]
    assert "NOT" in gaps[0], (
        "the gap does not say what it is NOT, so it reads as 'this project has no bundle'")


def test_a_forge_that_cannot_build_a_url_costs_the_map_and_not_the_ANSWER(monkeypatch):
    """`answer()` never raises: a tech-lead that replies to a question with a traceback has not
    answered it. The registry raises on a forge kind it does not know, correctly."""
    from openfactory.adapters.forge import registry
    from openfactory.techlead import conversation

    _no_credentials(monkeypatch)

    def _boom(*a, **k):
        raise ValueError("no adapter for forge kind 'svn'")

    monkeypatch.setattr(registry, "clone_url_for", _boom)

    got, gaps = conversation._bundle_for(_Project())

    assert got is None and len(gaps) == 1


def test_the_credential_never_reaches_the_log_when_the_url_does(monkeypatch, caplog):
    """A failed clone embeds the tokened URL in its message, and the token sits well inside the
    first 120 characters — truncation is not redaction (`util/causes`)."""
    from openfactory.adapters.forge import registry
    from openfactory.techlead import conversation

    _no_credentials(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("clone failed: https://x:s3cr3t-token@example.invalid/acme/api-context")

    monkeypatch.setattr(registry, "clone_url_for", _boom)
    with caplog.at_level("WARNING"):
        conversation._bundle_for(_Project())

    assert "s3cr3t-token" not in caplog.text


def test_a_fetched_bundle_comes_back_with_no_gap(monkeypatch, tmp_path):
    from openfactory.knowledge import pipeline
    from openfactory.techlead import conversation

    _no_credentials(monkeypatch)
    here = _bundle(tmp_path)
    monkeypatch.setattr(pipeline, "fetch_bundle", lambda *a, **k: Fetched(here))

    assert conversation._bundle_for(_Project()) == (here, [])


def test_the_fetch_asks_for_THIS_SOURCE_repository_s_folder(monkeypatch):
    """D-2: one folder per source. A multirepo product's tech-lead asking for the `.okf/` root
    would get whichever bundle happened to be there."""
    from openfactory.knowledge import pipeline
    from openfactory.techlead import conversation

    _no_credentials(monkeypatch)
    seen: dict[str, object] = {}

    def _spy(url, *, subpath):
        seen["url"], seen["subpath"] = url, subpath
        return Fetched(None)

    monkeypatch.setattr(pipeline, "fetch_bundle", _spy)
    conversation._bundle_for(_Project())

    assert seen["subpath"] == okf_subpath("acme/api")
    assert "api-context" in str(seen["url"]), "the bundle was looked for in the SOURCE repository"


# ── 4. end to end: the fetch reaches the pack, and the checkout does not outlive it ──────────────

def _answered(monkeypatch, *, cloned: bool = True):
    """`_answer` with every vendor edge stubbed — the wire between the fetch and the pack is what
    is under test, and it is the half that was never guarded when the two halves were."""
    import openfactory.adapters.agent as agent_registry
    from openfactory.techlead import conversation

    class _Harness:
        def chat(self, *, sandbox, workspace, question, context):
            return {"text": "ok"}

    monkeypatch.setattr(conversation, "gather_jobs", lambda p: [])
    monkeypatch.setattr(conversation, "clone_repo",
                        lambda p: (scratch.make("test-bundle"), cloned))
    monkeypatch.setattr(conversation, "answer_text", lambda res: "an answer")
    monkeypatch.setattr(conversation, "_record_chat_spend", lambda *a, **k: None)
    monkeypatch.setattr(agent_registry, "build_techlead", lambda p: _Harness())
    conversation._answer(_Project(), "what is billing?", cap=None, can=(), thread="")


def test_the_fetched_bundle_reaches_write_pack_and_is_then_DISCARDED(monkeypatch, tmp_path):
    """Two properties on one wire. The bundle has to arrive — and the temp checkout it arrived in
    has to go, because one of those per question fills the worker's disk (the leak
    `discard_fetched_bundle` exists for, on a path that asks a question per chat message)."""
    from openfactory.knowledge import pipeline
    from openfactory.techlead import conversation

    _no_credentials(monkeypatch)
    here = _bundle(tmp_path)
    seen: dict[str, object] = {}
    monkeypatch.setattr(pipeline, "fetch_bundle", lambda *a, **k: Fetched(here))
    monkeypatch.setattr(pipeline, "discard_fetched_bundle",
                        lambda d: seen.__setitem__("discarded", d))

    real = pack.write_pack

    def _spy(root, **kw):
        seen["bundle"] = kw.get("bundle")
        return real(_root(tmp_path / "ws"), **kw)

    monkeypatch.setattr(conversation.pack, "write_pack", _spy)
    _answered(monkeypatch)

    assert seen.get("bundle") == here, "the tech-lead's pack was written without the bundle"
    assert seen.get("discarded") == here, "one temp checkout per question, kept for ever"


def test_a_question_with_no_checkout_does_not_pay_for_a_context_CLONE(monkeypatch):
    """With no workspace there is no pack, and nothing that would read a bundle. Fetching one
    anyway is a git clone spent on a file nobody will open."""
    from openfactory.techlead import conversation

    _no_credentials(monkeypatch)
    monkeypatch.setattr(conversation, "_bundle_for", lambda p: pytest.fail(
        "the bundle was fetched for a question that has nowhere to put it"))

    _answered(monkeypatch, cloned=False)


def test_the_gap_reaches_the_MANIFEST_the_model_reads(monkeypatch, tmp_path):
    """End to end for the failed read: a gap collected and never rendered is a gap nobody sees."""
    from openfactory.knowledge import pipeline
    from openfactory.techlead import conversation

    _no_credentials(monkeypatch)
    written: dict[str, object] = {}
    monkeypatch.setattr(pipeline, "fetch_bundle",
                        lambda *a, **k: Fetched(None, "the context repository could not be read"))

    real = pack.write_pack

    def _spy(root, **kw):
        into = real(_root(tmp_path / "ws"), **kw)
        written["readme"] = (into / "README.md").read_text(encoding="utf-8")
        return into

    monkeypatch.setattr(conversation.pack, "write_pack", _spy)
    _answered(monkeypatch)

    readme = str(written.get("readme", ""))
    assert "knowledge bundle could not be read" in readme
    assert "FAILED READS, not absences" in readme
