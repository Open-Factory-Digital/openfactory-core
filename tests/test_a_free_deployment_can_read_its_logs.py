"""Nothing is LOST by having no cloud — only made free (pilot, 2026-08-15).

The panel offered a console button for logs, parameters and tasks. On a deployment with no
cloud those buttons pointed at pages that 404, so they were dropped — and dropping them left an
operator with no way to read what the agent did at all. His correction was the requirement:
*"I don't want to lose any of it — I just want to see it in a free option. Logs, for
example: I do want to see the logs, only in a free solution."*

Every job already writes a journal, locally and for free. What was missing was a surface:

  1. a FINISHED job's briefing shows that run's log (it had a PR and the engine and nothing else);
  2. the log a finished job shows is rendered by the SAME code as the live feed, so the two
     cannot drift into two different products;
  3. the journal is served with no cloud reachable, and no vendor credential consulted;
  4. when there is genuinely no journal, the panel names the free command that has the output —
     never a console.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openfactory.api.app import app

#: THE PATTERN AND THE STRIPPER LIVE NEXT DOOR (#147), imported rather than repeated. This file
#: carried its own copy of both, and two regexes for one rule is the defect the whole day was
#: about: they agree until somebody tightens one, and then the narrower is the one that decides.
from tests.test_a_hostile_value_stays_data import INLINE_HANDLER, without_comments

ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "openfactory" / "api" / "panel.html").read_text()


def _briefing() -> str:
    """The finished-job modal, from its function to the next one."""
    body = PANEL[PANEL.index("async function openJobDetail("):]
    return body[:body.index("\n// scan the board's TO-DO")]


def test_a_finished_jobs_briefing_shows_that_runs_log():
    b = _briefing()
    assert "/events" in b, (
        "the briefing of a job that already ran offers a PR and the engine — and no way to read "
        "what the agent actually did")
    assert re.search(r'S\("log', b), "the log is fetched and never rendered"


def test_the_replayed_log_is_the_SAME_renderer_as_the_live_feed():
    """One function builds an event line. Two would drift, and the run an operator watched would
    stop matching the run they read afterwards."""
    assert len(re.findall(r'<span class="k k-\$\{esc\(e\.kind\)\}"', PANEL)) == 1, (
        "an event line is built in more than one place — the live feed and the replay will drift")
    # ONE log block too: the briefing and the Logs view render the same thing the same way, so a
    # cap or a fallback added to one cannot be missing from the other.
    assert "logBlock(evs)" in _briefing()
    assert len(re.findall(r"function logBlock\(", PANEL)) == 1
    assert "evs.map(evLine)" not in PANEL.replace("shown.map(evLine)", ""), (
        "a second replay path bypasses logBlock")
    assert "shown.map(evLine)" in PANEL


def test_the_journal_is_served_with_no_cloud_and_no_vendor_credential(tmp_path, monkeypatch):
    """The free path, end to end: a journal on disk comes back through the API with the cloud
    switched OFF — and boto3 is never even imported to do it."""
    import sys

    from openfactory.paths import events_file
    from openfactory.registry import ProjectRegistry

    reg = tmp_path / "registry.yaml"
    reg.write_text(json.dumps({"projects": {"demo": {
        "name": "demo", "repo": "acme/demo", "repo_path": str(tmp_path / "repo")}}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "container")  # the free default: boxes are local
    for leaked in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(leaked, raising=False)

    path = events_file(ProjectRegistry().get("demo"), "7")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"ts": "2026-08-15T10:00:01", "kind": "state", "message": "spec_validation"})
        + "\n"
        + json.dumps({"ts": "2026-08-15T10:04:09", "kind": "agent_action",
                      "message": "wrote tests/test_x.py", "data": {"role": "executor"}}) + "\n")

    import openfactory.api.app as panel

    reached = []
    monkeypatch.setattr(panel, "_remote_tail", lambda *a, **k: reached.append(a) or None)

    monkeypatch.delitem(sys.modules, "boto3", raising=False)
    client = TestClient(app)
    events = client.get("/api/jobs/demo/7/events").json()

    assert [e["message"] for e in events] == ["spec_validation", "wrote tests/test_x.py"]

    # THE CASE THAT ACTUALLY EXERCISES THE CLOUD ARM: a job with no journal yet. With events on
    # disk the read short-circuits and would pass even if the guard were removed — which is how
    # this guard was caught being decoration (mutation, 2026-08-15).
    assert client.get("/api/jobs/demo/999/events").json() == []
    assert not reached, (
        "a deployment whose boxes run on this machine asked AWS for the log — every empty read "
        "costs a failed credential lookup and teaches the operator that log alarms are noise")
    assert "boto3" not in sys.modules, "reading a local log imported an AWS client"


def test_no_journal_names_the_free_command_and_no_console():
    """Every surface that can show an empty log shows the same answer, because they share one
    renderer — the briefing, the Logs list and a single run's log."""
    block = PANEL[PANEL.index("function logBlock("):]
    block = block[:block.index("function openLogs(")]
    assert "docker compose" in block and "logs worker" in block, (
        "with no journal the panel says nothing about where the output IS")
    assert "console.aws" not in block and "CloudWatch" not in block, (
        "a deployment with no cloud is being pointed at a cloud console")


def test_the_logs_button_goes_somewhere_on_a_deployment_with_no_cloud():
    """THE DEAD WORD. `Logs` was rendered from the CloudWatch link, so a free deployment showed it
    greyed out and unclickable — beside a factory writing a journal for every job. An operator
    reads that as "there are no logs here" (pilot, 2026-08-15: *"I didn't really understand
    the local log, but it has to exist"*)."""
    bar = PANEL[PANEL.index('<div class="links">'):]
    bar = bar[:bar.index("</div>")]
    assert "openLogs(" in bar, "with no cloud the Logs button still leads nowhere"
    assert "L.cloudwatch" in bar, "the cloud console is no longer offered where it exists"
    # the two that stay unreachable must at least SAY where the thing is
    assert ".env.compose" in bar and "docker ps" in bar


def test_no_background_updater_paints_over_a_page_it_does_not_own():
    """THE PAGE THAT WENT HOME BY ITSELF. The engine tick, the inbox read and the project-list
    push each called `renderIndex()` whenever `curProject()` was null — true of every page that is
    not a project's floor. So a few seconds after opening the Logs page (or the product surface),
    the floor index painted itself over it, with the URL still saying otherwise (pilot,
    2026-08-15: *"I open a project's logs and it goes back to the home page… without me doing anything"*).

    Asserted as a PROPERTY over every call site, so the next background reader inherits it."""
    body = PANEL[PANEL.index("function viewOwner()"):]
    for m in re.finditer(r"renderIndex\(\)", PANEL):
        line_start = PANEL.rfind("\n", 0, m.start())
        line = PANEL[line_start:PANEL.find("\n", m.start())]
        if line.strip().startswith("//"):
            continue  # a COMMENT explaining the rule is not a violation of it — this guard
            # matched the paragraph that documents the defect, which is how the last three
            # decorative guards in this repository were written
        if "function renderIndex" in line or "curProject()?renderProject" in line:
            continue  # the definition, and the router itself, which is allowed to choose
        # The question may be asked on the line or two above it (`const owner=viewOwner()`), so
        # the window is the statement, not the character.
        window = PANEL[max(0, line_start - 220):m.end()]
        assert "viewOwner()" in window, (
            f"this repaints the floor index without asking who owns the screen: {line.strip()}")
    assert 'if(curLogs())return "logs"' in body and 'curProduct()!==null)return "product"' in body


def test_a_log_has_its_own_address():
    """A modal is the wrong shape for something an operator READS. It got a quarter of the screen,
    no way to search inside a run, and no link to send anybody — so a run's log is a PAGE now, and
    a specific run is a URL (pilot, 2026-08-15: *"shouldn't this be a bigger screen of its
    own, with filters and so on?"*)."""
    assert "function curLogs()" in PANEL
    assert re.search(r"/\^\\/logs", PANEL), "there is no /logs route"
    assert "if(curLogs()){renderLogsPage();return}" in PANEL, (
        "the route exists and nothing dispatches to it — the page is unreachable")
    assert 'go(`/logs/${encodeURIComponent(project)}/${encodeURIComponent(issue)}`)' in PANEL, (
        "a single run has no address of its own — nobody can link to what they found")


def test_the_way_back_returns_where_the_operator_came_from():
    """"← floor" from a project's logs went to the projects INDEX — the operator was reading one
    project and got handed the list of all of them. The page carries its project, so the list is
    scoped to it and the way back is that project's floor."""
    page = PANEL[PANEL.index("async function renderLogsPage("):]
    page = page[:page.index("function paintLogList(")]
    assert "at.project?`/p/${encodeURIComponent(at.project)}`" in page, (
        "the way back ignores which project's logs are open")
    scope = PANEL[PANEL.index("function paintLogList("):]
    assert "!at.project||r.project===at.project" in scope, (
        "a project-scoped address shows every project's runs anyway")


def test_the_address_survives_a_refresh(tmp_path, monkeypatch):
    """A client-side route the SERVER does not answer works until somebody presses F5 or opens
    the link they were sent — and then the product's own URL is a 404."""
    reg = tmp_path / "registry.yaml"
    reg.write_text("{}")
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))
    client = TestClient(app)
    for url in ("/logs", "/logs/podbeam/87"):
        r = client.get(url)
        assert r.status_code == 200, f"{url} is unreachable except by clicking"
        assert "renderLogsPage" in r.text


def test_the_page_filters_by_more_than_a_substring():
    """"With filters and so on" was the ask, and a filter that only greps the visible row text is
    the appearance of one: the state a run ended in is the question an operator actually has."""
    body = PANEL[PANEL.index("function paintLogList("):]
    body = body[:body.index("async function loadJobLog(")]
    assert 'id="logstate"' in PANEL and "r.state===want" in body, (
        "the list cannot be narrowed to failures, merges, or anything else that matters")
    assert "logq" in PANEL, "there is no free-text search"

    run = PANEL[PANEL.index("function paintJobLog("):]
    assert 'id="logfind"' in run, "a run's log cannot be searched — the reason a page exists"
    assert "show all" in run, "a capped log offers no way to see the rest"


def test_the_local_log_list_is_read_from_the_journals_not_the_engine():
    """Journals outlive the engine's history. A list built from Temporal loses the log of every
    job the engine has forgotten, while the file sits on disk — so the door is `/api/jobs`, which
    globs the journal directory."""
    body = PANEL[PANEL.index("async function renderLogsPage("):]
    body = body[:body.index("async function loadJobLog(")]
    assert '"/api/jobs"' in body
    assert "temporal" not in body.lower(), "the log list was built from the engine's memory"


def test_a_log_view_never_renders_an_unbounded_journal():
    """A four-hour pass writes thousands of events; a modal is not a file. Capped, and the cap is
    STATED — a silent truncation reads as "that is the whole run"."""
    body = PANEL[PANEL.index("function logBlock("):]
    body = body[:body.index("function openLogs(")]
    assert "_LOG_CAP" in body and "slice(-_LOG_CAP)" in body
    assert "showing the last" in body, "the cap is silent — the operator reads a partial log as all"


#: Handlers that still take their arguments as a JS string inside an HTML attribute. `esc()` maps
#: `'` to `&#39;`, which is right for TEXT and wrong here: the HTML parser decodes it back to `'`
#: BEFORE the script is parsed, so a value carrying a quote breaks out of the call. These 9 are
#: pre-existing (#119); the list is a RATCHET — it may shrink, never grow.
#: EMPTY, AND THAT IS THE POINT (#147). Seven handlers were grandfathered here: they predated the
#: rule and were left alone so the ratchet could stop NEW ones while somebody dealt with the old.
#: They are all gone now — every value travels as a data attribute and a single delegated listener
#: reads it — so the list that protected them protects nothing, and an empty allowlist is the only
#: state in which "no handler may do this" is simply true.
_INLINE_ARG_HANDLERS: set[str] = set()

def test_no_row_passes_a_name_through_a_javascript_string_in_an_attribute():
    """`esc()` is correct for element TEXT and insufficient inside an attribute: the HTML parser
    DECODES the value before the JavaScript in it is parsed, so `&#39;` becomes a real quote and
    the call closes early —

        key = "');alert(document.cookie);//"
        →  decide('acme','7','');alert(document.cookie);//')

    Two statements; the second runs. And `DecisionOption.key` is an unvalidated string parsed out
    of an AGENT's fenced JSON, so it is influenceable by the text of a ticket on a client's board.

    A data attribute has no such seam: the parser decodes it into a string and `dataset` hands
    that string over, never as source.
    """
    offenders = {m.group(1) for m in INLINE_HANDLER.finditer(without_comments(PANEL))}
    new = offenders - _INLINE_ARG_HANDLERS
    assert not new, (
        f"these handlers take a value through a JS string in an attribute: {sorted(new)} — give "
        f"the button `data-act` plus `data-*` values and let the delegated listener read them")
    gone = _INLINE_ARG_HANDLERS - offenders
    assert not gone, (
        f"{sorted(gone)} no longer does this — remove it from the ratchet so it cannot come back")
    for handler in ("openJobLog", "openJobDetail"):
        assert f"{handler}(this.dataset.p,this.dataset.i)" in PANEL


def test_the_DELEGATED_LISTENER_is_the_only_way_those_buttons_act():
    """One listener, because every one of these buttons is regenerated inside an `innerHTML` on
    almost every frame: attaching per element would mean re-attaching after each render, and the
    one render somebody forgets is a dead button on a gate a human is waiting at."""
    assert "const ACTS={" in PANEL and 'closest("[data-act]")' in PANEL
    for verb in ("decide", "mergeGate", "actJob", "answerQuestion", "openPromote",
                 "submitPromote", "scanNow"):
        assert f"{verb}:" in PANEL.split("const ACTS={")[1].split("};")[0], (
            f"{verb} has buttons carrying `data-act` and no entry to dispatch them")


def test_an_UNKNOWN_verb_is_named_rather_than_ignored():
    """A typo in one of twenty call sites would otherwise look exactly like a button the operator
    failed to press."""
    body = PANEL.split('closest("[data-act]")')[1].split("});")[0]
    assert "console.warn" in body, "an unrecognised action fails silently"


def test_an_empty_log_list_names_the_next_step_not_just_the_fact():
    """A healthy factory, a card sitting in Backlog, and a Logs box that says only "no journal
    yet" is a dead end: the operator cannot tell whether the feature is broken, the deployment is
    broken, or nothing has run. The floor logs a run when it TAKES a card, and it only takes from
    TO-DO — so that is what the empty state says (pilot, 2026-08-15)."""
    body = PANEL[PANEL.index("function paintLogList("):]
    body = body[:body.index("async function loadJobLog(")]
    assert "TO-DO" in body, "the empty list never says where a run comes from"
    assert "Scan TO-DO now" in body, "the empty list does not name the button that starts one"
    assert "no run matches this filter" in body, (
        "a filter that matches nothing is reported as 'nothing has ever run' — two different "
        "situations on one screen")
    assert "couldn't read the journals" in body, (
        "and 'the panel could not ask' is a third situation, not the same blank")


def test_the_logs_view_says_it_could_not_ask_rather_than_showing_nothing():
    """`api()` returns the body for ANY status, so an expired token answers an object. Mapping
    over it throws and leaves a blank page, which reads as "this deployment has no logs"."""
    body = PANEL[PANEL.index("async function renderLogsPage("):]
    body = body[:body.index("function paintLogList(")]
    assert "Array.isArray(r)" in body


def test_a_project_this_deployment_does_not_have_is_a_404(tmp_path, monkeypatch):
    """`registry.get` raises KeyError; unhandled it reaches the browser as a 500, which reads as
    a broken panel for what is only a stale bookmark."""
    reg = tmp_path / "registry.yaml"
    reg.write_text("{}")
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))
    client = TestClient(app)
    assert client.get("/api/jobs/ghost/1/events").status_code == 404
    assert client.get("/api/jobs/ghost/1/stream").status_code == 404


@pytest.mark.parametrize("gauge", ["cloudwatch", "ssm", "ecs"])
def test_no_cloud_button_is_the_only_way_to_reach_a_capability(gauge):
    """The rule the half-fix broke: a button may be cloud-only, but the CAPABILITY may not be.
    Whatever a console button reaches, the how-to states the free way to reach it too."""
    free_counterpart = {
        "cloudwatch": "docker compose --env-file .env.compose logs -f worker",
        "ssm": ".env.compose",
        "ecs": "docker ps",
    }[gauge]
    assert free_counterpart in PANEL, (
        f"{gauge} is the only route to this capability — an install with no cloud loses it")
