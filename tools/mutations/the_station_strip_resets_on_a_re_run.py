"""The station strip belongs to one run — the cuts that put two runs back on one strip."""

TEST = "tests/test_the_station_strip_resets_on_a_re_run.py"

MUTATIONS = [
    ("the strip is never reset",
     "openfactory/api/panel.html",
     '    if(e.message=="spec_validation"){focus.reached=-1;focus.mode="running";}\n',
     ''),

    ("the reset comes after the fold, so Math.max re-applies the old maximum",
     "openfactory/api/panel.html",
     '    if(e.message=="spec_validation"){focus.reached=-1;focus.mode="running";}\n'
     '    if(idx>=0)focus.reached=Math.max(focus.reached,idx);\n',
     '    if(idx>=0)focus.reached=Math.max(focus.reached,idx);\n'
     '    if(e.message=="spec_validation"){focus.reached=-1;focus.mode="running";}\n'),

    ("the ticks reset but the mode keeps saying failed",
     "openfactory/api/panel.html",
     '    if(e.message=="spec_validation"){focus.reached=-1;focus.mode="running";}\n',
     '    if(e.message=="spec_validation"){focus.reached=-1;}\n'),
]
