"""A pull request the review rejected looked exactly like one it approved (#149).

MEASURED ON THE PILOT. The factory announced `#101 PR ready for review: <url>` at 16:46:00; the
operator said "you can merge, please"; and only THEN was he told that this platform's own review
had REJECTED the change (score 58) with a high finding saying the ticket's deliverable was not
achievable. Every word of it was already in the store when the announcement went out.

Grepped the gate's own payloads for `score`, `review`, `reject`: all absent. A verdict computed at
the REVIEW station, published by a workflow query, and rendered in exactly one place — a dense
line inside the tech-lead's prompt. On the one screen where a person is deciding, nothing.

THE ABSENT CASE IS A LEVEL, NOT A BLANK. "No review was run", "I could not read the review" and
"the review approved it" are three different facts, and a card that draws nothing for the first
two is telling somebody their diff was checked.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from openfactory import api
from openfactory.review import verdict as vr

PANEL = (Path(inspect.getfile(api)).parent / "panel.html").read_text()
CODE = "\n".join(re.sub(r"(^|\s)//.*$", "", ln)
                 for ln in re.sub(r"/\*.*?\*/", "", PANEL, flags=re.S).splitlines())

REJECTED = {"decision": "rejected", "score": 58,
            "findings": [{"severity": "high", "description": "the deliverable is not reachable",
                          "file": "src/providers/openai.py"},
                         {"severity": "low", "description": "a nit"}],
            "gates": [{"name": "test", "passed": True}]}
APPROVED = {"decision": "approved", "score": 91, "gates": [{"name": "test", "passed": True}]}


# ── 1. the three absences are three different answers ───────────────────────────────────────────

@pytest.mark.parametrize("verdict,unread,level,word", [
    (None, False, "unknown", "No review"),
    ({}, False, "unknown", "No review"),
    (None, True, "unknown", "Review unreadable"),
    (APPROVED, False, "ok", "Review approved it"),
    (REJECTED, False, "warn", "Review rejected it"),
])
def test_each_state_says_which_one_it_is(verdict, unread, level, word):
    got = vr.headline(verdict, unread=unread)
    assert got["level"] == level and got["word"] == word, got


def test_unreadable_is_not_reported_as_unreviewed():
    """The claim a person acts on hardest, and the one most easily lost: a workflow that will not
    answer is usually one whose worker is gone."""
    got = vr.headline(None, unread=True)
    assert "not the same as unreviewed" in got["clause"]


# ── 2. what a person is asked to confirm travels with it ────────────────────────────────────────

def test_the_HIGH_findings_are_carried_and_the_noise_is_not():
    got = vr.headline(REJECTED)
    joined = " ".join(got["points"])
    assert "the deliverable is not reachable" in joined
    assert "src/providers/openai.py" in joined
    assert "a nit" not in joined, "every finding is repeated, so the serious one stops standing out"


def test_a_gate_SUPPRESSION_is_a_point_even_on_an_approved_change():
    """The commonest reason a green pull request is handed to a person, and the pilot's second
    flag. An approval with a suppression in it is not a clean bill."""
    got = vr.headline({**APPROVED, "suppressions": ["type: ignore"]})
    assert got["level"] == "warn"
    assert got["word"] == "Review approved it, with flags"
    assert any("type: ignore" in p for p in got["points"])


def test_a_FAILED_gate_is_named():
    got = vr.headline({**APPROVED, "gates": [{"name": "types", "passed": False}]})
    assert any("gates failed: types" in p for p in got["points"])


def test_gates_that_were_not_RE_RUN_are_not_reported_as_passing():
    got = vr.headline({"decision": "approved", "score": 88, "gates": [],
                       "gates_note": "the forge's own CI is the live check"})
    assert any("not re-run" in p for p in got["points"]), got


def test_an_OUT_OF_DATE_verdict_outranks_its_own_decision():
    """A decision about code that is gone is not a decision. `approved` must not colour the card
    green when the diff it approved has been rewritten (#153)."""
    got = vr.headline({**APPROVED, "stale": "a pass rewrote the pull request"})
    assert got["level"] == "unknown"
    assert got["word"] == "Review out of date"
    assert "nothing re-ran the reviewer" in got["clause"]


def test_and_every_point_under_it_is_stamped():
    got = vr.headline({**REJECTED, "suppressions": ["noqa"], "stale": "a pass rewrote it"})
    assert got["points"], "there is nothing to stamp — this guard measures nothing"
    assert all(p.startswith("was: ") for p in got["points"]), got["points"]


# ── 3. one definition, two renderers ────────────────────────────────────────────────────────────

def test_the_tech_lead_reads_the_SAME_module():
    """`verdict_line` used to hold the only reading of this dict. A second one written beside it
    for the panel is how two surfaces come to disagree about one review — which is the defect the
    whole floor ladder exists to have ended."""
    from openfactory.techlead import conversation

    src = inspect.getsource(conversation.verdict_line)
    assert "openfactory.review" in src
    assert "findings" not in src, "the tech-lead still picks the dict apart itself"


def test_the_two_renderers_never_disagree_about_the_SEVERITY():
    """They may word it differently — one is a prompt, one is a card. Neither may say the review
    was fine when the other says it was not."""
    for verdict in (REJECTED, APPROVED, {**APPROVED, "suppressions": ["noqa"]},
                    {**APPROVED, "stale": "rewritten"}):
        head = vr.headline(verdict)
        line = vr.line(verdict)
        if head["level"] == "ok":
            assert "rejected" not in line and "OUT OF DATE" not in line, line
            assert "ADDS gate-suppressions" not in line, line
        else:
            assert line, "the model's renderer says nothing about a change the card flags"


# ── 4. it actually reaches the screen ───────────────────────────────────────────────────────────

def test_the_gate_ROUTE_asks_for_it():
    from openfactory.api import app

    src = inspect.getsource(app.inbox)
    assert "_verdict_of" in src, "the inbox builds the gate card without the review again"
    assert '"review": review' in src, "it is read and then not put on the item"


def test_the_route_degrades_to_UNREADABLE_rather_than_to_nothing():
    from openfactory.api import app

    src = inspect.getsource(app._verdict_of)
    assert "unread=True" in src, (
        "a query that fails renders as 'no review', which tells somebody at a merge gate that "
        "nothing checked their diff")


def test_the_PANEL_paints_it_and_derives_nothing():
    assert "function reviewHtml(" in CODE, "the card has no place to show the review"
    assert "${reviewHtml(it.review)}" in CODE, "the renderer exists and nothing calls it"
    body = CODE[CODE.index("function reviewHtml("):]
    body = body[:body.index("\n}") + 2]
    for judging in ("rejected", "score", "severity", "critical"):
        assert judging not in body, (
            f"the page decides {judging!r} for itself instead of painting what the server said")


def test_the_badge_classes_it_emits_are_DEFINED():
    """`b-idle` was written here first and defined nowhere — the exact shape of #139, where a pill
    class was emitted for as long as the pill existed and styled by nobody."""
    body = CODE[CODE.index("function reviewHtml("):]
    body = body[:body.index("\n}") + 2]
    for cls in re.findall(r'"(b-[a-z]+)"', body):
        assert f".{cls}{{" in CODE, f"{cls} is painted onto the card and defined in no stylesheet"
