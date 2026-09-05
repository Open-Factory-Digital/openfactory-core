"""The merge re-authors the concepts its change invalidated — and the two manifests stop colliding.

TWO FINDINGS, ONE SLICE. First: concepts were written once, at the backfill, and never again —
`propose_concepts` had one caller, and the refresh that runs after every merge regenerated the
module map alone. Second, found on the way: the map and the OKF both published `manifest.yaml`
into `.okf/repos/<source>/`, with different schemas, and took turns destroying each other. No
test ran both writers on one directory, which is why it stood.

The fixtures are real repositories and the real writers — `write_okf`, `write_bundle`,
`propose_concepts` with fingerprints from `compute_checksums` — so what is exercised is what the
platform publishes. The activity test drives `_do_refresh_knowledge` itself, through the same
harness `test_knowledge_pipeline.py` uses, with only the harness and the budget faked.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.knowledge import read_bundle_dir
from openfactory.knowledge.bundle import (
    MANIFEST_FILE,
    MODULES_FILE,
    build_bundle,
    compute_checksums,
    write_bundle,
)
from openfactory.knowledge.contracts import Concept, ConceptSource, Gap, OkfManifest
from openfactory.knowledge.okf import (
    OKF_INDEX_FILE,
    OKF_MANIFEST_FILE,
    parse_manifest,
    read_concepts,
    read_manifest,
    render_manifest,
    write_okf,
)
from openfactory.onboarding import onboard
from openfactory.onboarding.concepts import modules_for_sources, propose_concepts
from openfactory.onboarding.context import RepoSurvey, SurveyedModule
from openfactory.onboarding.renew import STALE_GAP, Renewal, renew_concepts
from tests.test_knowledge_pipeline import (
    _SUBPATH,
    _client_repo,
    _context_repo,
    _git,
    _patch_activity,
)

ROOT = Path(__file__).resolve().parents[1]


# ── the collision: two manifests, one directory ─────────────────────────────────────────────────

def _source(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    (src / "billing").mkdir(parents=True)
    (src / "billing" / "rules.py").write_text("def charge():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    return src


def _map_into(shared: Path, repo: Path) -> None:
    """What the refresh does: the module map's two files, written beside whatever is there —
    produced by the real writer and copied in, the way `publish_bundle` copies `knowledge/`."""
    written = write_bundle(build_bundle(repo, commit="c1", generated_at="t"), repo, force=True)
    shared.mkdir(parents=True, exist_ok=True)
    for name in (MODULES_FILE, MANIFEST_FILE):
        shutil.copy(written / name, shared / name)


def _concept(path: str = "billing/rules.py", fingerprint: str = "abc",
             title: str = "Billing rules") -> Concept:
    return Concept(type="policy", title=title, status="draft",
                   sources=[ConceptSource(path=path, fingerprint=fingerprint, commit="c1")])


@pytest.mark.parametrize("okf_first", [True, False])
def test_the_map_and_the_okf_each_keep_their_own_manifest(tmp_path, okf_first):
    """MEASURED 2026-09-04, both orders. Backfill after map: the map's manifest was replaced by the
    OKF's, which pydantic accepted as a `BundleManifest` with EMPTY checksums — `is_stale` then
    called the map stale forever. Map after backfill: the OKF's manifest was replaced, and
    coverage, gaps and `source_commit` were lost in silence."""
    repo = _source(tmp_path)
    shared = tmp_path / "context" / ".okf" / "repos" / "acme--src"
    writes = [lambda: write_okf(shared, manifest=OkfManifest(source_commit="c2"),
                                concepts=[_concept()]),
              lambda: _map_into(shared, repo)]
    for write in (writes if okf_first else writes[::-1]):
        write()

    the_map = read_bundle_dir(shared)
    assert the_map is not None and the_map.manifest.checksums, (
        "the map's manifest was overwritten — the map reads as stale forever")
    the_okf = read_manifest(shared)
    assert the_okf is not None and the_okf.source_commit == "c2", (
        "the OKF's manifest was overwritten — coverage, gaps and source_commit are gone")
    assert [c.title for c in read_concepts(shared)] == ["Billing rules"]


def test_the_okf_manifest_is_not_called_manifest_yaml():
    assert OKF_MANIFEST_FILE != MANIFEST_FILE
    assert OKF_MANIFEST_FILE == "okf.yaml"


def test_the_manifest_round_trips():
    manifest = OkfManifest(source_commit="c9", generated_at="t", scope_limit="reading, not spec",
                           gaps=[Gap(kind="open-question", path="a.py", detail="why?")])

    back = parse_manifest(render_manifest(manifest))

    assert back is not None
    assert (back.source_commit, back.generated_at, back.scope_limit) == ("c9", "t", "reading, not spec")
    assert [g.kind for g in back.gaps] == ["open-question"]


@pytest.mark.parametrize("text", ["- not: a mapping\n", ": : :\n", ""])
def test_an_unreadable_manifest_is_none_not_a_crash(text):
    assert parse_manifest(text) is None


# ── authoring a CHOSEN set of modules, and finding the modules a file belongs to ─────────────────

def _survey(repo: Path, *paths: str) -> RepoSurvey:
    return RepoSurvey(repo=str(repo), modules=[
        SurveyedModule(name=p.replace("/", ".") or "root", path=p, purpose=p or "root",
                       purpose_is_folder_name=True, files=1, file_changes=1)
        for p in paths])


def test_modules_for_sources_takes_the_longest_owner_once_each():
    survey = _survey(Path("."), ".", "core", "core/sub")

    owners = modules_for_sources(survey, ["core/sub/x.py", "core/y.py", "core/sub/z.py", "top.py"])

    assert [m.path for m in owners] == [".", "core", "core/sub"]


def test_a_named_module_is_authored_and_the_ranking_is_not_consulted(tmp_path):
    repo = _source(tmp_path)
    (repo / "other").mkdir()
    (repo / "other" / "thing.py").write_text("x = 1\n", encoding="utf-8")
    survey = _survey(repo, "billing", "other")
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return json.dumps({"type": "policy", "title": "Other", "what_it_does": "x",
                           "business_rules": [{"text": "x is one", "cites": ["other/thing.py:1"]}]})

    concepts, _ = propose_concepts(survey, ask=ask, budget=5, modules=[survey.modules[1]])

    assert len(asked) == 1 and "other" in asked[0]
    assert [c.title for c in concepts] == ["Other"]


# ── the renewal ─────────────────────────────────────────────────────────────────────────────────

def _published(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """A source, and a bundle whose one concept was written against it with a REAL fingerprint."""
    repo = _source(tmp_path)
    fps = {c.file: c.sha256 for c in compute_checksums(repo)}
    bundle = tmp_path / "bundle"
    write_okf(bundle, manifest=OkfManifest(source_commit="c1", generated_at="day1"),
              concepts=[_concept(fingerprint=fps["billing/rules.py"])])
    (bundle / OKF_INDEX_FILE).write_text("# old index\n", encoding="utf-8")
    return repo, bundle, fps


def _harness(monkeypatch, answer: str | None, budget: int = 5) -> list[str]:
    """The backfill's seams, faked at the module the renewal imports them from."""
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return answer or ""

    monkeypatch.setattr(onboard, "semantic_pass_for",
                        lambda project, source: ((ask, "fake-harness") if answer is not None
                                                 else (None, "no harness on this machine")))
    monkeypatch.setattr(onboard, "_concept_budget", lambda project, source: budget)
    return asked


_REWRITE = json.dumps({
    "type": "policy", "title": "Billing rules", "what_it_does": "Charges twice now.",
    "business_rules": [{"text": "A charge is issued twice", "cites": ["billing/rules.py:2"]}],
})
_PROJECT = SimpleNamespace(name="p", language=None)


def test_nothing_published_is_nothing_to_renew(tmp_path):
    repo = _source(tmp_path)

    got = renew_concepts(_PROJECT, tmp_path / "empty", repo, commit="c2", generated_at="t")

    assert got == Renewal(0, 0, 0, 0, "nothing-published")
    assert not (tmp_path / "empty").exists()


def test_a_fresh_bundle_is_left_untouched(tmp_path, monkeypatch):
    repo, bundle, _ = _published(tmp_path)
    asked = _harness(monkeypatch, _REWRITE)
    before = (bundle / OKF_MANIFEST_FILE).read_text(encoding="utf-8")

    got = renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t")

    assert got.mode == "fresh" and not got.wrote
    assert asked == [], "a fresh bundle must cost no model call"
    assert (bundle / OKF_MANIFEST_FILE).read_text(encoding="utf-8") == before


def test_the_bytes_move_and_the_next_refresh_re_authors_the_concept(tmp_path, monkeypatch):
    """THE PRODUCT OWNER'S SENTENCE: the OKF updates after the code changes. Nobody asked a
    question; the file changed, so the concept that read it is rewritten — in place, same title,
    with the new fingerprint — and the manifest moves to the new commit."""
    repo, bundle, _ = _published(tmp_path)
    (repo / "billing" / "rules.py").write_text("def charge():\n    return 2\n", encoding="utf-8")
    asked = _harness(monkeypatch, _REWRITE)

    got = renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="day30")

    assert (got.broken, got.rewritten, got.left) == (1, 1, 0) and got.wrote
    assert len(asked) == 1 and "billing" in asked[0]
    [concept] = read_concepts(bundle)
    assert concept.sources[0].fingerprint == {
        c.file: c.sha256 for c in compute_checksums(repo)}["billing/rules.py"]
    assert "Charges twice now" in (bundle / "concepts" / "policy" / "billing-rules.md").read_text()
    manifest = read_manifest(bundle)
    assert (manifest.source_commit, manifest.generated_at) == ("c2", "day30")
    assert not [g for g in manifest.gaps if g.kind == STALE_GAP]
    assert "old index" not in (bundle / OKF_INDEX_FILE).read_text(encoding="utf-8")


def test_with_no_harness_the_broken_concept_becomes_a_named_gap(tmp_path, monkeypatch):
    """DATA, NOT SILENCE. This machine cannot rewrite it; the manifest says so, by title, so the
    index shows it until a round that can reaches it. The concept file itself is not touched."""
    repo, bundle, _ = _published(tmp_path)
    (repo / "billing" / "rules.py").write_text("changed\n", encoding="utf-8")
    _harness(monkeypatch, None)
    before = (bundle / "concepts" / "policy" / "billing-rules.md").read_text(encoding="utf-8")

    got = renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t")

    assert (got.broken, got.rewritten, got.left) == (1, 0, 1) and got.wrote
    [gap] = [g for g in read_manifest(bundle).gaps if g.kind == STALE_GAP]
    assert "'Billing rules'" in gap.detail and "no harness" in gap.detail
    assert gap.path == "billing/rules.py"
    assert (bundle / "concepts" / "policy" / "billing-rules.md").read_text(encoding="utf-8") == before


def test_over_budget_the_rest_is_left_as_gaps_and_the_gap_does_not_accumulate(tmp_path, monkeypatch):
    repo = _source(tmp_path)
    (repo / "other").mkdir()
    (repo / "other" / "thing.py").write_text("x = 1\n", encoding="utf-8")
    fps = {c.file: c.sha256 for c in compute_checksums(repo)}
    bundle = tmp_path / "bundle"
    write_okf(bundle, manifest=OkfManifest(source_commit="c1"), concepts=[
        _concept(fingerprint=fps["billing/rules.py"]),
        _concept(path="other/thing.py", fingerprint=fps["other/thing.py"], title="Other")])
    # two lines, so the rewrite's citation of line 2 can anchor — a one-line file would reject the
    # citation and leave the concept with a directory source, which is unverifiable, not stale
    (repo / "billing" / "rules.py").write_text("def charge():\n    return 9\n", encoding="utf-8")
    (repo / "other" / "thing.py").write_text("x = 2\n", encoding="utf-8")
    _harness(monkeypatch, _REWRITE, budget=1)

    first = renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t")
    assert (first.broken, first.rewritten, first.left) == (2, 1, 1)
    [gap] = [g for g in read_manifest(bundle).gaps if g.kind == STALE_GAP]
    assert "'Other'" in gap.detail and "over budget" in gap.detail

    # the next round recomputes the stale gaps rather than appending to last round's
    second = renew_concepts(_PROJECT, bundle, repo, commit="c3", generated_at="t2")
    assert second.broken == 1  # 'Billing rules' was rewritten against c2's bytes and holds
    assert len([g for g in read_manifest(bundle).gaps if g.kind == STALE_GAP]) == 1


def test_a_bundle_whose_manifest_is_gone_is_renewed_with_the_scope_statement(tmp_path,
                                                                             monkeypatch):
    """hermes's question on the first review: a bundle in the wild whose `manifest.yaml` was the
    OKF's is read as the map's (empty checksums), called stale, and overwritten by the map — so
    the renewal finds concepts and NO manifest. Measured: nothing published by this platform is in
    that state (the concepts pass never ran outside the suite before `okf.yaml` existed). Traced:
    the renewal started from an EMPTY manifest, and the index it wrote carried no scope statement
    — the sentence that stops a reader treating a machine reading as a specification. Now the
    default manifest carries the same sentence the backfill writes, from one constant."""
    from openfactory.knowledge.okf import OKF_INDEX_FILE, SCOPE_LIMIT
    repo, bundle, fps = _published(tmp_path)
    (bundle / OKF_MANIFEST_FILE).unlink()
    (repo / "billing" / "rules.py").write_text("def charge():\n    return 2\n", encoding="utf-8")
    _harness(monkeypatch, None)
    got = renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t")
    assert got.checked == 1 and got.broken == 1
    manifest = read_manifest(bundle)
    assert manifest is not None and manifest.scope_limit == SCOPE_LIMIT
    index = (bundle / OKF_INDEX_FILE).read_text(encoding="utf-8")
    assert "> Machine-generated from the code" in index, "the index says nothing about scope"


def test_the_backfill_and_the_renewal_share_the_scope_sentence():
    """Two spellings of the same sentence would drift, and a drifted scope statement is two
    bundles making different promises about the same repository."""
    from openfactory.knowledge.okf import SCOPE_LIMIT
    for name in ("openfactory/onboarding/onboard.py", "openfactory/onboarding/renew.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        assert "scope_limit=SCOPE_LIMIT" in src, name
        assert "Machine-generated from the code" not in src, f"{name} spells the sentence itself"
    assert "never a specification" in SCOPE_LIMIT


def test_a_failure_inside_costs_the_renewal_and_never_the_caller(tmp_path, monkeypatch):
    repo, bundle, _ = _published(tmp_path)
    (repo / "billing" / "rules.py").write_text("changed\n", encoding="utf-8")

    def boom(project, source):
        raise RuntimeError("no harness binary")

    monkeypatch.setattr(onboard, "semantic_pass_for", boom)

    got = renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t")

    assert got.mode == "failed" and not got.wrote


def test_a_renewal_never_deletes_a_concept_it_did_not_rewrite(tmp_path, monkeypatch):
    repo, bundle, fps = _published(tmp_path)
    (bundle / "concepts" / "policy" / "human-note.md").write_text(
        "---\ntype: policy\ntitle: Human note\nstatus: stable\n---\n# Human note\n", encoding="utf-8")
    (repo / "billing" / "rules.py").write_text("changed\n", encoding="utf-8")
    _harness(monkeypatch, _REWRITE)

    renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t")

    assert (bundle / "concepts" / "policy" / "human-note.md").is_file()
    assert {c.title for c in read_concepts(bundle)} == {"Billing rules", "Human note"}


# ── the activity: the merge is the trigger, and the schedule reaches the same line ─────────────

def _seed_concepts(context: Path, work: Path, tmp_path: Path) -> None:
    """Publish one concept into the context repo, written against the client's current bytes."""
    clone = tmp_path / "ctx-clone"
    subprocess.run(["git", "clone", "-q", str(context), str(clone)], check=True)
    fps = {c.file: c.sha256 for c in compute_checksums(work)}
    concept = Concept(type="policy", title="Decision rules", status="draft",
                      sources=[ConceptSource(path="core/rules.py", fingerprint=fps["core/rules.py"],
                                             commit="seed")])
    write_okf(clone / _SUBPATH, manifest=OkfManifest(source_commit="seed"), concepts=[concept])
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "backfill: one concept")
    _git(clone, "push", "-q", "origin", "HEAD")
    shutil.rmtree(clone)


def test_the_merge_time_refresh_re_authors_and_publishes(tmp_path, monkeypatch):
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, work = _client_repo(tmp_path)
    context = _context_repo(tmp_path, with_docs=True)
    acts = _patch_activity(monkeypatch, tmp_path, remote, context)
    inp = KnowledgeRefreshInput(project="p", issue="1")
    assert acts._do_refresh_knowledge(inp) == "published"        # the map, as before
    _seed_concepts(context, work, tmp_path)
    rewrite = json.dumps({
        "type": "policy", "title": "Decision rules", "what_it_does": "Decides by doubling.",
        "business_rules": [{"text": "doubles", "cites": ["core/rules.py:2"]}]})
    _harness(monkeypatch, rewrite)

    (work / "core" / "rules.py").write_text("def decide(x):\n    return x * 2\n", encoding="utf-8")
    _git(work, "commit", "-qam", "the change")
    _git(work, "push", "-q", "origin", "main")

    assert acts._do_refresh_knowledge(inp) == "published+concepts:1"
    files = _git(context, "ls-tree", "-r", "--name-only", "main").split()
    assert f"{_SUBPATH}/{OKF_MANIFEST_FILE}" in files and f"{_SUBPATH}/{MANIFEST_FILE}" in files
    body = _git(context, "show", f"main:{_SUBPATH}/concepts/policy/decision-rules.md")
    assert "Decides by doubling" in body
    # THE MAP'S SELF-REPORT DOES NOT COUNT OUR OWN OUTPUT. Since the concepts moved in beside the
    # map, the refresh copied the whole published bundle into `knowledge/` before building — and
    # the extension survey counted `okf.yaml`, `concepts/*.md` and `index.md` as unread files of
    # the CLIENT's repository. This client has no `.md` or `.yaml` of its own.
    import yaml

    published_map = yaml.safe_load(_git(context, "show", f"main:{_SUBPATH}/{MANIFEST_FILE}"))
    unread = {row["suffix"] for row in (published_map.get("unread_extensions") or [])}
    assert not unread & {".md", ".yaml"}, (
        f"the map counts our own bundle files as the client's unread files: {sorted(unread)}")
    # and the round after, with nothing changed, is a no-op — the renewal's own commit is not a
    # reason to renew again (it was: `index.md` made every next build differ, forever)
    assert acts._do_refresh_knowledge(inp) == "unchanged"


def test_a_broken_concept_alone_is_reason_to_publish(tmp_path, monkeypatch):
    """THE MAP IS CURRENT AND A CONCEPT IS NOT — the shape the mutation plan showed the guards
    above could not see, because there every renewal coincided with a source change. A concept
    published against bytes the tree never had (a bad backfill, a hand edit) is broken while the
    map's derived key is unchanged; the activity must publish for the renewal's sake alone."""
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, work = _client_repo(tmp_path)
    context = _context_repo(tmp_path, with_docs=True)
    acts = _patch_activity(monkeypatch, tmp_path, remote, context)
    inp = KnowledgeRefreshInput(project="p", issue="1")
    assert acts._do_refresh_knowledge(inp) == "published"
    clone = tmp_path / "ctx-clone"
    subprocess.run(["git", "clone", "-q", str(context), str(clone)], check=True)
    wrong = Concept(type="policy", title="Decision rules", status="draft",
                    sources=[ConceptSource(path="core/rules.py", fingerprint="0" * 64)])
    write_okf(clone / _SUBPATH, manifest=OkfManifest(source_commit="seed"), concepts=[wrong])
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "a concept that never matched")
    _git(clone, "push", "-q", "origin", "HEAD")
    _harness(monkeypatch, json.dumps({
        "type": "policy", "title": "Decision rules", "what_it_does": "Decides by identity.",
        "business_rules": [{"text": "identity", "cites": ["core/rules.py:1"]}]}))

    assert acts._do_refresh_knowledge(inp) == "published+concepts:1"
    assert acts._do_refresh_knowledge(inp) == "unchanged"


def test_the_activity_reaches_the_renewal_on_the_real_path():
    src = (ROOT / "openfactory" / "runtime" / "temporal" / "activities.py").read_text(encoding="utf-8")
    assert "renew_concepts(project, dest, Path(repo_path)" in src


def test_propose_concepts_has_exactly_the_callers_the_design_names():
    """ONE PATH. The backfill and the renewal, and nothing else, author concepts — a third caller
    is a second implementation of the same decision waiting to drift."""
    callers = sorted(
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "openfactory").rglob("*.py")
        if "propose_concepts(" in p.read_text(encoding="utf-8") and p.name != "concepts.py")
    assert callers == ["openfactory/onboarding/onboard.py", "openfactory/onboarding/renew.py"]
