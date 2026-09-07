"""The sizer names the area — the cuts that leave the plan blind to where a change lands."""

TEST = "tests/test_the_sizer_names_the_area_it_expects_to_touch.py"

MUTATIONS = [
    ("the parser drops the touches",
     "openfactory/runtime/temporal/activities.py",
     '                     for p in (d.get("touches") or []) if str(p).strip()][:30],\n',
     '                     for p in [] if str(p).strip()][:30],\n'),

    ("the sizer is never asked for it",
     "openfactory/org_defaults/roles/sizer.md",
     '  "touches": ["<the files or directories you expect the change to touch — [] when you '
     'cannot tell>"]\n',
     '  "touches": []\n'),
]
