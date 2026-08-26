"""A ticket is not picked up until the box is proven — and the gate SPEAKS (ADR-0037 D5).

The product owner asked whether a box should be pre-configured per client before pulling from
TO-DO. The
answer is stronger: **configuration is a declaration, a proof is a fact**, and a fact about a world
that moves. So the poller asks, before taking anything: is there a proof, and does it still
describe the box this job would get?

WHY IT EXPIRES RATHER THAN BEING TICKED. Three things move underneath a proof — the client
republishes their image, we pin a new harness, they edit `setup:` or `validate:`. A checkbox ages
in silence; this one notices. The comparison is exactly the three fields `box prove` records.

AND THE GATE IS NEVER MUTE, which is ADR-0038 D2 applied to the first new gate created since it:
*a wait is a question, never a state*. A poller that stops picking up and only logs is the "In
review with a link" failure wearing different clothes — the card sits in TO-DO looking merely
unstarted, which is indistinguishable from a quiet factory.

ONCE, THOUGH. The poller ticks every few minutes; an unproven box that announced itself on every
tick would train somebody to filter the alarm, which is the same cost a false alarm has anywhere
else in this platform. It announces when the REASON changes, and goes quiet again once proven.

FOLDED INTO `scan_todo` DELIBERATELY. That activity already loads the project and already returns
`[]` for "no board configured", with a warning saying empty is a configuration rather than an empty
queue — the same shape. Putting the gate there means the workflow BODY does not change, so no
`workflow.patched()` and no replay risk for jobs in flight (TMPRL1100).

AND IT APPLIES ONLY WHERE THERE IS SOMETHING TO PROVE. A `worktree` box has no image and no
toolbox; a `fargate` job runs inside a task whose image is baked. Gating either would block a
deployment on a proof it cannot take — so both live deployments are untouched by this.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from openfactory import namespace
from openfactory.box_prove import Proof, gate_reason, save


@pytest.fixture(autouse=True)
def _proofs(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFACTORY_PROOFS", str(tmp_path / "proofs"))
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "container")
    import openfactory.box_prove as bp

    monkeypatch.setattr(bp, "PROOF_DIR", tmp_path / "proofs")
    return tmp_path / "proofs"


@pytest.fixture
def project(tmp_path):
    from openfactory.contracts.project import Project

    repo = tmp_path / "repo"
    (repo / namespace.DIR).mkdir(parents=True)
    (repo / namespace.MANIFEST).write_text("setup: ['true']\nvalidate:\n  test: 'true'\n")
    return Project(name="acme", repo_path=str(repo))


def _a_valid_proof(project, monkeypatch, **overrides):
    """Record a proof that matches the world, so the gate opens."""
    import openfactory.box_prove as bp
    from openfactory.loader import load_manifest
    from openfactory.orchestrator.validation import gate_commands
    from openfactory.runtime import toolbox as tb

    monkeypatch.setattr(bp, "_current_digest", lambda *_a, **_k: "sha256:abc")
    monkeypatch.setattr(tb, "read_stamp", lambda *_a, **_k: {"variant": "linux-arm64-glibc",
                                                            "harnesses": ["claude"]})
    m = load_manifest(project)
    fields = dict(project="acme", image="img", ok=True, digest="sha256:abc",
                  toolbox="linux-arm64-glibc",
                  # THROUGH `gate_commands`, exactly as `gate_reason` and `prove` do
                  # (box_prove.py:754). `dict(m.validation)` was a shortcut that only worked while
                  # every gate in this fixture was a bare string: the documented advisory form
                  # (`security: {command: …, advisory: true}`) parses to a `Gate`, and a `Gate` is
                  # not JSON-serialisable — so this helper raised TypeError the moment the manifest
                  # carried one, which it now always does (the deployment's inherited floor gate).
                  # The hash the gate compares against has always been the normalised one.
                  commands_hash=bp._hash_commands(list(m.setup), gate_commands(m.validation),
                                                  bp.component_gates(m)),
                  at="2026-08-03T00:00:00+00:00")
    fields.update(overrides)
    save(Proof(**fields))


# ── the gate ────────────────────────────────────────────────────────────────────────────────────

def test_a_valid_proof_opens_the_gate(project, monkeypatch):
    _a_valid_proof(project, monkeypatch)

    assert gate_reason(project, sandbox="container") is None


def test_no_proof_at_all_closes_it(project):
    reason = gate_reason(project, sandbox="container")

    assert reason and "box prove acme" in reason, reason


def test_a_failed_proof_closes_it(project, monkeypatch):
    _a_valid_proof(project, monkeypatch, ok=False)

    assert gate_reason(project, sandbox="container")


@pytest.mark.parametrize("moved,expect", [
    ("digest", "image"),
    ("toolbox", "toolbox"),
    ("commands_hash", "setup"),
])
def test_the_reason_NAMES_what_moved(project, monkeypatch, moved, expect):
    """"expired" with no reason is a wall. Somebody has to know whether to re-prove, rebuild the
    worker, or look at what they just edited."""
    _a_valid_proof(project, monkeypatch, **{moved: "something-else"})

    reason = gate_reason(project, sandbox="container")

    assert reason and expect in reason.lower(), reason


def test_the_reason_carries_the_command_to_run(project):
    """ADR-0038 D2: a wait is a question with EXECUTABLE options, not a state."""
    assert "openfactory box prove acme" in (gate_reason(project, sandbox="container") or "")


# ── only where there is something to prove ──────────────────────────────────────────────────────

@pytest.mark.parametrize("box", ["worktree", "fargate"])
def test_a_box_with_nothing_to_prove_is_not_gated(project, box):
    """A worktree has no image and no toolbox; a fargate job's image is baked into the task
    definition. Gating either blocks a deployment on a proof it cannot take — and both live
    deployments are fargate, so this is what keeps them untouched."""
    assert gate_reason(project, sandbox=box) is None


def test_an_unknown_box_does_not_gate(project):
    """The box registry owns that error, with its list of what IS supported. Turning a typo into a
    silent pickup halt would bury it."""
    assert gate_reason(project, sandbox="contianer") is None


# ── the poller respects it, and says so once ────────────────────────────────────────────────────

def test_scan_todo_returns_nothing_when_the_box_is_unproven(project, monkeypatch):
    """MY FIRST VERSION OF THIS PASSED FOR THE WRONG REASON. It patched `acts.build_board`, which
    `scan_todo` imports INSIDE the function — so the patch bound nothing, the real builder ran,
    found no board configured on the fixture project, and returned `[]`. Green, and proving
    nothing about the gate.

    So the project now HAS a board, and the board builder is patched where the function actually
    looks it up. If the gate does not short-circuit, this raises."""
    import asyncio

    import openfactory.adapters.board as board_pkg
    import openfactory.runtime.temporal.activities as acts
    from openfactory.contracts.project import ProviderRef
    from openfactory.runtime.temporal.io import ScanInput

    project.tracker = ProviderRef(kind="github", repo="o/n",
                                  options={"board_owner": "o", "board_number": "1"})
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: project)

    def _never(*_a, **_k):
        raise AssertionError("the board was polled for a project whose box is unproven")

    monkeypatch.setattr(board_pkg, "build_board", _never)

    issues = asyncio.run(acts.scan_todo(ScanInput(
        project="acme", board_owner="o", board_number="1", pickup_status="TO-DO")))

    assert issues == []


def test_scan_todo_polls_the_board_once_the_box_IS_proven(project, monkeypatch):
    """The other half — a gate that always closes is not a gate, it is an outage."""
    import asyncio

    import openfactory.adapters.board as board_pkg
    import openfactory.runtime.temporal.activities as acts
    from openfactory.contracts.project import ProviderRef
    from openfactory.runtime.temporal.io import ScanInput

    _a_valid_proof(project, monkeypatch)
    project.tracker = ProviderRef(kind="github", repo="o/n",
                                  options={"board_owner": "o", "board_number": "1"})
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: project)
    monkeypatch.setattr(board_pkg, "build_board",
                        lambda *_a, **_k: type("_B", (), {"items_in_status": lambda s, x: [7]})())
    # the closed-issue guard reads each candidate through the tracker; an OPEN one passes
    monkeypatch.setattr(acts, "_tracker_for",
                        lambda p: type("_T", (), {"get_ticket": lambda s, r: type(
                            "_Tk", (), {"state": "open"})()})())

    issues = asyncio.run(acts.scan_todo(ScanInput(
        project="acme", board_owner="o", board_number="1", pickup_status="TO-DO")))

    assert issues == ["7"]


def test_a_CLOSED_issue_in_the_pickup_column_is_never_re_run(project, monkeypatch, caplog):
    """FOUND LIVE, 2026-08-04: fx-py-simple#1 merged, its card stayed in TO-DO (that deployment's
    board move had failed), and the next tick RE-RAN the delivered ticket — a full agent pass
    spent to discover there was nothing to do, ending in "no commits between main and sdlc/1",
    parked, holding the single-slot floor. The queue is the money gate; a closed issue is a stale
    card, not work."""
    import asyncio

    import openfactory.adapters.board as board_pkg
    import openfactory.runtime.temporal.activities as acts
    from openfactory.contracts.project import ProviderRef
    from openfactory.runtime.temporal.io import ScanInput

    _a_valid_proof(project, monkeypatch)
    project.tracker = ProviderRef(kind="github", repo="o/n",
                                  options={"board_owner": "o", "board_number": "1"})
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: project)
    healed: list[tuple] = []

    class _Board:
        def items_in_status(self, _s):
            return ["1", "2"]

        def set_status(self, *, issue, issue_url, state, needs_person=None):
            # set_STATUS, not a column literal: on a renamed board (C-14) the healing must speak
            # the same map every other move speaks
            healed.append((issue, state.value))
            return True

    monkeypatch.setattr(board_pkg, "build_board", lambda *_a, **_k: _Board())
    states = {"1": "closed", "2": "open"}
    monkeypatch.setattr(acts, "_tracker_for",
                        lambda p: type("_T", (), {"get_ticket": lambda s, r: type(
                            "_Tk", (), {"state": states[r]})()})())

    with caplog.at_level("WARNING"):
        issues = asyncio.run(acts.scan_todo(ScanInput(
            project="acme", board_owner="o", board_number="1", pickup_status="TO-DO")))

    assert issues == ["2"], "the delivered ticket was queued for a re-run"
    assert healed == [("1", "done")], "the stale card was left to re-trigger the skip for ever"
    assert "OPENFACTORY_STALE_PICKUP_CARD" in caplog.text


def test_an_UNREADABLE_ticket_is_picked_up_rather_than_silently_dropped(project, monkeypatch,
                                                                        caplog):
    """Fail OPEN: a tracker hiccup must not hold the whole queue hostage — the job itself will
    find out, and a wrongly-skipped ticket is invisible while a wrongly-run one is a log line."""
    import asyncio

    import openfactory.adapters.board as board_pkg
    import openfactory.runtime.temporal.activities as acts
    from openfactory.contracts.project import ProviderRef
    from openfactory.runtime.temporal.io import ScanInput

    _a_valid_proof(project, monkeypatch)
    project.tracker = ProviderRef(kind="github", repo="o/n",
                                  options={"board_owner": "o", "board_number": "1"})
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: project)
    monkeypatch.setattr(board_pkg, "build_board",
                        lambda *_a, **_k: type("_B", (), {"items_in_status":
                                                          lambda s, x: ["9"]})())

    class _T:
        def get_ticket(self, r):
            raise RuntimeError("throttled")

    monkeypatch.setattr(acts, "_tracker_for", lambda p: _T())

    with caplog.at_level("WARNING"):
        issues = asyncio.run(acts.scan_todo(ScanInput(
            project="acme", board_owner="o", board_number="1", pickup_status="TO-DO")))

    assert issues == ["9"]
    assert "picking it up anyway" in caplog.text


def test_it_announces_once_per_reason(project, monkeypatch, caplog):
    """The poller ticks every few minutes. An alarm on every tick is an alarm somebody filters."""
    import openfactory.box_prove as bp

    with caplog.at_level("WARNING"):
        first = bp.announce_gate("acme", "the box is not proven — run `sdlc box prove acme`")
        second = bp.announce_gate("acme", "the box is not proven — run `sdlc box prove acme`")

    assert first is True and second is False
    assert sum("not proven" in r.getMessage() for r in caplog.records) == 1


def test_a_different_reason_speaks_again(project, monkeypatch):
    import openfactory.box_prove as bp

    assert bp.announce_gate("acme", "no proof") is True
    assert bp.announce_gate("acme", "the toolbox changed") is True


def test_being_proven_again_clears_the_announcement(project, monkeypatch):
    """So the NEXT time it breaks, it speaks — rather than staying quiet because it once said
    something similar."""
    import openfactory.box_prove as bp

    bp.announce_gate("acme", "no proof")
    bp.clear_gate_announcement("acme")

    assert bp.announce_gate("acme", "no proof") is True


# ── the half that was never reached ─────────────────────────────────────────────────────────────
#
# THE THREE TESTS ABOVE ARE ALL TRUE AND ALL BLIND. They assert `announce_gate`'s RETURN VALUE and
# its log line — and the whole point of this function is that it also pushes to a channel, which
# it did by calling `.send(...)` on a `Notifier` whose Protocol has exactly one member, `notify`
# (adapters/notify/base.py:17). Every call raised AttributeError into the catch-all and logged at
# DEBUG. So the commit that shipped this gate claimed "the gate speaks" while the channel half had
# never once executed, in either deployment.
#
# Asserting the return bool is asserting the CHEAP half. These assert the expensive one.

class _RecordingNotifier:
    """Exactly the real Protocol's surface — `notify`, keyword-only, and NO `send`.

    Deliberately does not inherit from anything: a stub with a permissive `__getattr__`, or one
    that grew a `send` to match the caller, would have passed against the broken code and is how a
    test double launders a defect into a green suite."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def notify(self, *, message: str, level: str = "info", about: str = "") -> str | None:
        self.sent.append({"message": message, "level": level, "about": about})
        return "ts-1"


def test_the_gate_actually_reaches_a_channel(project, monkeypatch):
    """The positive twin the original three lacked. A gate that logs and cannot speak is the
    silent-wait failure ADR-0038 D2 exists to make impossible."""
    import openfactory.box_prove as bp
    import openfactory.factory as factory
    from openfactory.registry import ProjectRegistry

    notifier = _RecordingNotifier()
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: project)
    monkeypatch.setattr(factory, "notifier_for_project", lambda p: notifier)

    spoke = bp.announce_gate("acme", "the box is not proven — run `sdlc box prove acme`")

    assert spoke is True
    assert len(notifier.sent) == 1, "the gate held pickup and told no channel"
    said = notifier.sent[0]
    assert "acme" in said["message"] and "not proven" in said["message"]
    assert said["level"] == "warning"  # a held queue is not an FYI


def test_the_channel_stays_quiet_on_the_repeat_too(project, monkeypatch):
    """The once-per-reason rule has to govern the CHANNEL, not just the return value — a channel
    that repeats every tick is the alarm somebody mutes."""
    import openfactory.box_prove as bp
    import openfactory.factory as factory
    from openfactory.registry import ProjectRegistry

    notifier = _RecordingNotifier()
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: project)
    monkeypatch.setattr(factory, "notifier_for_project", lambda p: notifier)

    bp.announce_gate("acme", "no proof")
    bp.announce_gate("acme", "no proof")

    assert len(notifier.sent) == 1


def test_a_channel_that_raises_never_holds_the_gate(project, monkeypatch, caplog):
    """A channel is an ADD-ON (ADR-0038): its failure must not stop the gate recording itself. But
    it must be VISIBLE — DEBUG is exactly what hid a method that did not exist."""
    import openfactory.box_prove as bp
    import openfactory.factory as factory
    from openfactory.registry import ProjectRegistry

    def _boom(_p):
        raise RuntimeError("slack is down")

    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: project)
    monkeypatch.setattr(factory, "notifier_for_project", _boom)

    with caplog.at_level("WARNING"):
        spoke = bp.announce_gate("acme", "no proof")

    assert spoke is True  # the gate still announced itself in the log and recorded the marker
    assert any("slack is down" in r.getMessage() for r in caplog.records), (
        "a channel push that failed was invisible at WARNING")


def test_an_unreadable_toolbox_stamp_is_not_a_CHANGED_toolbox(project, monkeypatch, tmp_path):
    """A surface that cannot see the toolbox must not announce that it moved.

    The PANEL runs with no toolbox volume — it starts no boxes, so it has no reason to carry
    one — and read the empty stamp as `none`. It then told the operator, in the banner across
    the top of his floor: *"podbeam is held — the harness toolbox changed (linux-arm64-glibc →
    none) — run `openfactory box prove podbeam`"*, while the WORKER, the process that actually
    picks cards up, read the stamp correctly and would have held nothing (2026-08-14).

    Three states, two shapes, again: unknown is not changed. Everything the process CAN measure
    still gates — only the question it cannot ask goes unanswered."""
    from openfactory import box_prove

    _a_valid_proof(project, monkeypatch)
    monkeypatch.setattr("openfactory.runtime.toolbox.read_stamp", dict)  # {} — no toolbox here

    held = box_prove.gate_reason(project, sandbox="container")

    assert held is None, f"a process that cannot read the toolbox held the floor: {held}"


def test_a_toolbox_that_REALLY_changed_still_holds(project, monkeypatch):
    """The positive twin: the check that pays for the feature must survive the fix."""
    from openfactory import box_prove

    _a_valid_proof(project, monkeypatch)
    monkeypatch.setattr("openfactory.runtime.toolbox.read_stamp",
                        lambda: {"variant": "linux-amd64-musl"})

    held = box_prove.gate_reason(project, sandbox="container")

    assert held and "toolbox changed" in held, held
    assert "musl" in held, "the sentence does not say what it changed TO"


# ── the freshness check keeps the loader's sentence ────────────────────────────────────────────

def test_a_repository_on_the_retired_name_holds_the_gate_WITH_the_rename(project, monkeypatch):
    """The freshness check re-reads the manifest to hash its commands, and its missing-manifest
    arm REWRITES the cause: "not on the base branch yet — the box is proven, and pickup starts
    when the pull request declaring it merges". For a repository whose manifest sits under the
    directory's former name that is a false cause — the file IS on the base branch — and the
    sentence saying what to rename was the one thing dropped (review, 2026-08-25). The gate holds,
    and it holds with the rename in the reason."""
    _a_valid_proof(project, monkeypatch)
    repo = Path(project.repo_path)
    shutil.move(repo / namespace.DIR, repo / namespace.RETIRED_DIR)

    held = gate_reason(project, sandbox="container")

    assert held, "a repository the loader refuses was admitted"
    assert ".sdlc/project.yaml" in held and ".openfactory/" in held, held
    assert "rename" in held.lower(), held
    assert "base branch" not in held, (
        f"the refusal was rewritten as a manifest that is not on the base branch: {held}")


def test_a_manifest_that_is_not_there_is_still_named_as_NOT_ON_THE_BASE_BRANCH(project,
                                                                               monkeypatch):
    """The twin: nothing under either name is the state onboarding mints on purpose (the proof is
    saved while the manifest rides an un-merged pull request), and that sentence stays."""
    _a_valid_proof(project, monkeypatch)
    shutil.rmtree(Path(project.repo_path) / namespace.DIR)

    held = gate_reason(project, sandbox="container")

    assert held and "not on the base branch yet" in held, held
