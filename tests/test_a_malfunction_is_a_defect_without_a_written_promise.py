"""A malfunction is a defect whether or not a requirement names it (#399).

MEASURED LIVE: a person reported controls and content cut off when the window is resized, with a
screenshot, and called it a bug. The product role answered that no requirement promises a
responsive layout, "não é uma promessa quebrada", and drafted a REQUIREMENT, which waits for two
agreements before any card exists. The prompt had defined a defect as behaviour that contradicts
an ACCEPTED REQUIREMENT, and on a product whose code predates its requirements almost no bug has
one. Read as code: the answer needs a model, and what decides the route is the paragraph it is
told."""

from __future__ import annotations

import re
from pathlib import Path

ROLE = Path(__file__).resolve().parents[1] / "openfactory" / "product" / "role.py"


def _paragraph() -> str:
    src = ROLE.read_text(encoding="utf-8")
    start = src.index("REPORTED THAT SOMETHING IS NOT WORKING")
    # the prompt as the model reads it: the source's adjacent string literals joined
    return re.sub(r'"\s*\n\s*"', "", src[start:src.index("IF THEY ASKED YOU TO OPEN A CARD", start)])


def test_the_defect_is_defined_by_the_malfunction_not_by_a_written_requirement():
    said = _paragraph()

    assert "DEFECT NEEDS NO WRITTEN REQUIREMENT" in said
    assert "[[DEFEITO]] alone when no requirement names it" in said
    for shape in ("cut off", "unreachable", "an error", "lost or wrong data", "layout that breaks"):
        assert shape in said, f"the malfunction {shape!r} is no longer named"


def test_no_requirement_is_not_a_reason_to_call_a_bug_a_wish():
    said = _paragraph()

    assert "is NOT a reason to call a malfunction a wish" in said
    assert "when the person calls it a bug" in said
    assert "contradicts an accepted requirement" not in said, (
        "the definition that routed every brownfield bug into the requirement cycle is back")


def test_a_request_is_still_what_the_product_does_not_do_yet():
    said = _paragraph()

    assert "A REQUEST is something the product does not do yet" in said
    assert "Do NOT use the defect marker for a new capability" in said
