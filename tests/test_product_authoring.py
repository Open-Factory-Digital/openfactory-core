"""Writing requirements and issues.

The property that matters most here is the ROUND TRIP: what this module writes must be readable by
the parser that loads the corpus. If the two ever drift, every requirement the role authors becomes
a file full of findings — and it would look fine to a human reading the markdown, which is the worst
kind of bug to have.
"""

from __future__ import annotations

import logging
import subprocess

import pytest

from openfactory.product.authoring import (
    branch_for,
    issue_body,
    next_number,
    propose_requirement,
    render_requirement,
    slugify,
)
from openfactory.product.corpus import ACCEPTED, Requirement, load_corpus
from openfactory.product.role import Conflict, IssueDraft, RequirementDraft
from openfactory.product.voice import jargon_in

DOCS = "AcmeCorp/acme-books-documentation"


def _draft(**kw) -> RequirementDraft:
    kw.setdefault("title", "Editable reconciled statements")
    kw.setdefault("why", "accountants need to fix a typo after reconciling")
    kw.setdefault("must_be_true", ["an admin can edit a reconciled statement"])
    return RequirementDraft(**kw)


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture(autouse=True)
def _no_merge_patience(monkeypatch):
    """The merge read-back waits, because Azure DevOps completes asynchronously (measured: +2.4s).
    A test must not buy that patience in wall-clock seconds — and the constants are read at CALL
    time precisely so this fixture works at all; as default arguments they would be bound at `def`
    and silently ignore it."""
    import openfactory.product.authoring as authoring

    monkeypatch.setattr(authoring, "_MERGE_DELAY", 0)


class _Forge:
    """A `ForgeAdapter` stand-in for EVERY call this module makes over the DOCUMENTATION repo.

    ONE FAKE NOW, WHERE THERE WERE TWO (#95). The reads — which `req/*` branches exist, and whether
    this one was ever proposed — went through the port already; opening the pull request, merging it
    and reading its state back were a `gh` subprocess, because `open_pr`/`merge_pr`/`pr_status` were
    bound to the adapter's OWN repository and the documentation is a different one. All three take a
    repository now, so the whole ceremony is one interface and this fake can hold the pull request's
    STATE instead of pattern-matching argv.

    `None` is a first-class answer on both reads — "I could not read", as distinct from `[]`/`""`,
    "I read and there is nothing" — and the writer refuses on it rather than minting a number or
    opening a second pull request for work already proposed.
    """

    def __init__(self, branches=(), *, proposed=None, branches_unreadable=False,
                 prs_unreadable=False, opens=True, merges=True, deletes=True):
        self.branches = list(branches)
        self.proposed = dict(proposed or {})
        self.branches_unreadable = branches_unreadable
        self.prs_unreadable = prs_unreadable
        #: `False` = the forge REFUSES to open one, the way `gh pr create` failing does
        self.opens = opens
        #: `False` = the merge is accepted and never lands — a protected branch, or an auto-merge
        #: armed and never fired. The insidious shape: no error, and nothing in the base.
        self.merges = merges
        self.deletes = deletes
        self.asked: list[tuple[str, str]] = []
        self.acted: list[tuple[str, str, str]] = []
        self.bodies: list[str] = []
        self.state: dict[str, str] = {}
        self._next = 1

    def list_branches(self, repo: str = "", *, prefix: str = ""):
        self.asked.append(("list_branches", repo))
        if self.branches_unreadable:
            return None
        return [b for b in self.branches if b.startswith(prefix)]

    def pr_for_head(self, head: str, *, repo: str = ""):
        self.asked.append(("pr_for_head", repo))
        if self.prs_unreadable:
            return None
        return self.proposed.get(head, "")

    def open_pr(self, *, head: str, base: str, title: str, body: str, repo: str = ""):
        self.acted.append(("open_pr", repo, head))
        self.bodies.append(body)
        if not self.opens:
            raise RuntimeError("the forge refused to open a pull request")
        url = f"https://forge/{repo}/pull/{self._next}"
        self._next += 1
        self.proposed[head] = url
        self.state[url] = "open"
        self.branches.append(head)
        return url

    def pr_status(self, *, pr: str, repo: str = ""):
        self.acted.append(("pr_status", repo, pr))
        return self.state.get(pr, "open")

    def merge_pr(self, *, pr: str, repo: str = ""):
        self.acted.append(("merge_pr", repo, pr))
        if self.merges:
            self.state[pr] = "merged"

    def delete_branch(self, name: str, *, repo: str = ""):
        self.acted.append(("delete_branch", repo, name))
        if not self.deletes:
            return False
        self.branches = [b for b in self.branches if b != name]
        return True

    def did(self, what: str) -> list[tuple[str, str, str]]:
        return [row for row in self.acted if row[0] == what]


# ── numbering ───────────────────────────────────────────────────────────────────────────────────

def test_numbers_are_never_reused_even_when_a_requirement_was_retired():
    """Reusing a retired number silently re-points every citation of the old requirement at a new
    and unrelated one — the sort of corruption nobody notices until a decision is argued from the
    wrong document."""
    from openfactory.product.corpus import Corpus

    corpus = Corpus(requirements=[
        Requirement(number=1, slug="a", path="0001-a.md", status="superseded", superseded_by=2),
        Requirement(number=2, slug="b", path="0002-b.md", status=ACCEPTED),
    ])
    assert next_number(corpus) == 3


def test_the_first_requirement_is_one():
    from openfactory.product.corpus import Corpus

    assert next_number(Corpus()) == 1


@pytest.mark.parametrize("title,slug", [
    ("Editable reconciled statements", "editable-reconciled-statements"),
    ("  Weird   ✱ punctuation!! ", "weird-punctuation"),
    ("", "requirement"),
    ("—", "requirement"),
])
def test_slugs_stay_filesystem_safe(title, slug):
    assert slugify(title) == slug


def test_a_branch_name_is_deterministic_so_a_retry_finds_its_own_work():
    assert branch_for(12, "Editable reconciled statements") == branch_for(12, "Editable reconciled statements")
    assert branch_for(12, "x").startswith("req/0012-")


# ── the round trip ──────────────────────────────────────────────────────────────────────────────

def test_what_we_WRITE_is_readable_by_what_we_READ(tmp_path):
    """The round trip. If the writer and the parser drift, every authored requirement becomes a file
    full of findings while looking perfectly fine to a human reading the markdown."""
    draft = _draft(out_of_scope=["bulk editing"], affects=["AcmeCorp/acme-books"])
    (tmp_path / "0012-editable-reconciled-statements.md").write_text(
        render_requirement(draft, number=12, asked_by="Alice", date="2026-07-26"))

    corpus = load_corpus(tmp_path)
    req = corpus.by_number(12)
    assert req is not None
    assert req.title == "Editable reconciled statements"
    assert req.status == "proposed"
    assert req.asked_by == "Alice" and req.date == "2026-07-26"
    assert req.affects == ["AcmeCorp/acme-books"]
    assert corpus.errors == []


def test_a_freshly_written_requirement_is_PROPOSED_not_accepted():
    """The role proposes; merging the PR is the sign-off. Writing `accepted` here would let it
    grant its own approval."""
    assert "**Status:** proposed" in render_requirement(_draft(), number=1)


def test_supersession_is_written_in_a_form_the_parser_reads_back(tmp_path):
    (tmp_path / "0002-new.md").write_text(
        render_requirement(_draft(supersedes=[1]), number=2))
    assert load_corpus(tmp_path).by_number(2).supersedes == [1]


def test_a_written_requirement_records_no_decisions_yet(tmp_path):
    """It ships the empty table, and the rot detector must not mistake the header for a write-back
    or every fresh requirement would look maintained."""
    (tmp_path / "0001-x.md").write_text(render_requirement(_draft(), number=1))
    assert load_corpus(tmp_path).by_number(1).has_decisions is False


def test_conflicts_are_recorded_IN_the_document_not_only_in_chat():
    """A contradiction found while drafting and then lost in a Slack scrollback is one that gets
    rediscovered the expensive way."""
    body = render_requirement(
        _draft(conflicts=[Conflict(requirement=7, kind="contradicts",
                                   explanation="REQ-0007 says reconciled statements are immutable")]),
        number=12)
    assert "Conflicts raised while drafting" in body
    assert "REQ-0007" in body and "immutable" in body


def test_open_questions_survive_into_the_document():
    body = render_requirement(_draft(questions=["who counts as an admin?"]), number=1)
    assert "who counts as an admin?" in body


def test_missing_provenance_is_marked_rather_than_left_blank(tmp_path):
    """"unrecorded" is a fact; an empty line looks like nobody filled the template in."""
    (tmp_path / "0001-x.md").write_text(render_requirement(_draft(), number=1))
    assert "unrecorded" in (tmp_path / "0001-x.md").read_text()


# ── issues cite their requirement ───────────────────────────────────────────────────────────────

def test_an_issue_cites_the_requirement_the_path_and_the_commit():
    """The citation is what makes an issue a unit of EXECUTION rather than a second, drifting copy
    of the requirement."""
    body = issue_body(
        IssueDraft(title="t", objective="build the queue", acceptance_criteria=["it lists them"],
                   cites=12),
        requirement_path="requirements/0012-editable.md", docs_repo=DOCS,
        commit="abcdef1234567890")
    assert "REQ-0012" in body
    assert "requirements/0012-editable.md" in body
    assert "abcdef123456" in body
    assert DOCS in body
    assert "belongs in the document first" in body


def test_an_issue_without_a_citation_still_names_the_gap():
    body = issue_body(IssueDraft(title="t", objective="o"), requirement_path="p", docs_repo=DOCS)
    assert "a requirement" in body


# ── the pull request ────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def origin(tmp_path):
    src = tmp_path / "docs-origin"
    src.mkdir()
    _git("init", "-q", "-b", "main", cwd=src)
    _git("config", "user.email", "t@t", cwd=src)
    _git("config", "user.name", "t", cwd=src)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=src)
    (src / "requirements").mkdir()
    (src / "requirements" / ".keep").write_text("")
    _git("add", "-A", cwd=src)
    _git("commit", "-qm", "seed", cwd=src)
    return src


def test_a_proposal_commits_the_file_and_opens_a_pull_request(origin):
    forge = _Forge()
    res = propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(),
                              number=12, asked_by="Alice", date="2026-07-26", forge=forge)
    assert res.ok and res.url == f"https://forge/{DOCS}/pull/1"
    assert res.ref == branch_for(12, _draft().title)

    # the branch really exists on the origin, with the file on it
    out = subprocess.run(["git", "show", f"{res.ref}:requirements/"
                          f"0012-editable-reconciled-statements.md"],
                         cwd=origin, capture_output=True, text=True, check=True)
    assert "REQ-0012" in out.stdout and "Alice" in out.stdout

    created = forge.did("open_pr")
    assert created and created[0][1] == DOCS, (
        "the review request was opened against something other than the documentation repository")


def test_the_proposal_LANDS_and_the_branch_it_landed_from_is_removed(origin):
    """MERGING IS MECHANISM (ADR-0032) — and the `--delete-branch` half is not tidiness.

    `gh pr merge --squash --delete-branch` did both in one command; the port does neither
    implicitly, so a straight translation would have left every landed `req/*` branch on the
    remote. That branch is not litter: `_requirement_branches` reads it as a proposal still in
    flight and it is an input to the NUMBER the next requirement gets, and the hourly sweep
    re-examines it for ever. `req/0002` was found in exactly that state on the live client
    repository, outliving its squash-merged pull request."""
    forge = _Forge()
    res = propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(), number=12,
                              forge=forge)

    assert res.merged is True
    assert [row[1] for row in forge.did("merge_pr")] == [DOCS]
    assert [(row[1], row[2]) for row in forge.did("delete_branch")] == [(DOCS, res.ref)]
    assert res.ref not in forge.branches, "the landed branch is still on the remote"


def test_a_merge_that_never_LANDED_is_not_announced_as_landed_and_keeps_its_branch(origin):
    """A protected docs branch, or an auto-merge armed and never fired: the call is accepted and
    nothing reaches the base. Reading the state back is the difference between "we merged it" and
    "we ran a command" — and the branch must SURVIVE, because deleting it on an assumed merge
    deletes the requirement."""
    forge = _Forge(merges=False)
    res = propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(), number=12,
                              forge=forge)

    assert res.ok is True and res.merged is False
    assert forge.did("delete_branch") == [], "a branch was deleted on a merge that did not happen"


def test_a_retry_finds_its_own_pull_request_instead_of_opening_a_second(origin):
    """Slack retries, a worker replaced mid-operation, a signal delivered twice — each would
    otherwise leave a second PR proposing the same requirement."""
    forge = _Forge(proposed={branch_for(12, _draft().title): "https://forge/x/pull/1"})
    res = propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(),
                              number=12, forge=forge)
    assert res.ok and res.existed is True
    assert forge.did("open_pr") == [], "a second pull request was opened"


def test_the_conflicts_lead_the_pull_request_body(origin):
    """They are the reason a reviewer might reject the proposal outright, so they go first."""
    forge = _Forge()
    propose_requirement(
        docs_repo=DOCS, clone_url=str(origin), number=13, forge=forge,
        draft=_draft(conflicts=[Conflict(requirement=7, kind="contradicts",
                                         explanation="REQ-0007 says immutable")]))
    body = forge.bodies[0]
    assert body.index("Conflicts") < body.index("What must be true")
    assert "does **not** start any work" in body


def test_an_unreachable_docs_repo_reports_instead_of_raising(tmp_path):
    res = propose_requirement(docs_repo=DOCS, clone_url=str(tmp_path / "nope"),
                              draft=_draft(), number=1, forge=_Forge())
    assert res.ok is False and "could not clone" in res.detail


def test_a_pushed_branch_whose_PR_failed_says_the_work_is_not_lost(origin):
    """The most confusing possible failure: the branch is on the remote but there is no PR.

    TWO AUDIENCES, TWO PLACES. This test used to require the branch name and "open it by hand" IN
    THE DETAIL — and `detail` is what the CLIENT reads. That sentence duly reached somebody who runs
    an accounting firm: English, a branch name, and an instruction they cannot carry out.

    The operator's half did not go away, it moved to where operators look: `ref` carries the branch
    and `OPENFACTORY_PRODUCT_PR_FAILED` carries branch, base and repo into the log. What the client gets is
    that nothing was lost and the team has it.
    """
    res = propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(),
                              number=14, forge=_Forge(opens=False))
    assert res.ok is False
    assert res.ref, "the branch is not recoverable by the team"
    assert "req/0014" in res.ref
    assert "req/0014" not in res.detail, "the branch name reached the client's sentence"
    assert "by hand" not in res.detail, "the client is told to open a pull request themselves"
    assert "Nada se perdeu" in res.detail


# ── the two reads that moved to the port (#95/#97) ──────────────────────────────────────────────

def test_the_two_QUESTIONS_go_to_the_port_and_name_the_DOCUMENTATION_repository(origin):
    """REACHABILITY, and the repository argument is the whole reason these methods could serve.

    Every other read on the forge port answers about `self.repo` — the repository the adapter was
    built for, which on this path is the SOURCE code. The documentation is a different repository,
    so `list_branches(repo)` and `pr_for_head(head, repo=)` take one, exactly as `clone_url` does.
    An implementation that ignored the argument would answer confidently about the wrong repo."""
    forge = _Forge()
    propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(), number=16,
                        forge=forge)

    assert ("list_branches", DOCS) in forge.asked
    assert ("pr_for_head", DOCS) in forge.asked


def test_a_retry_CONVERGES_on_its_own_branch_even_with_a_rival_above_it(origin):
    """FOUND BY THE LIVE DRIVE on a production client's Azure DevOps project (`fx-ado`),
    2026-08-06, and it is the exact
    corruption the minting paragraph exists to prevent — produced by the retry it exists to make
    idempotent.

    Two proposals are pushed and neither lands: `req/0001-<ours>` and `req/0002-<a rival>`. The base
    corpus still mints 1, because nothing reached it. Re-proposing the FIRST draft then took the
    rival-bump arm — `own` was `[1]`, `max(own + [1]) == 1`, so "adopt" was a no-op and control fell
    through — and minted `req/0003-<ours>`: a third branch and a third number for a text that
    already had one. It compounds one per attempt (0001, 0003, 0005…), each a live file under the
    same title.

    Invisible on GitHub only because the pull-request lookup returns first. The one state where it
    does not is a branch pushed with NO pull request — which is what a `pr create` failure leaves
    (production lived there for weeks) and what a forge whose PR ceremony the port cannot reach yet
    is in permanently."""
    ours, rival = "req/0001-editable-reconciled-statements", "req/0002-outra-coisa"
    forge = _Forge(("main", ours, rival))

    res = propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(), number=1,
                              forge=forge)

    assert res.number == 1, f"a retry minted a second number for one draft: {res.ref}"
    assert res.ref == ours, f"a retry pushed a third branch for one draft: {res.ref}"


def test_a_requirement_already_on_the_remote_with_no_request_SAYS_that(origin, caplog):
    """The second half of the same live measurement. Having converged on its own branch, the retry
    used to clone and push over it — and git rejects that as a non-fast-forward, so the client's
    entire reply became `could not push req/0003-…: ! [rejected]`.

    The cosmetic half is that the sentence is English machinery aimed at somebody who runs an
    accounting firm. The load-bearing half is that `ref` and `number` came back EMPTY: the act that
    DID write requirement 3 reported having minted nothing, which is the one thing `WriteResult`'s
    `number` field exists to prevent."""
    ours = "req/0001-editable-reconciled-statements"
    with caplog.at_level(logging.WARNING, logger="openfactory.product"):
        res = propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(), number=1,
                                  forge=_Forge(("main", ours)))

    assert res.ok is False
    assert res.ref == ours and res.number == 1, "the write reported minting nothing"
    assert "OPENFACTORY_PRODUCT_ALREADY_PUSHED" in caplog.text
    assert "guardado em segurança" in res.detail
    assert jargon_in(res.detail) == [], res.detail
    assert "rejected" not in res.detail and "push" not in res.detail

    # AND IT PROMISES NOTHING NOBODY IS DOING. The sentence here was copied from the `pr create`
    # failure and said *"o time foi avisado e conclui isso"* — two claims, both false from this
    # branch. Nothing on this path opens an impediment (`OPENFACTORY_PRODUCT_ALREADY_PUSHED` is a log
    # line, and the seams that reach a person are `_could_not` and `_tell_the_factory`, neither of
    # which is here), and the sweep that would finish it — `land_open_proposals` — runs on `gh` and
    # refuses on every other forge. So on the deployment where this answer is PERMANENT, the client
    # is told once a request that somebody has been alerted and is finishing it, forever.
    #
    # That is this codebase's own named defect, quoted in `product/board.py`: "the client was told
    # a colleague had been alerted who did not exist." Asserted here rather than trusted, because
    # the sentence reads perfectly well either way.
    assert "avisado" not in res.detail, (
        "the client is told somebody was alerted, and nothing on this path alerts anybody")
    assert "me peça de novo" in res.detail, "a stall with no way out is a silent wait"


def test_a_branch_list_that_could_NOT_be_read_mints_NOTHING(origin, caplog):
    """**`None` IS NOT `[]`, ON THE ONE DECISION THIS MODULE CANNOT TAKE BACK.**

    The proposal branches are how a number is minted against work that is pushed but not landed. An
    empty answer there means "nothing else claims a number"; an unreadable one means nothing at all,
    and acting on it files a SECOND requirement under an identity the first one already has — two
    files claiming NNNN, the citation corruption `next_number` warns about. Every other failure here
    is repairable by a later sweep; a number is in the filename, in the card that cites it and in the
    supersede stamp.

    So nothing is cloned, nothing is committed and nothing is pushed — asserted against the origin,
    not against the return value."""
    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        res = propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(), number=17,
                                  forge=_Forge(branches_unreadable=True))

    assert res.ok is False
    assert res.ref == "" and res.number == 0
    branches = subprocess.run(["git", "branch", "--list", "req/*"], cwd=origin,
                              capture_output=True, text=True, check=True).stdout
    assert branches.strip() == "", "a requirement was written from a board nobody could read"
    assert "OPENFACTORY_PRODUCT_BRANCHES_UNREADABLE" in caplog.text
    assert "não registrei nada" in res.detail
    assert jargon_in(res.detail) == [], res.detail


def test_an_unreadable_PRIOR_PROPOSAL_never_opens_a_second_one(origin, caplog):
    """The other `None` arm, and the one the port's own docstring names: a caller that writes
    `if not pr: create_one()` puts "there is none" and "I could not ask" back together and files the
    duplicate on a transient error. The check is `is None`."""
    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        res = propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(), number=18,
                                  forge=_Forge(prs_unreadable=True))

    assert res.ok is False
    assert "OPENFACTORY_PRODUCT_PRIOR_PROPOSAL_UNREADABLE" in caplog.text
    assert jargon_in(res.detail) == [], res.detail


def test_a_caller_that_handed_NO_forge_has_not_READ_anything(origin, caplog):
    """**A MISSING FORGE IS AN UNREADABLE ANSWER, NOT AN EMPTY ONE**, and that arm had no guard.

    Both helpers open with `if forge is None: return None`, and the reason is stated in their
    docstrings: a caller that offered no adapter cannot have asked anybody anything. Production
    always passes one — two mutations prove that — so this arm is the defence for the THIRD call
    site somebody adds next month, which is exactly the shape that keeps landing here. Collapsed to
    `[]`/`""` it does not fail: it mints a requirement number against a board nobody read, and that
    is the single decision in this module no later sweep can repair.

    The behavioural half first, then the two helpers directly with their positive twins — the
    behavioural drive can only reach the branch half, because one absent forge answers both."""
    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        res = propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(),
                                  number=19)

    assert res.ok is False and res.number == 0
    assert "OPENFACTORY_PRODUCT_BRANCHES_UNREADABLE" in caplog.text, (
        "a caller with no forge minted a number against a board it never read")
    assert jargon_in(res.detail) == [], res.detail

    from openfactory.product.authoring import _already_proposed, _requirement_branches

    assert _requirement_branches(None, DOCS) is None
    assert _already_proposed(None, DOCS, "req/0001-x") is None

    readable = _Forge(("main", "req/0007-alguma-coisa"), proposed={"req/0009-x": "u"})
    assert _requirement_branches(readable, DOCS) == [(7, "alguma-coisa")]
    assert _already_proposed(readable, DOCS, "req/0001-x") == "", (
        "a forge that ANSWERED 'no pull request' was reported as unreadable")


def test_the_BASELINE_asks_the_same_question_and_refuses_the_same_unreadable_answer(origin,
                                                                                   caplog):
    """The brownfield first pass carries the same `None` arm, and the duplicate it prevents is the
    most expensive one this module can file: a second baseline is forty candidate requirements
    proposed twice, at the exact moment whose design argument is that a team asked to review forty
    pull requests reviews none.

    ITS FIRST BEHAVIOURAL TEST. Everything asserted about `propose_baseline` until now was the
    SOURCE TEXT of the module — "propose_baseline(" appears in module.py — which cannot see what
    the function does with an answer it did not get."""
    from openfactory.product.authoring import propose_baseline

    files = {"requirements/0001-observed.md": "# REQ-0001 — observado\n"}
    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        refused = propose_baseline(docs_repo=DOCS, clone_url=str(origin), files=files,
                                   product="books", observations=1, covered=["fecho"],
                                   forge=_Forge(prs_unreadable=True))

    assert refused.ok is False
    assert "OPENFACTORY_PRODUCT_PRIOR_PROPOSAL_UNREADABLE" in caplog.text
    assert jargon_in(refused.detail) == [], refused.detail

    # the positive twin, or the refusal above would be indistinguishable from a function that
    # never writes at all
    landed = propose_baseline(docs_repo=DOCS, clone_url=str(origin), files=files,
                              product="books", observations=1, covered=["fecho"],
                              forge=_Forge())
    assert landed.ok and landed.ref == "product/baseline"
    assert landed.url.endswith("/pull/1")


def test_on_a_NON_github_forge_the_WHOLE_ceremony_happens(origin):
    """**THE HEADLINE OF #95.** Every pull-request call in this module used to be `gh`, which
    refuses on a deployment that is not GitHub's — correctly, because the token it would carry is
    that project's Microsoft credential. So an Azure Repos client got the requirement written and
    pushed, and NO review request, permanently: the ceremony did not port when the vendor changed,
    it vanished.

    Nothing here branches on a vendor any more. `forge_kind="azure_devops"` is accepted and
    ignored, the forge adapter is the whole mechanism, and every act lands: the number is minted
    against the unlanded `req/0002-*` branch, the file is committed and pushed, the pull request
    opens against the DOCUMENTATION repository, it merges, and the branch it landed from is gone.

    Proven live, not only here: a production client's Azure DevOps project, PR 14, opened by an
    adapter configured for `fx-ado` into `fx-dsk-context`, merged at +2.4s, branch deleted
    (2026-08-06)."""
    forge = _Forge(("main", "req/0002-relatorio-mensal"))

    res = propose_requirement(docs_repo=DOCS, clone_url=str(origin),
                              draft=_draft(title="Exportar extratos"), number=2,
                              forge_kind="azure_devops", token="an-azure-pat", forge=forge)

    assert res.ref == "req/0003-exportar-extratos", (
        f"the unlanded branch was invisible again: {res.ref}")
    out = subprocess.run(["git", "show", f"{res.ref}:requirements/0003-exportar-extratos.md"],
                         cwd=origin, capture_output=True, text=True, check=True)
    assert "REQ-0003" in out.stdout, "the requirement never reached the repository"

    assert res.ok is True, "the review request was refused on a vendor the port now covers"
    assert res.url == f"https://forge/{DOCS}/pull/1"
    assert res.merged is True, "the role still cannot read its own requirement"
    assert res.number == 3, "the number this write minted was not reported back"
    assert [row[1] for row in forge.did("open_pr")] == [DOCS], (
        "the review request was aimed at something other than the documentation repository")


def test_a_review_request_that_could_NOT_open_is_never_reported_as_opened(origin, caplog):
    """THE HONESTY THAT HAD TO SURVIVE THE PORT. The old `gh` runner returned "" and the caller said
    the text was safe and the request was missing — the refusal was wrong about the vendor and right
    about everything else. `open_pr` RAISES, on both providers, and a raise that escaped here would
    throw away the half that worked: the requirement is already committed and pushed.

    So the exception becomes "", the client is told nothing was lost, and `ok=False` carries the
    branch and the number. What must never happen is the opposite: `ok=True` with no URL."""
    forge = _Forge(opens=False)
    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        res = propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(),
                                  number=20, forge=forge)

    assert res.ok is False and res.url == ""
    assert res.ref == branch_for(20, _draft().title) and res.number == 20
    assert "OPENFACTORY_PRODUCT_PR_CREATE_FAILED" in caplog.text
    assert "OPENFACTORY_PRODUCT_PR_FAILED" in caplog.text
    assert forge.did("merge_pr") == [], "a pull request that never opened was merged"
    assert forge.did("delete_branch") == [], "the only copy of the requirement was deleted"
    assert "Nada se perdeu" in res.detail
    assert jargon_in(res.detail) == [], res.detail


def test_a_custom_requirements_dir_is_honoured(origin):
    res = propose_requirement(docs_repo=DOCS, clone_url=str(origin), draft=_draft(), number=15,
                              requirements_dir="specs/", forge=_Forge())
    assert res.ok
    out = subprocess.run(["git", "ls-tree", "-r", "--name-only", res.ref],
                         cwd=origin, capture_output=True, text=True, check=True)
    assert "specs/0015-editable-reconciled-statements.md" in out.stdout


# ── the identity is CARRIED, never assumed (found by CI, 2026-08-05) ────────────────────────────

def test_a_commit_works_on_a_machine_with_no_git_identity_at_all(tmp_path, monkeypatch):
    """THE PRODUCTION BUG. This module ran `git commit` on the ambient config — a bet that
    whoever built the worker image happened to run `git config --global user.email`. Where that
    bet loses, git refuses with "Please tell me who you are" and EVERY requirement the product
    role writes fails, on a container that is otherwise perfectly healthy.

    A clean machine is exactly what a fresh deployment's container is, which is why the
    platform's own CI — a runner with no identity — is what surfaced it."""
    import subprocess

    from openfactory.product.authoring import _git

    # no global, no system config: the shape of a container nobody ran `git config` in
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "nonexistent-global"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(tmp_path / "nonexistent-system"))
    monkeypatch.setenv("OPENFACTORY_BOT_NAME", "SDLC Bot")
    monkeypatch.setenv("OPENFACTORY_BOT_EMAIL", "openfactory-bot@example.test")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=True)
    (repo / "a.md").write_text("hello\n")

    _git(["add", "--", "a.md"], cwd=repo)
    rc, out = _git(["commit", "-m", "REQ-0001: a requirement"], cwd=repo)

    assert rc == 0, f"the commit was refused on a machine with no identity:\n{out}"
    author = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%an <%ae>"],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert author == "SDLC Bot <openfactory-bot@example.test>", (
        "the commit landed under whatever identity the machine happened to have, not the bot's")
