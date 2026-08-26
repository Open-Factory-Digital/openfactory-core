"""While the agent rewrote the pull request, every surface said a person was needed (#151).

The engine raises `working` on the merge gate before launching a repair pass — the pass a human
just asked for with Adjust. The floor headline, the census and `/api/inbox` were taught to read it.
The PANEL was not: it decides "a person is needed" from `action.kind == "merge_wait"` alone, so the
machine card said *PR ready — waiting for your review & merge* over a branch being rewritten, with
live Merge / Adjust / Discard buttons above it.

AND THE ANSWER PATH DID NOT DEFEND ITSELF. `answer_merge_gate` accepted merge or discard while the
pass ran, so a stale page, a curl, or a Slack click still landed it — a merge on whatever the agent
had pushed so far, or a discard of a pass the operator is paying for. Refusing at the seam every
surface crosses is what makes the panel's silence a fact rather than a hope.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from openfactory.runtime.temporal.view import gate_cannot_hear

PANEL = Path(inspect.getfile(__import__("openfactory.api", fromlist=["x"]))).parent / "panel.html"


def _code() -> str:
    from conftest import code_only  # noqa: F401 — python stripper, not for HTML

    return "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in PANEL.read_text().splitlines())


# ── 1. the seam every surface crosses ───────────────────────────────────────────────────────────

def test_an_answer_is_REFUSED_while_the_pass_it_asked_for_runs():
    said = gate_cannot_hear({"pr_url": "https://x/pr/9", "auto": False, "working": True})

    assert said, "merge and discard are still accepted over a branch being rewritten"
    assert "repair pass" in said and "ask again" in said, (
        f"the refusal does not say what is happening or what comes next: {said!r}")


def test_and_an_ordinary_gate_is_still_answerable():
    """The positive twin. A refusal that fired always would strand every pull request this
    platform opens."""
    assert gate_cannot_hear({"pr_url": "https://x/pr/9", "auto": False}) == ""
    assert gate_cannot_hear({"pr_url": "https://x/pr/9", "auto": False, "working": False}) == ""


def test_the_two_refusals_stay_DIFFERENT_sentences():
    """A gate that predates the patch can never hear; a gate mid-pass will hear in a minute.
    Collapsing them would tell an operator to go and merge on the forge by hand — losing the pass
    they are paying for."""
    deaf = gate_cannot_hear({"gate_live": False})
    busy = gate_cannot_hear({"working": True})

    assert deaf and busy and deaf != busy
    assert "forge itself" in deaf and "forge itself" not in busy


# ── 2. the panel says what is happening, and offers nothing to press ────────────────────────────

def test_the_machine_card_reads_WORKING_before_it_reads_auto():
    """Order matters: `auto` is false during a human-answered pass, so a check that reads it first
    renders "PR ready — waiting for your review" over the rewrite."""
    code = _code()
    at = code.index("mnow.innerHTML=")
    block = code[at:at + 400]

    assert "mw.action.working" in block, "the machine card does not read `working` at all"
    assert block.index("working") < block.index("auto"), (
        "`auto` is read first, so the rewrite is announced as a wait on a person")


def test_the_floor_control_says_a_pass_is_running():
    code = _code()
    at = code.index("fc.innerHTML=")
    block = code[at:at + 500]

    assert "a.working" in block and "repair pass running" in block


def test_and_the_three_answers_are_NOT_offered_during_it():
    """The buttons are for when the machine waits on a person — not while it does the work that
    person asked for. The server refuses them too; this keeps a person from being shown a button
    that will be refused."""
    code = _code()

    assert 'a.auto||a.working?""' in code, (
        "Merge / Adjust / Discard are still painted while a repair pass rewrites the branch")


@pytest.mark.parametrize("verb", ["merge", "adjust", "discard"])
def test_the_gate_buttons_all_sit_behind_that_one_condition(verb):
    """One condition, not three: a fourth answer added later inherits the guard rather than
    needing somebody to remember it."""
    # SCOPED TO THE FLOOR CONTROL. `data-k="merge"` is painted on more than one surface (the
    # inbox card has its own), and a whole-page `index` finds whichever comes first — which is how
    # a guard written against a page ends up measuring a different widget.
    code = _code()
    block = code[code.index("fc.innerHTML="):]
    guard = block.index('a.auto||a.working?""')
    button = block.index(f'data-k="{verb}"')

    assert guard < button, f"the {verb} button is painted outside the working guard"
