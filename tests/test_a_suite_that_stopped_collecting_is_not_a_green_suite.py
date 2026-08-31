"""Forty tests that stopped being collected exit 0 exactly as convincingly as forty that passed.

`docs/STATUS.md` states the ceiling: *"the `setup:` and `validate:` commands are shell strings and
only the exit code is read."* `_SUPPRESSION_RE` closes the small version of the hole — a `# noqa`
added to silence one error. The large version was open: deleting a test file out of discovery,
renaming it out of the collector's glob, or breaking an import so a whole module stops loading are
all invisible to an exit code, and every one of them makes the suite greener.

Three properties are load-bearing:

  1. THE GATE IS A COUNT, THE REASON IS A SET. A set difference would flag every renamed test as a
     vanished one, and renaming tests is ordinary work — the guard would human-gate refactors and
     be switched off within a week.
  2. THE THREE STATES ARE READ AS THREE. No census is not a census of zero. A project that
     declares no inventory command must be untouched by all of this.
  3. THE SUMMARY LINE IS NOT A TEST. `pytest --collect-only -q` prints `120 tests collected in
     0.52s`, whose DURATION changes between two runs of an unchanged suite — compared naively that
     is a test vanishing on every job of every project.
"""

from __future__ import annotations

from openfactory.contracts import Manifest, RunResult, ValidationResult
from openfactory.orchestrator.merge_policy import should_auto_merge
from openfactory.policy import census

_PASS = [ValidationResult(name="test", command="t", exit_code=0, passed=True)]


def _result(**kw) -> RunResult:
    base = dict(ticket_id="#1", state="pr_open", validations=_PASS)
    base.update(kw)
    return RunResult(**base)


# ── reading one run's output ────────────────────────────────────────────────────────────────────


def test_the_pytest_summary_line_is_not_counted_as_a_test():
    """THE FALSE POSITIVE THAT WOULD HAVE KILLED THIS GUARD. The duration changes between two runs
    of an unchanged suite, so a naive comparison reports a vanished test on every job."""
    out = "tests/test_a.py::test_one\ntests/test_a.py::test_two\n\n120 tests collected in 0.52s\n"

    assert census.inventory_of(out) == ("tests/test_a.py::test_one", "tests/test_a.py::test_two")


def test_a_header_line_is_not_counted_as_a_test():
    """`dotnet test -t` prints "The following Tests are available:" before the names."""
    out = "The following Tests are available:\n    ACM.Tests.OrderTests.Places\n"

    assert census.inventory_of(out) == ("ACM.Tests.OrderTests.Places",)


def test_an_identifier_the_platform_has_never_seen_is_kept_verbatim():
    """The platform does not know what a test id looks like in a language it has never heard of,
    and guessing would be the same mistake as guessing the command."""
    assert census.inventory_of("ACM::Order#places_an_order\nsuite/thing_spec.rb:14\n") == (
        "ACM::Order#places_an_order", "suite/thing_spec.rb:14")


def test_no_output_is_no_identifiers():
    assert census.inventory_of("") == ()
    assert census.inventory_of(None) == ()


# ── the gate is a count; the reason is a set ────────────────────────────────────────────────────


def test_a_rename_does_not_gate_because_the_count_did_not_move():
    """PROPERTY 1. Renaming tests is ordinary work, and a guard that human-gates refactors gets
    switched off within a week."""
    before = ("t::a", "t::b")
    after = ("t::a_renamed", "t::b")

    assert len(after) == len(before)
    assert should_auto_merge(
        Manifest(merge_policy="auto"),
        _result(test_census_before=len(before), test_census_after=len(after))) is True


def test_a_test_that_stopped_being_collected_holds_the_merge():
    m = Manifest(merge_policy="auto")

    assert should_auto_merge(m, _result(test_census_before=120, test_census_after=119)) is False
    assert should_auto_merge(m, _result(test_census_before=120, test_census_after=120)) is True


def test_a_suite_that_grew_is_not_gated():
    assert should_auto_merge(
        Manifest(merge_policy="auto"),
        _result(test_census_before=120, test_census_after=140)) is True


def test_the_vanished_identifiers_are_the_reason_even_when_a_rename_is_among_them():
    """The list a person reads. It is deliberately NOT the gate — a rename appears here and does
    not hold the merge."""
    gone = census.vanished(("t::a", "t::b", "t::c"), ("t::a_renamed", "t::b"))

    assert gone == ("t::a", "t::c")


def test_the_reason_names_the_drop_and_the_tests():
    line = census.reason(120, 119, ("tests/test_orders.py::test_refund",))

    assert "120" in line and "119" in line
    assert "tests/test_orders.py::test_refund" in line
    assert census.reason(120, 120, ()) == "", "a suite that did not shrink has nothing to say"


# ── the three states ────────────────────────────────────────────────────────────────────────────


def test_a_project_with_no_inventory_command_is_untouched_by_all_of_this():
    """PROPERTY 2, and the one that keeps this from human-gating every project on earth for a
    feature none of them has adopted."""
    assert census.inventory_command(Manifest()) is None
    assert should_auto_merge(Manifest(merge_policy="auto"), _result()) is True


def test_a_declared_command_is_read_and_a_blank_one_is_not():
    assert census.inventory_command(Manifest(test_inventory="pytest --collect-only -q")) == (
        "pytest --collect-only -q")
    assert census.inventory_command(Manifest(test_inventory="   ")) is None


def test_a_census_taken_before_and_impossible_after_holds_the_merge():
    """The agent broke enumeration — an import error in a test module, a collector that no longer
    loads. It is one of the failures this exists to catch, so "no after" is not "no news"."""
    assert should_auto_merge(
        Manifest(merge_policy="auto"),
        _result(test_census_before=120, test_census_after=None)) is False


def test_no_census_before_gates_nothing_even_when_there_is_none_after_either():
    """`None` before is "we never measured", not "it fell to zero"."""
    assert should_auto_merge(
        Manifest(merge_policy="auto"),
        _result(test_census_before=None, test_census_after=None)) is True


def test_zero_collected_is_a_measurement_and_not_an_absence():
    """A command that ran and collected nothing is a real and alarming answer; it must not read as
    "no census". This is the `None is not {}` doctrine at the only place it could be lost."""
    assert should_auto_merge(
        Manifest(merge_policy="auto"),
        _result(test_census_before=120, test_census_after=0)) is False
    # and a suite that was empty and stayed empty has not regressed
    assert should_auto_merge(
        Manifest(merge_policy="auto"),
        _result(test_census_before=0, test_census_after=0)) is True


# ── the attempt has to TAKE it, and then RECORD it ──────────────────────────────────────────────


def _runner_with(cmd, out, rc=0):
    from openfactory.orchestrator.machine import JobRunner

    return JobRunner, type("_H", (), {
        "manifest": Manifest(test_inventory=cmd) if cmd else Manifest(),
        "sandbox": type("_S", (), {
            "run": staticmethod(lambda workspace=None, command=None, timeout=None: (rc, out)),
        })(),
    })()


def test_the_attempt_enumerates_the_suite_when_the_project_declares_how():
    JobRunner, holder = _runner_with(
        "pytest --collect-only -q", "t::a\nt::b\n3 tests collected in 0.1s\n")

    assert JobRunner._take_census(holder, None) == ("t::a", "t::b")


def test_an_inventory_command_that_fails_is_no_census_rather_than_an_empty_one(caplog):
    """A command that exited 1 has not told us there are zero tests."""
    JobRunner, holder = _runner_with("pytest --collect-only -q", "boom", rc=2)

    with caplog.at_level("WARNING"):
        assert JobRunner._take_census(holder, None) is None
    assert "exited 2" in caplog.text


def test_a_project_that_declares_nothing_is_never_asked():
    JobRunner, holder = _runner_with(None, "")

    assert JobRunner._take_census(holder, None) is None


def test_the_attempt_records_the_counts_and_the_reason_so_the_gate_can_read_them():
    """The gate holds a `RunResult`, not a workspace. An answer dropped on the way there exists
    for the length of one method and changes nothing."""
    from openfactory.orchestrator.machine import JobRunner

    holder = type("_H", (), {
        "_census_before": ("t::a", "t::b", "t::c"),
        "_census_after": ("t::a", "t::b"),
    })()
    result = _result()

    JobRunner._record_risk(holder, result)

    assert result.test_census_before == 3
    assert result.test_census_after == 2
    assert result.test_census_gone == ["t::c"]


def test_an_attempt_that_never_took_a_census_records_none_rather_than_zero():
    """The three states, at the seam where two of them are easiest to collapse."""
    from openfactory.orchestrator.machine import JobRunner

    result = _result()
    JobRunner._record_risk(type("_H", (), {})(), result)

    assert result.test_census_before is None
    assert result.test_census_after is None
    assert result.test_census_gone == []


def test_a_command_that_ran_and_collected_nothing_is_a_measurement_not_an_absence():
    """`0` and `None` are the pair this whole design turns on, and this is the seam where they are
    easiest to collapse: an empty tuple is falsy, so one `or None` erases the most alarming answer
    the census can give."""
    JobRunner, holder = _runner_with("pytest --collect-only -q", "0 tests collected in 0.01s\n")

    assert JobRunner._take_census(holder, None) == ()


# ── the ORDER, which is the difference between a census and a census of nothing ─────────────────


class _Recorder:
    """A sandbox that remembers what it was asked to run, in order."""

    def __init__(self, inventory_out: str = "t::a\nt::b\n"):
        self.calls: list[str] = []
        self._inventory_out = inventory_out

    def run(self, workspace=None, command=None, timeout=None):
        self.calls.append(command)
        if "collect-only" in (command or ""):
            return 0, self._inventory_out
        return 0, ""

    def diff_paths(self, workspace=None):
        return ["src/app.py"]


def test_the_before_census_is_taken_by_setup_and_only_after_it_installed_anything():
    """THE ORDERING, AND IT IS NOT A DETAIL. The inventory command imports the test suite, so a
    census taken before `setup:` runs enumerates a tree with no dependencies — it collects nothing,
    every later census looks like growth, and the gate becomes a green light over exactly the hole
    it closes."""
    from openfactory.orchestrator.machine import JobRunner

    sandbox = _Recorder()
    holder = type("_H", (), {
        "manifest": Manifest(setup=["pip install -e .", "npm ci"],
                             test_inventory="pytest --collect-only -q"),
        "sandbox": sandbox,
        "_emit": lambda self, ticket, kind, text: None,
        # the real method, so the ORDER under test is the real one
        "_take_census": JobRunner._take_census,
    })()

    JobRunner._run_setup(holder, None, None)

    assert holder._census_before == ("t::a", "t::b"), "setup must leave a census behind"
    assert sandbox.calls == ["pip install -e .", "npm ci", "pytest --collect-only -q"], (
        "the census ran before the dependencies it needs were installed")


def test_validation_takes_the_after_census_beside_the_other_questions_it_asks_the_diff():
    """If `_validate` never enumerates the edited tree, a project that adopted the census gets a
    permanent "could not measure" — and read as no news, that merges everything."""
    from openfactory.orchestrator.machine import JobRunner

    holder = type("_H", (), {
        "manifest": Manifest(test_inventory="pytest --collect-only -q"),
        "sandbox": _Recorder("t::a\n"),
        "_set_state": lambda self, ticket, state: None,
        "_run_validations": lambda self, ws, touched, ticket: [],
        "_take_census": JobRunner._take_census,
    })()

    JobRunner._validate(holder, None, None)

    assert holder._census_after == ("t::a",)
