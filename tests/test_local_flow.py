"""The local flow harness — and the regression it exists to catch: the split cascade.

Runs the REAL _do_preflight/_do_split loop offline (no cloud, no LLM) in a fraction of a
second, so an emergent bug like 'pre-flight re-sizes its own split children forever' is caught
here instead of after a deploy + a live poll on the heavy project.
"""

from __future__ import annotations

from openfactory.testing.local_flow import always_split, run_flow, split_once_then_fit


def test_intended_flow_splits_once_then_children_go_to_code():
    run = run_flow(seed_title="Plan 92 — big bundle", sizer=split_once_then_fit(4))
    assert not run.cascaded
    # exactly one split (the parent) + 4 children each coded → 5 ticks, no more
    verdicts = [v for _, _, v, _ in run.trace]
    # THE TRACE IS IN THE MESSAGE, WITH THE REASON. A bare `assert 3 == 4` cost an afternoon of
    # re-running the suite to find out WHICH tick degraded and why — and `degraded` is not a
    # cosmetic outcome: in production it means a ticket went through UNSIZED, which is the live
    # #37 bug this harness exists to catch offline.
    detail = "\n".join(f"    tick {t}: #{i} → {v} ({d})" for t, i, v, d in run.trace)
    assert verdicts.count("split") == 1, f"expected exactly one split:\n{detail}"
    assert verdicts.count("fit") == 4, f"a tick did not size cleanly:\n{detail}"
    # the sizer was asked ONLY about the parent — children skip sizing (the guard)
    assert len(run.sizer_calls) == 1


def test_cascade_guard_holds_even_when_the_sizer_always_splits():
    # Worst case: the sizer judges EVERY ticket too large. The split-child marker still stops
    # the recursion — a child is never re-sized — so the flow converges instead of exploding.
    run = run_flow(seed_title="Plan 92 — big bundle", sizer=always_split(4))
    assert not run.cascaded, "split children were re-sized — cascade regression"
    # the parent splits into 4; each child is recognised as already-scoped → coded, not re-split
    assert [v for _, _, v, _ in run.trace].count("split") == 1
    # only the parent ever reached the sizer
    assert run.sizer_calls == ["Plan 92 — big bundle"]
    assert len(run.tracker._tickets) == 5  # parent + 4 children, nothing more


def test_invariant_a_parent_has_children_never_grandchildren():
    # The hard rule (owner): depth-1 only. Even with a sizer that would split everything, no
    # split child may become a parent — no grandchildren, ever.
    run = run_flow(seed_title="Plan 92 — big bundle", sizer=always_split(5))
    assert run.tracker.grandchildren() == [], "a split child was itself split — grandchildren!"
    # every child of the seed has ZERO children of its own
    for child in run.tracker.children_of("#101"):
        assert run.tracker.children_of(child) == []


def test_children_are_natively_linked_to_the_parent():
    run = run_flow(seed_title="Plan 92 — big bundle", sizer=split_once_then_fit(3))
    # find the parent (the seed, #101) and assert 3 native children were linked
    assert len(run.tracker.children_of("#101")) == 3
