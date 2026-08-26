"""The panel's Temporal bridge: id parsing, row mapping, and graceful degradation.

The bridge must READ live engine state for the product surface AND never break the
panel when the engine (or the runtime extra) is absent — robustness over reach.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from temporalio.client import WorkflowExecutionStatus

from openfactory import namespace
from openfactory.api import app as app_module
from openfactory.runtime.temporal import view as tv


# --- pure helpers ---
def test_job_id_roundtrips():
    assert tv.job_id("books", "189") == "openfactory-books-189"
    assert tv.parse_job_id("openfactory-books-189") == ("books", "189")


def test_parse_ignores_foreign_ids():
    assert tv.parse_job_id("some-other-workflow") == (None, None)


def test_status_label_maps_and_defaults():
    assert tv.status_label(WorkflowExecutionStatus.RUNNING) == "running"
    assert tv.status_label(WorkflowExecutionStatus.COMPLETED) == "completed"
    assert tv.status_label(None) == "unknown"


def test_temporal_url_points_at_the_ui(monkeypatch):
    monkeypatch.setenv("TEMPORAL_UI_URL", "http://ui:8233")
    url = tv.temporal_url("openfactory-books-189", "run-1", "default")
    assert url == "http://ui:8233/namespaces/default/workflows/openfactory-books-189/run-1/history"


# --- row mapping via a fake client ---
class _FakeWf:
    def __init__(self, wf_id, status, memo=None, true_status=None, result=None, park=None):
        self.id = wf_id
        self.run_id = "run-x"
        self.status = status
        # true_status models the AUTHORITATIVE describe() status (vs the possibly-lagged
        # visibility `status`). Defaults to the visibility status when not diverging.
        self.true_status = true_status or status
        self.result = result if result is not None else {}
        # park models awaiting_action's answer on a genuinely-LIVE workflow (an impediment park);
        # None = not parked. Only consulted when the workflow is truly RUNNING.
        self.park = park
        self.start_time = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        self.close_time = None
        self._memo = memo or {}

    async def memo(self):
        return self._memo


class _FakeJobHandle:
    """Models a live workflow handle: describe() returns the AUTHORITATIVE status, awaiting_action
    reports the wf's park (the other awaiting_* queries report None), and result() the run result."""

    def __init__(self, wf):
        self._wf = wf

    async def describe(self):
        return type("D", (), {"status": self._wf.true_status, "run_id": self._wf.run_id})()

    async def query(self, name=None, *a, **k):
        return self._wf.park if getattr(name, "__name__", str(name)) == "awaiting_action" else None

    async def result(self):
        return self._wf.result


class _FakeClient:
    def __init__(self, wfs):
        self._wfs = wfs
        self.seen_query = None

    def list_workflows(self, query):
        self.seen_query = query

        async def gen():
            for w in self._wfs:
                yield w

        return gen()

    def get_workflow_handle(self, wf_id, run_id=None):
        wf = next((w for w in self._wfs if w.id == wf_id), None)
        if wf is None:
            raise RuntimeError("workflow not found")
        return _FakeJobHandle(wf)


async def test_list_jobs_maps_rows():
    client = _FakeClient([
        _FakeWf("openfactory-books-189", WorkflowExecutionStatus.RUNNING),
        _FakeWf("openfactory-podbeam-4", WorkflowExecutionStatus.COMPLETED),
    ])
    rows = await tv.list_jobs(client, "default")
    assert 'WorkflowType = "JobWorkflow"' in client.seen_query
    assert [(r["project"], r["issue"], r["status"]) for r in rows] == [
        ("books", "189", "running"),
        ("podbeam", "4", "completed"),
    ]
    assert rows[0]["temporal_url"].endswith("/workflows/openfactory-books-189/run-x/history")
    assert all("title" in r for r in rows)  # every row carries a title field (may be "")


async def test_visibility_lagged_running_is_corrected_not_a_ghost():
    # The visibility store lists a just-terminated workflow as RUNNING for a while. describe()
    # is authoritative: the row must NOT read status=='running' (which paints an 'in production'
    # ghost card that never clears) — it is stamped 'closed' and carries its real domain state.
    tv._state_cache.clear()
    client = _FakeClient([
        _FakeWf("openfactory-books-37", WorkflowExecutionStatus.RUNNING,   # visibility says running
                true_status=WorkflowExecutionStatus.TERMINATED),       # …but it's terminated
    ])
    rows = await tv.list_jobs(client, "default")
    assert len(rows) == 1
    assert rows[0]["status"] == "closed"      # not 'running' → no ghost machine card
    assert rows[0]["state"] != "running"


async def test_live_parked_job_is_attention():
    # A genuinely RUNNING job parked on an impediment DOES need a human → attention True.
    tv._state_cache.clear()
    client = _FakeClient([
        _FakeWf("openfactory-books-412", WorkflowExecutionStatus.RUNNING,
                park={"kind": "impediment", "state": "on_hold", "note": "push rejected"}),
    ])
    rows = await tv.list_jobs(client, "default")
    assert rows[0]["state"] == "on_hold"
    assert rows[0]["attention"] is True


async def test_closed_job_with_parked_state_is_not_attention():
    # ROOT FIX: a CLOSED workflow can still carry a parked-ish domain state — a run TERMINATED
    # while on_hold (→ 'failed'), or COMPLETED after a needs_refinement park. Neither needs a
    # human anymore: attention must be False (gated on `live`), else the panel/Slack show a
    # phantom "needs attention" for a finished job (the #416/#386 ghosts).
    tv._state_cache.clear()
    client = _FakeClient([
        # terminated (visibility lags to running) → domain state 'failed' (in ATTENTION_STATES)
        _FakeWf("openfactory-books-386", WorkflowExecutionStatus.RUNNING,
                true_status=WorkflowExecutionStatus.TERMINATED),
        # completed with a cached parked result state
        _FakeWf("openfactory-books-416", WorkflowExecutionStatus.COMPLETED,
                result={"state": "on_hold"}),
    ])
    rows = await tv.list_jobs(client, "default")
    by = {r["issue"]: r for r in rows}
    assert by["386"]["state"] == "failed" and by["386"]["attention"] is False
    assert by["416"]["state"] == "on_hold" and by["416"]["attention"] is False
    assert by["386"]["status"] == "closed" and by["416"]["status"] == "completed"


async def test_aged_out_workflow_is_dropped_from_the_frame():
    # describe() raises (workflow gone from retention) → the row is omitted entirely, so a
    # stale entry the visibility store still returns can't linger on the board.
    class _GoneClient(_FakeClient):
        def get_workflow_handle(self, wf_id, run_id=None):
            raise RuntimeError("workflow not found for ID")

    client = _GoneClient([_FakeWf("openfactory-books-37", WorkflowExecutionStatus.RUNNING)])
    rows = await tv.list_jobs(client, "default")
    assert rows == []


class _FakeHandle:
    def __init__(self, status, result=None):
        self._status = status
        self._result = result

    async def describe(self):
        return type("D", (), {"status": self._status})()

    async def result(self):
        return self._result


class _DeployClient:
    def __init__(self, handles):
        self._handles = handles  # wf_id -> _FakeHandle (missing = no watch)

    def get_workflow_handle(self, wf_id, run_id=None):
        if wf_id not in self._handles:
            raise RuntimeError("workflow not found")
        return self._handles[wf_id]


async def test_deploy_state_reads_the_watch_outcome():
    tv._deploy_cache.clear()
    client = _DeployClient({
        "openfactory-deploy-books-1": _FakeHandle(WorkflowExecutionStatus.COMPLETED, "success"),
        "openfactory-deploy-books-2": _FakeHandle(WorkflowExecutionStatus.COMPLETED, "failure"),
        "openfactory-deploy-books-3": _FakeHandle(WorkflowExecutionStatus.RUNNING),
    })
    assert await tv._deploy_state(client, "books", "1") == "deployed"
    assert await tv._deploy_state(client, "books", "2") == "deploy_failed"
    assert await tv._deploy_state(client, "books", "3") == "deploying"  # still watching
    assert await tv._deploy_state(client, "books", "9") is None  # no watch for this job
    # a terminal outcome is cached — no second describe needed
    assert "openfactory-deploy-books-1" in tv._deploy_cache
    assert "openfactory-deploy-books-3" not in tv._deploy_cache  # running → re-checked, not cached


async def test_list_jobs_surfaces_the_memo_title():
    # the workflow stamped the ticket title into its memo → the panel row carries it, so the
    # UI can show "#189 Add health check" instead of a bare number (ADR-0005 companion).
    client = _FakeClient([
        _FakeWf("openfactory-books-189", WorkflowExecutionStatus.RUNNING,
                memo={"title": "Add health check"}),
        _FakeWf("openfactory-books-190", WorkflowExecutionStatus.RUNNING),  # no memo → ""
    ])
    rows = await tv.list_jobs(client, "default")
    assert rows[0]["title"] == "Add health check"
    assert rows[1]["title"] == ""  # older/untitled jobs degrade to just the number


# --- graceful degradation at the endpoint ---
@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_temporal_jobs_degrades_when_engine_down(client, monkeypatch):
    async def boom():
        raise ConnectionError("no engine here")

    monkeypatch.setattr(tv, "connect", boom)
    r = client.get("/api/temporal/jobs")
    assert r.status_code == 200  # panel still renders
    body = r.json()
    assert body["connected"] is False
    assert body["jobs"] == []


def test_temporal_approve_needs_authorized_approver(client, monkeypatch, tmp_path):
    # unknown approver → 403 before any engine call (durable signal is gated on auth).
    # The store must be non-empty: an EMPTY store is a config error and 503s instead.
    monkeypatch.setenv("OPENFACTORY_APPROVERS", '{"alice": "not-a-real-hash"}')
    monkeypatch.delenv("OPENFACTORY_PROD_APPROVERS", raising=False)
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    repo = tmp_path / "repo"
    (repo / namespace.DIR).mkdir(parents=True)
    (repo / namespace.MANIFEST).write_text("version: 1\nbase_branch: main\n")
    ProjectRegistry().add(
        Project(name="p", repo_path=str(repo), tracker=ProviderRef(kind="github", repo="o/p"))
    )
    r = client.post(
        "/api/temporal/approve/p/5",
        json={"approver": "ghost", "password": "x", "version": "1.0.0"},
    )
    assert r.status_code == 403


# --- card-click briefing: the "why" derivation (observability) ---
def test_why_explains_each_state():
    assert "Merged" in tv._why("merged", {})
    # a suppression is the reason, and the text teaches what it means + what to do
    w = tv._why("pr_open", {"added_suppressions": ["pragma: no cover"]})
    assert "pragma: no cover" in w and "human" in w and "coverage" in w.lower()
    # a rejected review carries the verdict + summary
    w = tv._why("pr_open", {"review": {"decision": "rejected", "score": 40, "summary": "bad test"}})
    assert "REJECTED" in w and "40" in w and "bad test" in w
    # the generic human path (no suppression, not rejected) still explains itself
    assert "human" in tv._why("pr_open", {}).lower()
    # on_hold / needs_refinement surface the note
    assert tv._why("on_hold", {"note": "conflict"}) == "conflict"
    assert "refinement" in tv._why("needs_refinement", {}).lower()
