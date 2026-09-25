"""Capabilities across sources, turn-time concept checks, blind spots, the gap signal and the
traceability chain (#268 slice 3; ADR-0052 D19–D23).

THE BED IS THE MICROSERVICE FIXTURE OF THE BATTERY (`tests/fixtures/evaluation/quayside/`): a
context repository and four service repositories, made real git repositories here and served over
`file://`. The context repository carries what the platform's own writers published for them —
three per-source bundles (the platform service has none: the blind spot), the system map
(`.okf/system/`) and the flows the pipeline observed across them (`.okf/flows/`). The loader, the
module, the workspace, the caches, the checks and git are real; the model is a stub harness that
does what the prompt tells it, through the sandbox's `run`, at the paths the prompt names. So "the
role is handed what spans three services" is measured the way the role would read it.

What is pinned, in the acceptance's order:

  1. a question whose answer spans three services is handed, in the prompt and the files, the
     flow that spans them — its concept cites the code of all three, and the role opens each;
  2. a cited concept whose code moved is named stale — in the prompt, in the reading, in the answer;
  3. code no concept covers, read by a turn, raises exactly one `no-concept` request to the
     knowledge pipeline — never twice, never for what a concept or an exemption covers, never for a
     path outside `sources:` — and the pipeline, at its own entry, records it; the role writes no
     bundle;
  4. "is requirement N in production, and in which version?" is answered from the chain, and so are
     "what code serves this capability?" and "what does a change to this part touch?";
  5. a capability is never curated truth before a person of the product confirms it, and a link of
     a confirmed one that no longer holds is reported.

Then the pieces alone: the check never reads outside the tree it names, the flows are what the
pipeline observes of the fixture, the blind spots are bounded and said.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.contracts import AgentRunResult
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.knowledge import requests as asked
from openfactory.knowledge.okf import parse_concept
from openfactory.product.module import ProductModule
from openfactory.product.speaker import ENGINEER, Person

FIXTURE = Path(__file__).parent / "fixtures" / "evaluation" / "quayside"
REPOS = ("quayside-orders", "quayside-billing", "quayside-freight", "quayside-platform")
#: The three services REQ-0001 crosses, and the line of each that its part of the flow is.
THREE = {"quayside-orders": ("orders/placing.py", "def place(order: Order, quote, publish)"),
         "quayside-billing": ("billing/invoicing.py", "def on_order_placed(event: dict"),
         "quayside-freight": ("freight/quote.py", "def quote(origin_port: str")}
FLOW = "0001-an-order-is-invoiced-the-moment-it-is-placed"
FLOW_FILE = "concepts/flow/an-order-is-invoiced-the-moment-it-is-placed.md"
UNCOVERED = "orders/cancelling.py"


# ── the bed ─────────────────────────────────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})
    return done.stdout


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def _repository(src: Path, dest: Path) -> Path:
    """`src` as a git repository at `dest`, one commit on `main`, serving partial clones."""
    shutil.copytree(src, dest)
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "config", "user.name", "fixture")
    _git(dest, "config", "user.email", "fixture@example.invalid")
    _git(dest, "config", "commit.gpgsign", "false")
    _git(dest, "config", "uploadpack.allowFilter", "true")
    _git(dest, "config", "uploadpack.allowAnySHA1InWant", "true")
    _commit(dest, "the fixture")
    return dest


class _Checkouts:
    """The loader's cache, answering the context repository's key with the fixture's own."""

    def __init__(self, context: Path) -> None:
        from openfactory.runtime.repo_cache import RepoCache

        self._cache, self._context = RepoCache(), context

    def sync(self, project: str, clone_url: str, base_branch: str = ""):
        from openfactory.product.loader import DOCS_CACHE_SUFFIX

        url = str(self._context) if project.endswith(DOCS_CACHE_SUFFIX) else clone_url
        return self._cache.sync(project, url, base_branch)


@dataclass
class Bed:
    tmp: Path
    repos: dict[str, Path]
    context: Path
    project: Project

    def module(self, agent=None) -> ProductModule:
        from openfactory.product.loader import load_product_context

        ctx = load_product_context(self.project, cache=_Checkouts(self.context))
        return ProductModule(self.project, context=ctx, agent=agent)

    def inbox(self) -> Path:
        return asked.inbox_for(self.project)

    def requests(self) -> list[dict]:
        path = self.inbox()
        if not path.is_file():
            return []
        return list(json.loads(path.read_text(encoding="utf-8"))["requests"].values())


@pytest.fixture()
def bed(tmp_path, monkeypatch) -> Bed:
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "null")
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    # the read model is #267's, and reads the engine; the tests that walk the chain hand one in
    monkeypatch.setattr("openfactory.product.module._the_read_model", lambda module, root: {})
    made = tmp_path / "repositories"
    repos = {name: _repository(FIXTURE / "sources" / name, made / name) for name in REPOS}
    context = _repository(FIXTURE / "context", made / "quayside-context")
    # a person's confirmation is pushed to it, as to a forge
    _git(context, "config", "receive.denyCurrentBranch", "updateInstead")
    urls = {**{name: f"file://{path}" for name, path in repos.items()},
            "quayside-context": f"file://{context}"}

    def clone_url(self, repo):
        return urls.get(repo, f"file://{tmp_path}/nowhere/{repo}")

    monkeypatch.setattr(ProductModule, "_clone_url", clone_url)
    local = {"kind": "local", "repo": "quayside-orders", "options": {}}
    project = Project(name="quayside", repo_path=str(repos["quayside-orders"]),
                      tracker=ProviderRef(**local), forge=ProviderRef(**local),
                      ci=ProviderRef(kind="none", repo="quayside-orders", options={}),
                      product=ProductConfig(docs_repo="quayside-context", admins=["ines"]))
    return Bed(tmp=tmp_path, repos=repos, context=context, project=project)


class _Recording:
    """A harness that records the prompt and answers `answer`."""

    name = "recording"

    def __init__(self, answer: str = "ok") -> None:
        self.prompts: list[str] = []
        self.answer = answer

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        return AgentRunResult(ok=True, summary=self.answer)


_MOUNTED = re.compile(r"^  - `(src/[^`]+)/` — the repository `([^`]+)`", re.MULTILINE)
_FLOWS = re.compile(r"`([^`]+)/index\.md` lists the flows that cross services")


class _Walker(_Recording):
    """A harness that does what the prompt says a question spanning services asks: it opens the
    flows' door the prompt names, opens the flow's concept, and then the code of every part the
    concept cites — each in the directory the prompt says that repository is mounted at, through
    the sandbox. Nothing here knows where anything is except the prompt."""

    def __init__(self) -> None:
        super().__init__()
        self.flow_text = ""
        self.opened: dict[str, tuple[str, str]] = {}

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        mounted = {repo: where for where, repo in _MOUNTED.findall(prompt)}
        door = _FLOWS.search(prompt)
        cited = []
        if door:
            rc, listing = sandbox.run(workspace=workspace, timeout=30,
                                      command=f"ls {door.group(1)}/concepts/flow")
            name = next((n for n in listing.split() if n.endswith(".md")), "")
            rc, self.flow_text = sandbox.run(workspace=workspace, timeout=30,
                                             command=f"cat {door.group(1)}/concepts/flow/{name}")
            cited.append(f"{door.group(1)}/concepts/flow/{name}")
            concept = parse_concept(self.flow_text)
            for source in (concept.sources if concept else []):
                where = mounted.get(source.repo)
                if where is None:
                    continue
                rc, text = sandbox.run(workspace=workspace, timeout=30,
                                       command=f"cat {where}/{source.path}")
                if rc == 0:
                    self.opened[source.repo] = (f"{where}/{source.path}", text)
        self.answer = ("Placing an order fixes the freight quote on it and announces it; billing "
                       "invoices it with that freight.\n[[EVIDENCIA: " + "; ".join(
                           [*cited, "REQ-0001", *(p for p, _ in self.opened.values())]) + "]]")
        return super().ask(sandbox=sandbox, workspace=workspace, prompt=prompt, phase=phase)


# ── 1. the question that spans three services ──────────────────────────────────────────────────

def test_a_question_spanning_three_services_is_handed_the_flow_that_spans_them(bed):
    """THE ACCEPTANCE: the role is told where the flows across services are, the flow of REQ-0001
    is a concept whose sources cite the code of all three services, and the role — following the
    prompt alone — opens that concept and the code of every part of it."""
    walker = _Walker()
    answer = bed.module(agent=walker).answer("is the freight on the invoice when an order is "
                                             "placed?")

    assert answer.ok, answer
    prompt = walker.prompts[0]
    assert "`docs/.okf/flows/index.md` lists the flows that cross services" in prompt
    # the capability section names the flow, what carries it, and that nobody confirmed it
    assert "**Observed, NOT confirmed by anybody**" in prompt
    assert (f"- An order is invoiced the moment it is placed — its flow concept "
            f"`docs/.okf/flows/{FLOW_FILE}` — REQ-0001; components billing, freight, orders; "
            f"concepts `quayside-billing` — Invoicing a placed order, `quayside-freight` — The "
            f"freight calculation, `quayside-orders` — Placing an order") in prompt
    # the flow's own concept cites the code of all three services, each naming its repository
    concept = parse_concept(walker.flow_text)
    assert concept is not None and concept.type == "flow"
    assert {s.repo: s.path for s in concept.sources} == {r: p for r, (p, _) in THREE.items()}
    for step in ("billing → orders over http", "orders → billing over event",
                 "orders → freight over grpc"):
        assert step in walker.flow_text, step
    # and the role opened the code of every one, in the directory it is mounted at
    assert sorted(walker.opened) == sorted(THREE)
    for repo, (path, text) in walker.opened.items():
        rel, line = THREE[repo]
        assert path == f"src/{repo}/{rel}" and line in text, (repo, path)
        assert text == (FIXTURE / "sources" / repo / rel).read_text()


def test_the_answer_that_cites_the_flow_and_the_three_services_is_bound_alta(bed):
    """The citations reach the bound: the flow's concept is found (the flows are one of the bundles
    a reading stands on), it is fresh against the code mounted for every repository it names, and
    the three code files are the reading's code — so the answer is `alta`, and none of the code it
    read is a gap."""
    from openfactory.product.reading import ALTA

    walker = _Walker()
    answer = bed.module(agent=walker).answer("is the freight on the invoice?")

    reading = answer.reading
    assert reading.confidence == ALTA, reading.bounded_by
    assert reading.verified["concepts"] == {f"docs/.okf/flows/{FLOW_FILE}": "fresh"}
    assert reading.verified["requirements"] == {1: True}
    assert sorted(reading.code) == sorted(f"src/{r}/{p}" for r, (p, _) in THREE.items())
    assert bed.requests() == [], "code every concept covers was signalled as a gap"


def test_the_flow_concept_is_checked_source_by_source_against_the_repository_each_names(bed):
    """The flow's sources lie in three repositories; checked against one, two of them would read
    as missing. Checked across, every one is fresh — and a source whose repository is not mounted
    is unverifiable, never looked for elsewhere."""
    from openfactory.knowledge.check import FRESH, UNVERIFIABLE, check_across

    flows = FIXTURE / "context" / ".okf" / "flows"
    trees = {repo: FIXTURE / "sources" / repo for repo in THREE}
    [flow] = check_across(flows, trees).concepts
    assert flow.verdict == FRESH and len(flow.sources) == 3

    del trees["quayside-billing"]
    [flow] = check_across(flows, trees).concepts
    assert flow.verdict == UNVERIFIABLE
    [billing] = [s for s in flow.sources if s.path == "billing/invoicing.py"]
    assert billing.verdict == UNVERIFIABLE and "`quayside-billing` is not mounted" in billing.detail


# ── 2. a stale cited concept is named stale ────────────────────────────────────────────────────

def _move_billing(bed: Bed) -> None:
    path = bed.repos["quayside-billing"] / "billing" / "invoicing.py"
    path.write_text(path.read_text().replace("round(self.lines_total + self.freight_amount, 2)",
                                             "round(self.lines_total, 2)"))
    _commit(bed.repos["quayside-billing"], "the invoice leaves the freight out")


def test_a_concept_whose_code_moved_is_named_stale_in_the_prompt(bed):
    """The billing concept was published against bytes the billing service no longer has. The
    turn's check finds it against the code mounted for billing — not the manifest, which says
    nothing moved — and the prompt names it, and the flow that cites the same file, as stale."""
    _move_billing(bed)
    harness = _Recording()
    bed.module(agent=harness).answer("is the freight on the invoice?")
    prompt = harness.prompts[0]

    assert "# Where the map is thin (checked against the code mounted for this turn)" in prompt
    assert ("- `quayside-billing` — 'Invoicing a placed order' is STALE: it no longer matches the "
            "code mounted this turn (stale: `billing/invoicing.py` — bytes moved") in prompt
    assert ("- the flow 'An order is invoiced the moment it is placed' is STALE: it no longer "
            "matches the code mounted this turn (stale: `billing/invoicing.py`") in prompt
    # the concepts of the services whose code did not move are not named
    assert "'Placing an order' is STALE" not in prompt
    assert "'The freight calculation' is STALE" not in prompt


def test_a_stale_cited_concept_bounds_the_reading_and_is_named_in_the_answer(bed):
    """Cited, the stale concept is `stale` in the reading, the confidence is no higher than
    `média`, and the answer the person reads names it as out of date."""
    from openfactory.product.reading import MEDIA

    _move_billing(bed)
    harness = _Recording("It invoices the freight too.\n[[USO: Invoicing a placed order; REQ-1]]")
    answer = bed.module(agent=harness).answer("is the freight on the invoice?")

    assert answer.reading.verified["concepts"] == {"Invoicing a placed order": "stale"}
    assert answer.reading.confidence == MEDIA
    assert "no longer matches the code mounted for this turn" in answer.reading.bounded_by
    assert "«Invoicing a placed order»" in answer.text
    assert "no longer matches today's code" in answer.text


def test_a_fresh_cited_concept_carries_no_stale_caveat(bed):
    from openfactory.product.reading import ALTA

    harness = _Recording("It invoices the freight too.\n[[USO: Invoicing a placed order; REQ-1]]")
    answer = bed.module(agent=harness).answer("is the freight on the invoice?")

    assert answer.reading.verified["concepts"] == {"Invoicing a placed order": "fresh"}
    assert answer.reading.confidence == ALTA
    assert "«Invoicing a placed order»" not in answer.text


# ── 3. the gap signal ───────────────────────────────────────────────────────────────────────────

def _reads(*paths: str) -> _Recording:
    return _Recording("An order is cancelled while it is still placed.\n[[EVIDENCIA: "
                      + "; ".join(paths) + "]]")


def test_code_no_concept_covers_raises_exactly_one_no_concept_request(bed):
    """THE ACCEPTANCE: a turn that answered by reading `orders/cancelling.py` — code no concept of
    the orders bundle describes, of a kind nothing excuses — leaves ONE request in the pipeline's
    inbox, in ADR-0046's vocabulary; the second turn that reads it again is the same request,
    counted, never a second one."""
    for _ in range(2):
        bed.module(agent=_reads(f"src/quayside-orders/{UNCOVERED}")).answer(
            "can an order be cancelled after it leaves?")

    [request] = bed.requests()
    assert request["repo"] == "quayside-orders"
    assert (request["gap"]["kind"], request["gap"]["path"]) == ("no-concept", UNCOVERED)
    assert request["times"] == 2 and request["taken"] == ""
    # what it carries: the repository, the path, the fixed sentence — never the question
    assert "cancelled" not in json.dumps(request)


def test_a_reply_that_read_uncovered_code_is_medium_not_low(bed):
    """D21's own sentence: "what I say about it comes from reading the code just now, medium
    confidence" — a reading that cites no concept and stands on code it opened this turn."""
    from openfactory.product.reading import MEDIA

    answer = bed.module(agent=_reads(f"src/quayside-orders/{UNCOVERED}")).answer("cancel?")
    assert answer.reading.confidence == MEDIA
    assert "rests on 1 code file(s) opened this turn" in answer.reading.bounded_by


def test_what_a_concept_or_an_exemption_covers_raises_nothing(bed):
    """Covered code, a declaration its kind excuses, and documentation are read every day and are
    not gaps: the gate's own ladder decides, and only `no-concept` is signalled."""
    bed.module(agent=_reads("src/quayside-orders/orders/placing.py",
                            "src/quayside-orders/api/openapi.yaml",
                            "src/quayside-orders/README.md",
                            "src/quayside-billing/billing/invoicing.py:29")).answer("how?")
    assert bed.requests() == []


def test_a_path_outside_the_products_sources_is_never_judged_or_signalled(bed):
    """The documentation, a path that climbs out of a mount, an absolute path outside the view, and
    a source the product has with no bundle (a backfill owed, not a file to describe) — none of
    them is a request."""
    bed.module(agent=_reads("docs/requirements/0001-an-order-is-invoiced-when-placed.md",
                            f"src/quayside-orders/../quayside-orders/../../{UNCOVERED}",
                            "/etc/hosts",
                            "src/quayside-platform/infra/main.tf")).answer("where?")
    assert bed.requests() == []


def test_a_read_the_harness_stream_reports_is_signalled_too(bed):
    """The reply's evidence is one witness; the harness's own stream is the other. A `Read` the
    stream reports of uncovered code, in the turn's view, is the same request, whatever the reply
    cited. (Relative here: the bed's own temporary path is long enough for the stream reader's
    200-character cap to cut it, and a cut path is not read as a file — the test below.)"""

    class _Streaming(_Recording):
        def ask(self, *, sandbox, workspace, prompt, phase="ask"):
            self.prompts.append(prompt)
            target = f"src/quayside-orders/{UNCOVERED}"
            stream = "\n".join(json.dumps(e) for e in (
                {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "name": "Read", "input": {"file_path": target}}]}},
                {"type": "result", "subtype": "success", "result": "It is cancelled."}))
            return AgentRunResult(ok=True, summary="It is cancelled.", harness="claude_code",
                                  raw_output=stream)

    answer = bed.module(agent=_Streaming()).answer("can an order be cancelled?")
    assert answer.ok and answer.text == "It is cancelled."
    [request] = bed.requests()
    assert request["gap"]["path"] == UNCOVERED


def test_a_path_the_stream_reader_may_have_cut_is_not_read_as_a_file():
    from openfactory.product.module import _opened_in_stream

    def stream(target: str) -> str:
        return json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": target}}]}})

    assert _opened_in_stream("claude_code", stream("src/a/x.py")) == ["src/a/x.py"]
    assert _opened_in_stream("claude_code", stream("/" + "d" * 240 + "/x.py")) == []
    assert _opened_in_stream("unknown-harness", stream("src/a/x.py")) == []
    # a shell command is not a read the stream can vouch for — the reply's evidence names it
    shell = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "src/a/x.py"}}]}})
    assert _opened_in_stream("claude_code", shell) == []


def test_the_role_writes_no_bundle_and_nothing_in_the_context_repository(bed):
    """The signal is a request, and the role's whole write is the inbox: the context repository —
    where every bundle lives — has exactly the commits it had, and its working tree is clean."""
    before = _git(bed.context, "rev-parse", "HEAD")
    bed.module(agent=_reads(f"src/quayside-orders/{UNCOVERED}")).answer("cancel?")
    assert len(bed.requests()) == 1
    assert _git(bed.context, "rev-parse", "HEAD") == before
    assert _git(bed.context, "status", "--porcelain") == ""


def test_the_pipeline_takes_the_request_at_its_own_entry_and_records_it(tmp_path, monkeypatch):
    """THE PIPELINE'S HALF: the knowledge refresh — after a merge, on the schedule — takes what was
    asked about its repository, merges it into the manifest it publishes as a `no-concept` gap, and
    marks it taken; the round after publishes nothing for it."""
    from openfactory.knowledge.okf import OKF_MANIFEST_FILE, parse_manifest
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput
    from tests.test_knowledge_pipeline import (
        _SUBPATH,
        _client_repo,
        _context_repo,
        _patch_activity,
    )
    from tests.test_knowledge_pipeline import _git as git
    from tests.test_the_merge_re_authors_what_it_invalidated import _seed_concepts

    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    remote, work = _client_repo(tmp_path)
    context = _context_repo(tmp_path, with_docs=True)
    acts = _patch_activity(monkeypatch, tmp_path, remote, context)
    inp = KnowledgeRefreshInput(project="p", issue="1")
    assert acts._do_refresh_knowledge(inp) == "published"
    _seed_concepts(context, work, tmp_path)
    acts._do_refresh_knowledge(inp)                      # the inventory joins the seeded bundle
    assert acts._do_refresh_knowledge(inp) == "unchanged"

    project = acts.ProjectRegistry().get("p")
    inbox = asked.inbox_for(project)
    assert asked.request(inbox, repo="owner/repo", path="core/__init__.py", at="2026-09-24T10")
    assert not asked.request(inbox, repo="owner/repo", path="core/__init__.py", at="2026-09-24T11")

    assert acts._do_refresh_knowledge(inp) == "published"
    manifest = parse_manifest(git(context, "show", f"main:{_SUBPATH}/{OKF_MANIFEST_FILE}"))
    gaps = [(g.kind, g.path) for g in manifest.gaps if g.kind == "no-concept"]
    assert gaps == [("no-concept", "core/__init__.py")]
    assert asked.pending(inbox, "owner/repo") == []
    assert acts._do_refresh_knowledge(inp) == "unchanged"


def test_a_request_about_a_file_described_since_is_not_recorded(tmp_path):
    """Asked on Monday, described on Tuesday: the pipeline records nothing for it, and a request
    already in the manifest is the same gap — merged by key, answered stays answered."""
    from openfactory.knowledge.contracts import Concept, ConceptSource, OkfManifest
    from openfactory.knowledge.gaps import record_in_bundle
    from openfactory.knowledge.okf import read_manifest, write_okf

    bundle = tmp_path / "bundle"
    write_okf(bundle, manifest=OkfManifest(), concepts=[
        Concept(type="policy", title="Rules", sources=[ConceptSource(path="core/rules.py")])])
    described, open_ = asked.gap_for("core/rules.py"), asked.gap_for("core/other.py")

    assert record_in_bundle(bundle, [described, open_, open_]) == [open_]
    assert [g.path for g in read_manifest(bundle).gaps] == ["core/other.py"]
    assert record_in_bundle(bundle, [open_]) == []


# ── 4. the chain ────────────────────────────────────────────────────────────────────────────────

def _model(*, job: dict | None, tag: str | None = "req-12", card_state: str = "closed",
           cites: int = 1):
    """A read model of the product holding REQ-0001, the card that executes it and its job."""
    from openfactory.product.model import ProductModel

    member = "quayside-orders"
    card = {"ref": "12", "title": "Invoice the order when it is placed", "state": card_state,
            "state_reason": "completed" if card_state == "closed" else "",
            "body": f"## Objective\n\nInvoice it.\n\n## Source\n\nREQ-{cites:04d} — the promise.\n"}
    return ProductModel(
        key="repo:quayside-context", members=[member],
        now={member: {"jobs": [], "pulls": {}, "loops": []}},
        history={member: {"board": {"cards": [card]},
                          "finished": [job] if job else [],
                          "release": None if tag is None else {"latest_tag": tag}}},
        meaning={member: {"cards": {"12": card}}},
        requirements=[{"number": 1, "title": "An order is invoiced the moment it is placed",
                       "status": "accepted", "superseded_by": None,
                       "affects": ["quayside-orders`, `quayside-billing`, `quayside-freight"],
                       "path": "requirements/0001-an-order-is-invoiced-when-placed.md",
                       "asked_by": "ines"}])


_DONE = {"issue": "12", "state": "done", "status": "closed", "close_time": "2026-09-20T10:00",
         "action": {"pr_url": "https://forge.example/quayside-orders/pull/31"}}


def _chain(model, sight=None):
    from openfactory.product import chain

    return chain.Chain(model=model, sight=sight, declared=list(REPOS))


def test_is_requirement_n_in_production_is_answered_from_the_chain():
    """THE ACCEPTANCE: REQ-0001 → card 12, whose `## Source` cites it → its job, `done` — released
    to production and verified — → the release tag the client-approved release of card 12 is
    tagged with. In production, in `req-12`, and each link said."""
    from openfactory.product.chain import IN_PRODUCTION

    trace = _chain(_model(job=_DONE)).requirement(1)
    assert trace.verdict == IN_PRODUCTION and trace.version == "req-12"
    assert "quayside-orders#12's job ended `done` at 2026-09-20T10:00" in trace.because
    assert [(s.member, s.ref) for s in trace.steps] == [("quayside-orders", "12")]


@pytest.mark.parametrize("job, tag, verdict, version, said", [
    (_DONE, "v1.4.0", "in production", "",
     "the newest release tag of quayside-orders is `v1.4.0` (the tag of this release is not on "
     "record)"),
    ({**_DONE, "state": "merged", "deploy": "deployed"}, "v1.4.0", "in production", "",
     "the deploy watch saw it deployed"),
    ({**_DONE, "state": "merged", "deploy": "deploy_failed"}, "v1.4.0",
     "merged, not seen in production", "", "the deploy watch says deploy_failed"),
    (None, "v1.4.0", "on the board, not built", "", "closed as completed — the board's word, not "
                                                    "a release"),
])
def test_each_verdict_names_the_link_it_rests_on_and_a_version_only_when_recorded(
        job, tag, verdict, version, said):
    trace = _chain(_model(job=job, tag=tag)).requirement(1)
    assert (trace.verdict, trace.version) == (verdict, version)
    assert said in trace.because


def test_a_requirement_no_card_executes_is_said_and_an_unread_model_is_unknown():
    from openfactory.product.chain import NO_CARD, UNREAD

    assert _chain(_model(job=_DONE, cites=7)).requirement(1).verdict == NO_CARD
    assert _chain(None).requirement(1) is None
    text = _chain(None).render()
    assert "The product's read model could not be built for this message" in text
    assert UNREAD == "unknown — the board or the jobs could not be read"


def test_the_turn_writes_the_chain_and_the_prompt_says_to_answer_from_it(bed, monkeypatch):
    """Wired: the facts pack of an answer carries `chain.md`, walked from the read model the turn
    built and the map it mounted — REQ-0001 in production in `req-12`, crossing the three services,
    the code of each — and the prompt says what it answers."""
    model = _model(job=_DONE)
    monkeypatch.setattr("openfactory.product.module._the_read_model",
                        lambda module, root: {"model": model, "speaker": ""})
    harness = _Recording()
    module = bed.module(agent=harness)
    module.answer("is requirement 1 in production?")
    where = Path(module._combined) / module.mounted()["facts"]
    chain = (where / "chain.md").read_text()

    assert "- **in production** —" in chain and "version `req-12`" in chain
    assert ("- crosses `quayside-orders`, `quayside-billing`, `quayside-freight` — components "
            "billing, freight, orders") in chain
    for repo, (rel, _line) in THREE.items():
        assert f"- code: `{repo}` `{rel}:" in chain, repo
    assert not re.search(r"\bines\b", chain), "the chain named a person"
    assert f"`{module.mounted()['facts']}/chain.md`, when the README lists it, is the chain" in \
        harness.prompts[0]


def test_what_code_serves_a_capability_and_what_a_change_touches(bed):
    """The other two questions: the code that serves the flow of REQ-0001 is in all three
    services; a change to the freight calculation touches the freight service and the orders
    service that calls it, and REQ-0001."""
    module = bed.module(agent=_Recording())
    module._workspace()
    serving = _chain(_model(job=_DONE), module.sight()).serving(FLOW)

    assert serving["confirmed"] is False
    assert serving["components"] == ["billing — code in `quayside-billing` `.`",
                                     "freight — code in `quayside-freight` `.`",
                                     "orders — code in `quayside-orders` `.`"]
    assert {c.split("`")[1] for c in serving["code"]} == set(THREE)
    touched = _chain(_model(job=_DONE), module.sight()).touched_by("The freight calculation")
    assert touched["components"] == ["freight"]
    assert touched["called_by"] == ["orders (grpc, env FREIGHT_ADDR)"]
    assert touched["requirements"] == [1]
    billing = _chain(_model(job=_DONE), module.sight()).touched_by("billing")
    assert (billing["called_by"], billing["hears_from"]) == (
        [], ["orders (event, channel order.placed)"])


# ── 5. a capability is curated only once a person confirms it ──────────────────────────────────

def test_an_observed_flow_is_never_curated_truth(bed):
    """Before anybody confirms it, the flow is evidence: the prompt lists it as observed and has no
    confirmed capability at all, and the chain says it is not confirmed."""
    harness = _Recording()
    module = bed.module(agent=harness)
    module.answer("what does checkout cover?")
    prompt = harness.prompts[0]

    assert "**Confirmed by a person of the product**" not in prompt
    assert "**Observed, NOT confirmed by anybody**" in prompt
    assert not (Path(module._combined) / "docs" / "capabilities").exists()


def test_confirmed_with_nobody_beside_it_is_not_a_confirmation(bed):
    """A file that says `confirmed` and records nobody, or no day, is read as observed — a status
    nobody can attribute is not a confirmation — and the finding is logged."""
    from openfactory.product.capabilities import load_capabilities

    folder = bed.context / "capabilities"
    folder.mkdir()
    (folder / "checkout.md").write_text("---\ntitle: Checkout\nstatus: confirmed\n---\n\n# X\n")
    caps, findings = load_capabilities(bed.context)
    assert [(c.slug, c.status, c.curated) for c in caps] == [("checkout", "observed", False)]
    assert [f.code for f in findings] == ["unattributed"]


#: An engineer of the product, in private (#269 slice 3). A capability is a document of the
#: context repository and carries no audience, so it is internal: a client's view holds none,
#: and these pin what the role says of capabilities to whom may read them.
_INSIDE = {"speaker": Person(id="rui", role=ENGINEER), "private": True}


def test_a_capability_somebody_wrote_without_a_confirmation_is_said_as_observed(bed):
    """A person may write a capability by hand; until it is confirmed it is an observation, listed
    as one — never under what the product has confirmed."""
    folder = bed.context / "capabilities"
    folder.mkdir()
    (folder / "checkout.md").write_text(
        "---\ntitle: Checkout\nstatus: observed\ncomponents: [orders, billing]\n---\n\n# X\n")
    _commit(bed.context, "a capability somebody proposed")
    harness = _Recording()
    bed.module(agent=harness).answer("what does checkout cover?", **_INSIDE)
    section = harness.prompts[0].split("# The product's business capabilities")[1].split("\n# ")[0]

    assert "**Confirmed by a person of the product**" not in section
    observed = section.split("**Observed, NOT confirmed by anybody**")[1]
    assert "- Checkout — `docs/capabilities/checkout.md` — components orders, billing" in observed


def test_a_person_who_may_not_act_cannot_confirm_and_nothing_is_written(bed):
    before = _git(bed.context, "rev-parse", "HEAD")
    result = bed.module().confirm_capability(FLOW, actor="somebody-else")
    assert not result.ok
    assert _git(bed.context, "rev-parse", "HEAD") == before


def test_a_person_of_the_product_confirms_and_the_capability_becomes_the_products(bed):
    """The one act: an admin of the product confirms the observed flow; the capability is written
    at the product level with who and when, and the next turn is told it as the product's — never
    naming who confirmed it."""
    from openfactory.product.capabilities import load_capabilities

    result = bed.module().confirm_capability(FLOW, actor="ines")
    assert result.ok, result.detail
    assert result.ref == f"capabilities/{FLOW}.md"
    [cap], findings = load_capabilities(bed.context)
    assert findings == [] and cap.curated
    assert (cap.confirmed_by, cap.requirements, cap.components) == (
        "ines", [1], ["billing", "freight", "orders"])
    assert {c.repo for c in cap.concepts} == set(THREE)

    again = bed.module().confirm_capability(FLOW, actor="ines")
    assert again.ok and again.existed

    harness = _Recording()
    bed.module(agent=harness).answer("what does invoicing cover?", **_INSIDE)
    prompt = harness.prompts[0]
    assert "**Confirmed by a person of the product**" in prompt
    assert (f"- **An order is invoiced the moment it is placed** — "
            f"`docs/capabilities/{FLOW}.md` — REQ-0001") in prompt
    assert "**Observed, NOT confirmed by anybody**" not in prompt, "the confirmed flow twice"
    section = prompt.split("# The product's business capabilities")[1].split("\n# ")[0]
    assert not re.search(r"\bines\b", section), "the prompt named who confirmed it"


def test_a_link_of_a_confirmed_capability_that_no_longer_holds_is_reported(bed, caplog):
    """A curated capability does not follow the code: a concept retitled, a component the map no
    longer derives. Each broken link is said beside it in the prompt and logged — never repaired."""
    import logging

    folder = bed.context / "capabilities"
    folder.mkdir()
    (folder / "checkout.md").write_text(
        "---\ntitle: Checkout\nstatus: confirmed\nconfirmed_by: ines\nconfirmed_at: 2026-09-01\n"
        "components: [orders, payments]\nconcepts:\n- repo: quayside-orders\n  title: Placing an "
        "order\n- repo: quayside-freight\n  title: The tariff table\n---\n\n# Checkout\n")
    _commit(bed.context, "a capability somebody confirmed a while ago")
    harness = _Recording()
    with caplog.at_level(logging.WARNING, logger="openfactory.product"):
        bed.module(agent=harness).answer("what does checkout cover?", **_INSIDE)
    prompt = harness.prompts[0]

    assert ("  - a link that no longer holds: the concept `quayside-freight` — The tariff table no "
            "longer exists") in prompt
    assert ("  - a link that no longer holds: the component `payments` is no longer on the system "
            "map") in prompt
    assert "Placing an order no longer exists" not in prompt
    assert "OPENFACTORY_PRODUCT_CAPABILITY_DANGLING slug=checkout links=2" in caplog.text


@pytest.mark.parametrize("slug", ["../requirements/0001-an-order-is-invoiced-when-placed",
                                  ".okf/flows/flows", "an order", ""])
def test_a_capability_is_named_never_addressed_by_a_path(bed, slug):
    """The slug is typed by a person and names the file the confirmation writes: anything that is
    not a plain name — a path that climbs into the requirements, one into `.okf/` — is refused
    before anything is read or written."""
    from openfactory.product.capabilities import confirm_in_repository

    before = _git(bed.context, "rev-parse", "HEAD")
    result = bed.module().confirm_capability(slug, actor="ines")
    assert not result.ok and result.detail == "esse nome não é o de uma capacidade"
    direct = confirm_in_repository(docs_repo="quayside-context", clone_url="file:///nowhere",
                                   slug=slug, flow=None, confirmed_by="ines")
    assert not direct.ok and direct.detail == "esse nome não é o de uma capacidade"
    assert _git(bed.context, "rev-parse", "HEAD") == before


@pytest.mark.asyncio
async def test_the_catalogue_row_confirms_only_with_a_yes(bed, monkeypatch):
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor

    monkeypatch.setattr(catalog, "_product_module",
                        lambda _n, **_k: (bed.module(), bed.project, None))
    ines = Actor(id="ines", display="Ines", via="panel", admin=True)
    refused = await catalog._product_confirm_capability(project="quayside",
                                                        capability=FLOW, by=ines)
    assert not refused.ok and refused.code == catalog.INVALID
    assert not (bed.context / "capabilities").exists()
    done = await catalog._product_confirm_capability(project="quayside", capability=FLOW,
                                                     by=ines, yes=True)
    assert done.ok, done.message
    assert (bed.context / "capabilities" / f"{FLOW}.md").is_file()


# ── blind spots, said out loud ─────────────────────────────────────────────────────────────────

def test_the_blind_spots_are_said_source_by_source(bed):
    """What the role cannot stand on: the platform service has no bundle; `orders/cancelling.py`
    is code no concept describes; the map could not derive five things. Said in the prompt."""
    harness = _Recording()
    bed.module(agent=harness).answer("how do the services talk?")
    prompt = harness.prompts[0]
    blind = prompt.split("# Where the map is thin")[1].split("\n# ")[0]

    assert ("- `quayside-platform` has no knowledge bundle yet — what you say about it comes from "
            "reading its code now") in blind
    assert "- `quayside-orders`: 2 of its 3 file(s) that need a concept have none " \
           f"(`orders/__init__.py`, `{UNCOVERED}`)" in blind
    assert "- the system map could not derive 5 thing(s) (not-declared 2, not-followed 1, " \
           "not-read 1, unknown-format 1)" in blind
    assert "is STALE:" not in blind


def test_a_source_that_could_not_be_mounted_is_a_blind_spot_and_its_concepts_are_not_checked(
        bed, monkeypatch):
    harness = _Recording()
    manifest = bed.context / ".openfactory" / "product.yaml"
    manifest.write_text(manifest.read_text().replace("quayside-billing",
                                                     "quayside-billing-gone"))
    _commit(bed.context, "a source that is not there")
    module = bed.module(agent=harness)
    module.answer("is the freight on the invoice?")
    blind = harness.prompts[0].split("# Where the map is thin")[1].split("\n# ")[0]

    assert "- `quayside-billing-gone`: its code could not be opened this turn" in blind
    assert module.sight().stale == []


def test_the_blind_spots_are_bounded_and_the_cut_is_counted():
    from openfactory.product.sight import MAX_LINES, _bounded

    shown, cut = _bounded([f"line {i}" for i in range(MAX_LINES + 5)])
    assert len(shown) == MAX_LINES and cut == 5
    shown, cut = _bounded(["x" * 1500, "y" * 1500, "z"])
    assert shown == ["x" * 1500] and cut == 2


# ── the pieces, alone ──────────────────────────────────────────────────────────────────────────

def test_the_check_never_reads_outside_the_tree_it_names(tmp_path):
    """A concept is a file somebody wrote into the context repository; its `path` can climb out, or
    name a link that leads out. Neither is opened: missing from this checkout, said why."""
    from openfactory.knowledge.check import MISSING, check_concepts
    from openfactory.knowledge.contracts import Concept, ConceptSource, OkfManifest
    from openfactory.knowledge.okf import write_okf

    secret = tmp_path / "secret.txt"
    secret.write_text("never read")
    tree = tmp_path / "tree"
    (tree / "pkg").mkdir(parents=True)
    (tree / "pkg" / "link.py").symlink_to(secret)
    bundle = tmp_path / "bundle"
    write_okf(bundle, manifest=OkfManifest(), concepts=[
        Concept(type="policy", title="Climbs", sources=[
            ConceptSource(path="../secret.txt", fingerprint="0" * 64)]),
        Concept(type="policy", title="Links", sources=[
            ConceptSource(path="pkg/link.py", fingerprint="0" * 64)])])

    report = check_concepts(bundle, tree)
    for concept in report.concepts:
        assert concept.verdict == MISSING, concept
        assert concept.sources[0].detail == "outside this checkout — not read", concept


def test_the_flows_are_what_the_pipeline_observes_of_the_fixture(tmp_path):
    """THE FIXTURE IS THE PLATFORM'S OWN OUTPUT: the flows under the context repository are what
    `observe` derives from its requirements, its system map and its bundles — byte for byte."""
    from openfactory.knowledge.flows import observe, write_flows
    from openfactory.product.corpus import load_corpus
    from openfactory.product.sight import bundles_of, read_system
    from openfactory.product.sources import declared

    context = FIXTURE / "context"
    repos = declared(context).repos
    flows, concepts = observe(load_corpus(context / "requirements").requirements, sources=repos,
                              bundles=bundles_of(context, repos), system=read_system(context),
                              generated_at="2026-09-24T00:00:00Z")
    write_flows(flows, concepts, tmp_path / "flows")
    published = context / ".okf" / "flows"
    for path in sorted((tmp_path / "flows").rglob("*")):
        if path.is_file():
            rel = path.relative_to(tmp_path / "flows")
            assert path.read_text() == (published / rel).read_text(), rel
    [flow] = flows.flows
    assert (flow.slug, flow.sources, flow.not_linked) == (FLOW, list(THREE), [])


def test_the_system_refresh_publishes_the_flows_beside_the_map_and_converges(tmp_path,
                                                                           monkeypatch):
    """The pipeline writes the flows, never a role: the refresh that derives the system map
    observes the flows from the published bundles and requirements and publishes them at
    `.okf/flows/`, under the product's semaphore, with a commit of their own — and the round after
    publishes nothing."""
    import yaml

    from openfactory.knowledge.flows import FLOWS_FILE
    from openfactory.knowledge.system import refresh
    from tests.test_the_system_layer_is_published import _commits, _published
    from tests.test_the_system_layer_is_published import product as bed_of

    project, remotes, root, tmp = bed_of.__wrapped__(tmp_path, monkeypatch)
    context = remotes["quayside-context"]
    clone = _published(context, tmp / "strip")
    _git(clone, "rm", "-rq", ".okf/flows")
    _git(clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "no flows yet")
    _git(clone, "push", "-q", "origin", "main")

    assert refresh.refresh_system(project, root=root) == refresh.PUBLISHED
    seen = _published(context, tmp / "seen")
    flows = yaml.safe_load((seen / ".okf" / "flows" / FLOWS_FILE).read_text())
    assert [f["slug"] for f in flows["flows"]] == [FLOW]
    assert (seen / ".okf" / "flows" / FLOW_FILE).is_file()
    assert _commits(context)[0] == f"chore(okf): refresh the flows across sources @ " \
                                   f"{flows['derived_key']}"
    before = _commits(context)
    assert refresh.refresh_system(project, root=root) == refresh.UNCHANGED
    assert _commits(context) == before


def test_the_per_source_concepts_of_the_fixture_are_fresh_against_its_code():
    from openfactory.knowledge.check import FRESH, check_concepts

    for repo in THREE:
        report = check_concepts(FIXTURE / "context" / ".okf" / "repos" / repo,
                                FIXTURE / "sources" / repo)
        assert [c.verdict for c in report.concepts] == [FRESH], repo


def test_a_flow_says_what_it_could_not_link():
    """A source of the flow with no bundle, or with no concept naming another part of it, and no
    system map at all — each said on the flow, never a silent partial flow."""
    from openfactory.knowledge.flows import observe

    req = SimpleNamespace(number=4, title="Shipping", slug="shipping", status="accepted",
                          superseded_by=None, affects=["quayside-orders, quayside-platform"])
    flows, _ = observe([req], sources=list(REPOS),
                       bundles={"quayside-orders": FIXTURE / "context" / ".okf" / "repos" /
                                "quayside-orders", "quayside-platform": None}, system=None)
    [flow] = flows.flows
    assert flow.not_linked == [
        "no concept of `quayside-orders` names another part of this flow",
        "`quayside-platform` has no knowledge bundle published — what it does in this flow is "
        "not described",
        "no system map is published — its components and interfaces are not linked"]


def test_a_flow_concept_names_the_repository_of_every_source_it_cites(tmp_path):
    """A source's own bundle writes its citations without a repository — it is about one — and
    the flow that gathers them names the repository of each, or its check would not know where to
    look."""
    from openfactory.knowledge.contracts import Concept, ConceptSource, OkfManifest
    from openfactory.knowledge.flows import observe
    from openfactory.knowledge.okf import write_okf

    bundles = {}
    for repo, other in (("acme-a", "acme-b"), ("acme-b", "acme-a")):
        bundles[repo] = tmp_path / repo
        write_okf(bundles[repo], manifest=OkfManifest(), concepts=[Concept(
            type="workflow", title=f"{repo} part", depends_on=[other],
            sources=[ConceptSource(path="src/part.py", fingerprint="f" * 64)])])
    req = SimpleNamespace(number=2, title="Across", slug="across", status="accepted",
                          superseded_by=None, affects=["acme-a", "acme-b"])
    _, [concept] = observe([req], sources=["acme-a", "acme-b"], bundles=bundles, system=None)
    assert sorted((s.repo, s.path) for s in concept.sources) == [("acme-a", "src/part.py"),
                                                                 ("acme-b", "src/part.py")]


def test_a_proposed_requirement_is_not_a_flow():
    """A flow is observed from what is built or promised, never from a request nobody agreed to."""
    from openfactory.knowledge.flows import observe

    req = SimpleNamespace(number=9, title="Refunds", slug="refunds", status="proposed",
                          superseded_by=None, affects=["quayside-orders", "quayside-billing"])
    flows, concepts = observe([req], sources=list(REPOS), bundles={}, system=None)
    assert flows.flows == [] and concepts == []


def test_the_turn_is_read_from_the_reply_only_where_it_lies_in_a_mount(tmp_path):
    from openfactory.product.sight import where_read

    root = tmp_path / "view"
    (root / "src" / "a" / "pkg").mkdir(parents=True)
    (root / "src" / "a" / "pkg" / "x.py").write_text("x = 1\n")
    (root / "docs").mkdir()
    (root / "docs" / "y.md").write_text("y\n")
    got = where_read(["src/a/pkg/x.py:3-4", str(root / "src" / "a" / "pkg" / "x.py"),
                      "docs/y.md", "src/a/../../docs/y.md", "/etc/hosts", "src/a/pkg"],
                     root=root, mounts={"acme/a": root / "src" / "a"})
    assert got == [("acme/a", "pkg/x.py")]


def test_a_path_outside_the_view_is_not_even_resolved(tmp_path, monkeypatch):
    """Nothing outside `sources:` is looked at — a link's target included: a path that names a
    place outside the view is dropped before anything asks the filesystem about it."""
    from openfactory.product.sight import where_read

    root = tmp_path / "view"
    (root / "src" / "a").mkdir(parents=True)
    asked_about: list[str] = []
    real = Path.resolve

    def resolve(self, *args, **kwargs):
        asked_about.append(str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    where_read(["/etc/hosts", "src/a/../../../outside.py", "../elsewhere/x.py"], root=root,
               mounts={"acme/a": root / "src" / "a"})
    outside = [p for p in asked_about if not p.startswith(str(root))
               and not str(root).startswith(p)]
    assert outside == [], outside
