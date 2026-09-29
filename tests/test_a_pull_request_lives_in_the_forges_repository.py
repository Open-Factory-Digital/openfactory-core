"""A card's pull request lives in the FORGE's repository, never in the tracker's namespace (#403).

WHAT HAPPENED. A compose deployment, one project registered as `shop` whose forge repository is
`Org.Shop`, on the local board. A card's job opened pull request 1807 in `Org.Shop`; the person
pressed "start a preview"; the record went `offered → starting → failed` with
`repos: {<pr>: "shop"}`, `missing: ["<pr>'s change is in `shop`, and this preview is of `shop`'s own
repository — not included."]` and `why: "this unit has no open pull request"`. The worker's log
said the Azure DevOps adapter had been told the pull request was in `shop`.

THE CAUSE WAS ONE FIELD READ AT THE WRONG LEVEL. `Ticket.repo` is where the TRACKER keeps the card
— the registry name on the local board, the Azure DevOps project on Azure Boards, the key on Jira —
and the offer recorded it as the pull request's repository. The knowledge gate read the same field
to find the bundle it judges against. Only a GitHub tracker makes the two the same, so the suite,
built on GitHub-shaped doubles, never saw it.

THE PROJECT IN EVERY CASE BELOW IS NAMED DIFFERENTLY FROM ITS REPOSITORY, and its tickets say the
board's name, which is the shape every non-GitHub tracker hands the job.
"""

from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace

import pytest

from openfactory import preview
from openfactory.contracts.project import Project, ProviderRef
from openfactory.preview import demand, steps
from openfactory.preview.plan import Layout, Tree

ROOT = pathlib.Path(__file__).resolve().parent.parent
PR = "https://dev.example/org/Proj/_git/Org.Shop/pullrequest/1807"
HEAD = "a" * 40


def _shop(tracker: str = "local") -> Project:
    """Registered as `shop`, pushing to `Org.Shop` — the registry name is not the repository."""
    return Project(name="shop", repo_path="/src/org-shop",
                   tracker=ProviderRef(kind=tracker, repo="shop"),
                   forge=ProviderRef(kind="azure_devops", repo="Org.Shop",
                                     options={"organization": "org", "project": "Proj"}))


def _ticket(ref: str = "#12"):
    """What a tracker that is not GitHub hands the job: `repo` is the BOARD's name."""
    return SimpleNamespace(id=ref, repo="shop", raw="## Objective\n\nx\n")


@pytest.fixture
def sink(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    demand._CACHE.clear()
    yield
    demand._CACHE.clear()


# ── the offer records the forge's repository ────────────────────────────────────────────────────


def test_the_offer_records_the_repository_the_forge_opened_the_pull_request_in(sink):
    made = demand.offer(project=_shop(), manifest=SimpleNamespace(preview=object()),
                        ticket=_ticket(), pr_url=PR, branch="openfactory/12",
                        runtime_kind="compose")
    assert made.repos == {PR: "Org.Shop"}, "the board's name was recorded as a repository"


def test_the_caller_names_the_repository_and_the_ticket_is_never_asked(sink):
    """The job hands its forge's repository in (`JobRunner._change_repo`); a ticket whose `repo`
    says something else — any tracker's container — changes nothing."""
    made = demand.offer(project=_shop(), manifest=SimpleNamespace(preview=object()),
                        ticket=SimpleNamespace(id="#13", repo="SomeBoard", raw=""),
                        pr_url=PR + "3", branch="openfactory/13", runtime_kind="compose",
                        repo="Org.Web")
    assert made.repos == {PR + "3": "Org.Web"}


def test_the_job_offers_its_forges_repository_not_its_tickets(monkeypatch):
    from openfactory.orchestrator.machine import JobRunner

    runner = JobRunner.__new__(JobRunner)
    runner.project = _shop()
    assert runner._change_repo() == "Org.Shop"
    seen: dict = {}

    def offer(**kw):
        seen.update(kw)
        return None

    monkeypatch.setattr("openfactory.preview.demand.offer", offer)
    runner.manifest = SimpleNamespace(base_branch="main")
    runner._emit = lambda *a, **k: None
    runner._offer_preview(_ticket(), PR, "openfactory/12")
    assert seen["repo"] == "Org.Shop"


# ── the start keeps the change ──────────────────────────────────────────────────────────────────


class Forge:
    """Answers about one pull request, and remembers which repository each question named."""

    def __init__(self):
        self.named: list[str] = []

    def pr_for_head(self, head, **_):
        return PR

    def pr_status(self, *, pr, repo: str = ""):
        self.named.append(repo)
        return "open"

    def push_remote(self):
        return "R"


class Runtime:
    def watch(self, cp):
        return None

    def logs(self, cp, log_dir):
        return []

    def down(self, cp, workdir):
        return [cp]


class Store:
    def __init__(self, *seed):
        self.rows = list(seed)

    def record(self, p):
        self.rows.append(p)

    def latest(self, project, token):
        mine = [r for r in self.rows if r.project == project and r.unit == token]
        return mine[-1] if mine else None


@pytest.fixture
def checkout(monkeypatch, tmp_path):
    from openfactory.adapters.preview import compose

    monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    made: dict = {}

    def materialise(unit, project, *, trees, fetch):
        made.update(trees=trees, fetch=fetch)
        tree = Tree(repo="Org.Shop", dir="shop", base_commit="b" * 40, merge_base="b" * 40,
                    branch=trees[0].branch, change_commit=HEAD, pr_url=trees[0].pr_url,
                    diff_paths=("app.py",))
        return Layout(workdir=compose.workdir_for("shop", unit.token), trees={"shop": tree})

    monkeypatch.setattr(compose, "sources_of", lambda project: [
        compose.TreeSource(repo="Org.Shop", dir="shop", source="/src/org-shop")])
    monkeypatch.setattr(compose, "materialise", materialise)
    return made


def _start(store: Store, forge: Forge):
    world = steps.World(record=store.record, latest=store.latest, forge_of=lambda p: forge,
                        clock=lambda: 1_900_000_000.0,
                        product_of=lambda p: SimpleNamespace(available=False, reason="off"))
    return steps.materialise(_shop(), "12", runtime=Runtime(), world=world, started_by="Ana")


def _offered(repos: dict[str, str]) -> preview.Preview:
    return preview.Preview(project="shop", unit="12", cards=("12",), state=preview.OFFERED,
                           pr_urls=(PR,), branches={PR: "openfactory/12"}, repos=repos)


def test_a_start_keeps_the_change_the_job_opened_and_names_its_repository_to_the_forge(
        checkout):
    store, forge = Store(_offered({PR: "Org.Shop"})), Forge()
    layout = _start(store, forge)
    assert isinstance(layout, Layout), store.rows[-1].why
    assert checkout["trees"][0].pr_url == PR, "the unit's one change is in the preview"
    assert forge.named == ["Org.Shop"]
    assert store.rows[-1].state == preview.STARTING and store.rows[-1].missing == ()


def test_a_record_written_before_the_fix_still_starts(checkout):
    """The live record: `repos` says the BOARD's name. Read as what it meant — the project's own
    repository — rather than leaving the card unstartable until its job opens another."""
    closed = PR.replace("1807", "1700")  # an older pull request of the card, no longer offered
    store, forge = Store(_offered({PR: "shop", closed: "shop"})), Forge()
    layout = _start(store, forge)
    assert isinstance(layout, Layout), (store.rows[-1].why, store.rows[-1].missing)
    assert "shop" not in forge.named, "the forge was told the pull request is in the board"
    assert store.rows[-1].repos == {PR: "Org.Shop"}, \
        "the start writes back what it meant, and no board name survives on the record"


def test_a_name_that_is_also_the_forges_repository_is_kept():
    """A project registered under its repository's own name has no board name to drop."""
    same = Project(name="Org.Shop", repo_path="/r", tracker=ProviderRef(kind="local"),
                   forge=ProviderRef(kind="azure_devops", repo="Org.Shop"))
    assert demand.repos_of(same, _offered({PR: "Org.Shop"})) == {PR: "Org.Shop"}
    assert demand.repos_of(_shop(), _offered({PR: "Org.Api"})) == {PR: "Org.Api"}, \
        "another repository of the product is not the board"


# ── the knowledge gate reads the bundle the change's repository published ──────────────────────


def test_the_gate_reads_the_bundle_of_the_forges_repository(monkeypatch):
    from openfactory.knowledge.pipeline import okf_subpath
    from openfactory.orchestrator.machine import JobRunner

    runner = JobRunner.__new__(JobRunner)
    runner.project = _shop().model_copy(update={"product": SimpleNamespace(
        docs_repo="Org.Context")})
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda project, repo, token="": f"https://x/{repo}.git")
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda project: "t")
    runner._card_repo = runner._change_repo()      # what `_knowledge_gate` sets
    _url, subpath = runner._okf_home()
    assert subpath == okf_subpath("Org.Shop") != okf_subpath("shop")


# ── the class ───────────────────────────────────────────────────────────────────────────────────


def _reads_ticket_repo(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "repo" and \
                isinstance(node.value, ast.Name) and node.value.id == "ticket":
            lines.append(node.lineno)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "getattr" and \
                len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and \
                node.args[0].id == "ticket" and isinstance(node.args[1], ast.Constant) and \
                node.args[1].value == "repo":
            lines.append(node.lineno)
    return lines


@pytest.mark.parametrize("package", ["openfactory/preview", "openfactory/orchestrator"])
def test_nothing_that_names_where_a_change_lives_reads_the_tickets_repo(package):
    """`Ticket.repo` is the tracker's; the preview and the job name the forge's (#403)."""
    files = sorted((ROOT / package).rglob("*.py"))
    assert len(files) >= 3, f"{package} shrank under the guard"
    found = {str(p.relative_to(ROOT)): lines for p in files
             if (lines := _reads_ticket_repo(ast.parse(p.read_text())))}
    assert not found, f"the ticket's repo read where a forge repository belongs: {found}"


def test_the_guard_sees_both_spellings():
    assert _reads_ticket_repo(ast.parse('x = getattr(ticket, "repo", "")')) == [1]
    assert _reads_ticket_repo(ast.parse("x = ticket.repo")) == [1]
