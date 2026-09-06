"""The panel's station strip belongs to ONE run (defects ledger #7, found 2026-08-27 on the first
real Azure DevOps run).

The strip's ticks are folded with `Math.max` over every `state` event the job's journal replays. A
ticket skipped at Review and picked up again therefore showed the previous run's ✓ up to Review
while the badge and the live log said Spec — two runs on one strip, and an operator reading
"Review reached" about a job that had just started. The fix is where the timer already resets: a
run re-enters `spec_validation`, and from that event on nothing earlier is this run's.

Source-level guards over the panel's JavaScript (comments stripped, as the frame guard does), and
a small interpreter of the fold rule so the ORDER — reset, then fold — is exercised, not read.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import openfactory.api as api

PANEL_PATH = Path(inspect.getfile(api)).parent / "panel.html"
PANEL = PANEL_PATH.read_text(encoding="utf-8")
CODE = "\n".join(ln for ln in PANEL.splitlines() if not ln.lstrip().startswith("//"))

RESET = 'if(e.message=="spec_validation"){focus.reached=-1;focus.mode="running";}'
FOLD = "if(idx>=0)focus.reached=Math.max(focus.reached,idx);"


def _state_block() -> str:
    start = CODE.index('if(e.kind=="state"){')
    return CODE[start:CODE.index("const pipe=$(\"#mpipe\")", start)]


def test_a_run_that_re_enters_spec_validation_starts_its_own_strip():
    block = _state_block()
    assert RESET in block, "the strip is never reset — a re-run inherits the previous run's ticks"
    assert block.index(RESET) < block.index(FOLD), (
        "the reset must come BEFORE the fold: after it, Math.max re-applies the old maximum")


def _replay(events: list[str]) -> tuple[int, str]:
    """The fold as the panel's code states it, run over a journal — reset first, then max."""
    stations = ["spec_validation", "preparing", "planning", "implementing", "validating",
                "reviewing", "pr_open"]
    block = _state_block()
    reached, mode = -1, "running"
    for message in events:
        idx = stations.index(message) if message in stations else -1
        for line in [ln.strip() for ln in block.splitlines()]:
            if line == RESET and message == "spec_validation":
                reached, mode = -1, "running"
            elif line == FOLD and idx >= 0:
                reached = max(reached, idx)
            elif re.fullmatch(r'if\(e\.message=="failed"\|\|e\.message=="needs_refinement"\)'
                              r'focus\.mode="failed";', line) and message in ("failed",
                                                                                "needs_refinement"):
                mode = "failed"
    return reached, mode


def test_the_skipped_run_s_ticks_do_not_survive_the_pickup():
    """Two runs in one journal: the first got to Review and was skipped; the second is at Spec."""
    first = ["spec_validation", "preparing", "planning", "implementing", "validating", "reviewing"]
    second = ["spec_validation"]
    assert _replay(first) == (5, "running")
    assert _replay(first + second) == (0, "running"), "the strip still shows the first run"
    assert _replay(first + second + ["preparing"]) == (1, "running")


def test_a_park_at_review_then_a_re_run_reads_running_not_failed():
    first = ["spec_validation", "preparing", "reviewing", "needs_refinement"]
    assert _replay(first) == (5, "failed")
    assert _replay(first + ["spec_validation"]) == (0, "running"), "the mode did not reset"
