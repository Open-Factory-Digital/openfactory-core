"""A product of several repositories is previewed as ONE thing — the requirement a card executes,
every sibling's pull request in its own repository beside the others — and nothing outside the
product ever reaches it (#265 slice 5; ADR-0050 D1, D3, D5, D12; the design's §2.2, §6, §8, S6, S7).

What these tests hold, in the order it protects something:

1. THE BOUNDARY IS `sources:`. A preview never checks out, builds or mounts a repository the
   product's `product.yaml` does not list: not through `preview.compose.repository`, not through
   `dirs:`, not through a `../x` in a compose file, not through a tree somebody put on disk.
2. A CARD OF ANOTHER PRODUCT IS NEVER JOINED. A card that cites REQ-0012 from a repository outside
   `sources:` is left out and SAID — its pull request is never even asked about.
3. NO READ LEAVES ITS TREE. `product.yaml` and the compose files are read inside the checkout, once
   every link is followed.
4. THE UNIT. A card of a requirement is the requirement only when the product can be read; off, it
   is previewed alone and says why.
5. THE LAYOUT. Side by side under short names (`../web` is `web`), `dirs:` for the rest, and a
   product whose `product.yaml` and a source's manifest both declare a shape is refused.
6. S6 AND S7 end to end on real git repositories, the compose CLI's answers RECORDED from the
   pinned plugin (v2.32.4, `tests/fixtures/preview/README.md`): each with one sibling that has no
   pull request and one foreign card.
7. THE WRITERS. What automation lands in the context repository without a person: requirements
   only through the sweep, `domain/` only for a fact, `.okf/` only for the map.
8. FILING. A card of the back end is filed in the back end's repository — within `sources:` only.
9. THE PRODUCT'S DRAFT. `preview propose --product` writes into the context repository, on a pull
   request of its own, byte for byte what S6 then previews.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory import preview
from openfactory.adapters.preview import compose
from openfactory.contracts.product import ProductConfig, ProductDocs, ProductPreview
from openfactory.contracts.project import Project, ProviderRef
from openfactory.preview import product as pv_product
from openfactory.preview import siblings, steps
from openfactory.preview.plan import CardRef, Layout, PreviewPlan, Refused, Unit
from openfactory.product.config import ProductLink
from openfactory.product.loader import ProductContext, parse_docs_manifest
from openfactory.product.triage import Ticket as BoardTicket
from tests.test_a_preview_is_started_on_demand import Runtime, Store
from tests.test_a_preview_is_started_on_demand import sink as sink  # noqa: F401 — the fixture

FIXTURES = Path(__file__).parent / "fixtures" / "preview"
WEB_PR = "https://github.com/acme/web/pull/12"
API_PR = "https://github.com/acme/api/pull/13"
CONTEXT = "acme/shop-context"


def _source(n: int) -> str:
    """A card's body as `issue_body` writes it: the objective, and the Source citing REQ-n."""
    return (f"## Objective\n\nx\n\n## Source\n\nExecutes **REQ-{n:04d}** in `{CONTEXT}` — "
            f"`requirements/{n:04d}.md`.\n")


def _card(number: str, n: int = 12, state: str = "open") -> BoardTicket:
    return BoardTicket(number=number, title=f"card {number}", body=_source(n), state=state)


# ── real repositories ────────────────────────────────────────────────────────────────────────────


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                          cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout


def _repo(at: Path, tree: Path) -> Path:
    shutil.copytree(tree, at)
    for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-qm", "base")):
        _git(at, *args)
    return at


def _branch(repo: Path, branch: str, files: dict[str, str]) -> str:
    """`files` committed on `branch`, cut from `main`; the head's sha."""
    _git(repo, "checkout", "-q", "-b", branch)
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"the change on {branch}")
    sha = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", "main")
    return sha


class Forge:
    """The forge port, at the methods a start of a product's preview uses. Asked about a
    repository that is not the product's, it FAILS THE TEST: a foreign card's pull request is never
    even looked up."""

    def __init__(self, repos: dict[str, Path], prs: dict[tuple[str, str], str],
                 status: dict[str, str] | None = None):
        self.repos, self.prs, self.status = repos, prs, status or {}
        self.asked: list[tuple[str, str]] = []

    def push_remote(self):
        return str(self.repos["acme/web"])

    def clone_url(self, repo, *, token=None):
        return str(self.repos[repo])

    def authenticated_url(self, url):
        return url

    def pr_for_head(self, head, *, repo=""):
        self.asked.append((head, repo))
        if (repo or "acme/web") not in self.repos:
            raise AssertionError(f"the forge was asked about {repo}, which is not the product's")
        return self.prs.get((repo or "acme/web", head), "")

    def pr_status(self, *, pr, repo=""):
        return self.status.get(pr, "open")


def _project(repos: dict[str, Path]) -> Project:
    return Project(name="shop", repo_path=str(repos["acme/web"]),
                   forge=ProviderRef(kind="github", repo="acme/web"),
                   tracker=ProviderRef(kind="github", repo="acme/web"),
                   product=ProductConfig(docs_repo=CONTEXT))


def _ctx(context: Path, *, active: bool = True, reason: str = "") -> ProductContext:
    docs, error = parse_docs_manifest((context / ".openfactory" / "product.yaml").read_text())
    assert docs is not None, error
    return ProductContext(link=ProductLink(active=active, docs_repo=CONTEXT,
                                           kind="ok" if active else "off", reason=reason),
                          docs_path=str(context), docs=docs if active else None)


class Shop:
    """One product — `acme/web`, `acme/api` and the context repository `acme/shop-context` — as
    real repositories under a test directory, from a fixture's trees."""

    def __init__(self, tmp_path: Path, scenario: str, monkeypatch):
        root = Path(os.path.realpath(tmp_path))
        monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(root / "work"))
        monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(root / "logs"))
        trees = FIXTURES / scenario / "trees"
        self.scenario = scenario
        self.repos = {"acme/web": _repo(root / "src" / "web", trees / "web"),
                      "acme/api": _repo(root / "src" / "api", trees / "api"),
                      CONTEXT: _repo(root / "src" / "shop-context", trees / "shop-context")}
        self.project = _project(self.repos)
        self.store = Store()
        self.prs: dict[tuple[str, str], str] = {}
        self.heads: dict[str, str] = {}
        self.tickets: list = []
        self.board_error = ""
        self.ctx = _ctx(self.repos[CONTEXT])
        self.status: dict[str, str] = {}

    def pull_request(self, repo: str, number: str, url: str, files: dict[str, str]) -> None:
        branch = f"openfactory/{number}"
        self.heads[url] = _branch(self.repos[repo], branch, files)
        self.prs[(repo, branch)] = url

    def world(self) -> steps.World:
        self.forge = Forge(self.repos, self.prs, self.status)
        return steps.World(
            record=self.store.record, latest=self.store.latest, forge_of=lambda p: self.forge,
            clock=lambda: 1_900_000_000.0, product_of=lambda p: self.ctx,
            board_of=lambda p: (self.tickets, self.board_error),
            source_of=lambda p, repo, d: compose.TreeSource(repo=repo, dir=d,
                                                            source=str(self.repos[repo])))

    def materialise(self, token: str = "req0012"):
        return steps.materialise(self.project, token, runtime=Runtime(), world=self.world())

    def plan(self, layout: Layout, monkeypatch, token: str = "req0012"):
        """The plan, with the compose CLI's answer RECORDED from the pinned plugin — and the
        argv it was asked with kept, so a test can say which file it read."""
        text = (FIXTURES / self.scenario / "canonical.json").read_text().replace(
            '"/pv/', f'"{layout.workdir}/')
        self.argv: list[list[str]] = []

        def run(argv, **_kw):
            self.argv.append([str(a) for a in argv])
            return subprocess.CompletedProcess(argv, 0, text, "")

        monkeypatch.setattr(compose, "_as_run", run)
        unit = Unit(project="shop", kind="requirement" if token.startswith("req") else "card",
                    id=token, token=token)
        return compose.plan(layout, unit, self.project, others=[], now=1_900_000_000)

    @property
    def record(self) -> preview.Preview:
        return self.store.rows[-1]


@pytest.fixture
def shop(tmp_path, monkeypatch):
    return lambda scenario="s6": Shop(tmp_path, scenario, monkeypatch)


def _ok(result):
    assert not isinstance(result, Refused), getattr(result, "reasons", result)
    return result


def _context(svc: dict) -> str:
    build = svc.get("build") or {}
    return build.get("context", "") if isinstance(build, dict) else str(build)


# ── 4. the unit: the requirement a card executes, when the product can be read ─────────────────


ON = SimpleNamespace(available=True, reason="")
OFF = SimpleNamespace(available=False,
                      reason="the product module is not enabled for this project (no `product:` "
                             "section in its registry entry)")


def test_a_card_of_a_requirement_is_the_requirement_only_while_the_product_can_be_read():
    from openfactory.preview.unit import unit_of

    card = CardRef(ref="#12", repo="acme/web")
    on = unit_of("shop", card, _source(12), ctx=ON)
    assert (on.kind, on.token, on.alone) == ("requirement", "req0012", "")

    off = unit_of("shop", card, _source(12), ctx=OFF)
    assert (off.kind, off.token) == ("card", "12"), "a third of REQ-0012 previewed as all of it"
    assert off.alone == ("previewed as one card: the product module is off — the product module "
                         "is not enabled for this project (no `product:` section in its registry "
                         "entry)")
    unread = unit_of("shop", card, _source(12), ctx=None)
    assert unread.kind == "card" and "could not be read" in unread.alone

    plain = unit_of("shop", card, "## Objective\n\nno citation\n", ctx=OFF)
    assert (plain.kind, plain.alone) == ("card", ""), "a card that cites nothing is not downgraded"


def test_the_offer_asks_the_product_only_of_a_card_that_cites_and_writes_why_it_is_alone(sink):
    from openfactory.preview import demand

    asked: list = []
    ticket = SimpleNamespace(id="#12", repo="acme/web", raw=_source(12))
    made = demand.offer(project=SimpleNamespace(name="shop"),
                        manifest=SimpleNamespace(preview=object()), ticket=ticket,
                        pr_url=WEB_PR, branch="openfactory/12", runtime_kind="compose",
                        product=lambda p: asked.append(p) or OFF)
    assert asked, "a card citing a requirement was offered without asking whether the product reads"
    assert (made.unit, made.kind) == ("12", "card")
    assert made.alone.startswith("previewed as one card: the product module is off — ")
    assert made.missing == (made.alone,), "the card says why, from the offer on"
    assert made.repos == {WEB_PR: "acme/web"}, "the pull request's repository is recorded"

    asked.clear()
    plain = SimpleNamespace(id="#15", repo="acme/web", raw="## Objective\n\nx\n")
    demand.offer(project=SimpleNamespace(name="shop"), manifest=SimpleNamespace(preview=object()),
                 ticket=plain, pr_url=WEB_PR + "5", branch="openfactory/15",
                 runtime_kind="compose", product=lambda p: asked.append(p) or ON)
    assert asked == [], "the product was checked out for a card that cites nothing"

    joined = demand.offer(project=SimpleNamespace(name="shop"),
                          manifest=SimpleNamespace(preview=object()), ticket=ticket,
                          pr_url=WEB_PR, branch="openfactory/12", runtime_kind="compose",
                          product=lambda p: ON)
    assert (joined.unit, joined.kind, joined.alone) == ("req0012", "requirement", "")


def test_a_start_says_again_why_a_card_is_alone(shop):
    s = shop()
    s.pull_request("acme/web", "12", WEB_PR, {"src/index.js": "// total\n"})
    alone = "previewed as one card: the product module is off — it is not enabled"
    s.store = Store(preview.Preview(project="shop", unit="12", cards=("12",),
                                    state=preview.OFFERED, pr_urls=(WEB_PR,),
                                    branches={WEB_PR: "openfactory/12"}, alone=alone,
                                    missing=(alone,)))
    s.ctx = _ctx(s.repos[CONTEXT], active=False, reason="it is not enabled")
    _ok(s.materialise("12"))
    assert s.store.rows[1].missing == (alone,), "a fresh start forgot why the card is alone"
    assert s.record.missing[0] == alone


# ── 4b. the citation: defects are cards of their requirement too ────────────────────────────────


def _requirement(number: int, status: str = "accepted", superseded_by: int | None = None):
    from openfactory.product.corpus import Requirement

    return Requirement(number=number, slug="total", path=f"{number:04d}-total.md",
                       title="Total", status=status, superseded_by=superseded_by)


def test_a_defect_cites_the_promise_it_breaks_and_is_still_a_defect():
    from openfactory.product.authoring import defect_body, filed_by_the_product_role
    from openfactory.product.module import _cited_requirement

    body = defect_body(restated="the total is wrong", reported_by="ana", severity="",
                       source="", requirement=_requirement(12),
                       requirement_path="requirements/0012-total.md", docs_repo=CONTEXT,
                       commit="c" * 40)
    assert "## Source\n\nRestores **REQ-0012** in `acme/shop-context` — " \
           "`requirements/0012-total.md` @ `cccccccccccc`." in body
    assert _cited_requirement(body) == 12
    assert filed_by_the_product_role(body) == "defect", "the Source made a defect a requirement card"

    before = body.split("\n## Source")[0]
    assert _cited_requirement(before) == 12, "a defect filed before its Source is not a sibling"
    assert _cited_requirement("## O que está acontecendo\n\nsee REQ-0012\n") is None
    assert _cited_requirement("## A promessa violada\n\nnenhuma\n") is None
    uncited = defect_body(restated="x", reported_by="ana", severity="", source="",
                          requirement=None, requirement_path="", docs_repo=CONTEXT)
    assert "## Source" not in uncited and _cited_requirement(uncited) is None


def test_the_orphan_repair_still_leaves_a_defect_exactly_as_it_was(monkeypatch):
    """Reading a defect's citation must not hand it to the repair, which writes a REQUIREMENT
    card's Source over what it rewrites."""
    from openfactory.product.authoring import defect_body
    from openfactory.product.corpus import Corpus
    from openfactory.product.module import ProductModule

    corpus = Corpus(requirements=[_requirement(4, "superseded", superseded_by=6),
                                  _requirement(6)])
    ctx = ProductContext(link=ProductLink(active=True, docs_repo=CONTEXT, kind="ok"),
                         corpus=corpus)
    defect = defect_body(restated="x", reported_by="ana", severity="", source="",
                         requirement=_requirement(4), requirement_path="requirements/0004.md",
                         docs_repo=CONTEXT)
    card = _source(4)
    mod = ProductModule(SimpleNamespace(name="shop"), context=ctx)
    monkeypatch.setattr(mod, "_read_board", lambda **kw: ([
        BoardTicket(number="7", body=defect), BoardTicket(number="8", body=card)], ""))
    assert [n for n, _, _ in mod.orphaned_cards()] == ["8"]


# ── 1–2. the siblings: the board's cards of the requirement, bounded by `sources:` ─────────────


SOURCES = ["acme/api", "acme/web"]


def test_the_siblings_are_the_open_cards_citing_the_requirement_in_the_products_repositories():
    tickets = [_card("12"), _card("acme/api#13"), _card("acme/tools#4"), _card("acme/api#14", 99),
               _card("acme/api#9", state="closed"), _card("acme/web#12"),
               BoardTicket(number="30", body="## Objective\n\nThis is REQ-0012 again.\n")]
    found, missing = siblings.cards_citing(12, tickets, sources=SOURCES, default_repo="acme/web")
    assert found == [("acme/web", "12"), ("acme/api", "13")]
    assert missing == ["acme/tools#4 cites REQ-0012 but is not a repository of this product — "
                       "not included."]


def test_a_repository_is_a_member_by_the_modules_own_match_never_by_a_suffix():
    assert pv_product.member("ACME/Web", SOURCES) == "acme/web"
    assert pv_product.member("evil/web", SOURCES) == "", "an owner is part of the repository"
    assert pv_product.member("web", SOURCES) == "acme/web", "a bare name on one side matches"
    found, missing = siblings.cards_citing(12, [_card("evil/web#3")], sources=SOURCES,
                                           default_repo="acme/web")
    assert found == [] and "evil/web#3" in missing[0]


class _Siblings:
    """A forge that knows which branch of which repository has which pull request."""

    def __init__(self, prs=None, status=None, unreadable=()):
        self.prs, self.status, self.unreadable = prs or {}, status or {}, set(unreadable)
        self.asked: list[tuple[str, str]] = []

    def pr_for_head(self, head, *, repo=""):
        self.asked.append((head, repo))
        if repo in self.unreadable:
            raise RuntimeError("rate limited")
        return self.prs.get((repo, head), "")

    def pr_status(self, *, pr, repo=""):
        return self.status.get(pr, "open")


def test_a_siblings_pull_request_is_the_platforms_on_its_job_branch_in_its_own_repository():
    forge = _Siblings(prs={("acme/web", "openfactory/12"): WEB_PR,
                           ("acme/api", "openfactory/13"): API_PR})
    got = siblings.of_requirement(12, [_card("12"), _card("acme/api#13"), _card("acme/tools#4")],
                                  sources=SOURCES, default_repo="acme/web", forge=forge)
    assert [(c.repo, c.url, c.branch) for c in got.open] == [
        ("acme/web", WEB_PR, "openfactory/12"), ("acme/api", API_PR, "openfactory/13")]
    assert forge.asked == [("openfactory/12", "acme/web"), ("openfactory/13", "acme/api")], \
        "a foreign card's pull request was looked up, or a sibling's on the wrong repository"
    assert got.missing == ("acme/tools#4 cites REQ-0012 but is not a repository of this product "
                           "— not included.",)


@pytest.mark.parametrize("forge,said", [
    (_Siblings(), "`acme/api` runs its current version — api#13 has no pull request yet."),
    (_Siblings(prs={("acme/api", "openfactory/13"): API_PR}, status={API_PR: "merged"}),
     "`acme/api` runs its current version — api#13's pull request is merged."),
    (_Siblings(unreadable={"acme/api"}),
     "whether api#13 has a pull request could not be read — `acme/api` runs its current version "
     "in this preview."),
])
def test_a_sibling_with_no_open_pull_request_is_its_repositorys_current_version_and_said(forge,
                                                                                      said):
    got = siblings.of_requirement(12, [_card("acme/api#13")], sources=SOURCES,
                                  default_repo="acme/web", forge=forge)
    assert got.open == () and got.missing == (said,)


# ── 5. `product.yaml`'s `preview:`, typed, and read inside its tree ─────────────────────────────


BLOCK = {"compose": {"repository": "acme/web", "paths": ["docker-compose.yml"]},
         "expose": {"web": 3000}}


def test_the_block_is_typed_and_strict_and_the_file_around_it_stays_lenient():
    docs = ProductDocs(product="shop", sources=SOURCES, preview=BLOCK, somebody_elses_key=1)
    assert isinstance(docs.preview, ProductPreview)
    assert docs.preview.compose.repository == "acme/web"
    assert ProductDocs(product="shop").preview is None, "a file written before the block loads"
    short = ProductPreview(compose=".openfactory/preview.compose.yml", expose={"web": 3000})
    assert (short.compose.repository, short.compose.paths) == (
        "", [".openfactory/preview.compose.yml"])


@pytest.mark.parametrize("block,said", [
    ({**BLOCK, "expse": {"web": 3000}}, "invalid at `preview.expse`"),
    ({**BLOCK, "compose": {"paths": ["../../etc/compose.yml"]}},
     "invalid at `preview.compose.paths`"),
    ({**BLOCK, "compose": {"paths": ["/abs.yml"]}}, "invalid at `preview.compose.paths`"),
    ({**BLOCK, "dirs": {"a/b": "acme/web"}}, "invalid at `preview.dirs`"),
    ({**BLOCK, "expose": {"web": 70000}}, "preview.expose ports must be 1–65535"),
    ({**BLOCK, "exclude": ["web"]}, "preview.expose and preview.exclude both name ['web']"),
])
def test_a_bad_block_never_turns_the_product_module_off_and_the_preview_says_why(block, said):
    from openfactory.product.config import resolve_product_link

    docs = ProductDocs(product="shop", sources=SOURCES, preview=block)
    assert docs.preview is None
    assert docs.preview_error.startswith("`preview:` in `.openfactory/product.yaml` is invalid")
    assert said in docs.preview_error
    project = Project(name="shop", repo_path="/r",
                      forge=ProviderRef(kind="github", repo="acme/web"),
                      product=ProductConfig(docs_repo=CONTEXT))
    assert resolve_product_link(project=project, docs=docs).active, \
        "a typo in the preview block took the requirements, the board and the conversation down"
    refused = pv_product.shape_of(docs, context=CONTEXT)
    assert isinstance(refused, Refused) and refused.reasons[0].startswith(docs.preview_error)


def test_product_yaml_is_read_inside_its_checkout_and_never_through_a_link_out(tmp_path):
    root = Path(os.path.realpath(tmp_path))
    secret = root / "elsewhere.yaml"
    secret.write_text(f"product: shop\nsources: [acme/web]\npreview: {json.dumps(BLOCK)}\n")
    tree = root / "context"
    (tree / ".openfactory").mkdir(parents=True)
    (tree / ".openfactory" / "product.yaml").symlink_to(secret)
    docs, error = pv_product.read_docs(str(tree))
    assert docs is None and "is not a file of the context repository's base branch" in error

    (tree / ".openfactory" / "product.yaml").unlink()
    shutil.copy(secret, tree / ".openfactory" / "product.yaml")
    docs, error = pv_product.read_docs(str(tree))
    assert docs is not None and docs.preview.compose.repository == "acme/web"


# ── 1. the shape, bounded by `sources:` ─────────────────────────────────────────────────────────


def _docs(**preview) -> ProductDocs:
    return ProductDocs(product="shop", sources=SOURCES, preview={**BLOCK, **preview})


def test_every_member_is_a_source_or_the_context_repository_under_its_short_name():
    shape = pv_product.shape_of(_docs(), context=CONTEXT)
    assert shape.members == {"shop-context": CONTEXT, "api": "acme/api", "web": "acme/web"}
    assert (shape.shape_dir, shape.context_dir) == ("web", "shop-context")
    renamed = pv_product.shape_of(_docs(dirs={"backend": "acme/api"}), context=CONTEXT)
    assert renamed.members == {"shop-context": CONTEXT, "backend": "acme/api", "web": "acme/web"}
    assert renamed.dir_of("acme/api") == "backend" and renamed.dir_of("acme/tools") == ""


@pytest.mark.parametrize("preview_,said", [
    ({"compose": {"repository": "acme/tools", "paths": ["compose.yaml"]}},
     "`preview.compose.repository` in `.openfactory/product.yaml` names `acme/tools`, which is "
     "not a repository of this product (`acme/api`, `acme/web`)"),
    ({"dirs": {"backend": "acme/tools"}},
     "`preview.dirs` in `.openfactory/product.yaml` maps `backend` to `acme/tools`, which is not "
     "a repository of this product"),
    ({"dirs": {"a": "acme/api", "b": "acme/api"}}, "gives `acme/api` two directory names"),
])
def test_a_shape_that_names_a_repository_outside_sources_is_refused_by_name(preview_, said):
    refused = pv_product.shape_of(_docs(**preview_), context=CONTEXT)
    assert isinstance(refused, Refused) and said in " ".join(refused.reasons)


def test_two_sources_sharing_a_short_name_are_refused_until_one_is_named():
    docs = ProductDocs(product="shop", sources=["acme/web", "other/web"], preview=BLOCK)
    refused = pv_product.shape_of(docs, context=CONTEXT)
    assert isinstance(refused, Refused)
    assert "`acme/web` and `other/web` would both be checked out as `web`" in refused.reasons[0]
    docs = ProductDocs(product="shop", sources=["acme/web", "other/web"],
                       preview={**BLOCK, "dirs": {"theirs": "other/web"}})
    assert pv_product.shape_of(docs, context=CONTEXT).members["theirs"] == "other/web"


# ── 6. S6 and S7, end to end on real repositories ───────────────────────────────────────────────

FOREIGN = "acme/tools#4 cites REQ-0012 but is not a repository of this product — not included."


def _board(s: Shop) -> None:
    """The product's board for REQ-0012: its two cards, a card of ANOTHER product citing it, a
    card of another requirement and a closed one — only the first two may be in the preview."""
    s.tickets = [_card("12"), _card("acme/api#13"), _card("acme/tools#4"),
                 _card("acme/api#14", n=99), _card("acme/api#9", state="closed")]


def test_s6_a_requirement_is_previewed_side_by_side_from_the_context_repositorys_shape(
        shop, monkeypatch):
    """The front end's card has its pull request; the back end's has none yet; a card of another
    product cites the same requirement. The preview holds the front end's change, the back end's
    current version — and nothing of the other product, not even a question to the forge."""
    s = shop("s6")
    s.pull_request("acme/web", "12", WEB_PR, {"src/index.js": "// the order's total\n"})
    _board(s)

    layout = _ok(s.materialise())

    assert set(layout.trees) == {"shop-context", "web", "api"} and layout.context == "shop-context"
    web, api = layout.trees["web"], layout.trees["api"]
    assert (web.repo, web.pr_url, web.change_commit) == ("acme/web", WEB_PR, s.heads[WEB_PR])
    assert web.diff_paths == ("src/index.js",), "the change's own diff, merge base to head"
    assert api.repo == "acme/api" and not api.has_change
    assert os.path.isdir(layout.root("web", "change"))
    assert not os.path.exists(layout.root("api", "change")), "a change tree with no pull request"
    assert s.record.missing == (
        FOREIGN, "`acme/api` runs its current version — api#13 has no pull request yet.")
    assert all(repo in ("acme/web", "acme/api") for _, repo in s.forge.asked), \
        "the forge was asked about a repository outside the product"
    assert (s.record.pr_urls, s.record.repos) == ((WEB_PR,), {WEB_PR: "acme/web"})

    plan = _ok(s.plan(layout, monkeypatch))
    assert isinstance(plan, PreviewPlan)
    assert plan.from_change == {"web": True, "api": False, "db": False}
    services = plan.doc["services"]
    assert _context(services["web"]) == layout.root("web", "change")
    assert _context(services["api"]) == layout.root("api", "base")
    assert "build" not in services["db"] and services["db"]["pull_policy"] == "always"
    assert plan.commits["acme/web"] == s.heads[WEB_PR]
    assert plan.commits["acme/api"] == api.base_commit
    first = s.argv[0][s.argv[0].index("-f") + 1]
    assert first == layout.root("shop-context", "base") + "/.openfactory/preview.compose.yml", \
        "the product's compose file is read from the context repository's BASE"
    assert plan.expose == {"api": 8000, "web": 3000} and plan.pr_urls == (WEB_PR,)


def test_s7_the_compose_file_a_source_already_has_is_the_products_shape(shop, monkeypatch):
    """`product.yaml` points at the compose file `acme/web`'s developers run (`build: ../api`);
    `../api` IS the `api` repository because the layout checks them out side by side. Here the
    back end has the pull request and the front end has none."""
    s = shop("s7")
    s.pull_request("acme/api", "13", API_PR, {"app/main.py": "# the order's total\n"})
    _board(s)

    layout = _ok(s.materialise())

    assert set(layout.trees) == {"shop-context", "web", "api"}
    assert layout.trees["api"].has_change and not layout.trees["web"].has_change
    assert s.record.missing == (
        FOREIGN, "`acme/web` runs its current version — web#12 has no pull request yet.")

    plan = _ok(s.plan(layout, monkeypatch))
    assert plan.from_change == {"web": False, "api": True, "db": False}
    services = plan.doc["services"]
    assert _context(services["api"]) == layout.root("api", "change")
    assert _context(services["web"]) == layout.root("web", "base")
    assert s.argv[0][s.argv[0].index("-f") + 1] == layout.root("web", "base") + \
        "/docker-compose.yml"
    assert any("`ports:`" in n for n in plan.notes), "the dev file's ports are dropped and said"


def test_a_two_repository_unit_builds_each_changed_service_from_its_own_change_tree(
        shop, monkeypatch):
    """Both cards have their pull request: each service built from THE CHANGE TREE OF ITS OWN
    REPOSITORY, and what neither changed from base."""
    s = shop("s6")
    s.pull_request("acme/web", "12", WEB_PR, {"src/index.js": "// the order's total\n"})
    s.pull_request("acme/api", "13", API_PR, {"app/main.py": "# the order's total\n"})
    _board(s)

    layout = _ok(s.materialise())
    assert layout.trees["web"].has_change and layout.trees["api"].has_change
    assert s.record.missing == (FOREIGN,)
    plan = _ok(s.plan(layout, monkeypatch))

    assert plan.from_change == {"web": True, "api": True, "db": False}
    services = plan.doc["services"]
    assert _context(services["web"]) == layout.root("web", "change")
    assert _context(services["api"]) == layout.root("api", "change")
    assert "image" not in services["web"] and "image" not in services["api"]
    assert services["db"]["image"] == "postgres:16" and services["db"]["pull_policy"] == "always"
    assert plan.commits == {"acme/web": s.heads[WEB_PR], "acme/api": s.heads[API_PR],
                            CONTEXT: layout.trees["shop-context"].base_commit}
    assert set(plan.pr_urls) == {WEB_PR, API_PR}
    assert {t.tree: t.side for tps in plan.paths.values() for t in tps} == {
        "web": "change", "api": "change"}


def test_a_path_into_a_repository_outside_sources_is_refused_by_name_before_it_is_cloned(
        shop, monkeypatch):
    s = shop("s7")
    web = s.repos["acme/web"]
    text = (web / "docker-compose.yml").read_text().replace("build: ../api", "build: ../frontend")
    (web / "docker-compose.yml").write_text(text)
    _git(web, "commit", "-qam", "api now lives in a directory nobody declared")
    s.pull_request("acme/web", "12", WEB_PR, {"src/index.js": "// total\n"})
    s.tickets = [_card("12")]
    sourced: list[str] = []
    world = s.world()
    world.source = lambda p, repo, d: sourced.append(repo) or compose.TreeSource(
        repo=repo, dir=d, source=str(s.repos[repo]))

    refused = steps.materialise(s.project, "req0012", runtime=Runtime(), world=world)

    assert isinstance(refused, Refused)
    assert refused.reasons[0] == (
        "`api` in `docker-compose.yml` builds from `../frontend`, and `frontend` is not a "
        "repository of this product (api, shop-context, web) — rename it, or declare "
        "`dirs: {frontend: <owner/name>}` in `.openfactory/product.yaml`.")
    assert s.record.state == preview.FAILED and s.record.why == refused.reasons[0]
    assert "frontend" not in " ".join(sourced) and sourced == [], "a stranger was cloned"
    assert not os.path.exists(compose.workdir_for("shop", "req0012")), "the checkout was kept"


def test_a_directory_named_in_dirs_is_that_repository_and_only_that(shop):
    s = shop("s7")
    web, context = s.repos["acme/web"], s.repos[CONTEXT]
    text = (web / "docker-compose.yml").read_text().replace("build: ../api", "build: ../backend")
    (web / "docker-compose.yml").write_text(text)
    _git(web, "commit", "-qam", "the back end is checked out as backend")
    yaml_ = (context / ".openfactory" / "product.yaml").read_text().replace(
        "  expose:\n", "  dirs:\n    backend: acme/api\n  expose:\n")
    (context / ".openfactory" / "product.yaml").write_text(yaml_)
    _git(context, "commit", "-qam", "dirs")
    s.ctx = _ctx(context)
    s.pull_request("acme/api", "13", API_PR, {"app/main.py": "# total\n"})
    s.tickets = [_card("acme/api#13")]

    layout = _ok(s.materialise())

    assert set(layout.trees) == {"shop-context", "web", "backend"}
    assert layout.trees["backend"].repo == "acme/api" and layout.trees["backend"].has_change


def test_a_product_whose_source_also_declares_a_shape_is_refused_naming_both(shop, monkeypatch):
    s = shop("s6")
    api = s.repos["acme/api"]
    manifest = api / ".openfactory" / "project.yaml"
    manifest.write_text(manifest.read_text() + "preview:\n  compose: [compose.yaml]\n"
                                                "  expose: {api: 8000}\n")
    _git(api, "commit", "-qam", "a shape of its own")
    s.pull_request("acme/web", "12", WEB_PR, {"src/index.js": "// total\n"})
    s.tickets = [_card("12"), _card("acme/api#13")]

    refused = s.plan(_ok(s.materialise()), monkeypatch)

    assert isinstance(refused, Refused)
    assert refused.reasons[0].startswith(
        "two shapes: `.openfactory/product.yaml` and `acme/api`'s manifest both declare "
        "`preview:` — keep one.")
    assert s.argv == [], "a shape was read while two were declared"


def test_the_plan_judges_every_tree_on_disk_against_the_membership_it_reads(shop, monkeypatch):
    """Whatever put a tree in the layout, the plan re-reads `product.yaml` from the context
    repository's base and refuses a tree that is not the member its directory names."""
    s = shop("s6")
    s.pull_request("acme/web", "12", WEB_PR, {"src/index.js": "// total\n"})
    s.tickets = [_card("12")]
    layout = _ok(s.materialise())
    planted = layout.model_copy(update={"trees": {
        **layout.trees, "api": layout.trees["api"].model_copy(update={"repo": "acme/tools"})}})

    refused = s.plan(planted, monkeypatch)

    assert isinstance(refused, Refused) and s.argv == []
    assert "`acme/tools` is checked out as `api`, which is not a repository of this product" in \
        refused.reasons[0]


def test_the_products_shape_is_read_from_the_layouts_own_base_and_never_the_cache(shop,
                                                                                 monkeypatch):
    """The module's checkout of the context repository says one thing; the unit's fresh base says
    another. The plan reads the base in the layout — and refuses when it declares no shape."""
    s = shop("s6")
    s.pull_request("acme/web", "12", WEB_PR, {"src/index.js": "// total\n"})
    s.tickets = [_card("12")]
    layout = _ok(s.materialise())
    base = Path(layout.root("shop-context", "base")) / ".openfactory" / "product.yaml"
    base.write_text("product: shop\nsources: [acme/api, acme/web]\n")

    refused = s.plan(layout, monkeypatch)

    assert isinstance(refused, Refused)
    assert "declares no `preview:`" in refused.reasons[0]


@pytest.mark.parametrize("board_error,ctx_off,said", [
    ("rate limited", False, "the board could not be read (rate limited): REQ-0012 is previewed "
                            "with the cards that reached their pull request here, and any other "
                            "card of it is not in this preview."),
    ("", True, "the product module is off — it went off: REQ-0012 is previewed with the cards "
               "that reached their pull request here, and any other card of it is not in this "
               "preview."),
])
def test_a_requirement_whose_board_or_product_cannot_be_read_is_previewed_with_what_offered_and_said(
        shop, board_error, ctx_off, said):
    s = shop("s6")
    s.pull_request("acme/web", "12", WEB_PR, {"src/index.js": "// total\n"})
    s.tickets = [_card("acme/api#13")]
    s.board_error = board_error
    if ctx_off:
        s.ctx = _ctx(s.repos[CONTEXT], active=False, reason="it went off")
    s.store = Store(preview.Preview(project="shop", unit="req0012", kind="requirement",
                                    cards=("12",), state=preview.OFFERED, pr_urls=(WEB_PR,),
                                    branches={WEB_PR: "openfactory/12"},
                                    repos={WEB_PR: "acme/web"}))

    layout = _ok(s.materialise())

    assert said in s.record.missing
    assert layout.trees and all(t.repo in ("acme/web", CONTEXT, "acme/api")
                                for t in layout.trees.values())
    assert ("openfactory/13", "acme/api") not in s.forge.asked, "the unread board was guessed at"


def test_with_the_product_module_off_a_change_in_another_repository_is_left_out_and_said(shop):
    s = shop("s6")
    s.pull_request("acme/web", "12", WEB_PR, {"src/index.js": "// total\n"})
    s.pull_request("acme/api", "13", API_PR, {"app/main.py": "# total\n"})
    s.ctx = _ctx(s.repos[CONTEXT], active=False, reason="off")
    s.store = Store(preview.Preview(
        project="shop", unit="req0012", kind="requirement", cards=("12", "13"),
        state=preview.OFFERED, pr_urls=(WEB_PR, API_PR),
        branches={WEB_PR: "openfactory/12", API_PR: "openfactory/13"},
        repos={WEB_PR: "acme/web", API_PR: "acme/api"}))

    layout = _ok(s.materialise())

    assert set(layout.trees) == {"web"} and layout.context == ""
    assert (f"{API_PR}'s change is in `acme/api`, and this preview is of `shop`'s own repository "
            f"— not included.") in s.record.missing


def test_two_open_pull_requests_in_one_repository_are_refused_but_one_in_each_is_a_product(shop):
    s = shop("s6")
    s.pull_request("acme/web", "12", WEB_PR, {"src/index.js": "// total\n"})
    s.pull_request("acme/web", "15", WEB_PR + "5", {"src/other.js": "// more\n"})
    s.tickets = [_card("12"), _card("15")]

    refused = s.materialise()

    assert isinstance(refused, Refused)
    assert refused.reasons[0].startswith("2 pull requests of this unit are open")
    assert "in one repository" in refused.reasons[0]


# ── 7. the writers: what lands in the context repository without a person ──────────────────────

import tests.test_a_proposal_whose_base_moved_still_lands_on_the_local_forge as local  # noqa: E402


@pytest.fixture
def sweep(tmp_path, monkeypatch):
    """The context repository as the ONE-MACHINE row makes it — bare, the installation's own —
    behind the real `LocalForge`, and a clone to push proposals from the way the product role
    pushes them: the world `test_a_proposal_whose_base_moved_…` builds, with real git."""
    from openfactory.adapters.forge.local import LocalForge

    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(root / "board.db"))
    monkeypatch.setenv("OPENFACTORY_BOT_NAME", local.BOT)
    monkeypatch.setenv("OPENFACTORY_BOT_EMAIL", "factory@example.invalid")
    person = root / "myapp"
    person.mkdir()
    local._ok(person, "init", "-q", "-b", "main")
    local._identity(person)
    (person / "app.py").write_text("print('one')\n")
    local._ok(person, "add", "-A")
    local._ok(person, "commit", "-qm", "first")
    forge_ = LocalForge("myapp", str(person), base="main")
    forge_.create_repository(name=local.CONTEXT)
    bare = forge_.clone_url(local.CONTEXT)
    authoring_ = root / "authoring"
    subprocess.run(["git", "clone", "-q", bare, str(authoring_)], capture_output=True, check=True)
    local._identity(authoring_)
    local._ok(authoring_, "symbolic-ref", "HEAD", "refs/heads/main")
    (authoring_ / "product.md").write_text("# myapp\n")
    local._ok(authoring_, "add", "-A")
    local._ok(authoring_, "commit", "-qm", "seed")
    local._ok(authoring_, "push", "-q", "origin", "main")
    return SimpleNamespace(forge=forge_, context=bare, authoring=authoring_)


@pytest.mark.parametrize("paths,allowed,out", [
    (["requirements/0012-total.md"], ["requirements"], []),
    (["requirements/../.openfactory/preview.compose.yml"], ["requirements"],
     ["requirements/../.openfactory/preview.compose.yml"]),
    ([".openfactory/preview.compose.yml"], [".openfactory", "requirements"],
     [".openfactory/preview.compose.yml"]),
    (["domain/2026-09-24-total.md", "docs/x.md"], ["domain/"], ["docs/x.md"]),
    (["/etc/passwd", "~/x", "", ".."], ["domain"], ["/etc/passwd", "~/x", "", ".."]),
    ([".okf/repos/acme--api/modules.yaml"], [".okf"], []),
])
def test_a_writer_lands_only_its_own_paths_and_never_the_platforms_directory(paths, allowed, out):
    from openfactory.policy.context_writes import outside

    assert outside(paths, allowed) == out


def test_the_paths_of_a_diff_are_both_sides_of_every_file_and_an_unreadable_diff_is_none():
    from openfactory.policy.context_writes import diff_paths

    diff = ("diff --git a/requirements/0012.md b/requirements/0012.md\n"
            "--- a/requirements/0012.md\n+++ b/requirements/0012.md\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/requirements/x.md b/.openfactory/preview.compose.yml\n"
            "rename from requirements/x.md\nrename to .openfactory/preview.compose.yml\n"
            'diff --git "a/requirements/a b.md" "b/requirements/a b.md"\n')
    assert diff_paths(diff) == ["requirements/0012.md", "requirements/x.md",
                                ".openfactory/preview.compose.yml", "requirements/a b.md"]
    assert diff_paths("") == []
    assert diff_paths("something that is not a diff\n") is None


def test_the_sweep_leaves_open_a_req_branch_carrying_the_previews_shape(sweep, caplog):
    """The acceptance of #265 §6.4: a `req/*` branch carrying `.openfactory/preview.compose.yml`
    is LEFT OPEN by the sweep, and says why; the requirement beside it still lands."""
    from openfactory.product.authoring import land_open_proposals

    local._commit(sweep.authoring, "req/0001-login",
                  {"requirements/0001-login.md": "# log in\n"}, "propose 1")
    local._commit(sweep.authoring, "req/0002-total", {
        "requirements/0002-total.md": "# total\n",
        ".openfactory/preview.compose.yml": "services:\n  x:\n    image: evil\n"}, "propose 2")

    with caplog.at_level("WARNING"):
        landed = land_open_proposals(docs_repo=local.CONTEXT, forge=sweep.forge, base="main")

    assert landed == ["req/0001-login"]
    shown = subprocess.run(["git", "-C", sweep.context, "cat-file", "-e",
                            "main:.openfactory/preview.compose.yml"], capture_output=True)
    assert shown.returncode != 0, "a shape landed on the context repository's base unattended"
    assert "req/0002-total" in (sweep.forge.list_branches(local.CONTEXT) or [])
    pr = sweep.forge.pr_for_head("req/0002-total", repo=local.CONTEXT)
    assert pr and sweep.forge.pr_status(pr=pr, repo=local.CONTEXT) == "open", \
        "left OPEN, for a person"
    assert "it changes `.openfactory/preview.compose.yml` — outside `requirements/`" in \
        caplog.text


class _Diffs:
    """A forge whose one `req/*` pull request shows the diff a test names."""

    def __init__(self, diff):
        self.diff, self.merged = diff, []

    def list_branches(self, repo="", *, prefix=""):
        return ["req/0003-x"]

    def pr_for_head(self, head, *, repo=""):
        return "https://x/pull/3"

    def pr_status(self, *, pr, repo=""):
        return "merged" if self.merged else "open"

    def pr_diff(self, *, pr, repo="", max_chars=60000):
        if isinstance(self.diff, Exception):
            raise self.diff
        return self.diff

    def merge_pr(self, *, pr, repo=""):
        self.merged.append(pr)

    def delete_branch(self, name, *, repo=""):
        return True


@pytest.mark.parametrize("diff,said", [
    (None, "its changes could not be read"),
    (RuntimeError("401"), "its changes could not be read (401)"),
    ("x" * 400_001, "its diff is too long to be read whole"),
    ("not a diff at all\n", "which files it changes could not be read"),
    ("diff --git a/reqs/0003.md b/reqs/0003.md\n", "it changes `reqs/0003.md` — outside "
                                                   "`requirements/`"),
])
def test_every_doubt_about_a_proposals_files_leaves_it_for_a_person(diff, said, caplog):
    from openfactory.product.authoring import land_open_proposals

    forge_ = _Diffs(diff)
    with caplog.at_level("WARNING"):
        assert land_open_proposals(docs_repo="acme/shop-context", forge=forge_) == []
    assert forge_.merged == [], "a proposal nobody could vouch for was merged"
    assert said in caplog.text and "OPENFACTORY_PRODUCT_PROPOSAL_LEFT_OPEN" in caplog.text


def test_the_sweep_lands_a_proposal_in_the_folder_the_product_declares():
    from openfactory.product.authoring import land_open_proposals

    forge_ = _Diffs("diff --git a/reqs/0003.md b/reqs/0003.md\n")
    assert land_open_proposals(docs_repo="acme/shop-context", forge=forge_,
                               requirements_dir="reqs") == ["req/0003-x"]


def _bare(tmp_path: Path, files: dict[str, str]) -> Path:
    seed, bare = tmp_path / "seed", tmp_path / "context.git"
    seed.mkdir()
    for rel, text in files.items():
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed / rel).write_text(text)
    _git(seed, "init", "-q", "-b", "main")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "seed")
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(bare)], check=True,
                   capture_output=True)
    return bare


def _files_on(bare: Path, branch: str = "main") -> list[str]:
    return _git(bare, "ls-tree", "-r", "--name-only", branch).split()


def test_a_fact_lands_under_domain_and_a_path_out_of_it_lands_nothing(tmp_path, monkeypatch):
    from openfactory.product import authoring

    bare = _bare(tmp_path, {"README.md": "# shop\n"})
    ok = authoring.record_fact(docs_repo=CONTEXT, clone_url=str(bare), term="total",
                               body="the total includes shipping", said_by="ana",
                               today="2026-09-24")
    assert ok.ok and ok.ref == "domain/2026-09-24-total.md"
    assert "domain/2026-09-24-total.md" in _files_on(bare)

    monkeypatch.setattr(authoring, "slugify", lambda term, limit=40:
                        "x/../../.openfactory/preview.compose")
    refused = authoring.record_fact(docs_repo=CONTEXT, clone_url=str(bare), term="evil",
                                    body="b", said_by="ana", today="2026-09-24")
    assert not refused.ok and "fora de `domain/`" in refused.detail
    assert not any(p.startswith(".openfactory") for p in _files_on(bare)), \
        "a fact reached the platform's directory on the base"


def test_a_fact_whose_checkout_staged_anything_else_commits_nothing(tmp_path, monkeypatch):
    """Checked on what git STAGED, not only on the path it was handed."""
    from openfactory.product import authoring

    bare = _bare(tmp_path, {"README.md": "# shop\n"})
    real = authoring._git

    def git(args, cwd=None):
        if args[:2] == ["add", "--"] and cwd is not None:
            (Path(cwd) / ".openfactory").mkdir(exist_ok=True)
            (Path(cwd) / ".openfactory" / "preview.compose.yml").write_text("services: {}\n")
            real(["add", "--", ".openfactory/preview.compose.yml"], cwd=cwd)
        return real(args, cwd=cwd)

    monkeypatch.setattr(authoring, "_git", git)
    refused = authoring.record_fact(docs_repo=CONTEXT, clone_url=str(bare), term="total",
                                    body="b", said_by="ana", today="2026-09-24")
    assert not refused.ok and ".openfactory/preview.compose.yml" in refused.detail
    assert _files_on(bare) == ["README.md"], "the commit went ahead"


def _bundle(tmp_path: Path) -> Path:
    from openfactory.knowledge.bundle import MANIFEST_FILE, MODULES_FILE

    bundle = tmp_path / "bundle" / "knowledge"
    bundle.mkdir(parents=True)
    (bundle / MODULES_FILE).write_text("modules: []\n")
    (bundle / MANIFEST_FILE).write_text("commit: abc\n")
    return bundle


def test_the_module_map_lands_under_okf_and_a_subpath_out_of_it_lands_nothing(tmp_path):
    from openfactory.knowledge.pipeline import okf_subpath, publish_bundle

    bare = _bare(tmp_path, {"README.md": "# shop\n"})
    bundle = _bundle(tmp_path)
    assert publish_bundle(bundle, str(bare), subpath=okf_subpath("acme/api"),
                          source_commit="abc")
    assert any(p.startswith(".okf/repos/acme--api/") for p in _files_on(bare))

    before = _git(bare, "rev-parse", "main")
    for subpath in (Path(".openfactory"), Path(".okf/../.openfactory/preview"),
                    Path("docs")):
        assert not publish_bundle(bundle, str(bare), subpath=subpath, source_commit="abd")
    assert _git(bare, "rev-parse", "main") == before, "the map was published outside .okf/"


# ── 8. filing: a card of the back end in the back end's repository, within `sources:` only ─────


def test_a_github_card_filed_in_another_repository_of_the_product_is_there_and_says_so(
        monkeypatch):
    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    tracker = GitHubIssuesTracker("acme/web")
    argv: list[list[str]] = []

    def gh(args, timeout=60):
        argv.append(list(args))
        repo = args[args.index("--repo") + 1]
        return subprocess.CompletedProcess(args, 0, f"https://github.com/{repo}/issues/14\n", "")

    monkeypatch.setattr(tracker, "_gh", gh)
    assert tracker.create_ticket(title="t", body="b", repo="acme/api") == "acme/api#14"
    assert argv[-1][argv[-1].index("--repo") + 1] == "acme/api"
    assert tracker.create_ticket(title="t", body="b") == "#14", "its own repository stays bare"
    assert argv[-1][argv[-1].index("--repo") + 1] == "acme/web"
    assert tracker.create_ticket(title="t", body="b", repo="acme/web") == "#14"


class _AdoClient:
    def __init__(self):
        self.bodies: list[list[dict]] = []

    def call(self, method, path, *, content_type=None, body=None, params=None):
        self.bodies.append(body)
        return {"id": 77}


@pytest.mark.parametrize("repo,options,area", [
    ("Deskline/fx-dsk-ui", {}, "Deskline\\fx-dsk-ui"),
    ("fx-dsk-ui", {"areas": '{"Portal": "fx-dsk-ui"}'}, "Deskline\\Portal"),
    ("", {}, None),
])
def test_an_azure_card_filed_in_another_repository_carries_its_area_path(repo, options, area):
    from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker

    client = _AdoClient()
    tracker = AzureBoardsTracker(organization="acme", project="Deskline", client=client,
                                 options=options)
    assert tracker.create_ticket(title="t", body="b", repo=repo) == "77"
    set_area = [op["value"] for op in client.bodies[-1] if op["path"] == "/fields/System.AreaPath"]
    assert set_area == ([area] if area else [])


def test_whether_a_row_can_file_elsewhere_is_read_from_its_signature():
    from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker
    from openfactory.adapters.tracker.base import files_elsewhere
    from openfactory.adapters.tracker.github import GitHubIssuesTracker
    from openfactory.product.module import _WatchedWrites

    class Stranger:
        def create_ticket(self, *, title, body):
            return "1"

    assert files_elsewhere(GitHubIssuesTracker("acme/web"))
    assert files_elsewhere(AzureBoardsTracker(organization="o", project="P", client=_AdoClient()))
    assert not files_elsewhere(Stranger()), "a row written before the keyword was asked for it"
    assert files_elsewhere(_WatchedWrites(GitHubIssuesTracker("acme/web"), lambda *a: None))
    assert not files_elsewhere(_WatchedWrites(Stranger(), lambda *a: None))


class _Filing:
    """A tracker that records where each card was filed."""

    def __init__(self, *, elsewhere: bool = True):
        self.filed: list[dict] = []
        if not elsewhere:
            self.create_ticket = self._create_here

    def find_ticket(self, *, title):
        return None

    def create_ticket(self, *, title, body, repo=""):
        self.filed.append({"title": title, "repo": repo})
        return f"{repo}#21" if repo else "#21"

    def _create_here(self, *, title, body):
        self.filed.append({"title": title, "repo": None})
        return "#21"

    def ticket_url(self, ref):
        return ""


def _module(monkeypatch, tracker):
    from openfactory.product.module import ProductModule

    ctx = ProductContext(link=ProductLink(active=True, docs_repo=CONTEXT, kind="ok"))
    project = Project(name="shop", repo_path="https://github.com/acme/web.git",
                      forge=ProviderRef(kind="github", repo="acme/web"),
                      product=ProductConfig(docs_repo=CONTEXT))
    mod = ProductModule(project, context=ctx, tracker=tracker)
    monkeypatch.setattr(mod, "_sources", lambda: ["acme/web", "acme/api"])
    monkeypatch.setattr(mod, "_docs_url", lambda: "")
    return mod


@pytest.mark.parametrize("target,filed,said", [
    ("acme/api", "acme/api", ""),
    ("ACME/api", "acme/api", ""),
    ("acme/web", "", ""),
    ("", "", ""),
    ("evil/api", "", "o cartão foi aberto em `acme/web`: `evil/api` não está entre os "
                     "repositórios deste produto."),
])
def test_a_card_goes_to_the_repository_the_role_named_only_within_sources(monkeypatch, target,
                                                                          filed, said):
    from openfactory.product.role import IssueDraft

    tracker = _Filing()
    mod = _module(monkeypatch, tracker)
    draft = IssueDraft(title="the total", objective="show it", target_repo=target, cites=12)

    done = mod._file_one(draft, _requirement(12), tracker, None)

    assert done.ok and tracker.filed == [{"title": "the total", "repo": filed}]
    assert done.detail == said
    assert done.ref == (f"{filed}#21" if filed else "#21")


def test_a_tracker_that_files_in_one_place_is_asked_for_that_place_and_it_is_said(monkeypatch):
    from openfactory.product.role import IssueDraft

    tracker = _Filing(elsewhere=False)
    mod = _module(monkeypatch, tracker)
    done = mod._file_one(IssueDraft(title="t", objective="o", target_repo="acme/api", cites=12),
                         _requirement(12), tracker, None)
    assert done.ok and tracker.filed == [{"title": "t", "repo": None}]
    assert "registra todo cartão num lugar só, e ele é de `acme/api`" in done.detail


def test_a_retried_filing_in_another_repository_finds_the_card_it_already_filed(monkeypatch):
    from openfactory.product.role import IssueDraft

    tracker = _Filing()
    mod = _module(monkeypatch, tracker)
    mod._board_tickets = [BoardTicket(number="acme/api#21", title="the total", body="")]
    done = mod._file_one(IssueDraft(title="the total", objective="o", target_repo="acme/api",
                                    cites=12), _requirement(12), tracker, None)
    assert done.existed and done.ref == "acme/api#21" and tracker.filed == []


# ── 9. the product's draft: its own pull request, in the context repository ───────────────────


def _readings(scenario: str = "s6", repos=("acme/api", "acme/web")):
    from openfactory.onboarding.preview_infer import infer_preview

    trees = FIXTURES / scenario / "trees"
    return [(r, infer_preview(trees / r.split("/")[1], name=r.split("/")[1])) for r in repos]


def test_s6_the_products_draft_is_byte_for_byte_what_its_preview_then_reads():
    """The compose file and the block `preview propose --product` drafts are the S6 fixture's
    context repository — the files the S6 preview above is assembled from."""
    from openfactory.onboarding.preview_product import draft_product
    from openfactory.onboarding.preview_propose import pr_body

    reading, out = draft_product(_readings(), product="shop", context=CONTEXT, accept=True)

    tree = FIXTURES / "s6" / "trees" / "shop-context"
    assert out.files == {".openfactory/preview.compose.yml":
                         (tree / ".openfactory" / "preview.compose.yml").read_text()}
    assert out.block == {"compose": ".openfactory/preview.compose.yml",
                         "expose": {"api": 8000, "web": 3000}}
    assert ProductPreview.model_validate(out.block)
    assert pr_body(reading, out, project="shop", repo=CONTEXT) == \
        (FIXTURES / "s6" / "expected" / "pull-request.md").read_text()
    compose_text = out.files[".openfactory/preview.compose.yml"]
    assert "context: ../../web" in compose_text and "context: ../../api" in compose_text
    assert all(e.path.split("/")[0] in ("web", "api")
               for s in reading.services for e in s.evidence), "a citation that says no repository"


def test_the_products_draft_waits_for_accept_on_what_is_inferred():
    from openfactory.onboarding.preview_product import draft_product

    reading, out = draft_product(_readings(), product="shop", context=CONTEXT)
    assert "db" not in out.files.get(".openfactory/preview.compose.yml", "")
    assert any("`db`" in n and "--accept" in n for n in out.left_out)


def test_a_source_that_declares_its_own_shape_refuses_the_products_draft(tmp_path):
    from openfactory.onboarding.preview_infer import infer_preview
    from openfactory.onboarding.preview_product import draft_product

    api = tmp_path / "api"
    shutil.copytree(FIXTURES / "s6" / "trees" / "api", api)
    manifest = api / ".openfactory" / "project.yaml"
    manifest.write_text(manifest.read_text() + "preview:\n  compose: [compose.yaml]\n"
                                                "  expose: {api: 8000}\n")
    readings = [("acme/api", infer_preview(api, name="api")), *_readings(repos=("acme/web",))]
    _, out = draft_product(readings, product="shop", context=CONTEXT, accept=True)
    assert out.refusal.startswith("`acme/api` already declares `preview:` in its own manifest")
    assert out.files == {} and out.block is None


def test_s7_a_source_with_its_own_compose_file_gets_the_block_that_points_at_it(tmp_path):
    from openfactory.onboarding.preview_product import draft_product

    readings = _readings("s7", repos=("acme/web", "acme/api"))
    checkouts = {r: FIXTURES / "s7" / "trees" / r.split("/")[1] for r, _ in readings}
    reading, out = draft_product(readings, product="shop", context=CONTEXT, accept=True,
                                 checkouts=checkouts)
    assert out.files == {}, "the client's own compose file was drafted over"
    assert out.block["compose"] == {"repository": "acme/web", "paths": ["docker-compose.yml"]}
    assert out.block["expose"] == {"api": 8000, "web": 3000}
    assert ProductPreview.model_validate(out.block)
    assert not any("../api" in q for q in reading.questions), "`api` IS a member's short name"


def test_s7_a_directory_no_member_answers_is_asked_as_dirs(tmp_path):
    from openfactory.onboarding.preview_infer import infer_preview
    from openfactory.onboarding.preview_product import draft_product

    web = tmp_path / "web"
    shutil.copytree(FIXTURES / "s7" / "trees" / "web", web)
    text = (web / "docker-compose.yml").read_text().replace("../api", "../backend")
    (web / "docker-compose.yml").write_text(text)
    readings = [("acme/web", infer_preview(web, name="web")), *_readings("s7", ("acme/api",))]
    reading, out = draft_product(readings, product="shop", context=CONTEXT, accept=True,
                                 checkouts={"acme/web": web})
    assert reading.questions[0].startswith(
        "`acme/web`'s compose file reaches `../backend`, which is not the short name of any "
        "repository of this product")
    assert "--set preview.dirs.backend=<owner/name>" in reading.questions[0]
    _, answered = draft_product(readings, product="shop", context=CONTEXT, accept=True,
                                checkouts={"acme/web": web},
                                answers={"preview": {"dirs": {"backend": "acme/api"}}})
    assert answered.block["dirs"] == {"backend": "acme/api"}


class _ContextForge:
    """The forge port at the methods a proposal in the context repository uses."""

    def __init__(self, existing: str | None = ""):
        self.existing = existing
        self.opened: list[dict] = []

    def pr_for_head(self, head, *, repo=""):
        if self.existing is None:
            raise RuntimeError("unreachable")
        return self.existing

    def pr_status(self, *, pr, repo=""):
        return "open"

    def list_branches(self, repo="", *, prefix=""):
        return []

    def open_pr(self, *, head, base, title, body, repo=""):
        self.opened.append({"head": head, "base": base, "title": title, "body": body,
                            "repo": repo})
        return f"https://github.com/{repo}/pull/9"


@pytest.fixture
def hosted_product(tmp_path, monkeypatch):
    """`shop` registered by URL, its three repositories real bare ones: the sources as the S6
    fixture has them, the context repository as `product init` left it."""
    from openfactory.adapters.forge import registry as forge_registry
    from openfactory.product import onboard

    root = Path(os.path.realpath(tmp_path))
    bares: dict[str, Path] = {}
    for repo, tree in (("acme/web", FIXTURES / "s6" / "trees" / "web"),
                       ("acme/api", FIXTURES / "s6" / "trees" / "api"),
                       (CONTEXT, FIXTURES / "s6" / "context-before")):
        seed = _repo(root / "seed" / repo.replace("/", "--"), tree)
        bares[repo] = root / "bare" / f"{repo.replace('/', '--')}.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(bares[repo])],
                       check=True, capture_output=True)
    forge_ = _ContextForge()
    monkeypatch.setattr(onboard, "context_forge", lambda project: forge_)
    monkeypatch.setattr(onboard, "context_clone_url", lambda project, repo: str(bares[repo]))
    monkeypatch.setattr(onboard, "_context_token", lambda project: None)
    monkeypatch.setattr(forge_registry, "clone_url_for",
                        lambda project, repo, token=None: str(bares[repo]))
    project = Project(name="shop", repo_path="https://github.com/acme/web.git",
                      forge=ProviderRef(kind="github", repo="acme/web"),
                      product=ProductConfig(docs_repo=CONTEXT))
    return SimpleNamespace(project=project, forge=forge_, bares=bares)


def test_s6_the_products_draft_is_its_own_pull_request_in_the_context_repository(hosted_product):
    from openfactory.onboarding.preview_product import propose_product
    from openfactory.onboarding.preview_propose import BRANCH

    h = hosted_product
    before = {r: _git(b, "for-each-ref") for r, b in h.bares.items()}

    outcome = propose_product(h.project, accept=True)

    assert outcome.ok and outcome.url == f"https://github.com/{CONTEXT}/pull/9"
    opened, = h.forge.opened
    assert (opened["repo"], opened["head"], opened["base"]) == (CONTEXT, BRANCH, "main")
    assert opened["title"] == "OpenFactory: a preview of the product shop"
    assert opened["body"] == (FIXTURES / "s6" / "expected" / "pull-request.md").read_text()
    after = FIXTURES / "s6" / "trees" / "shop-context"
    for rel in (".openfactory/product.yaml", ".openfactory/preview.compose.yml"):
        assert _git(h.bares[CONTEXT], "show", f"{BRANCH}:{rel}") == (after / rel).read_text(), rel
    assert "preview" not in _git(h.bares[CONTEXT], "show", "main:.openfactory/product.yaml"), \
        "the draft landed on the base: a product's shape is merged by a person"
    for repo in ("acme/web", "acme/api"):
        assert _git(h.bares[repo], "for-each-ref") == before[repo], f"{repo} was written to"


@pytest.mark.parametrize("existing,said", [
    ("https://github.com/acme/shop-context/pull/3", "already proposed at"),
    (None, "could not ask"),
])
def test_an_open_product_proposal_is_named_and_could_not_ask_proposes_nothing(hosted_product,
                                                                             existing, said):
    from openfactory.onboarding.preview_product import propose_product

    hosted_product.forge.existing = existing
    outcome = propose_product(hosted_product.project, accept=True)
    assert said in outcome.detail and hosted_product.forge.opened == []


def test_a_product_yaml_that_already_declares_a_preview_is_never_overwritten(hosted_product):
    from openfactory.onboarding.preview_product import propose_product

    h = hosted_product
    work = h.bares[CONTEXT].parent / "edit"
    subprocess.run(["git", "clone", "-q", str(h.bares[CONTEXT]), str(work)], check=True,
                   capture_output=True)
    (work / ".openfactory" / "product.yaml").write_text(
        (FIXTURES / "s6" / "trees" / "shop-context" / ".openfactory" / "product.yaml").read_text())
    _git(work, "commit", "-qam", "a person wrote the block")
    _git(work, "push", "-q", "origin", "main")

    outcome = propose_product(h.project, accept=True)
    assert not outcome.ok and "already declares `preview:`" in outcome.detail
    assert h.forge.opened == []


def test_the_verb_proposes_the_products_draft_with_product_and_refuses_single_repo_flags(
        hosted_product, monkeypatch):
    from typer.testing import CliRunner

    from openfactory import cli
    from openfactory.onboarding import preview_product

    monkeypatch.setattr(cli, "_get_project", lambda name: hosted_product.project)
    calls: list = []
    monkeypatch.setattr(preview_product, "propose_product",
                        lambda project, **kw: calls.append(kw) or preview_product.Outcome(
                            ok=True, repo=CONTEXT, url="https://x/pull/9"))
    out = CliRunner().invoke(cli.app, ["preview", "propose", "shop", "--product", "--accept",
                                       "--yes"])
    assert out.exit_code == 0, out.output
    assert calls == [{"accept": True, "answers": {}}] and "https://x/pull/9" in out.output

    out = CliRunner().invoke(cli.app, ["preview", "propose", "shop", "--product", "--source",
                                       "acme/api", "--yes"])
    assert out.exit_code == 2 and "--source" in out.output and len(calls) == 1

    out = CliRunner().invoke(cli.app, ["preview", "propose", "shop", "--product"])
    assert out.exit_code == 2 and "--yes" in out.output and len(calls) == 1


REQUIREMENT = "requirements/0012-editable-reconciled-statements.md"


@pytest.mark.parametrize("writer", ["propose", "accept", "drop", "decision", "fact"])
def test_no_writer_that_lands_on_the_base_unattended_commits_under_openfactory(
        tmp_path, monkeypatch, writer):
    """Whatever else reaches the index — here, a compose file planted beside the writer's own —
    the writers that land straight on the context repository's base commit NOTHING (§6.4)."""
    from openfactory.product import authoring
    from tests.test_product_authoring import _draft
    from tests.test_product_authoring import _Forge as _DocsForge

    monkeypatch.setattr(authoring, "_MERGE_DELAY", 0)
    text = authoring.render_requirement(_draft(), number=12, asked_by="ana", date="2026-09-01")
    bare = _bare(tmp_path, {"README.md": "# shop\n", REQUIREMENT: text})
    real = authoring._git

    def git(args, cwd=None):
        if args[:2] == ["add", "--"] and cwd is not None:
            (Path(cwd) / ".openfactory").mkdir(exist_ok=True)
            (Path(cwd) / ".openfactory" / "preview.compose.yml").write_text("services: {}\n")
            real(["add", "--", ".openfactory/preview.compose.yml"], cwd=cwd)
        return real(args, cwd=cwd)

    monkeypatch.setattr(authoring, "_git", git)
    common = {"docs_repo": CONTEXT, "clone_url": str(bare)}
    call = {
        "propose": lambda: authoring.propose_requirement(
            **common, draft=_draft(title="Another"), number=13, forge=_DocsForge()),
        "accept": lambda: authoring.accept_requirement(**common, path=REQUIREMENT, number=12,
                                                       accepted_by="ana"),
        "drop": lambda: authoring.drop_requirement(**common, path=REQUIREMENT, number=12,
                                                   dropped_by="ana"),
        "decision": lambda: authoring.record_decision(**common, path=REQUIREMENT, number=12,
                                                      decision="ship it", decided_by="ana"),
        "fact": lambda: authoring.record_fact(**common, term="total", body="b", said_by="ana"),
    }[writer]
    before = _git(bare, "rev-parse", "main")

    result = call()

    assert not result.ok and "não gravei nada" in result.detail, result
    assert _git(bare, "rev-parse", "main") == before, f"{writer} committed to the base"
    assert _git(bare, "branch", "--list", "req/*").strip() == "", f"{writer} pushed a branch"


def test_a_siblings_head_is_read_in_its_own_repository_so_stale_means_its_own_branch():
    """`openfactory/13` read in the front end's repository is another card's branch, or none: each
    pull request's head is asked of the repository the record says it is in."""
    from openfactory.preview import demand

    was = preview.Preview(project="shop", unit="req0012", kind="requirement", cards=("12", "13"),
                          state=preview.LIVE, pr_urls=(WEB_PR, API_PR),
                          branches={WEB_PR: "openfactory/12", API_PR: "openfactory/13"},
                          repos={WEB_PR: "acme/web", API_PR: "acme/api"})
    forge_ = Forge({"acme/web": Path("/src/web"), "acme/api": Path("/src/api")}, prs={})
    heard: list[tuple[str, str]] = []
    state = demand._forge_state(_project(forge_.repos), "req0012", was,
                                forge_of=lambda p: forge_,
                                heads_of=lambda remote, branch: heard.append((remote, branch))
                                or "f" * 40)
    assert heard == [("/src/web", "openfactory/12"), ("/src/api", "openfactory/13")]
    assert state.heads == {WEB_PR: "f" * 40, API_PR: "f" * 40}


def test_an_offered_change_in_a_repository_outside_the_product_is_never_fetched(shop):
    """The board could not be read, so the unit is what offered itself — and one offer is in a
    repository the product does not list. It is left out and said; the rest is previewed."""
    s = shop("s6")
    s.pull_request("acme/web", "12", WEB_PR, {"src/index.js": "// total\n"})
    tools = "https://github.com/acme/tools/pull/4"
    s.board_error = "rate limited"
    s.store = Store(preview.Preview(
        project="shop", unit="req0012", kind="requirement", cards=("12", "4"),
        state=preview.OFFERED, pr_urls=(WEB_PR, tools),
        branches={WEB_PR: "openfactory/12", tools: "openfactory/4"},
        repos={WEB_PR: "acme/web", tools: "acme/tools"}))

    layout = _ok(s.materialise())

    assert {t.repo for t in layout.trees.values()} == {CONTEXT, "acme/web", "acme/api"}
    assert (f"{tools}'s change is in `acme/tools`, which is not a repository of this product — "
            f"not included.") in s.record.missing
    assert s.record.pr_urls == (WEB_PR,), "the preview says it holds another product's change"


def test_the_map_whose_checkout_staged_anything_else_publishes_nothing(tmp_path, monkeypatch,
                                                                       caplog):
    """Checked on what git STAGED, as well as on the folder it was handed: the pre-check refuses a
    folder out of `.okf/` before anything is cloned, and the staged check anything else."""
    from openfactory.knowledge import pipeline

    bare = _bare(tmp_path, {"README.md": "# shop\n"})
    bundle = _bundle(tmp_path)
    before = _git(bare, "rev-parse", "main")
    with caplog.at_level("ERROR"):
        assert not pipeline.publish_bundle(bundle, str(bare), subpath=Path(".openfactory"),
                                           source_commit="abc")
    assert "the module map lands under .okf/ only" in caplog.text, "it was cloned to find out"

    real = pipeline._git

    def git(*args, cwd=None, author=None):
        if args[:2] == ("add", "-A") and cwd is not None:
            (Path(cwd) / ".openfactory").mkdir(exist_ok=True)
            (Path(cwd) / ".openfactory" / "preview.compose.yml").write_text("services: {}\n")
            real("add", "--", ".openfactory/preview.compose.yml", cwd=cwd)
        return real(*args, cwd=cwd, author=author)

    monkeypatch.setattr(pipeline, "_git", git)
    caplog.clear()
    with caplog.at_level("ERROR"):
        assert not pipeline.publish_bundle(bundle, str(bare),
                                           subpath=pipeline.okf_subpath("acme/api"),
                                           source_commit="abc")
    assert ".openfactory/preview.compose.yml would land outside .okf/" in caplog.text
    assert _git(bare, "rev-parse", "main") == before, "the map's commit carried a shape"


def test_a_member_that_cannot_be_fetched_is_a_refusal_on_the_card_not_a_step_that_dies(shop):
    s = shop("s6")
    s.pull_request("acme/web", "12", WEB_PR, {"src/index.js": "// total\n"})
    s.tickets = [_card("12")]
    world = s.world()

    def unreachable(project, repo, d):
        raise RuntimeError(f"project 'shop' is registered as 'https://x:tok@h/{repo}.git' and "
                           f"it could not be fetched")

    world.source = unreachable
    refused = steps.materialise(s.project, "req0012", runtime=Runtime(), world=world)

    assert isinstance(refused, Refused)
    assert refused.reasons[0].startswith("a repository of the product could not be fetched")
    assert "tok" not in refused.reasons[0], "a credential reached the card"
    assert s.record.state == preview.FAILED
    assert not os.path.exists(compose.workdir_for("shop", "req0012"))
