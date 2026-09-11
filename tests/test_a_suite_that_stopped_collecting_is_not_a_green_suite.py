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

AND THE FILTER CANNOT CARRY THAT PROPERTY ALONE, which review on #19 measured against this
repository's own suite with the example this feature shipped. The warnings-summary block `-q` does
not suppress is counted too, it moves in both directions, and the dangerous direction is UP: delete
three tests, add four deprecation warnings, and the census RISES while the suite shrank. The three
answers are here — the shipped examples are the quiet forms, the counts are logged so an adopter
sees the discrepancy on day one, and the vanished set prints whenever it is non-empty rather than
only when the count fell.
"""

from __future__ import annotations

from openfactory.contracts import Manifest, RunResult, Ticket, ValidationResult
from openfactory.orchestrator.merge_policy import should_auto_merge
from openfactory.policy import census

_PASS = [ValidationResult(name="test", command="t", exit_code=0, passed=True)]
_TICKET = Ticket(id="#1", title="make the CI green", objective="o", repo="acme/app")


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


def test_a_non_ascii_digit_does_not_make_a_line_a_summary():
    """`'\u0663'.isdigit()` is True, and so is a superscript's. The intent is an ASCII number."""
    assert census.inventory_of("\u0663_tests::first\n") == ("\u0663_tests::first",)


_NOISY_COLLECT = """tests/test_a.py::test_one
tests/test_a.py::test_two
tests/test_a.py::test_three

=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /x/fastapi/testclient.py:1: StarletteDeprecationWarning: install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
3 tests collected in 0.52s
"""


def test_the_filter_cannot_save_a_noisy_command_and_the_gate_fails_OPEN():
    """THE FIRST BLOCKING FINDING ON #19, MEASURED AND KEPT. `-q` does not suppress the warnings
    block, none of its lines starts with a digit or ends with `:`, so all of them are counted as
    tests. Measured against this repository's real output: 8529 counted where pytest reported 8524.

    The direction that matters is UP. Delete tests, have the change add deprecation warnings, and
    the census RISES while the suite shrank — the gate compares counts, the counts moved the wrong
    way, and the merge proceeds through the module's own shipped example."""
    counted = census.inventory_of(_NOISY_COLLECT)

    assert len(counted) == 3 + 5, (
        "if this is 3 the filter got smarter, and the reasoning below needs rewriting rather than "
        "the test deleting")

    # the same output, three tests deleted and four new warnings — the count goes UP
    before = counted
    after = census.inventory_of(
        "tests/test_a.py::test_one\n"
        + _NOISY_COLLECT.split("\n", 3)[3]
        + "\nw1\nw2\nw3\nw4\n")

    assert len(after) > len(before), "the reproduction of the defect, kept so it stays visible"
    gone = census.vanished(before, after)
    assert "tests/test_a.py::test_two" in gone and "tests/test_a.py::test_three" in gone, (
        "`vanished()` is the part of this design that survives a noisy command")
    assert census.reason(len(before), len(after), gone), (
        "and the reason must SAY so — silencing it on the count is silencing the only signal left")


def test_the_shipped_examples_are_the_quiet_form_of_the_command():
    """The example is what every adopter pastes, so the platform's own must satisfy the contract
    the platform states. `pytest --collect-only -q` alone does not."""
    from pathlib import Path

    from openfactory.contracts import manifest as manifest_mod

    example = Path("docs/project.yaml.example").read_text(encoding="utf-8")
    src = Path(manifest_mod.__file__).read_text(encoding="utf-8")

    for text, where in ((example, "docs/project.yaml.example"), (src, "contracts/manifest.py")):
        assert "pytest --collect-only -q -p no:warnings --no-header" in text, (
            f"{where} still shows a pytest census command whose warnings block is counted as tests")
        assert "ONE IDENTIFIER PER LINE" in text.upper(), (
            f"{where} does not state the contract a silent miss depends on")


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


def test_the_vanished_set_is_not_cut_inside_the_measurement():
    """A list truncated here is a number nobody can recover — the same split `undeclared_paths`
    and `undeclared_count` already make, and the same defect `protected_hits` was reviewed for."""
    before = tuple(f"t::case_{i:03d}" for i in range(40))

    assert len(census.vanished(before, ())) == 40


def test_the_reason_names_the_drop_and_the_tests():
    line = census.reason(120, 119, ("tests/test_orders.py::test_refund",))

    assert "120" in line and "119" in line
    assert "tests/test_orders.py::test_refund" in line
    assert census.reason(120, 120, ()) == "", "a suite that shrank by nothing has nothing to say"


def test_the_reason_is_not_silenced_by_the_comparison_that_let_the_merge_through():
    """THE FINDING REVIEW ON #19 NAMED, KEPT AS A TEST. `reason()` early-returned on
    `after >= before`, which is precisely the case where a person most needs the list: three tests
    deleted, four warning lines added by the same change, count UP, gate open — and `vanished()`
    holding the right answer with nobody to tell. The set is the part of this design that survives
    a noisy command; gating its output on the count throws away the one signal left."""
    line = census.reason(120, 121, ("tests/test_orders.py::test_refund",))

    assert "tests/test_orders.py::test_refund" in line
    assert "did not fall" in line


def test_the_reason_survives_the_none_the_fields_actually_carry():
    """`RunResult.test_census_before` is `int | None` BY DESIGN — the whole three-state argument
    turns on it — so a signature typed `int` made this raise `TypeError` while a pull request body
    was being built, which is the worst place to discover it."""
    assert census.reason(None, 5, ()) == ""
    assert census.reason(None, None, ()) == ""


def test_a_census_that_could_not_be_taken_after_the_change_gets_its_own_sentence():
    """One of the three failures the gate holds for, and it had no message at all: the agent broke
    enumeration, so the suite can no longer say what it contains."""
    line = census.reason(120, None, ())

    assert "could not be taken after" in line and "120" in line


def test_the_truncated_list_still_carries_the_true_number():
    """`MAX_SHOWN` bounds what a person is SHOWN, never what was measured — and the number is not
    recoverable from the count drop, since a rename is minus-one-plus-one by this design's own
    argument. The comment used to promise a `vanished_count` that existed nowhere."""
    many = tuple(f"t::case_{i:03d}" for i in range(40))

    line = census.reason(200, 160, many[:census.MAX_SHOWN], len(many))

    assert "and 28 more" in line


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
    for the length of one method and changes nothing.

    THE "AFTER" IS TAKEN HERE, ONCE. `_validate` runs on the initial pass, the repair pass, the
    review-repair pass and the post-rebase re-validation, and a census at each cost a full
    test-collection run apiece while this method overwrote the field every time — every one but
    the last paid for and discarded."""
    from openfactory.orchestrator.machine import JobRunner

    sandbox = _Recorder("t::a\nt::b\n")
    holder = type("_H", (), {
        "manifest": Manifest(test_inventory="pytest --collect-only -q"),
        "sandbox": sandbox,
        "_census_before": ("t::a", "t::b", "t::c"),
        "_census_ws": object(),
        "_take_census": JobRunner._take_census,
    })()
    result = _result()

    JobRunner._record_risk(holder, result)

    assert result.test_census_before == 3
    assert result.test_census_after == 2
    assert result.test_census_gone == ["t::c"]
    assert result.test_census_gone_count == 1
    assert sandbox.calls == ["pytest --collect-only -q"], (
        "the after-census must be taken exactly once, at the point the result is built")


def test_no_baseline_means_the_after_census_is_not_paid_for_at_all():
    """A census with nothing to compare against gates nothing, so running the command to produce a
    number no reader has a use for is a test-collection run spent on nothing."""
    from openfactory.orchestrator.machine import JobRunner

    sandbox = _Recorder()
    holder = type("_H", (), {
        "manifest": Manifest(test_inventory="pytest --collect-only -q"),
        "sandbox": sandbox,
        "_census_ws": object(),
        "_take_census": JobRunner._take_census,
    })()

    JobRunner._record_risk(holder, _result())

    assert sandbox.calls == []


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

    JobRunner._run_setup(holder, None, None, at_base=True)

    assert holder._census_before == ("t::a", "t::b"), "setup must leave a census behind"
    assert sandbox.calls == ["pip install -e .", "npm ci", "pytest --collect-only -q"], (
        "the census ran before the dependencies it needs were installed")


def test_validation_hands_on_the_workspace_the_census_will_be_taken_in():
    """If `_validate` never records which workspace it validated, the after-census has nothing to
    run in, a project that adopted the census gets a permanent "could not measure" — and read as
    no news, that merges everything."""
    from openfactory.orchestrator.machine import JobRunner

    ws = object()
    holder = type("_H", (), {
        "manifest": Manifest(test_inventory="pytest --collect-only -q"),
        "sandbox": _Recorder("t::a\n"),
        "_set_state": lambda self, ticket, state: None,
        "_run_validations": lambda self, ws, touched, ticket, **_: [],
    })()

    JobRunner._validate(holder, ws, None)

    assert holder._census_ws is ws


# ── the baseline is a property of the TREE, not of where the call sits ──────────────────────────


def test_a_resumed_attempt_takes_no_baseline_rather_than_a_wrong_one():
    """THE SECOND BLOCKING FINDING ON #19. "The last moment the tree is still the base commit" was
    true of `_run_setup`'s POSITION and not of the tree: a resume prepares with
    `checkout_existing=True`, so a baseline taken there absorbs work the agent has already done —
    `after >= before` for the rest of the job, and pausing and resuming is all it takes to defeat
    the gate. No baseline is better than a wrong one, because `before is not None` is what switches
    the gate on: this is a coverage gap somebody can see, not a gate that silently cannot fire."""
    from openfactory.orchestrator.machine import JobRunner

    sandbox = _Recorder()
    holder = type("_H", (), {
        "manifest": Manifest(setup=["pip install -e ."],
                             test_inventory="pytest --collect-only -q"),
        "sandbox": sandbox,
        "_emit": lambda self, ticket, kind, text: None,
        "_take_census": JobRunner._take_census,
    })()

    JobRunner._run_setup(holder, None, None, at_base=False)

    assert not hasattr(holder, "_census_before")
    assert sandbox.calls == ["pip install -e ."], (
        "a census on a tree that is not the base commit is a baseline that absorbs the damage")


def test_the_main_path_says_which_tree_it_is_on_and_the_ci_repair_path_says_the_other():
    """The two `_run_setup` call sites disagree about the tree, so the fact has to be passed rather
    than assumed. `at_base=True` at either of them re-opens the defect above."""
    from openfactory.orchestrator import machine as machine_mod

    src = _source_of(machine_mod)

    assert "self._run_setup(ticket, ws, at_base=not resuming)" in src, (
        "the main path must pass `at_base=not resuming` — a resume is not the base commit")
    assert "self._run_setup(ticket, ws)\n" in src, (
        "the CI-repair path checks out an open pull request's branch and must take no baseline")


# ── the CI-repair path, which never reaches `should_auto_merge` ─────────────────────────────────


def test_the_ci_repair_pass_censuses_itself_because_the_merge_gate_never_runs_there():
    """The repair agent is told *"the CI for this PR is FAILING. Make it pass"*, and the cheapest
    way to make a failing test stop failing is to delete it or rename it out of collection. It
    emits no suppression token, `_validate` is not called on this path, `should_auto_merge` is not
    called on this path, and the pass pushes to a pull request with auto-merge ALREADY ARMED."""
    from openfactory.orchestrator import machine as machine_mod

    src = _source_of(machine_mod)
    start = src.index("            repair_census_before = self._take_census(ws)")
    block = src[start:src.index("# THE PASS REVIEWS WHAT IT PRODUCED", start)]

    assert "repair_census_after" in block, "the pass never re-censuses what it produced"
    assert "lost_tests" in block and "or lost_tests:" in block, (
        "the disarm branch does not read the census, so a repair that deleted the failing tests "
        "lands on an armed auto-merge")
    assert "disable_auto_merge" in block


def test_the_census_reaches_the_pull_request_body_where_the_person_decides():
    """The third gate in this stack that refused silently. The vanished identifiers are the signal
    that survives a count the noise moved the wrong way, and both readers threw them away."""
    from openfactory.orchestrator.machine import JobRunner

    holder = type("_H", (), {
        "manifest": Manifest(),
        "_stripped_workflows": set(),
        "_knowledge_state": lambda self: "unavailable",
    })()
    result = _result(test_census_before=120, test_census_after=119,
                     test_census_gone=["tests/test_orders.py::test_refund"],
                     test_census_gone_count=1)

    body = JobRunner._pr_body(holder, _TICKET, result)

    assert "tests/test_orders.py::test_refund" in body
    assert "120" in body and "119" in body


def _source_of(mod) -> str:
    from pathlib import Path

    return Path(mod.__file__).read_text(encoding="utf-8")
