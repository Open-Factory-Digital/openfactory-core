"""On a Jira site whose word for "withdrawn" is a STATUS, a withdrawn card could not be recorded.

#203 TAUGHT THE JIRA ROW ONE OF JIRA'S TWO WAYS TO SAY IT. `close_ticket(delivered=False)` sends a
configured RESOLUTION and the read side answers `not_planned` for a card carrying it. A resolution
travels only on a transition whose screen has the field, and Atlassian documents team-managed
projects as having no such screen — so there the close degraded, and the card read as delivered.
Those sites say "withdrawn" the other way: a status of its own in the Done category (`Cancelled`,
`Won't do`, `Cancelado`), a column a person can see. Found 2026-09-19, reading what #213 left out.

WHAT IS DRIVEN HERE IS THE REAL `JiraTracker` AND THE REAL `JiraProjectBoard`, BUILT BY THE REAL
REGISTRY ROWS from a project's tracker options, against a fake at the ONE place the adapter touches
the network (`urllib.request.urlopen`). The fake is a small Jira site that HOLDS A WORKFLOW — four
statuses with their categories, and which moves the card's current status offers — so a close, the
read that follows it, a reopen and the board's own view are the round trips a deployment makes.
`search/jql` answers only the fields it was asked for, as the live endpoint does.

THE SHAPES ARE ATLASSIAN'S REST v3 DOCUMENTATION AND THIS REPOSITORY'S RECORDED FIXTURES, NOT A
LIVE SITE — none was available. What is documented: `GET issue/{key}/transitions` answers each
transition's `to` as a status WITH its `statusCategory`; a transition a workflow validator refuses
answers 400 with the validator's sentence under `errorMessages`.
"""

from __future__ import annotations

import io
import json
import logging
import urllib.error
import urllib.parse
from types import SimpleNamespace

import pytest

from openfactory.adapters.tracker.registry import build_tracker
from openfactory.product.board import _ticket

REF = "DAR-7"
TODO, DOING, DONE, CANCELLED = "A Fazer", "Em andamento", "Concluído", "Cancelado"
TO_TODO, TO_DONE, TO_CANCELLED = "11", "31", "41"
WONT_DO = "Won't Do"
LOG = "OPENFACTORY_JIRA_WITHDRAWN_READS_AS_DELIVERED"


class _Answer:
    def __init__(self, payload) -> None:
        self._body = json.dumps(payload).encode() if payload is not None else b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _Site:
    """One team-managed-shaped Jira site: a workflow with a `Cancelado` status in the Done category,
    and — unless a case says otherwise — NO Resolution field on any transition's screen."""

    def __init__(self, *, offers_cancelled: bool = True, offers_done: bool = True,
                 cancelled_category: str = "done", screen_has_resolution: bool = False,
                 validator_refuses_cancelled: bool = False, breaks_with: int = 0,
                 transitions_state_a_category: bool = True) -> None:
        self.categories = {TODO: "new", DOING: "indeterminate", DONE: "done",
                           CANCELLED: cancelled_category}
        self.offers = {TO_TODO: ("Reabrir", TODO)}
        if offers_done:
            self.offers[TO_DONE] = ("Concluir", DONE)
        if offers_cancelled:
            self.offers[TO_CANCELLED] = ("Cancelar", CANCELLED)
        self.screen_has_resolution = screen_has_resolution
        self.validator_refuses_cancelled = validator_refuses_cancelled
        self.breaks_with = breaks_with          # an HTTP status every transition POST answers
        self.transitions_state_a_category = transitions_state_a_category
        self.status, self.resolution = DOING, None
        self.requests: list[tuple[str, str, dict | None]] = []

    # -- what a test reads ---------------------------------------------------------------------
    def posts(self, suffix: str) -> list[dict]:
        return [body or {} for method, path, body in self.requests
                if method == "POST" and path.endswith(suffix)]

    def said(self) -> list[str]:
        from openfactory.adapters.tracker.jira import JiraTracker

        return [JiraTracker._text(body.get("body")) for body in self.posts("/comment")]

    # -- the wire ------------------------------------------------------------------------------
    def _refuse(self, req, code: int, payload: dict):
        raise urllib.error.HTTPError(req.full_url, code, "refused", hdrs=None,
                                     fp=io.BytesIO(json.dumps(payload).encode()))

    def _status(self, name: str) -> dict:
        return {"name": name, "statusCategory": {"key": self.categories[name]}}

    def urlopen(self, req, timeout=0):  # noqa: ARG002 — urllib's own signature
        method = req.get_method()
        path = req.full_url.split("/rest/api/3/", 1)[1]
        body = json.loads(req.data) if req.data else None
        self.requests.append((method, path, body))
        if (method, path) == ("GET", f"issue/{REF}/transitions"):
            return _Answer({"transitions": [
                {"id": tid, "name": name,
                 "to": self._status(to) if self.transitions_state_a_category else {"name": to}}
                for tid, (name, to) in self.offers.items() if to != self.status]})
        if (method, path) == ("POST", f"issue/{REF}/comment"):
            return _Answer({"id": "10001"})
        if (method, path) == ("POST", f"issue/{REF}/transitions"):
            return self._transition(req, body or {})
        if (method, path) == ("POST", "search/jql"):
            return _Answer({"isLast": True, "issues": [self._row(body or {})]})
        if method == "GET" and path.startswith("search/jql?"):          # the board's own read
            query = urllib.parse.parse_qs(path.split("?", 1)[1])
            jql = query["jql"][0]
            shown = 'status = "' not in jql or f'status = "{self.status}"' in jql
            return _Answer({"isLast": True, "issues": [self._row({"fields": ["status"]})]
                            if shown else []})
        if (method, path) == ("GET", "project/DAR/statuses"):
            return _Answer([{"name": "Tarefa",
                             "statuses": [self._status(n) for n in self.categories]}])
        raise AssertionError(f"the adapter called {method} {path}, a route this site never had")

    def _transition(self, req, body: dict):
        if self.breaks_with:
            self._refuse(req, self.breaks_with, {"errorMessages": ["the site said no"]})
        tid = str((body.get("transition") or {}).get("id"))
        assert tid in self.offers, f"a transition this workflow never offered: {body}"
        _name, to = self.offers[tid]
        if to == CANCELLED and self.validator_refuses_cancelled:
            self._refuse(req, 400, {"errorMessages": ["Informe o motivo do cancelamento."],
                                    "errors": {}})
        sent = ((body.get("fields") or {}).get("resolution") or {}).get("name")
        if sent is not None and not self.screen_has_resolution:
            self._refuse(req, 400, {"errorMessages": [], "errors": {
                "resolution": "Field 'resolution' cannot be set. It is not on the appropriate "
                              "screen, or unknown."}})
        self.status = to
        # Jira's own rule: leaving the Done category clears the resolution; entering it without
        # naming one gets whatever the site's workflow sets.
        self.resolution = (sent or "Done") if self.categories[to] == "done" else None
        return _Answer(None)   # 204, no body

    def _row(self, query: dict) -> dict:
        held = {"summary": "exportar o relatório", "labels": [], "assignee": None,
                "updated": "2026-09-19T10:00:00.000+0100", "description": None,
                "status": self._status(self.status),
                "resolution": {"id": "10001", "name": self.resolution} if self.resolution else None}
        return {"id": "10071", "key": REF,
                "fields": {k: v for k, v in held.items() if k in (query.get("fields") or [])}}


@pytest.fixture
def site(monkeypatch):
    def _open(**kw) -> _Site:
        jira = _Site(**kw)
        monkeypatch.setattr("urllib.request.urlopen", jira.urlopen)
        return jira
    return _open


def _project(*, status: str = CANCELLED, resolution: str = "", status_map: dict | None = None,
             language: str | None = None) -> SimpleNamespace:
    """A project as the registry holds one: every option a string, the map a JSON string."""
    options = {"site": "https://acme-team.atlassian.net", "email": "alice@acme.ai",
               "status_map": json.dumps({"todo": TODO, "done": DONE}
                                        if status_map is None else status_map)}
    if status:
        options["not_delivered_status"] = status
    if resolution:
        options["not_delivered_resolution"] = resolution
    return SimpleNamespace(name="acme", language=language,
                           tracker=SimpleNamespace(kind="jira", repo="DAR", options=options))


def _tracker(**kw):
    """THROUGH THE REGISTRY ROW, the way a deployment gets one — so a row that never hands the
    option over fails every case here, and the base this was written against (which ignores an
    option it never heard of) answers with what it DID rather than with a constructor error."""
    return build_tracker(_project(**kw), token="t")


def _read_back(tracker):
    """The card as triage judges it — through the same function the board sweep uses."""
    (summary,) = tracker.list_tickets(state="all") or [None]
    return _ticket(summary, {})


def _warned(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if LOG in r.getMessage()]


# ── the close that can say it, in the site's other word ─────────────────────────────────────────

def test_a_withdrawn_card_is_moved_into_the_status_the_deployment_named(site):
    jira = site()

    _tracker().close_ticket(REF, "duplicate of DAR-3", delivered=False)

    assert jira.posts("/transitions") == [{"transition": {"id": TO_CANCELLED}}], (
        "the bare transition into the site's own status: no field a screen could refuse")
    assert jira.status == CANCELLED
    assert jira.said() == ["duplicate of DAR-3"], "the vendor said it; no note is owed"


def test_and_it_reads_back_as_NOT_delivered(site, caplog):
    site()
    tracker = _tracker()
    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.jira"):
        tracker.close_ticket(REF, "duplicate of DAR-3", delivered=False)

    card = _read_back(tracker)

    assert (card.state, card.state_reason) == ("closed", "not_planned")
    assert card.delivered is False
    assert _warned(caplog) == [], "nothing degraded, so nothing is said to have"


def test_a_DELIVERED_close_still_goes_to_done_whatever_is_named_for_the_other_word(site):
    jira = site()
    tracker = _tracker(resolution=WONT_DO)

    tracker.close_ticket(REF, "shipped in #12")

    assert jira.posts("/transitions") == [{"transition": {"id": TO_DONE}}]
    card = _read_back(tracker)
    assert (card.state, card.state_reason, card.delivered) == ("closed", "", True)


def test_a_card_a_PERSON_dragged_into_that_status_reads_the_same_way(site):
    jira = site()
    jira.status, jira.resolution = CANCELLED, "Done"

    assert _read_back(_tracker(status="CANCELADO")).delivered is False, (
        "compared the way `_transition_for` compares a status name: without case")


def test_a_status_nobody_named_is_never_read_by_its_name(site):
    """#203's rule, kept: delivery is not decided from a name this module GUESSED."""
    jira = site()
    jira.status, jira.resolution = CANCELLED, "Done"

    card = _read_back(_tracker(status=""))

    assert (card.state, card.state_reason, card.delivered) == ("closed", "", True)


def test_it_has_NO_default_on_the_row_or_on_the_adapter():
    from openfactory.adapters.tracker.jira import JiraTracker

    assert _tracker(status="").not_delivered_status == ""
    assert JiraTracker(site="https://x", project_key="DAR", email="a@b.c").not_delivered_status == ""
    assert _tracker(status="  Cancelado ").not_delivered_status == CANCELLED


# ── reopened, it stops reading as withdrawn — with nothing to clear ─────────────────────────────

def test_a_withdrawn_card_REOPENED_and_then_delivered_reads_as_delivered(site):
    """The stale-mark failure a label would have had (`JiraTracker.close_ticket` says why #203
    refused one) cannot happen here: the read is of the status the card is in NOW."""
    jira = site()
    tracker = _tracker()
    tracker.close_ticket(REF, "withdrawn by the client", delivered=False)
    assert _read_back(tracker).delivered is False

    tracker.reopen_ticket(REF)
    reopened = _read_back(tracker)
    assert (jira.status, reopened.state, reopened.state_reason) == (TODO, "open", "")

    tracker.close_ticket(REF, "shipped in #12")
    card = _read_back(tracker)
    assert (jira.status, card.state_reason, card.delivered) == (DONE, "", True)


# ── the ways it cannot, and what each leaves behind ─────────────────────────────────────────────

def test_a_workflow_with_NO_MOVE_into_that_status_still_closes_the_card_and_says_so(site, caplog):
    jira = site(offers_cancelled=False)
    tracker = _tracker()

    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.jira"):
        tracker.close_ticket(REF, "withdrawn by the client", delivered=False)

    assert jira.posts("/transitions") == [{"transition": {"id": TO_DONE}}]
    reason, note = jira.said()
    assert reason == "withdrawn by the client"
    assert "NOT delivered" in note and DONE in note, "#203's note, naming where it landed"
    (line,) = _warned(caplog)
    assert "`not_delivered_status`" in line and CANCELLED in line and REF in line
    assert "count it as delivered" in line
    assert _read_back(tracker).delivered is True, "the limit #203 pinned, unchanged: Jira holds " \
                                                  "nothing for this card that says otherwise"


def test_a_VALIDATOR_that_refuses_the_move_degrades_the_same_way_in_jiras_own_words(site, caplog):
    jira = site(validator_refuses_cancelled=True)

    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.jira"):
        _tracker().close_ticket(REF, "withdrawn", delivered=False)

    assert jira.posts("/transitions") == [{"transition": {"id": TO_CANCELLED}},
                                          {"transition": {"id": TO_DONE}}]
    assert jira.status == DONE and "NOT delivered" in jira.said()[-1]
    (line,) = _warned(caplog)
    assert "Informe o motivo do cancelamento." in line, "what somebody sends back"
    assert "`not_delivered_status`" in line


@pytest.mark.parametrize("code", [401, 403, 500])
def test_any_OTHER_failure_raises_and_nothing_is_retried(site, code):
    from openfactory.adapters.tracker.jira import JiraRefused

    jira = site(breaks_with=code)

    with pytest.raises(JiraRefused) as caught:
        _tracker().close_ticket(REF, "withdrawn", delivered=False)

    assert caught.value.code == code
    assert jira.posts("/transitions") == [{"transition": {"id": TO_CANCELLED}}]
    assert jira.said() == ["withdrawn"], "no note may say a card was closed that was not"


def test_a_status_that_does_not_CLOSE_a_card_is_not_used_to_close_one(site, caplog):
    """A deployment can name a status its administrator filed under To Do. Moving the card there
    would answer "closed" for a card every read then shows as open work."""
    jira = site(cancelled_category="new")
    tracker = _tracker()

    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.jira"):
        tracker.close_ticket(REF, "withdrawn", delivered=False)

    assert jira.posts("/transitions") == [{"transition": {"id": TO_DONE}}]
    (line,) = _warned(caplog)
    assert "`not_delivered_status`" in line and CANCELLED in line and "Done category" in line
    assert _read_back(tracker).state == "closed"


def test_only_a_category_the_site_STATES_can_refuse_the_status(site):
    """A transitions answer thinner than the documented one is not evidence of anything, and
    refusing on it would switch the option off for that whole site."""
    jira = site(transitions_state_a_category=False)

    _tracker().close_ticket(REF, "withdrawn", delivered=False)

    assert jira.posts("/transitions") == [{"transition": {"id": TO_CANCELLED}}]


def test_and_an_OPEN_card_sitting_in_such_a_status_is_never_read_as_withdrawn(site):
    jira = site(cancelled_category="new")
    jira.status = CANCELLED

    card = _read_back(_tracker())

    assert (card.state, card.state_reason) == ("open", "")


def test_the_status_needs_no_done_mapping_to_be_reached(site):
    """`not_delivered_status` is its own declaration, not a variant of `status_map["done"]`."""
    jira = site()
    tracker = _tracker(status_map={"todo": TODO})

    tracker.close_ticket(REF, "withdrawn", delivered=False)

    assert jira.status == CANCELLED and _read_back(tracker).delivered is False


def test_a_card_that_cannot_be_moved_AT_ALL_is_not_told_it_was_withdrawn(site, caplog):
    jira = site(offers_cancelled=False, offers_done=False)

    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.jira"):
        _tracker().close_ticket(REF, "withdrawn", delivered=False)

    assert jira.posts("/transitions") == [] and jira.status == DOING
    assert jira.said() == ["withdrawn"] and _warned(caplog) == []


# ── a deployment that named BOTH words ──────────────────────────────────────────────────────────

def test_with_both_named_the_STATUS_is_the_record_and_no_field_is_sent(site):
    jira = site(screen_has_resolution=True)
    tracker = _tracker(resolution=WONT_DO)

    tracker.close_ticket(REF, "withdrawn", delivered=False)

    assert jira.posts("/transitions") == [{"transition": {"id": TO_CANCELLED}}]
    assert _read_back(tracker).delivered is False


def test_with_both_named_a_card_with_no_move_into_the_status_gets_the_RESOLUTION(site, caplog):
    jira = site(offers_cancelled=False, screen_has_resolution=True)
    tracker = _tracker(resolution=WONT_DO)

    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.jira"):
        tracker.close_ticket(REF, "withdrawn", delivered=False)

    assert jira.posts("/transitions") == [
        {"transition": {"id": TO_DONE}, "fields": {"resolution": {"name": WONT_DO}}}]
    assert jira.said() == ["withdrawn"] and _warned(caplog) == []
    assert _read_back(tracker).delivered is False, "recorded the second way, so nothing degraded"


def test_with_both_named_and_NEITHER_taken_the_line_says_what_each_met(site, caplog):
    jira = site(offers_cancelled=False)                  # and no Resolution field on any screen
    tracker = _tracker(resolution=WONT_DO)

    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.jira"):
        tracker.close_ticket(REF, "withdrawn", delivered=False)

    assert jira.posts("/transitions") == [
        {"transition": {"id": TO_DONE}, "fields": {"resolution": {"name": WONT_DO}}},
        {"transition": {"id": TO_DONE}}]
    (line,) = _warned(caplog)
    assert "`not_delivered_status`" in line and CANCELLED in line
    assert "`not_delivered_resolution`" in line and "not on the appropriate screen" in line
    assert _read_back(tracker).delivered is True


def test_either_word_a_PERSON_used_reads_as_not_delivered_when_both_are_named(site):
    jira = site()
    tracker = _tracker(resolution=WONT_DO)

    jira.status, jira.resolution = DONE, WONT_DO
    assert _read_back(tracker).delivered is False
    jira.status, jira.resolution = CANCELLED, "Done"
    assert _read_back(tracker).delivered is False
    jira.status, jira.resolution = DONE, "Done"
    assert _read_back(tracker).delivered is True


def test_a_deployment_that_names_NEITHER_is_told_about_both(site, caplog):
    site()

    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.jira"):
        _tracker(status="").close_ticket(REF, "withdrawn", delivered=False)

    (line,) = _warned(caplog)
    assert "`not_delivered_status`" in line and "`not_delivered_resolution`" in line


# ── one lookup for every move this row makes ────────────────────────────────────────────────────

def test_a_state_and_a_named_status_are_found_by_the_SAME_lookup(site):
    """`_transition_for` takes either — the state a job is in, resolved through `status_map`, or a
    status the deployment named outright — and a second copy of "how a status is found" is how the
    close and `set_state` would come to disagree about a name's case."""
    from openfactory.contracts import JobState

    site()
    tracker = _tracker(status="cancelado")

    assert tracker._transition_for(REF, JobState.DONE)["id"] == TO_DONE
    assert tracker._transition_for(REF, status="cancelado")["id"] == TO_CANCELLED
    assert tracker._transition_for(REF, status="Cancelar")["id"] == TO_CANCELLED, (
        "by the transition's own name too, as `set_state` has always matched")
    assert tracker._transition_for(REF, status="Arquivado") is None
    assert tracker._transition_for(REF, JobState.REVIEWING) is None, "unmapped, as before"


# ── what the board shows ────────────────────────────────────────────────────────────────────────

def _board(**kw):
    from openfactory.adapters.board.factory import build_board

    return build_board(_project(**kw), token="t")


def test_the_board_shows_the_withdrawn_card_in_the_sites_own_column_and_not_in_the_queue(site):
    """ON JIRA THE COLUMN IS THE STATUS, so there is no second map for the board to keep in step:
    the card is in `Cancelado` because that is where Jira holds it."""
    site()
    _tracker().close_ticket(REF, "withdrawn", delivered=False)
    board = _board()

    assert board.columns() == {REF: CANCELLED}
    assert CANCELLED in (board.column_names() or [])
    assert board.items_in_status(board.pickup_column()) == []
    assert board.items_in_status(CANCELLED) == [REF]
