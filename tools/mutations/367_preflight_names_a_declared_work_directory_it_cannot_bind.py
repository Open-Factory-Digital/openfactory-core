"""`preflight` names a declared `OPENFACTORY_WORK_DIR` compose cannot bind, and does not blame
`$HOME` for it (#367).

Run:  .venv/bin/python tools/mutate.py tools/mutations/367_preflight_names_a_declared_work_directory_it_cannot_bind.py

The rest of #367 — `init` and the installer refusing the value — is
`367_a_declared_work_directory_is_checked_like_a_kept_one.py`. This is the reader that plan left:
the probe caught `UnusableWorkDir` as its parent `UnusableHome`, answered None, and a declared
`~/work` was reported as "$HOME is not a directory this process can write under" (measured on
34c91c7, 2026-10-01). Row 1 is that defect; row 2 the check that names it, without which the
refusal reaches `_guarded` and is reported as preflight's own defect; row 3 the value it names.
"""

TEST = "tests/test_preflight_names_a_remedy_for_every_thing_it_refuses.py"

PREFLIGHT = "openfactory/preflight.py"
DEPLOYMENT = "openfactory/onboarding/deployment.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the probe swallows a declared refusal, and the finding blames `$HOME`",
     PREFLIGHT,
     "    except UnusableWorkDir:\n        raise\n",
     ""),

    ("the check does not catch the declared refusal, so it is reported as preflight's own defect",
     PREFLIGHT,
     "    except UnusableWorkDir as exc:\n",
     "    except NotImplementedError as exc:\n"),

    ("the refusal does not carry the value that was declared", DEPLOYMENT,
     '                "Nothing was written.", declared)\n',
     '                "Nothing was written.", "")\n'),
]
