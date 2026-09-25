"""The two ways a document is read (#269 slice 1): on the knowledge pipeline's schedule, and by
an event that names the file.

  - the SCHEDULE: `KnowledgeRefreshWorkflow` — the knowledge pipeline's own tick — runs the
    documents pass after the map, on the product role's own checkout of the context repository;
  - the EVENT: the `product_ingest` row, which the panel's upload will call (#269 point 10) and an
    operator can call today, reads the named file alone.

The workflow runs for real on Temporal's time-skipping environment with its two activities stood
in for; the activity and the row run for real on a copy of the fixture's context repository.
"""

from __future__ import annotations

import asyncio
import types
import uuid

import pytest

from openfactory import actions
from openfactory.product.documents.store import Store
from openfactory.runtime.temporal.io import KnowledgeRefreshInput
from tests import documents_bed as bed


def _checkout(tree, *, terms=bed.TERMS):
    """The product role's own context as `ProductModule.context` answers it — its checkout of the
    context repository, the commit it is at, and the glossary."""
    from openfactory.product.domain import Domain, Fact

    return types.SimpleNamespace(docs_path=str(tree), docs_commit="c0ffee", reason="",
                                 domain=Domain(facts=[Fact(term=t) for t in terms]))


@pytest.fixture
def registered(tmp_path, monkeypatch):
    from openfactory.product.module import ProductModule
    from openfactory.registry import ProjectRegistry

    project = bed.project(tmp_path)
    ProjectRegistry().add(project)
    tree = bed.context(tmp_path)
    monkeypatch.setattr(ProductModule, "context", lambda self, **_k: _checkout(tree))
    monkeypatch.setattr("openfactory.product.documents.ingest.ModelReader",
                        lambda **_k: bed.StubReader())
    return project, tree


# ── the schedule ────────────────────────────────────────────────────────────────────────────────

def test_the_scheduled_pass_reads_the_product_role_s_own_checkout(registered):
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    project, tree = registered
    (tree / "sla.pdf").write_bytes(bed.text_pdf("Service level agreement"))

    said = acts._do_ingest_documents(KnowledgeRefreshInput(project=project.name))

    assert said == "8 new version(s) recorded, 0 unchanged"
    store = Store(bed.KEY)
    assert store.index()["commit"] == "c0ffee"
    readme = store.get("README.md", store.index()["paths"]["README.md"]["digest"])
    assert readme.commit == "c0ffee" and "Reconciled Statement" in readme.entities
    assert acts._do_ingest_documents(KnowledgeRefreshInput(project=project.name)) == (
        "0 new version(s) recorded, 8 unchanged")


def test_the_scheduled_pass_says_why_it_read_nothing(tmp_path, monkeypatch):
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.product.module import ProductModule
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    registry = ProjectRegistry()
    registry.add(Project(name="plain", repo_path=str(tmp_path / "plain"),
                         tracker=ProviderRef(kind="github", repo="lark/plain"),
                         forge=ProviderRef(kind="github", repo="lark/plain")))
    registry.add(bed.project(tmp_path))

    assert acts._do_ingest_documents(KnowledgeRefreshInput(project="plain")) == "off"
    assert acts._do_ingest_documents(KnowledgeRefreshInput(project="nobody")) == "off"
    monkeypatch.setattr(ProductModule, "context",
                        lambda self, **_k: types.SimpleNamespace(docs_path="", reason="down"))
    assert acts._do_ingest_documents(KnowledgeRefreshInput(project="lark")) == "no-context"

    def broken(self, **_k):
        raise RuntimeError("the checkout broke")

    monkeypatch.setattr(ProductModule, "context", broken)
    assert acts._do_ingest_documents(KnowledgeRefreshInput(project="lark")) == "failed"


#: What the two stood-in activities of the tick were asked, in order.
_RAN: list[str] = []


async def _refresh(inp: KnowledgeRefreshInput) -> str:
    _RAN.append(f"map:{inp.project}")
    return "unchanged"


async def _documents(inp: KnowledgeRefreshInput) -> str:
    _RAN.append(f"documents:{inp.project}")
    return "1 new version(s) recorded, 6 unchanged"


async def _distil(inp: KnowledgeRefreshInput) -> str:
    _RAN.append(f"distil:{inp.project}")
    return "1 conversation(s) distilled"


@pytest.mark.owns_its_engine
async def test_the_knowledge_pipeline_s_tick_reads_the_documents_after_the_map():
    from temporalio import activity
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from openfactory.runtime.temporal.workflow import KnowledgeRefreshWorkflow

    _RAN.clear()
    ran = _RAN
    refresh = activity.defn(name="refresh_knowledge")(_refresh)
    documents = activity.defn(name="ingest_documents")(_documents)
    # the product's quiet conversations are distilled between the two (#269 slice 3), so the tick
    # that writes a distillate also ingests it
    distilled = activity.defn(name="distil_conversations")(_distil)

    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        async with Worker(env.client, task_queue="tq-documents",
                          workflows=[KnowledgeRefreshWorkflow],
                          activities=[refresh, distilled, documents]):
            said = await env.client.execute_workflow(
                KnowledgeRefreshWorkflow.run, "lark", id=f"okf-{uuid.uuid4()}",
                task_queue="tq-documents")
    finally:
        await env.shutdown()

    assert ran == ["map:lark", "distil:lark", "documents:lark"]
    assert said == ("unchanged; conversations: 1 conversation(s) distilled; documents: 1 new "
                    "version(s) recorded, 6 unchanged")


def test_the_worker_registers_the_documents_activity():
    from openfactory.runtime.temporal.activities import ingest_documents
    from openfactory.runtime.temporal.worker import WORKER_ACTIVITIES

    assert ingest_documents in WORKER_ACTIVITIES
    from openfactory.runtime.temporal.activities import distil_conversations

    assert distil_conversations in WORKER_ACTIVITIES


def test_the_tick_is_bounded_for_both_of_its_activities():
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal import schedule as sched

    built = sched._okf_schedule("lark", sched.OKF_EVERY_HOURS)
    assert built.action.execution_timeout.total_seconds() >= 3 * 10 * 60
    assert acts.DOCUMENT_PASS_SECONDS < 10 * 60, "the pass ends inside its activity's ten minutes"
    assert acts.DISTIL_PASS_SECONDS < 10 * 60, "and so does the distillation's (#269 slice 3)"


# ── the event ───────────────────────────────────────────────────────────────────────────────────

def _admin():
    return actions.Actor(id="ana", display="Ana", via="panel", admin=True)


def test_the_event_reads_the_named_file_alone(registered, monkeypatch):
    project, tree = registered
    calls = bed.count_extractions(monkeypatch)
    (tree / "nda.pdf").write_bytes(bed.protected_pdf("Mutual NDA"))

    out = asyncio.run(actions.perform("product_ingest", by=_admin(), project=project.name,
                                      path="nda.pdf"))

    assert out.ok, out.message
    assert out.data["ingested"] == ["nda.pdf"] and calls == [("pdf", "nda.pdf")]
    assert out.data["unreadable"] == [
        {"path": "nda.pdf", "reason": "a protected PDF: it needs a password to be opened"}]
    assert out.message == "1 new version(s) recorded, 1 of them unreadable, 0 unchanged"


def test_the_event_with_no_file_reads_what_changed(registered):
    project, tree = registered
    out = asyncio.run(actions.perform("product_ingest", by=_admin(), project=project.name))
    assert out.ok and len(out.data["ingested"]) == 7


def test_the_event_refuses_a_path_outside_the_repository_and_a_reader_who_is_not_an_admin(
        registered):
    project, _tree = registered
    outside = asyncio.run(actions.perform("product_ingest", by=_admin(), project=project.name,
                                          path="../secrets.txt"))
    assert not outside.ok
    assert outside.message == "../secrets.txt: not a path inside the context repository"
    absent = asyncio.run(actions.perform("product_ingest", by=_admin(), project=project.name,
                                         path="minutes/never-written.md"))
    assert not absent.ok and absent.message == (
        "minutes/never-written.md: there is no such file in the context repository")

    reader = actions.Actor(id="bia", display="Bia", via="panel", admin=False)
    refused = asyncio.run(actions.perform("product_ingest", by=reader, project=project.name,
                                          path="README.md"))
    assert not refused.ok and Store(bed.KEY).index()["paths"] == {}


def test_the_event_without_a_checkout_says_so(tmp_path, monkeypatch):
    from openfactory.product.module import ProductModule
    from openfactory.registry import ProjectRegistry

    ProjectRegistry().add(bed.project(tmp_path))
    monkeypatch.setattr(ProductModule, "context", lambda self, **_k: types.SimpleNamespace(
        docs_path="", reason="the documentation repo could not be checked out"))
    out = asyncio.run(actions.perform("product_ingest", by=_admin(), project="lark"))
    assert not out.ok and out.message == "the documentation repo could not be checked out"
