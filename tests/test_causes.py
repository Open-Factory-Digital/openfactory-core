"""The message a park note actually needs, out of the placeholder Temporal hands back (#66).

`str(ActivityError)` is the fixed string `"Activity task failed"` — every exception raised inside
a Temporal activity arrives at the workflow wearing it, and until this fix the workflow's
catch-all wrote that string straight into a parked ticket's note. The real message survives one
level down, in `__cause__`, as an `ApplicationError` carrying the original type and text.

THE FIRST TWO SECTIONS TEST `openfactory.util.causes` DIRECTLY, with the REAL `temporalio.exceptions`
classes rather than a stand-in — the whole point is proving the extraction survives contact with
the actual shape Temporal produces, not a shape this test made up to be convenient.

THE THIRD SECTION IS THE INTEGRATION POINT the card's acceptance criteria names: "a park note for
an activity failure contains the original exception's message, not `Activity task failed`" and
"configuration refusals are non-retryable." Neither `workflow.py`'s catch-all nor
`activities.py`'s `resolve_box_image` call sites can be driven through a real Temporal
WorkflowEnvironment without much heavier infrastructure than this repository's other workflow
tests use (`test_park_alert.py` asserts on the SOURCE for the same reason) — so this drives the
real classes through the real functions directly, which is the strongest check available at this
weight.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from temporalio.exceptions import ActivityError, ApplicationError

from openfactory.util.causes import describe, first_message


def _activity_error(cause: BaseException | None) -> ActivityError:
    """A REAL `ActivityError` wearing the REAL placeholder — `temporalio`'s constructor requires
    five keyword-only fields no caller of this module will ever have on hand outside a live
    workflow, so they are filled with values that assert nothing (the SDK does not look at their
    CONTENT to build `str(err)`, only their presence)."""
    err = ActivityError(
        "Activity task failed", scheduled_event_id=1, started_event_id=2, identity="worker-1",
        activity_type="run_job", activity_id="5", retry_state=None,
    )
    err.__cause__ = cause
    return err


# ── the chain-walk, against the real SDK classes ────────────────────────────────────────────────

def test_the_real_cause_survives_the_real_placeholder():
    """THE regression. `str(ActivityError(...))` alone is 'Activity task failed'; the SDK puts the
    real message one level down — as `ApplicationError.__str__`, which itself prefixes the
    ORIGINAL exception's type when the SDK recorded one (`type="ValueError"`), so that prefix is
    part of the real message here, not noise `first_message` should strip."""
    exc = _activity_error(ApplicationError("nuget.org returned 401", type="ValueError"))

    assert str(exc) == "Activity task failed"  # confirms the bug shape is real, not assumed
    assert "401" in first_message(exc)
    assert first_message(exc) == "ValueError: nuget.org returned 401"


def test_describe_keeps_the_type_a_reader_needs():
    """`first_message` alone loses which layer failed; a park note read days later benefits from
    knowing `ValueError` and `TimeoutError` send an operator to different places."""
    exc = _activity_error(RuntimeError("box cannot honour box.image"))

    assert describe(exc) == "RuntimeError: box cannot honour box.image"


def test_a_chain_of_only_placeholders_falls_back_to_the_outermost_type_name():
    """Every link says nothing — still better than the fixed string alone: the type name tells the
    reader which layer gave up. Never returns '', which would print a note ending in a bare colon
    and read as a truncation bug rather than as a genuinely empty cause."""
    exc = _activity_error(_activity_error(None))

    assert first_message(exc) == "ActivityError"
    assert first_message(exc) != ""


def test_a_context_chain_is_walked_too():
    """`raise X from Y` is not the only way Python chains exceptions — catching Y and raising X
    DURING that handling sets `__context__`, which several wrappers in this codebase actually use.
    Reading only `__cause__` would miss the real message whenever the OUTER exception is itself a
    placeholder — exactly the `ActivityError` shape, reconstructed here through real `raise`
    statements (`_activity_error` sets `__cause__` by hand; this checks the OTHER attribute)."""
    try:
        try:
            raise ValueError("the real one")
        except ValueError:
            raise ActivityError(
                "Activity task failed", scheduled_event_id=1, started_event_id=2,
                identity="worker-1", activity_type="run_job", activity_id="5", retry_state=None,
            ) from None  # `from None` only hides the traceback; __context__ is still set
    except ActivityError as exc:
        assert first_message(exc) == "the real one"


def test_a_context_cycle_does_not_hang():
    """Catching an exception inside its own `except` block and re-raising the original produces
    `a.__context__ is b` and `b.__context__ is a` — a genuine cycle, and this runs on an error
    path, the worst possible moment to hang."""
    a = ValueError("a")
    b = RuntimeError("b")
    a.__context__ = b
    b.__context__ = a

    assert first_message(a) in ("a", "b")  # terminates; which one wins is not the point


@pytest.mark.parametrize("blob", ["", "   ", "Activity task failed", "cancelled", "NONE"])
def test_placeholders_are_skipped_case_and_whitespace_insensitively(blob):
    """The whole chain — the outer `ActivityError` AND the placeholder-shaped inner one — has
    nothing informative to say, so this falls all the way through to the OUTERMOST type name
    (`first_message`'s documented last resort), not the inner exception's."""
    exc = _activity_error(ValueError(blob))

    assert first_message(exc) == "ActivityError"


def test_a_message_that_merely_contains_a_placeholder_word_survives():
    """The match is EXACT, not a substring test — a real message that happens to start with a
    placeholder word is the informative one and must not be discarded."""
    exc = _activity_error(ValueError("activity task failed after 3 attempts: 401 from nuget.org"))

    assert "401" in first_message(exc)


def test_a_long_message_is_capped_and_collapsed_to_one_line():
    exc = _activity_error(ValueError("line one\nline two\n" + "x" * 400))

    out = first_message(exc, limit=50)

    assert len(out) <= 50 and "\n" not in out and out.endswith("…")


# ── the integration points #66 actually fixed ───────────────────────────────────────────────────

WORKFLOW = Path("openfactory/runtime/temporal/workflow.py").read_text()
ACTIVITIES = Path("openfactory/runtime/temporal/activities.py").read_text()


def test_the_park_note_no_longer_uses_str_exc():
    """The exact site #66 names: the outer catch-all's `RunResult.note`."""
    site = WORKFLOW[WORKFLOW.index('note=f"job errored after retries:'):][:80]

    assert "describe(exc" in site
    assert "str(exc)" not in site


def test_resolve_box_image_is_never_called_bare_outside_its_own_wrapper():
    """Both call sites go through `_resolved_image` now — a bare call would retry a config error
    that cannot be fixed by retrying (the other half of #66). AST, not substring: the wrapper's
    OWN body legitimately contains the one real call, and a text search cannot tell that call
    apart from a second, un-wrapped one added later beside it."""
    import ast

    tree = ast.parse(ACTIVITIES)
    wrapper = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_resolved_image")
    inside_wrapper = set(ast.walk(wrapper))

    bare = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "resolve_box_image"
        and node not in inside_wrapper
    ]
    assert bare == [], f"resolve_box_image called directly at line(s) {[n.lineno for n in bare]}"


def test_a_box_image_refusal_is_a_real_non_retryable_application_error():
    """`_resolved_image` — the single place both activity call sites go through — must actually
    raise what `test_resolve_box_image_is_never_called_bare_inside_an_activity` assumes it does."""
    from openfactory.runtime.temporal.activities import _resolved_image

    project = type("_P", (), {
        "name": "demo", "box": type("_B", (), {"image": "ghcr.io/acme/custom:1"})()})()

    with pytest.raises(ApplicationError) as exc_info:
        _resolved_image(project, sandbox="worktree")  # worktree cannot honour box.image

    assert exc_info.value.non_retryable is True
    assert "box.image" in str(exc_info.value)


def test_a_resolvable_image_is_unaffected():
    """The wrap must not change the answer for the overwhelming common case — no `box.image`
    declared at all."""
    from openfactory.runtime.temporal.activities import _resolved_image

    project = type("_P", (), {"name": "demo", "box": None})()

    assert _resolved_image(project, sandbox="worktree")  # does not raise
