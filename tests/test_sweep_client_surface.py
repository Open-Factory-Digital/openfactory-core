"""The broad sweep's client-surface findings, each pinned by the failure that confirmed it.

Every test here drives the PRODUCTION path (`handle`, `confirm_by_click`, `role.answer`, the voice
composers) — never a copy of its logic. The classes covered, from the sweep of 2026-07-30:

  - the pt-BR sentence-start "No …" read as a rejection (and it DESTROYED the staged proposal)
  - the accept branch decorating the actor into `<@U…>` and failing its own authz one call deeper
  - a proposal staged in a thread, unreachable from a bare channel-level "sim"
  - `_consume`'s `or waiting` fallback turning a confirmation race into a double write
  - accept fingerprints hashing identically for different requirements
  - a "sim" after the TTL silently swallowed by the conversational model
  - raw machinery (git stderr, board errors, exception text) reaching the client channel
  - the discarded proposal still described as pending in the very next prompt
  - click-reject demanding an admin while the typed "não" honoured the requester
  - the marker strip exercised end-to-end through `role.answer`, not through the regexes
"""

from __future__ import annotations

import time

import pytest

import openfactory.product.channel as pc
from openfactory.contracts import AgentRunResult
from openfactory.product.role import ProductRole

# ── stand-ins at the production seams ────────────────────────────────────────────────────────────

class _Product:
    enabled = True
    slack_channel = "C1"
    agent_name = "Nina"

    def __init__(self, admins):
        self.admins = admins


class _Project:
    name = "books"
    language = "pt-BR"

    def __init__(self, admins=("UADM",)):
        self.product = _Product(list(admins))


class _Result:
    def __init__(self, ok=True, url="", ref="", detail="", existed=False, merged=True):
        self.ok, self.url, self.ref = ok, url, ref
        self.detail, self.existed, self.merged = detail, existed, merged


class _Module:
    """Only what the branches under test actually touch — anything else raising is the point."""

    def __init__(self):
        self.accepted_with = None
        self.promoted = None
        self.broke_down = None

    def accept(self, number, *, actor):
        self.accepted_with = (number, actor)
        return _Result(ok=True)

    def break_down(self, number, *, actor):
        """Accepting decomposes now, so this branch touches it. Present rather than absent on
        purpose: the composer catches everything, so a fake missing this method would let these
        tests keep passing while asserting a reply production no longer produces."""
        self.broke_down = (number, actor)
        return [_Result(ok=True, ref="#901")]

    def promote(self, numbers, *, actor):
        self.promoted = (list(numbers), actor)
        return [_Result(ok=True, ref="#7"),
                _Result(ok=False, detail="fatal: branch req/0009-x rejected by remote")]

    def confirmed(self, text, *, proposal):  # pragma: no cover — is_yes short-circuits it
        return "neither"


@pytest.fixture(autouse=True)
def _clean_stage(monkeypatch):
    """No test leaves a staged proposal or a tombstone behind — the leak class this sweep found
    in its own test files."""
    # THE STATE LIVES IN `openfactory/product/staging.py` NOW (#98 slice 3), so isolation is
    # applied THERE. Rebinding the re-export on `product_channel` would leave the code
    # reading the original dict: the fixture would look like it isolates and would not,
    # which is how a staged proposal leaked into the next test when this move was first
    # attempted — with the symptom landing far from the cause.
    from openfactory.product import staging as _staging
    monkeypatch.setattr(_staging, "_PENDING", {})
    monkeypatch.setattr(_staging, "_EXPIRED_TOMBSTONES", {})
    from openfactory.memory import transcript

    monkeypatch.setattr(transcript, "record", lambda *a, **k: None)
    yield


# ── the "No …" preposition is not a rejection ────────────────────────────────────────────────────

def test_a_portuguese_sentence_starting_with_no_is_not_a_rejection():
    for sentence in ("No sistema de férias o saldo está errado",
                     "No fechamento do mês isso trava",
                     "No momento não sei dizer"):
        assert not pc.is_no(sentence), sentence


def test_a_bare_english_no_still_counts():
    for sentence in ("no", "No", "no.", "No!", " no, "):
        assert pc.is_no(sentence), sentence
    assert pc.is_no("não, pode deixar")
    assert pc.is_no("nao é isso")


# ── the accept branch passes the RAW id; the module decorates ────────────────────────────────────

def test_accept_confirmation_passes_the_raw_slack_id():
    project, module = _Project(admins=["UADM"]), _Module()
    pc.remember("C1", {"kind": "accept", "number": 3, "channel": "C1",
                       "asked_by": "<@UADM>"})
    reply = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)
    assert module.accepted_with == (3, "UADM"), reply
    assert "<@" not in (module.accepted_with[1] or "")


# ── a proposal staged in a thread is confirmable from channel level ──────────────────────────────

def test_a_thread_staged_proposal_is_found_by_a_bare_channel_yes():
    project, module = _Project(admins=["UADM"]), _Module()
    pc.remember("171234.5678", {"kind": "accept", "number": 5, "channel": "C1",
                                "asked_by": "<@UADM>"})
    pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)
    assert module.accepted_with == (5, "UADM")
    assert pc.pending_for("171234.5678") is None, "consumed from where it was staged"


# ── a lost race must not write twice, and must not pretend it did ───────────────────────────────

def test_a_confirmation_that_lost_the_race_neither_writes_nor_lies(monkeypatch):
    project, module = _Project(admins=["UADM"]), _Module()
    entry = {"kind": "accept", "number": 3, "channel": "C1", "staged_at": time.time()}
    # the other consumer popped between the read and the consume: _PENDING is already empty
    monkeypatch.setattr(pc, "find_waiting", lambda t, c="", project=None: ("C1", entry))
    reply = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)
    assert module.accepted_with is None
    from openfactory.product.voice import proposal_already_handled

    assert reply == proposal_already_handled(language="pt-BR")


def test_a_yes_writes_from_the_PROPOSAL_IT_WAS_JUDGED_AGAINST_not_from_the_key():
    """VERIFICATION AND CONSUMPTION ARE ONE ACT, and for a long time they were two with the network
    between them. The handler reads the staged entry once, chooses its branch from it — and then
    sends the receipt, a chat.postMessage on every confirmed write, before popping. Socket Mode
    dispatches with concurrency=10, so the client's next message runs in parallel and lands inside
    that window; the pop then took whatever was under the key.

    Driven at the receipt itself, which is the real seam: staged "requisito 3", answered "sim", and
    requisito 9 — proposed a moment later and confirmed by nobody — was the one written.
    """
    project, module = _Project(admins=["UADM"]), _Module()
    pc.remember("C1", {"kind": "accept", "number": 3, "channel": "C1", "asked_by": "<@UADM>"})

    def _receipt(_text):
        # the second message, on another listener thread, while this receipt is in flight
        pc.remember("C1", {"kind": "accept", "number": 9, "channel": "C1",
                           "asked_by": "<@UADM>"})

    reply = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1",
                      module=module, notify=_receipt)

    assert module.accepted_with is None, (
        f"a yes shown one proposal performed another: {module.accepted_with}")
    from openfactory.product.voice import proposal_already_handled

    assert reply == proposal_already_handled(language="pt-BR"), reply
    assert pc.pending_for("C1") is not None, "the newcomer was eaten by somebody else's yes"


def test_a_proposal_staged_DURING_THE_JUDGEMENT_is_not_what_the_judge_approved():
    """The same defect through the slower seam, and the one that costs seconds rather than a
    round-trip. Anything that is not a bare "sim" goes to a model, which is shown a summary of the
    entry read BEFORE the call — so the sentence is judged against one proposal and the write was
    taken from whatever replaced it. Here that is the queue: two tickets were argued for, approved,
    and a different list was promoted — the one action on this surface that spends money.
    """
    project = _Project(admins=["UADM"])

    class _Judging(_Module):
        def confirmed(self, text, *, proposal):
            assert "7" in proposal, f"the judge was shown the wrong proposal: {proposal}"
            pc.remember("C1", {"kind": "queue", "numbers": [1], "channel": "C1"})
            return "approve"

    module = _Judging()
    pc.remember("C1", {"kind": "queue", "numbers": [7, 9], "channel": "C1"})

    reply = pc.handle(project, text="isso mesmo, pode mandar", user="UADM", thread="C1",
                      channel="C1", module=module)

    assert module.promoted is None, f"money was spent on a list nobody approved: {module.promoted}"
    from openfactory.product.voice import proposal_already_handled

    assert reply == proposal_already_handled(language="pt-BR"), reply


# ── two staged accepts must never share a fingerprint ────────────────────────────────────────────

def test_accept_fingerprints_differ_by_requirement():
    token_for_3 = pc.proposal_token("C1", {"kind": "accept", "number": 3})
    token_for_7 = pc.proposal_token("C1", {"kind": "accept", "number": 7})
    assert token_for_3 != token_for_7


def test_draft_fingerprints_differ_by_criteria():
    class _Draft:
        title = "Backup mensal"
        body = ""
        statement = ""

        def __init__(self, musts):
            self.must_be_true = musts

    class _Answer:
        def __init__(self, musts):
            self.draft = _Draft(musts)

    a = pc.proposal_token("C1", {"kind": "draft", "answer": _Answer(["gera todo dia 1"])})
    b = pc.proposal_token("C1", {"kind": "draft", "answer": _Answer(["gera todo dia 5"])})
    assert a != b


# ── a yes after the TTL hears "expired", once ────────────────────────────────────────────────────

def _expire_the_stage(key="C1"):
    pc._PENDING[key]["staged_at"] = time.time() - pc.PROPOSAL_TTL_SECONDS - 1


class _QuietModule(_Module):
    """The conversational tail for messages that fall through the staging gates."""

    def settle_acceptance(self, text):
        return None

    def context(self):
        class _Ctx:
            available = False
            reason = "not needed here"

        return _Ctx()


def test_a_yes_on_an_expired_proposal_is_answered_not_swallowed():
    project, module = _Project(admins=["UADM"]), _QuietModule()
    pc.remember("C1", {"kind": "accept", "number": 3, "channel": "C1"})
    _expire_the_stage()
    reply = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)
    from openfactory.product.voice import proposal_expired

    assert reply == proposal_expired(language="pt-BR")
    assert module.accepted_with is None


def test_the_expiry_notice_is_owed_to_exactly_one_late_yes():
    project, module = _Project(admins=["UADM"]), _QuietModule()
    pc.remember("C1", {"kind": "accept", "number": 3, "channel": "C1"})
    _expire_the_stage()
    first = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)
    second = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)
    assert first != second, "the tombstone must be consumed by the notice it produced"


def test_a_click_on_an_expired_proposal_hears_expired_not_gone():
    project = _Project(admins=["UADM"])
    pc.remember("C1", {"kind": "accept", "number": 3, "channel": "C1"})
    token = pc.proposal_token("C1", pc._PENDING["C1"])
    _expire_the_stage()
    reply = pc.confirm_by_click(project, token=token, approved=True, user="UADM")
    from openfactory.product.voice import proposal_expired, proposal_gone

    assert reply == proposal_expired(language="pt-BR")
    assert reply != proposal_gone(language="pt-BR")


def test_a_fresh_proposal_clears_the_expiry_tombstone():
    project, module = _Project(admins=["UADM"]), _Module()
    pc.remember("C1", {"kind": "accept", "number": 3, "channel": "C1"})
    _expire_the_stage()
    assert pc.pending_for("C1") is None  # expiry observed, tombstone written
    pc.remember("C1", {"kind": "accept", "number": 4, "channel": "C1",
                       "asked_by": "<@UADM>"})
    pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)
    assert module.accepted_with == (4, "UADM"), "the new proposal, not an expiry notice"


# ── refusing by click follows the typed rule: admin OR requester ─────────────────────────────────

def test_the_requester_may_reject_their_own_proposal_by_click():
    project = _Project(admins=["UADM"])
    pc.remember("C1", {"kind": "draft", "asked_by": "<@UREQ>", "channel": "C1"})
    token = pc.proposal_token("C1", pc._PENDING["C1"])
    reply = pc.confirm_by_click(project, token=token, approved=False, user="UREQ")
    from openfactory.product.voice import proposal_rejected

    assert reply == proposal_rejected(language="pt-BR")
    assert pc.pending_for("C1") is None


def test_a_stranger_may_not_destroy_a_proposal_by_click():
    project = _Project(admins=["UADM"])
    pc.remember("C1", {"kind": "draft", "asked_by": "<@UREQ>", "channel": "C1"})
    token = pc.proposal_token("C1", pc._PENDING["C1"])
    pc.confirm_by_click(project, token=token, approved=False, user="USTRANGER")
    assert pc.pending_for("C1") is not None, "an unauthorised reject must not consume"


def test_the_requester_still_may_not_approve_by_click():
    project = _Project(admins=["UADM"])
    pc.remember("C1", {"kind": "draft", "asked_by": "<@UREQ>", "channel": "C1"})
    token = pc.proposal_token("C1", pc._PENDING["C1"])
    pc.confirm_by_click(project, token=token, approved=True, user="UREQ")
    assert pc.pending_for("C1") is not None, "approval stays admin-only, and must not consume"


# ── no machinery reaches the channel ─────────────────────────────────────────────────────────────

def test_a_partial_queue_failure_is_sanitised_like_the_total_one():
    project, module = _Project(admins=["UADM"]), _Module()
    pc.remember("C1", {"kind": "queue", "numbers": [7, 9], "channel": "C1"})
    reply = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)
    assert module.promoted == ([7, 9], "UADM")
    assert "fatal:" not in reply and "branch" not in reply and "req/0009" not in reply


def test_board_read_errors_never_reach_the_channel_raw():
    class _BrokenBoard(_QuietModule):
        def triage_board(self):
            return None, "could not read acmetech/books.git (HTTP 404)"

        def review_needs_action(self):
            return None, "gh: Not Found (HTTP 404) — check the repository slug"

        def propose_queue(self):
            return None, None, "fatal: repository handle stale"

    project, module = _Project(admins=["UADM"]), _BrokenBoard()
    for intent in ("triage", "needs_action", "queue"):
        reply = pc._run_intent(project, intent, {}, module=module, lang="pt-BR",
                               user="UADM", thread="C1", channel="C1")
        assert reply, intent
        for leak in ("HTTP", "404", ".git", "fatal:", "gh:", "acmetech"):
            assert leak not in reply, f"{intent} leaked {leak!r}: {reply}"


def test_a_baseline_failure_detail_is_sanitised_by_the_composer():
    from openfactory.product.voice import baseline_done

    text = baseline_done(ok=False, detail="fatal: could not clone repo acme/docs.git",
                         language="pt-BR", agent_name="Nina")
    for leak in ("fatal:", ".git", "clone"):
        assert leak not in text
    assert "Nina" in text


def test_the_baseline_SUCCESS_carries_no_pull_request_link(monkeypatch):
    """The failure branch was sanitised and the HAPPY one, every single time, put a forge URL —
    repository slug and all — into an accounting firm's channel. Driven through the real
    `_baseline_reply`, on its own daemon thread, with a fake only at the `build_channel().say`
    seam: everything between the gesture and the client is production code.

    The link was never an affordance. The entries sit on a branch nobody merged, so there is
    nothing the client can do on that page — and `_DIAGNOSTIC`, the rule this module uses to decide
    what a client may read, classes `https?://` as machinery on every OTHER path.
    """
    import threading

    import openfactory.adapters.channel as channel_mod

    said: list[str] = []
    announced = threading.Event()

    class _Chan:
        def say(self, *, project, channel, text):
            said.append(text)
            announced.set()
            return True

    monkeypatch.setattr(channel_mod, "build_channel", lambda project: _Chan())

    class _Surveying(_QuietModule):
        def baseline(self):
            return _Result(ok=True,
                           url="https://github.com/AcmeCorp/acme-books-docs/pull/12")

    pc._baseline_reply(_Project(admins=["UADM"]), _Surveying(), "Nina", "UADM", None)

    assert announced.wait(5), "the baseline finished and never reached the channel"
    from openfactory.product.voice import jargon_in

    assert "http" not in said[0], f"a forge URL reached the client channel: {said[0]}"
    assert "acme-books-docs" not in said[0], f"a repository slug reached the client: {said[0]}"
    assert jargon_in(said[0]) == [], said[0]
    assert "Nina" in said[0] and "observação" in said[0], said[0]


def test_no_message_this_module_can_SAY_carries_a_link():
    """The structural half, because "the failure branch learned it and the success branch did not"
    is this repository's signature defect and it landed here twice — `written_up` killed the leak
    for requirements and `baseline_done`, written afterwards, put it straight back.

    Read off the catalogues rather than off the composers: every client-facing sentence in
    `voice.py` is a literal in an upper-case table, so a link can only enter by being written into
    one. Regex constants are skipped — they are the machinery that DETECTS links, and `_URL_RE` and
    `_DIAGNOSTIC` both have to contain one to do their job.
    """
    import ast
    from pathlib import Path

    # THE ONE ADDRESS A CLIENT CAN ACT ON IS THEIR OWN PRODUCT (#122). This rule is about
    # MECHANICS reaching somebody who cannot use them — a repository slug, a pull request, a CI
    # run — and it was written when every URL this module could hold was one of those. The
    # invitation to look at a change that is live is the opposite: without the address, the message
    # is "it's up somewhere, go and find it", which costs the reader a reply to learn where.
    #
    # Exempted BY NAME and held to a stricter bar in `test_the_deploy_invitation_sends_them_to_
    # THEIR_product`: it must be a `{url}` the caller fills from the client's own manifest, never a
    # literal, and never one of ours.
    CLIENT_OWNED = {"_DEPLOY_INVITATION"}

    tree = ast.parse(Path("openfactory/product/voice.py").read_text())
    offenders = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if getattr(node.targets[0], "id", "") in CLIENT_OWNED:
            continue
        catalogue = node.value
        if not isinstance(catalogue, (ast.Constant, ast.Dict, ast.Tuple, ast.List)):
            continue
        if any(isinstance(c, ast.Call) for c in ast.walk(catalogue)):
            continue        # a compiled pattern, not something anybody is shown
        for text in ast.walk(catalogue):
            if isinstance(text, ast.Constant) and isinstance(text.value, str) and (
                    "{url}" in text.value or "http" in text.value):
                offenders.append((getattr(node.targets[0], "id", "?"), text.lineno))

    assert not offenders, (
        f"a client-facing message carries a link at {offenders} — a URL in this channel is a "
        "repository slug in front of somebody who cannot act on one (AUDIENCE_RULES)")


def test_the_deploy_invitation_sends_them_to_THEIR_product_and_nothing_else():
    """The exemption above, paid for. The one link this module may carry has to be the client's
    own address, supplied by their manifest — so it is a placeholder, never a literal, and the
    rendered sentence must still be free of every mechanic the rest of the rule bans."""
    import ast
    from pathlib import Path

    from openfactory.product.voice import deploy_invitation, jargon_in

    tree = ast.parse(Path("openfactory/product/voice.py").read_text())
    catalogue = next(n.value for n in tree.body
                     if isinstance(n, ast.Assign)
                     and getattr(n.targets[0], "id", "") == "_DEPLOY_INVITATION")
    for text in ast.walk(catalogue):
        if isinstance(text, ast.Constant) and isinstance(text.value, str):
            assert "http" not in text.value, (
                "the invitation hardcodes a URL — the address belongs to the client's manifest")

    for lang in ("pt-BR", "en"):
        said = deploy_invitation(what="the signup age column", url="https://stg.example.com/",
                                 language=lang)
        assert "https://stg.example.com" in said
        assert jargon_in(said) == [], said
        for mechanic in ("github", "pull request", "commit", "workflow", "#", "staging"):
            assert mechanic not in said.lower(), (
                f"the invitation leaks {mechanic!r}: {said}")


def test_the_stale_button_reply_names_no_machinery():
    from openfactory.product.voice import (
        jargon_in,
        proposal_already_handled,
        proposal_expired,
        proposal_gone,
    )

    for text in (proposal_gone(language="pt-BR"), proposal_expired(language="pt-BR"),
                 proposal_already_handled(language="pt-BR")):
        assert "worker" not in text.lower()
        assert jargon_in(text) == [], text


# ── a rejection clears the prompt's notion of "pending" ─────────────────────────────────────────

def test_after_a_rejection_the_prompt_no_longer_claims_a_pending_proposal(monkeypatch):
    seen = {}

    class _Talky(_QuietModule):
        def confirmed(self, text, *, proposal):
            return "reject"

        def context(self):
            class _Ctx:
                available = True
                reason = ""

            return _Ctx()

        def close_decisions_answered(self, *, channel=""):
            pass

        def answer(self, text, *, conversation="", pending=""):
            seen["pending"] = pending

            class _Ans:
                ok = True
                text = "entendi — me diz de novo como você prefere."
                decisions = []
                is_defect = False
                is_request = False

            return _Ans()

    from openfactory.memory import transcript

    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    monkeypatch.setattr(transcript, "render", lambda *a, **k: "")
    project = _Project(admins=["UADM"])
    pc.remember("C1", {"kind": "draft", "asked_by": "<@UADM>", "channel": "C1"})
    pc.handle(project, text="não é bem isso — o backup é semanal, não mensal",
              user="UADM", thread="C1", channel="C1", module=_Talky())
    assert seen["pending"] == "", "the discarded proposal survived into the prompt"
    assert pc.pending_for("C1") is None


# ── the person's turn is on the record BEFORE the slow part ──────────────────────────────────────

def test_the_incoming_turn_is_recorded_before_the_module_answers(monkeypatch):
    order = []

    class _Chatty(_QuietModule):
        def context(self):
            class _Ctx:
                available = True
                reason = ""

            return _Ctx()

        def close_decisions_answered(self, *, channel=""):
            pass

        def answer(self, text, *, conversation="", pending=""):
            order.append("answer")

            class _Ans:
                ok = True
                text = "tudo certo por aqui."
                decisions = []
                is_defect = False
                is_request = False

            return _Ans()

    from openfactory.memory import transcript
    from openfactory.product import intents as product_intents

    monkeypatch.setattr(transcript, "record",
                        lambda *a, **k: order.append(f"record:{k.get('role')}"))
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    monkeypatch.setattr(transcript, "render", lambda *a, **k: "")
    # no intent shortcut: this test is about the conversational path, the slow one
    monkeypatch.setattr(product_intents, "match_intent", lambda t: None)
    pc.handle(_Project(), text="como estamos?", user="U2", thread="C1", channel="C1",
              module=_Chatty())
    assert order[0] == "record:person", order
    assert "answer" in order and order.index("record:person") < order.index("answer")


# ── the marker strip, exercised through the PRODUCTION answer path ───────────────────────────────

class _Harness:
    name = "canned"

    def __init__(self, answer):
        self.answer = answer

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        return AgentRunResult(ok=True, summary=self.answer)


class _Sandbox:
    def run(self, **kw):
        return 0, ""


def _ws():
    from openfactory.adapters.sandbox.base import Workspace

    return Workspace(path="/tmp", branch="main", base_branch="main")


def test_no_marker_survives_the_production_answer_path():
    # the three historical leak causes, together, through the REAL strip site: a label past the
    # parser's 400-char cap (dropped LOUDLY by the safety net — that is its documented design),
    # a label with brackets inside it (the third leak's cause), and a marker no parser knows
    long_label = "Definir " + "x" * 440
    raw = ("Aqui está o resumo.\n"
           f"[[DECISAO: {long_label}]]\n"
           "[[DECISAO: Priorizar o card [Product] Decrypt na fila]]\n"
           "[[MARCADOR_NOVO: algo que parser nenhum conhece]]\n"
           "E mais um parágrafo.")
    answer = ProductRole(_Harness(raw)).answer(sandbox=_Sandbox(), workspace=_ws(),
                                               question="como estamos?")
    assert answer.ok
    assert "[[" not in answer.text and "]]" not in answer.text, answer.text
    assert "Aqui está o resumo." in answer.text and "E mais um parágrafo." in answer.text
    # BOTH parse now — the bracketed one (the third leak's cause) and the over-long one, whose
    # length ceiling was removed after it lost a real decision in production on 2026-07-31
    assert any("[Product] Decrypt" in d for d in answer.decisions), answer.decisions
    assert any(len(d) > 400 for d in answer.decisions), [len(d) for d in answer.decisions]


# ── the decision marker has no length cliff ─────────────────────────────────────────────────────

def test_a_LONG_decision_is_recorded_not_lost():
    """2026-07-31, in production: Nina asked for a decision about how to identify the documents
    left out of the totals. The label ran past 400 characters, the parser's ceiling dropped it,
    and the commitment was never recorded and never chased — it reached a person only because
    somebody happened to be reading the channel.

    The ceiling was always redundant: the tempered class cannot cross `]]` or a newline, so the
    delimiter bounds the match. Length is a storage concern, and `record_decisions` truncates.
    """
    label = ("No requisito 3, fechar a pergunta em aberto sobre identificação dos documentos que "
             "ficaram fora dos totais adotando a regra: nomear o documento quando o nome for "
             "legível, e quando não for, identificar pela data de entrada e pela posição no mês, "
             "ancorada no momento em que a saída foi produzida. " + "detalhe adicional. " * 12)
    assert len(label) > 400, "the fixture stopped reproducing the failure"
    raw = f"Resumo.\n[[DECISAO: {label}]]\nFim."

    answer = ProductRole(_Harness(raw)).answer(sandbox=_Sandbox(), workspace=_ws(),
                                               question="e agora?")

    assert answer.decisions and answer.decisions[0].startswith("No requisito 3"), answer.decisions
    assert "[[" not in answer.text and "]]" not in answer.text


def test_two_decisions_on_one_line_stay_two():
    """The reason the tempered class exists — dropping the ceiling must not resurrect the bug where
    the shortest legal match grew past the first `]]`."""
    raw = "x\n[[DECISAO: primeira coisa a decidir]] meio [[DECISAO: segunda coisa a decidir]]\ny"

    answer = ProductRole(_Harness(raw)).answer(sandbox=_Sandbox(), workspace=_ws(), question="?")

    assert len(answer.decisions) == 2, answer.decisions
    assert answer.decisions[0] == "primeira coisa a decidir"
    assert answer.decisions[1] == "segunda coisa a decidir"


def test_opening_a_file_to_READ_is_not_a_claim_of_writing():
    """Her most desirable sentence — "I went and opened the code" — set off the false-claim alarm.
    Six firings in production, six false positives, this the clearest of them."""
    from openfactory.product.voice import claims_a_write

    assert claims_a_write("Abri o requisito 3 e o código que ele cita.") == ""
    assert claims_a_write("Abrimos o arquivo e conferimos linha a linha.") == ""
    # and a REAL claim still fires
    assert claims_a_write("Registrado o Requisito 1. Vai para o time conferir.")
    assert claims_a_write("Coloquei na fila, nesta ordem: #7, #9.")


# ── the most-asked question on the surface answered in operator prose ────────────────────────────

def test_como_estamos_never_answers_with_the_operators_line():
    """WHAT THE CLIENT ACTUALLY READ, every day, to the question he asks most:

        product module ready on acmecorp/acme-books-documentation — 4 requirements,
        1 accepted — 0 errors, 1 warnings · 1 aviso(s) de configuração: the source repo does
        not declare docs_repo … in its .sdlc/project.yaml

    A repository slug, English prose, a warning count and a file path — to somebody who bought a
    product that needs no developer. `status_line()` is `ProductContext.health()`, written for the
    panel and the log, and this branch handed it straight to a business channel.
    """
    from openfactory.product.voice import jargon_in

    class _Corpus:
        requirements = [object(), object(), object(), object()]

        def promises(self):
            return [object()]

    class _Ctx:
        available = True
        reason = ""
        corpus = _Corpus()

    class _M(_QuietModule):
        def context(self):
            return _Ctx()

        def status_line(self):
            raise AssertionError("the operator's health line reached the client channel")

    reply = pc._run_intent(_Project(), "status", {}, module=_M(), lang="pt-BR",
                           user="UADM", thread="C1", channel="C1")

    assert "4" in reply and "1" in reply, reply
    assert jargon_in(reply) == [], reply
    for leak in ("acmecorp/", "docs_repo", ".openfactory", "product module", "warnings", "errors"):
        assert leak not in reply, f"{leak!r} reached the client: {reply}"


def test_a_base_it_cannot_open_is_never_reported_as_an_empty_one():
    """"nothing is written yet" and "I could not open it" are opposite facts, and one of them has
    a client believing their requirements are gone."""
    class _Ctx:
        available = False
        reason = "could not clone acmecorp/acme-books-documentation"
        corpus = None

    class _M(_QuietModule):
        def context(self):
            return _Ctx()

    reply = pc._run_intent(_Project(), "status", {}, module=_M(), lang="pt-BR",
                           user="UADM", thread="C1", channel="C1")

    assert "ainda não há nada escrito" not in reply, reply
    assert "não estou conseguindo abrir" in reply.lower(), reply
    assert "acmecorp" not in reply and "clone" not in reply, reply
