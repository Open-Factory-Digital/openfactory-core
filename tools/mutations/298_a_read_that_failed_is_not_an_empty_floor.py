"""Proven by breaking it — a read that failed is never painted as a floor with nothing on it (#298).

Four sites built the degraded engine frame — `/api/temporal/jobs`' two branches and the stream's
two — and each wrote `"jobs": []` beside `connected: False` for a question it never got to ask.
The page read that `[]` as the engine's answer: a running job left the screen for the seconds one
slow read arms `view._within`'s window, and "Scan TO-DO now" was offered over a held floor. The
floor ladder said the same sentence one route over — "nothing is running" over a job list it
could not read — and the pull request page drew an unread review timeline as "no review recorded".

FOUR CLAIMS:

  1. **A frame carries a job list exactly when it read one.** `None` when nobody could ask, `[]`
     still the engine's own "nothing", and a list read before a later read failed travels.
  2. **The page keeps the list it last had and marks it** — why the latest frame could not read
     it, and when the kept one was read — and a list a frame DID read clears the mark.
  3. **No scan is offered while the page cannot say whether the floor is busy**: after a failed
     read, and before the first one.
  4. **The floor never says "nothing is running" over a list it did not read**, and a review
     timeline or a description the page could not read is not drawn as an empty one.
  5. **The rest of the class, found by the same check**: the page's project list, a remote box's
     journal, and the poller's CLI each turned a failed read into an empty answer — "no projects
     yet", "this run wrote no journal", "in flight: nothing" right after a pause.

The guard is `tests/test_a_read_that_failed_is_not_an_empty_floor.py`.
"""

TEST = "tests/test_a_read_that_failed_is_not_an_empty_floor.py"

APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
LADDER = "openfactory/floor/ladder.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    # ── claim 1: the frame says it could not read ─────────────────────────────────────────────
    ("THE DEFECT ITSELF: the route's degraded frame answers `[]` for a list it could not read", APP,
     '        return {"connected": False, "address": addr, "error": str(exc)[:200], "jobs": jobs,',
     '        return {"connected": False, "address": addr, "error": str(exc)[:200], "jobs": [],'),

    ("…and so does the branch with no engine to ask", APP,
     '        return {"connected": False, "error": str(exc), "jobs": None, "build": build}',
     '        return {"connected": False, "error": str(exc), "jobs": [], "build": build}'),

    ("a job list the route read is thrown away because the schedule read after it failed", APP,
     '        return {"connected": False, "address": addr, "error": str(exc)[:200], "jobs": jobs,',
     '        return {"connected": False, "address": addr, "error": str(exc)[:200], "jobs": None,'),

    ("the stream repeats the filler on every tick of a blip", APP,
     '                         "jobs": None, "build": _build_report()}',
     '                         "jobs": [], "build": _build_report()}'),

    ("…and on the frame of a deployment with no engine to ask", APP,
     "'error': str(exc), 'jobs': None})}",
     "'error': str(exc), 'jobs': []})}"),

    ("a review timeline that could not be read reaches the page as one with no reviews", APP,
     'lambda **_: [])(pr=ref), default=None),',
     'lambda **_: [])(pr=ref), default=[]),'),

    # ── claim 2: the page keeps what it last knew, and marks it ───────────────────────────────
    ("THE DEFECT ON THE PAGE: a frame that could not read the list clears the floor", PANEL,
     "  else{next.jobs=Array.isArray(was.jobs)?was.jobs:[];",
     "  else{next.jobs=[];"),

    ("the kept list is not marked, so it is re-asserted as current", PANEL,
     '       next.jobs_unread=String(f.error||"the engine frame carried no job list")}',
     '       next.jobs_unread=""}'),

    ("the kept list is dated by the frame that failed, so it never looks old", PANEL,
     "next.jobs_read_at=was.jobs_read_at||0;",
     "next.jobs_read_at=Date.now();"),

    ("the mark outlives the failure, so a floor read again stays 'could not be read'", PANEL,
     'next.jobs_read_at=Date.now();next.jobs_unread=""}',
     'next.jobs_read_at=Date.now();next.jobs_unread=was.jobs_unread||""}'),

    ("the page has nothing to say over a list it could not read", PANEL,
     '  if(!engine.jobs_unread)return "";\n',
     '  return "";\n'),

    ("the project page never draws the mark", PANEL,
     '  if(stale){const said=jobsStaleLine();stale.innerHTML=said;'
     'stale.style.display=said?"":"none"}',
     '  if(stale){stale.style.display="none"}'),

    ("…and has nowhere to draw it", PANEL,
     '    <div id="jobsStale" style=',
     '    <div id="jobsStale-gone" style='),

    # ── claim 3: no scan the page cannot vouch for ────────────────────────────────────────────
    ("a scan is offered over a floor the page could not read", PANEL,
     "  const known=!!engine.jobs_read_at&&!engine.jobs_unread;",
     "  const known=true;"),

    ("a scan is offered before the first job list lands, on the `[]` the page declared", PANEL,
     "  const known=!!engine.jobs_read_at&&!engine.jobs_unread;",
     "  const known=!engine.jobs_unread;"),

    # ── claim 4: the floor, and the pull request page ─────────────────────────────────────────
    ("the floor says 'nothing is running' over a list it did not read", LADDER,
     '        lead = "it cannot say whether anything is running" if jobs_unread '
     'else "nothing is running"',
     '        lead = "nothing is running"'),

    ("the floor is called Armed beneath its own 'could not read'", LADDER,
     "    if (not out or all(c.rung >= 8 for c in out)) and not jobs_unread:",
     "    if not out or all(c.rung >= 8 for c in out):"),

    ("with the inbox in hand, an unread job list leaves nothing unread at all", LADDER,
     '    elif jobs_unread:\n        unread.append("the job list")\n',
     ""),

    ("a poller that has not fired yet vouches for a list nobody read", LADDER,
     '    if unread and (ev["verdict"] != "starting" or jobs_unread):',
     '    if unread and ev["verdict"] != "starting":'),

    ("the pull request page draws an unread timeline as 'no review recorded'", PANEL,
     "  if(p.events === null)\n",
     "  if(false)\n"),

    ("…and an unread description as 'nothing written'", PANEL,
     '<div class="md">${p.body === null',
     '<div class="md">${false'),

    # ── claim 5: the rest of the class ────────────────────────────────────────────────────────
    ("THE BOOT DEFECT: a project list that could not be read becomes 'no projects yet'", PANEL,
     "  if(Array.isArray(got))projects=got;",
     "  projects=Array.isArray(got)?got:[];"),

    ("the page starts from an empty project list nobody read", PANEL,
     "let projects=null,engine=",
     "let projects=[],engine="),

    ("a failed re-read throws away the project list the page has", PANEL,
     "  if(Array.isArray(got))projects=got;",
     "  projects=Array.isArray(got)?got:null;"),

    ("the boot never asks for the project list", PANEL,
     "  await loadProjects();",
     "  ;"),

    ("the board says there is no project when the list could not be read", PANEL,
     'toast("No project", projects===null',
     'toast("No project", false'),

    ("a remote box whose tail could not be built reads as a run that wrote nothing", APP,
     "    if tail is None:\n        raise JournalUnreadable(",
     "    if tail is None:\n        return local\n        raise JournalUnreadable("),

    ("a remote box whose read failed reads as a run that wrote nothing", APP,
     '        log.info("remote events unavailable for %s#%s (%s)", project, issue, exc)\n'
     "        raise JournalUnreadable(",
     '        log.info("remote events unavailable for %s#%s (%s)", project, issue, exc)\n'
     "        return local\n        raise JournalUnreadable("),

    ("an unreadable box's journal escapes the route as a 500 rather than a sentence", APP,
     "    except JournalUnreadable as exc:\n"
     "        raise HTTPException(status_code=503, detail=str(exc)) from exc",
     "    except KeyError as exc:\n"
     "        raise HTTPException(status_code=503, detail=str(exc)) from exc"),

    ("the log block draws a read that failed as a run with no journal", PANEL,
     "  if(why)\n",
     "  if(false)\n"),

    ("the briefing drops the reason its read failed", PANEL,
     "logBlock(evs,evsErr)",
     "logBlock(evs)"),

    ("the poller's CLI folds an unread job list into an empty one again", CLI,
     '"note": ""}), got.jobs',
     '"note": ""}), (got.jobs or [])'),

    ("an unread job list is said as nothing in flight", CLI,
     "    if jobs is None:\n        # AN UNREAD LIST",
     "    if False:\n        # AN UNREAD LIST"),

    ("a pause over a floor it could not read does not warn against rolling", CLI,
     "        if after_pause:\n"
     '            typer.echo("  the pause holds NEW pickups only, and this cannot say',
     "        if False:\n"
     '            typer.echo("  the pause holds NEW pickups only, and this cannot say'),
]
