r"""A park alert carries its ticket on every tracker, not just numeric ones (C-43, #86).

`notify_coordinator_say` attached `about` — the ticket identity a provider links its thread to —
from `re.search(r"#(\d+)", text)`. Digits only. On a Jira or Azure DevOps deployment (refs like
`DAR-3`, `CONT-412`) it never matched, so `about` was always empty.

The comment beside `about` already stated the cost: *"a reply in the alert's own thread — `skip`,
the verb this very alert asks for — resolves to nothing"*. So the escalation fired, the human was
reached, and the executable option it offered was not executable from where it was offered: the
letter of the resilience invariant kept and the spirit broken — and only on the trackers we do not
run ourselves, which is why it survived.

Same class as #69, fixed in `techlead_watch` and left here.
"""

from __future__ import annotations

import pytest

from openfactory.runtime.temporal.activities import _ref_in


@pytest.mark.parametrize(("text", "expected"), [
    ("▶ Picking up #425", "425"),                       # GitHub, the shape that always worked
    ("Parked DAR-3 — needs you", "DAR-3"),              # Jira: this deployment runs it today
    ("CONT-412 is blocked on a decision", "CONT-412"),  # the client-2 shape (Azure DevOps)
    ("PR ready for AcmeFixtures/fx-multirepo-web#1",
     "AcmeFixtures/fx-multirepo-web#1"),         # C-18 qualified ref
])
def test_the_alert_finds_its_ticket(text, expected):
    assert _ref_in(text) == expected


@pytest.mark.parametrize("text", [
    "nothing here",
    "the release went out at 14h",
    "",
])
def test_prose_with_no_ticket_yields_nothing(text):
    """The positive twin. A pattern loose enough to find a ref in any sentence is loose enough to
    invent one — and `about` pointing at the WRONG ticket is worse than pointing at none: the
    reply resolves, to somebody else's work."""
    assert _ref_in(text) == ""


def test_a_bare_number_loses_its_hash():
    """Every tracker method takes the ref without it; `about` is passed straight through."""
    assert _ref_in("done #7") == "7"


def test_the_activity_uses_the_extractor_not_a_local_regex():
    """The reachability half. `_ref_in` returning the right answer proves nothing if the call site
    still carries `re.search(r"#(\\d+)")` — which is exactly the shape the bug had."""
    import inspect

    from openfactory.runtime.temporal import activities

    src = inspect.getsource(activities.notify_coordinator_say)
    assert "_ref_in(" in src
    assert r'#(\d+)' not in src
