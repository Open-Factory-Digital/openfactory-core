"""The inventory joins the renewal path (#48 → #49): re-taken every round, written when it changed.

The backfill took the inventory once. A bundle whose concepts were all fresh then kept an
inventory of a tree that no longer existed: the coverage table divided by yesterday's files, a
credential risk that had been fixed still a gap, a file added since read as `new-file` by the
gate for ever. Now every renewal re-takes it, compares it by SHAPE — paths, kinds, fingerprints,
risks; never the commit stamp — writes it only when it changed, recomputes the per-kind coverage
rows and the inventory gaps without accumulating, and says so in `Renewal.inventoried`, which
`wrote` counts so the refresh publishes a round that rewrote no concept.
"""
from __future__ import annotations

from openfactory.knowledge.bundle import compute_checksums
from openfactory.knowledge.contracts import OkfManifest
from openfactory.knowledge.inventory import read_inventory, take_inventory, write_inventory
from openfactory.knowledge.okf import OKF_INDEX_FILE, read_manifest, write_okf
from openfactory.onboarding.renew import Renewal, renew_concepts
from tests.test_the_merge_re_authors_what_it_invalidated import (
    _PROJECT,
    _REWRITE,
    _concept,
    _harness,
    _published,
    _source,
)


def test_an_unchanged_tree_leaves_the_bundle_byte_identical(tmp_path, monkeypatch):
    repo, bundle, _ = _published(tmp_path)
    _harness(monkeypatch, None)
    before = {p.name: p.read_bytes() for p in bundle.iterdir() if p.is_file()}
    got = renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t2")
    assert got.mode == "fresh" and not got.inventoried and not got.wrote
    assert {p.name: p.read_bytes() for p in bundle.iterdir() if p.is_file()} == before


def test_a_bundle_published_without_an_inventory_gains_one(tmp_path, monkeypatch):
    """The bundle as the backfill wrote it before #48. The first renewal is a write even though
    every concept is fresh: the inventory, the per-kind coverage rows, the inventory's gaps."""
    repo = _source(tmp_path)
    fps = {c.file: c.sha256 for c in compute_checksums(repo)}
    bundle = tmp_path / "bundle"
    write_okf(bundle, manifest=OkfManifest(source_commit="c1", generated_at="day1"),
              concepts=[_concept(fingerprint=fps["billing/rules.py"])])
    (bundle / OKF_INDEX_FILE).write_text("# old index\n", encoding="utf-8")
    _harness(monkeypatch, None)
    got = renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t2")
    assert got.mode == "fresh" and got.inventoried and got.wrote
    assert read_inventory(bundle) is not None
    manifest = read_manifest(bundle)
    kinds = {r.kind: r for r in manifest.coverage}
    assert kinds["code"].inventoried == 1 and kinds["code"].concepts == 1
    assert "policy" in kinds, "the type row was lost"
    assert manifest.source_commit == "c2"
    assert "## Coverage" in (bundle / OKF_INDEX_FILE).read_text(encoding="utf-8")


def test_a_file_added_since_moves_the_numbers_without_a_broken_concept(tmp_path, monkeypatch):
    repo, bundle, _ = _published(tmp_path)
    (repo / "billing" / "tax.py").write_text("RATE = 0.2\n", encoding="utf-8")
    _harness(monkeypatch, None)
    got = renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t2")
    assert got.mode == "fresh" and got.inventoried and got.wrote
    assert got.summary().endswith("inventory refreshed")
    taken = read_inventory(bundle)
    assert taken.by_kind["code"] == 2 and taken.commit == "c2"
    code = next(r for r in read_manifest(bundle).coverage if r.kind == "code")
    assert (code.inventoried, code.concepts) == (2, 1)


def test_a_risk_that_was_fixed_leaves_the_manifest(tmp_path, monkeypatch):
    repo, bundle, _ = _published(tmp_path)
    (repo / "settings.py").write_text('PASSWORD = "hunter2hunter2"\n', encoding="utf-8")
    _harness(monkeypatch, None)
    renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t2")
    risks = [g for g in read_manifest(bundle).gaps if g.kind == "credential-risk"]
    assert [g.path for g in risks] == ["settings.py"] and "hunter2" not in risks[0].detail
    (repo / "settings.py").write_text('PASSWORD = os.getenv("PW")\n', encoding="utf-8")
    renew_concepts(_PROJECT, bundle, repo, commit="c3", generated_at="t3")
    assert [g for g in read_manifest(bundle).gaps if g.kind == "credential-risk"] == [], (
        "the fixed risk stayed beside its successor")


def test_a_broken_concept_and_a_changed_tree_are_one_round(tmp_path, monkeypatch):
    repo, bundle, _ = _published(tmp_path)
    (repo / "billing" / "rules.py").write_text("def charge():\n    return 2\n", encoding="utf-8")
    asked = _harness(monkeypatch, _REWRITE)
    got = renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t2")
    assert got.broken == 1 and got.rewritten == 1 and got.inventoried and got.wrote
    assert len(asked) == 1
    taken = read_inventory(bundle)
    fp = next(r.fingerprint for r in taken.files if r.path == "billing/rules.py")
    assert fp == compute_checksums(repo)[0].sha256 if compute_checksums(repo) else True
    code = next(r for r in read_manifest(bundle).coverage if r.kind == "code")
    assert code.concepts == 1, "the rewritten concept was not counted against the new tree"


def test_an_inventory_alone_is_something_to_renew(tmp_path, monkeypatch):
    """A project with `okf_concept_budget: 0` publishes an inventory and no concepts; its tree
    still moves, and the renewal still keeps the inventory current."""
    repo = _source(tmp_path)
    bundle = tmp_path / "bundle"
    write_inventory(bundle, take_inventory(repo, commit="c1"))
    (repo / "billing" / "tax.py").write_text("RATE = 0.2\n", encoding="utf-8")
    _harness(monkeypatch, None)
    got = renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t2")
    assert got.mode == "fresh" and got.checked == 0 and got.inventoried and got.wrote
    assert read_inventory(bundle).by_kind["code"] == 2
    assert got.summary() == "no concepts published — inventory refreshed"


def test_the_staged_bundle_is_not_the_repository(tmp_path, monkeypatch):
    """FOUND BY THE REFRESH'S OWN GUARD. The refresh stages the bundle INSIDE the checkout it
    renews (`<checkout>/knowledge/`), and the first cut inventoried it — `okf.yaml`, the
    concepts, `inventory.json` itself — so no two rounds ever agreed and the refresh published
    for ever. The same class of defect #43 closed for the module map, one layer up."""
    repo = _source(tmp_path)
    fps = {c.file: c.sha256 for c in compute_checksums(repo)}
    bundle = repo / "knowledge"
    write_okf(bundle, manifest=OkfManifest(source_commit="c1", generated_at="day1"),
              concepts=[_concept(fingerprint=fps["billing/rules.py"])])
    write_inventory(bundle, take_inventory(repo, commit="c1", exclude=bundle))
    _harness(monkeypatch, None)
    first = renew_concepts(_PROJECT, bundle, repo, commit="c2", generated_at="t2")
    assert first.mode == "fresh" and not first.inventoried, "its own output read as the client's"
    assert not any(r.path.startswith("knowledge/") for r in read_inventory(bundle).files)
    second = renew_concepts(_PROJECT, bundle, repo, commit="c3", generated_at="t3")
    assert not second.wrote, "two rounds on one tree disagreed"


def test_wrote_counts_the_inventory_and_never_a_failure():
    assert not Renewal(3, 0, 0, 0, "fresh").wrote
    assert Renewal(3, 0, 0, 0, "fresh", True).wrote
    assert Renewal(3, 1, 0, 1, "no harness").wrote
    assert not Renewal(0, 0, 0, 0, "failed", True).wrote
