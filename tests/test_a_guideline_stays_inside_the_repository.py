"""A guideline the manifest names is read from the repository, and from nowhere else (#329).

The manifest is the repository's own content — it lives in the tree the agent edits — and each
guideline it names is inlined into the agent's prompt. `repo_path / g` let an absolute entry, one
that climbs out with `..`, or a link committed in the repository name any readable file on the
worker and put it in front of the model. These tests hold what a regression would cost:

  1. an entry outside the checkout is refused — absolute, climbing, or a link out — in
     `docs.guidelines` and in a component's `guidelines`, and one inside is still read;
  2. the refusal is loud: the job's log names the entry and where central guidelines belong;
  3. `openfactory doctor` fails the project before the first job, with the remedy — on the same
     shapes the job refuses, the repository itself among them.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pinned_probes import a_fully_pinned_probe_set

from openfactory import doctor
from openfactory.contracts import Manifest, Ticket
from openfactory.orchestrator.context import build_context

SECRET = "worker-only secret: do not show the model"


def _ticket() -> Ticket:
    return Ticket(id="#1", title="t", objective="o", repo="o/x")


@pytest.fixture
def worker(tmp_path: Path):
    """A checkout, and beside it a file of the worker that no repository may name."""
    checkout = tmp_path / "checkout"
    (checkout / "rules").mkdir(parents=True)
    (checkout / "rules" / "house.md").write_text("100% coverage is enforced.")
    outside = tmp_path / "worker" / "secret.md"
    outside.parent.mkdir()
    outside.write_text(SECRET)
    return checkout, outside


def _read(manifest: Manifest, checkout: Path) -> str:
    return "\n".join(build_context(manifest, checkout, _ticket()).guidelines)


# ── 1. refused outside, read inside ────────────────────────────────────────────────────────────

def test_an_absolute_entry_outside_the_checkout_is_refused(worker):
    checkout, outside = worker
    got = _read(Manifest(docs={"guidelines": [str(outside), "rules/house.md"]}), checkout)
    assert SECRET not in got, "a file of the worker reached the agent's prompt"
    assert "100% coverage" in got, "the guideline inside the repository stopped being read"


def test_an_entry_that_climbs_out_is_refused(worker):
    checkout, _ = worker
    got = _read(Manifest(docs={"guidelines": ["../worker/secret.md"]}), checkout)
    assert SECRET not in got


def test_a_link_in_the_repository_that_points_out_of_it_is_refused(worker):
    checkout, outside = worker
    (checkout / "rules" / "linked.md").symlink_to(outside)
    got = _read(Manifest(docs={"guidelines": ["rules/linked.md"]}), checkout)
    assert SECRET not in got


def test_a_component_s_guidelines_are_held_to_the_same_rule(worker):
    checkout, outside = worker
    manifest = Manifest(components={"api": {"path": "api/**", "stack": "python",
                                            "guidelines": [str(outside)]}})
    assert SECRET not in _read(manifest, checkout)


# ── 2. the refusal is loud ─────────────────────────────────────────────────────────────────────

def test_the_refusal_names_the_entry_and_where_central_guidelines_belong(worker, caplog):
    checkout, outside = worker
    manifest = Manifest(components={"api": {"path": "api/**", "stack": "python",
                                            "guidelines": [str(outside)]}})
    with caplog.at_level(logging.WARNING):
        _read(manifest, checkout)
    assert "components.api.guidelines" in caplog.text and str(outside) in caplog.text
    assert "REFUSED" in caplog.text and "WITHOUT" in caplog.text
    assert "OPENFACTORY_GUIDELINES_DIR" in caplog.text


def test_an_entry_naming_the_repository_itself_is_not_called_an_escape(worker, caplog):
    checkout, _ = worker
    with caplog.at_level(logging.WARNING):
        _read(Manifest(docs={"guidelines": ["."]}), checkout)
    assert "the repository itself" in caplog.text and "outside the checkout" not in caplog.text


# ── 3. the doctor says so before the first job ─────────────────────────────────────────────────

def _finding(manifest: Manifest) -> doctor.Finding:
    report = doctor.diagnose(a_fully_pinned_probe_set(manifest=lambda: manifest))
    return next(f for f in report.findings if f.check == "guidelines")


@pytest.mark.parametrize("entry", ["/etc/openfactory/standards.md", "../central/standards.md",
                                   "rules/../../central/standards.md"])
def test_the_doctor_fails_a_project_that_names_a_guideline_outside_it(entry):
    f = _finding(Manifest(docs={"guidelines": [entry]}))
    assert not f.ok and entry in f.message and "WITHOUT" in f.message
    assert "OPENFACTORY_GUIDELINES_DIR" in f.remedy


@pytest.mark.parametrize("entry", [".", "docs/..", ""])
def test_the_doctor_fails_an_entry_that_names_the_repository_itself(entry):
    """The job refuses these too; the doctor and the job agree on every shape (review of #346)."""
    f = _finding(Manifest(docs={"guidelines": [entry]}))
    assert not f.ok and "the repository itself" in f.message


def test_the_doctor_passes_guidelines_inside_the_repository():
    f = _finding(Manifest(docs={"guidelines": ["rules/house.md", "./rules/../rules/a.md"]}))
    assert f.ok and "2 named" in f.message
