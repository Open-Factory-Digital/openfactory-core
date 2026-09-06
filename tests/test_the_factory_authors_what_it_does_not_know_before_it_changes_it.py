"""The factory authors what it does not know before it changes it (ADR-0046, decided 2026-09-06).

Under `okf_gate: enforce`, a change touching a file nothing describes was refused with the
question asked — author the knowledge, or merge by hand. On a legacy repository after a
five-concept backfill that is most changes, and a factory that stops to ask on nearly every pull
request is the opposite of the product. So before it asks, it answers: the same authoring the
backfill and the renewal use (`concepts.author_for_paths` — ONE authoring for every trigger),
aimed at the modules the dark files belong to, under the budget the project declares, written
into the fetched bundle, published, and the gate judges again. It parks only if still dark.
`advise` authors nothing, so the default spends nothing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from openfactory.contracts.state import JobState
from openfactory.knowledge import bundle as _bundle
from openfactory.knowledge.contracts import OkfManifest
from openfactory.knowledge.gate import DARK, GREEN
from openfactory.knowledge.okf import OKF_INDEX_FILE, read_concepts, read_manifest, write_okf
from openfactory.onboarding.concepts import author_for_paths
from openfactory.onboarding.cover import Covered, cover_paths
from tests.test_a_file_nothing_describes_is_the_least_safe_to_change import (
    _bundle_for_job,
    _concept,
    _job_repo,
    _run,
)
from tests.test_the_merge_re_authors_what_it_invalidated import (
    _PROJECT,
    _REWRITE,
    _harness,
    _source,
)

ROOT = Path(__file__).resolve().parents[1]


# ── one authoring for every trigger ─────────────────────────────────────────────────────────────

def test_the_authoring_aims_the_budget_at_the_modules_owning_the_paths(tmp_path, monkeypatch):
    repo = _source(tmp_path)
    asked = _harness(monkeypatch, _REWRITE)
    got = author_for_paths(_PROJECT, repo, ["billing/rules.py"], commit="c2", generated_at="t")
    assert got.mode == "fake-harness" and len(asked) == 1
    (concept,) = got.concepts
    assert [s.path for s in concept.sources] == ["billing/rules.py"]
    assert concept.sources[0].fingerprint == _bundle._sha256(
        (repo / "billing" / "rules.py").read_bytes())


def test_no_harness_is_an_answer_not_an_error(tmp_path, monkeypatch):
    repo = _source(tmp_path)
    asked = _harness(monkeypatch, None)
    got = author_for_paths(_PROJECT, repo, ["billing/rules.py"], commit="c2", generated_at="t")
    assert got.concepts == [] and got.mode == "no harness on this machine" and asked == []


def test_a_path_no_module_owns_costs_nothing(tmp_path, monkeypatch):
    repo = _source(tmp_path)
    asked = _harness(monkeypatch, _REWRITE)
    got = author_for_paths(_PROJECT, repo, ["elsewhere/x.py"], commit="c2", generated_at="t")
    assert got.concepts == [] and "no module" in got.mode and asked == []


def test_a_budget_of_zero_authors_nothing(tmp_path, monkeypatch):
    repo = _source(tmp_path)
    asked = _harness(monkeypatch, _REWRITE, budget=0)
    got = author_for_paths(_PROJECT, repo, ["billing/rules.py"], commit="c2", generated_at="t")
    assert got.concepts == [] and asked == []


def test_the_budget_goes_to_the_module_owning_the_path_not_to_the_ranked_one(tmp_path,
                                                                             monkeypatch):
    """THE FIXTURE THAT CAN SEE THE CUT. With one module, the ranking and the target coincide and
    `modules=` could be dropped unnoticed (a mutation survived exactly that way). Two modules —
    `alpha`, which the ranking picks first, and `zeta`, which owns the dark file — and a harness
    that answers about whichever module it was asked about."""
    import json
    import subprocess

    from openfactory.onboarding import onboard

    src = tmp_path / "src"
    (src / "alpha").mkdir(parents=True)
    (src / "zeta").mkdir()
    (src / "alpha" / "first.py").write_text("A = 1\n", encoding="utf-8")
    (src / "zeta" / "late.py").write_text("Z = 1\n", encoding="utf-8")
    # ALPHA OUTRANKS ZETA BY CHURN, not by luck: on a tie the ranking sorts by name DESCENDING and
    # `zeta` would come first anyway — which is exactly how the first version of this guard let
    # the mutation live. Three commits on alpha make the ranking's choice unmistakable.
    git = ["git", "-c", "user.email=t@t.dev", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], cwd=src, check=True)
    subprocess.run([*git, "add", "-A"], cwd=src, check=True)
    subprocess.run([*git, "commit", "-qm", "init"], cwd=src, check=True)
    for i in range(3):
        (src / "alpha" / "first.py").write_text(f"A = {i + 2}\n", encoding="utf-8")
        subprocess.run([*git, "commit", "-qam", f"alpha {i}"], cwd=src, check=True)
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        module, file = ("zeta", "late") if "zeta" in prompt else ("alpha", "first")
        return json.dumps({"type": "policy", "title": f"{module} rules", "what_it_does": "x",
                           "business_rules": [{"text": "r", "cites": [f"{module}/{file}.py:1"]}]})

    monkeypatch.setattr(onboard, "semantic_pass_for", lambda p, s: (ask, "fake"))
    monkeypatch.setattr(onboard, "_concept_budget", lambda p, s: 1)
    got = author_for_paths(_PROJECT, src, ["zeta/late.py"], commit="c", generated_at="t")
    assert len(prompts) == 1 and "zeta" in prompts[0], prompts
    (concept,) = got.concepts
    assert [c.path for c in concept.sources] == ["zeta/late.py"], (
        "the budget went to the ranked module, not to the one owning the dark file")


def test_the_renewal_and_the_gate_share_the_one_authoring():
    """`propose_concepts(modules=…)` behind ONE helper: a second path would answer the same
    question differently. The renewal's inline block joins it in a follow-up (it lives in the
    lines #54 changes)."""
    src = (ROOT / "openfactory/onboarding/cover.py").read_text(encoding="utf-8")
    assert "author_for_paths(" in src and "propose_concepts(" not in src


# ── the covering ────────────────────────────────────────────────────────────────────────────────

def _published(tmp_path: Path) -> tuple[Path, Path]:
    repo = _source(tmp_path)
    bundle = tmp_path / "bundle"
    write_okf(bundle, manifest=OkfManifest(source_commit="c1", generated_at="day1"),
              concepts=[])
    (bundle / OKF_INDEX_FILE).write_text("# old index\n", encoding="utf-8")
    return repo, bundle


def test_covering_writes_the_concepts_into_the_bundle_and_says_what_is_still_dark(tmp_path,
                                                                                  monkeypatch):
    repo, bundle = _published(tmp_path)
    _harness(monkeypatch, _REWRITE)
    got = cover_paths(_PROJECT, bundle, repo, ["billing/rules.py", "billing/tax.py"],
                      commit="c2", generated_at="t2")
    assert got == Covered(1, ("billing/rules.py",), ("billing/tax.py",), "fake-harness")
    assert [c.title for c in read_concepts(bundle)] == ["Billing rules"]
    manifest = read_manifest(bundle)
    assert manifest.source_commit == "c2" and manifest.scope_limit
    assert "Billing rules" in (bundle / OKF_INDEX_FILE).read_text(encoding="utf-8")
    assert got.summary() == "authored 1 concept(s) covering 1 of 2 undescribed file(s)"


def test_nothing_authored_leaves_the_bundle_byte_identical(tmp_path, monkeypatch):
    repo, bundle = _published(tmp_path)
    _harness(monkeypatch, None)
    before = {p.name: p.read_bytes() for p in bundle.iterdir() if p.is_file()}
    got = cover_paths(_PROJECT, bundle, repo, ["billing/rules.py"], commit="c2", generated_at="t")
    assert got.authored == 0 and got.left == ("billing/rules.py",)
    assert "no harness" in got.summary()
    assert {p.name: p.read_bytes() for p in bundle.iterdir() if p.is_file()} == before


def test_an_authoring_that_raises_costs_the_covering_and_never_the_job(tmp_path, monkeypatch):
    repo, bundle = _published(tmp_path)
    monkeypatch.setattr("openfactory.onboarding.cover.author_for_paths",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no agent here")))
    got = cover_paths(_PROJECT, bundle, repo, ["billing/rules.py"], commit="c2", generated_at="t")
    assert got.authored == 0 and got.mode.startswith("the authoring failed")


def test_nothing_to_cover_is_nothing_done(tmp_path):
    repo, bundle = _published(tmp_path)
    assert cover_paths(_PROJECT, bundle, repo, ["", "  "], commit="c", generated_at="t") == (
        Covered(0, (), (), "nothing to cover"))


# ── the station ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def covering(monkeypatch):
    """A covering that writes a real concept for `app.py` into the bundle it is handed — so the
    re-judgement is the real gate reading a real citation — and a publish that records."""
    from openfactory.orchestrator.machine import JobRunner

    calls: dict = {"cover": [], "publish": []}

    def fake_cover(project, bundle_dir, source, paths, *, commit, generated_at):
        calls["cover"].append(list(paths))
        fp = _bundle._sha256((Path(source) / "app.py").read_bytes())
        write_okf(Path(bundle_dir), manifest=read_manifest(Path(bundle_dir)),
                  concepts=[_concept("app.py", fp, "The value")])
        return Covered(1, ("app.py",), (), "fake-harness")

    def fake_publish(bundle_dir, remote_url, *, subpath, source_commit="", author=None):
        calls["publish"].append((remote_url, str(subpath), source_commit))
        return True

    monkeypatch.setattr("openfactory.onboarding.cover.cover_paths", fake_cover)
    monkeypatch.setattr("openfactory.knowledge.pipeline.publish_bundle", fake_publish)
    monkeypatch.setattr(JobRunner, "_okf_home",
                        lambda self: ("https://ctx/acme-context", Path(".okf/repos/o--app")))
    return calls


def test_under_enforce_a_dark_change_is_covered_published_and_judged_again(tmp_path, monkeypatch,
                                                                            covering):
    repo = _job_repo(tmp_path / "a")
    bundle = _bundle_for_job(tmp_path, repo)
    result, tracker, forge, _ = _run(tmp_path / "b", monkeypatch, mode="enforce", bundle=bundle)
    assert covering["cover"] == [["app.py"]]
    assert result.state is JobState.PR_OPEN, result.note
    assert result.knowledge_stance == GREEN and result.knowledge_authored == 1
    (url, subpath, commit) = covering["publish"][0]
    assert url == "https://ctx/acme-context" and subpath.endswith("o--app") and len(commit) == 40
    body = forge.opened["body"]
    assert "after authoring 1 concept(s) for what nothing described" in body
    assert "- 🟢 `app.py` — clear: described by 'The value'" in body
    assert not any("knowledge gate —" in c for c in tracker.comments), "it parked anyway"


def test_when_nothing_could_be_authored_the_change_is_parked_as_before(tmp_path, monkeypatch,
                                                                        covering):
    monkeypatch.setattr("openfactory.onboarding.cover.cover_paths",
                        lambda *a, **k: Covered(0, (), ("app.py",), "no harness on this machine"))
    repo = _job_repo(tmp_path / "a")
    bundle = _bundle_for_job(tmp_path, repo)
    result, tracker, forge, _ = _run(tmp_path / "b", monkeypatch, mode="enforce", bundle=bundle)
    assert result.state is JobState.ON_HOLD and result.knowledge_authored == 0
    assert covering["publish"] == [], "nothing was authored and something was published"
    assert any("`app.py`" in c and "merge by hand" in c for c in tracker.comments)


def test_advise_authors_nothing_so_the_default_spends_nothing(tmp_path, monkeypatch, covering):
    repo = _job_repo(tmp_path / "a")
    bundle = _bundle_for_job(tmp_path, repo)
    result, _, _, _ = _run(tmp_path / "b", monkeypatch, mode="advise", bundle=bundle)
    assert result.knowledge_stance == DARK and covering["cover"] == []
    assert result.knowledge_authored == 0


def test_nothing_published_is_not_covered_it_is_the_backfills_job(tmp_path, monkeypatch, covering):
    result, tracker, _, _ = _run(tmp_path, monkeypatch, mode="enforce", bundle=None)
    assert covering["cover"] == [] and result.state is JobState.ON_HOLD
    assert any("run the backfill" in c for c in tracker.comments)


def test_the_covering_runs_only_where_the_gate_is_dark_and_enforced():
    from openfactory.orchestrator import machine
    src = Path(machine.__file__).read_text(encoding="utf-8")
    gate = src[src.index("    def _knowledge_gate("):src.index("    def _author_first(")]
    assert ('mode == "enforce" and bundle is not None and report.stance() == "dark"' in gate
            and 'report.count("no-concept")' in gate)
