"""A requirement's whole life happens in the channel — ADR-0032.

THE PRODUCT OWNER ASKED THE QUESTION THAT FOUND THIS: *"isn't she the one who should be doing all
of this? we cannot be doing it from outside… shouldn't she translate it into business language and
do the merge herself?"*

That was right on every count. The lifecycle stopped dead after the proposal:

  | step                        | who did it before |
  | write the requirement       | her               |
  | open the review request     | her (once `gh` had credentials at all) |
  | MERGE it                    | NOBODY — no code merged the docs repo |
  | `proposed` -> `accepted`    | NOBODY — the status was read in four places, written by none |

So a product sold as needing no developer required TWO developer operations per requirement — merge
a pull request, then hand-edit a field in a markdown file — on a business artefact. And the client
was sent a GitHub link to a diff they cannot judge.

Worse, and invisible until it bit: an unmerged requirement is one THE ROLE CANNOT SEE. She reads the
docs branch. Asked about a requirement she had written minutes earlier she answered "do meu lado ela
está vazia" — and she was right.

MERGING IS NOT ACCEPTING. That is what unlocks it: the merge is mechanism and can be automatic; the
promise is created by a person confirming, in the channel, in their own words.

FIXTURE DISCIPLINE (the lesson of findings 2/5): every file fed to the status writers here is
produced by `render_requirement` ITSELF, or is a hand-edit the corpus parser demonstrably reads.
The old fixtures fed a bare `status:` front-matter no production writer ever emitted — so the
accept path stayed green for weeks while it flipped nothing on any real file.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from openfactory.product.authoring import (
    WriteResult,
    _fold_replacement_conflicts,
    _mark_superseded,
    _merged_now,
    _set_status_accepted,
    branch_for,
    land_open_proposals,
    propose_requirement,
    render_requirement,
    slugify,
)
from openfactory.product.corpus import _status_of, parse_requirement
from openfactory.product.intents import match_intent
from openfactory.product.role import Conflict, RequirementDraft
from openfactory.product.voice import accept_confirmation, accepted, written_up


@pytest.fixture(autouse=True)
def _no_merge_patience(monkeypatch):
    """The merge read-back waits up to ~10s, because Azure DevOps completes asynchronously
    (measured live: +2.4s). Only the genuinely-unmerged cases pay it — and there are two here, so
    without this the file spends twenty real seconds proving nothing."""
    import openfactory.product.authoring as authoring

    monkeypatch.setattr(authoring, "_MERGE_DELAY", 0)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    """The production writers commit inside their own clone; a bare CI box has no global git
    identity, and these tests must not depend on the machine they run on."""
    for key, value in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"),
                       ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(key, value)


def _draft(**kw) -> RequirementDraft:
    kw.setdefault("title", "Pacote de fecho")
    kw.setdefault("why", "o cliente precisa fechar o mês")
    kw.setdefault("must_be_true", ["o fecho gera o pacote completo"])
    return RequirementDraft(**kw)


def _rendered(number: int = 1, *, asked_by: str = "", **kw) -> str:
    """A requirement EXACTLY as production writes one — bullet fields, never front-matter."""
    return render_requirement(_draft(**kw), number=number, asked_by=asked_by, date="")


# ── merging is mechanism ───────────────────────────────────────────────────────────────────────
class _MergeReads:
    """A forge that answers a scripted sequence of `pr_status` reads, so the WAIT can be tested."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.reads = 0

    def pr_status(self, *, pr: str, repo: str = ""):
        self.reads += 1
        answer = self.answers[min(self.reads - 1, len(self.answers) - 1)]
        if answer is None:
            raise RuntimeError("the forge could not be reached")
        return answer


def test_a_merge_is_VERIFIED_not_assumed():
    """`merge_pr` returns None on a real merge and on an armed-but-unfired auto-merge alike, so its
    return is no evidence. Announcing a merge that did not happen would be the same defect as
    announcing a write that did not happen — and ours, not the agent's.

    THREE ANSWERS, NOT TWO. `None` is "I could not read it back", which is neither "landed" nor
    "still open"; the caller reports it as not landed AND logs it as unconfirmed, because a merge
    announced on no evidence is the thing this read exists to prevent."""
    assert _merged_now(_MergeReads("merged"), "a/b", "u", delay=0) is True
    assert _merged_now(_MergeReads("open"), "a/b", "u", attempts=1, delay=0) is False
    assert _merged_now(_MergeReads("closed"), "a/b", "u", delay=0) is False
    assert _merged_now(_MergeReads(None), "a/b", "u", attempts=2, delay=0) is None, \
        "an unreadable answer was collapsed into 'not merged'"


def test_the_read_back_WAITS_because_one_vendor_completes_asynchronously():
    """MEASURED, THROUGH THE REAL ADAPTER (2026-08-06): `AzureReposForge.merge_pr` returned in 0.8s,
    the pull request read `open` at +1.0s and `merged` at +2.4s. Azure DevOps completes a PR
    asynchronously by design — the arming PATCH answers `active`.

    A single read would therefore call an honest merge a failure, and this module's `merged` field
    is client-visible: it is what makes the channel say the requirement is not where the role can
    read it yet. One vendor's timing must not become another vendor's wrong sentence.

    It stops the moment the answer is not `open`, so the common case costs one round trip."""
    forge = _MergeReads("open", "open", "merged")
    assert _merged_now(forge, "a/b", "u", delay=0) is True
    assert forge.reads == 3

    instant = _MergeReads("merged")
    assert _merged_now(instant, "a/b", "u", delay=0) is True
    assert instant.reads == 1, "a merge that was already visible was polled again"

    abandoned = _MergeReads("closed", "merged")
    assert _merged_now(abandoned, "a/b", "u", delay=0) is False
    assert abandoned.reads == 1, "the wait went on after somebody abandoned the pull request"


def test_the_result_carries_whether_it_LANDED():
    assert WriteResult(ok=True).merged is False, "the safe default is 'not landed'"
    assert WriteResult(ok=True, merged=True).merged is True


@pytest.mark.parametrize("lang", ["pt-BR", "en"])
def test_the_two_outcomes_read_differently_and_neither_carries_a_link(lang):
    landed = written_up(title="t", url="https://x/pull/2", number=1, language=lang, merged=True)
    open_ = written_up(title="t", url="https://x/pull/2", number=1, language=lang, merged=False)

    assert landed != open_
    for text in (landed, open_):
        assert "http" not in text, f"a code-forge link reached the client: {text}"


def test_the_unmerged_message_admits_she_cannot_read_it():
    """The fact that was invisible. If she cannot see it, saying so beats answering about it."""
    text = written_up(title="t", url="u", number=1, language="pt-BR", merged=False)
    assert "não consigo lê-lo" in text, text


# ── accepting is the promise ───────────────────────────────────────────────────────────────────
def test_accepting_flips_the_status_of_a_file_production_actually_writes():
    """Driven against `render_requirement`'s own output, and read back with the corpus parser —
    the writer and the reader can no longer drift apart unnoticed (findings 2/5)."""
    updated, outcome = _set_status_accepted(_rendered(1), accepted_by="<@U1>", day="2026-07-30")

    assert outcome == "flipped"
    req, findings = parse_requirement(Path("0001-pacote-de-fecho.md"), updated)
    assert req is not None and req.status == "accepted"
    assert req.is_promise, "flipped, yet the factory still would not defend it"
    assert "U1" in req.asked_by, "who agreed is not readable back by the parser"
    assert req.date == "2026-07-30"
    assert not [f for f in findings if f.code in ("no-asker", "no-date")], (
        "the inserted provenance is invisible to corpus._field_re — the old bare `asked_by:` bug")
    assert "o fecho gera o pacote completo" in updated, "the body was disturbed"


@pytest.mark.parametrize("status_line", [
    "- **Status:** proposed",
    "* **Status:** proposed",      # hand-edited: a different bullet
    "- Status: proposed",          # hand-edited: the bold markers dropped
])
def test_every_status_line_the_PARSER_tolerates_can_be_flipped(status_line):
    """Finding 55's principle, on the accept side: `corpus._field_re` deliberately tolerates hand
    edits, so the writers must read with the same eyes — the shared regex, never a stricter copy."""
    text = _rendered(1).replace("- **Status:** proposed", status_line)

    updated, outcome = _set_status_accepted(text, accepted_by="<@U1>", day="2026-07-30")

    assert outcome == "flipped", f"the writer refused a line the parser reads: {status_line!r}"
    assert _status_of(updated, "p")[0] == "accepted"


def test_a_file_whose_status_cannot_be_found_is_an_ERROR_never_already_agreed():
    """THE poison half of findings 2/5: `changed=False` used to be reported as "esse requisito já
    estava acordado" — the live client was told a promise existed while the file stayed
    `proposed`. Unflippable must be unmistakably a failure."""
    text = "# REQ-0001 — Pacote\n\ncorpo sem linha de status\n"

    updated, outcome = _set_status_accepted(text, accepted_by="<@U1>", day="2026-07-30")

    assert outcome not in ("flipped", "already")
    assert updated == text, "an unreadable file was rewritten anyway"


def test_an_OBSERVED_reading_becomes_a_promise_when_a_person_confirms():
    """brownfield.py's contract: a human confirming is the ONLY event that turns a reading of the
    code into a commitment — so the confirm writer must be able to flip `observed` too."""
    text = _rendered(1).replace("- **Status:** proposed", "- **Status:** observed")

    updated, outcome = _set_status_accepted(text, accepted_by="<@U1>", day="2026-07-30")

    assert outcome == "flipped"
    assert _status_of(updated, "p")[0] == "accepted"


def test_a_superseded_requirement_is_refused_not_re_promised():
    """Accepting a retired text would resurrect a promise somebody already replaced."""
    text = _rendered(1).replace("- **Status:** proposed", "- **Status:** superseded-by 0002")

    updated, outcome = _set_status_accepted(text, accepted_by="<@U1>", day="2026-07-30")

    assert outcome not in ("flipped", "already")
    assert updated == text


def test_accepting_twice_does_not_rewrite_who_agreed():
    """A second confirmation must not quietly reassign the agreement to whoever clicked last."""
    once, first = _set_status_accepted(_rendered(1), accepted_by="<@U1>", day="2026-07-30")
    assert first == "flipped"

    twice, outcome = _set_status_accepted(once, accepted_by="<@U9>", day="2026-08-01")

    assert outcome == "already"
    assert twice == once
    assert "U9" not in twice


def test_a_real_asker_is_kept_and_only_the_unrecorded_placeholder_is_filled():
    """`unrecorded` is absence written down (render's placeholder); a person's name is history."""
    updated, outcome = _set_status_accepted(_rendered(1, asked_by="Alice"),
                                            accepted_by="<@U9>", day="2026-07-30")

    assert outcome == "flipped"
    assert "- **Asked by:** Alice" in updated, "the real asker was overwritten"
    assert "Asked by:** <@U9>" not in updated
    assert "- **Date:** 2026-07-30" in updated, "the placeholder date was not filled"
    assert "unrecorded" not in updated


@pytest.mark.parametrize("phrase", [
    "aceita o requisito 1",
    "aprova o requisito 12",
    "acorda o requisito 3",
    "dá o requisito 1 como acordado",
    "dar o requisito 12 como aceito",
])
def test_a_person_can_ASK_for_acceptance_in_their_own_words(phrase):
    matched = match_intent(phrase)
    assert matched and matched[0] == "accept", f"{phrase!r} -> {matched}"


@pytest.mark.parametrize("phrase", [
    "pode aceitar o requisito 1?",
    "o requisito 1 está aceito?",
    "dá uma olhada no requisito 1",
])
def test_a_QUESTION_never_creates_a_promise(phrase):
    """The most consequential write on this surface: after it the factory ARGUES FROM the statement.
    Imperative only, like every other writing intent."""
    matched = match_intent(phrase)
    assert not (matched and matched[0] == "accept"), f"{phrase!r} -> {matched}"


def test_the_confirmation_explains_what_CHANGES_not_what_field_moves():
    """Nobody confirms a status field. What a person can weigh is the consequence: from here on, a
    product that behaves differently is a DEFECT rather than a new request."""
    text = accept_confirmation(number=1, title="Pacote de fecho", language="pt-BR")

    assert "promessa" in text and "defeito" in text, text
    assert "status" not in text.lower(), "the client is asked about a field"


def test_the_acceptance_reply_records_who_and_when():
    assert "você quem acordou" in accepted(number=1, language="pt-BR")


# ── nothing is left with no owner ──────────────────────────────────────────────────────────────
class _SweepForge:
    """A `ForgeAdapter` stand-in for the proposal sweep, holding the pull requests' STATE.

    THE SWEEP IS THE PORT'S LAST CUSTOMER (#95). It used to shell out to `gh` — list the branches,
    ask for a MERGED pull request, ask for an OPEN one, create, merge, read back, delete a ref by
    REST path — and every one of those calls named the documentation repository, which is the one
    thing `open_pr`/`merge_pr`/`pr_status` could not be told. So this fake is written the way the
    port is: acts, not argv.

    `open_prs` are branches whose pull request is still open; `merged_prs` are branches whose pull
    request is already in the base; `closed_prs` are branches somebody REFUSED. The sweep does a
    different thing with each, so the fake must be able to say each.
    """

    def __init__(self, branches, *, open_prs=(), merged_prs=(), closed_prs=(), merges=True,
                 unreadable=False):
        self.branches = list(branches)
        self.merges = merges
        self.unreadable = unreadable
        self.acted: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.state: dict[str, str] = {}
        self.prs: dict[str, str] = {}
        for group, state in ((open_prs, "open"), (merged_prs, "merged"), (closed_prs, "closed")):
            for branch in group:
                url = f"https://x/{branch}"
                self.prs[branch] = url
                self.state[url] = state

    def list_branches(self, repo: str = "", *, prefix: str = ""):
        self.acted.append(("list_branches", repo))
        if self.unreadable:
            return None
        return [b for b in self.branches if b.startswith(prefix)]

    def pr_for_head(self, head: str, *, repo: str = ""):
        return self.prs.get(head, "")

    def open_pr(self, *, head: str, base: str, title: str, body: str, repo: str = ""):
        self.acted.append(("open_pr", head))
        url = f"https://x/{head}"
        self.prs[head] = url
        self.state[url] = "open"
        return url

    def pr_status(self, *, pr: str, repo: str = ""):
        return self.state.get(pr, "open")

    def merge_pr(self, *, pr: str, repo: str = ""):
        self.acted.append(("merge_pr", pr))
        if self.merges:
            self.state[pr] = "merged"

    def delete_branch(self, name: str, *, repo: str = ""):
        self.deleted.append(name)
        self.branches = [b for b in self.branches if b != name]
        return True

    def did(self, what: str) -> list[str]:
        return [ref for act, ref in self.acted if act == what]


def test_a_proposal_outside_the_base_is_LANDED_not_merely_opened():
    """THE HALF-RECOVERY, and it was mine. The first version opened the review request and stopped —
    which recreates the state it exists to clear: on a branch, out of the base, and unreadable by
    the role that wrote it. Nina found it in one message ("Quantos requisitos existem: zero") and
    reasoned to the cause herself."""
    forge = _SweepForge(["main", "req/0001-x", "product/baseline"])

    assert land_open_proposals(docs_repo="a/b", forge=forge) == ["req/0001-x"]
    assert forge.did("open_pr") == ["req/0001-x"]
    assert forge.did("merge_pr"), "the review request was opened and left open"
    assert forge.deleted == ["req/0001-x"], "the landed branch stays and the sweep churns on it"


def test_a_branch_that_ALREADY_has_a_request_is_merged_rather_than_re_opened():
    """The common case after a failure: the request exists, nothing landed it."""
    forge = _SweepForge(["main", "req/0001-x"], open_prs=("req/0001-x",))

    assert land_open_proposals(docs_repo="a/b", forge=forge) == ["req/0001-x"]
    assert forge.did("open_pr") == [], "a second review request was opened for the same branch"
    assert forge.did("merge_pr")


def test_a_merged_branch_that_survived_deletion_is_CLEARED_not_reproposed():
    """Finding 53 — the live state this repairs: `req/0002` outlived its squash-merged PR #3, and
    every sweep then opened a fresh client-visible "Requisito proposto" PR about a requirement
    already in the base. Recognise MERGED, delete the leftover, converge."""
    forge = _SweepForge(["main", "req/0002-totais"], merged_prs=("req/0002-totais",))

    assert land_open_proposals(docs_repo="a/b", forge=forge) == []
    assert forge.did("open_pr") == [], "a requirement already in the base was re-proposed"
    assert forge.did("merge_pr") == []
    assert forge.deleted == ["req/0002-totais"], (
        "the leftover branch survives, so the next sweep churns on it again")


def test_a_proposal_a_person_CLOSED_is_left_alone_rather_than_re_proposed(caplog):
    """A CLOSED PULL REQUEST IS AN ANSWER OF NO, and the `gh` version could not hear it: it asked
    for MERGED, then for OPEN, and opened a fresh one when it saw neither — so a proposal somebody
    had deliberately closed came back as a new client-visible "Requisito proposto" on the next pass,
    and the one after that, hourly, for ever.

    `pr_for_head` reports the pull request in ANY state and `pr_status` says which, so the sweep can
    now tell "nobody ever asked" from "somebody said no". Nothing is re-proposed, and nothing is
    deleted either — the text stays on the branch for whoever wants it back."""
    forge = _SweepForge(["main", "req/0004-descartado"], closed_prs=("req/0004-descartado",))

    with caplog.at_level(logging.WARNING, logger="openfactory.product"):
        assert land_open_proposals(docs_repo="a/b", forge=forge) == []

    assert forge.did("open_pr") == [], "a proposal a person closed was re-proposed"
    assert forge.did("merge_pr") == [], "a proposal a person closed was merged anyway"
    assert forge.deleted == [], "the text somebody may still want was deleted"
    assert "OPENFACTORY_PRODUCT_PROPOSAL_DISCARDED" in caplog.text


def test_a_merge_that_did_not_happen_is_not_reported_as_landed():
    """A protected branch is the repository owner's right. Saying it landed anyway would be
    ADR-0028's defect committed by the platform."""
    forge = _SweepForge(["main", "req/0001-x"], merges=False)

    assert land_open_proposals(docs_repo="a/b", forge=forge) == []
    assert forge.deleted == [], "a branch was deleted on a merge that did not happen"


def test_only_req_branches_are_touched():
    forge = _SweepForge(["main", "product/baseline", "feature/x"])

    assert land_open_proposals(docs_repo="a/b", forge=forge) == []
    assert forge.acted == [("list_branches", "a/b")], "it acted on a branch that is not a proposal"
    assert forge.deleted == []


def test_a_sweep_that_could_not_look_answers_NONE_and_never_an_empty_list(caplog):
    """**`[]` MEANS SWEPT AND CLEAN; `None` MEANS THE SWEEP DID NOT HAPPEN**, and the `gh` version
    spelled both the same way. Its one production caller reads `if rescued:` — so a repository it
    could not reach, and a repository with nothing stuck in it, produced the identical silence.

    Two ways to not-look, and both must answer None: no forge at all (the state the hourly
    tech-lead round is in until its call site passes one), and a branch list that could not be
    read. The positive twin is right below: a forge that ANSWERED "no branches" gets `[]`."""
    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        assert land_open_proposals(docs_repo="a/b") is None
    assert "OPENFACTORY_PRODUCT_SWEEP_NO_FORGE" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        assert land_open_proposals(docs_repo="a/b", forge=_SweepForge([], unreadable=True)) is None
    assert "OPENFACTORY_PRODUCT_SWEEP_UNREADABLE" in caplog.text

    assert land_open_proposals(docs_repo="a/b", forge=_SweepForge(["main"])) == [], (
        "a repository that was READ and holds no proposals must not read as unreachable")


def test_the_sweep_lands_them():
    """Reach: a recovery that depends on somebody remembering to run it is not a recovery."""
    import ast

    tree = ast.parse(Path("openfactory/runtime/temporal/activities.py").read_text())
    assert any(isinstance(n, ast.Call)
               and getattr(n.func, "id", None) == "land_open_proposals"
               for n in ast.walk(tree)), "the recovery exists and nothing calls it"


# ── a revision retires what it replaces ────────────────────────────────────────────────────────
def test_superseding_stamps_the_OLD_file_too(tmp_path):
    """THE TWO-VERSIONS DEFECT, and Nina predicted it before it happened: "você fica com duas
    versões do mesmo requisito para conciliar."

    A corrected requirement was written as REQ-0002 while REQ-0001 stayed `proposed`. Two live texts
    for one promise, and a factory that would defend whichever it read first. Declaring "Supersedes:
    REQ-0001" in the NEW file is only half of it — `corpus.live()` decides what is current by
    reading each requirement's OWN status, so the old one must learn it was replaced.
    """
    folder = tmp_path / "requirements"
    folder.mkdir()
    old = folder / "0001-pacote.md"
    old.write_text("# REQ-0001 — Pacote\n\n- **Status:** proposed\n- **Asked by:** <@U1>\n")

    changed, failed = _mark_superseded(tmp_path, "requirements", [1], by=2)

    assert (changed, failed) == (["requirements/0001-pacote.md"], [])
    status, by, _ = _status_of(old.read_text(), "p")
    assert (status, by) == ("superseded", 2), old.read_text()


@pytest.mark.parametrize("status_line", [
    "* **Status:** proposed",
    "- Status: proposed",
])
def test_a_hand_edited_status_line_is_still_retired(tmp_path, status_line):
    """Finding 55: `corpus._field_re` reads these on purpose ("a human editing by hand should not
    lose a requirement's status to a missing asterisk") — but the retire writer demanded exactly
    `- **status:**`, no-opped with a log line, and the commit landed half a supersession."""
    folder = tmp_path / "requirements"
    folder.mkdir()
    old = folder / "0001-pacote.md"
    old.write_text(f"# REQ-0001 — Pacote\n\n{status_line}\n")

    changed, failed = _mark_superseded(tmp_path, "requirements", [1], by=2)

    assert (changed, failed) == (["requirements/0001-pacote.md"], [])
    status, by, _ = _status_of(old.read_text(), "p")
    assert (status, by) == ("superseded", 2)


def test_a_superseded_requirement_leaves_the_live_set(tmp_path):
    """The property that actually matters: after the stamp, `live()` returns one promise, not two."""
    from openfactory.product.corpus import Corpus, Requirement

    folder = tmp_path / "requirements"
    folder.mkdir()
    (folder / "0001-x.md").write_text("# REQ-0001 — x\n\n- **Status:** proposed\n")
    _mark_superseded(tmp_path, "requirements", [1], by=2)

    corpus = Corpus(requirements=[
        Requirement(number=1, slug="x", path="requirements/0001-x.md", status="superseded",
                    superseded_by=2),
        Requirement(number=2, slug="y", path="requirements/0002-y.md", status="proposed"),
    ])
    assert [r.number for r in corpus.live()] == [2]


def test_the_FIRST_supersession_is_the_one_that_happened(tmp_path):
    """Overwriting an existing `superseded-by` would rewrite history to point at the newest text
    rather than the one that actually replaced it. Already retired is DONE, never a failure."""
    folder = tmp_path / "requirements"
    folder.mkdir()
    f = folder / "0001-x.md"
    f.write_text("# REQ-0001 — x\n\n- **Status:** superseded-by 0002\n")

    assert _mark_superseded(tmp_path, "requirements", [1], by=9) == ([], [])
    assert "0002" in f.read_text() and "0009" not in f.read_text()


def test_a_requirement_that_cannot_be_retired_is_a_FAILURE_not_a_log_line(tmp_path):
    """A missing file or an unreadable status is a supersession that CANNOT complete — reported to
    the caller, which must then refuse to land the other half."""
    (tmp_path / "requirements").mkdir()
    assert _mark_superseded(tmp_path, "requirements", [77], by=2) == ([], [77])

    f = tmp_path / "requirements" / "0005-x.md"
    f.write_text("# REQ-0005 — x\n\ncorpo sem linha de status\n")
    assert _mark_superseded(tmp_path, "requirements", [5], by=9) == ([], [5])
    assert "superseded" not in f.read_text()


def test_the_prompt_tells_her_WHEN_to_supersede():
    """The field existed in the schema and the instruction did not, so she left it empty — correctly,
    since the same prompt says "leave a list empty rather than inventing entries"."""
    # the instruction lives in the module-level draft schema the role sends, not on a method
    src = Path("openfactory/product/role.py").read_text()
    assert "IS NOT OPTIONAL WHEN YOU ARE REWRITING" in src
    assert "you are writing a revision" in src


def test_the_writer_stamps_both_sides():
    """Reach: declaring supersession on one side only leaves both requirements live, which is the
    defect rather than the fix."""
    import ast

    tree = ast.parse(Path("openfactory/product/authoring.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "propose_requirement")
    assert any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_mark_superseded"
               for n in ast.walk(fn)), "the new file declares it and the old one never learns"


# ── the propose path, end to end against a real repository ────────────────────────────────────
def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def origin(tmp_path):
    """A docs repository seeded with REQ-0001 exactly as production wrote it."""
    src = tmp_path / "docs-origin"
    src.mkdir()
    _git("init", "-q", "-b", "main", cwd=src)
    _git("config", "user.email", "t@t", cwd=src)
    _git("config", "user.name", "t", cwd=src)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=src)
    (src / "requirements").mkdir()
    (src / "requirements" / "0001-pacote-de-fecho.md").write_text(_rendered(1))
    _git("add", "-A", cwd=src)
    _git("commit", "-qm", "seed", cwd=src)
    return src


class _Forge:
    """A `ForgeAdapter` stand-in for EVERY call the proposal writer makes over the DOCS repo (#95).

    Which `req/*` branches exist decides the NUMBER this proposal is minted under, and whether the
    branch was ever proposed decides whether a second pull request is opened for work already
    proposed. Both used to be `gh` shell-outs about `docs_repo`, so both simply did not happen on a
    deployment that is not GitHub's — and both answered "" there, which the writer read as "there
    is nothing". `None` is what that state actually is, and it is asserted on its own below.

    Opening the pull request, merging it and reading its state back were the LAST `gh` calls here,
    for the one reason the whole issue turned on: `open_pr`/`merge_pr`/`pr_status` could only speak
    about the repository the adapter was built for, and every call on this path is about the
    documentation. They take a repository now, so this fake answers all of it."""

    def __init__(self, branches=("main",), *, proposed=None, branches_unreadable=False,
                 prs_unreadable=False):
        self.branches = list(branches)
        self.proposed = dict(proposed or {})
        self.branches_unreadable = branches_unreadable
        self.prs_unreadable = prs_unreadable
        self.state: dict[str, str] = {}
        self.deleted: list[str] = []

    def list_branches(self, repo="", *, prefix=""):
        if self.branches_unreadable:
            return None
        return [b for b in self.branches if b.startswith(prefix)]

    def pr_for_head(self, head, *, repo=""):
        if self.prs_unreadable:
            return None
        return self.proposed.get(head, "")

    def open_pr(self, *, head, base, title, body, repo=""):
        url = f"https://x/{repo}/{head}"
        self.proposed[head] = url
        self.state[url] = "open"
        return url

    def pr_status(self, *, pr, repo=""):
        return self.state.get(pr, "open")

    def merge_pr(self, *, pr, repo=""):
        self.state[pr] = "merged"

    def delete_branch(self, name, *, repo=""):
        self.deleted.append(name)
        return True


def test_a_duplicates_conflict_IS_a_supersession_and_lands_in_the_same_commit(origin):
    """Finding 30 — exactly how the live 0001/0002 corruption happened: the drafter declared "this
    replaces REQ-1" in a machine-readable duplicates conflict with `supersedes=[]`, and propose
    rendered the conflict to prose and landed the new text BESIDE the still-live old one."""
    draft = _draft(title="Totais de IVA verdadeiros",
                   conflicts=[Conflict(requirement=1, kind="duplicates",
                                       explanation="deve substituir o Requisito 1, não passar a "
                                                   "existir ao lado dele")])
    assert draft.supersedes == []          # the drafter's exact live output shape

    res = propose_requirement(docs_repo="a/b", clone_url=str(origin), draft=draft,
                              number=2, forge=_Forge())

    assert res.ok, res.detail
    branch = branch_for(2, draft.title)
    old = _git("show", f"{branch}:requirements/0001-pacote-de-fecho.md", cwd=origin).stdout
    assert "superseded-by 0002" in old, "the old version never learned it was replaced"
    new = _git("show", f"{branch}:requirements/0002-totais-de-iva-verdadeiros.md",
               cwd=origin).stdout
    assert "REQ-0001" in new.split("## Why")[0], "the new file's Supersedes field stayed '—'"
    files = _git("show", "--name-only", "--format=", branch, cwd=origin).stdout.split()
    assert sorted(files) == ["requirements/0001-pacote-de-fecho.md",
                             "requirements/0002-totais-de-iva-verdadeiros.md"], (
        "the two halves of the supersession did not land in ONE commit")


def test_only_a_duplicates_conflict_folds_never_a_contradiction():
    """`contradicts`/`narrows`/`depends_on` are tensions for a person to resolve — folding one
    would retire a requirement nobody chose to retire."""
    d = _draft(conflicts=[Conflict(requirement=3, kind="contradicts", explanation="x"),
                          Conflict(requirement=None, kind="duplicates", explanation="x"),
                          Conflict(requirement=1, kind="duplicates", explanation="x")])

    assert _fold_replacement_conflicts(d).supersedes == [1]
    assert _fold_replacement_conflicts(_draft()).supersedes == []


def test_half_a_supersession_NEVER_lands(origin):
    """Finding 55, end to end: when the old side cannot be stamped, the propose must abort —
    committing only the new file creates the two-live-versions state on purpose."""
    (origin / "requirements" / "0003-sem-status.md").write_text("# REQ-0003 — x\n\ncorpo\n")
    _git("add", "-A", cwd=origin)
    _git("commit", "-qm", "um requisito sem linha de status", cwd=origin)

    res = propose_requirement(docs_repo="a/b", clone_url=str(origin),
                              draft=_draft(title="Nova versão do fecho", supersedes=[3]),
                              number=4, forge=_Forge())

    assert res.ok is False
    assert "duas versões" in res.detail, "the client is not told why nothing was recorded"
    assert "branch" not in res.detail and "git" not in res.detail.lower(), (
        "plumbing vocabulary reached the client's sentence")
    assert "req/0004" not in _git("branch", "--list", "-a", cwd=origin).stdout, (
        "half a supersession was pushed anyway")


def test_a_number_claimed_by_an_unlanded_branch_is_never_reminted(origin):
    """Finding 60: a proposal pushed but never landed is invisible to the base corpus, so the next
    request re-minted its number — two files under one identity, and acceptance/supersession then
    act on whichever sorts first."""
    res = propose_requirement(docs_repo="a/b", clone_url=str(origin),
                              draft=_draft(title="Exportar extratos"), number=2,
                              forge=_Forge(("main", "req/0002-relatorio-mensal")))

    assert res.ok, res.detail
    assert res.ref == branch_for(3, "Exportar extratos"), (
        f"a number an unlanded branch already claims was minted twice: {res.ref}")
    files = _git("ls-tree", "-r", "--name-only", res.ref, cwd=origin).stdout
    assert "requirements/0003-exportar-extratos.md" in files


def test_a_retry_ADOPTS_its_own_prior_branch_instead_of_stepping_past_it(origin):
    """A prior attempt that was bumped to 0003 must be FOUND on retry (the base still mints 2) —
    adopting its number is what keeps the retry idempotent instead of proposing 0004."""
    forge = _Forge(("main", "req/0003-exportar-extratos"),
                   proposed={"req/0003-exportar-extratos": "https://x/7"})

    res = propose_requirement(docs_repo="a/b", clone_url=str(origin),
                              draft=_draft(title="Exportar extratos"), number=2,
                              forge=forge)

    assert res.ok and res.existed is True
    assert res.url == "https://x/7"


# ── the third door onto two live versions ──────────────────────────────────────────────────────
def test_a_LIVE_TWIN_of_the_text_being_written_is_RETIRED_in_the_same_commit(origin):
    """The production defect of 2026-07-31, found ONE TURN after the duplicates door was shut.

    The product owner asked for the final version of requirement 2; the drafter said "it replaces
    requirement
    1" — true, and incomplete. This platform has no update-in-place, so the rewrite minted 0003 and
    left 0002, its own predecessor, standing beside it: same title, same slug, both live. Nothing
    in the draft could have revealed it, because from the model's side there was nothing to
    replace — it believed it was editing 0002, not succeeding it.

    So the base is READ before it is written to. Here the drafter names nothing at all, which is
    the exact live shape.
    """
    title = "Totais de IVA verdadeiros em tudo que sai do produto"
    slug = slugify(title)
    (origin / "requirements" / f"0002-{slug}.md").write_text(_rendered(2, title=title))
    _git("add", "-A", cwd=origin)
    _git("commit", "-qm", "REQ-0002", cwd=origin)

    draft = _draft(title=title)
    assert draft.supersedes == [] and draft.conflicts == []      # nothing to fold from the draft

    res = propose_requirement(docs_repo="a/b", clone_url=str(origin), draft=draft,
                              number=3, forge=_Forge())

    assert res.ok, res.detail
    branch = branch_for(3, title)
    old = _git("show", f"{branch}:requirements/0002-{slug}.md", cwd=origin).stdout
    assert "superseded-by 0003" in old, "the twin was left live — one promise, two numbers"
    new = _git("show", f"{branch}:requirements/0003-{slug}.md", cwd=origin).stdout
    assert "REQ-0002" in new.split("## Why")[0], (
        "the new file's own Supersedes field disagrees with what the commit did")
    files = sorted(_git("show", "--name-only", "--format=", branch, cwd=origin).stdout.split())
    assert files == [f"requirements/0002-{slug}.md", f"requirements/0003-{slug}.md"], (
        "the two halves of the supersession did not land in ONE commit")


def test_a_twin_that_was_ALREADY_retired_is_left_alone(origin):
    """Only LIVE twins fold. Re-stamping a superseded file would rewrite history to point at the
    newest text rather than the one that actually replaced it — and would drag an untouched file
    into every later commit."""
    title = "Totais de IVA verdadeiros em tudo que sai do produto"
    slug = slugify(title)
    retired = _rendered(2, title=title).replace("- **Status:** proposed",
                                                "- **Status:** superseded-by 0009")
    (origin / "requirements" / f"0002-{slug}.md").write_text(retired)
    _git("add", "-A", cwd=origin)
    _git("commit", "-qm", "REQ-0002 retired", cwd=origin)

    res = propose_requirement(docs_repo="a/b", clone_url=str(origin), draft=_draft(title=title),
                              number=3, forge=_Forge())

    assert res.ok, res.detail
    files = sorted(_git("show", "--name-only", "--format=",
                        branch_for(3, title), cwd=origin).stdout.split())
    assert files == [f"requirements/0003-{slug}.md"], "a retired twin was stamped a second time"


def test_a_DIFFERENT_promise_is_never_retired_for_sharing_a_base(origin):
    """The guard keys on the slug, which is the title — not on being nearby in the corpus. A
    requirement about something else must survive its neighbour being written."""
    (origin / "requirements" / "0002-outra-coisa-completamente.md").write_text(
        _rendered(2, title="Outra coisa completamente"))
    _git("add", "-A", cwd=origin)
    _git("commit", "-qm", "REQ-0002", cwd=origin)

    res = propose_requirement(docs_repo="a/b", clone_url=str(origin),
                              draft=_draft(title="Totais de IVA verdadeiros"), number=3,
                              forge=_Forge())

    assert res.ok, res.detail
    old = _git("show", f"{branch_for(3, 'Totais de IVA verdadeiros')}:"
                       f"requirements/0002-outra-coisa-completamente.md", cwd=origin).stdout
    assert "superseded" not in old.lower(), "an unrelated requirement was retired"


def test_the_corpus_REPORTS_one_promise_wearing_two_numbers(tmp_path):
    """The state the client's base is in RIGHT NOW, and the corpus said nothing about it. An error,
    not a warning: `live()` hands both to the agent and the factory defends whichever it reads
    first."""
    from openfactory.product.corpus import load_corpus

    folder = tmp_path / "requirements"
    folder.mkdir()
    title = "Totais de IVA verdadeiros em tudo que sai do produto"
    slug = slugify(title)
    (folder / f"0002-{slug}.md").write_text(_rendered(2, title=title))
    (folder / f"0003-{slug}.md").write_text(
        _rendered(3, title=title).replace("- **Status:** proposed", "- **Status:** accepted"))

    codes = [f.code for f in load_corpus(folder).errors]

    assert "same-promise-twice" in codes, codes
    message = next(f.message for f in load_corpus(folder).findings
                   if f.code == "same-promise-twice")
    assert "REQ-0002" in message and "REQ-0003" in message, message


def test_a_retired_predecessor_is_NOT_reported_as_a_second_promise(tmp_path):
    """The healthy shape must stay silent, or the finding becomes noise nobody reads."""
    from openfactory.product.corpus import load_corpus

    folder = tmp_path / "requirements"
    folder.mkdir()
    title = "Totais de IVA verdadeiros em tudo que sai do produto"
    slug = slugify(title)
    (folder / f"0002-{slug}.md").write_text(
        _rendered(2, title=title).replace("- **Status:** proposed",
                                          "- **Status:** superseded-by 0003"))
    (folder / f"0003-{slug}.md").write_text(_rendered(3, title=title))

    assert [f.code for f in load_corpus(folder).errors] == []


def test_an_ACCEPTED_twin_is_never_retired_behind_a_persons_back(origin):
    """Retiring a text nobody agreed to loses no decision. Revoking a PROMISE does — and a matching
    title is not somebody saying "replace it". Same reasoning that stops a `contradicts` conflict
    folding: the write refuses, and says exactly what would make it legal."""
    title = "Totais de IVA verdadeiros em tudo que sai do produto"
    slug = slugify(title)
    (origin / "requirements" / f"0002-{slug}.md").write_text(
        _rendered(2, title=title).replace("- **Status:** proposed", "- **Status:** accepted"))
    _git("add", "-A", cwd=origin)
    _git("commit", "-qm", "REQ-0002 acordado", cwd=origin)
    before = _git("rev-parse", "main", cwd=origin).stdout.strip()

    res = propose_requirement(docs_repo="a/b", clone_url=str(origin), draft=_draft(title=title),
                              number=3, forge=_Forge())

    assert not res.ok, "an accepted promise was replaced on a title match alone"
    assert "2" in res.detail and "substitui" in res.detail, res.detail
    for leak in ("branch", "commit", "REQ-", "supersede"):
        assert leak not in res.detail, f"the refusal talks machinery to a client: {res.detail}"
    assert _git("rev-parse", "main", cwd=origin).stdout.strip() == before, "something landed anyway"


def test_saying_it_replaces_the_promise_makes_the_write_legal(origin):
    """The way out is the person's word, recorded — and then the unagreed twin rides along, so one
    title ends with exactly one live number."""
    title = "Totais de IVA verdadeiros em tudo que sai do produto"
    slug = slugify(title)
    (origin / "requirements" / f"0002-{slug}.md").write_text(_rendered(2, title=title))
    (origin / "requirements" / f"0003-{slug}.md").write_text(
        _rendered(3, title=title).replace("- **Status:** proposed", "- **Status:** accepted"))
    _git("add", "-A", cwd=origin)
    _git("commit", "-qm", "REQ-0002 + REQ-0003", cwd=origin)

    draft = _draft(title=title, supersedes=[3])          # the person said so; the drafter recorded
    res = propose_requirement(docs_repo="a/b", clone_url=str(origin), draft=draft,
                              number=4, forge=_Forge())

    assert res.ok, res.detail
    branch = branch_for(4, title)
    for retired in (2, 3):
        text = _git("show", f"{branch}:requirements/{retired:04d}-{slug}.md", cwd=origin).stdout
        assert "superseded-by 0004" in text, f"REQ-{retired:04d} stayed live"
    files = sorted(_git("show", "--name-only", "--format=", branch, cwd=origin).stdout.split())
    assert len(files) == 3, f"the three halves did not land in one commit: {files}"
