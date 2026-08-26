"""A doctor test measures what it names — every other probe is pinned green, by derivation.

THE CLASS, TWICE, WITH THE SAME SHAPE. A test builds its probe set with
`dataclasses.replace(doctor.probes_for(project), **a_few)`, names the handful of members it
cares about, and leaves the rest reading the machine it happens to run on. Then a new member
joins `doctor.Probes`:

  * `agent_credential` (2026-08-21) — green on a laptop with a `.env`, red on a clean runner.
  * `api_budget` (2026-08-24) — green on a laptop where `gh` is logged in (the probe SHELLS OUT,
    so the session's credential firewall, which strips environment variables, never sees it),
    red anywhere else. Three tests red on GitHub Actions, and the export's first CI run over the
    public repository was that run.

Both times the repair proposed was to pin the new member in each affected test. This file is the
other repair: the default is inverted (`tests/pinned_probes.py`), and these guards keep it
inverted — the helper covers every field of the dataclass, its answers are green when the real
`diagnose` runs them, and no test goes back to building a probe set out of the real machine.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from openfactory import doctor
from tests.pinned_probes import GREEN_ANSWERS, a_fully_pinned_probe_set

TESTS = Path(__file__).resolve().parent


# ── the helper covers the whole probe set ───────────────────────────────────────────────────────

def test_every_member_of_the_probe_set_has_a_green_answer():
    """DERIVED FROM THE DATACLASS, not from a list somebody remembers to update — the same
    defect `cli.py` paid for with its hand-written set of check names, and the same guard shape
    `test_three_commands_one_verdict.py` already keeps over `readiness.Probes`.

    Both directions, because they fail differently: a member with no answer leaves a test
    reading the machine (the accident above), and an answer for a member that no longer exists
    is a `TypeError` waiting for whoever next calls the helper."""
    members = {f.name for f in dataclasses.fields(doctor.Probes)}
    answered = set(GREEN_ANSWERS)

    assert members - answered == set(), (
        f"doctor.Probes members with no green answer in tests/pinned_probes.py: "
        f"{sorted(members - answered)} — every test built on the helper is now measuring an "
        f"unpinned probe")
    assert answered - members == set(), (
        f"tests/pinned_probes.py answers for members doctor.Probes no longer has: "
        f"{sorted(answered - members)}")


def test_a_member_with_no_green_answer_FAILS_LOUDLY():
    """THE POSITIVE TWIN, and the whole point of the file. "Nothing is unpinned" cannot see a
    member that is MISSING from the table — absence reads as compliance — so the helper is made
    to meet one and must refuse, naming it.

    One more member is added to a COPY of the dataclass rather than to the real one: the
    guard has to hold for a probe nobody has written yet, and the only honest way to show that
    is to introduce one."""
    grown = dataclasses.make_dataclass(
        "Probes",
        [(f.name, f.type, dataclasses.field(default=f.default))
         if f.default is not dataclasses.MISSING else (f.name, f.type)
         for f in dataclasses.fields(doctor.Probes)]
        + [("quota_reset_horizon", object, dataclasses.field(default=None))],
    )

    with pytest.raises(AssertionError) as refused:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(doctor, "Probes", grown)
            a_fully_pinned_probe_set()

    assert "quota_reset_horizon" in str(refused.value), (
        f"the helper refused without naming the member that has no green answer, so the next "
        f"person has to go and find it: {refused.value}")
    assert "pinned_probes" in str(refused.value), (
        "the refusal does not say where the missing answer goes")


def test_a_member_the_caller_measures_is_not_required_to_have_one():
    """The helper is a floor, not a cage: a test unpins what it measures, and what it hands over
    is what the probe set carries."""
    unreadable = object()
    probes = a_fully_pinned_probe_set(api_budget=lambda: unreadable)

    assert probes.api_budget() is unreadable
    assert probes.docker_running() == (True, ""), "unpinning one member disturbed another"


# ── and the answers really are green ────────────────────────────────────────────────────────────

def test_the_green_answers_are_green_when_the_real_diagnose_runs_them():
    """MEASURED, NEVER CLAIMED. "Green" is not a property of the table above; it is what
    `diagnose` says about it, and the check that renders each answer is the only authority on
    whether it is one."""
    report = doctor.diagnose(a_fully_pinned_probe_set())
    red = [f"{f.check}: {f.message}" for f in report.findings if not f.ok]

    assert red == [], f"the baseline probe set is not green: {red}"
    assert report.ok


def test_every_check_the_doctor_HAS_is_reached_by_the_green_set():
    """A green report is easy to fake by not running the checks: every optional probe defaults
    to `None`, and `diagnose` runs its check only `if probes.X`, so a member
    left out of the helper makes its check vanish rather than fail. Built, tested, reached by
    nothing — the recurring defect of this codebase, and here it would be invisible."""
    checks = [f.check for f in doctor.diagnose(a_fully_pinned_probe_set()).findings]

    for optional in ("agent_credential", "ci_declared", "box_proof", "api_budget"):
        assert optional in checks, (
            f"the {optional!r} check did not run at all on the baseline probe set — its probe is "
            f"unpinned, so `diagnose` skipped it and the report is green about a question "
            f"nobody asked")
    assert len(checks) == len(set(checks)), f"a check ran twice: {checks}"


def test_the_verdict_over_the_green_set_is_READY_through_the_command(tmp_path, monkeypatch):
    """The operator's own surface, not the report object: `doctor` is a command, and "green"
    means the command says so and exits zero."""
    from typer.testing import CliRunner

    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(app, ["project", "add", "demo", str(tmp_path)]).exit_code == 0
    monkeypatch.setattr(doctor, "probes_for", lambda _project: a_fully_pinned_probe_set())

    result = CliRunner().invoke(app, ["doctor", "demo"])

    assert result.exit_code == 0, result.output
    assert "OK — 'demo' can run a ticket" in result.output
    assert "FAIL" not in result.output, result.output


def test_nothing_in_the_green_set_reads_this_machine(monkeypatch):
    """THE PROPERTY THE WHOLE FILE EXISTS FOR, asserted rather than described. Every door the
    real probes use to reach a machine — a subprocess, a PATH lookup — is nailed shut, and the
    baseline stays green. Nailed shut inside `doctor`'s own module namespace, which is where
    `probes_for` reaches them from."""
    def _no_subprocess(*a, **kw):
        raise AssertionError(f"a green probe shelled out: {a[:1]}")

    def _no_path_lookup(*a, **kw):
        raise AssertionError(f"a green probe looked something up on PATH: {a[:1]}")

    monkeypatch.setattr(doctor.subprocess, "run", _no_subprocess)
    monkeypatch.setattr(doctor.shutil, "which", _no_path_lookup)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(doctor, "probes_for", lambda _p: (_ for _ in ()).throw(
        AssertionError("the green set was built out of the REAL probes")))

    assert doctor.diagnose(a_fully_pinned_probe_set()).ok


# ── and no test goes back to the machine ────────────────────────────────────────────────────────

def _live_probe_set_replacements(source: str) -> list[int]:
    """Lines where a `dataclasses.replace(...)` rebuilds a set the REAL `probes_for` produced.

    THROUGH THE AST, and the alias with it. Two spellings occur — `replace(doc.probes_for(p), …)`
    and `real = doc.probes_for` followed by `replace(real(p), …)` — and a text search for the
    first would report the nine call sites as one. It would also trip on this docstring, which is
    the defect this repository has now paid for in three separate guards."""
    tree = ast.parse(source)
    aliases = {"probes_for"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        named = (value.attr if isinstance(value, ast.Attribute)
                 else value.id if isinstance(value, ast.Name) else "")
        if named in aliases:
            aliases.update(t.id for t in node.targets if isinstance(t, ast.Name))
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        called = node.func.attr if isinstance(node.func, ast.Attribute) else \
            node.func.id if isinstance(node.func, ast.Name) else ""
        if called != "replace":
            continue
        first = node.args[0]
        if not isinstance(first, ast.Call):
            continue
        source_of = first.func.attr if isinstance(first.func, ast.Attribute) else \
            first.func.id if isinstance(first.func, ast.Name) else ""
        if source_of in aliases:
            hits.append(node.lineno)
    return hits


def test_the_sweep_can_see_both_spellings_of_the_defect():
    """The positive twin for the sweep below — a guard that says "nothing in this directory does
    X" is worth exactly what its detector is worth, and five probes in one day have passed here
    for the wrong reason."""
    direct = _live_probe_set_replacements(
        "import dataclasses\nfrom openfactory import doctor as doc\n"
        "p = dataclasses.replace(doc.probes_for(project), docker_running=lambda: (True, ''))\n")
    aliased = _live_probe_set_replacements(
        "import dataclasses\nfrom openfactory import doctor as doc\n"
        "real = doc.probes_for\n"
        "p = dataclasses.replace(real(project), docker_running=lambda: (True, ''))\n")
    innocent = _live_probe_set_replacements(
        "import dataclasses\nfrom tests.pinned_probes import a_fully_pinned_probe_set\n"
        "p = dataclasses.replace(a_fully_pinned_probe_set(), docker_running=lambda: (True, ''))\n")

    assert direct == [3], direct
    assert aliased == [4], aliased
    assert innocent == [], "the sweep refuses a probe set that never touched the machine"


def test_no_test_builds_its_probe_set_out_of_the_real_machine():
    """Nine call sites had this shape and three were red on CI; the other six were green only by
    luck of assertion wording — an extra FAIL line reinforced the sentence they asserted. The
    class is closed here rather than case by case, because the member that breaks the next test
    is always the one nobody had thought of."""
    offenders = {}
    for path in sorted(TESTS.glob("test_*.py")):
        found = _live_probe_set_replacements(path.read_text())
        if found:
            offenders[path.name] = found

    assert offenders == {}, (
        f"a test pins a few members of a live `doctor.probes_for` set and lets the rest answer "
        f"off this machine: {offenders}. Build it with "
        f"`tests.pinned_probes.a_fully_pinned_probe_set(**what_this_test_measures)` instead — "
        f"the wiring of the real probes is a separate behaviour with its own guards "
        f"(`test_the_real_probes_actually_wire_the_gate`).")
