"""#203: on Jira a withdrawn card was closed into Done, indistinguishable from work that shipped.

THE PORT SAYS *CLOSED IS NOT DELIVERED* (`TrackerAdapter.close_ticket`), every other shipped row
honoured it, and the Jira row's `close_ticket(ref, reason)` could not: a card an operator withdrew
and a duplicate the product owner folded both landed in the Done status beside the work that
shipped — and the product owner's close did not land at all, because it passes `delivered=False`
and that signature raised `TypeError` on it. Generic code knew: `_card_close` caught the
`TypeError` and called again without the word, with a comment naming Jira.

WHAT IS DRIVEN HERE IS THE REAL `JiraTracker`, THROUGH ITS REAL `_call`, against a fake at the ONE
place the adapter touches the network (`urllib.request.urlopen`). The fake is a small Jira site —
one issue, its workflow, its resolutions, whether the closing transition's screen carries the
Resolution field — so a close and the read that follows it are the same round trip a deployment
makes, and `search/jql` answers ONLY THE FIELDS IT WAS ASKED FOR, as the live endpoint does.

THE SHAPES ARE ATLASSIAN'S REST v3 DOCUMENTATION AND THIS REPOSITORY'S RECORDED FIXTURES
(`test_the_tracker_has_a_read_side.py`), NOT A LIVE SITE — none was available. What is documented:
`POST issue/{key}/transitions` takes `{"transition": {"id"}, "fields": {"resolution": {"name"}}}`
and answers 400 with `{"errors": {"resolution": "Field 'resolution' cannot be set. It is not on the
appropriate screen, or unknown."}}` when the screen has no such field.
"""

from __future__ import annotations

import ast
import io
import json
import logging
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.adapters.tracker import base as port
from openfactory.adapters.tracker.jira import JiraTracker
from openfactory.product.board import _ticket

REF = "DAR-7"
DONE, DONE_ID = "Concluído", "31"
WONT_DO = "Won't Do"
LOG = "OPENFACTORY_JIRA_WITHDRAWN_READS_AS_DELIVERED"


class _Answer:
    def __init__(self, payload: dict | None) -> None:
        self._body = json.dumps(payload).encode() if payload is not None else b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _Site:
    """One Jira Cloud site, as far as closing a card and reading it back are concerned."""

    def __init__(self, *, resolutions=("Done", WONT_DO), screen_has_resolution: bool = True,
                 transitions_to_done: bool = True, breaks_with: int = 0) -> None:
        self.resolutions = resolutions
        self.screen_has_resolution = screen_has_resolution
        self.transitions_to_done = transitions_to_done
        self.breaks_with = breaks_with          # an HTTP status every transition POST answers
        self.status, self.category, self.resolution = "Em andamento", "indeterminate", None
        self.requests: list[tuple[str, str, dict | None]] = []

    # -- what a test reads ---------------------------------------------------------------------
    def posts(self, suffix: str) -> list[dict]:
        return [body or {} for method, path, body in self.requests
                if method == "POST" and path.endswith(suffix)]

    def said(self) -> list[str]:
        return [JiraTracker._text(body.get("body")) for body in self.posts("/comment")]

    # -- the wire ------------------------------------------------------------------------------
    def _refuse(self, req, code: int, payload: dict):
        raise urllib.error.HTTPError(req.full_url, code, "refused", hdrs=None,
                                     fp=io.BytesIO(json.dumps(payload).encode()))

    def urlopen(self, req, timeout=0):  # noqa: ARG002 — urllib's own signature
        method = req.get_method()
        path = req.full_url.split("/rest/api/3/", 1)[1]
        body = json.loads(req.data) if req.data else None
        self.requests.append((method, path, body))
        if (method, path) == ("GET", f"issue/{REF}/transitions"):
            rows = [{"id": "11", "name": "Reabrir", "to": {"name": "A Fazer"}}]
            if self.transitions_to_done:
                rows.append({"id": DONE_ID, "name": "Concluir",
                             "to": {"name": DONE, "statusCategory": {"key": "done"}}})
            return _Answer({"transitions": rows})
        if (method, path) == ("POST", f"issue/{REF}/comment"):
            return _Answer({"id": "10001"})
        if (method, path) == ("POST", f"issue/{REF}/transitions"):
            return self._transition(req, body or {})
        if (method, path) == ("POST", "search/jql"):
            return _Answer({"isLast": True, "issues": [self._row(body or {})]})
        raise AssertionError(f"the adapter called {method} {path}, a route this site never had")

    def _transition(self, req, body: dict):
        if self.breaks_with:
            self._refuse(req, self.breaks_with, {"errorMessages": ["the site said no"]})
        assert (body.get("transition") or {}).get("id") == DONE_ID, body
        sent = ((body.get("fields") or {}).get("resolution") or {}).get("name")
        if sent is not None and not self.screen_has_resolution:
            self._refuse(req, 400, {"errorMessages": [], "errors": {
                "resolution": "Field 'resolution' cannot be set. It is not on the appropriate "
                              "screen, or unknown."}})
        if sent is not None and sent not in self.resolutions:
            self._refuse(req, 400, {"errorMessages": [], "errors": {
                "resolution": f"Resolution name '{sent}' is not valid."}})
        # a transition that names no resolution gets the one the site's own workflow sets
        self.status, self.category, self.resolution = DONE, "done", sent or "Done"
        return _Answer(None)   # 204, no body

    def _row(self, query: dict) -> dict:
        held = {"summary": "exportar o relatório", "labels": [], "assignee": None,
                "updated": "2026-09-19T10:00:00.000+0100",
                "status": {"name": self.status, "statusCategory": {"key": self.category}},
                "resolution": {"id": "10001", "name": self.resolution} if self.resolution else None,
                "description": None}
        # ONLY WHAT WAS ASKED FOR — the live endpoint's rule, and the reason `_LIST_FIELDS` matters
        return {"id": "10071", "key": REF,
                "fields": {k: v for k, v in held.items() if k in (query.get("fields") or [])}}


@pytest.fixture
def site(monkeypatch):
    def _open(**kw) -> _Site:
        jira = _Site(**kw)
        monkeypatch.setattr("urllib.request.urlopen", jira.urlopen)
        return jira
    return _open


def _tracker(resolution: str = WONT_DO) -> JiraTracker:
    # The option is passed only where a case HAS one, so the cases about a deployment that names
    # none — and the one about a delivered close — also run against the row as it was before #203,
    # and say what it did rather than that its constructor is older.
    named = {"not_delivered_resolution": resolution} if resolution else {}
    return JiraTracker(site="https://acme-team.atlassian.net", project_key="DAR",
                       email="alice@acme.ai", token="t",
                       status_map={"todo": "A Fazer", "done": DONE}, **named)


def _read_back(tracker: JiraTracker):
    """The card as triage judges it — through the same function the board sweep uses."""
    (summary,) = tracker.list_tickets(state="all") or [None]
    return _ticket(summary, {})


# ── the close that can say it ───────────────────────────────────────────────────────────────────

def test_a_withdrawn_card_is_closed_with_the_sites_own_resolution(site):
    jira = site()
    tracker = _tracker()

    tracker.close_ticket(REF, "duplicate of DAR-3", delivered=False)

    assert jira.posts("/transitions") == [
        {"transition": {"id": DONE_ID}, "fields": {"resolution": {"name": WONT_DO}}}]
    assert jira.said() == ["duplicate of DAR-3"], "the vendor said it; no note is owed"


def test_and_it_reads_back_as_NOT_delivered(site):
    site()
    tracker = _tracker()
    tracker.close_ticket(REF, "duplicate of DAR-3", delivered=False)

    card = _read_back(tracker)

    assert (card.state, card.state_reason) == ("closed", "not_planned")
    assert card.delivered is False


def test_a_delivered_close_is_the_bare_transition_it_always_was(site):
    jira = site()
    tracker = _tracker(resolution="")

    tracker.close_ticket(REF, "shipped in #12")

    assert jira.posts("/transitions") == [{"transition": {"id": DONE_ID}}]
    assert jira.said() == ["shipped in #12"]
    card = _read_back(tracker)
    assert card.state == "closed" and card.delivered is True
    assert card.state_reason == "", "`Done` is a name nobody told this row the meaning of"


def test_a_card_a_PERSON_closed_as_that_resolution_reads_the_same_way(site):
    jira = site()
    jira.status, jira.category, jira.resolution = DONE, "done", "WON'T DO"

    assert _read_back(_tracker()).delivered is False


def test_a_resolution_nobody_configured_is_never_read_by_its_name(site):
    """The rule this row had before #203 and keeps: delivery is not decided from a name this module
    GUESSED. A deployment that named nothing reads every closed card as the port's "does not say"."""
    jira = site()
    jira.status, jira.category, jira.resolution = DONE, "done", WONT_DO

    card = _read_back(_tracker(resolution=""))

    assert (card.state, card.state_reason) == ("closed", "")


# ── the two ways it cannot, and what each leaves behind ─────────────────────────────────────────

def test_with_no_resolution_configured_the_card_is_closed_and_SAYS_it_was_withdrawn(site, caplog):
    jira = site()
    tracker = _tracker(resolution="")

    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.jira"):
        tracker.close_ticket(REF, "withdrawn by the client", delivered=False)

    assert jira.posts("/transitions") == [{"transition": {"id": DONE_ID}}]
    reason, note = jira.said()
    assert reason == "withdrawn by the client"
    assert "NOT delivered" in note and "withdrawn" in note and DONE in note
    (line,) = [r.getMessage() for r in caplog.records if LOG in r.getMessage()]
    assert "`not_delivered_resolution`" in line and REF in line


@pytest.mark.parametrize("kw,jiras_words", [
    ({"screen_has_resolution": False}, "not on the appropriate screen"),
    ({"resolutions": ("Done", "Duplicate")}, "is not valid"),
])
def test_a_site_that_REFUSES_the_field_still_closes_the_card(site, caplog, kw, jiras_words):
    jira = site(**kw)
    tracker = _tracker()

    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.jira"):
        tracker.close_ticket(REF, "withdrawn by the client", delivered=False)

    assert jira.posts("/transitions") == [
        {"transition": {"id": DONE_ID}, "fields": {"resolution": {"name": WONT_DO}}},
        {"transition": {"id": DONE_ID}}]
    assert jira.status == DONE
    assert "NOT delivered" in jira.said()[-1]
    (line,) = [r.getMessage() for r in caplog.records if LOG in r.getMessage()]
    assert "`not_delivered_resolution`" in line and WONT_DO in line
    assert jiras_words in line, "Jira's own words are what somebody sends back"


@pytest.mark.parametrize("kw", [{}, {"screen_has_resolution": False}])
def test_a_degraded_close_reads_as_DELIVERED_and_the_log_says_so(site, caplog, kw):
    """THE LIMIT, PINNED SO NOBODY FAKES PAST IT. Without the resolution Jira holds nothing for
    this card that it does not hold for shipped work, so the read side cannot tell them apart —
    `JiraTracker.close_ticket` says why a label was not used to pretend otherwise."""
    site(**kw)
    tracker = _tracker(resolution="" if not kw else WONT_DO)

    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.jira"):
        tracker.close_ticket(REF, "withdrawn", delivered=False)

    assert _read_back(tracker).delivered is True
    assert any(LOG in r.getMessage() and "count it as delivered" in r.getMessage()
               for r in caplog.records)


@pytest.mark.parametrize("code", [401, 403, 500])
def test_any_OTHER_failure_raises_and_nothing_is_retried(site, code):
    from openfactory.adapters.tracker.jira import JiraRefused

    jira = site(breaks_with=code)

    with pytest.raises(JiraRefused) as caught:
        _tracker().close_ticket(REF, "withdrawn", delivered=False)

    assert caught.value.code == code and isinstance(caught.value, RuntimeError)
    assert len(jira.posts("/transitions")) == 1
    assert jira.said() == ["withdrawn"], "no note may say a card was closed that was not"


@pytest.mark.parametrize("status_map,site_kw", [
    ({"todo": "A Fazer"}, {}),                                   # `done` was never mapped
    ({"done": DONE}, {"transitions_to_done": False}),            # the workflow has no such move
])
def test_a_card_that_cannot_be_moved_is_not_told_it_was_withdrawn(site, status_map, site_kw):
    """`set_state`'s contract — unmapped, or no transition, is a warning and a no-op — holds for
    the withdrawn close too, and the note is not left on a card that stayed where it was."""
    jira = site(**site_kw)
    tracker = _tracker()
    tracker.status_map = status_map

    tracker.close_ticket(REF, "withdrawn", delivered=False)

    assert jira.posts("/transitions") == [] and jira.status == "Em andamento"
    assert jira.said() == ["withdrawn"]


def test_set_state_still_moves_a_card_and_still_answers_whether_it_did(site):
    """The lookup moved into `_transition_for`; what `set_state` promises did not."""
    from openfactory.contracts import JobState

    jira = site()
    tracker = _tracker(resolution="")

    assert tracker.set_state(REF, JobState.DONE) is True
    assert jira.posts("/transitions") == [{"transition": {"id": DONE_ID}}]
    assert tracker.set_state(REF, JobState.REVIEWING) is False, "in_review is not mapped here"


# ── the option is the deployment's, and it has no default ───────────────────────────────────────

def _project(options: dict, **more) -> SimpleNamespace:
    return SimpleNamespace(name="acme", **more, tracker=SimpleNamespace(
        kind="jira", repo="DAR", options={"site": "https://acme-team.atlassian.net",
                                          "email": "alice@acme.ai", **options}))


def test_the_note_is_written_in_the_PROJECTS_language_not_the_rows(site):
    """The one sentence the row says to a person in its own name. It was first written as an English
    f-string in the adapter, and `test_nothing_speaks_before_it_asks_the_language` caught it: a
    Portuguese board would have been told in English that its card was not delivered."""
    from openfactory.adapters.tracker.registry import build_tracker

    jira = site()
    tracker = build_tracker(_project({"status_map": json.dumps({"done": DONE})},
                                     language="pt-BR"), token="t")

    tracker.close_ticket(REF, "retirado pelo cliente", delivered=False)

    reason, note = jira.said()
    assert reason == "retirado pelo cliente"
    assert "NÃO entregue" in note and DONE in note and "NOT delivered" not in note


def test_the_registry_row_hands_the_sites_resolution_to_the_tracker():
    from openfactory.adapters.tracker.registry import build_tracker

    tracker = build_tracker(_project({"not_delivered_resolution": "Não será feito"}), token="t")

    assert tracker.not_delivered_resolution == "Não será feito"


def test_and_a_deployment_that_names_none_gets_NONE_not_a_literal():
    from openfactory.adapters.tracker.registry import build_tracker

    assert build_tracker(_project({}), token="t").not_delivered_resolution == ""
    assert JiraTracker(site="https://x", project_key="DAR",
                       email="a@b.c").not_delivered_resolution == ""


# ── every row says the word, and the suite refuses one that cannot ──────────────────────────────

def test_every_row_the_core_ships_takes_the_keyword():
    from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker
    from openfactory.adapters.tracker.github import GitHubIssuesTracker
    from openfactory.adapters.tracker.local import LocalTracker
    from openfactory.testing.local_flow import InMemoryTracker

    for row in (JiraTracker, GitHubIssuesTracker, AzureBoardsTracker, LocalTracker,
                InMemoryTracker):
        assert port.says_delivered(row), f"{row.__name__}.close_ticket takes no `delivered`"


class _RowFromBeforeTheKeyword:
    """An add-on tracker as one was written before `delivered` existed, already in the field."""

    def __init__(self) -> None:
        self.closed: list[tuple] = []

    def close_ticket(self, ref, reason):
        self.closed.append((ref, reason))


def test_the_conformance_suite_refuses_such_a_row_BY_NAME():
    from openfactory.conformance.adapters import check_tracker
    from tests.test_the_tracker_has_a_read_side import _FaithfulTracker

    class _Old(_FaithfulTracker):
        def close_ticket(self, ref, reason): ...

    assert check_tracker(_FaithfulTracker()) == []
    (finding,) = check_tracker(_Old())
    assert finding.rule == "tracker.close-says-delivered"
    assert "`delivered`" in finding.detail


# ── the seam generic code closes through ────────────────────────────────────────────────────────

def test_a_row_from_before_the_keyword_still_closes_DELIVERED_work():
    row = _RowFromBeforeTheKeyword()

    port.close_ticket(row, "CONT-4", "shipped", delivered=True)

    assert row.closed == [("CONT-4", "shipped")]


def test_and_is_refused_a_NOT_delivered_close_by_name_before_anything_is_written():
    row = _RowFromBeforeTheKeyword()

    with pytest.raises(port.CannotSayUndelivered) as caught:
        port.close_ticket(row, "CONT-4", "a duplicate", delivered=False)

    said = str(caught.value)
    assert "`delivered`" in said and "_RowFromBeforeTheKeyword.close_ticket" in said
    assert "CONT-4" in said and row.closed == []


def test_a_row_that_takes_the_word_through_kwargs_is_handed_it():
    """A wrapper row — one that forwards to another tracker — declares it with `**kwargs`."""
    got: list[dict] = []

    class _Forwards:
        def close_ticket(self, ref, reason, **kw):
            got.append(kw)

    port.close_ticket(_Forwards(), "CONT-4", "a duplicate", delivered=False)

    assert got == [{"delivered": False}]


def test_a_TypeError_from_INSIDE_a_real_close_is_not_mistaken_for_an_old_row():
    """What the `except TypeError` fallback got wrong besides the word: it closed the card twice."""
    calls: list[tuple] = []

    class _Breaks:
        def close_ticket(self, ref, reason, *, delivered=True):
            calls.append((ref, delivered))
            raise TypeError("unsupported operand type(s) for +: 'NoneType' and 'str'")

    with pytest.raises(TypeError, match="unsupported operand"):
        port.close_ticket(_Breaks(), "CONT-4", "a duplicate", delivered=False)

    assert calls == [("CONT-4", False)]


def test_the_product_owners_watched_tracker_does_not_hide_what_the_row_takes():
    """`_WatchedWrites` forwards `*args, **kwargs`, which reads as "takes anything" — and an old row
    behind it would be handed the keyword and answer with the raw `TypeError` again."""
    from openfactory.product.module import _WatchedWrites

    row, told = _RowFromBeforeTheKeyword(), []
    watched = _WatchedWrites(row, lambda ok, what: told.append((ok, what)))

    assert port.says_delivered(watched) is False
    with pytest.raises(port.CannotSayUndelivered):
        port.close_ticket(watched, "CONT-4", "a duplicate", delivered=False)
    port.close_ticket(watched, "CONT-4", "shipped", delivered=True)

    assert row.closed == [("CONT-4", "shipped")] and told == [(True, "close_ticket")]
    assert port.says_delivered(_WatchedWrites(_tracker(), lambda *_a: None)) is True


def test_the_real_jira_row_is_closed_through_the_seam_with_the_word(site):
    jira = site()

    port.close_ticket(_tracker(), REF, "folded into DAR-3", delivered=False)

    assert jira.posts("/transitions")[0]["fields"] == {"resolution": {"name": WONT_DO}}


def test_no_generic_caller_passes_the_word_to_a_row_directly():
    """The seam is one place only while nothing walks around it. A `.close_ticket(…, delivered=…)`
    outside the tracker rows is a call that meets an old add-on with a raw `TypeError`."""
    root = Path(__file__).resolve().parent.parent / "openfactory"
    rows = root / "adapters" / "tracker"
    around = []
    for path in sorted(root.rglob("*.py")):
        if rows in path.parents:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "close_ticket"
                    and any(k.arg == "delivered" for k in node.keywords)):
                around.append(f"{path.relative_to(root.parent)}:{node.lineno}")

    assert around == [], f"close through `adapters.tracker.base.close_ticket`: {around}"
