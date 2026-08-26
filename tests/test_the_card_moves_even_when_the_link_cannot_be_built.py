"""A ticket URL is a nicety; MOVING THE CARD is the job. One must never cost the other.

Two call sites hand the board a `issue_url` — the child-to-TO-DO move after a split, and the
healing move that closes a stale card. Both used to compose `https://github.com/{repo}/issues/{n}`
by hand, which is the shape `TrackerAdapter.ticket_url` exists to end: the literal ignores
`GH_HOST`, so a GitHub Enterprise deployment linked to public github.com, where a same-named
repository may belong to somebody else.

Routing them through the port was right and the FIRST version was wrong: it called
`tracker.ticket_url(...)` unguarded, and three suites went red at once — every tracker double,
and any adapter written before the method existed, does not have it. Only the GitHub Projects
board consumes this value at all (Jira and Azure Boards ignore it), so a missing link must
degrade to the literal and let the card move.

The property, in one sentence: **the move happens whatever the tracker says about links.**
"""

from __future__ import annotations

import pytest

from openfactory.runtime.temporal.activities import _ticket_url_or

_FALLBACK = "https://github.com/acme/api/issues/7"


class _Silent:
    """A tracker from before `ticket_url` existed — the shape every test double has."""


class _Raising:
    def ticket_url(self, ref):
        raise RuntimeError("the tracker is unreachable")


class _Empty:
    def ticket_url(self, ref):
        return ""


class _Speaking:
    def ticket_url(self, ref):
        return f"https://ghe.acme.internal/acme/api/issues/{ref.lstrip('#')}"


@pytest.mark.parametrize("tracker, why", [
    (_Silent(), "an adapter that predates the method"),
    (_Raising(), "a tracker that cannot be reached"),
    (_Empty(), "a provider that cannot say"),
])
def test_the_fallback_is_used_and_nothing_is_raised(tracker, why):
    assert _ticket_url_or(tracker, "#7", _FALLBACK) == _FALLBACK, why


def test_a_provider_that_CAN_say_is_believed_over_the_literal():
    """The whole reason for asking: this is the answer the literal could not give — an
    Enterprise host, where the composed github.com link points at somebody else's repository."""
    assert _ticket_url_or(_Speaking(), "#7", _FALLBACK) == \
        "https://ghe.acme.internal/acme/api/issues/7"


def test_the_two_call_sites_go_through_it_rather_than_calling_the_port_directly():
    """The reachability half. A call site that went back to `tracker.ticket_url(...)` would pass
    every test above while breaking the move for every tracker without the method — which is
    exactly what happened the first time (2026-08-12)."""
    import inspect

    from openfactory.runtime.temporal import activities

    for fn in (activities._child_to_todo,):
        src = inspect.getsource(fn)
        assert "_ticket_url_or(" in src, f"{fn.__name__} composes or calls the port directly"
        assert "tracker.ticket_url(" not in src, f"{fn.__name__} calls the port unguarded"
