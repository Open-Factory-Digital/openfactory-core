"""Card #95 — the product/requirements path reached for github.com by construction.

Four things were true of `openfactory/product/` before this file existed, and each is a different shape of
the same defect: a provider written as a literal where the registry already answers the question.

    `normalize_repo`      assumed two segments, so an Azure Repos coordinate — the bare
                          `fx-dsk-context` every registry row actually uses, and the three-segment
                          `organization/project/repository` a person pastes — normalised to `""`.
                          `""` is not a harmless unknown here: it turns the module OFF, and it
                          empties the `sources:` membership set so the isolation check passes
                          without running.

    `clone_url`           eight call sites imported `runtime.fargate.entrypoint.clone_url`, which
                          spells `github.com`. The documentation checkout is one of them, so a
                          product on Azure had no corpus at all.

    `_repo_url`           read `GH_HOST`, which made it provider-aware in APPEARANCE: with that
                          variable set to `dev.azure.com` it produced `https://dev.azure.com/<repo>`,
                          which addresses nothing, and unset a github.com link to a repository that
                          may belong to somebody else.

    `_issue_url`          built `https://github.com/{repo}/issues/{n}` by hand — the exact call site
                          `TrackerAdapter.ticket_url` was put on the port for.

EVERY TEST HERE HAS A REACHABILITY HALF. The behaviour half proves the function answers correctly;
the reachability half proves a PRODUCTION call site reaches it, because this codebase's signature
defect is code that is written, tested, and called by nothing.
"""

from __future__ import annotations

import ast
import inspect
import logging
import subprocess
from pathlib import Path

import pytest

from openfactory.contracts.product import ProductConfig, ProductDocs
from openfactory.contracts.project import Project, ProviderRef
from openfactory.product.config import (
    MATCH_EXACT,
    MATCH_NAME,
    normalize_repo,
    repo_match,
    resolve_product_link,
)

#: The coordinates of the Azure deployment this card is about, spelled the way each surface spells
#: them: the registry names the repository alone (organisation and project live in the provider's
#: `options`), and a person documenting the product pastes what their browser showed them.
ORG = "acme-ai"
ADO_PROJECT = "factory"
DOCS_REPO = "fx-dsk-context"
SRC_REPO = "fx-dsk-spfx"
DOCS_URL = f"https://dev.azure.com/{ORG}/{ADO_PROJECT}/_git/{DOCS_REPO}"


def _ado_project(*, docs_repo: str = DOCS_REPO, sources: list[str] | None = None,
                 repo: str = SRC_REPO) -> Project:
    options = {"organization": ORG, "project": ADO_PROJECT}
    return Project(
        name="dsk", repo_path="/tmp/dsk",
        tracker=ProviderRef(kind="azure_devops", repo=ADO_PROJECT, options=options),
        forge=ProviderRef(kind="azure_devops", repo=repo, options=options),
        product=ProductConfig(docs_repo=docs_repo, admins=["U1"]),
    )


def _docs(sources: list[str] | None = None) -> ProductDocs:
    return ProductDocs(product="dsk", sources=sources if sources is not None else [SRC_REPO])


# ── 1. the coordinate, as measured ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("written,expected", [
    # what worked before, and must keep working
    ("AcmeFixtures/fx-dsk-context", "acmefixtures/fx-dsk-context"),
    ("git@github.com:AcmeCorp/x.git", "acmecorp/x"),
    # the three that returned "" — the whole card
    (f"{ORG}/{ADO_PROJECT}/{DOCS_REPO}", f"{ORG}/{ADO_PROJECT}/{DOCS_REPO}"),
    (DOCS_REPO, DOCS_REPO),
    (DOCS_URL, f"{ORG}/{ADO_PROJECT}/{DOCS_REPO}"),
    # the other spellings Azure DevOps itself serves
    (f"https://{ORG}@dev.azure.com/{ORG}/{ADO_PROJECT}/_git/{DOCS_REPO}",
     f"{ORG}/{ADO_PROJECT}/{DOCS_REPO}"),
    (f"git@ssh.dev.azure.com:v3/{ORG}/{ADO_PROJECT}/{DOCS_REPO}",
     f"{ORG}/{ADO_PROJECT}/{DOCS_REPO}"),
    (f"https://{ORG}.visualstudio.com/{ADO_PROJECT}/_git/{DOCS_REPO}",
     f"{ORG}/{ADO_PROJECT}/{DOCS_REPO}"),
    (f"{DOCS_URL}?path=%2Freadme.md&version=GBmain", f"{ORG}/{ADO_PROJECT}/{DOCS_REPO}"),
])
def test_an_azure_repos_coordinate_is_a_repository_reference(written, expected):
    """MEASURED, not guessed. These four lines are the card's own table, and three of them read
    `""` before: a two-segment assumption is GitHub's shape wearing the name of a general rule."""
    assert normalize_repo(written) == expected


def test_the_legacy_azure_host_keeps_the_organisation_it_carries():
    """`acme-ai.visualstudio.com/df/_git/x` and `dev.azure.com/acme-ai/df/_git/x` are the SAME
    repository and Azure DevOps still serves both. Dropping the host would turn the first into a
    two-segment coordinate — which does not fail, it MISMATCHES, and a mismatch here is reported to
    a human as a membership inconsistency over a URL copied out of the wrong browser tab."""
    assert (normalize_repo(f"https://{ORG}.visualstudio.com/{ADO_PROJECT}/_git/{DOCS_REPO}")
            == normalize_repo(DOCS_URL))


def test_a_bare_owner_is_not_mistaken_for_a_hostname():
    """The regression guard for the first draft of this fix: a prefix strip that accepted a bare
    `host/` read `AcmeCorp` as a hostname and threw it away, so every two-segment GitHub reference
    silently became its repository name — and two different owners' repositories of one name then
    compared EQUAL."""
    assert normalize_repo("AcmeCorp/x") == "acmecorp/x"
    assert normalize_repo("someone-else/x") == "someone-else/x"
    assert repo_match("AcmeCorp/x", "someone-else/x") == ""


@pytest.mark.parametrize("written,expected", [
    ("AcmeCorp/v3", "acmecorp/v3"),
    ("AcmeCorp/_git", "acmecorp/_git"),
    ("v3", "v3"),
])
def test_a_route_segment_is_only_a_route_segment_where_a_route_puts_it(written, expected):
    """`_git` and `v3` are dropped because Azure DevOps' URLs carry them — and a blanket "drop any
    segment with that name" turns the perfectly ordinary GitHub repository `AcmeCorp/v3` into the
    bare owner `acmecorp`. That is a silent corruption of a VALID coordinate, which is precisely
    the class of bug this whole function exists to remove rather than to add."""
    assert normalize_repo(written) == expected


@pytest.mark.parametrize("junk", ["", None, "   ", "a/b/c/d", "git@github.com", "two words", ".."])
def test_unusable_is_still_empty_so_the_caller_can_still_tell_the_two_apart(junk):
    """Accepting one segment must not turn this into "anything is a repository". `git@github.com`
    is a real typo out of a client's `.sdlc/project.yaml`, and parsing it as a repository NAMED
    `git@github.com` would report it as a membership conflict instead of an unreadable field."""
    assert normalize_repo(junk) == ""


# ── 2. comparing two spellings of one repository ────────────────────────────────────────────────

def test_a_bare_name_and_a_qualified_one_match_but_say_so():
    """The two spellings arrive on the SAME deployment: the registry names `fx-dsk-spfx` and the
    docs repo's `sources:` lists what a person pasted. `==` would report one repository written
    twice as a membership inconsistency — the false alarm this module most wants to avoid."""
    assert repo_match(SRC_REPO, f"{ORG}/{ADO_PROJECT}/{SRC_REPO}") == MATCH_NAME
    assert repo_match(SRC_REPO, SRC_REPO) == MATCH_EXACT


def test_two_qualified_coordinates_that_disagree_stay_a_conflict():
    """The leniency is bounded on purpose: it is what keeps the check that stops one client's
    requirements being written from another's code doing its job."""
    assert repo_match(f"{ORG}/{ADO_PROJECT}/x", f"someone-else/{ADO_PROJECT}/x") == ""
    assert repo_match(f"{ORG}/{ADO_PROJECT}/x", f"{ORG}/other-project/x") == ""


# ── 3. what the coordinate decides: the module runs at all ──────────────────────────────────────

def test_an_azure_product_resolves_instead_of_reporting_a_broken_registry():
    """THE HEADLINE. `authorized = normalize_repo(cfg.docs_repo)` was `""` for every Azure row, so
    the module answered "the registry's `product.docs_repo` is missing or unreadable" — and a
    client whose product is on Azure was told "não consigo ver os requisitos" to every message."""
    link = resolve_product_link(project=_ado_project(), manifest_docs_repo=DOCS_REPO,
                                docs=_docs())
    assert link.active is True, link.reason
    assert link.docs_repo == DOCS_REPO


def test_a_membership_set_that_could_not_be_read_is_never_a_membership_set_that_passed():
    """THE DANGEROUS HALF, and the reason `""` was not a harmless unknown. With every `sources:`
    entry normalising to `""` the set was EMPTY, the project's own source repo normalised to `""`
    too, and `if source and source not in members` never ran — so the one check standing between
    an agent and another client's requirements read as passed. Absence must not read as
    compliance: the module goes off and names the field to fix."""
    link = resolve_product_link(project=_ado_project(repo="a/b/c/d"),
                                manifest_docs_repo=DOCS_REPO, docs=_docs())
    assert link.active is False and link.kind == "config"
    assert "a/b/c/d" in link.reason
    assert "forge.repo" in link.reason


def test_a_source_that_is_genuinely_absent_from_the_set_is_still_refused():
    """The positive twin: the check that stopped running must still FIRE when it should."""
    link = resolve_product_link(project=_ado_project(),
                                manifest_docs_repo=DOCS_REPO,
                                docs=_docs(sources=[f"{ORG}/{ADO_PROJECT}/some-other-repo"]))
    assert link.active is False and link.kind == "conflict"
    assert "sources:" in link.reason


def test_an_unreadable_member_is_named_rather_than_silently_dropped():
    """`- {""}` removed unparseable members and nothing said so. A repository dropped from the
    membership set is invisible to the product role for ever — and "not listed" and "list
    unreadable" produced identical silence."""
    link = resolve_product_link(
        project=_ado_project(), manifest_docs_repo=DOCS_REPO,
        docs=_docs(sources=[SRC_REPO, "a/b/c/d"]))
    assert link.active is True
    assert any("cannot read" in w and "a/b/c/d" in w for w in link.warnings)


def test_the_refusal_names_what_it_could_not_read_because_a_refusal_carries_no_warnings():
    """THE BRANCH THE WARNING ABOVE CANNOT REACH, and it is the one the whole `sources:` fix is
    about. `_off` returns a `ProductLink` with no warnings at all, so when EVERY entry is
    unreadable — a `sources:` list of Azure coordinates, which is exactly the state this card
    exists to end — the membership check fails and the operator is told:

        "…is not listed in `sources:` … (it lists nothing). Add it there."

    about a block they can see listing it. They add it again, in the same spelling that failed.
    Warning on the surviving path and going silent on the refusing one is "not listed" and "list
    unreadable" collapsing into one message again, one branch further down."""
    link = resolve_product_link(project=_ado_project(), manifest_docs_repo=DOCS_REPO,
                                docs=_docs(sources=["a/b/c/d", "two words"]))
    assert link.active is False and link.kind == "conflict"
    assert link.warnings == [], "a refusal carries no warnings — that is why this must be inline"
    assert "cannot read" in link.reason and "a/b/c/d" in link.reason, link.reason


def test_a_match_made_on_the_bare_name_alone_is_declared():
    """Correct on this deployment, and it stops being correct the day two of its projects host a
    repository of one name. Telling somebody now costs a line of text."""
    link = resolve_product_link(project=_ado_project(), manifest_docs_repo=DOCS_REPO,
                                docs=_docs(sources=[f"{ORG}/{ADO_PROJECT}/{SRC_REPO}"]))
    assert link.active is True
    assert any("NAME" in w for w in link.warnings), link.warnings


# ── 4. the clone URL: one home, and it is the forge's ───────────────────────────────────────────

def _string_literals(tree):
    """Every string constant in `tree` that is not a docstring.

    PROSE IS NOT A LITERAL. This package explains at length WHY `github.com` must not be spelled
    here, so a plain substring scan flags the very comments that record the lesson — and a guard
    that fires on its own explanation gets deleted rather than obeyed. Docstrings are excluded by
    identity, so a host named inside an f-string or a bare assignment is still caught."""
    import ast

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = (node.body or [None])[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def test_nothing_in_the_product_package_spells_a_forge_host():
    """A LITERAL IS A DEFECT THAT LOOKS LIKE CODE. Eight call sites imported
    `runtime.fargate.entrypoint.clone_url` — the helper `ForgeAdapter.clone_url`'s own docstring
    names as the reason it exists — and one hand-built issue URL made nine.

    Asserted over the source rather than by behaviour because a tenth would be added the same way
    the ninth was: by copying a neighbour."""
    import ast
    import pathlib

    package = pathlib.Path(inspect.getfile(resolve_product_link)).parent
    offenders = []
    for path in sorted(package.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        offenders += [f"{path.name}:{line}: {value!r}"
                      for line, value in _string_literals(tree)
                      if "github.com" in value or "dev.azure.com" in value]
        offenders += [f"{path.name}:{node.lineno}: imports the github.com clone_url"
                      for node in ast.walk(tree)
                      if isinstance(node, ast.ImportFrom)
                      and (node.module or "").endswith("fargate.entrypoint")
                      and any(a.name == "clone_url" for a in node.names)]
    assert offenders == [], "\n".join(offenders)


def test_the_documentation_checkout_goes_through_the_forge_registry(monkeypatch):
    """REACHABILITY. `load_product_context` is the one door to a corpus, and this is the line that
    decides which HOST it clones from. Before this it was `github.com` for every provider."""
    from openfactory.product import loader

    seen: dict = {}

    def _clone_url_for(project, repo="", *, token=None):
        seen["project"], seen["repo"], seen["token"] = project.name, repo, token
        raise RuntimeError("stop here — the URL is what this test is about")

    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for", _clone_url_for)
    ctx = loader.load_product_context(_ado_project(), token="gh-token")

    assert seen["repo"] == DOCS_REPO, "the docs repo must be the one asked for"
    assert seen["project"] == "dsk", "the PROJECT decides the forge — that is the whole seam"
    assert ctx.available is False and "could not be checked out" in ctx.reason


def test_every_writer_addresses_the_docs_repo_through_one_helper():
    """`ProductModule._clone_url` is the single home. Six writers plus two checkouts used to carry
    their own import of the github.com helper; a ninth would have been added by copying an
    eighth."""
    from openfactory.product import module as product_module

    source = inspect.getsource(product_module)
    assert source.count("self._clone_url(") == 8, (
        "every clone on the product path goes through the one helper — a new writer that spells "
        "its own URL is how the github.com literal came back")


def test_the_azure_row_keeps_its_own_credential_on_the_product_path(monkeypatch):
    """The forge registry REFUSES an ambient token on its Azure row, because every caller hands
    that axis a GitHub credential. `ProductModule.token` is one of them — `forge_token_for` gives
    it whatever the deployment holds. Routing through `clone_url_for` is what makes the refusal
    apply here too, instead of being walked around one layer up.

    THE PAT IS SET HERE BECAUSE THE UNSET CASE IS NOT THIS PACKAGE'S TO ANSWER, and it is not
    clean: `clone_url_for` ends in `token=getattr(forge, "token", None) or token`, so with
    `AZURE_DEVOPS_PAT` absent the `or` hands the ADO adapter the caller's GitHub token after all —
    the exact defect its own docstring says the wrapper exists to prevent. Reported, not fixed:
    `openfactory/adapters/forge/registry.py` belongs to another agent's card."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "an-azure-pat")
    from openfactory.adapters.forge.registry import clone_url_for

    url = clone_url_for(_ado_project(), DOCS_REPO, token="ghp_a_github_secret")
    assert "dev.azure.com" in url
    assert "ghp_a_github_secret" not in url, "a github.com secret must never reach Microsoft"
    assert "an-azure-pat" in url, "the adapter's own credential is what authenticates the clone"
    assert f"/{ORG}/{ADO_PROJECT}/_git/{DOCS_REPO}" in url


# ── 5. the two URLs a human reads ───────────────────────────────────────────────────────────────

def _module_for(project):
    from openfactory.product.config import resolve_product_link as _resolve
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule

    link = _resolve(project=project, manifest_docs_repo=DOCS_REPO, docs=_docs())
    return ProductModule(project, token="", context=ProductContext(link=link))


def test_the_docs_link_on_a_filed_card_addresses_the_repository_that_exists():
    """`_repo_url` read `GH_HOST` and was therefore provider-aware in APPEARANCE only. The `##
    Source` block is the one line that makes an authored issue auditable."""
    url = _module_for(_ado_project())._docs_url()
    assert url == DOCS_URL, url


def test_the_docs_link_never_carries_a_credential(monkeypatch, caplog):
    """THE GUARD BEHIND THE SENTENCE. This string is written onto a client's board, and the forge
    adapter's `token` property resolves the deployment's PAT at every use — so "we ask for it
    without a credential" has to be checkable, not merely stated. Nothing downstream would notice
    a userinfo section in a published URL."""
    monkeypatch.setattr(
        "openfactory.adapters.forge.azure_devops.AzureReposForge.clone_url",
        lambda self, repo, *, token=None: f"https://openfactory:a-real-pat@dev.azure.com/x/_git/{repo}")
    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        url = _module_for(_ado_project())._docs_url()
    assert url == "", "a URL carrying userinfo must be dropped, not published"
    assert "OPENFACTORY_PRODUCT_DOCS_URL_HAS_A_CREDENTIAL" in caplog.text


def test_a_card_with_no_usable_docs_link_names_the_repository_without_linking_it():
    """No link beats a wrong one: the provenance of a requirement is what makes the card auditable,
    and on GitHub Enterprise a same-named repository on the public site may belong to somebody
    else."""
    from openfactory.product.authoring import issue_body
    from openfactory.product.role import IssueDraft

    body = issue_body(IssueDraft(title="t", objective="o", cites=4),
                      requirement_path="requirements/0004-x.md", docs_repo=DOCS_REPO)
    assert f"`{DOCS_REPO}`" in body
    assert "http" not in body.split("## Source", 1)[1]


def test_the_card_url_is_asked_of_the_tracker_not_spelled_by_the_product_module():
    """`https://github.com/{repo}/issues/{n}` was built by hand at three call sites — the exact one
    `TrackerAdapter.ticket_url` was put on the port for. On Azure Boards a work item lives at
    `/_workitems/edit/{id}`."""
    module = _module_for(_ado_project())

    class _Tracker:
        def ticket_url(self, ref):
            return f"https://dev.azure.com/{ORG}/{ADO_PROJECT}/_workitems/edit/{ref}"

    assert module._issue_url(_Tracker(), "412").endswith("/_workitems/edit/412")


def test_a_tracker_that_cannot_name_a_url_costs_the_link_and_not_the_card():
    """The contract allows "" and the board tolerates it; a placement is repairable and an
    invented URL is not."""
    module = _module_for(_ado_project())

    class _Broken:
        def ticket_url(self, ref):
            raise RuntimeError("throttled")

    assert module._issue_url(_Broken(), "412") == ""


# ── 6. no vendor's command line is left on the product path ────────────────────────────────────

def test_the_product_path_starts_NO_process_but_git(monkeypatch):
    """TWO THINGS WERE WRONG WITH SHELLING OUT TO `gh` HERE, and only the first was obvious.
    `gh pr create --repo fx-dsk-context` cannot succeed against Azure Repos. The second was a
    CREDENTIAL LEAK: the callers pass `ProductModule.token`, which resolves through
    `credentials.forge_token_for`, so on an Azure project it is `AZURE_DEVOPS_PAT` — and `_gh`
    exported whatever it was given as `GH_TOKEN` before running a process that talks to github.com.
    A Microsoft secret sent to GitHub, and a 401 that reads like a revoked credential.

    The stopgap was a runner that REFUSED on any non-GitHub forge: honest, and it lost the whole
    review-request ceremony on every other vendor. #95 removed the reason for both — the forge
    adapter opens, merges and reads the pull request back, on any vendor, carrying its own
    credential. So the guard is no longer "refuse politely", it is "there is nothing to refuse".

    DRIVEN, not grepped: a real proposal is run end to end with `subprocess.run` replaced by one
    that fails on anything that is not `git`."""
    from openfactory.product import authoring

    started: list[str] = []
    real = subprocess.run

    def _watch(argv, *a, **kw):
        started.append(argv[0] if isinstance(argv, (list, tuple)) else str(argv))
        assert started[-1] == "git", f"the product path started {started[-1]!r}"
        return real(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", _watch)

    forge = _PortForge()
    res = authoring.propose_requirement(
        docs_repo=DOCS_REPO, clone_url="file:///nowhere", number=1, forge=forge,
        draft=_a_draft(), token="an-azure-pat", forge_kind="azure_devops")

    assert started == ["git"], f"more than the clone was started: {started}"
    assert res.ok is False and "could not clone" in res.detail
    assert not hasattr(authoring, "gh_runner"), "the refusing runner is importable again"
    assert not hasattr(authoring, "_gh")


def test_the_review_request_is_OPENED_on_an_azure_deployment(caplog):
    """THE ISSUE, IN ONE ASSERTION. On any forge but GitHub this used to end with the branch pushed
    and no pull request, for ever — `gh_runner` logged `OPENFACTORY_PRODUCT_GH_NOT_THIS_FORGE` and
    returned "". The module was right that it could not act and right to say so; what it could not
    do was act.

    Now the vendor is not consulted at all: `forge_kind` is accepted and ignored, and the adapter
    does the work. Proven against the live API too — `acme-ai/factory` PR 14, opened by an
    adapter built for `fx-ado` into `fx-dsk-context`, merged, branch deleted (2026-08-06)."""
    from openfactory.product import authoring

    forge = _PortForge()
    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        url = authoring._open_review_request(forge, docs_repo=DOCS_REPO, head="req/0001-x",
                                             base="main", title="REQ-0001", body="b")

    assert url, "the review request was refused on a vendor the port covers"
    assert forge.opened == [(DOCS_REPO, "req/0001-x")], (
        "the pull request was aimed at something other than the DOCUMENTATION repository")
    assert "OPENFACTORY_PRODUCT_GH_NOT_THIS_FORGE" not in caplog.text
    assert authoring._merge_and_confirm(forge, docs_repo=DOCS_REPO, pr=url, delay=0) is True


class _PortForge:
    """The whole port surface this module uses, over an arbitrary repository."""

    def __init__(self):
        self.opened: list[tuple[str, str]] = []
        self.state: dict[str, str] = {}

    def list_branches(self, repo="", *, prefix=""):
        return []

    def pr_for_head(self, head, *, repo=""):
        return ""

    def open_pr(self, *, head, base, title, body, repo=""):
        self.opened.append((repo, head))
        url = f"https://forge/{repo}/pull/{len(self.opened)}"
        self.state[url] = "open"
        return url

    def pr_status(self, *, pr, repo=""):
        return self.state.get(pr, "open")

    def merge_pr(self, *, pr, repo=""):
        self.state[pr] = "merged"

    def delete_branch(self, name, *, repo=""):
        return True


def _a_draft():
    from openfactory.product.role import RequirementDraft

    return RequirementDraft(title="Exportar extratos", why="w", must_be_true=["x"])


def test_the_writers_that_READ_the_docs_repo_are_HANDED_a_forge_by_production(monkeypatch):
    """REACHABILITY, DRIVEN THROUGH THE PRODUCTION ENTRY POINT. `propose_requirement` asks the docs
    repository two questions — which `req/*` branches exist, and whether this one was ever proposed
    — and both were `gh` shell-outs, so both answered "" on any deployment that is not GitHub's.
    They go through `ForgeAdapter` now, which only helps if the module actually builds one: an
    adapter that arrives solely from tests is this codebase's signature defect (#21), and the
    placement default `board=None` is the same trap in the same file.

    Asserted where the client's act enters — `ProductModule.propose` — rather than by counting a
    string in the source, so a call site that stops passing it fails HERE."""
    seen: dict = {}

    class _Forge:
        token = None

        def list_branches(self, repo="", *, prefix=""):
            seen["branches"] = (repo, prefix)
            return []

        def pr_for_head(self, head, *, repo=""):
            seen["pr_for_head"] = (head, repo)
            return ""

        def clone_url(self, repo, *, token=None):
            return f"https://dev.azure.com/{ORG}/{ADO_PROJECT}/_git/{repo}"

    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                        lambda project, *, token=None, token_provider=None: _Forge())
    # the clone is the next step and is not what this test is about
    monkeypatch.setattr("openfactory.product.authoring._git", lambda args, cwd=None: (1, "no origin"))

    module = _module_for(_ado_project())

    from openfactory.product.role import ProductAnswer, RequirementDraft

    result = module.propose(
        ProductAnswer(ok=True, draft=RequirementDraft(title="Exportar extratos", why="w",
                                                      must_be_true=["x"])),
        actor="U1")

    assert seen["branches"] == (DOCS_REPO, "req/"), (
        "the proposal branches were not read through the forge, about the DOCUMENTATION repository")
    assert seen["pr_for_head"][1] == DOCS_REPO
    assert result.ok is False and "could not clone" in result.detail   # the step after the reads


def test_the_FORGE_reaches_every_entry_point_that_writes_to_the_docs_repository():
    """REACHABILITY. Three functions act on the documentation repository, and one left without an
    adapter would go on being GitHub-only — or, worse, silently do nothing — while the other two
    were fixed. `land_open_proposals` is now among them: its four acts (open / merge / delete /
    leave alone) all needed a method that could name a repository, which is exactly what #95 gave
    the port."""
    from openfactory.product import authoring

    for fn in (authoring.propose_requirement, authoring.land_open_proposals,
               authoring.propose_baseline):
        assert "forge" in inspect.signature(fn).parameters, fn.__name__

    from openfactory.product import module as product_module

    # AND BOTH WRITERS ARE HANDED THE ADAPTER ITSELF. `propose` has a behavioural guard above;
    # `baseline` would need a survey, a source checkout and a role to drive end to end, and the
    # reads it is about happen before any of them. Counted, for the reason its sibling is: the
    # failure this catches is somebody deleting one argument of two, after which the writer
    # refuses every baseline with a sentence about a board it was never given.
    assert inspect.getsource(product_module).count("forge=self._forge()") == 2, (
        "both writers that act on the documentation repository must be handed a forge")


def test_the_HOURLY_sweep_is_the_one_call_site_still_missing_its_forge():
    """**NAMED, BECAUSE IT IS A REAL GAP AND NOT A FINISHED JOB.**
    `runtime/temporal/activities.py::_land_product_proposals` calls `land_open_proposals` on every
    hourly tech-lead round with a `token` and no `forge`. `token` is accepted and ignored, so the
    sweep answers `None` and logs `OPENFACTORY_PRODUCT_SWEEP_NO_FORGE` — loud, and doing nothing.

    That file is not this pass's to edit. This test says out loud what remains rather than letting
    it be discovered as silence: it FAILS the day somebody wires `forge=` at that call site, and
    the fix is to delete this test and assert the wiring instead."""
    tree = ast.parse(Path("openfactory/runtime/temporal/activities.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "land_open_proposals"]
    assert calls, "the recovery exists and nothing calls it"
    for call in calls:
        assert not any(k.arg == "forge" for k in call.keywords), (
            f"the sweep at activities.py:{call.lineno} now HAS a forge — delete this test and "
            f"assert the wiring instead")


# ── 7. the board reader ─────────────────────────────────────────────────────────────────────────

def test_an_azure_board_is_READ_now_and_no_gh_process_is_ever_started(monkeypatch):
    """THE HEADLINE OF THIS SECTION, INVERTED BY #97. `_columns` routed the board read through the
    provider registry correctly and, on Azure, had executed exactly never: `_sweep` read the issues
    with `gh issue list` first and returned at that failure. The module answered with a NAMED
    refusal — the right shape for a capability that did not exist, and an apology all the same.

    `TrackerAdapter.list_tickets` is that capability, so the refusal is gone and the board is read.
    What must NOT come back is the old failure mode: no subprocess at all, because the reader was
    handed `ProductModule.token` — this project's Azure PAT — and `_gh` exported whatever it was
    given as `GH_TOKEN` to a process that talks to github.com, once per board read."""
    import subprocess

    from openfactory.product import board

    def _must_not_run(*a, **kw):
        raise AssertionError("no process may be started to read an Azure DevOps board")

    monkeypatch.setattr(subprocess, "run", _must_not_run)
    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda project, *, token=None, token_provider=None: _AdoTracker())
    monkeypatch.setattr(board, "_columns", lambda project, token: {"14": "TO-DO"})
    board.forget_board()

    tickets, error = board.read_board(_ado_project(), token="an-azure-pat")

    assert error == ""
    assert [(t.number, t.column) for t in tickets] == [("14", "TO-DO")]
    assert tickets[0].state_reason == "" and tickets[0].assignees == ["nina@acme.ai"]


class _AdoTracker:
    """What `AzureBoardsTracker.list_tickets` answers, in the port's own vocabulary."""

    def list_tickets(self, *, state="all", updated_since="", limit=0):
        from openfactory.adapters.tracker.base import TicketSummary

        return [TicketSummary(ref="14", title="Conferência de notas", body="…", state="open",
                              assignees=["nina@acme.ai"], updated_at="2026-08-06T11:27:51.75Z")]


def test_an_unreadable_azure_board_is_still_never_an_empty_one(monkeypatch):
    """What the refusal was PROTECTING is not allowed to be lost with it. `None` from the port is
    "I could not read"; every caller here branches on `error`, and an empty board is an ANSWER —
    "nothing is queued", "no findings", "the open questions resolved themselves"."""
    from openfactory.product import board

    class _Unreadable:
        def list_tickets(self, *, state="all", updated_since="", limit=0):
            return None

    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda project, *, token=None, token_provider=None: _Unreadable())
    # a READABLE, empty column set — so the only thing that can produce an error here is the
    # unreadable ticket list. Left to the real board this test passed for the wrong reason: the
    # Azure board build fails on its own and supplies an error of its own.
    monkeypatch.setattr(board, "_columns", lambda project, token: {})
    board.forget_board()

    tickets, error = board.read_board(_ado_project(), token="an-azure-pat")

    assert tickets == [] and error, "an unreadable Azure board answered like an empty one"


def test_the_board_reader_still_reads_a_github_project(monkeypatch):
    """The positive twin: a reader that worked for nobody would look exactly like a working one to
    the tests above."""
    from openfactory.product import board

    built: dict = {}

    class _Empty:
        def list_tickets(self, *, state="all", updated_since="", limit=0):
            built["asked"] = True
            return []

    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda project, *, token=None, token_provider=None: _Empty())
    monkeypatch.setattr(board, "_columns", lambda project, token: {})
    board.forget_board()
    project = Project(name="gh", repo_path="/tmp/gh",
                      tracker=ProviderRef(kind="github", repo="Org/repo"))
    tickets, error = board.read_board(project, token="a-github-token")

    assert error == "" and tickets == []
    assert built.get("asked"), "the GitHub path stopped reading the board"


# ── 8. the credential the ticket writes travel on ───────────────────────────────────────────────

#: The registry row's own spelling: the project NAMES the variable, the registry never holds the
#: secret (`credentials.tracker_token_for`, ADR-0015's `bot_token_env` shape).
def _ado_project_naming_its_pat() -> Project:
    options = {"organization": ORG, "project": ADO_PROJECT, "token_env": "AZURE_DEVOPS_PAT"}
    return Project(
        name="dsk", repo_path="/tmp/dsk",
        tracker=ProviderRef(kind="azure_devops", repo=ADO_PROJECT, options=options),
        forge=ProviderRef(kind="azure_devops", repo=SRC_REPO, options=options),
        product=ProductConfig(docs_repo=DOCS_REPO, admins=["U1"]),
    )


class _FakeBoard:
    def add_item(self, *, issue_url):
        return True

    def set_column(self, *, issue, issue_url, name):
        return True


def test_the_tickets_and_the_board_travel_on_this_projects_credential_not_the_deployments(
        monkeypatch):
    """REACHABILITY, THROUGH A PRODUCTION ENTRY POINT — `promote` is the action that spends money,
    and it builds both adapters.

    `ProductModule` resolved its tracker and its board with `credentials.tracker_token()`: ONE
    process-wide value (`OPENFACTORY_TRACKER_TOKEN` / `OPENFACTORY_BOT_TOKEN`) on a worker that now serves
    projects on different vendors. The tracker registry's Azure row accepts the token it is handed
    — unlike the FORGE registry's, which refuses it and mints its own — so this module was posting
    the deployment's GitHub PAT to dev.azure.com as HTTP Basic. Two failures, and the second is the
    expensive one: a github.com secret sent to Microsoft, and a 401 that reads like a revoked
    credential rather than like the configuration mistake it is.

    `forge_token_for` already closed this on the other axis (`ProductModule.token`) and every other
    build site in the codebase — factory, activities, CLI, doctor, tech-lead — had already moved to
    the per-project resolver. This module was the last reader of the process-wide one."""
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghp_the_deployments_github_secret")
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "the-projects-azure-pat")

    seen: dict = {}

    class _Tracker:
        def ticket_url(self, ref):
            return f"https://dev.azure.com/{ORG}/{ADO_PROJECT}/_workitems/edit/{ref}"

    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda project, *, token=None, token_provider=None:
                            seen.update(tracker=token) or _Tracker())
    monkeypatch.setattr("openfactory.adapters.board.build_board",
                        lambda project, *, token=None: seen.update(board=token) or _FakeBoard())
    # the impediment seam reaches DynamoDB; this test is about the credential, not the report
    monkeypatch.setattr("openfactory.product.module._tell_the_factory",
                        lambda *a, **kw: None)

    results = _module_for(_ado_project_naming_its_pat()).promote(["412"], actor="U1")

    assert [r.ok for r in results] == [True], results
    assert seen["tracker"] == "the-projects-azure-pat", (
        "the ticket writes authenticated with the deployment's own credential")
    assert seen["board"] == "the-projects-azure-pat", (
        "the board placement authenticated with the deployment's own credential")
    assert "ghp_the_deployments_github_secret" not in (seen["tracker"], seen["board"])


def test_a_project_that_names_no_variable_still_gets_the_deployments_credential(monkeypatch):
    """The positive twin, and the whole reason this is safe to land: `tracker_token_for` falls back
    to `tracker_token()` when the registry row names nothing. Every GitHub project that exists today
    behaves byte for byte as it did — a per-project resolver that CHANGED them would be a migration
    wearing the word "fix"."""
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "the-deployments-token")
    monkeypatch.delenv("OPENFACTORY_TRACKER_TOKEN", raising=False)

    seen: dict = {}
    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda project, *, token=None, token_provider=None:
                            seen.update(tracker=token) or object())

    project = Project(name="gh", repo_path="/tmp/gh",
                      tracker=ProviderRef(kind="github", repo="Org/repo"),
                      product=ProductConfig(docs_repo="Org/docs", admins=["U1"]))
    _module_for(project)._tracker()

    assert seen["tracker"] == "the-deployments-token"


def test_no_reader_in_the_product_package_resolves_a_credential_process_wide():
    """A LITERAL IS A DEFECT THAT LOOKS LIKE CODE, on the credential axis this time. The two call
    sites above were written by copying each other, and the tenth would be too — so the guard is
    over the source rather than over one more behaviour.

    `tracker_token`/`forge_token` are the process-wide pair; `tracker_token_for`/`forge_token_for`
    take the project. The `_for` suffix is what makes the substring test below discriminate, so the
    check is on the imported NAME, not on a grep."""
    import ast
    import pathlib

    package = pathlib.Path(inspect.getfile(resolve_product_link)).parent
    offenders = []
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [f"{path.name}:{node.lineno}: imports the process-wide {alias.name}"
                      for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                      for alias in node.names
                      if (node.module or "") == "openfactory.credentials"
                      and alias.name in ("tracker_token", "forge_token")]
    assert offenders == [], "\n".join(offenders)
