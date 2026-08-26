"""#139: a frame must not erase the facts it does not carry.

The first cuts restore the blindness that shipped: the stream stops sending the poller's state,
the page goes back to replacing its whole engine object, the boot read disappears. The rest attack
the OTHER direction — a merge that never overwrites, an error that is inherited for ever, a job
list that is kept across a disconnect. Both signs matter: this defect is a page believing something
it was never told, and every fix for it can fail by believing the wrong thing twice as hard.
"""

TEST = "tests/test_a_frame_does_not_erase_what_it_omits.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── the blindness this card removes ─────────────────────────────────────────────────────────
    ("the stream stops carrying the poller's state", APP,
     '                    slow = {"intake": await tv.intake(client), "build": _build_report()}',
     '                    slow = {"build": _build_report()}'),

    ("the stream stops carrying the build stamps", APP,
     '                    slow = {"intake": await tv.intake(client), "build": _build_report()}',
     '                    slow = {"intake": await tv.intake(client)}'),

    ("the cached pair is computed and never reaches the frame", APP,
     '                         "jobs": await tv.list_jobs(client, ns), **slow}',
     '                         "jobs": await tv.list_jobs(client, ns)}'),

    ("the disconnected frame drops the build stamps again", APP,
     '                frame = {"connected": False, "address": addr, "error": str(exc)[:200],'
     ' "jobs": [],\n                         "build": _build_report()}',
     '                frame = {"connected": False, "address": addr, "error": str(exc)[:200],'
     ' "jobs": []}'),

    ("a blip carries a stale poller read across it", APP,
     "                slow, slow_at = {}, 0.0   # never carry an intake read from before the "
     "blip\n",
     ""),

    ("the schedule read stops being throttled — a status line becomes load", APP,
     "_STREAM_SLOW_S = 10.0", "_STREAM_SLOW_S = 0.0"),

    ("the merge becomes a blanket, inheriting keys nobody decided to keep", PANEL,
     "  const next={...f};", "  const next={...was,...f};"),

    ("a fact the frame omits is dropped instead of kept", PANEL,
     "  for(const k of ENGINE_KEPT_IF_ABSENT) if(!(k in f) && (k in was)) next[k]=was[k];\n", ""),

    ("nothing asks for the complete state before the stream opens", PANEL,
     "  await loadEngine();\n", ""),

    ("the painters go back inside the parser's catch", PANEL,
     "    let f; try{f=JSON.parse(e.data)}catch(_){return} // eslint-disable-line\n"
     "    applyEngineFrame(f);\n    applyEngine();",
     "    try{applyEngineFrame(JSON.parse(e.data));applyEngine()}catch(_){} "
     "// eslint-disable-line"),

    ("this page's own fetch failure is announced as the engine being down", PANEL,
     '  let f=null; try{f=await api("/api/temporal/jobs")}catch(e){_engineErr=String(e&&e.message'
     '||e)}',
     '  let f=null; try{f=await api("/api/temporal/jobs")}catch(e){engine={connected:false,'
     'jobs:[]}}'),

    # ── the other direction: believing the wrong thing twice as hard ─────────────────────────────
    ("the merge never overwrites, so the first answer is pinned for ever", PANEL,
     "  for(const k of ENGINE_KEPT_IF_ABSENT) if(!(k in f) && (k in was)) next[k]=was[k];",
     "  for(const k of ENGINE_KEPT_IF_ABSENT) if(k in was) next[k]=was[k];"),

    ("only the poller's state survives its absence — the build stamps go blind again", PANEL,
     'const ENGINE_KEPT_IF_ABSENT=["intake","build","address","ui_base"];',
     'const ENGINE_KEPT_IF_ABSENT=["intake","address","ui_base"];'),

    ("an error is added to the allowlist and pins the first blip on screen", PANEL,
     'const ENGINE_KEPT_IF_ABSENT=["intake","build","address","ui_base"];',
     'const ENGINE_KEPT_IF_ABSENT=["intake","build","address","ui_base","error"];'),

    ("a disconnected frame keeps the jobs from before it", PANEL,
     '  next.jobs=Array.isArray(f.jobs)?f.jobs:[];',
     '  next.jobs=Array.isArray(f.jobs)&&f.jobs.length?f.jobs:(was.jobs||[]);'),

    ("a non-object answer is allowed to rewrite the floor", PANEL,
     '  if(!f||typeof f!=="object")return;\n', ""),

    # ── the two live bugs this pass removes ─────────────────────────────────────────────────────
    ("the redraw key outlives the view again", PANEL,
     "  window._machineKey=null;", "  window._machineKey=window._machineKey;"),

    ("the degraded transport loses its treatment again", PANEL,
     ".b-warn{background:var(--amber-wash);color:var(--amber);border-color:var(--amber-glow)}",
     ".b-warn-unused{color:inherit}"),
]
