"""The doctor sees a guideline committed in the repository as a link out of it (#350).

`openfactory doctor`'s `guidelines` line read the manifest's text and nothing else, so a guideline
committed as a link that points out of the repository passed there, while every job refused the
link at run time and the agent ran without it. That is the shape of a deployment whose central
standards are symlinked into each repository, the workaround #318 was filed about: a green line
and agents running without the organisation's standards. These tests hold what a regression
would cost:

  1. through the doctor's REAL probes, a link out committed in a real git repository fails the
     line, by name, with where it leads and the remedy; links that stay inside still pass;
  2. the doctor and the job agree on every entry, because the doctor asks the job's own rule
     (`context.resolve_inside`) in the tree the job resolves it in;
  3. with no checkout at hand the line says it read the text only, and claims nothing more.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from pinned_probes import a_fully_pinned_probe_set

from openfactory import doctor, namespace
from openfactory.contracts import Manifest, Ticket
from openfactory.contracts.project import Project
from openfactory.orchestrator.context import build_context

HOUSE = "house rule: 100% coverage is enforced"
CENTRAL = "central standard: the organisation's API guidelines"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    """A git repository with its links COMMITTED, and beside it the organisation's standards.

    `rules/standards.md` is the #318 workaround: an absolute link to the central file.
    `rules/relative.md` leaves the same way by a relative path, `rules/inlink.md` stays inside,
    and `rules/up` points at the repository itself."""
    central = tmp_path / "central" / "standards.md"
    central.parent.mkdir()
    central.write_text(CENTRAL)
    repo = tmp_path / "shop"
    (repo / "rules").mkdir(parents=True)
    (repo / "rules" / "house.md").write_text(HOUSE)
    (repo / "rules" / "standards.md").symlink_to(central)
    (repo / "rules" / "relative.md").symlink_to(Path("..") / ".." / "central" / "standards.md")
    (repo / "rules" / "inlink.md").symlink_to("house.md")
    (repo / "rules" / "up").symlink_to("..")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "the organisation's standards, linked in")
    links = {line.split("\t")[1] for line in _git(repo, "ls-files", "-s").splitlines()
             if line.startswith("120000 ")}
    assert links == {"rules/standards.md", "rules/relative.md", "rules/inlink.md",
                     "rules/up"}, f"git did not record the links as links: {links}"
    return repo


def _declare(repo: Path, *guidelines: str) -> Project:
    manifest = repo / namespace.MANIFEST
    manifest.parent.mkdir(exist_ok=True)
    manifest.write_text(yaml.safe_dump({"version": 1, "docs": {"guidelines": list(guidelines)}}))
    return Project(name="shop", repo_path=str(repo))


def _the_doctors_line(project: Project) -> doctor.Finding:
    """The REAL `manifest` and `checkout` probes of this project under the real `diagnose`."""
    real = doctor.probes_for(project)
    report = doctor.diagnose(a_fully_pinned_probe_set(manifest=real.manifest,
                                                      checkout=real.checkout))
    return next(f for f in report.findings if f.check == "guidelines")


# ── 1. the doctor sees the link, through its real probes ───────────────────────────────────────

@pytest.mark.parametrize("entry", ["rules/standards.md", "rules/relative.md"])
def test_a_guideline_committed_as_a_link_out_of_the_repository_fails_the_doctor(shop, entry):
    f = _the_doctors_line(_declare(shop, "rules/house.md", entry))

    assert not f.ok, f"the doctor passed a link out of the repository: {f.message}"
    assert entry in f.message and "WITHOUT" in f.message
    target = (shop.parent / "central" / "standards.md").resolve()
    assert str(target) in f.message, f"the line does not say where the link leads: {f.message}"
    assert "rules/house.md" not in f.message, "a guideline inside the repository was failed too"
    assert "OPENFACTORY_GUIDELINES_DIR" in f.remedy and "link" in f.remedy


def test_a_link_to_the_repository_itself_fails_by_that_name(shop):
    f = _the_doctors_line(_declare(shop, "rules/up"))

    assert not f.ok and "rules/up" in f.message and "the repository itself" in f.message


def test_links_that_stay_inside_the_repository_pass_and_the_line_names_the_checkout(shop):
    f = _the_doctors_line(_declare(shop, "rules/house.md", "rules/inlink.md"))

    assert f.ok, f.message
    assert "2 named" in f.message and str(shop) in f.message
    assert "links followed" in f.message and "manifest's text" not in f.message


# ── 2. the doctor and the job agree, entry by entry ────────────────────────────────────────────

@pytest.mark.parametrize("entry", [
    "rules/house.md", "rules/inlink.md", "rules/standards.md", "rules/relative.md", "rules/up",
    ".", "../central/standards.md", "CENTRAL_ABSOLUTE",
    # climbs out and back in: the text calls it outside, the job reads it
    "../shop/rules/house.md",
])
def test_the_doctor_fails_exactly_the_entries_the_job_does_not_read(shop, entry):
    if entry == "CENTRAL_ABSOLUTE":
        entry = str(shop.parent / "central" / "standards.md")
    ticket = Ticket(id="#1", title="t", objective="o", repo="o/x")
    prompt = "\n".join(build_context(Manifest(docs={"guidelines": [entry]}), shop,
                                     ticket).guidelines)
    read = HOUSE in prompt or CENTRAL in prompt

    f = _the_doctors_line(_declare(shop, entry))

    assert f.ok == read, (f"the job {'reads' if read else 'refuses'} {entry!r} and the doctor "
                          f"{'passes' if f.ok else 'fails'} it: {f.message}")


# ── 3. no checkout at hand: the text, said as the text ─────────────────────────────────────────

def test_with_no_checkout_at_hand_the_line_says_it_read_the_text_only():
    f = next(x for x in doctor.diagnose(a_fully_pinned_probe_set(
        manifest=lambda: Manifest(docs={"guidelines": ["rules/standards.md"]}),
        checkout=lambda: None)).findings if x.check == "guidelines")

    assert f.ok, "the text alone cannot see a link, and a red line would be a guess"
    assert "manifest's text" in f.message and "no checkout" in f.message
    assert "resolves inside" not in f.message, f"it claims a containment it did not check: " \
                                               f"{f.message}"


def test_a_checkout_the_doctor_cannot_resolve_is_no_checkout_not_a_crash(shop, monkeypatch):
    project = _declare(shop, "rules/standards.md")
    real = doctor.probes_for(project)

    def unfetchable(*_a, **_kw):
        raise RuntimeError("project 'shop' could not be fetched")

    monkeypatch.setattr("openfactory.factory.resolve_repo_path", unfetchable)

    assert real.checkout() is None
