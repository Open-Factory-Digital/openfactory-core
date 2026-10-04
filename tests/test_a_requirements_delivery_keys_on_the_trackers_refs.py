"""A requirement's delivery is followed on the tracker's own refs — every Jira key, and a card filed
in another repository of the product (#485).

THE LOOP WAS KEYED ON BARE NUMBERS. `ProductModule._open_delivery` ran `ref_numbers` over the refs
its cards landed under, and `ref_numbers` drops every ref that is not a number. Measured on `main`
(0f9a01f), what it wrote for each shape of refs a requirement's cards came back with:

    landed                              the delivery loop written
    ─────────────────────────────────   ────────────────────────────────────────────────────────
    #12, 3, #3, 12      GitHub          `7` waits on `3,12`
    DAR-1, DAR-2        Jira            none — "delivery not tracked … none of … is a numeric ref"
    #1, acme/web#1      two repos       `7` waits on `1`: the web card is dropped, and the loop
                                        closes when the API's #1 ships, with web's still open
    acme/web#1, acme/web#2              none

So on Jira no requirement's requester was ever told it shipped, and on a product of several
repositories it was said early, or never.

NOW THE LOOP HOLDS THE TRACKER'S REFS (`followup.deliveries_to_open`), in the one spelling every
reader of it compares (`refs.canonical_ref`, `events._deliveries_of`), deduplicated and in board
order — so a GitHub project of one repository writes the same row, byte for byte, as before.

WHAT IS DRIVEN HERE. The breakdown's filer, `file_issues`, over the real tracker of each row against
a fake at its one transport: Jira's `urllib.request.urlopen`, as `test_a_jira_key_is_a_card_ref.py`
does, and GitHub's `gh` (`subprocess.run`). The breakdown is a harness answering two fronts; the
ledger is the deployment's SQLite store. Whether a card was delivered is the board's to say
(`events._delivered_now`), so that one read is stood in for, and the door (`events._tell`) records
what it was handed. Everything between — which loop waits on the card that finished, whether ALL
of its work is delivered, the announcement and the close — is the production path.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess

import pytest

from openfactory.contracts import AgentRunResult
from openfactory.memory import store as loop_store
from openfactory.memory.ledger import ACCEPTANCE, CLOSED, DELIVERY, open_loop, waiting
from openfactory.product import events, followup
from openfactory.product.corpus import Corpus, Requirement
from openfactory.product.speaker import sealed
from tests.test_a_jira_key_is_a_card_ref import BACKLOG, DOING, DONE, KEY, TO_BACKLOG, TODO, _Site

ANA = "ana-requester-77"
ANAS = f"person:{ANA}"
#: the requirement the two fronts come out of
REQ = Requirement(number=7, slug="fecho-do-mes", path="0007-fecho-do-mes.md",
                  title="Fecho do mês", status="accepted")


class _Harness:
    """The breakdown: the same two fronts, whatever it is asked."""

    name = "recording"

    def __init__(self, fronts: list[dict]) -> None:
        self.answer = json.dumps({"issues": fronts})

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        return AgentRunResult(ok=True, summary=self.answer)


def _front(title: str, **extra) -> dict:
    return {"title": title, "objective": f"{title}, para quem fecha o mês",
            "acceptance_criteria": [f"{title} funciona do começo ao fim"], **extra}


def _pen(project, tmp_path, fronts: list[dict]):
    """The product role's real pen over `project`, its own seams to the forge stood in: the board
    it shows the breakdown (empty, and readable) and the checkout it mounts (none)."""
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule

    ctx = ProductContext(link=ProductLink(active=True, docs_repo="acme/acme-docs", kind="ok",
                                          reason="fine"),
                         corpus=Corpus(requirements=[REQ]), docs_path=str(tmp_path / "docs"),
                         docs_commit="c0ebc3c", requirements_dir="requisitos")
    module = ProductModule(project, context=ctx, agent=_Harness(fronts))
    module._read_board = lambda **_k: ([], "")   # noqa: SLF001 — the module's own board seam
    module._workspace = lambda: (None, None)     # noqa: SLF001 — nothing to mount
    return module


def _deliveries(project) -> list:
    return [x for x in waiting(loop_store.read(project.name)) if x.kind == DELIVERY]


@pytest.fixture
def told(monkeypatch) -> list[dict]:
    """What the door was handed, and taken."""
    said: list[dict] = []
    monkeypatch.setattr(events, "_tell", lambda project, **kw: said.append(kw) or True)
    return said


def _the_board_says(monkeypatch, delivered: set[str]) -> None:
    monkeypatch.setattr(events, "_delivered_now", lambda project: set(delivered))


def _finished(project, monkeypatch, card: str, *, delivered: set[str]) -> list:
    """A job ended with `card` done, and the board, read fresh, says `delivered` were delivered."""
    _the_board_says(monkeypatch, delivered)
    return events.card_finished(project, card=card)


def _memory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))


# ── the Jira row ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def jira(monkeypatch, tmp_path):
    """A Jira project as the registry holds one, its site faked at `urlopen`, and its row's real
    tracker and board."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    _memory(monkeypatch, tmp_path)
    site = _Site()
    monkeypatch.setattr("urllib.request.urlopen", site.urlopen)
    options = {"site": "https://acme-team.atlassian.net", "email": "alice@acme.ai",
               "status_map": json.dumps({"todo": TODO, "in_progress": DOING, "done": DONE})}
    project = Project(name="acme", repo_path=str(tmp_path), language="pt-BR",
                      tracker=ProviderRef(kind="jira", repo=KEY, options=options),
                      product=ProductConfig(docs_repo="acme/acme-docs", admins=[ANA],
                                            agent_name="Nina"))
    return project, site, build_tracker(project, token="t"), build_board(project, token="t")


def test_on_jira_the_loop_names_every_card_and_closes_only_when_every_one_is_delivered(
        jira, tmp_path, told, monkeypatch):
    project, site, tracker, board = jira
    module = _pen(project, tmp_path, [_front("Gerar o pacote de fecho"),
                                      _front("Conferir as notas do mês")])

    results = module.file_issues(REQ, actor=ANA, tracker=tracker, board=board,
                                 conversation=ANAS, requester=ANA)

    assert [(r.ok, r.ref) for r in results] == [(True, "DAR-1"), (True, "DAR-2")]
    assert site.moves() == [("DAR-1", TO_BACKLOG), ("DAR-2", TO_BACKLOG)]
    assert site.status == {"DAR-1": BACKLOG, "DAR-2": BACKLOG}
    [loop] = _deliveries(project)
    assert (loop.subject, loop.context["issues"]) == ("7", "DAR-1,DAR-2")
    assert (loop.context["conversation"], loop.context["requester"]) == (ANAS, sealed(ANA))
    # what is said about either card now reaches the person who asked for it
    assert events.requester_conversation(project, "DAR-2") == ANAS

    # HALF OF THE WORK IS NOT THE WORK
    assert _finished(project, monkeypatch, "DAR-1", delivered={"DAR-1"}) == []
    assert told == [] and _deliveries(project) == [loop]

    written = _finished(project, monkeypatch, "DAR-2", delivered={"DAR-1", "DAR-2"})

    assert [t["conversation"] for t in told] == [ANAS]
    assert "requisito 7" in told[0]["text"]
    assert [(x.kind, x.subject, x.state) for x in written if x.kind == DELIVERY] == [
        (DELIVERY, "7", CLOSED)]
    assert [x.kind for x in written if x.kind == ACCEPTANCE] == [ACCEPTANCE]
    assert _deliveries(project) == []


# ── the GitHub row: a product of two repositories ────────────────────────────────────────────────

class _GH:
    """`gh`, answering the two calls the filer makes: no issue of that title yet, and a new issue
    in the repository named — numbered per repository, as GitHub numbers them. And the one read a
    waiting delivery makes of a card in another repository (#492): every card it filed is still
    OPEN, so the loop waits on it for the right reason — never because the read failed, which is
    what an unexpected call raising here used to look like (review of #499)."""

    def __init__(self) -> None:
        self.created: list[tuple[str, str]] = []
        self.viewed: list[tuple[str, str]] = []

    def __call__(self, argv, **_kw):
        args = list(argv)
        repo = args[args.index("--repo") + 1]
        if args[1:3] == ["issue", "list"]:
            return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")
        if args[1:3] == ["issue", "create"]:
            title = args[args.index("--title") + 1]
            self.created.append((repo, title))
            number = sum(1 for where, _ in self.created if where == repo)
            return subprocess.CompletedProcess(
                argv, 0, stdout=f"https://github.com/{repo}/issues/{number}\n", stderr="")
        if args[1:3] == ["issue", "view"]:
            self.viewed.append((repo, args[3]))
            card = {"number": int(args[3]), "title": "", "body": "", "state": "OPEN",
                    "stateReason": None, "labels": [], "assignees": [], "updatedAt": ""}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(card), stderr="")
        raise AssertionError(f"the tracker ran `{' '.join(args)}`, a call this forge never had")


@pytest.fixture
def two_repositories(monkeypatch, tmp_path):
    """A GitHub product of `acme/api` — the tracker's own — and `acme/web`, as its context
    repository's manifest declares it, with `gh` faked."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    _memory(monkeypatch, tmp_path)
    manifest = tmp_path / "docs" / ".openfactory" / "product.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("product: shop\nsources: [acme/api, acme/web]\n")
    gh = _GH()
    monkeypatch.setattr(subprocess, "run", gh)
    project = Project(name="shop", repo_path=str(tmp_path), language="pt-BR",
                      tracker=ProviderRef(kind="github", repo="acme/api"),
                      product=ProductConfig(docs_repo="acme/acme-docs", admins=[ANA],
                                            agent_name="Nina"))
    return project, gh, build_tracker(project, token="t")


def test_on_a_product_of_two_repositories_the_loop_waits_for_the_card_in_the_other_one(
        two_repositories, tmp_path, told, monkeypatch):
    """Both cards are #1 — each in its own repository — which is what made the one the loop kept
    stand for both."""
    project, gh, tracker = two_repositories
    module = _pen(project, tmp_path, [_front("Fechar o mês na API"),
                                      _front("Mostrar o fecho na tela", target_repo="acme/web")])

    results = module.file_issues(REQ, actor=ANA, tracker=tracker, board=None,
                                 conversation=ANAS, requester=ANA)

    assert gh.created == [("acme/api", "Fechar o mês na API"),
                          ("acme/web", "Mostrar o fecho na tela")]
    assert [(r.ok, r.ref) for r in results] == [(True, "#1"), (True, "acme/web#1")]
    [loop] = _deliveries(project)
    assert (loop.subject, loop.context["issues"]) == ("7", "1,acme/web#1")
    assert events.requester_conversation(project, "acme/web#1") == ANAS

    # THE API'S #1 IS NOT THE WEB'S — and the web's #1 was asked, and is still open
    assert _finished(project, monkeypatch, "1", delivered={"1"}) == []
    assert told == [] and _deliveries(project) == [loop]
    assert gh.viewed == [("acme/web", "1")], gh.viewed

    written = _finished(project, monkeypatch, "acme/web#1", delivered={"1", "acme/web#1"})

    assert [t["conversation"] for t in told] == [ANAS]
    assert [(x.subject, x.state) for x in written if x.kind == DELIVERY] == [("7", CLOSED)]
    assert _deliveries(project) == []


def test_a_requirement_whose_cards_all_landed_in_another_repository_is_followed(
        two_repositories, tmp_path):
    project, _gh, tracker = two_repositories
    module = _pen(project, tmp_path, [_front("Mostrar o fecho na tela", target_repo="acme/web"),
                                      _front("Exportar o fecho", target_repo="acme/web")])

    module.file_issues(REQ, actor=ANA, tracker=tracker, board=None)

    assert [(x.subject, x.context["issues"]) for x in _deliveries(project)] == [
        ("7", "acme/web#1,acme/web#2")]


# ── what a GitHub project of one repository writes does not move ────────────────────────────────

def _as_main_wrote_it(requirement: int, landed: list[str], *, ts: str):
    """The row `main` (0f9a01f) wrote: `_open_delivery` keyed it on `ref_numbers(landed)`, and
    `deliveries_to_open` joined those numbers — copied here, so the pin cannot move with the code."""
    from openfactory.contracts.refs import ref_numbers

    return open_loop(DELIVERY, str(requirement), owner=followup.OWNER, ts=ts,
                     context={"issues": ",".join(str(i) for i in ref_numbers(landed)),
                              **followup.delivered_to(ANAS, ANA)})


def test_on_one_repository_the_loop_written_is_byte_for_byte_what_it_was(monkeypatch):
    """THE PIN: the row written now against `main`'s, as JSON — key for key, byte for byte."""
    from types import SimpleNamespace

    from openfactory.product.authoring import WriteResult
    from openfactory.product.module import ProductModule

    rows: list = []
    monkeypatch.setattr(loop_store, "read", lambda project, **_k: list(rows))
    monkeypatch.setattr(loop_store, "write",
                        lambda project, loops, **_k: rows.extend(loops) or len(loops))
    landed = ["#12", "3", "#3", "12"]
    results = [WriteResult(ok=True, ref=r) for r in landed]
    results.insert(2, WriteResult(ok=False, ref="", detail="this front was not filed"))

    ProductModule._open_delivery(SimpleNamespace(project=SimpleNamespace(name="books")),
                                 SimpleNamespace(number=7), results, conversation=ANAS,
                                 requester=ANA)

    [loop] = rows
    before = _as_main_wrote_it(7, landed, ts=loop.ts)
    assert json.dumps(dataclasses.asdict(loop)) == json.dumps(dataclasses.asdict(before))
    assert loop.context["issues"] == "3,12"


@pytest.mark.parametrize(("landed", "issues"), [
    (["#12", "3", "#3", "12"], "3,12"),
    ([500, 501], "500,501"),
    (["DAR-10", "DAR-2", "#DAR-2"], "DAR-2,DAR-10"),
    (["acme/web#1", "#1", " 1 "], "1,acme/web#1"),
    (["", "#", "  "], None),
])
def test_the_loop_holds_the_refs_in_one_spelling_once_each(landed, issues):
    loops = followup.deliveries_to_open({7: landed}, [], ts="T1")
    assert [x.context["issues"] for x in loops] == ([issues] if issues else [])


# ── the readers of the loop ──────────────────────────────────────────────────────────────────────

def test_the_release_question_finds_the_requirement_behind_any_spelling_of_its_card():
    """`requirement_behind` matched the ref as typed — the one reader of the loop that did not
    compare as `events._deliveries_of` does — so `#12` found nothing behind a loop holding `12`."""
    loops = [open_loop(DELIVERY, "7", owner=followup.OWNER, ts="T1",
                       context={"issues": "3,12"}),
             open_loop(DELIVERY, "9", owner=followup.OWNER, ts="T2",
                       context={"issues": "DAR-1,acme/web#1"})]
    assert [followup.requirement_behind(card, loops)
            for card in ("12", "#12", " 3 ", "DAR-1", "acme/web#1", "#acme/web#1", "1", "")] == [
        "7", "7", "7", "9", "9", "9", "", ""]
