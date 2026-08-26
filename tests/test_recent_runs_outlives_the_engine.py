"""The floor's history survives the engine forgetting it (#131).

The operator opened his floor ~26h after shipping two tickets and read, in the Recent runs box:

    nothing shipped yet

Both journals were on disk the whole time. The list was built from the ENGINE alone, and Temporal's
namespace had aged those executions out — so a true statement about one record was published as a
claim about the factory, and the claim was false.

RAISING THE RETENTION (#131) SHORTENS THE WINDOW; IT DOES NOT CLOSE IT. On day 31 the same screen
tells the same lie. The fix has to be about WHERE HISTORY LIVES: the engine is the live half —
status, gates, wedged, deploy, everything a running job needs — and the journals are the half that
outlives it. Recent runs is history, so it reads both.

THREE THINGS A FORGOTTEN RUN MUST NOT DO, each its own guard below: claim to be absent, offer a
link into an engine that no longer has it, or pretend to know what it cannot (a title, a duration,
a gate list). It is thinner, it says why, and its click goes to the log that is actually there.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from openfactory.api import app as api

PANEL = (Path(inspect.getfile(api)).parent / "panel.html").read_text()
#: The page's JavaScript with `//` comments stripped — a rule this file asserts about CODE, and a
#: comment mentioning a symbol has already satisfied two guards in this repository by accident.
CODE = "\n".join(ln for ln in PANEL.splitlines() if not ln.lstrip().startswith("//"))


def _fn(name: str) -> str:
    """One function's body, so a guard cannot be satisfied by a different one's code."""
    start = CODE.index(f"function {name}(")
    rest = CODE[start:]
    end = rest.index("\n}\n")
    return rest[:end]


# ── 1. history reads both records ───────────────────────────────────────────────────────────────

def test_recent_runs_is_built_from_the_engine_AND_the_journals():
    body = _fn("refreshProject")
    assert "mergeRecent(" in body, (
        "Recent runs is back to the engine alone — the day its retention window passes, the floor "
        "reports that nothing ever shipped")
    assert "_journalRuns" in _fn("mergeRecent")


def _merge(engine_rows, journal_rows):
    """Run the panel's OWN `mergeRecent` under node, on fixtures.

    ASSERTING THE TEXT WAS NOT ENOUGH, and the mutation run proved it the same hour: the guard
    read `"String(j.issue)" in body`, the anchor appears TWICE in that function, and cutting one
    of them left the other — a merge that no longer matches `89` against `"89"`, with the guard
    green. This is the third time today that a substring guard has been satisfied by a second
    occurrence of its own anchor, so this one executes the function instead."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the source-level guards below still run")
    script = (_fn("mergeRecent") + "\n}\n"
              + f"window={{_journalRuns:{json.dumps(journal_rows)}}};\n"
              + f"console.log(JSON.stringify(mergeRecent({json.dumps(engine_rows)})));")
    out = subprocess.run([node, "-e", "var window;" + script],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:500]
    return json.loads(out.stdout)


def test_the_ENGINE_row_wins_where_both_records_have_the_job():
    """The engine's row carries the title, the gates and the deploy; the journal's is a fallback,
    not a duplicate. Two rows for one ticket would be the merge announcing itself as a bug."""
    merged = _merge(
        [{"issue": "89", "title": "from the engine", "state": "merged", "close_time": "2026-08-17"}],
        [{"project": "p", "issue": "89", "state": "reviewing", "updated": "2026-08-16"}])

    assert len(merged) == 1, f"one ticket, two rows: {merged}"
    assert merged[0]["title"] == "from the engine" and not merged[0].get("forgotten")


def test_a_ticket_the_two_records_SPELL_differently_is_still_one_job():
    """`/api/jobs` reads its issue off a filename (a string); the engine reads it off a workflow
    id. A merge that compares them raw shows the same run twice, and the operator has no way to
    know which of the two to believe."""
    merged = _merge(
        [{"issue": 89, "title": "engine", "state": "merged", "close_time": "2026-08-17"}],
        [{"project": "p", "issue": "89", "state": "reviewing", "updated": "2026-08-16"}])

    assert len(merged) == 1, f"89 and \"89\" were treated as two tickets: {merged}"


def test_a_run_ONLY_the_journal_has_is_carried_over_and_marked():
    merged = _merge(
        [],
        [{"project": "p", "issue": "87", "state": "pr_open", "updated": "2026-08-15",
          "cost_usd": 2.67, "events": 101}])

    assert [j["issue"] for j in merged] == ["87"]
    assert merged[0]["forgotten"] is True
    assert merged[0]["cost_usd"] == 2.67 and merged[0]["events"] == 101, (
        "what the journal DOES know is dropped on the way into the row")


def test_the_merged_list_is_newest_first():
    """Recent runs is read top-down. Two records with two clocks, concatenated, would put a run
    from last week above one from this morning."""
    merged = _merge(
        [{"issue": "90", "state": "merged", "close_time": "2026-08-17T10:00"}],
        [{"project": "p", "issue": "87", "state": "pr_open", "updated": "2026-08-15T09:00"},
         {"project": "p", "issue": "89", "state": "reviewing", "updated": "2026-08-16T15:41"}])

    assert [j["issue"] for j in merged] == ["90", "89", "87"]


def test_the_journals_are_read_ONCE_per_project_and_not_per_tick():
    """`refreshProject` runs on every engine frame. A finished run's journal does not change, and
    re-reading the directory every three seconds spends IO to re-learn a fact."""
    assert "/api/jobs" not in _fn("refreshProject"), (
        "the journal directory is re-read on every engine tick")
    assert '"/api/jobs"' in _fn("loadJournalRuns")
    assert "loadJournalRuns(" in _fn("renderProject"), "nothing ever fetches the durable half"


# ── 2. what a forgotten run may and may not say ─────────────────────────────────────────────────

def test_a_forgotten_run_is_marked_as_coming_from_the_journal():
    assert "forgotten:true" in _fn("mergeRecent"), (
        "a run read off disk is presented as though the engine still held it")
    assert "j.forgotten" in _fn("recentRow")


def test_it_offers_no_link_into_an_engine_that_no_longer_has_it():
    """A `temporal_url` for an execution the namespace dropped is a link to a 404 — and this row
    exists precisely because the engine forgot."""
    row = _fn("recentRow")
    forgotten = row[row.index("if(j.forgotten)"):row.index("const dur=")]
    assert "temporal_url" not in forgotten, "it links into the engine for a run the engine lost"
    assert "openJobDetail" not in forgotten, (
        "the click opens the engine-backed briefing, which answers 'job not found' about a run "
        "this very row proves exists")
    assert "openJobLog" in forgotten, "the click is a dead end"


def test_it_says_WHY_it_is_thinner_rather_than_inventing_what_it_lacks():
    row = _fn("recentRow")
    forgotten = row[row.index("if(j.forgotten)"):row.index("const dur=")]
    assert "journal" in forgotten and "retention" in forgotten, (
        "a row with no title and no duration appears next to full ones with no explanation")
    assert "j.title" not in forgotten and "fmtDur" not in forgotten, (
        "it renders fields the journal does not carry")


def test_the_log_route_it_points_at_is_one_the_server_answers():
    """`/logs/<project>/<issue>` is served, not only reachable by clicking — a client-side route
    the server 404s is a link that works until somebody refreshes the page."""
    assert "/logs/" in _fn("openJobLog")
    routes = [d for d in inspect.getsource(api).splitlines() if "@app.get(\"/logs" in d]
    assert any("{project}/{issue}" in r for r in routes), (
        f"the panel sends a forgotten run to a route this app does not serve: {routes}")


# ── 3. the empty state stops making a claim ─────────────────────────────────────────────────────

def test_nothing_shipped_yet_is_only_said_when_BOTH_records_are_empty():
    body = _fn("renderRecent")
    assert "_journalUnread" in body, (
        "an unreadable journal directory is still reported as a floor that shipped nothing — the "
        "absence-reads-as-an-answer defect, on the sentence that started this card")
    empty = body[body.index("if(!list.length)"):]
    assert "nothing shipped yet" in empty and "could not be read" in empty


def test_a_journal_read_that_FAILED_is_not_an_empty_history():
    body = _fn("loadJournalRuns")
    assert "_journalUnread" in body, "a directory we could not read is recorded as no runs"
    assert "catch" in body, "a failed fetch takes the whole project page down"


# ── 4. the durable half is genuinely reachable ──────────────────────────────────────────────────

def test_the_endpoint_it_reads_lists_runs_the_ENGINE_never_sees():
    """`/api/jobs` globs the journal DIRECTORY rather than asking the engine — which is the entire
    reason it still held the pilot's two runs when the namespace had dropped them.

    The first cut of this guard was written as `... if hasattr(...) else True` — a test that
    silently becomes a no-op the moment its subject is renamed. Named directly instead."""
    src = inspect.getsource(api.list_jobs)
    assert "project_log_dir" in src, "the durable listing stopped reading the journals"
    assert "temporal" not in src.lower(), (
        "the journal listing now asks the engine — the one source that forgets, on the one door "
        "that exists because it forgets")


@pytest.mark.parametrize("field", ["project", "issue", "state", "updated", "events", "cost_usd"])
def test_the_merge_uses_only_fields_the_journal_actually_carries(field):
    """A merge that reads a field the endpoint never returns renders `undefined` in a row an
    operator is meant to trust."""
    assert re.search(rf"j\.{field}\b", _fn("mergeRecent")), (
        f"`{field}` is dropped on the way from the journal into the row")
