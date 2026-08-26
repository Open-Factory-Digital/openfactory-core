"""A requirement can be decided AGAINST — the act the lifecycle had no word for.

The product owner asked the question that found this, one turn after watching the first requirement
in the platform's history get accepted:

    *"would 'retired' be a removal of a requirement?" … "then it has to be built — this must be
    very common in a dialogue with the PO, something that will no longer be done, don't you
    agree?"*

That is right, and the gap was structural rather than cosmetic. The lifecycle could WRITE a
requirement, AGREE it, and REPLACE it — and every one of those acts requires somebody to author a
new text. There was no way to say a thing simply will not be done. Retiring by writing a
replacement forces an invention (a text nobody wants) in order to record an absence.

TWO THINGS THIS FILE PINS, and they are the two the design turns on.

**`dropped` is not `superseded`.** `superseded-by NNNN` means "read that one instead"; using it for
something nobody replaced would point a reader at a document that does not exist — and the corpus's
own dangling-pointer rule would call it an error, correctly. So abandonment gets its own status.

**Dropping a PROMISE is a different act from dropping a draft.** A `proposed` text was never
agreed, so retiring it costs nothing. An `accepted` one is a commitment the factory defends, and
taking it back is the only act on this surface that REMOVES a promise — so the confirmation must
say that in the same terms the acceptance used, and the two must never read alike.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

import openfactory.product.channel as pc
from openfactory.product.authoring import (
    _set_status_dropped,
    accept_requirement,
    drop_requirement,
    render_requirement,
)
from openfactory.product.corpus import DROPPED, load_corpus, parse_requirement
from openfactory.product.intents import match_intent
from openfactory.product.role import RequirementDraft
from openfactory.product.voice import drop_confirmation, dropped, jargon_in


def _rendered(number: int = 2, *, title: str = "Pacote de fecho", status: str = "proposed") -> str:
    draft = RequirementDraft(title=title, why="o cliente precisa fechar o mês",
                             must_be_true=["o fecho gera o pacote completo"])
    text = render_requirement(draft, number=number, asked_by="<@UADM>", date="2026-07-30")
    return text.replace("- **Status:** proposed", f"- **Status:** {status}")


# ── 1. the gesture: how a person actually says it ───────────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "Nina, cancela o requisito 2",
    "abandona o requisito 2",
    "descarta o requisito 2",
    "esquece o requisito 2",
    "arquiva o requisito 2",
    "não vamos mais fazer o requisito 2",
    "não vamos fazer o requisito 2",
    "Nina, não precisamos mais implementar o requisito 2",
    "o requisito 2 não vale mais",
    "o requisito 2 saiu de escopo",
    "o requisito 2 foi cancelado",
])
def test_a_person_can_drop_a_requirement_in_their_own_words(phrase):
    matched = match_intent(phrase)
    assert matched, phrase
    assert matched[0] == "drop", f"{phrase!r} matched {matched[0]!r}"
    assert matched[1]["number"] == "2", matched


@pytest.mark.parametrize("phrase", [
    "vamos fazer o requisito 2",
    "quando vamos fazer o requisito 2?",
    "quebra o requisito 2 em tarefas",
    "aceita o requisito 2",
    "o requisito 2 já vale?",
    "me explica o requisito 2",
])
def test_what_must_NEVER_read_as_an_abandonment(phrase):
    """The negated shape is the dangerous one: its verb is ordinary ("fazer"), so matching it
    loosely would turn a plan into a retraction. The negation is required, never inferred."""
    matched = match_intent(phrase)
    assert (matched or ("", {}))[0] != "drop", f"{phrase!r} was read as an abandonment"


def test_the_reason_is_captured_when_the_person_gives_one():
    """What makes the record answer "why aren't we doing this?" in six months, instead of showing
    a status field and a date."""
    _, captures = match_intent("cancela o requisito 2, o cliente desistiu do módulo de férias")
    assert "cliente desistiu" in captures.get("reason", "")


# ── 2. the write: any live state can be dropped, and the dead ones say so ────────────────────────

@pytest.mark.parametrize("status", ["proposed", "observed", "accepted"])
def test_every_live_state_can_be_dropped(status):
    """Including `accepted`, deliberately. A lifecycle that only lets you drop things nobody agreed
    to would force the one case that most needs a record — taking a promise back — to happen by
    hand in a markdown file."""
    updated, outcome = _set_status_dropped(_rendered(status=status), dropped_by="<@UADM>",
                                           day="2026-07-31")

    assert outcome == "flipped", outcome
    req, _ = parse_requirement(Path("0002-pacote-de-fecho.md"), updated)
    assert req.status == DROPPED and not req.is_live
    assert "Dropped by:** <@UADM> on 2026-07-31" in updated


def test_a_superseded_requirement_is_not_re_retired():
    """It is already off the table AND it points at what replaced it. Overwriting that status would
    erase the pointer a reader follows to find the current text."""
    text = _rendered(status="superseded-by 0003")

    updated, outcome = _set_status_dropped(text, dropped_by="<@UADM>", day="2026-07-31")

    assert outcome == "superseded"
    assert updated == text, "the replacement pointer was overwritten"


def test_dropping_twice_is_not_a_second_decision():
    once, _ = _set_status_dropped(_rendered(), dropped_by="<@UADM>", day="2026-07-31")

    twice, outcome = _set_status_dropped(once, dropped_by="<@UOTHER>", day="2026-08-01")

    assert outcome == "already"
    assert twice == once, "a second drop rewrote who decided and when"


def test_the_reason_is_written_into_the_file():
    updated, _ = _set_status_dropped(_rendered(), dropped_by="<@UADM>", day="2026-07-31",
                                     reason="o cliente desistiu do módulo de férias")

    assert "o cliente desistiu do módulo de férias" in updated


def test_a_file_whose_status_cannot_be_read_is_refused_not_guessed():
    updated, outcome = _set_status_dropped("# REQ-0002 — x\n\ncorpo sem status\n",
                                           dropped_by="<@UADM>", day="2026-07-31")

    assert outcome != "flipped" and "status" in outcome
    assert "corpo sem status" in updated


# ── 3. the corpus reads it back, and stops handing it over as current ───────────────────────────

def test_a_dropped_requirement_is_parsed_cleanly_and_is_not_live(tmp_path):
    """A status the writer emits and the reader calls unknown is the drift that cost this codebase
    weeks — so the round trip is the assertion, not the regex."""
    folder = tmp_path / "requirements"
    folder.mkdir()
    updated, _ = _set_status_dropped(_rendered(), dropped_by="<@UADM>", day="2026-07-31")
    (folder / "0002-pacote-de-fecho.md").write_text(updated)

    corpus = load_corpus(folder)

    assert [f.code for f in corpus.errors] == [], corpus.errors
    assert corpus.live() == [], "a dropped requirement is still being handed over as current"
    assert corpus.by_number(2).status == DROPPED


def test_a_dropped_requirement_is_never_a_promise(tmp_path):
    """The factory defends `promises()`. A requirement somebody decided against must leave it the
    moment the decision is recorded — that IS the behaviour being bought."""
    folder = tmp_path / "requirements"
    folder.mkdir()
    updated, _ = _set_status_dropped(_rendered(status="accepted"), dropped_by="<@UADM>",
                                     day="2026-07-31")
    (folder / "0002-pacote-de-fecho.md").write_text(updated)

    assert load_corpus(folder).promises() == []


def test_a_dropped_twin_never_blocks_a_new_requirement(tmp_path):
    """It composes with the twin guard by construction: `is_live` is the one predicate both read,
    so a text somebody dropped cannot make a later requirement of the same name unwritable."""
    from openfactory.product.authoring import _live_twins

    folder = tmp_path / "requirements"
    folder.mkdir()
    updated, _ = _set_status_dropped(_rendered(status="accepted"), dropped_by="<@UADM>",
                                     day="2026-07-31")
    (folder / "0002-pacote-de-fecho.md").write_text(updated)

    assert _live_twins(tmp_path, "requirements", slug="pacote-de-fecho", number=3) == []


# ── 4. end to end, against a real repository ────────────────────────────────────────────────────

def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    for key, value in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"),
                       ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(key, value)


@pytest.fixture()
def origin(tmp_path):
    src = tmp_path / "docs-origin"
    src.mkdir()
    _git("init", "-q", "-b", "main", cwd=src)
    _git("config", "user.email", "t@t", cwd=src)
    _git("config", "user.name", "t", cwd=src)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=src)
    (src / "requirements").mkdir()
    (src / "requirements" / "0002-pacote-de-fecho.md").write_text(_rendered(status="accepted"))
    _git("add", "-A", cwd=src)
    _git("commit", "-qm", "seed", cwd=src)
    return src


def test_dropping_lands_on_the_branch_everyone_reads(origin):
    res = drop_requirement(docs_repo="a/b", clone_url=str(origin),
                           path="requirements/0002-pacote-de-fecho.md", number=2,
                           dropped_by="<@UADM>", reason="o cliente desistiu",
                           today="2026-07-31")

    assert res.ok, res.detail
    landed = _git("show", "main:requirements/0002-pacote-de-fecho.md", cwd=origin).stdout
    assert "- **Status:** dropped" in landed
    assert "<@UADM> on 2026-07-31 — o cliente desistiu" in landed
    subject = _git("log", "-1", "--format=%s", "main", cwd=origin).stdout
    assert "abandonado por <@UADM>" in subject, subject
    files = _git("show", "--name-only", "--format=", "main", cwd=origin).stdout.split()
    assert files == ["requirements/0002-pacote-de-fecho.md"], f"it touched more than one file: {files}"


def test_a_requirement_that_is_not_there_changes_nothing(origin):
    before = _git("rev-parse", "main", cwd=origin).stdout.strip()

    res = drop_requirement(docs_repo="a/b", clone_url=str(origin),
                           path="requirements/0009-nao-existe.md", number=9,
                           dropped_by="<@UADM>")

    assert not res.ok and "9" in res.detail
    assert _git("rev-parse", "main", cwd=origin).stdout.strip() == before


# ── 5. what the person reads, and the gate in front of the write ────────────────────────────────

def test_taking_a_promise_back_never_reads_like_dropping_a_draft():
    draft = drop_confirmation(number=2, title="Pacote de fecho", was_a_promise=False,
                              language="pt-BR")
    promise = drop_confirmation(number=2, title="Pacote de fecho", was_a_promise=True,
                                language="pt-BR")

    assert draft != promise
    assert "defende" in promise and "defeito" in promise, (
        "the one act that REMOVES a promise does not say so")
    for text in (draft, promise,
                 dropped(number=2, language="pt-BR"),
                 dropped(number=2, was_a_promise=True, language="pt-BR")):
        assert jargon_in(text) == [], text
        assert "status" not in text.lower(), f"a field name reached the client: {text}"


class _Req:
    def __init__(self, number=2, status="proposed"):
        self.number, self.status = number, status
        self.title, self.slug, self.path = "Pacote de fecho", "pacote-de-fecho", "0002-x.md"

    @property
    def is_live(self):
        return self.status not in ("superseded", "dropped")

    @property
    def is_promise(self):
        return self.status == "accepted"


class _Module:
    def __init__(self, req=None):
        self.req, self.dropped_with = req, None

    def context(self):
        req = self.req

        class _Corpus:
            def by_number(self, n):
                return req if req and req.number == n else None

        class _Ctx:
            available = True
            reason = ""
            corpus = _Corpus()

        return _Ctx()

    def drop(self, number, *, actor, reason=""):
        self.dropped_with = (number, actor, reason)

        class _R:
            ok, detail, existed, ref = True, "", False, ""

        return _R()

    def settle_acceptance(self, text):
        return None


class _Product:
    enabled, slack_channel, agent_name = True, "C1", "Nina"

    def __init__(self, admins):
        self.admins = admins


class _Project:
    name, language = "books", "pt-BR"

    def __init__(self, admins=("UADM",)):
        self.product = _Product(list(admins))


@pytest.fixture(autouse=True)
def _clean_stage(monkeypatch):
    # THE STATE LIVES IN `openfactory/product/staging.py` NOW (#98 slice 3), so isolation is
    # applied THERE. Rebinding the re-export on `product_channel` would leave the code
    # reading the original dict: the fixture would look like it isolates and would not,
    # which is how a staged proposal leaked into the next test when this move was first
    # attempted — with the symptom landing far from the cause.
    from openfactory.product import staging as _staging
    monkeypatch.setattr(_staging, "_PENDING", {})
    monkeypatch.setattr(_staging, "_EXPIRED_TOMBSTONES", {})
    from openfactory.memory import transcript

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")
    yield


def test_the_whole_gesture_reaches_the_write_through_the_channel():
    """The reachability assertion, not a unit one: this codebase's signature defect is a capability
    that exists, passes its tests and is reached by nothing in production."""
    project, module = _Project(), _Module(_Req(2, "accepted"))

    ask = pc.handle(project, text="Nina, cancela o requisito 2, o cliente desistiu",
                    user="UADM", thread="C1", channel="C1", module=module)

    assert "abandonado" in ask and "defende" in ask, ask
    assert module.dropped_with is None, "it wrote before anybody confirmed"

    done = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert module.dropped_with == (2, "UADM", "o cliente desistiu"), module.dropped_with
    assert "abandonado" in done or "promessa" in done, done


def test_an_unauthorised_person_cannot_drop_and_does_not_consume_the_proposal():
    project, module = _Project(admins=["UADM"]), _Module(_Req(2, "accepted"))
    pc.handle(project, text="cancela o requisito 2", user="UADM", thread="C1", channel="C1",
              module=module)

    refused = pc.handle(project, text="sim", user="USTRANGER", thread="C1", channel="C1",
                        module=module)

    assert module.dropped_with is None, refused
    assert pc.pending_for("C1") is not None, "the real approver's yes would find nothing"


def test_dropping_something_already_off_the_table_stages_nothing():
    """Staging a write that changes nothing would have the person confirm a decision they did not
    make — the platform announcing an act it did not perform, from the other end."""
    project, module = _Project(), _Module(_Req(2, "superseded"))

    reply = pc.handle(project, text="cancela o requisito 2", user="UADM", thread="C1",
                      channel="C1", module=module)

    assert "não estava valendo" in reply, reply
    assert pc.pending_for("C1") is None


def test_a_drop_and_an_accept_of_the_same_number_never_share_a_button():
    """Opposite acts on one requirement. A stale button for one must never perform the other — the
    fingerprint is what stands between them."""
    drop_token = pc.proposal_token("C1", {"kind": "drop", "number": 2})
    accept_token = pc.proposal_token("C1", {"kind": "accept", "number": 2})

    assert drop_token != accept_token


# ── 6. what was handed to the role is on the record ─────────────────────────────────────────────
# Not part of the drop lifecycle, but the same discipline and it earned its place the hard way:
# Nina reported "o que está montado para mim veio vazio" and the platform could not say whether
# she was right. Three silent exits led there.

def test_an_empty_mount_is_an_ERROR_not_a_shrug(tmp_path, caplog):
    from openfactory.product.module import _log_mount

    empty = tmp_path / "vazio"
    empty.mkdir()

    with caplog.at_level("ERROR"):
        _log_mount("books", empty, docs=empty, code=None)

    assert any("OPENFACTORY_PRODUCT_MOUNT_EMPTY" in r.getMessage() for r in caplog.records)


def test_a_missing_mount_is_told_apart_from_an_empty_one(tmp_path):
    from openfactory.product.module import _visible

    missing, empty, full = tmp_path / "nao-existe", tmp_path / "vazio", tmp_path / "cheio"
    empty.mkdir()
    full.mkdir()
    (full / "0001-x.md").write_text("x")
    (full / ".git").mkdir()

    assert _visible(missing) == -1, "a missing path must not read as an empty one"
    assert _visible(empty) == 0
    assert _visible(full) == 1, "dotfiles must not count as something an agent can open"


def test_a_healthy_mount_records_what_was_handed_over(tmp_path, caplog):
    from openfactory.product.module import _log_mount

    docs, code = tmp_path / "documentation", tmp_path / "code"
    for d in (docs, code):
        d.mkdir()
        (d / "algo.md").write_text("x")

    with caplog.at_level("INFO"):
        _log_mount("books", tmp_path, docs=docs, code=code)

    said = " ".join(r.getMessage() for r in caplog.records)
    assert "OPENFACTORY_PRODUCT_MOUNT " in said and "code_entries=1" in said and "docs_entries=1" in said
    assert "OPENFACTORY_PRODUCT_MOUNT_EMPTY" not in said


def test_a_deployment_with_no_source_repo_says_so_instead_of_degrading_in_silence(caplog):
    """The first silent exit: no forge and no tracker means the code can never be mounted, for
    every conversation, for ever — and nothing said it."""
    from openfactory.product.module import ProductModule

    class _P:
        name = "sem-fonte"
        forge = None
        tracker = None

    mod = ProductModule.__new__(ProductModule)
    mod.project = _P()

    with caplog.at_level("WARNING"):
        assert mod._source_repo() == ""

    assert any("OPENFACTORY_PRODUCT_NO_SOURCE_REPO" in r.getMessage() for r in caplog.records)


# ── 7. a decision AGAINST is not overwritten by a later replacement ─────────────────────────────

def test_a_DROPPED_requirement_is_never_re_stamped_as_superseded():
    """PRODUCTION, 2026-07-31, hours after `dropped` was introduced. REQ-0005 was dropped with a
    reason and a name; a later requirement declared it superseded, and `_mark_superseded` — which
    knew to skip an already-`superseded-by` file and had never heard of `dropped` — overwrote the
    status. The file was left saying "read 0006 instead" on one line and "the product owner decided
    against this, because…" on the next.

    `is_live`, the status reader and the acceptance writer all learned about the new dead state.
    This writer did not. Which is the lesson-learned-in-one-file class, committed twelve hours
    after writing the comment that names it.
    """
    from openfactory.product.authoring import _mark_superseded

    root = Path(__import__("tempfile").mkdtemp())
    folder = root / "requirements"
    folder.mkdir()
    dropped, _ = _set_status_dropped(_rendered(5), dropped_by="<@UADM>", day="2026-07-31",
                                     reason="não devia ter nascido")
    target = folder / "0005-pacote-de-fecho.md"
    target.write_text(dropped)

    changed, failed = _mark_superseded(root, "requirements", [5], by=6)

    assert changed == [] and failed == [], (changed, failed)
    after = target.read_text()
    assert "- **Status:** dropped" in after, "the decision against it was overwritten"
    assert "não devia ter nascido" in after
    assert "superseded-by" not in after


# ── 8. and accepting one that is already off the table is an ANSWER, not an apology ─────────────
# The other half of `dropped`: a status only one of the two writers had learned to tell apart.
# `drop_requirement` gained `_drop_refusal` the day the state was introduced; the acceptance kept
# one sentence for everything that is not a flip, so the newest outcome fell into the branch
# reserved for a file nobody can parse.

def _seeded(origin, text: str) -> str:
    """Put the corpus in `text` and hand back the commit nothing may move past."""
    (origin / "requirements" / "0002-pacote-de-fecho.md").write_text(text)
    _git("add", "-A", cwd=origin)
    _git("commit", "-qm", "estado", cwd=origin)
    return _git("rev-parse", "main", cwd=origin).stdout.strip()


def test_accepting_something_the_CLIENT_dropped_never_calls_their_decision_an_unreadable_file(
        origin, caplog):
    """They abandoned it yesterday and say "aceita o requisito 2" today — a normal thing to do,
    and one the platform answers with a plain fact plus the way back.

    What it must never answer is the sentence written for a damaged document: an apology for a file
    that is perfectly healthy, a promise that a team is on its way to repair it, and an `error` in
    the operators' log naming a corpus that is fine. Nobody would be coming."""
    dropped_text, _ = _set_status_dropped(_rendered(status="accepted"), dropped_by="<@UADM>",
                                          day="2026-07-31", reason="o cliente desistiu")
    before = _seeded(origin, dropped_text)

    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        res = accept_requirement(docs_repo="a/b", clone_url=str(origin),
                                 path="requirements/0002-pacote-de-fecho.md", number=2,
                                 accepted_by="<@UADM>", today="2026-08-01")

    assert res.ok is False
    assert "abandonado" in res.detail, res.detail
    assert "formato" not in res.detail, "their own decision was reported as a malformed document"
    assert "time foi avisado" not in res.detail, "a repair was promised for a healthy file"
    assert jargon_in(res.detail) == [], res.detail
    assert [r.getMessage() for r in caplog.records] == [], "a healthy corpus raised an error marker"
    assert _git("rev-parse", "main", cwd=origin).stdout.strip() == before


def test_accepting_a_requirement_that_was_REPLACED_points_at_the_one_that_took_its_place(origin):
    """The third answer, and the reason there are three: a retired text has a successor to ask
    about, so sending the person to the team would send them to the wrong place — exactly what
    `_drop_refusal` already says on the abandonment side."""
    before = _seeded(origin, _rendered(status="superseded-by 0003"))

    res = accept_requirement(docs_repo="a/b", clone_url=str(origin),
                             path="requirements/0002-pacote-de-fecho.md", number=2,
                             accepted_by="<@UADM>", today="2026-08-01")

    assert res.ok is False
    assert "substituído" in res.detail and "formato" not in res.detail, res.detail
    assert jargon_in(res.detail) == [], res.detail
    assert "superseded" not in res.detail.lower(), "the machine's own word for it reached the client"
    assert _git("rev-parse", "main", cwd=origin).stdout.strip() == before


def test_a_requirement_file_NOBODY_can_parse_is_still_ours_to_fix_and_still_an_error(origin, caplog):
    """The half that must survive the distinction. A document the parser cannot read is real
    breakage: the person is told the truth, and the operators' log keeps the marker that says a file
    in the corpus needs a person."""
    before = _seeded(origin, "# REQ-0002 — Pacote de fecho\n\ncorpo sem linha de status\n")

    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        res = accept_requirement(docs_repo="a/b", clone_url=str(origin),
                                 path="requirements/0002-pacote-de-fecho.md", number=2,
                                 accepted_by="<@UADM>", today="2026-08-01")

    assert res.ok is False and "formato" in res.detail and "time foi avisado" in res.detail
    assert any("OPENFACTORY_PRODUCT_ACCEPT_UNFLIPPABLE" in r.getMessage() for r in caplog.records)
    assert _git("rev-parse", "main", cwd=origin).stdout.strip() == before


def test_a_draft_that_names_a_DEAD_requirement_stops_claiming_it(tmp_path):
    """The other half. Skipping the stamp is only right if the new file also stops ASSERTING the
    replacement — otherwise it claims a supersession the commit deliberately did not perform, and
    `_cross_check` calls that an error, correctly."""
    from openfactory.product.authoring import _already_dead

    folder = tmp_path / "requirements"
    folder.mkdir()
    alive = _rendered(4)
    gone, _ = _set_status_dropped(_rendered(5), dropped_by="<@UADM>", day="2026-07-31")
    (folder / "0004-pacote-de-fecho.md").write_text(alive)
    (folder / "0005-pacote-de-fecho.md").write_text(gone)

    assert _already_dead(tmp_path, "requirements", [4, 5]) == [5]
    assert _already_dead(tmp_path, "requirements", [4]) == []
