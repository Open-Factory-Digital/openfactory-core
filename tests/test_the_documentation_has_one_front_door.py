"""One path in, and every link on it resolves.

The pilot operator, halfway through the first hour: *"vejo que tem 3 lugares que posso fazer o
onboarding… quando publicarmos para virar opensource não pode ser essa confusão"*. He was
right and it was structural, not editorial: `README.md` had a quickstart,
`docs/ONBOARDING.md` had the guided path, and `docs/product/` held BOTH a `01-quickstart.md`
and a `02-onboarding-a-project.md` — four beginnings, drifting apart one fix at a time (he had
already followed the README into `project add` while ONBOARDING led with `project init`).

The tidy: one path (`docs/ONBOARDING.md`), vendor pages under `docs/setup/`, references under
`docs/reference/` plus `docs/STATUS.md`, and `docs/product/` gone — its name collided with the
PRODUCT ROLE, which is a different thing entirely.

Two guards keep it that way, because prose cannot:

  1. no second beginning — nothing on the adopter surface may be NAMED like an onboarding or a
     quickstart except the one document that is one;
  2. every relative link on that surface resolves — the failure mode of any reorganisation, and
     the one a reader meets as a 404 rather than as a broken build.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: What a stranger reads. `core/` and `adr/` are deliberately NOT on it — the design rationale and
#: the decision records are for whoever builds on this, and a reader installing it should not have
#: to walk them first. Not internal: `docs/README.md` and `docs/STATUS.md` both send public readers
#: into `core/`, and since 2026-08-26 `docs/core/` is exactly the three design documents and the
#: index that names them.
ADOPTER_SURFACE = (
    [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "SECURITY.md"]
    + sorted((ROOT / "docs").glob("*.md"))
    + sorted((ROOT / "docs" / "setup").glob("*.md"))
    + sorted((ROOT / "docs" / "reference").glob("*.md"))
)

_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def test_exactly_one_document_is_a_beginning():
    named_like_a_start = [
        p.relative_to(ROOT) for p in ADOPTER_SURFACE
        if re.search(r"onboarding|quickstart|getting-started", p.stem, re.IGNORECASE)
    ]
    assert named_like_a_start == [Path("docs/ONBOARDING.md")], (
        f"more than one document is named like a beginning: {[str(p) for p in named_like_a_start]}"
        " — a reader has to guess which is current, which is exactly how the four of them drifted")


def test_the_product_folder_does_not_come_back():
    """`docs/product/` read as "the product role's documentation" and held the two duplicate
    beginnings. The references live in `docs/reference/`; the role's own page is one of them."""
    assert not (ROOT / "docs" / "product").exists(), (
        "docs/product/ is back — its name collides with the product ROLE, and it is where the "
        "duplicate onboarding pages lived")


#: The PATH — the pages somebody follows to install. A reference page may cite a decision
#: record (its reader is deciding); the path may not, because a reader mid-install has no use
#: for our filing system and reads it as a required detour.
THE_PATH = [ROOT / "docs" / "ONBOARDING.md", *sorted((ROOT / "docs" / "setup").glob("*.md"))]


@pytest.mark.parametrize("doc", THE_PATH, ids=lambda p: str(p.relative_to(ROOT)))
def test_the_path_speaks_consequences_not_decision_records(doc: Path):
    """The pilot operator, at §0: *"e ainda faz menção a ADR, isso deveria estar em um documento
    de onboarding?"* No. `(ADR-0040)` beside "no cloud account is required" adds nothing a
    reader installing the platform can act on, and asks them to hold a number that means
    nothing yet — the same defect as the platform's own vocabulary leaking into the `init`
    prompts. Say the consequence; the records are one link away in docs/README.md."""
    citations = re.findall(r"ADR-\d+", doc.read_text())
    assert not citations, (
        f"{doc.relative_to(ROOT)} cites {sorted(set(citations))} — on the installation path, "
        f"state the consequence instead; docs/README.md points at docs/adr/ for the reader who "
        f"wants the reasoning")


@pytest.mark.parametrize("doc", ADOPTER_SURFACE, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_page_links_to_ITSELF(doc: Path):
    """A self-link is what a bulk path rewrite leaves behind when the old target folded into
    the page doing the pointing: ONBOARDING §2 kept sending readers to "ONBOARDING §4" for a
    recipe that had moved to the GitHub guide (found by the pilot reading it, 2026-08-12). The
    link RESOLVES, so the integrity guard below is blind to it — this is the other half."""
    here = doc.resolve()
    selfies = [t for t in _LINK.findall(doc.read_text())
               if "://" not in t and (doc.parent / t.split("#", 1)[0]).resolve() == here
               and t.split("#", 1)[0]]
    assert not selfies, f"{doc.relative_to(ROOT)} links to itself: {selfies}"


@pytest.mark.parametrize("doc", ADOPTER_SURFACE, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_relative_link_on_the_adopter_surface_resolves(doc: Path):
    broken = []
    for target in _LINK.findall(doc.read_text()):
        target = target.split("#", 1)[0].strip()
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        if not (doc.parent / target).exists():
            broken.append(target)
    assert not broken, f"{doc.relative_to(ROOT)} links to files that do not exist: {broken}"
