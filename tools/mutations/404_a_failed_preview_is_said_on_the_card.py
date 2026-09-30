"""Mutation plan for #404 — a preview start is said at once and followed, and a failed one is said
as a failure, in the project's language.

Every row must turn `tests/test_a_failed_preview_is_said_on_the_card.py` red.
"""

TEST = "tests/test_a_failed_preview_is_said_on_the_card.py"
PAGE = "openfactory/api/panel.html"
APP = "openfactory/api/app.py"
LIVE = "openfactory/preview/live.py"

MUTATIONS = [
    ("an accepted start is not remembered — the drawer redraws the record it replaced", PAGE,
     '    else if(d.state === "starting") _pvPending[id] = {was: Number(s||0), until: Date.now() + PV_PENDING_MS};',
     "    else {}"),
    ("the section stops asking while it waits for the start to begin", PAGE,
     '  if(r.state === "starting" || waiting) _pvPoll[id]',
     '  if(r.state === "starting") _pvPoll[id]'),
    ("a waiting click never gives up", PAGE,
     "  if(pend && (Date.now() > pend.until || r.live",
     "  if(pend && (r.live"),
    ("the record's own start is not what ends the wait", PAGE,
     "              || (r.started_at || 0) !== pend.was)) delete _pvPending[id];",
     "              )) delete _pvPending[id];"),
    ("a failed preview is drawn like an untouched card again", PAGE,
     '  } else if(r.state === "failed"){',
     '  } else if(false){'),
    ("the failure's reason is not drawn under its headline", PAGE,
     "    if(r.why) out.push(line(r.why));\n    if(r.can_start) out.push(`<div style=\"margin-top:8px\"><button class=\"btn\" ${data} onclick=\"previewAct(this,'start')\">start again</button>",
     "    if(r.can_start) out.push(`<div style=\"margin-top:8px\"><button class=\"btn\" ${data} onclick=\"previewAct(this,'start')\">start again</button>"),
    ("the button carries no start to compare with", PAGE,
     ' data-id="${esc(id)}" data-s="${esc(String(r.started_at||0))}"`;',
     ' data-id="${esc(id)}"`;'),
    ("the body carries no headline", APP,
     '            "headline": pv_live.headline(found, can_start=judged.can_start, language=language),',
     '            "headline": "",'),
    ("the body carries no start time", APP,
     '            "started_at": found.started_at if found else 0,',
     '            "started_at": 0,'),
    ("the headline ignores the project's language", LIVE,
     "    return voice.say(voice.PREVIEW, key, language, **params)",
     "    return voice.say(voice.PREVIEW, key, 'en', **params)"),
    ("a failed preview's headline is the ended one", LIVE,
     '    if found is not None and found.state == preview.FAILED:\n        return _say("preview.failed", language)',
     '    if False:\n        return ""'),
    ("the comment's link does not walk into the preview", PAGE,
     "    if(first && first.url) location.assign(safeUrl(first.url));",
     "    if(false) location.assign(safeUrl(first.url));"),
    ("the comment's route is not served", APP,
     '@app.get("/p/{project}/preview/{ref}")\n',
     ""),
]
