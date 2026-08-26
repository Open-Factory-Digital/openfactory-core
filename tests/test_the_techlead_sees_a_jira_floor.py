"""The tech-lead's rounds must SEE a floor whose tickets are not numbers (#69).

WHY THIS FILE EXISTS RATHER THAN MORE CASES IN `test_techlead_watch.py`. That file tests `watch()`
— the pure function — by handing it a `FloorState` somebody built by hand. It is thorough and it
was completely blind to this bug, because the bug is upstream of it: the ACTIVITY that builds the
`FloorState` matched running workflows with `^openfactory-{project}-(\\d+)$`, so on a Jira/ADO deployment
it built an EMPTY one and `watch()` was asked, correctly, about nothing.

The only two tests that called the activity at all monkeypatched `connect()` to raise, so
execution never reached the matcher. A hundred green tests over the pure function, two over the
activity, and the line in between was reached by nothing — this repository's signature defect, in
the subsystem whose own docstring says a wrong verdict "poisons `hopeless()` permanently".

So these drive the REAL activity with a fake engine, and assert on what it saw.
"""

from __future__ import annotations

import pytest

import openfactory.runtime.temporal.activities as acts


class _Workflow:
    def __init__(self, wf_id: str) -> None:
        from datetime import UTC, datetime, timedelta

        self.id = wf_id
        # 18 HOURS AGO, deliberately: `watch()` leaves a park younger than STUCK_PARK_HOURS (3)
        # alone, so a workflow with no start_time reads as 0h and every assertion below would pass
        # for the wrong reason — the round would report "clean" because the park is FRESH, not
        # because the ref was unreadable. 18h is #478's real number.
        self.start_time = datetime.now(UTC) - timedelta(hours=18)


class _Handle:
    def __init__(self, parked: dict | None) -> None:
        self._parked = parked

    async def query(self, _name):
        return self._parked

    async def signal(self, _name, *, args):
        return None


class _Client:
    """Just enough Temporal client for `techlead_watch`: an async iterator of running workflows
    and a queryable handle per id."""

    def __init__(self, running: dict[str, dict | None]) -> None:
        self._running = running

    async def list_workflows(self, _query: str):
        for wf_id in self._running:
            yield _Workflow(wf_id)

    def get_workflow_handle(self, wf_id: str):
        return _Handle(self._running.get(wf_id))


@pytest.fixture
def floor(monkeypatch):
    """Everything `techlead_watch` reaches for except the engine, pinned. Returns a dict the test
    fills with `{workflow_id: parked_state_or_None}`."""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.memory import store as loop_store

    running: dict[str, dict | None] = {}
    project = Project(name="acme", repo_path="/tmp/acme",
                      tracker=ProviderRef(kind="jira", repo="ACME"))
    #: THE SIBLING IS REGISTERED, which is the only reason the guard below can work at all.
    #: `parse_job_id` splits on the known project names longest-first, so `acme-web` has to BE a
    #: known name for `openfactory-acme-web-478` to resolve to it rather than to `acme`. A fixture that
    #: registered only `acme` would let the sibling test pass through the parser's degraded
    #: fallback instead of through the guard, which is passing for the wrong reason.
    sibling = Project(name="acme-web", repo_path="/tmp/acme-web",
                      tracker=ProviderRef(kind="jira", repo="ACMEWEB"))

    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: project)
    monkeypatch.setattr(acts.ProjectRegistry, "list", lambda self: [project, sibling])
    monkeypatch.setattr(acts, "_land_product_proposals", lambda *a, **k: [])
    monkeypatch.setattr(acts, "_repoint_product_orphans", lambda *a, **k: [])
    monkeypatch.setattr(acts, "_queued_tickets", lambda p: [])
    monkeypatch.setattr(acts, "_recent_causes", lambda n: {})
    monkeypatch.setattr(acts, "_watch_history", lambda n: {})
    monkeypatch.setattr(acts, "_remember_watch", lambda n, said: None)
    monkeypatch.setattr(acts, "_finding_reminders", lambda n, ledger, lang="": [])
    monkeypatch.setattr(loop_store, "read", lambda name: [])
    monkeypatch.setattr(loop_store, "write", lambda name, loops, **kw: len(loops))

    async def _no_release(_project, _client):
        return ""

    monkeypatch.setattr(acts, "_offer_the_release_to_the_client", _no_release)

    async def _connect():
        return _Client(running)

    monkeypatch.setattr("openfactory.runtime.temporal.connection.connect", _connect)
    return running


#: A park the classifier reads as transient, so `watch()` marks it resumable and the round acts.
THROTTLED = "box failed: gh project field-list failed: GraphQL: API rate limit exceeded"


def _parked(hours_ago_note: str = THROTTLED) -> dict:
    return {"kind": "impediment", "state": "on_hold", "note": hours_ago_note}


def test_a_jira_ticket_parked_on_the_floor_is_SEEN(floor):
    """THE regression. `openfactory-acme-CONT-412` matched nothing under `(\\d+)`, so the rounds reported
    "clean" while the floor was held."""
    import asyncio

    floor["openfactory-acme-CONT-412"] = _parked()

    result = asyncio.run(acts.techlead_watch("acme"))

    assert result != "clean", "the rounds saw an empty floor while a Jira ticket held it"


def test_a_github_ticket_still_works(floor):
    """The other half. A fix that only understands the new shape would silently blind every
    existing deployment — all of which are numeric."""
    import asyncio

    floor["openfactory-acme-478"] = _parked()

    result = asyncio.run(acts.techlead_watch("acme"))

    assert result != "clean"


def test_a_sibling_project_is_never_counted_or_resumed(floor):
    """The guard the hand-rolled regex's own comment cited as its reason to exist: `openfactory-acme-` is
    a prefix of `openfactory-acme-web-478`. Losing it while widening the shape would let one project's
    rounds RESUME another project's jobs — strictly worse than the bug being fixed."""
    import asyncio

    floor["openfactory-acme-web-478"] = _parked()

    result = asyncio.run(acts.techlead_watch("acme"))

    assert result == "clean", "a sibling project's job was counted as this project's"


def test_an_unrelated_workflow_is_ignored(floor):
    import asyncio

    floor["poll-acme"] = _parked()
    floor["openfactory-other-CONT-1"] = _parked()

    assert asyncio.run(acts.techlead_watch("acme")) == "clean"


def test_the_jira_ticket_reaches_the_RESUME_signal_with_its_ref_intact(floor, monkeypatch):
    """Seeing it is half. The round's one real power is pressing resume, and the handle is fetched
    by workflow id — an int somewhere in between would build `openfactory-acme-0` and signal nothing."""
    import asyncio

    floor["openfactory-acme-CONT-412"] = _parked()
    asked: list[str] = []

    real_handle = _Client(floor).get_workflow_handle

    def _spy(self, wf_id):  # noqa: ARG001
        asked.append(wf_id)
        return real_handle(wf_id)

    monkeypatch.setattr(_Client, "get_workflow_handle", _spy)

    asyncio.run(acts.techlead_watch("acme"))

    assert "openfactory-acme-CONT-412" in asked, (
        f"the resume never addressed the real workflow id — asked for {asked}")


def test_the_channel_message_names_the_jira_ref_a_person_must_type(floor, monkeypatch):
    """The end of the chain, and the point of the whole subsystem: the sentence a human reads has
    to carry a ref their own channel can parse back (`resume CONT-412` — C-05, commands.py)."""
    import asyncio

    from openfactory.contracts.project import Project, ProviderRef

    project = Project(name="acme", repo_path="/tmp/acme",
                      tracker=ProviderRef(kind="jira", repo="ACME"), channel_id="C0ABC")
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: project)

    said: list[str] = []
    monkeypatch.setattr(
        "openfactory.adapters.channel.build_channel",
        lambda p: type("_C", (), {"say": lambda s, **kw: said.append(kw.get("text", "")) or True})())

    floor["openfactory-acme-CONT-412"] = _parked("something nobody has taught the factory to fix")

    asyncio.run(acts.techlead_watch("acme"))

    assert said, "the floor was held and the channel was told nothing"
    assert "CONT-412" in said[0], said[0]
