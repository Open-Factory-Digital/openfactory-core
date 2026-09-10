"""A ticket URL is a nicety; MOVING THE CARD is the job. One must never cost the other.

Two call sites hand the board a `issue_url` — the child-to-TO-DO move after a split, and the
healing move that closes a stale card. Both used to compose `https://github.com/{repo}/issues/{n}`
by hand, which is the shape `TrackerAdapter.ticket_url` exists to end: the literal ignores
`GH_HOST`, so a GitHub Enterprise deployment linked to public github.com, where a same-named
repository may belong to somebody else.

Routing them through the port was right and the FIRST version was wrong: it called
`tracker.ticket_url(...)` unguarded, and three suites went red at once — every tracker double,
and any adapter written before the method existed, does not have it. Only the GitHub Projects
board consumes this value at all (Jira and Azure Boards ignore it), so a missing link must never
stop the card moving.

**WHAT IT DEGRADES TO CHANGED ON 2026-09-09 (ADR-0049 slice 3e, PR #95): nothing, instead of a
composed literal.** The literal was not merely redundant — it resolved a bare ref through
`_ref_repo`, whose default is the FORGE's repository and only then the tracker's, so on a project
that declares both it addressed an issue in the repository the issue is not in. `""` is a shape
the boards already meet (`conformance/adapters.py` probes with exactly it), and the Projects
board's own scan — not this value — is the authority on whether a card is there. The proof that
the GitHub row answers on every shape these call sites hand it lives in
`test_the_ticket_url_is_the_trackers_own.py`, which is what let the literal go.

The property is untouched, in one sentence: **the move happens whatever the tracker says about
links.**
"""

from __future__ import annotations

import pytest

from openfactory.runtime.temporal.activities import _ticket_url


class _Silent:
    """A tracker from before `ticket_url` existed — the shape every test double has."""


class _Raising:
    def ticket_url(self, ref):
        raise RuntimeError("the tracker is unreachable")


class _Empty:
    def ticket_url(self, ref):
        return ""


class _Speaking:
    """AND IT PADS ITS ANSWER, which is not decoration in this double.

    A row composes its URL from configuration a person typed, and a trailing newline or a stray
    space survives every shape of that composition. The board hands the value straight to
    `add_item`, where a padded URL resolves to no content id at all — so the card is not added,
    and the only trace is a warning about a card that was never there. The helper strips; this is
    what makes that visible."""

    def ticket_url(self, ref):
        return f"  https://ghe.acme.internal/acme/api/issues/{ref.lstrip('#')}\n"


@pytest.mark.parametrize("tracker, why", [
    (_Silent(), "an adapter that predates the method"),
    (_Raising(), "a tracker that cannot be reached"),
    (_Empty(), "a provider that cannot say"),
])
def test_nothing_is_raised_and_the_answer_is_nothing_rather_than_a_guess(tracker, why):
    """`""`, not an exception and not an address nobody located — see the module docstring."""
    assert _ticket_url(tracker, "#7") == "", why


def test_a_provider_that_CAN_say_is_believed_over_the_literal():
    """The whole reason for asking: this is the answer the literal could not give — an
    Enterprise host, where the composed github.com link points at somebody else's repository."""
    assert _ticket_url(_Speaking(), "#7") == "https://ghe.acme.internal/acme/api/issues/7"


def test_the_two_call_sites_go_through_it_rather_than_calling_the_port_directly():
    """The reachability half. A call site that went back to `tracker.ticket_url(...)` would pass
    every test above while breaking the move for every tracker without the method — which is
    exactly what happened the first time (2026-08-12).

    BOTH SITES, since slice 3e: the healer was named in this file's own first paragraph and left
    out of its only reachability assertion, so the half of the property that lives in `scan_todo`
    was never held."""
    import inspect

    from openfactory.runtime.temporal import activities

    for fn in (activities._child_to_todo, activities.scan_todo):
        src = inspect.getsource(fn)
        assert "_ticket_url(" in src, f"{fn.__name__} composes or calls the port directly"
        assert "tracker.ticket_url(" not in src, f"{fn.__name__} calls the port unguarded"
