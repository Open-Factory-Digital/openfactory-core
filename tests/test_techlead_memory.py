"""The tech-lead's memory (the gap the product owner flagged: "having no memory is very worrying").

Before this, its whole memory was one number — how many distinct tickets had failed each way. It
could count, but it could not recognise; it could not say what it tried, because `_remedied` died
with the workflow; and nothing anywhere recorded whether anything worked.

The third gap is the expensive one: a remedy that has never worked looked exactly like one that
always works, so the factory could retry the same useless thing on every ticket at a full agent pass
each time, and every retry looked like diligence.
"""

from __future__ import annotations

from openfactory.techlead.classify import Remedy
from openfactory.techlead.memory import (
    DID_NOT_WORK,
    PENDING,
    WORKED,
    Episode,
    History,
    learn,
    signature,
    temper,
)

# ── recognising the same problem ────────────────────────────────────────────────────────────────

def test_the_same_failure_on_different_tickets_is_ONE_signature():
    """The whole point. If #478 and #503 fingerprint differently, a recurring problem is remembered
    as unrelated one-offs and nothing is ever learned."""
    a = signature("box failed: GraphQL: API rate limit exceeded for installation ID 146152259")
    b = signature("box failed: GraphQL: API rate limit exceeded for installation ID 987654321")
    assert a == b


def test_ticket_numbers_shas_urls_and_timestamps_do_not_split_a_signature():
    one = signature("#478 failed at 2026-07-27T20:38:24 on abc1234 see https://x/y")
    two = signature("#503 failed at 2026-07-28T01:02:03 on def5678 see https://a/b")
    assert one == two


def test_genuinely_different_failures_stay_different():
    assert signature("rate limit exceeded") != signature("could not clone the repository")


# ── what the record means ───────────────────────────────────────────────────────────────────────

def test_it_counts_tickets_not_attempts_when_saying_how_widespread():
    # each attempt carries its own `ts` — that IS its identity, which is how a retry and the row
    # that later resolves it are told apart in an append-only store
    eps = [Episode(ticket=1, cause="transient", sig="s", remedy="retry", ts="T1",
                   outcome=DID_NOT_WORK),
           Episode(ticket=1, cause="transient", sig="s", remedy="retry", ts="T2",
                   outcome=DID_NOT_WORK),
           Episode(ticket=2, cause="transient", sig="s", remedy="retry", ts="T3",
                   outcome=WORKED)]
    h = learn(eps)["s"]
    assert h.seen == 2 and h.attempts == 3 and h.failed == 2 and h.worked == 1


def test_a_remedy_that_never_worked_becomes_hopeless():
    h = History(sig="s", attempts=2, failed=2)
    assert h.hopeless() is True


def test_one_failure_is_not_yet_a_pattern():
    """The first failure can be coincidence; giving up on it would be its own kind of wrong."""
    assert History(sig="s", attempts=1, failed=1).hopeless() is False


def test_a_remedy_that_has_EVER_worked_is_not_hopeless():
    """Two failures and one success is a flaky remedy, not a useless one — and refusing to try it
    would strand every future occurrence on a human."""
    assert History(sig="s", attempts=3, failed=2, worked=1).hopeless() is False


def test_pending_attempts_never_count_as_failures():
    """A pile of `pending` proves only that nobody has looked. Reading it as failure would abandon
    something that may be working perfectly."""
    assert History(sig="s", attempts=5, pending=5).hopeless() is False


# ── what it changes ─────────────────────────────────────────────────────────────────────────────

def test_history_WITHDRAWS_a_remedy_that_has_never_worked():
    """The behaviour that saves money: stop paying for a retry the record says does nothing."""
    out = temper(Remedy(action="retry", wait_seconds=900, attempts_left=2),
                 History(sig="s", attempts=2, failed=2))
    assert out.action == "escalate"
    assert out.wait_seconds == 0
    assert "nunca resolveu" in out.reason


def test_history_can_NEVER_talk_the_factory_INTO_acting():
    """One direction only. A memory that could turn an escalation into a retry would let a bad week
    become a policy — the same asymmetry as `observed` never becoming `accepted`."""
    escalation = Remedy(action="escalate", reason="ninguém entendeu isso")
    assert temper(escalation, History(sig="s", attempts=9, worked=9)) is escalation


def test_no_history_changes_nothing():
    r = Remedy(action="retry", wait_seconds=900, attempts_left=3)
    assert temper(r, None) is r
    assert temper(r, History(sig="s")) is r


def test_the_escalation_says_what_it_LEARNED_not_just_that_it_failed():
    """"não consegui" is a shrug. "já vi isso 4 vezes e retomar nunca resolveu" tells somebody
    where to look — which is the entire value of having a memory."""
    out = temper(Remedy(action="retry"),
                 History(sig="s", tickets={1, 2, 3, 4}, attempts=4, failed=4))
    assert "4 ticket" in out.say and "nunca" in out.say.lower() or "não resolveu" in out.say


# ── outcomes are observed, never self-reported ──────────────────────────────────────────────────

def _remedy(ticket="478", sig="throttled", cause="transient"):
    from openfactory.memory.ledger import REMEDY, open_loop

    return open_loop(REMEDY, ticket, owner="techlead", about=sig, ts="T1",
                     context={"cause": cause})


def test_still_parked_the_same_way_means_it_did_NOT_work():
    from openfactory.techlead.memory import remedy_verdicts

    v = remedy_verdicts([_remedy()], parked_now={"478": ("throttled", "transient")},
                        observed={"478"}, terminal={})
    assert list(v.values()) == [DID_NOT_WORK]


def test_parked_on_a_DIFFERENT_cause_means_this_one_worked():
    from openfactory.techlead.memory import remedy_verdicts

    v = remedy_verdicts([_remedy()], parked_now={"478": ("could not clone", "environment")},
                        observed={"478"}, terminal={})
    assert list(v.values()) == [WORKED]


def test_same_cause_in_new_words_is_NO_verdict():
    """String drift must be neither credit nor blame: "secondary rate limit" and "API rate limit
    exceeded" are the same disease in a different rash, and crediting the remedy for the wording
    change would book a false `worked` — one of which poisons `hopeless()` for ever."""
    from openfactory.techlead.memory import remedy_verdicts

    v = remedy_verdicts([_remedy()], parked_now={"478": ("secondary rate limit", "transient")},
                        observed={"478"}, terminal={})
    assert v == {}


def test_a_RUNNING_job_yields_no_verdict():
    """The reviewer's second counterexample: a resume un-parks the job for the ninety minutes its
    agent pass runs; the next round sees it not-parked. Reading that as `worked` books a success
    for every slow-recurring failure, for ever."""
    from openfactory.techlead.memory import remedy_verdicts

    v = remedy_verdicts([_remedy()], parked_now={}, observed={"478"}, terminal={})
    assert v == {}


def test_an_UNOBSERVABLE_job_yields_no_verdict():
    """The reviewer's first counterexample: a deploy mid-round makes the query fail; the ticket
    drops out of every set. Absence is never an outcome — the loop stays pending."""
    from openfactory.techlead.memory import remedy_verdicts

    v = remedy_verdicts([_remedy()], parked_now={}, observed=set(), terminal={"478": ""})
    assert v == {}


def test_a_workflow_that_ENDED_settles_the_remedy_by_its_terminal_state():
    from openfactory.techlead.memory import remedy_verdicts

    worked = remedy_verdicts([_remedy()], parked_now={}, observed=set(),
                             terminal={"478": WORKED})
    failed = remedy_verdicts([_remedy()], parked_now={}, observed=set(),
                             terminal={"478": DID_NOT_WORK})
    assert list(worked.values()) == [WORKED] and list(failed.values()) == [DID_NOT_WORK]


def test_a_human_termination_is_neither_credit_nor_blame():
    """`abandoned` closes the loop without touching the worked/failed arithmetic, so a person
    cancelling a job can never tip `hopeless()` in either direction."""
    from openfactory.techlead.memory import remedy_verdicts

    v = remedy_verdicts([_remedy()], parked_now={}, observed=set(), terminal={"478": "abandoned"})
    assert list(v.values()) == ["abandoned"]
    h = History(sig="s", attempts=3, pending=1)  # abandoned folds as neither worked nor failed
    assert h.hopeless() is False


def test_nothing_self_reports_success():
    """`PENDING` is the only outcome an attempt may write about itself — a remedy that grades its
    own homework is exactly what this module exists to stop believing."""
    ep = Episode(ticket="1", cause="c", sig="s", remedy="retry")
    assert ep.outcome == PENDING


# ── the ref is the provider's, not a number (#69) ───────────────────────────────────────────────
#
# EVERY TEST ABOVE USES "478", and that is why none of them caught this: a numeric ref survives
# `int(subject)` unharmed, so the whole truth table was exercised on the one shape that could not
# fail. On a Jira/ADO deployment `int("CONT-412")` raised, the code fell back to `0`, and 0 can
# never be a key in `parked_now` / `observed` / `terminal` — so every open remedy fell through all
# three branches and stayed PENDING for ever. `hopeless()` counts only RESOLVED attempts, so it
# could never fire: the factory would retry a useless remedy at full price, indefinitely.

def _jira_remedy(ticket="CONT-412", sig="throttled", cause="transient"):
    from openfactory.memory.ledger import REMEDY, open_loop

    return open_loop(REMEDY, ticket, owner="techlead", about=sig, ts="T1",
                     context={"cause": cause})


def test_a_jira_ref_still_parked_the_same_way_means_it_did_NOT_work():
    from openfactory.techlead.memory import remedy_verdicts

    v = remedy_verdicts([_jira_remedy()], parked_now={"CONT-412": ("throttled", "transient")},
                        observed={"CONT-412"}, terminal={})

    assert list(v.values()) == [DID_NOT_WORK]


def test_a_jira_ref_reaches_a_terminal_verdict_at_all():
    """THE regression. Before this, a non-numeric ref could reach NO verdict by any route, so a
    remedy loop opened on a Jira deployment was immortal."""
    from openfactory.techlead.memory import remedy_verdicts

    v = remedy_verdicts([_jira_remedy()], parked_now={}, observed=set(),
                        terminal={"CONT-412": WORKED})

    assert list(v.values()) == [WORKED]


def test_a_jira_ref_can_reach_hopeless():
    """`hopeless()` is the memory's whole point — the thing that stops the factory paying for a
    remedy that has never once worked. It is reached through `seen`/`failed`, which are counted
    per TICKET, and every non-numeric ticket used to collapse into the same bucket (0)."""
    from openfactory.techlead.memory import learn

    episodes = [
        Episode(ticket=f"CONT-{n}", cause="transient", sig="throttled", remedy="retry",
                outcome=DID_NOT_WORK, ts=f"T{n}")
        for n in (1, 2, 3)
    ]

    history = learn(episodes)["throttled"]

    assert history.seen == 3, "three distinct Jira tickets collapsed into one bucket"
    assert history.failed == 3
    assert history.hopeless() is True


def test_the_phrase_a_human_reads_counts_jira_tickets_correctly():
    """`seen` is not internal: `phrase()` puts it in front of a person as 'já vi isso em N
    tickets'. Collapsing every Jira ref to 0 made that number permanently 1."""
    from openfactory.techlead.memory import learn

    episodes = [
        Episode(ticket=f"PROJ-{n}", cause="transient", sig="throttled", remedy="retry",
                outcome=DID_NOT_WORK, ts=f"T{n}")
        for n in (10, 20, 30, 40)
    ]

    said = learn(episodes)["throttled"].phrase()

    assert "4 tickets" in said, said
