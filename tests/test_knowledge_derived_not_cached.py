"""The map is DERIVED, so it is derived where the checkout is (ADR-0023).

The defect that forced this: #478 — the very ticket the A/B existed to measure — ran with no map.
The map was published on factory merges only, a person merged PR #508 at 22:40 on 2026-07-26, and
for TWENTY-TWO HOURS the published map described the previous commit. Every job in that window
found the checksums mismatched and degraded to no injection. The degradation was right; the trigger
was incomplete.

The reflex fix — an hourly refresh — shrinks the window from 22h to 1h and does not close it. Each
such fix makes the cache *more correct* without making it *correct*.

The question nobody had asked: generating the map costs **0.24s for 215 files** (measured). The
manifest that exists solely to tell whether the cache is still valid is **186 KB**. A cache is only
worth its machinery when computing is expensive.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from openfactory.knowledge.bundle import read_bundle_dir
from openfactory.knowledge.pipeline import discard_fetched_bundle, generate_bundle_for
from openfactory.knowledge.service import load_agent_knowledge
from openfactory.knowledge.staleness import is_stale, is_trustworthy

REPO = Path(".")


@pytest.fixture()
def generated():
    d = generate_bundle_for(REPO)
    yield d
    discard_fetched_bundle(d)


# ── fresh by construction ───────────────────────────────────────────────────────────────────────

def test_a_map_generated_from_a_tree_is_never_stale_against_it():
    """The whole architecture in one assertion: there is no window in which it can drift, because
    it is derived from the tree it describes."""
    d = generate_bundle_for(REPO)
    try:
        bundle = read_bundle_dir(d)
        assert bundle is not None, "the bundle could not even be read back"
        assert is_stale(bundle, REPO) is False
        assert is_trustworthy(bundle, REPO) is True
    finally:
        discard_fetched_bundle(d)


def test_the_generated_map_is_actually_INJECTED(generated):
    """`is_trustworthy` passing is not the same as the agent receiving text — the first version of
    this returned a directory one level off the established layout, so the injection read nothing
    and reported an empty map while everything "passed"."""
    text = load_agent_knowledge(REPO, enabled=True, bundle_dir=generated)
    assert text, "the freshly generated map was rejected at injection"
    assert len(text) > 500, f"suspiciously small injection: {len(text)} chars"


def test_it_lands_OUTSIDE_the_workspace(generated):
    """A bundle inside the agent's tree would be swept into the ticket's commit by `git add -A`,
    and every client pull request would carry a copy of the map."""
    assert REPO.resolve() not in generated.resolve().parents


def test_the_temp_directory_is_reclaimed():
    """A leaked directory per job fills the worker's disk. The discard contract computes the temp
    root from the returned path, which is why the layout must match the fetched path's exactly."""
    d = generate_bundle_for(REPO)
    root = d.parent.parent
    assert root.exists()
    discard_fetched_bundle(d)
    assert not root.exists(), "the temp root survived — this leaks once per job"


# ── cheap enough that the cache was never justified ─────────────────────────────────────────────

def test_generating_is_fast_enough_to_do_every_time():
    """0.24s for 215 files, measured 2026-07-29. The assertion is generous — it guards the
    ARCHITECTURE (deriving beats caching) rather than a benchmark: if this ever failed, the answer
    would not be to raise the number, it would be to revisit ADR-0023.

    CPU TIME, NOT WALL-CLOCK (2026-08-26). Measured by the clock on the wall this took 19s with
    three suites sharing the cores and 0.3s alone — the same work, and the assertion is about
    the WORK. `os.times()` counts this process and the children it waited for (the pipeline
    shells out), which is what generation costs wherever it runs; a loaded machine is not a
    finding about the architecture."""
    def cpu() -> float:
        t = os.times()
        return t.user + t.system + t.children_user + t.children_system

    started = cpu()
    d = generate_bundle_for(REPO)
    elapsed = cpu() - started
    discard_fetched_bundle(d)
    assert elapsed < 10.0, (
        f"generation cost {elapsed:.1f}s of CPU — if this is real, the cache ADR-0023 removed "
        f"may have been justified after all"
    )


# ── the A/B stays an experiment ─────────────────────────────────────────────────────────────────

def test_the_control_arm_GENERATES_and_discards():
    """Decision (b), 2026-07-29. Skipping generation for the control is cheaper and makes the arms
    differ in TWO variables — the injection and the CPU — so any measured difference would have two
    explanations and the convenient one would be chosen. The A/B exists to support a commercial
    claim; one that cannot support it is worse than none."""
    import ast

    src = Path("openfactory/orchestrator/machine.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_knowledge_bundle")
    body = ast.unparse(fn)
    assert "generate_bundle_for" in body
    assert "discard_fetched_bundle" in body, "the control arm no longer discards — it leaks"
    # generation must NOT sit behind the arm check, or the control stops paying the same CPU
    assert body.index("treated = self._experiment_arm()") < body.index("generate_bundle_for"), (
        "the arm check moved above generation — the control stopped generating, and the two arms "
        "now differ in CPU as well as in injection"
    )


def test_the_control_arm_receives_NO_bundle():
    """Generated, measured, thrown away: the control must run exactly as a project with the map
    switched off does."""
    import ast

    src = Path("openfactory/orchestrator/machine.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_knowledge_bundle")
    body = ast.unparse(fn)
    assert "self._bundle_dir = None" in body, "the control arm would be handed the map"
