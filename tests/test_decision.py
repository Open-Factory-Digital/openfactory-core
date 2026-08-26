"""The DecisionRequest contract + parser — the foundation of 'no park without options'."""

from __future__ import annotations

from openfactory.contracts import DecisionRequest, canned, parse_decision


def test_parse_pulls_the_last_fenced_decision_block():
    text = (
        "Here is my analysis.\n"
        "```json\n{\"stage\": \"plan\", \"question\": \"scratch\", \"options\": []}\n```\n"
        "…on reflection…\n"
        "```json\n{\"stage\": \"plan\", \"question\": \"Trust X-Forwarded-For for the IP tier?\","
        " \"context\": \"Behind a proxy XFF is forgeable if accepted from anywhere.\","
        " \"options\": ["
        "{\"key\": \"A\", \"label\": \"Trust only configured proxies\", \"consequence\": \"safe; needs per-env config\", \"recommended\": true},"
        "{\"key\": \"B\", \"label\": \"Always trust XFF\", \"consequence\": \"forgeable — limit bypassable\"},"
        "{\"key\": \"C\", \"label\": \"Drop the IP tier\", \"consequence\": \"weaker, zero config\"}],"
        " \"default\": \"A\"}\n```"
    )
    d = parse_decision(text)
    assert d is not None
    assert d.stage == "plan" and "X-Forwarded-For" in d.question
    assert [o.key for o in d.options] == ["A", "B", "C"]
    assert d.recommended_key() == "A"
    assert d.option("a").label.startswith("Trust only")  # case-insensitive lookup
    assert d.option("z") is None


def test_parse_normalises_the_recommendation_to_exactly_one():
    # default names B, but two options claim recommended — after parsing, only B is recommended
    text = ("```json\n{\"question\": \"q\", \"default\": \"B\", \"options\": ["
            "{\"key\": \"A\", \"label\": \"a\", \"recommended\": true},"
            "{\"key\": \"B\", \"label\": \"b\", \"recommended\": true}]}\n```")
    d = parse_decision(text)
    assert d.recommended_key() == "B"
    assert [o.recommended for o in d.options] == [False, True]


def test_parse_degrades_to_none_never_raises():
    assert parse_decision("no json here") is None
    assert parse_decision("```json\n{not json}\n```") is None
    # a "decision" with fewer than two options isn't a real choice
    assert parse_decision('```json\n{"question": "q", "options": [{"key":"A","label":"a"}]}\n```') is None
    assert parse_decision("") is None


def test_canned_builds_process_options_with_a_recommendation():
    d = canned("impediment", "The job crashed — what now?",
               [("retry", "Retry", "re-run from the top"),
                ("fresh", "Retry with a clean workspace", "discard partial work, clone fresh"),
                ("skip", "Skip", "give up, free the floor")],
               default="retry")
    assert isinstance(d, DecisionRequest)
    assert d.recommended_key() == "retry"
    assert [o.recommended for o in d.options] == [True, False, False]


def test_parse_advice_pulls_the_tech_lead_briefing():
    from openfactory.contracts import parse_advice

    a = parse_advice(
        "Let me think.\n```json\n{\"summary\": \"The PR is behind a busy main.\","
        " \"recommend\": \"merge\", \"rationale\": \"CI is green and the change is small; "
        "forcing it in avoids another rebase race.\", \"watch_outs\": \"confirm no required "
        "check was skipped\"}\n```")
    assert a and a.recommend == "merge"
    assert "busy main" in a.summary and a.watch_outs


def test_parse_advice_degrades_to_none():
    from openfactory.contracts import parse_advice

    assert parse_advice("no json") is None
    assert parse_advice("```json\n{\"unrelated\": 1}\n```") is None
    assert parse_advice("") is None


def test_runresult_carries_a_decision():
    from openfactory.contracts import JobState, RunResult

    d = canned("plan", "q", [("A", "a", ""), ("B", "b", "")], default="A")
    r = RunResult(ticket_id="#1", state=JobState.BLOCKED, decision=d)
    # round-trips through pydantic (Temporal ships it as JSON)
    r2 = RunResult.model_validate(r.model_dump())
    assert r2.decision and r2.decision.options[0].key == "A"
