"""A staged proposal does not outlive its test — the guard for
`conftest._a_staged_proposal_does_not_outlive_its_test`.

`product/staging.py::_PENDING` is a process-wide dict keyed by CONVERSATION, which is right in a
worker and wrong in a test process: twenty-five files in this suite hold their conversation in
`C1`, so a proposal one of them stages is the next one's "proposal awaiting approval". What it
costs is not a wrong assertion but a MODEL CALL nobody asked for, attributed to the wrong
sentence — the reply is judged as a confirmation of the leftover before it is read as anything
else.

MEASURED ON CI (2026-09-21, PR #261 run 502, on a change that touches none of this):
`test_the_chat_s_own_gesture_IS_an_explicit_request` failed `2 == 1`, having judged `quebra o
requisito 12 em tarefas` against a stale proposal first. Green on every laptop, green on that
file alone under twelve seeds, red in one second with a single entry staged under `C1` ahead of
it — which is what `test_the_fixture_ITSELF_clears_a_staged_proposal` drives.

THE FIRST TEST EXECUTES THE FIXTURE, rather than reading the conftest or trusting the pair below:
under a random order `test_2` may run before `test_1` and pass having measured nothing, and a
guard that can pass vacuously is how this class survives in the first place.
"""

from __future__ import annotations

import time

from openfactory.product import staging

#: the conversation twenty-five files in this suite share
SHARED = "C1"


def _a_proposal() -> dict:
    return {"kind": "fact", "term": "erp", "body": "a firma usa Primavera",
            "channel": SHARED, "staged_at": time.time()}


def test_the_fixture_ITSELF_clears_a_staged_proposal():
    """The conftest fixture, CALLED — not a copy of it, and not its docstring."""
    from tests import conftest

    staging._PENDING[SHARED] = _a_proposal()
    staging._EXPIRED_TOMBSTONES[SHARED] = time.time()

    conftest._a_staged_proposal_does_not_outlive_its_test.__wrapped__()

    assert staging._PENDING == {}, (
        "the fixture every test runs under left a staged proposal behind — the next test's "
        "`find_waiting` will answer with it, and judge that test's sentence as a confirmation")
    assert SHARED not in staging._EXPIRED_TOMBSTONES, (
        "the tombstone survived, so the next test's first yes is answered 'that expired'")


def test_1_a_test_stages_a_proposal_in_the_shared_conversation():
    staging.remember(SHARED, _a_proposal(), project=None)
    assert staging.pending_for(SHARED) is not None, "the first test really did stage one"


def test_2_the_next_test_starts_from_nothing():
    assert staging.pending_for(SHARED) is None, (
        "the previous test's proposal survived into this one — the next reply in `C1` is judged "
        "as a confirmation of something this test never staged")
    assert staging.find_waiting(SHARED, SHARED) == (None, None)
