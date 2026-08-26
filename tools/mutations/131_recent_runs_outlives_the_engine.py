"""#131: Recent runs reads the durable record too. Each cut restores a way to lose the history."""

TEST = "tests/test_recent_runs_outlives_the_engine.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    ("Recent runs goes back to the engine alone — the pilot's own screen", PANEL,
     "  window._recent=mergeRecent(js.filter(j=>j.status!=\"running\"));",
     '  window._recent=js.filter(j=>j.status!="running");'),

    ("a job in both records is listed twice", PANEL,
     "    .filter(j=>!seen.has(String(j.issue)))\n", "\n"),

    ("the two records are matched on values of different types", PANEL,
     "  const seen=new Set(fromEngine.map(j=>String(j.issue)));",
     "  const seen=new Set(fromEngine.map(j=>j.issue));"),

    ("the journal directory is re-read on every engine tick", PANEL,
     "function refreshProject(){\n  const name=curProject();if(!name)return;",
     'function refreshProject(){\n  const name=curProject();if(!name)return;\n'
     '  api("/api/jobs");'),

    ("nothing ever fetches the durable half", PANEL,
     "  loadJournalRuns(name);   // the durable half of Recent runs — see mergeRecent\n", ""),

    ("a forgotten run is presented as though the engine still held it", PANEL,
     "              cost_usd:j.cost_usd,pr_url:j.pr_url,events:j.events,forgotten:true}));",
     "              cost_usd:j.cost_usd,pr_url:j.pr_url,events:j.events}));"),

    ("its click opens the engine-backed briefing and dead-ends", PANEL,
     '        onclick="openJobLog(this.dataset.p,this.dataset.i)"',
     '        onclick="openJobDetail(this.dataset.p,this.dataset.i)"'),

    ("it stops saying why it is thinner", PANEL,
     '        <div class="sub">last seen ${when}${cost} · ${j.events||0} events · from the '
     "journal on\n          disk — this run is past the engine's retention window</div></div>",
     '        <div class="sub">last seen ${when}${cost}</div></div>'),

    ("an unreadable journal directory is reported as a floor that shipped nothing", PANEL,
     "      :window._journalUnread\n", "      :false\n"),

    ("a failed journal fetch is recorded as no runs at all", PANEL,
     "    window._journalUnread=true;", "    ;"),

    ("the durable listing starts asking the engine", "openfactory/api/app.py",
     "@app.get(\"/api/jobs\")\ndef list_jobs() -> list[dict]:\n    jobs: list[dict] = []",
     "@app.get(\"/api/jobs\")\ndef list_jobs() -> list[dict]:\n    # temporal\n"
     "    jobs: list[dict] = []"),
]
