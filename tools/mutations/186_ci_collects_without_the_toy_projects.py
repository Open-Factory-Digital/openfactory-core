"""#186: collection does not depend on the author's optional working state.

The defect these cuts restore ran CI on ZERO tests for fifteen days (253 red runs, last green
2026-08-06) while this machine stayed green — so the only interesting question about the new guard
is whether it goes red when the defect comes back. Each cut below is a real shape it arrived in.
"""

TEST = "tests/test_ci_runs_what_we_run.py"
D = "tests/demo_projects.py"
E = "tests/test_env_proposes_before_it_verifies.py"

MUTATIONS = [
    # THE DEFECT ITSELF, verbatim as `88139ad` wrote it: a module-scope constant built by dividing
    # an Option by a name. Raises TypeError at import, which aborts the whole collection.
    ("the module divides None by a name at import again", E,
     "FIXTURES = demo_projects_root()",
     "from tests.demo_projects import demo_projects  # noqa\nFIXTURES = demo_projects()"),

    # THE SOFT HALF, and the reason the count assertion exists. A module that swallows the import
    # error stops raising — it just stops existing, and the suite silently shrinks.
    ("the module vanishes from collection instead of raising", E,
     "FIXTURES = demo_projects_root()",
     "import pytest as _p\nfrom tests.demo_projects import demo_projects\n"
     "if demo_projects() is None:\n    _p.skip('no fixtures', allow_module_level=True)\n"
     "FIXTURES = demo_projects_root()"),

    # THE HELPER GOING BACK TO BEING A LANDMINE. If `demo_projects_root` can answer None, every
    # caller is one edit away from the original defect and the guard must say so.
    ("the module-scope helper starts answering None again", D,
     "    return demo_projects() or _NOWHERE",
     "    return demo_projects()"),
]

#: The SECOND defect the same accident exposed, in the same file it lives in. Kept here rather
#: than in its own plan because it is one commit's worth of repair: the marker that went dark is
#: the marker `.gitignore` now refuses.
OWNER = "tests/test_the_product_carries_no_owners_name.py"

MUTATIONS += [
    ("a tracked file missing from disk is skipped into silence again", OWNER,
     "    except OSError:\n        pass",
     "    except OSError:\n        return None", OWNER),

    ("…and the index fallback stops carrying the content", OWNER,
     "        return out.stdout.decode(\"utf-8\")",
     "        return \"\"", OWNER),

    ("a file staged for deletion is resurrected and judged anyway", OWNER,
     "    if out.returncode != 0:\n        return None",
     "    if out.returncode != 0:\n        return \"\"", OWNER),
]

#: The docs header that must name a REAL commit, not a plausible-looking one.
DRIFT = "tests/test_the_docs_do_not_drift.py"
STATUS = "docs/STATUS.md"

MUTATIONS += [
    ("STATUS.md names a commit that does not exist", STATUS,
     "main at `015f806`", "main at `deadbee`", DRIFT),
]
