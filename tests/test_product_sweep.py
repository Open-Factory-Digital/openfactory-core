"""The scheduled board sweep — cadence, silence, and staying read-only.

A scheduled report has one failure mode nobody notices: it becomes wallpaper. So the tests here are
mostly about when it must say NOTHING.
"""

from __future__ import annotations

import pytest

from openfactory.product.intents import match_intent
from openfactory.product.triage import Observation, TriageReport
from openfactory.product.voice import jargon_in, triage_report


def intent_of(text: str) -> str | None:
    """The intent's NAME, for the sentences below — the captures are another file's subject."""
    match = match_intent(text)
    return match[0] if match else None


@pytest.fixture(autouse=True)
def _this_file_speaks_portuguese(monkeypatch):
    """The premise, once: these guards assert the platform's pt-BR sentences.

    They used to inherit pt-BR from the module default. When the product's default became
    English (2026-08-14 — a default IS the product, and this one ships to clients who do not
    speak Portuguese) they went red while nothing had broken. `voice.py` resolves its language
    at CALL time (`language or DEFAULT_LANGUAGE`), so declaring it here reaches every call in
    the file without threading a keyword through each one."""
    import openfactory.product.voice as _voice

    monkeypatch.setattr(_voice, "DEFAULT_LANGUAGE", "pt-BR")



def test_a_quiet_week_posts_no_REPORT_but_still_follows_through():
    """Two different silences, split on purpose.

    The triage REPORT stays behind the freshness gate: a weekly "nothing out of place" trains
    people to skip it, and then it is invisible on the day it matters. But FOLLOW-THROUGH must run
    on every sweep that could read the board — the first version put it after the quiet returns,
    which coupled closing questions, chasing, and "está pronto" to whether NEW rot appeared: the
    week somebody finally wrote the missing criteria was, by construction, a week with nothing new,
    so the question stayed open for ever and the thank-you was never said. Quiet weeks are exactly
    when follow-through is the only thing worth doing."""
    from pathlib import Path

    src = Path("openfactory/runtime/temporal/activities.py").read_text()
    body = src[src.index("async def product_sweep("):]
    reporting = body[body.index("report, error = module.triage_board()"):]
    followed = reporting.index("_product_followup(")
    quiet = reporting.index('return f"clean')
    report_post = reporting.index("triage_report(")
    assert followed < quiet, "follow-through is gated behind the quiet returns again"
    assert quiet < report_post, "the triage report must stay behind the freshness gate"


def test_the_FIRST_sweep_introduces_instead_of_reporting():
    """Nobody has met this role yet. A first message that opens with six board findings is a
    stranger handing you a list."""
    from pathlib import Path

    body = Path("openfactory/runtime/temporal/activities.py").read_text()
    body = body[body.index("async def product_sweep("):]
    arrival = body.index('return "introduced"')
    first_report = body.index("report, error = module.triage_board()")
    assert arrival < first_report, "the arrival must come before any reporting"
    assert "module.introduce()" in body


def test_the_sweep_never_writes_to_the_board():
    """On a schedule exactly as on request: this role has the least context precisely when it is
    told to look at everything at once, and a card it moved at 6am is one somebody has to un-move."""
    from pathlib import Path

    body = Path("openfactory/runtime/temporal/activities.py").read_text()
    body = body[body.index("async def product_sweep("):]
    for forbidden in ("set_column(", "create_ticket(", "close_ticket(", "set_status("):
        assert forbidden not in body, f"the sweep calls {forbidden}"


def test_a_report_is_grouped_by_KIND_not_listed_one_by_one():
    """"seven tickets have nothing that says when they're done" is a decision someone can make.
    Seven separate lines are a chore nobody starts."""
    report = TriageReport(observations=[
        Observation(ticket=n, kind="no-criteria", detail="d") for n in range(1, 8)])
    text = triage_report(report, agent_name="Nina")
    assert "**7**" in text
    assert text.count("•") == 1


def test_a_long_list_is_truncated_with_the_remainder_named():
    report = TriageReport(observations=[
        Observation(ticket=n, kind="no-criteria", detail="d") for n in range(1, 30)])
    text = triage_report(report, limit=5)
    assert "(+24)" in text


def test_the_report_says_out_loud_that_it_changed_nothing():
    text = triage_report(TriageReport(observations=[
        Observation(ticket=1, kind="stalled", detail="d")]))
    assert "Não mudei nada" in text


def test_the_report_speaks_to_a_client():
    text = triage_report(TriageReport(observations=[
        Observation(ticket=1, kind="done-but-open", detail="d"),
        Observation(ticket=2, kind="closed-elsewhere", detail="d")]), agent_name="Nina")
    assert jargon_in(text) == []
    assert "nunca foi encerrado" in text


def test_what_was_skipped_is_reported_as_a_count_not_hidden():
    """"you ignored these" must have an answer, without listing every epic every day."""
    text = triage_report(TriageReport(skipped={"491": "x", "492": "y"}))
    assert "2 de fora" in text


# ── asking for it ───────────────────────────────────────────────────────────────────────────────

def test_a_person_can_ask_for_the_things_it_does_on_its_own():
    assert intent_of("faz a triagem do board") == "triage"
    assert intent_of("se apresenta pro time") == "announce"
    assert intent_of("olha os impedimentos") == "needs_action"
    assert intent_of("status") == "status"


def test_addressing_it_by_name_still_works():
    """People talk to a named agent by name. Anchoring hard at the start made every one of those a
    miss — the most obvious way anyone would actually phrase it. (A real @mention never gets here:
    the listener strips it first.)"""
    assert intent_of("Nina, faz a triagem") == "triage"
    assert intent_of("nina: organiza a casa") == "triage"
    assert intent_of("Nina, como estamos?") == "status"


def test_the_vocative_is_narrow_enough_to_stay_out_of_the_way():
    """Allowing a bare name with no punctuation would turn "quem faz a triagem?" — a real question —
    into a command."""
    assert intent_of("quem faz a triagem?") is None


def test_a_question_ABOUT_those_things_stays_a_question():
    """The two mistakes cost differently: a missed intent means somebody rephrases, a false one
    means the role answers a question by running a board sweep."""
    assert intent_of("o que a triagem disse semana passada?") is None
    assert intent_of("por que esse ticket está parado?") is None
    assert intent_of("preciso que admin edite conciliado") is None


def test_the_schedule_is_per_project():
    """Per project, because the cadence is a judgement about people rather than about throughput:
    a poll every three minutes keeps the floor busy, a report every three minutes trains everyone
    to ignore it."""
    from openfactory.runtime.temporal.schedule import PRODUCT_SCHEDULE_PREFIX

    assert PRODUCT_SCHEDULE_PREFIX == "openfactory-product-sweep"


# ── the scheduled pass reports only what is NEW ─────────────────────────────────────────────────

def test_a_finding_has_a_stable_fingerprint():
    """`ticket:kind`, because the same ticket can rot in two ways at once and fixing one should not
    silence the other."""
    r = TriageReport(observations=[Observation(ticket=9, kind="stalled", detail="d"),
                                   Observation(ticket=9, kind="no-criteria", detail="d")])
    assert r.keys() == ["9:no-criteria", "9:stalled"]


def test_only_what_is_new_survives_the_comparison():
    r = TriageReport(observations=[Observation(ticket=1, kind="no-criteria", detail="d"),
                                   Observation(ticket=2, kind="no-criteria", detail="d")])
    assert [o.ticket for o in r.since(["1:no-criteria"]).observations] == ["2"]


def test_a_first_pass_compares_against_nothing():
    r = TriageReport(observations=[Observation(ticket=1, kind="stalled", detail="d")])
    assert len(r.since(None).observations) == 1
    assert len(r.since([]).observations) == 1


def test_NOTHING_NEW_still_says_what_is_outstanding():
    """Nothing new is not the same as nothing wrong. Reporting only novelty would let a backlog of
    unfixed rot disappear from view precisely by not changing."""
    text = triage_report(TriageReport(), standing={"no-criteria": 7}, agent_name="Nina")
    assert "Nada novo" in text
    assert "7" in text and "quando está pronto" in text


def test_unchanged_rot_is_COUNTED_not_re_listed():
    """Repeating forty ticket numbers every week is how a report becomes wallpaper; omitting them
    entirely is how a backlog vanishes by standing still. A count is the honest middle."""
    text = triage_report(
        TriageReport(observations=[Observation(ticket=99, kind="stalled", detail="d")]),
        standing={"no-criteria": 7}, agent_name="Nina")
    assert "#99" in text                      # the new one is named
    assert "Continuam pendentes" in text      # the old ones are counted
    assert "#1" not in text


def test_the_scheduled_pass_actually_uses_the_comparison():
    """It was built, tested, and then not wired into the path that runs on its own — so the same
    findings would have arrived every single week until somebody fixed them."""
    from pathlib import Path

    body = Path("openfactory/runtime/temporal/activities.py").read_text()
    body = body[body.index("async def product_sweep("):]
    assert "report.since(previous)" in body
    assert "_remember_sweep(" in body
    assert 'nothing-new' in body


def test_the_cadence_matches_how_fast_the_thing_it_watches_decays():
    """Every finding is rot — a missing criterion, an unmade decision, work nobody closed. That
    decays over weeks, so a daily pass would mostly be the same list again."""
    from openfactory.runtime.temporal.schedule import PRODUCT_EVERY_HOURS

    assert PRODUCT_EVERY_HOURS == 24 * 7


def test_the_sweep_can_actually_WRITE_what_it_remembers():
    """It could not. `MetricRecord.kind` is a closed set and `product_sweep` was not in it, so the
    record failed validation, the write was swallowed as best-effort, and the sweep would have
    greeted the channel every single week — never able to remember having arrived.

    The test that was supposed to cover this asserted the ORDER OF THE SOURCE, which cannot notice
    that a model rejects the value being passed to it. Only building the record does."""
    from datetime import UTC, datetime

    from openfactory.observability.metrics import InMemoryMetricsSink, MetricRecord

    sink = InMemoryMetricsSink()
    sink.record(MetricRecord(
        project="books", ticket="_sweep_", ts=datetime.now(UTC).isoformat(),
        kind="product_sweep", role="_sweep_",
        extra={"findings": "1:no-criteria", "backlog": "3"}))
    assert sink.records[0].kind == "product_sweep"
    assert sink.records[0].extra["findings"] == "1:no-criteria"


def test_the_dashboard_ignores_a_sweep_record():
    """A third kind must not appear as a ticket or an invocation on the cost dashboard."""
    from openfactory.api.metrics_view import dashboard

    rows = [{"pk": "p", "kind": "product_sweep", "ticket": "_sweep_", "ts": "2026-07-27T00:00:00",
             "role": "_sweep_", "extra": {"findings": ""}}]
    d = dashboard(rows)
    assert d["tasks"] == [] and d["totals"]["tasks"] == 0
