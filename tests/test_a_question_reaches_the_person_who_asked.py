"""The question reaches the person who asked, and the answer comes back through the card
(ADR-0048 §5-§7): the requester in the tracker's namespace, the sweep that recognises an answer,
the write in the requester's name, the concept that stops the next card asking again."""

from __future__ import annotations

from pathlib import Path

from openfactory.adapters.tracker.base import TicketComment
from openfactory.adapters.tracker.parse import parse_ticket_body
from openfactory.contracts import JobState
from openfactory.contracts.ticket import Ticket, tracker_requester_of
from openfactory.knowledge import gather as g
from openfactory.memory.ledger import CARD_QUESTION, CHASED, CLOSED, OPEN, open_loop
from openfactory.product.authoring import WriteResult, defect_body, issue_body, ticket_body
from openfactory.product.requester import forge_identity_for
from openfactory.runtime.temporal import activities as acts


def _parse(body: str) -> Ticket:
    return parse_ticket_body(id="#7", title="t", body=body, repo="o/r")


# ── the requester, in the tracker's namespace ───────────────────────────────────────────────────


def _ticket(**over) -> Ticket:
    base = dict(id="#7", title="t", repo="o/r", objective="x")
    base.update(over)
    return Ticket(**base)


def test_a_hand_written_card_s_author_is_its_requester():
    assert tracker_requester_of(_ticket(author="octocat")) == "octocat"


def test_a_factory_opened_card_for_a_chat_identity_names_nobody_the_tracker_knows():
    """Its author is the platform's App; returning that would address the question to the bot that
    asked it (refutation 9)."""
    assert tracker_requester_of(_ticket(author="openfactory[bot]", requester="U04ABC")) == ""


def test_the_forge_key_wins_when_the_deployment_could_resolve_one():
    assert tracker_requester_of(_ticket(author="openfactory[bot]", requester="U04ABC",
                                        requester_forge="mara")) == "mara"


def test_nobody_recorded_in_the_forge_key_is_nobody():
    assert tracker_requester_of(_ticket(author="octocat", requester_forge="unknown")) == "octocat"


def test_the_people_map_is_read_backwards_and_never_guessed():
    project = type("P", (), {"people": {"mara": "U04ABC", "joao": "U09XYZ", "dup": "U04ABC"}})()
    assert forge_identity_for(project, "U09XYZ") == "joao"
    assert forge_identity_for(project, "<@U09XYZ>") == "joao", "a mention token is its id"
    assert forge_identity_for(project, "U04ABC") == "", "two logins for one id resolve to nobody"
    assert forge_identity_for(project, "U00000") == "" and forge_identity_for(project, "") == ""
    assert forge_identity_for(type("Q", (), {})(), "U09XYZ") == ""


# ── the card carries both, quoted, and in prose ─────────────────────────────────────────────────

def test_the_bodies_write_both_keys_quoted_and_the_prose_line_carries_the_forge_identity():
    body = ticket_body(described="d", reported_by="U04ABC", source="s", requester_forge="mara")
    assert body.startswith('---\nrequester: "U04ABC"\nrequester_forge: "mara"\n---')
    assert "**Pedido por:** U04ABC (mara)" in body
    t = _parse(body)
    assert (t.requester, t.requester_forge) == ("U04ABC", "mara")


def test_a_login_starting_with_at_is_valid_yaml_because_it_is_quoted():
    """`requester: @octocat` is not YAML — `@` cannot start a token — and would have crashed every
    read of the card on three vendors (refutation 10)."""
    body = defect_body(restated="r", reported_by="@octocat", severity="", source="",
                       requirement=None, requirement_path="", docs_repo="d",
                       requester_forge="@octocat")
    t = _parse(body)
    assert t.requester == "@octocat" and t.requester_forge == "@octocat"


def test_the_prose_copy_survives_a_flattened_fence():
    """ADO's rich editor renders the `---` fence as body text; the parenthesis is what is left
    (refutation 11)."""
    flattened = "**Tipo:** tarefa pedida\n**Pedido por:** U04ABC (mara)\n\n## O que foi pedido\n\nx"
    t = _parse(flattened)
    assert (t.requester, t.requester_forge) == ("U04ABC", "mara")


def test_a_prose_line_without_a_parenthesis_names_no_forge_identity():
    t = _parse("**Pedido por:** U04ABC\n\n## x\n\ny")
    assert (t.requester, t.requester_forge) == ("U04ABC", None)


def test_issue_body_carries_the_forge_identity_of_who_asked_for_the_requirement():
    from openfactory.product.role import IssueDraft

    body = issue_body(IssueDraft(title="t", objective="o"), requirement_path="p", docs_repo="d",
                      requester="U04ABC", requester_forge="mara")
    assert 'requester_forge: "mara"' in body


def test_nobody_recorded_writes_no_key_and_no_parenthesis():
    body = ticket_body(described="d", reported_by="", source="")
    assert not body.startswith("---") and "**Pedido por:** não registrado" in body


# ── the pure rules of the gather ────────────────────────────────────────────────────────────────

def test_established_means_every_citation_verified_and_at_least_one():
    class A:
        ok = True

        def __init__(self, verified):
            self.reading = type("R", (), {"verified": verified})()

    assert g.established(A({"concepts": {"Tax": "fresh"}, "requirements": {7: True}}))
    assert not g.established(A({"concepts": {"Tax": "stale"}, "requirements": {}}))
    assert not g.established(A({"concepts": {}, "requirements": {99: False}})), "média"
    assert not g.established(A({"concepts": {}, "requirements": {}})), "an opinion"
    assert not g.established(None)
    bad = A({"concepts": {"Tax": "fresh"}, "requirements": {}})
    bad.ok = False
    assert not g.established(bad)


def test_expand_touches_uses_the_inventory_when_the_bundle_has_one(tmp_path):
    repo = tmp_path / "r"
    (repo / "billing").mkdir(parents=True)
    (repo / "billing" / "a.py").write_text("a")
    (repo / "billing" / "b.py").write_text("b")
    inv = ["billing/a.py", "other/c.py"]
    assert g.expand_touches(["billing/"], repo, inventory_paths=inv) == ["billing/a.py"]
    assert g.expand_touches(["billing"], repo) == ["billing/a.py", "billing/b.py"]
    assert g.expand_touches(["billing/a.py", "./billing/a.py", "ghost.py", " "], repo) == [
        "billing/a.py"], "a file that does not exist yet has no bytes to describe"


def test_question_hash_is_about_the_files_not_the_wording():
    assert g.question_hash(["b.py", "a.py"]) == g.question_hash(["a.py", "b.py", "a.py"])
    assert g.question_hash(["a.py"]) != g.question_hash(["b.py"])
    assert g.marker_for("abc").startswith(g.MARKER + " ")


def test_the_answer_is_by_the_requester_after_the_question_and_never_the_platform_s_own():
    asked_at = "2026-09-06T10:00:00+00:00"
    rows = [
        TicketComment(author="mara", body="earlier remark", created_at="2026-09-06T09:00:00+00:00"),
        TicketComment(author="bot", body=g.MARKER + " abc\n@mara — ...",
                      created_at="2026-09-06T10:00:00+00:00"),
        TicketComment(author="", body="anonymous yes", created_at="2026-09-06T10:30:00+00:00"),
        TicketComment(author="joao", body="I think 2%", created_at="2026-09-06T10:40:00+00:00"),
        TicketComment(author="mara", body=g.MARKER + " abc\nquoted", created_at="2026-09-06T10:50:00+00:00"),
        TicketComment(author="mara", body="2% after 30 days.", created_at="2026-09-06T11:00:00+00:00"),
    ]
    hit = g.answer_after(rows, asked_at=asked_at, requester="mara", poster="bot")
    assert hit is not None and hit.body == "2% after 30 days."
    assert g.answer_after(rows, asked_at=asked_at, requester="", poster="bot") is None
    assert g.answer_after(rows[:5], asked_at=asked_at, requester="mara", poster="bot") is None


def test_the_platform_s_own_identity_is_never_an_answer_even_when_it_is_the_requester_s_name():
    """On Azure DevOps the PAT is a person's; the platform's comments carry THEIR uniqueName
    (refutation 25)."""
    rows = [TicketComment(author="mara", body="still waiting on the question above",
                          created_at="2026-09-08T10:00:00+00:00")]
    assert g.answer_after(rows, asked_at="2026-09-06T10:00:00+00:00", requester="mara",
                          poster="mara") is None


def test_a_person_s_answer_becomes_a_concept_in_their_name():
    c = g.concept_from_answer(path="billing/fees.py", question="What is it for?",
                              answer="  Late fees:\n 2% after 30 days. ", by="mara",
                              at="2026-09-06T11:00:00+00:00", repo="o/r", fingerprint="f1")
    assert c.generated_by == "human:mara" and c.sources[0].path == "billing/fees.py"
    assert c.sources[0].fingerprint == "f1" and c.what_it_does == "Late fees: 2% after 30 days."
    assert "What is it for?" in c.caveats[0] and c.status == "draft"


# ── the sweep ───────────────────────────────────────────────────────────────────────────────────


class _Tracker:
    def __init__(self, comments, *, move=True):
        self._comments = comments
        self.said: list[tuple[str, str]] = []
        self.moves: list[tuple[str, JobState]] = []
        self._move = move

    def comments(self, ref, *, limit=0):
        return self._comments

    def mention(self, login):
        """The row renders its own mention (ADR-0049 D7) — borrowed from the GitHub row rather
        than copied, since this sweep's world is a GitHub deployment."""
        from openfactory.adapters.tracker.github import GitHubIssuesTracker

        return GitHubIssuesTracker.mention(self, login)

    def comment(self, ref, body):
        self.said.append((ref, body))

    def set_state(self, ref, state, reason=None, *, needs_person=None):
        self.moves.append((ref, state))
        return self._move


class _Module:
    def __init__(self, result):
        self.result = result
        self.calls: list[dict] = []

    def __call__(self, project, *, via="api"):
        return self

    def record_answer(self, **kw):
        self.calls.append(kw)
        return self.result


def _loop(ts="2026-09-06T10:00:00+00:00", state=OPEN):
    loop = open_loop(CARD_QUESTION, "41", owner="techlead", about="abc", ts=ts, context={
        "requester": "mara", "poster": "bot", "asked_at": ts, "paths": "billing/fees.py",
        "question": "What is `billing/fees.py` for?", "repo": "o/r", "language": "",
        "gap_keys": "abc123def456"})
    return loop if state == OPEN else loop.__class__(**{**loop.__dict__, "state": state})


class _Sweep:
    def __init__(self, monkeypatch, *, loops, comments, result=None, move=True):
        import openfactory.memory.store as loop_store
        import openfactory.product.module as product

        self.tracker = _Tracker(comments, move=move)
        self.module = _Module(result or WriteResult(ok=True, detail="written"))
        self.written: list = []
        self.into_bundle: list = []
        project = type("P", (), {"name": "acme", "language": "",
                                 "tracker": type("T", (), {"kind": "github"})()})()
        monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self_, name: project)
        monkeypatch.setattr(acts, "_tracker_for", lambda project: self.tracker)
        monkeypatch.setattr(acts, "_answer_into_bundle",
                            lambda project, **kw: self.into_bundle.append(kw) or True)
        monkeypatch.setattr(product, "ProductModule", self.module)
        monkeypatch.setattr(loop_store, "read", lambda name: list(loops))
        monkeypatch.setattr(loop_store, "write",
                            lambda name, rows: self.written.extend(rows) or len(rows))

    def run(self):
        return acts._do_card_question_sweep("acme")


_ANSWER = TicketComment(author="mara", body="2% after 30 days.",
                        created_at="2026-09-06T11:00:00+00:00")


def test_nothing_open_is_a_quiet_round(monkeypatch):
    s = _Sweep(monkeypatch, loops=[], comments=[])
    assert s.run() == "nothing-open" and not s.tracker.said


def test_an_answer_is_recorded_in_the_requester_s_name_becomes_a_concept_and_returns_the_card(
        monkeypatch):
    s = _Sweep(monkeypatch, loops=[_loop()], comments=[_ANSWER])
    out = s.run()
    assert out.startswith("answered:1")
    (call,) = s.module.calls
    assert call["said_by"] == "mara" and call["answer"] == "2% after 30 days."
    assert call["about"] == "billing/fees.py" and "card #41" in call["where"]
    (kw,) = s.into_bundle
    assert kw["paths"] == ["billing/fees.py"] and kw["by"] == "mara"
    assert kw["gap_keys"] == ["abc123def456"], "the open questions the comment carried, to retire"
    assert s.tracker.moves == [("41", JobState.TODO)]
    assert len(s.tracker.said) == 1 and "mara" in s.tracker.said[0][1]
    (row,) = s.written
    assert row.state == CLOSED and row.outcome == "answered"


def test_a_term_the_context_already_holds_counts_as_recorded(monkeypatch):
    """`note_fact` refuses a term it already holds — an existing term is the fact already in the
    context, a success (refutation 18)."""
    s = _Sweep(monkeypatch, loops=[_loop()], comments=[_ANSWER],
               result=WriteResult(ok=False, existed=True, detail="já tenho isto anotado"))
    s.run()
    assert s.into_bundle and s.tracker.moves and s.written[0].state == CLOSED
    assert "mara" in s.tracker.said[0][1] and "só neste" not in s.tracker.said[0][1]


def test_a_write_that_failed_keeps_the_answer_on_the_card_and_says_so(monkeypatch):
    s = _Sweep(monkeypatch, loops=[_loop()], comments=[_ANSWER],
               result=WriteResult(ok=False, detail="a base está protegida"))
    s.run()
    assert not s.into_bundle, "no concept from an answer the context could not hold"
    assert s.tracker.moves == [("41", JobState.TODO)] and s.written[0].state == CLOSED
    assert "card" in s.tracker.said[0][1] and "protegida" in s.tracker.said[0][1]


def test_a_card_that_could_not_be_returned_stays_open_for_the_next_round(monkeypatch):
    s = _Sweep(monkeypatch, loops=[_loop()], comments=[_ANSWER], move=False)
    out = s.run()
    assert out.startswith("answered:0") and not s.written and not s.tracker.said


def test_no_answer_is_chased_once_after_two_days_and_never_again(monkeypatch):
    fresh = _loop(ts="2026-09-01T10:00:00+00:00")  # five days without an answer
    s = _Sweep(monkeypatch, loops=[fresh], comments=[])
    assert s.run() == "answered:0 chased:1 open:1"
    assert "@mara" in s.tracker.said[0][1] and s.written[0].state == CHASED
    already = _loop(ts="2026-09-01T10:00:00+00:00", state=CHASED)
    s2 = _Sweep(monkeypatch, loops=[already], comments=[])
    assert s2.run() == "answered:0 chased:0 open:1" and not s2.tracker.said


def test_a_fresh_question_is_not_chased_yet(monkeypatch):
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    s = _Sweep(monkeypatch, loops=[_loop(ts=now)], comments=[])
    assert s.run() == "answered:0 chased:0 open:1" and not s.tracker.said


def test_an_unreadable_thread_skips_that_card_only(monkeypatch):
    s = _Sweep(monkeypatch, loops=[_loop()], comments=None)
    assert s.run() == "answered:0 chased:0 open:1" and not s.written


# ── the seam on the product module ──────────────────────────────────────────────────────────────

def test_the_answer_retires_the_open_questions_the_comment_carried_and_re_renders_the_door(
        tmp_path, monkeypatch):
    """ADR-0048 §7, the half that was NOT wired when the slice shipped: the sweep writes the answer
    back into the bundle's open question — kept, answered, in the person's name — beside the
    concept, and the front door shows both. A key the bundle no longer holds is skipped, not an
    error: a person's answer must not cost the sweep that carried it."""
    import openfactory.adapters.forge.registry as forge
    import openfactory.knowledge.pipeline as pipeline
    from openfactory.knowledge.contracts import ANSWERED, Gap, OkfManifest
    from openfactory.knowledge.okf import OKF_INDEX_FILE, read_concepts, read_manifest, write_okf
    from openfactory.knowledge.pipeline import Fetched

    gap = Gap(kind="open-question", path="billing/fees.py",
              detail="Is the 2% fee decided anywhere?")
    bundle = tmp_path / "bundle"
    write_okf(bundle, manifest=OkfManifest(source_commit="c1", gaps=[gap]), concepts=[])
    published: list = []
    monkeypatch.setattr(pipeline, "fetch_bundle", lambda url, *, subpath: Fetched(bundle))
    monkeypatch.setattr(pipeline, "publish_bundle",
                        lambda b, url, *, subpath, source_commit="", author=None:
                        published.append(subpath) or True)
    monkeypatch.setattr(pipeline, "discard_fetched_bundle", lambda p: None)
    monkeypatch.setattr(forge, "clone_url_for", lambda project, repo="", *, token=None: "u")

    def _no_checkout(project, repo):
        raise RuntimeError("no checkout on this machine")

    monkeypatch.setattr(acts, "_worker_checkout", _no_checkout)
    project = type("P", (), {
        "name": "acme", "language": "",
        "product": type("Pr", (), {"docs_repo": "acme/context", "docs_branch": "main"})(),
        "forge": type("F", (), {"repo": "acme/app", "kind": "github", "options": {}})(),
        "tracker": type("T", (), {"repo": "acme/app", "kind": "github", "options": {}})(),
    })()

    assert acts._answer_into_bundle(project, repo="acme/app", paths=["billing/fees.py"],
                                    question="What is it for?", answer="2% after 30 days.",
                                    by="mara", at="2026-09-07T12:00:00Z",
                                    gap_keys=[gap.key, "000000000000"]) is True

    [back] = read_manifest(bundle).gaps
    assert back.status == ANSWERED and back.answer == "2% after 30 days."
    assert back.answered_by == "mara" and back.detail == gap.detail, "kept as asked, answered"
    [concept] = read_concepts(bundle)
    assert concept.generated_by == "human:mara"
    door = (bundle / OKF_INDEX_FILE).read_text(encoding="utf-8")
    assert "**answered** by mara" in door and concept.title in door, door
    assert published == [pipeline.okf_subpath("acme/app")]


def test_record_answer_is_declared_where_the_gate_is_and_stores_the_author_verbatim():
    src = Path("openfactory/product/module.py").read_text(encoding="utf-8")
    authority = src[src.index("WHAT WRITES WITHOUT ASKING"):src.index('"""', src.index(
        "WHAT WRITES WITHOUT ASKING"))]
    assert "record_answer" in authority
    body = src[src.index("    def record_answer("):src.index("    def file_issues(")]
    assert "may_act" not in body.split('"""')[2], "provenance, not authorisation"
    assert "<@" not in body.split('"""')[2], "a tracker identity is not a chat mention"
    assert "decided_by=who" in body and "said_by=who" in body


def test_the_sweep_is_scheduled_not_only_registered():
    """Registering an activity is not scheduling it — `ensure_all`'s own lesson (refutation 20)."""
    from openfactory.runtime.temporal import schedule, worker

    src = Path("openfactory/runtime/temporal/schedule.py").read_text(encoding="utf-8")
    ensure_all = src[src.index("async def ensure_all("):src.index("RETENTION_DAYS")]
    assert "ensure_card_question_sweeps" in ensure_all
    assert schedule.CARD_QUESTION_EVERY_HOURS == 1
    assert acts.card_question_sweep in worker.WORKER_ACTIVITIES
    assert acts.gather_context in worker.WORKER_ACTIVITIES
    wsrc = Path("openfactory/runtime/temporal/worker.py").read_text(encoding="utf-8")
    assert "CardQuestionSweepWorkflow," in wsrc.split("workflows=[")[1].split("]")[0]
