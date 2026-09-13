"""#125: the block prints the reason it was handed, and never one it invented.

The reverses are where a fix like this goes wrong quietly: a fallback that names a plausible cause
is the same defect written as a default, and a findings shelf that renders when there is nothing
wrong teaches the reader to stop looking at it.
"""

TEST = "tests/test_the_requirements_block_says_what_it_was_told.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    ("the block guesses a credential again, while holding the reason", PANEL,
     '    const why=_prod.reqsWhy||"it did not say why";',
     '    const why="the documentation repository may need a credential";'),

    ("…and the reverse: the fallback names a cause instead of admitting ignorance", PANEL,
     '"it did not say why"', '"a credential is probably missing"'),

    ("the reason is never captured, so there is nothing to print", PANEL,
     '  _prod.reqsWhy=(out&&out.message)?String(out.message):"";',
     '  _prod.reqsWhy="";'),

    ("the corpus's complaints are never captured", PANEL,
     '  _prod.reqsFindings=(out&&out.data&&Array.isArray(out.data.findings))?out.data.findings:[];',
     "  _prod.reqsFindings=[];"),

    ("an empty corpus stops carrying the error that explains it", PANEL,
     '    el.innerHTML=`<div class="empty" style="padding:18px">nothing written yet</div>`+notes;return;',
     '    el.innerHTML=`<div class="empty" style="padding:18px">nothing written yet</div>`;return;'),

    ("a finding's message reaches the page as markup", PANEL,
     '    + `<div class="grow">${esc(f.message||"")}</div>`',
     '    + `<div class="grow">${f.message||""}</div>`'),
]
