"""A module is an AREA, and the survey now says which areas the work lands on.

WHAT THIS CLOSES. The survey knew everything about a module except the one fact that predicts where
the next change goes, and it ordered its own table by SIZE — which on a long-lived codebase is the
wrong question: the biggest module is routinely the one nobody has opened in years. The table is
capped at 40, so that sort decides which 40 of a large repository a reader ever sees.

AND THE SENTENCE NOBODY COULD SAY. Churn was on one side, `tests_inside` / `tested_by` on the
other, both correct, and nothing crossed them — so the most-changed undefended area of a codebase
read exactly like the quietest one. Measured on a real client bundle: the most-changed business
file in the repository had no live test and its own test file existed, commented out. Every fact
recorded separately; the sentence nowhere.

THE FIXTURE IS BUILT SO THE TWO ORDERINGS DISAGREE. `reporting` is the biggest module and
`billing` is the busiest, on purpose: a fixture where size and churn happen to agree would let a
`busiest_modules` that had lost its sort entirely pass every guard here.

WHAT IS NOT CLAIMED. `named_by_no_test` is not "untested" — name matching is not coverage, which is
this platform's own rule, and the renderer repeats it. This says nobody could find a module's tests
by looking.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openfactory.onboarding import context as ctx
from openfactory.onboarding.history import read_history

pytestmark = pytest.mark.skipif(shutil.which("git") is None,
                                reason="the join reads a real repository with real git")

NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)


def _git(repo: Path, *args: str, when: str = "", who: str = "Ada Lovelace") -> None:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": who, "GIT_AUTHOR_EMAIL": "dev@example.invalid",
                "GIT_COMMITTER_NAME": who, "GIT_COMMITTER_EMAIL": "dev@example.invalid"})
    if when:
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                    "-C", str(repo), *args], check=True, capture_output=True, env=env)


def _commit(repo: Path, files: dict[str, str], subject: str, when: str,
            who: str = "Ada Lovelace") -> None:
    for name, body in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A", when=when, who=who)
    _git(repo, "commit", "-q", "-m", subject, when=when, who=who)


@pytest.fixture()
def legacy(tmp_path: Path) -> Path:
    """`reporting` is BIGGEST: 5 files, one commit each, and `tests/test_reporting.py` names it.
    `billing` is BUSIEST: 2 files but five commits land on them, by two people, and nothing names
    it.

    THE TWO ORDERINGS MUST DISAGREE or this file proves nothing — a `busiest_modules` that had lost
    its sort entirely would return the same order and pass. Counted in FILE CHANGES, which is what
    the field measures: reporting 5 (five files, one import commit), billing 6 (two files imported,
    then four commits on `invoice.py`)."""
    repo = tmp_path / "legado"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Ada Lovelace")
    _git(repo, "config", "user.email", "dev@example.invalid")

    _commit(repo, {
        "reporting/__init__.py": "",
        "reporting/monthly.py": "def monthly():\n    return []\n",
        "reporting/quarterly.py": "def quarterly():\n    return []\n",
        "reporting/annual.py": "def annual():\n    return []\n",
        "reporting/export.py": "def export():\n    return b''\n",
        "tests/test_reporting.py": "def test_monthly():\n    assert True\n",
        "billing/__init__.py": "",
        "billing/invoice.py": "def total():\n    return 0\n",
    }, "initial import #1", "2026-06-01T09:00:00+00:00")

    # `start=1` because n=0 would rewrite the import commit's exact bytes and `git
    # commit` refuses an empty change — a fixture that fails to build is a guard
    # that never ran.
    for n, (subject, when) in enumerate((
            ("fix: rounding #42", "2026-07-10T09:00:00+00:00"),
            ("fix: currency", "2026-07-20T09:00:00+00:00"),
            ("fix: discounts", "2026-08-05T09:00:00+00:00"),
            ("fix: tax AB#77", "2026-08-20T09:00:00+00:00")), start=1):
        _commit(repo, {"billing/invoice.py": f"def total():\n    return {n}\n"},
                subject, when, who="Grace Hopper")
    return repo


@pytest.fixture()
def surveyed(legacy: Path):
    return ctx.survey(str(legacy), history=read_history(legacy, now=NOW))


# ── the join ─────────────────────────────────────────────────────────────────────────────────────

def test_a_module_carries_the_churn_of_its_own_files(surveyed) -> None:
    """The control. A module's churn is the churn of the files under it, attributed by the same
    walk-up the file and test joins already use — so a path counted for the map and a path counted
    for the log cannot land in different modules."""
    billing = next(m for m in surveyed.modules if m.name.endswith("billing"))

    # SIX, and the arithmetic is the point: `billing` holds two files, the import commit touched
    # both, and four commits then touched `invoice.py`. This counts FILE CHANGES, which is what the
    # field is called — one commit touching five files of a module counts five. The first version
    # of this guard asserted a commit count against a field that never was one, and the fixture
    # that came with it could not tell the two orderings apart.
    assert billing.file_changes == 6
    assert billing.last_touched == "2026-08-20"


def test_the_people_are_counted_once_per_module_not_once_per_file(legacy: Path) -> None:
    """Summing each file's author count reports a team where there is one maintainer, which is the
    opposite of the truth a reader needs from this number."""
    _commit(legacy, {"billing/tax.py": "RATE = 1\n", "billing/invoice.py": "def total():\n    x=1\n"},
            "chore: split", "2026-08-21T09:00:00+00:00", who="Grace Hopper")

    surveyed = ctx.survey(str(legacy), history=read_history(legacy, now=NOW))
    billing = next(m for m in surveyed.modules if m.name.endswith("billing"))

    assert billing.author_count == 2, "Ada and Grace, however many files each touched"


def test_the_work_items_reach_the_module(surveyed) -> None:
    """The `asked` tier, at the granularity a reader acts on: which tickets landed on this area."""
    billing = next(m for m in surveyed.modules if m.name.endswith("billing"))

    assert "#42" in billing.tickets and "AB#77" in billing.tickets


# ── the ordering, which decides which 40 a reader ever sees ──────────────────────────────────────

def test_the_busiest_module_is_not_the_biggest_one(surveyed) -> None:
    """THE WHOLE POINT, and the reason the fixture is shaped as it is. `reporting` has five files
    and `billing` one; `billing` is where the work goes."""
    assert surveyed.biggest_modules[0].name.endswith("reporting")
    assert surveyed.busiest_modules[0].name.endswith("billing")


def test_without_a_history_the_ordering_falls_back_to_size(legacy: Path) -> None:
    """A caller always gets an ordering rather than an empty list it has to special-case — and the
    fallback is the old behaviour exactly, so nothing regresses where nobody read the log."""
    surveyed = ctx.survey(str(legacy))

    assert surveyed.history is None
    assert [m.name for m in surveyed.busiest_modules] == \
        [m.name for m in surveyed.biggest_modules]


def test_the_rendered_table_says_which_ordering_is_in_force(surveyed, legacy: Path) -> None:
    """A reader who assumes the wrong ordering draws exactly the wrong conclusion from a correct
    table — and the table is capped, so the ordering is the whole of what they see."""
    with_log = ctx.render_survey(surveyed, language="en")
    without = ctx.render_survey(ctx.survey(str(legacy)), language="en")

    assert "ordered by how much they change" in with_log
    assert "does NOT say where the work happens" in without


# ── the sentence ─────────────────────────────────────────────────────────────────────────────────

def test_the_area_that_changes_and_that_no_test_names_is_named(surveyed) -> None:
    """Both halves were already collected and correct. Crossing them is the finding."""
    exposed = [m.name for m in surveyed.changed_and_named_by_no_test]

    assert any(n.endswith("billing") for n in exposed)


def test_an_area_that_changes_and_IS_named_by_a_test_is_not_listed(surveyed) -> None:
    """The positive twin. Without it, a property that returned every changed module would pass the
    guard above and the finding would carry no information."""
    exposed = [m.name for m in surveyed.changed_and_named_by_no_test]

    assert not any(n.endswith("reporting") for n in exposed)


def test_a_quiet_area_nothing_names_is_not_a_finding(legacy: Path) -> None:
    """An area nothing names is unremarkable in a corner nobody touches. Listing it would bury the
    one area that matters in a list of ones that do not — which is how a finding becomes noise."""
    (legacy / "attic").mkdir()
    (legacy / "attic" / "__init__.py").write_text("")
    (legacy / "attic" / "old.py").write_text("def old():\n    return 1\n")
    _commit(legacy, {}, "unused", "2026-01-02T09:00:00+00:00") if False else None
    _git(legacy, "add", "-A", when="2020-01-02T09:00:00+00:00")
    _git(legacy, "commit", "-q", "-m", "import the attic", when="2020-01-02T09:00:00+00:00")

    surveyed = ctx.survey(str(legacy), history=read_history(legacy, now=NOW))
    attic = next(m for m in surveyed.modules if m.name.endswith("attic"))

    assert attic.named_by_no_test, "the fixture must give it no test, or it proves nothing"
    assert attic.file_changes == 0, "and no churn inside the window"
    assert not any(m.name.endswith("attic") for m in surveyed.changed_and_named_by_no_test)


def test_without_a_history_the_finding_says_it_cannot_be_said(legacy: Path) -> None:
    """AN EMPTY LIST WOULD BE A MEASUREMENT — "every changed area is named by a test". Without the
    history there is no measurement, only an absence, and the two must not render alike."""
    rendered = ctx.render_survey(ctx.survey(str(legacy)), language="en")

    assert "cannot be said" in rendered
    assert "every area that changed" not in rendered


def test_the_finding_does_not_claim_coverage_it_cannot_measure(surveyed) -> None:
    """Name matching is not coverage — this platform's own rule, and the renderer has to keep
    repeating it or the finding overclaims and a reader stops trusting the rest."""
    rendered = ctx.render_survey(surveyed, language="en")

    assert "naming is not covering" in rendered


def test_both_languages_carry_the_finding(surveyed) -> None:
    """A deliverable a client keeps cannot be half in a language nobody there asked for."""
    assert "Áreas que mudam" in ctx.render_survey(surveyed, language="pt-BR")
    assert "Areas that change" in ctx.render_survey(surveyed, language="en")


def test_the_finding_reaches_the_prompt(surveyed) -> None:
    """The agent pass gets one read of this repository. If the finding stops at the human document
    the agent is still reading a size-ordered table and asking about the wrong areas."""
    prompt = ctx.build_prompt(surveyed, language="en")

    assert "Areas that change and that NO test names" in prompt
    assert "billing" in prompt


def test_churn_from_a_file_the_map_cannot_READ_still_lands_on_its_area(legacy: Path) -> None:
    """THE WALK-UP, and the case that makes it matter. A changed path is attributed to the module
    that OWNS it, not to its own directory — so `billing/sql/migrate.sql` counts as work on
    `billing` even though `billing/sql` is no module and `.sql` is a language the map cannot read.

    This is not a corner. It is the ordinary shape of a legacy repository: migrations, templates,
    stored procedures and config carry real change and the structural map is blind to every one of
    them. Attributing by directory would drop that churn into modules that do not exist, and an
    area would under-report exactly where the map is already weakest.

    It is also what a .NET solution needs, where one project folds every subfolder beneath it."""
    _commit(legacy, {"billing/sql/migrate.sql": "ALTER TABLE invoice ADD tax NUMERIC;\n"},
            "chore: migration #900", "2026-08-22T09:00:00+00:00")

    surveyed = ctx.survey(str(legacy), history=read_history(legacy, now=NOW))
    billing = next(m for m in surveyed.modules if m.name == "billing")

    assert not any(m.name == "billing.sql" for m in surveyed.modules), (
        "the fixture must give `billing/sql` no module of its own, or the walk-up is untested")
    assert billing.file_changes == 7, "the migration is work on billing"
    assert "#900" in billing.tickets


def test_the_rendered_table_is_actually_ordered_by_change(surveyed) -> None:
    """ASSERTS THE ROWS, NOT THE CAPTION. The first version of this checked only the sentence above
    the table, so a mutation that reverted the table to size order under a caption saying
    "ordered by how much they change" survived — a correct table under a caption that inverts it,
    which is worse than either alone."""
    rendered = ctx.render_survey(surveyed, language="en")
    table = rendered[rendered.index("## Modules"):]
    rows = [ln for ln in table.splitlines() if ln.startswith("| `")]

    assert rows, "no module rows were rendered"
    assert rows[0].startswith("| `billing`"), rows[:3]
