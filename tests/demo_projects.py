"""Where the hand-built toy projects live — resolved ONCE, for every test that reads them.

Five test modules each hardcoded `Path.home() / "Projects" / "<the author's own directory>"`,
and that one line was two problems wearing each other's clothes:

  * it published a former product name five times in a repository about to go public, and
  * it made every one of those tests **unrunnable for anybody except the author** — they call
    `pytest.skip` when the directory is absent, so for a contributor they did not fail, they
    vanished. A test that silently skips forever is worse than one that fails: nothing tells you
    the coverage is gone.

`OPENFACTORY_FIXTURES` fixes the second, and the first fell out of it: the directory is named in
exactly one place, under the product's name. (A fallback to the author's pre-rename directory
lived here until 2026-08-25; it served one laptop and the guard in
`test_the_product_carries_no_ones_past.py` now forbids the name it carried.)
"""

from __future__ import annotations

import os
from pathlib import Path

#: Where the toy projects live when nobody set the environment. The environment always wins; a
#: contributor points it at their own clone of the toy projects and every gated test in this
#: suite runs for them.
_DEFAULT = "openfactory-fixtures"


def demo_projects() -> Path | None:
    """The directory, or None when there is none to read.

    `None`, never a path that does not exist — the caller's next move is `pytest.skip`, and
    handing back a plausible-looking missing path is how a skip turns into a confusing failure
    three frames later.
    """
    named = (os.environ.get("OPENFACTORY_FIXTURES") or "").strip()
    if named:
        # AN EXPLICIT SETTING THAT IS WRONG MUST NOT FALL BACK. Silently using a different
        # directory than the one somebody named is the shape of every configuration bug in this
        # repository: it works, and it works on the wrong thing.
        path = Path(named).expanduser()
        return path if path.is_dir() else None
    path = Path.home() / "Projects" / _DEFAULT
    return path if path.is_dir() else None


#: A directory that exists nowhere, used as the module-scope stand-in below. Named for what it is,
#: so a path that leaks into a failure message says why it is missing instead of looking like a
#: typo somebody should chase.
_NOWHERE = Path("/openfactory-has-no-toy-projects-here")


def demo_projects_root() -> Path:
    """The directory, or a path that does not exist — safe to build constants from at MODULE SCOPE.

    `demo_projects()` answers `None` on purpose, and that contract is right for a caller inside a
    function whose next move is `pytest.skip`. At module scope it is a landmine: `FIXTURES / "x"`
    raises `TypeError` at IMPORT, and one module that raises during collection takes the ENTIRE
    suite with it — pytest reports `Interrupted: 1 error during collection` and runs nothing.

    IT DID, FOR FIFTEEN DAYS. `test_env_proposes_before_it_verifies.py` built such a constant on
    2026-08-06; every CI run from that commit to 2026-08-21 collected zero tests and failed, 253 of
    them, while the suite was green on the one machine that happens to have the toy projects on
    disk. The gate the platform applies to every client repository was dark on its own.

    Three other modules had already each invented `or Path("/nonexistent")` to dodge this. That is
    the same question answered in four places, and the fourth answered it wrong."""
    return demo_projects() or _NOWHERE
