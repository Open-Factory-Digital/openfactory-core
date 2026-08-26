"""The client's "funcionou" is what puts software in front of their users — not an operator's.

THE EVIDENCE. The pipeline parked at `AWAITING_PROD_APPROVAL` for days waiting for a signal FROM
THE PANEL, with a password, given by an operator. The person who knows whether the change is right
is the client, and they were the only one not asked. Nothing on the factory board contradicted "no
dev needed" harder: a factory that needs an operator to cut a release is not the factory being
sold.

EVERY PIECE ALREADY EXISTED — the durable park, `approve_job` querying the gate before signalling,
the acceptance loop that asks a client whether something worked and reads the answer with a model
judge. What was missing was the wire, which is why the module under test is small and why most of
this file is about the three rules that make a RELEASE answer different from an ordinary one:

    ambiguity is REFUSED, not named   a wrong guess here ships the wrong thing to real users
    authorisation is re-checked        reading a message is not an act; releasing is
    the act is observed before claimed a client told "subiu" over a signal that reached nothing is
                                       the worst outcome available on this path

AND THE OPERATOR PATH IS UNTOUCHED. `bot.act_job` carries a deliberate guardrail — Slack may only
resume/skip/ack, so a release "can never be driven from here". That is the TECH-LEAD surface and it
stays exactly as it was; this is the other one (ADR-0026). A test below pins that, because the
cheapest way to have built this feature was to widen that guardrail, and doing so would have merged
the two surfaces the platform keeps apart on purpose.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import add_ons
import pytest

import openfactory.product.channel as pc
from openfactory.memory.ledger import ACCEPTANCE, DELIVERY, open_loop
from openfactory.product import followup


class _Product:
    def __init__(self, admins=("UADM",)):
        self.admins = list(admins)
        self.agent_name, self.docs_repo, self.channel_id = "Nina", "a/docs", "C1"
        self.enabled, self.docs_branch, self.staging_url = True, "main", "https://staging.x"


class _Project:
    name, language = "books", "pt-BR"

    def __init__(self, admins=("UADM",)):
        self.product = _Product(admins)


def _release_loop(issue=512, requirement="0006"):
    return followup.release_of(issue, channel="C1", ts="2026-07-31T10:00:00+00:00",
                               requirement=requirement, where="https://staging.x")


def _plain_loop(subject="0006"):
    return open_loop(ACCEPTANCE, subject, owner=followup.OWNER, ts="2026-07-31T10:00:00+00:00",
                     about="C1", context={"asked_by": "<@UADM>"})


class _Module:
    def __init__(self, settled):
        self._settled = settled

    def settle_acceptance(self, _text):
        return self._settled

    def close_decisions_answered(self, **_):
        return 0

    def context(self):
        from types import SimpleNamespace

        class _Corpus:
            def by_number(self, _n):
                return None

        return SimpleNamespace(available=True, corpus=_Corpus(), reason="")


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
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    yield


@pytest.fixture
def released(monkeypatch):
    """Records every release() call, so the tests assert on the ACT and not on the sentence."""
    calls: list[tuple] = []

    def _fake(project, issue, *, approver, comment=""):
        calls.append((getattr(project, "name", ""), str(issue), approver))
        return True, ""

    monkeypatch.setattr("openfactory.product.release.release", _fake)
    return calls


def _say(module, text="funcionou", user="UADM", project=None):
    return pc.handle(project or _Project(), text=text, user=user, thread="C1", channel="C1",
                     module=module)


# ── 1. the bridge ──────────────────────────────────────────────────────────────────────────────

def test_the_clients_yes_releases_production(released):
    said = _say(_Module(("worked", _release_loop(512), False)))

    assert released == [("books", "512", "UADM")], released
    assert "produção" in said, said
    assert "você quem liberou" in said, "the record of who released is not claimed to them"


def test_a_NO_releases_nothing_and_says_so(released):
    said = _say(_Module(("did-not-work", _release_loop(512), False)), text="não funcionou")

    assert released == [], "a rejection released production"
    assert "não subi nada" in said.lower(), said
    assert "time" in said, "the client was not told what happens to what they reported"


def test_an_ORDINARY_delivery_acceptance_is_untouched(released):
    """The branch must not change any other answer — every previous acceptance still reads as it
    did, and cannot reach a release."""
    said = _say(_Module(("worked", _plain_loop("0006"), False)))

    assert released == [], "an ordinary delivery acceptance signalled a production release"
    assert "produção" not in said, said


# ── 2. the three rules that make it different ─────────────────────────────────────────────────

def test_AMBIGUITY_is_refused_rather_than_guessed(released):
    """`settle_acceptance` settles the newest and names it when several are waiting — a wrong guess
    normally costs one correction. Here it would ship the wrong software to real users."""
    said = _say(_Module(("worked", _release_loop(512), True)))

    assert released == [], "it guessed which release the client meant and shipped it"
    assert "não subi nada" in said.lower(), said
    assert "número" in said, "the way out was not offered"


def test_somebody_who_may_not_ACT_cannot_release(released):
    said = _say(_Module(("worked", _release_loop(512), False)), user="UOUTRO")

    assert released == [], "an unauthorised person released production"
    assert "produção" not in said or "não" in said.lower(), said


def test_a_job_no_longer_PARKED_is_told_honestly_not_reassuringly(monkeypatch):
    """The gate is re-asked at the moment of the act. Between the question and the answer the job
    may have timed out or been released by somebody else — and a client told "subiu" over a signal
    that reached nothing is the single worst outcome on this path."""
    monkeypatch.setattr("openfactory.product.release.release",
                        lambda p, i, *, approver, comment="": (False, "o #512 não está mais "
                                                                     "esperando essa liberação"))

    said = _say(_Module(("worked", _release_loop(512), False)))

    assert "não está mais esperando" in said, said
    assert "subindo" not in said, f"it claimed a release that did not happen: {said}"


def test_a_signal_that_FAILED_never_reads_as_a_release(monkeypatch, caplog):
    from openfactory.product import release as rel

    async def _boom(*_a, **_k):
        raise RuntimeError("temporal unreachable")

    monkeypatch.setattr(rel, "_awaiting", _boom)
    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        ok, why = rel.release(_Project(), 512, approver="UADM")

    assert ok is False
    assert "Nada subiu" in why, why
    assert any("OPENFACTORY_RELEASE_SIGNAL_FAILED" in r.getMessage() for r in caplog.records), (
        "a client approved a production release, it did not happen, and no log says so")


# ── 3. what the client is asked, in their words ───────────────────────────────────────────────

def test_the_question_uses_NO_pipeline_vocabulary():
    """The whole point of the bridge is that the person who knows whether the change is right does
    not have to learn the words the pipeline uses to talk about itself."""
    asked = followup.release_question(requirement="0006", where="https://staging.x",
                                      agent_name="Nina", language="pt-BR")
    # THE RULE IS ABOUT THE PROSE, not about the address. Whatever the operator configured as the
    # place to try it is their string, and it may well contain the word — asserting over it would
    # be testing the deployment's URL rather than how she writes.
    prose = asked.replace("https://staging.x", "«o endereço»").lower()

    for jargon in ("staging", "deploy", "release", "aprovação de produção", "merge", "pipeline"):
        assert jargon not in prose, f"{jargon!r} reached the client: {asked}"
    assert "ambiente de testes" in asked
    assert "https://staging.x" in asked, "the address the client needs was dropped"


def test_the_question_says_what_the_YES_will_DO():
    """A confirmation whose consequence is unstated is not one — and this one puts software in
    front of the client's own users."""
    asked = followup.release_question(agent_name="Nina", language="pt-BR")

    assert "coloca no ar" in asked, asked
    assert "não" in asked and "sobe" in asked, "the consequence of a no is not stated either"


def test_a_missing_staging_URL_does_not_hold_the_pipeline():
    """Empty costs the address and nothing else. Refusing to ask because nobody configured a URL
    would hold a finished release over a missing courtesy."""
    asked = followup.release_question(requirement="0006", where="",
                                      agent_name="Nina", language="pt-BR")

    assert "Para experimentar" not in asked
    assert "coloca no ar" in asked, "the release stopped being offered"


def test_the_requirement_is_read_off_the_OPEN_loops_and_never_invented():
    waiting = [open_loop(DELIVERY, "0006", owner=followup.OWNER, ts="t",
                         context={"issues": "511,512"})]

    assert followup.requirement_behind(512, waiting) == "0006"
    assert followup.requirement_behind(999, waiting) == "", (
        "an issue nothing claims was given a requirement it does not belong to")


def test_only_a_release_loop_is_read_as_one():
    assert followup.is_release(_release_loop(512)) == "512"
    assert followup.is_release(_plain_loop()) == ""


def test_the_version_is_DETERMINISTIC():
    """A retried approval must tag the same release. Two tags for one approval is a history nobody
    can read backwards."""
    from openfactory.product.release import version_for

    assert version_for(512) == version_for("#512") == version_for("512")


# ── 4. the operator surface stays exactly as it was ───────────────────────────────────────────

def test_the_TECH_LEAD_path_still_cannot_drive_a_release():
    """The cheapest way to build this was to widen `act_job`'s guardrail. Doing so would have
    merged the two surfaces the platform keeps apart on purpose (ADR-0026), so it is pinned:
    that path allows resume/skip/ack and nothing else, and it names no release signal."""
    src = add_ons.source("openfactory/runtime/slack/bot.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "act_job")
    # `ast.unparse` normalises quoting, so the guardrail is asserted on the normalised form rather
    # than on how it happens to be typed today.
    body = ast.unparse(fn)

    _SLACK_MAY = add_ons.module("openfactory.runtime.slack.bot")._SLACK_MAY

    assert "approve_prod" not in body, "the operator channel grew a production release"
    # The allow-list moved to a module constant with C-23 (act_job is now a mapping onto the
    # action layer), so this asserts the VALUE rather than the typed text — strictly stronger,
    # since a widened list can no longer hide behind different quoting or a longer literal.
    assert _SLACK_MAY == ("resume", "skip", "ack"), "the hard guardrail was loosened"
    assert "_SLACK_MAY" in body, "act_job no longer consults the allow-list at all"
    assert "release_prod" not in body and "openfactory.product.release" not in body, (
        "the operator path reached the client's release machinery")


def test_the_release_goes_through_the_gate_QUERY_and_not_straight_to_the_signal():
    """`approve_job` queries `awaiting_approval` before signalling, which is the only thing
    standing between a stale yes and a release nobody is parked for. Signalling the workflow
    directly from here would skip it — and would look identical in every test above."""
    # CALLS, NOT SUBSTRINGS. `"approve_job" in src` had a LIVE collision on the day of the guard
    # audit (2026-08-17): release.py mentions approve_job in its module docstring AND a comment,
    # so the actual call could be deleted — routing the release straight past the gate query —
    # with this guard still green. An AST walk cannot be satisfied by prose.
    import ast

    tree = ast.parse(Path("openfactory/product/release.py").read_text())
    called = {getattr(n.func, "id", "") or getattr(n.func, "attr", "")
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "approve_job" in called, "the release does not go through the checked entry point"
    assert "_awaiting" in called, "nothing re-asks whether the job is still parked"


def test_the_hourly_round_actually_OFFERS_the_release():
    """Reachability, off the source. The bridge could be perfect and never called: this repository
    has shipped "built, tested, reached by nothing" fourteen times, and an offer nobody makes is a
    client who is never asked and a pipeline that parks for ever."""
    src = Path("openfactory/runtime/temporal/activities.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "techlead_watch")

    assert "_offer_the_release_to_the_client" in ast.unparse(fn), (
        "nothing on any schedule asks the client to try what is parked")
