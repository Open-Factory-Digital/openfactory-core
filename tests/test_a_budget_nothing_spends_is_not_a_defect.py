"""An unreadable API budget is a finding about the POLLER — and only where the poller runs.

THE STRANGER'S SCREEN (2026-08-24). Somebody clones the public repository, follows
docs/ONBOARDING.md, registers a project at §2 and runs the diagnostic that section ends with, on
a machine with no tracker credential and no `gh`. He is told:

    NOT ready — fix the FAIL lines above

with an `api_budget` line he cannot act on at that point. That is precisely the confusion the
EXPECTED verdict was built to end in 2026-08-13, and it came back because a new check joined the
report carrying no attribution — the same accident `post_merge` produced in 2026-08-16.

WHAT THE FINDING ACTUALLY DESCRIBES, and it decides the answer: a safety net around the poller's
board scan. `runtime/temporal/activities.py::scan_todo` takes the box gate's verdict FIRST and
returns before it reads the board while pickup is held ("the original gate never spent board
quota on a project that cannot run anything"), and ONBOARDING §2 says the same thing in the
operator's words — *"registering a project does not release it to pick up work … §5 is what
changes that"*. So on a project that has not been released, nothing is scanning, nothing is
spending the quota, and there is no safety net to be missing. Once §5 releases pickup the poller
IS reading that board, and the same red line is a real finding.

The three answers the tracker port carries stay three on this screen: a `Budget` is a number, an
unreadable one is a failure whose severity depends on the step reached, and `NOT_REPORTED` — a
vendor that publishes no quota at all, like Jira or Azure Boards — is never a failure anywhere.
"""

from __future__ import annotations

import pytest

from openfactory import doctor
from openfactory.adapters.tracker.base import NOT_REPORTED, Budget, BudgetUnreadable
from openfactory.contracts.project import Project, ProviderRef
from tests.pinned_probes import a_fully_pinned_probe_set

#: What the port raises on a machine with no `gh` — the vendor's own sentence, verbatim shape.
UNREADABLE = BudgetUnreadable(
    "could not read the GitHub rate limit ([Errno 2] No such file or directory: 'gh')")

#: The gate's own sentence at §2, where nothing has been proven BY CONSTRUCTION.
NEVER_PROVEN = "the box has never been proven — run `openfactory box prove demo`"


def _registered(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(app, ["project", "add", "demo", str(tmp_path)]).exit_code == 0
    return CliRunner()


def _budget_finding(**over):
    report = doctor.diagnose(a_fully_pinned_probe_set(**over))
    return {f.check: f for f in report.findings}["api_budget"]


# ── the verdict a stranger reads at §2 ──────────────────────────────────────────────────────────

def test_at_registration_an_unreadable_budget_does_not_say_the_project_is_broken(tmp_path,
                                                                                 monkeypatch):
    """The §2 world, entire: the manifest §3 has not written yet, the box §5 has not proven yet,
    and a machine that cannot read the tracker's quota. Every red line is answered by a step
    ahead, so the verdict must say so — and must still PRINT the budget line, because it becomes
    a real finding the moment pickup is released."""
    from openfactory.cli import app

    runner = _registered(tmp_path, monkeypatch)
    monkeypatch.setattr(doctor, "probes_for", lambda _p: a_fully_pinned_probe_set(
        manifest=lambda: (_ for _ in ()).throw(FileNotFoundError("no manifest here")),
        box_gate=lambda: NEVER_PROVEN,
        api_budget=lambda: UNREADABLE))

    result = runner.invoke(app, ["doctor", "demo"])

    assert result.exit_code == 1, "nothing can run yet — the verdict is still NOT ready"
    assert "EXPECTED" in result.output, (
        "a stranger at §2 is told his project is broken over a quota nothing is spending yet")
    assert "fix the FAIL lines above" not in result.output
    assert "api_budget" in result.output, (
        "the line was hidden rather than attributed — it is true, and it becomes a finding at §5")
    assert "box prove demo" in result.output, "the step that answers it is not named"


def test_once_pickup_is_RELEASED_the_same_budget_is_a_real_failure(tmp_path, monkeypatch):
    """THE POSITIVE TWIN, and the reason this is not simply an excuse: on a project whose box is
    proven the poller reads that board every tick, so an unreadable quota is a safety net that is
    off, and the harsher sentence is the correct one."""
    from openfactory.cli import app

    runner = _registered(tmp_path, monkeypatch)
    monkeypatch.setattr(doctor, "probes_for", lambda _p: a_fully_pinned_probe_set(
        api_budget=lambda: UNREADABLE))

    result = runner.invoke(app, ["doctor", "demo"])

    assert result.exit_code == 1
    assert "fix the FAIL lines above" in result.output, (
        "an operational project's missing safety net was excused as a step not reached")
    assert "EXPECTED" not in result.output
    assert "the poller keeps scanning without that safety net" in result.output


def test_a_project_with_no_gate_probe_is_never_excused(tmp_path, monkeypatch):
    """ABSENCE MUST NOT READ AS COMPLIANCE. A probe set carrying no `box_gate` cannot show that
    pickup is held; unknown is not "nothing is exposed", and the louder answer is the safe one.

    ASSERTED ON THE FINDING FIRST, and that is not belt-and-braces. The screen alone kept saying
    the right sentence with the rule inverted — `cli.py` only softens the verdict when `manifest`
    or `box_proof` is among the red lines, and with no gate probe neither is, so the guard was
    passing on a condition it was not measuring (mutation, 2026-08-24)."""
    from openfactory.cli import app

    unattributed = _budget_finding(box_gate=None, api_budget=lambda: UNREADABLE)

    assert unattributed.not_yet == "", (
        "with no gate probe the doctor claimed to know that pickup is held — it cannot, and "
        "assuming it excuses a safety net that may well be off right now")

    runner = _registered(tmp_path, monkeypatch)
    monkeypatch.setattr(doctor, "probes_for", lambda _p: a_fully_pinned_probe_set(
        box_gate=None, api_budget=lambda: UNREADABLE))

    result = runner.invoke(app, ["doctor", "demo"])

    assert "fix the FAIL lines above" in result.output, result.output
    assert "EXPECTED" not in result.output


def test_a_held_gate_is_not_enough_when_ANOTHER_repo_of_the_project_is_proven():
    """C-18'S HALF, and without it the excuse is a false sentence on exactly the deployments
    multi-repo support exists for: `scan_todo` holds the default repo's cards on its gate and
    STILL reads the board when some other repo of the project is proven, because a proven
    foreign repo does not wait on the default's paperwork. The quota is being spent; the missing
    safety net is real."""
    still_scanning = _budget_finding(box_gate=lambda: NEVER_PROVEN,
                                     foreign_proofs=lambda: True,
                                     api_budget=lambda: UNREADABLE)
    not_scanning = _budget_finding(box_gate=lambda: NEVER_PROVEN,
                                   foreign_proofs=lambda: False,
                                   api_budget=lambda: UNREADABLE)

    assert still_scanning.not_yet == "", (
        "a board the poller reads every tick was called 'nothing is spending it yet'")
    assert "the poller keeps scanning" in still_scanning.message
    assert not_scanning.not_yet == "box_proof", (
        "the fixture no longer reaches the state it contrasts with")


def test_a_probe_set_that_cannot_answer_the_second_half_is_never_excused():
    """Absence again, one member further in: an older `Probes` carrying no `foreign_proofs`
    cannot show that the board goes unread, and unknown is not safe."""
    unknown = _budget_finding(box_gate=lambda: NEVER_PROVEN, foreign_proofs=None,
                              api_budget=lambda: UNREADABLE)

    assert unknown.not_yet == "", (
        "the doctor claimed the board is unread on a probe set that cannot say")


def test_the_default_repos_own_proof_is_not_a_FOREIGN_one(tmp_path, monkeypatch):
    """The naming this rests on: a foreign repo is recorded as `<project>--<owner>--<repo>.json`
    and the default repo keeps `<project>.json`. Counting the default's own proof would make
    every ordinary project look like a multi-repo one — and would silently delete the excuse
    the §2 report depends on."""
    from openfactory import box_prove
    from openfactory.runtime.card_repo import _checkout_key

    monkeypatch.setattr(box_prove, "PROOF_DIR", tmp_path)
    project = Project(name="dsk", repo_path="/tmp/dsk",
                      tracker=ProviderRef(kind="github", repo="acme/api"),
                      forge=ProviderRef(kind="github", repo="acme/api"))

    (tmp_path / "dsk.json").write_text("{}")
    assert box_prove.foreign_proofs_recorded("dsk") is False, (
        "the default repo's own proof was counted as a foreign one")

    (tmp_path / f"{_checkout_key(project, 'acme/web')}.json").write_text("{}")
    assert box_prove.foreign_proofs_recorded("dsk") is True, (
        "a proof recorded for another repo of the project was not seen")


def test_the_poller_and_the_doctor_ask_ONE_function(tmp_path, monkeypatch):
    """Reachability for both callers, because the value of asking the same question is entirely
    in both of them asking it. The poller's side is read from its own AST — a text search would
    match the comment that explains the rule, which this repository has paid for before."""
    import ast
    import inspect
    import textwrap

    from openfactory.runtime.temporal import activities

    tree = ast.parse(textwrap.dedent(inspect.getsource(activities.scan_todo)))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}

    assert "foreign_proofs_recorded" in called, (
        "the poller spells the foreign-proof condition itself again — one condition in two "
        "places is how the doctor and the poller start disagreeing")
    assert "glob" not in called, "the poller kept a second copy of the proof-name shape"

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    project = Project(name="demo", repo_path=str(tmp_path),
                      tracker=ProviderRef(kind="github", repo="acme/demo"))
    asked = []
    monkeypatch.setattr("openfactory.box_prove.foreign_proofs_recorded",
                        lambda name, **kw: asked.append(name) or True)

    assert doctor.probes_for(project).foreign_proofs() is True
    assert asked == ["demo"], (
        "doctor's own probes do not reach `box_prove.foreign_proofs_recorded`")


# ── the three answers stay three ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("held", [True, False], ids=["pickup held", "pickup released"])
def test_a_vendor_that_publishes_no_budget_is_a_failure_NOWHERE(held):
    """`NOT_REPORTED` is a declaration, not a failure: Jira Cloud and Azure Boards expose no
    endpoint that says what a token has left, so a whole deployment would read as broken for
    being itself. It passes on both sides of the gate, and for the same reason."""
    finding = _budget_finding(api_budget=lambda: NOT_REPORTED,
                              box_gate=(lambda: NEVER_PROVEN) if held else (lambda: None))

    assert finding.ok, finding.message
    assert "not_reported" not in finding.message, "the sentinel's name reached the operator"
    assert finding.not_yet == "", "a passing line was attributed to a step nobody has to take"


def test_the_operator_can_tell_the_three_answers_apart():
    """One value cannot carry three meanings — the lesson the port learned when `None` meant both
    "this vendor has none" and "the read failed", and the doctor rendered both as ok. Read as a
    person reads it: three different sentences, and the two failures differ in the fact that
    decides what to do about them."""
    number = _budget_finding(api_budget=lambda: Budget(resource="graphql", remaining=4800,
                                                       limit=5000, floor=200))
    absent = _budget_finding(api_budget=lambda: NOT_REPORTED)
    not_yet = _budget_finding(api_budget=lambda: UNREADABLE, box_gate=lambda: NEVER_PROVEN)
    exposed = _budget_finding(api_budget=lambda: UNREADABLE)

    said = [f.message for f in (number, absent, not_yet, exposed)]
    assert len(set(said)) == 4, f"two of the four answers read the same on the screen: {said}"
    assert (number.ok, absent.ok, not_yet.ok, exposed.ok) == (True, True, False, False)
    assert (not_yet.not_yet, exposed.not_yet) == ("box_proof", ""), (
        "the two failures carry the same attribution, so the verdict cannot tell them apart")


def test_no_remedy_asks_for_something_that_cannot_be_done_at_that_step():
    """The remedy is the whole point of a diagnostic, and at §2 the honest one is "not yours
    yet". The operational remedy sends him to the tracker's own call; the held one must not,
    because he has no credential to make it with and no poller spending anything if he did."""
    not_yet = _budget_finding(api_budget=lambda: UNREADABLE, box_gate=lambda: NEVER_PROVEN)
    exposed = _budget_finding(api_budget=lambda: UNREADABLE)

    assert "§5" in not_yet.remedy, "the step that answers it is not named in the remedy"
    assert "run the tracker's own CLI/API call" not in not_yet.remedy, (
        "the operator is sent to make a call he has no credential for, at a point where nothing "
        "is spending the quota anyway")
    assert "run the tracker's own CLI/API call" in exposed.remedy, (
        "the operational finding stopped saying how to see what the vendor answers")


def test_the_unreadable_answer_carries_the_vendors_own_reason():
    """"Could not be read" is a symptom; "gh is not installed" is a cause, and the port already
    said it. `floor/reading.py` keeps it as `error=`; this check dropped it on the floor and then
    asked the operator to re-run by hand the call the platform had just made."""
    finding = _budget_finding(api_budget=lambda: UNREADABLE)
    silent = _budget_finding(api_budget=lambda: None)

    assert "No such file or directory: 'gh'" in finding.message, (
        f"the reason the port gave did not reach the screen: {finding.message}")
    assert not silent.ok and "(" not in silent.message.split("—")[0], (
        f"a failure with no reason to give invented one: {silent.message}")


# ── the gate is asked once, and its answer is the one the budget reads ──────────────────────────

def test_the_box_gate_is_asked_ONCE_and_the_budget_reads_that_answer():
    """TWO ANSWERS TO ONE QUESTION IS HOW THE TWO DRIFT — the lesson `_box_proof` already carries
    — and this one is also expensive: `gate_reason` resolves a checkout and asks docker for a
    digest, which the poller bounds at sixty seconds. So the gate's finding is handed to the
    budget check rather than probed a second time."""
    asked = []

    def _gate():
        asked.append(1)
        return NEVER_PROVEN

    report = doctor.diagnose(a_fully_pinned_probe_set(box_gate=_gate,
                                                      api_budget=lambda: UNREADABLE))
    findings = {f.check: f for f in report.findings}

    assert len(asked) == 1, f"the box gate was asked {len(asked)} times in one diagnosis"
    assert not findings["box_proof"].ok
    assert findings["api_budget"].not_yet == "box_proof", (
        "the budget check did not learn from the gate's own finding that pickup is held")


# ── the wiring: the real probe hands back what the port raised ──────────────────────────────────

def test_the_real_probe_hands_the_ports_refusal_back_instead_of_swallowing_it(monkeypatch,
                                                                              tmp_path):
    """Reachability, by name: the attribution above is worth nothing if `probes_for` still
    answers a bare `None` for every failure. Asked of the REAL probe, with the tracker port
    raising what it really raises."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    project = Project(name="demo", repo_path=str(tmp_path),
                      tracker=ProviderRef(kind="github", repo="acme/demo"))

    class _Tracker:
        def budget(self):
            raise UNREADABLE

    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda *a, **kw: _Tracker())
    answer = doctor.probes_for(project).api_budget()

    assert answer is UNREADABLE, (
        "the probe swallowed the port's reason, so the check can only say 'could not be read'")


def test_a_failure_that_is_not_the_ports_own_answer_invents_no_reason(monkeypatch, tmp_path):
    """The other half: a builder that raised something else — an unknown tracker kind, a bad
    registry row — is still an unreadable budget, and the doctor must not dress that up as the
    vendor's answer."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    project = Project(name="demo", repo_path=str(tmp_path),
                      tracker=ProviderRef(kind="github", repo="acme/demo"))

    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no such tracker")))
    answer = doctor.probes_for(project).api_budget()

    assert answer is None
    assert not _budget_finding(api_budget=lambda: answer).ok, "a failed read passed as compliance"


# ── and the document says the same thing ────────────────────────────────────────────────────────

def test_the_onboarding_says_this_line_is_expected_at_registration():
    """The pilot's standing rule: a finding is fixed in the product and in the document nobody
    is there to explain, never in a chat message. §2 tells the operator what NOT ready means
    there, and this line is part of that answer."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "docs" / "ONBOARDING.md").read_text()
    where = text[text.index("## 2 · Register the project"):text.index("## 3 · Your STACK")]

    assert "`api_budget` may be red here too" in where, (
        "§2 lists the red lines a stranger should expect and omits the one that sent him "
        "looking for a defect")
    assert "§5" in where and "poller" in where, (
        "the document says the line is expected without saying what makes it expected")
