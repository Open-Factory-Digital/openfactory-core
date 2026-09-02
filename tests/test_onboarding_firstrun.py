"""The environment's first round — and the guarantees that make it safe to run in a client's room.

`openfactory/onboarding/firstrun.py` runs a synthetic ticket through the whole loop: a real box, a real
harness pass, a real diff, the client's real gates, a real reviewer. Every one of those is a thing
that could touch a client's product, and this file exists to assert it cannot.

FOUR PROMISES, AND EACH ONE HAS A MUTATION THAT REDDENS A NAMED TEST:

    the tracker is unreachable      `test_nothing_here_can_reach_a_tracker_a_forge_or_a_push`
                                    mutation: call `build_tracker` in `firstrun.py` → red
    the branches are unreachable    `test_the_remote_is_removed_and_verified_before_the_agent_runs`
                                    mutation: drop the removal loop → red
    the credential is reduced       `test_the_client_box_env_never_crosses_into_the_rehearsal_box`
                                    mutation: pass `project.box.env` as `extra_env` → red
    nothing is spent unasked        `test_without_consent_no_harness_is_ever_constructed`
                                    mutation: drop the `spend_approved` guard → red

Every fake here is a *seam*, never a stand-in for the thing under test: the gate loop that runs is
`machine.JobRunner._run_validations` itself, and the manifest is a real `Manifest`. What is faked is
docker, a harness and a dollar.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from openfactory.adapters.sandbox.base import Workspace
from openfactory.contracts import Manifest
from openfactory.contracts.project import BoxConfig, Project, ProviderRef
from openfactory.contracts.review import ReviewResult
from openfactory.contracts.run import AgentRunResult
from openfactory.onboarding import firstrun as fr

# ── fakes: docker, a harness, a dollar. Nothing else. ───────────────────────────────────────────


class FakeBox:
    """A box that records every command, and answers the four git questions the round asks."""

    def __init__(self, *, remotes=("origin",), base_resolves=True, diff=("tests/test_added.py",),
                 gate_rc=0, gate_out="", dirty="", cleanup_raises=False, prepare_raises=False,
                 setup_rc=0, git_dirs=(".git", ".git"), git_dirs_rc=0, diff_rc=0) -> None:
        self.setup_rc = setup_rc
        #: What `git rev-parse --git-dir --git-common-dir` answers. EQUAL = a repository of its
        #: own; DIFFERENT = a linked worktree sharing another repository's config. The default is
        #: what real git answers in a `git clone --local` — verified against git 2.50, both ways.
        self.git_dirs = tuple(git_dirs)
        self.git_dirs_rc = git_dirs_rc
        self.diff_rc = diff_rc
        self.remotes = list(remotes)
        self.base_resolves = base_resolves
        self.diff = list(diff)
        self.gate_rc = gate_rc
        #: What a gate command PRINTS, when a test needs it to be something other than a suite's
        #: own output — a shell answering `not found`, for instance, which is a different fact
        #: from a suite that ran and failed.
        self.gate_out = gate_out
        self.dirty = dirty
        self.cleanup_raises = cleanup_raises
        self.prepare_raises = prepare_raises
        #: every `run` command and every lifecycle call, in order — the ORDER is what several
        #: guards below assert on, so this is a list and never a set
        self.log: list[str] = []
        self.cleaned = False

    def prepare(self, *, repo_path, base_branch, branch, **_kw) -> Workspace:
        if self.prepare_raises:
            raise RuntimeError("could not start the box 'openfactory-x-rehearsal'")
        self.log.append(f"prepare:{branch}")
        return Workspace(path=Path("/workspace"), branch=branch, base_branch=base_branch,
                         host_path=Path("/tmp/clone"))

    def run(self, *, workspace, command, timeout):  # noqa: ARG002
        self.log.append(command)
        if command == "git remote":
            return 0, "\n".join(self.remotes) + ("\n" if self.remotes else "")
        if command.startswith("git remote remove "):
            self.remotes = [r for r in self.remotes if r != command.split()[-1]]
            return 0, ""
        if command == fr.OWN_CHECKOUT_PROBE:
            return self.git_dirs_rc, "\n".join(self.git_dirs) + "\n"
        if command.startswith("git rev-parse --verify"):
            return (0, "abc123") if self.base_resolves else (128, "fatal: Needed a single revision")
        if command.startswith("git status --porcelain"):
            return 0, self.dirty
        if command.startswith("git diff "):
            if self.diff_rc:
                return self.diff_rc, "fatal: ambiguous argument 'main..HEAD': unknown revision"
            return 0, "diff --git a/tests/test_added.py b/tests/test_added.py\n+def test_x(): ..."
        if "git commit" in command:
            return 0, ""
        if command.startswith("pip install"):  # the client's `setup:` — see `_manifest`
            return self.setup_rc, "could not resolve host: feed.acme.internal" if self.setup_rc \
                else "installed"
        # anything else is one of the CLIENT's gate commands
        if self.gate_out:
            return self.gate_rc, self.gate_out
        return self.gate_rc, "pytest output\nE   assert 1 == 2" if self.gate_rc else "3 passed"

    def diff_paths(self, *, workspace):  # noqa: ARG002
        return list(self.diff)

    def cleanup(self, *, workspace):  # noqa: ARG002
        self.log.append("cleanup")
        if self.cleanup_raises:
            raise RuntimeError("container still running")
        self.cleaned = True


class FakeAgent:
    def __init__(self, result: AgentRunResult | None = None, raises: bool = False) -> None:
        self.result = result or AgentRunResult(ok=True, summary="added one test", cost_usd=0.31,
                                               num_turns=7, input_tokens=9000, output_tokens=800)
        self.raises = raises
        self.calls = 0
        self.max_turns = 200

    def execute(self, *, sandbox, workspace, context):  # noqa: ARG002
        self.calls += 1
        if self.raises:
            raise RuntimeError("harness exploded")
        return self.result


class FakeReviewer:
    def __init__(self, result: ReviewResult | None = None) -> None:
        self.result = result or ReviewResult(decision="approved", score=88, summary="fine",
                                             cost_usd=0.12, num_turns=3)
        self.calls = 0

    def review(self, *, sandbox, workspace, review_input):  # noqa: ARG002
        self.calls += 1
        self.last_input = review_input
        return self.result


def _manifest(**kw) -> Manifest:
    kw.setdefault("validation", {"test": "pytest -q"})
    kw.setdefault("setup", ["pip install -e ."])
    return Manifest(**kw)


def _probes(*, box=None, agent=None, reviewer=None, manifest=None, box_ready=(True, "proven", ""),
            past_runs=None, gates_proven=True, client_env=(), route_env=("ANTHROPIC_API_KEY",),
            cap_enforced=True, on="worker", kind="container",
            image=lambda: "python:3.12") -> tuple[fr.Probes, dict]:
    """A `Probes` over the fakes, plus the handles a test needs to assert on."""
    box = box if box is not None else FakeBox()
    agent = agent if agent is not None else FakeAgent()
    manifest = manifest if manifest is not None else _manifest()
    built: dict = {"box": box, "agent": agent, "reviewer": reviewer, "executor_built": 0}

    def _executor():
        built["executor_built"] += 1
        return agent

    p = fr.Probes(
        project_name="acme",
        measured_on=lambda: on,
        sandbox_kind=lambda: kind,
        image=image,
        box_ready=lambda: box_ready,
        gates_already_proven=lambda: gates_proven,
        client_box_env=lambda: tuple(client_env),
        route_env_names=lambda: tuple(route_env),
        build_box=lambda: box,
        repo_path=lambda: Path("/repo"),
        manifest=lambda: manifest,
        executor=_executor,
        reviewer=lambda: reviewer,
        context=lambda ticket, ws: object(),  # noqa: ARG005
        past_runs=lambda: past_runs,
        bot=lambda: type("_Bot", (), {"name": "SDLC Bot", "email": "bot@localhost"})(),
        turn_cap_enforced=lambda: cap_enforced,
    )
    return p, built


APPROVED = fr.Consent(spend_approved=True, gates_may_run=True, by="alice")


# ── promise 1: the tracker, the forge and the push are unreachable ──────────────────────────────

#: Names that would take this round out of its temporary directory and into a client's world. Each
#: one is how one of the eleven smoke-test tickets reached a client's accounting product.
FORBIDDEN = {
    "build_tracker", "build_forge", "TrackerAdapter", "ForgeAdapter",
    "publish_branch", "open_pr", "create_pull_request", "create_ticket", "set_state",
    "comment", "close_ticket", "link_child", "items_in_status", "merge_pr", "build_runner",
}

#: The positive twin. A source walker that finds nothing proves nothing — it might be looking at
#: the wrong tree, matching the wrong node type, or reading an empty file. These names ARE in the
#: module, so the same walk that reports "no forbidden call" must also report finding these.
EXPECTED = {"build_executor", "build_reviewer", "build_sandbox", "_run_validations"}


def _names_used(module) -> set[str]:
    """Every attribute and bare name this module's source mentions."""
    tree = ast.parse(Path(inspect.getfile(module)).read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.alias):
            out.add((node.asname or node.name).split(".")[-1])
    return out


def test_nothing_here_can_reach_a_tracker_a_forge_or_a_push():
    """The physical guarantee, asserted where it can be broken: the source.

    MUTATION: add `from openfactory.adapters.tracker.registry import build_tracker` to `firstrun.py` and
    this goes red by name. The positive assertion below is what stops it passing vacuously — a walk
    that found nothing at all would satisfy the first half and mean nothing."""
    used = _names_used(fr)
    assert EXPECTED <= used, (
        f"the walker did not find {EXPECTED - used} — it is not seeing this module's calls, so "
        "the forbidden-name assertion below proves nothing")
    assert not (FORBIDDEN & used), (
        f"the first round reached {sorted(FORBIDDEN & used)} — this round may not touch a "
        "client's tracker, branches or PR list (openfactory/policy/test_work.py: eleven smoke-test "
        "tickets landed in a client's accounting product)")


def test_probes_carries_no_tracker_and_no_forge_seam():
    """Absence by construction, not by discipline. There is nothing to call, so no call site can
    ever be added by accident — a stub or a raising double would both be things to reach for."""
    fields = set(fr.Probes.__dataclass_fields__)
    assert not {f for f in fields if "tracker" in f or "forge" in f or "pr" == f}, fields


def test_the_synthetic_ticket_is_not_a_tracker_ref():
    """`rehearsal/first-round` must never be readable as a card on somebody's board."""
    assert not fr.looks_like_a_tracker_ref(fr.REHEARSAL_ID)
    # the twin: the detector actually detects
    for real in ("#142", "PROJ-31", "acme/app#7", "142"):
        assert fr.looks_like_a_tracker_ref(real), real


def test_the_synthetic_ticket_says_what_it_is_and_forbids_product_code():
    t = fr.rehearsal_ticket(repo="acme", base_branch="main")
    assert "destroyed" in t.objective and "no git remote" in t.objective
    assert "production source files" in t.out_of_scope
    assert len(t.acceptance_criteria) == 3


# ── promise 2: the branches are unreachable ─────────────────────────────────────────────────────

def test_the_remote_is_removed_and_verified_before_the_agent_runs():
    """Order is the guarantee: an agent that starts before the removal has had a push window.

    MUTATION: delete the `git remote remove` loop in `isolation_stage` and this goes red — the
    verification read still finds `origin`, so the round refuses before the agent."""
    box = FakeBox(remotes=("origin", "upstream"))
    p, built = _probes(box=box, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    removed = [i for i, c in enumerate(box.log) if c.startswith("git remote remove")]
    verified = box.log.index("git remote", removed[-1])
    assert removed, "no remote was removed"
    assert verified > removed[-1], "the removal was never verified"
    # the agent ran, and it ran AFTER all of that
    assert built["agent"].calls == 1
    isolation = next(s for s in run.stages if s.name == "isolation")
    assert isolation.ok and "2 remote(s) removed" in isolation.message


def test_a_clone_whose_remotes_survive_stops_the_round_before_any_money():
    """A removal that did not take is not a warning. `FakeBox` here refuses to forget `origin`."""

    class Stubborn(FakeBox):
        def run(self, *, workspace, command, timeout):
            if command.startswith("git remote remove "):
                self.log.append(command)
                return 1, "error: could not remove"
            return super().run(workspace=workspace, command=command, timeout=timeout)

    p, built = _probes(box=Stubborn(), reviewer=FakeReviewer())
    run = fr.rehearse(p, consent=APPROVED)

    assert run.verdict == "WOULD FAIL AT isolation"
    assert built["agent"].calls == 0, "an agent ran in a checkout that can still reach the forge"
    assert run.exit_code == 1


def test_a_base_ref_that_stops_resolving_is_caught_before_the_diff_can_lie():
    """`diff_paths` turns a failed `git diff` into `[]`, which reads as 'the agent wrote nothing'.

    Removing every remote deletes `refs/remotes/origin/*`, so a base branch that only existed there
    stops resolving — and the round would then blame the agent, one station after the money was
    spent. The isolation stage verifies the ref instead."""
    p, built = _probes(box=FakeBox(base_resolves=False), reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "isolation")
    assert not stage.ok and "no longer resolves" in stage.message
    assert "EMPTY diff" in stage.remedy
    assert built["agent"].calls == 0


# ── promise 2b: the checkout this round runs in is a COPY, and that is measured ─────────────────
#
# `git worktree add` shares the parent repository's config. Verified with real git 2.50, both
# directions, before these were written:
#
#     plain checkout / `git clone --local --no-hardlinks` → `.git`  `.git`
#     `git worktree add`                    → `<other>/.git/worktrees/x`  `<other>/.git`
#
# and in a worktree, `git remote remove origin` deletes `origin` from the PARENT repository — the
# client's own checkout, permanently, with nothing here to put it back.


def test_a_workspace_that_shares_another_repositorys_git_dir_is_refused_before_anything_runs():
    """THE ONE THAT MATTERS. `WorktreeSandbox.prepare` does `git worktree add` inside the
    repository it is handed, so the round's `git remote remove` would edit the CLIENT's config.

    MUTATION: delete the `_owns_its_checkout` call in `workspace_stage` and this goes red — the
    remote is removed, the agent runs, and the round reports `LOOP PROVEN` about a repository it
    just damaged."""
    box = FakeBox(git_dirs=("/repo/.git/worktrees/openfactory-env-rehearsal", "/repo/.git"))
    p, built = _probes(box=box, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "workspace")
    assert not stage.ok and "SHARES another repository's git directory" in stage.message
    assert "/repo/.git" in stage.message
    assert not [c for c in box.log if c.startswith("git remote remove")], (
        "a remote was removed from a checkout that shares the client's own git config")
    assert built["agent"].calls == 0
    assert run.verdict == "WOULD FAIL AT workspace"


def test_a_checkout_that_cannot_answer_is_never_read_as_a_clone():
    """Absence reads as compliance, which is this codebase's most expensive defect. A probe that
    could not run is not evidence that the workspace is a copy."""
    box = FakeBox(git_dirs_rc=128, git_dirs=("fatal: not a git repository",))
    p, built = _probes(box=box, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "workspace")
    assert not stage.ok and "could not ask this workspace" in stage.message
    assert not [c for c in box.log if c.startswith("git remote remove")]
    assert built["agent"].calls == 0


def test_the_positive_twin_a_real_clone_answers_the_probe_and_the_round_runs():
    """The negative guards above prove nothing on their own: a probe that always failed would
    satisfy both. The default `FakeBox` answers what a real `git clone --local` answers."""
    box = FakeBox()
    p, built = _probes(box=box, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    assert fr.OWN_CHECKOUT_PROBE in box.log, box.log
    assert box.log.index(fr.OWN_CHECKOUT_PROBE) < box.log.index("pip install -e ."), (
        "the client's setup ran in a checkout nobody had proved was a copy")
    assert box.log.index(fr.OWN_CHECKOUT_PROBE) < box.log.index("git remote remove origin")
    assert run.verdict == "LOOP PROVEN" and built["agent"].calls == 1


def test_the_probe_is_the_question_git_actually_answers():
    """The command is pinned, because the guard is only as good as what it asks. `--git-dir` is
    this working tree's ref store; `--git-common-dir` is the config and objects it WRITES to."""
    assert fr.OWN_CHECKOUT_PROBE == "git rev-parse --git-dir --git-common-dir"


def test_a_box_that_cannot_run_the_clients_image_is_refused_before_it_prepares():
    """A round taken in a box that ignores `box.image` certifies a box no ticket ever runs in.

    AND IT IS REFUSED BEFORE `prepare`, which is not a detail: `WorktreeSandbox.prepare` runs
    `git branch -D` and `git worktree add -b` in the CLIENT's repository, so a refusal after it
    would already have written a branch into their checkout that this round never cleans up."""
    box = FakeBox()
    p, built = _probes(box=box, kind="worktree", reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "workspace")
    assert not stage.ok and "cannot run this project's image" in stage.message
    assert box.log == [], "the box was asked to prepare a workspace after the round refused it"
    assert built["agent"].calls == 0


def test_the_image_question_is_asked_of_the_registry_not_of_a_vendor_name():
    """`factory.resolve_box_image` paid for the alternative: its first version tested
    `sandbox == "fargate"` and let `worktree` — the CLI's default — ignore `box.image` in silence.

    The twin runs both ways against the REAL trait table, so a table that changed its mind would
    be seen here rather than in a client's room."""
    from openfactory.adapters.sandbox.registry import box_traits

    for kind in ("worktree", "fargate"):
        assert not box_traits(kind).honours_image, kind
        assert fr._box_cannot_answer_this_question(kind) is not None, kind
    assert box_traits("container").honours_image
    assert fr._box_cannot_answer_this_question("container") is None
    # an unknown kind belongs to the registry's own error, which lists what IS supported
    assert fr._box_cannot_answer_this_question("nonesuch") is None


def test_a_remote_box_keeps_the_message_about_being_remote():
    """`build_sandbox` raises for fargate, and that raise says the accurate thing. The image guard
    runs AFTER the build for exactly this reason — placed before it, it would answer a remote box
    with a sentence about images and lose the only true thing said about it."""

    class Remote(FakeBox):
        pass

    def _explode():
        raise ValueError("the 'fargate' box is remote: there is no local SandboxAdapter to build")

    p, _ = _probes(box=Remote(), kind="fargate", reviewer=FakeReviewer())
    p.build_box = _explode

    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "workspace")
    assert "the fargate box could not be started" in stage.message
    assert "is remote" in stage.message, stage.message


def test_the_remedy_names_the_box_this_round_actually_creates():
    """A remedy is an INSTRUCTION. `docker ps -a and remove anything named sdlc-<project>-*` also
    matches `sdlc-<project>-<issue>` — a RUNNING job's box — so an operator following it during an
    incident destroys work. Tied here to the name the live wiring really produces, rather than to
    a string somebody remembers to keep in step."""
    from openfactory.adapters.sandbox.container import _container_name

    real = _container_name("acme-rehearsal", fr.REHEARSAL_BRANCH.replace("/", "-"))
    p, _ = _probes(box=FakeBox(cleanup_raises=True), reviewer=FakeReviewer())
    run = fr.rehearse(p, consent=APPROVED)

    remedy = next(s for s in run.stages if s.name == "teardown").remedy
    prefix = "openfactory-acme-rehearsal-"
    assert prefix in remedy, remedy
    assert real.startswith(prefix), (real, prefix)
    # the twin: a live job's box must NOT match what the remedy tells an operator to remove
    assert not _container_name("acme", "sdlc-12").startswith(prefix)


# ── promise 3: the credential is reduced ────────────────────────────────────────────────────────

def _project_with_secrets() -> Project:
    return Project(
        name="acme", repo_path="/repo",
        tracker=ProviderRef(kind="github", repo="acme/app"),
        box=BoxConfig(image="python:3.12",
                      env=["GITHUB_TOKEN", "SYSTEM_ACCESSTOKEN", "BLACKDUCK_API_TOKEN"]),
    )


def test_the_client_box_env_never_crosses_into_the_rehearsal_box(monkeypatch):
    """The guarantee that actually holds: a removed remote is nothing next to a live push token.

    MUTATION: in `probes_for._build_box`, add `extra_env=(*_route_env(), *project.box.env)` and
    this goes red by name."""
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "container")
    monkeypatch.delenv("OPENFACTORY_TOOLBOX_VOLUME", raising=False)
    p = fr.probes_for(_project_with_secrets())

    box = p.build_box()

    carried = set(getattr(box, "extra_env", ()))
    assert "GITHUB_TOKEN" not in carried, carried
    assert "SYSTEM_ACCESSTOKEN" not in carried, carried
    assert "BLACKDUCK_API_TOKEN" not in carried, carried
    # the positive twin: the harness's OWN route still crosses, or the round cannot run at all
    assert carried == set(p.route_env_names()), carried
    assert carried, "the box carries no credential at all — the harness could not authenticate"


def test_what_was_withheld_is_named_in_the_report():
    """A security decision nobody can see is a security decision nobody can check."""
    p, _ = _probes(client_env=("GITHUB_TOKEN", "SYSTEM_ACCESSTOKEN"), reviewer=FakeReviewer())
    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "workspace")
    assert "WITHHELD" in stage.message
    assert "GITHUB_TOKEN" in stage.message and "SYSTEM_ACCESSTOKEN" in stage.message


def test_the_rehearsal_box_is_not_the_job_box_by_name(monkeypatch):
    """Two boxes must never share a container name: one deployment, N projects, one docker."""
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "container")
    p = fr.probes_for(_project_with_secrets())
    assert "rehearsal" in getattr(p.build_box(), "project", "")


# ── promise 4: nothing is spent unasked ─────────────────────────────────────────────────────────

def test_without_consent_no_agent_pass_is_ever_made():
    """The estimate is free; the round is not. A caller must be able to decline after seeing one.

    THE PRECISE CLAIM, because a looser one would be false. `estimate_cost` runs BEFORE this gate
    (the caller needs the number in the declined result), and in the live wiring it asks
    `turn_cap_enforced`, which constructs an adapter object. Constructing one makes no call and
    costs nothing. What is guaranteed is that `Probes.executor` is never reached and no pass is
    ever made — which is where the money is.

    MUTATION: remove the `if not consent.spend_approved` branch in `rehearse` and this goes red —
    the executor probe is called, and the fake counts it."""
    p, built = _probes(reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=fr.Consent())

    assert built["executor_built"] == 0, "a harness was built for a round nobody approved"
    assert built["agent"].calls == 0
    assert run.verdict.startswith("NOT RUN")
    assert run.exit_code == 1
    assert run.stages == []
    assert "2 real agent pass(es)" in run.verdict


def test_the_estimate_is_measured_from_this_deployments_own_spend():
    rows = [
        {"role": "executor", "cost_usd": 0.40}, {"role": "executor", "cost_usd": 1.20},
        {"role": "review", "cost_usd": 0.10}, {"role": "review", "cost_usd": 0.30},
        {"role": "planner", "cost_usd": 99.0},  # not a pass this round makes
    ]
    p, _ = _probes(past_runs=rows)
    est = fr.estimate_cost(p)

    assert est.usd_low == pytest.approx(0.50) and est.usd_high == pytest.approx(1.50)
    assert est.sample == 4
    assert "2 executor" in est.basis and "2 review" in est.basis


def test_an_unknown_cost_is_never_reported_as_a_free_one():
    """`None` is could-not-determine. `0.0` would put an unmeasured round into a price comparison
    it would then win — and a first round is exactly when there is no history."""
    p, _ = _probes(past_runs=[])
    est = fr.estimate_cost(p)

    assert est.usd_low is None and est.usd_high is None and est.unknown
    assert "recorded no agent run" in est.basis
    assert "cost: UNKNOWN" in "\n".join(est.render())


def test_telemetry_that_could_not_be_read_is_not_priced_at_zero_either():
    """THE SENTENCE WAS ASSERTED AND THE NUMBER WAS NOT, so `usd_low=0.0` on this branch passed
    the whole file. Measured: with `estimate_cost`'s unreadable-telemetry return changed to
    `usd_low=0.0, usd_high=0.0`, all 48 tests stayed green — the branch the module's own docstring
    calls the place "`None` is not zero" earns its keep.

    MUTATION: return `usd_low=0.0, usd_high=0.0` from that branch and this goes red by name."""
    est = fr.estimate_cost(_probes(past_runs=None)[0])

    assert est.usd_low is None and est.usd_high is None and est.unknown
    assert est.sample == 0
    assert "cost: UNKNOWN" in "\n".join(est.render())
    assert "$0.00" not in "\n".join(est.render())


def test_unreadable_telemetry_and_an_empty_one_do_not_print_the_same_sentence():
    """Both are 'no number', and they send a reader in opposite directions: one is a broken metrics
    sink, the other is a brand-new client. `records_of_kind` collapses them; this does not."""
    unreadable = fr.estimate_cost(_probes(past_runs=None)[0]).basis
    empty = fr.estimate_cost(_probes(past_runs=[])[0]).basis

    assert unreadable != empty
    assert "could not be read" in unreadable
    assert "recorded no agent run" in empty


def test_rows_without_a_price_are_not_counted_as_zero():
    """A harness that reports effort and not dollars (Codex) must not drag the range to zero."""
    rows = [{"role": "executor", "cost_usd": None, "num_turns": 12},
            {"role": "review", "cost_usd": None}]
    est = fr.estimate_cost(_probes(past_runs=rows)[0])

    assert est.unknown
    assert "none of them carries a price" in est.basis


def test_an_unenforceable_turn_cap_says_so_instead_of_pretending():
    est = fr.estimate_cost(_probes(cap_enforced=False)[0])
    assert "REPORTED ONLY" in "\n".join(est.render())


# ── the client's own setup, in the round's own box ──────────────────────────────────────────────

def test_the_clients_setup_runs_in_this_rounds_own_box():
    """FOUND BY RUNNING IT against `py-simple` on a real docker daemon, not by reading the code.

    `box prove` runs `setup:` in ITS box and destroys it, so a round that composed the proof as a
    precondition and skipped setup got a FRESH box with none of the client's dependencies — and
    reported the client's own `pytest` as broken. A real job runs `setup:` right before the
    executor (`machine.py`) for exactly this reason.

    MUTATION: remove the `runner.setup_stage()` branch in `rehearse` and this goes red by name."""
    box = FakeBox()
    p, built = _probes(box=box, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    assert "pip install -e ." in box.log, box.log
    assert box.log.index("pip install -e .") < box.log.index("pytest -q"), (
        "the gates ran before the environment they need was prepared")
    assert next(s for s in run.stages if s.name == "setup").ok
    assert built["agent"].calls == 1


def test_setup_runs_before_the_remote_is_removed_and_the_agent_after_it():
    """`setup:` is the CLIENT's declared install and some of it needs the remote (submodules, a
    private feed reached over git). The invariant is that the remote is gone before the AGENT."""
    box = FakeBox()
    p, built = _probes(box=box, reviewer=FakeReviewer())

    class Recording(FakeAgent):
        def execute(self, *, sandbox, workspace, context):
            box.log.append("AGENT")
            return super().execute(sandbox=sandbox, workspace=workspace, context=context)

    p.executor = Recording
    fr.rehearse(p, consent=APPROVED)

    setup_at = box.log.index("pip install -e .")
    removed_at = box.log.index("git remote remove origin")
    agent_at = box.log.index("AGENT")
    assert setup_at < removed_at < agent_at, box.log


def test_a_failing_setup_stops_the_round_before_the_agent_and_blames_the_right_thing():
    """And it names the round's OWN withholding as a candidate cause — a setup that needs a
    credential from `box.env` will fail here and work in a real job, and that difference is a
    finding rather than a mystery."""
    p, built = _probes(box=FakeBox(setup_rc=1), reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "setup")
    assert not stage.ok and "feed.acme.internal" in stage.message
    assert "withholds every name in `box.env`" in stage.remedy
    assert built["agent"].calls == 0
    assert run.verdict == "WOULD FAIL AT setup"


def test_a_project_with_no_setup_is_a_reading_and_not_a_gap():
    """`[]` = read the manifest, nothing there. An image that already carries the toolchain really
    does need no install, and calling that a gap sends somebody to write a line for nothing."""
    p, _ = _probes(manifest=_manifest(setup=[]), reviewer=FakeReviewer())
    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "setup")
    assert stage.ok and stage.answered and "no setup command" in stage.message


# ── the loop itself ─────────────────────────────────────────────────────────────────────────────

def test_a_green_round_proves_the_loop_and_reports_every_station():
    p, built = _probes(reviewer=FakeReviewer())
    seen: list[str] = []
    done: list[fr.Stage] = []

    run = fr.rehearse(p, consent=APPROVED, on_start=seen.append, on_stage=done.append)

    assert run.verdict == "LOOP PROVEN", run.render()
    assert run.exit_code == 0
    assert [s.name for s in run.stages] == list(fr.STAGES), "a station stopped being reported"
    assert run.would_fail == []
    assert built["reviewer"].calls == 1
    # cost is the SUM of the two real passes, and it is reported
    assert run.spent_usd == pytest.approx(0.43)
    assert run.unpriced_passes == 0


def test_every_station_is_announced_before_it_answers():
    """A round whose first proof of life is the verdict has lost the room. An agent pass is minutes.

    MUTATION: delete the `self.announce(...)` call in `agent_stage` and this goes red by name."""
    p, _ = _probes(reviewer=FakeReviewer())
    started: list[str] = []
    finished: list[str] = []

    fr.rehearse(p, consent=APPROVED,
                on_start=started.append, on_stage=lambda s: finished.append(s.name))

    assert started == list(fr.STAGES), started
    assert finished == list(fr.STAGES), finished
    # and the announcement precedes the answer for every single one
    assert all(started.index(name) <= finished.index(name) for name in fr.STAGES)


def test_a_console_that_raises_never_fails_the_round():
    """The callbacks are a client's screen. A broken screen is not a broken environment."""
    p, _ = _probes(reviewer=FakeReviewer())

    def boom(_):
        raise RuntimeError("terminal closed")

    run = fr.rehearse(p, consent=APPROVED, on_start=boom, on_stage=boom)
    assert run.verdict == "LOOP PROVEN"


def test_the_stations_a_stopped_round_never_reached_are_reported_by_name():
    """A report that simply stops reads, to somebody who has never seen a complete one, like a
    complete report with fewer stations."""
    p, _ = _probes(box_ready=(False, "the box has never been proven", "run `sdlc box prove acme`"))

    run = fr.rehearse(p, consent=APPROVED)

    assert [s.name for s in run.stages] == list(fr.STAGES)
    assert run.verdict == "WOULD FAIL AT box"
    skipped = {s.name for s in run.skipped}
    assert "agent" in skipped and "gates" in skipped and "review" in skipped
    assert all("stopped at `box`" in s.message for s in run.skipped)
    assert "run `sdlc box prove acme`" in run.would_fail[0]


def test_an_unproven_box_never_gets_an_agent_pass():
    """C-35 as a precondition: 47 turns once ended in `ruff: not found`, at agent prices."""
    p, built = _probes(box_ready=(False, "never proven", "run `sdlc box prove acme`"))
    fr.rehearse(p, consent=APPROVED)
    assert built["executor_built"] == 0


def test_a_diff_of_nothing_is_a_failure_not_a_pass():
    """A round where the agent wrote nothing proved that a real ticket opens no PR."""
    p, _ = _probes(box=FakeBox(diff=()), reviewer=FakeReviewer())
    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "diff")
    assert not stage.ok and "no change at all" in stage.message
    assert run.verdict == "WOULD FAIL AT diff"


def test_a_failed_commit_is_told_apart_from_an_agent_that_wrote_nothing():
    """`diff_paths` returns `[]` for both. They have opposite remedies — one is ours, one is theirs.

    MUTATION: drop the `git status --porcelain` branch in `diff_stage` and this goes red."""
    p, _ = _probes(box=FakeBox(diff=(), dirty=" M src/app.py\n?? tests/test_new.py\n"),
                   reviewer=FakeReviewer())
    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "diff")
    assert "the commit did not take them" in stage.message
    assert "test_new.py" in stage.message


def test_a_diff_that_could_not_be_read_never_reaches_the_reviewer():
    """`_, self.diff_text = box.run(...)` threw the exit code away, so a failed `git diff` handed
    its own error text to the reviewer AS the diff — and the reviewer would answer with a decision
    about the client's code that nothing had read. fx-ado PR #9, one station earlier and harder to
    see, because an error message looks like input.

    MUTATION: drop the `if rc != 0` branch in `diff_stage` and this goes red — the reviewer is
    called, with `fatal: ambiguous argument` as its diff."""
    p, built = _probes(box=FakeBox(diff_rc=128), reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "diff")
    assert not stage.ok and "exited 128" in stage.message
    assert "reviewer's ENTIRE input" in stage.remedy
    assert built["reviewer"].calls == 0, "a reviewer judged the client's code from an error message"
    assert run.verdict == "WOULD FAIL AT diff"


def test_the_image_that_was_measured_is_named_in_the_report():
    """`Probes.image` was a documented seam that NOTHING asked — the defect class this module's own
    docstring is about, inside the module about it. A client whose stack is .NET 8 asks which image
    was proven, and "container" is not that answer.

    MUTATION: drop `{image}` from the workspace message and this goes red by name."""
    p, _ = _probes(image=lambda: "mcr.microsoft.com/dotnet/sdk:8.0", reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    assert "mcr.microsoft.com/dotnet/sdk:8.0" in next(
        s for s in run.stages if s.name == "workspace").message


def test_an_image_that_cannot_be_read_says_so_and_does_not_fail_a_running_box():
    """`resolve_box_image` RAISES when a project declares an image its box cannot honour. The box
    is already up by then, and failing it over a LABEL would be a failure invented by the report —
    while printing nothing would be the same collapse in the other direction."""

    def _raises():
        raise ValueError("declares box.image=x, but this deployment's box cannot honour it")

    p, _ = _probes(image=_raises, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "workspace")
    assert stage.ok and "image unreadable" in stage.message
    assert run.verdict == "LOOP PROVEN"


def test_the_real_gate_loop_runs_the_clients_real_gates():
    """The gates are `machine.JobRunner._run_validations` itself — advisory flags and all."""
    manifest = _manifest(validation={"test": "pytest -q",
                                     "security": {"command": "semgrep .", "advisory": True}})
    box = FakeBox(gate_rc=1)  # every client command fails
    p, _ = _probes(box=box, manifest=manifest, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "gates")
    assert "pytest -q" in box.log and "semgrep ." in box.log, box.log
    assert "security=exit 1 (advisory)" in stage.message, stage.message
    assert not stage.ok, "a blocking gate failed and the round called it fine"
    assert "repair loop" in stage.remedy


def test_an_advisory_only_failure_does_not_stop_the_round():
    """A brownfield client's scanners report fifteen years of debt on their first pass. That is the
    whole reason `advisory` exists (`presets/security-oss.yaml`), and a round that failed on it
    would refuse every legacy client on day one."""
    manifest = _manifest(validation={"security": {"command": "semgrep .", "advisory": True}})
    p, _ = _probes(box=FakeBox(gate_rc=1), manifest=manifest, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    assert run.verdict == "LOOP PROVEN", run.render()


def test_a_project_with_no_applicable_gate_is_a_finding(monkeypatch):
    """A run with no gates reports green having proven nothing.

    REACHING THIS TAKES WORK, AND THAT IS THE POINT OF THE COMMENT. `Manifest` inherits
    `org_defaults/floor.yaml`'s advisory credential scan into every project that does not declare
    `security` itself, so `validate: {}` alone still runs one gate. The state below is the one
    where the floor file is NOT THERE — an installed wheel whose package data missed
    `org_defaults/**` (card #99 §2, measured: `pyproject.toml`'s glob has one level). That is
    exactly the distributed installation this card exists for, and on it a first round would
    otherwise report a green loop over zero gates."""
    monkeypatch.setattr("openfactory.policy.presets.org_default_validation", dict)
    p, _ = _probes(manifest=Manifest(setup=[], validation={}), reviewer=FakeReviewer())
    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "gates")
    assert not stage.ok and "declares no gate" in stage.message


def test_gates_nobody_cleared_are_unanswered_and_the_round_is_not_proven():
    """A legacy suite can truncate a shared dev database from a workshop. Nobody has said whether
    this one does, and no box proof covers these commands — so the stage asks instead of running.

    And the verdict may not be green: `----` is not a shade of `ok`."""
    box = FakeBox()
    p, _ = _probes(box=box, gates_proven=False, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=fr.Consent(spend_approved=True, by="alice"))

    stage = next(s for s in run.stages if s.name == "gates")
    assert not stage.answered and stage.ok is True
    assert "writes to a real system" in stage.message
    assert "pytest -q" not in box.log, "the client's suite ran without anybody clearing it"
    assert run.verdict.startswith("PARTIAL")
    assert run.exit_code == 1, "a round that skipped the gates exited 0"
    assert "----" in "\n".join(run.render())


def test_an_existing_box_proof_is_enough_to_run_the_gates_unasked():
    """`box prove` has already run these exact commands in this box, so the round adds no exposure
    the platform has not already taken. That is a reason, not a shrug."""
    box = FakeBox()
    p, _ = _probes(box=box, gates_proven=True, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=fr.Consent(spend_approved=True, by="alice"))

    assert "pytest -q" in box.log
    assert run.verdict == "LOOP PROVEN"


def test_a_no_from_the_client_stops_the_gates_and_says_who_said_it():
    box = FakeBox()
    p, _ = _probes(box=box, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=fr.Consent(spend_approved=True, gates_may_run=False, by="ana"))

    assert "pytest -q" not in box.log
    assert "somebody said" in next(s for s in run.stages if s.name == "gates").message
    assert "approved by ana" in run.header()[0]


def test_a_harness_pause_is_not_reported_as_the_clients_problem():
    """A rate limit on our account says nothing about whether the factory works there."""
    paused = AgentRunResult(ok=False, pause_reason="rate_limit", summary="429")
    p, _ = _probes(agent=FakeAgent(paused), reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "agent")
    assert "OUR side, not your environment" in stage.message


def test_an_unparsed_review_is_not_a_rejection():
    """fx-ado PR #9: a correct diff headed `rejected` because our own envelope did not parse. On a
    first round that reads as the factory judging the client's code."""
    unread = ReviewResult(decision="rejected", score=0,
                          summary="reviewer output could not be parsed")
    p, _ = _probes(reviewer=FakeReviewer(unread))

    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "review")
    assert "not a judgement about the diff" in stage.remedy
    assert "nothing readable" in stage.message


def test_the_reviewer_sees_the_diff_and_the_gate_results():
    p, built = _probes(reviewer=FakeReviewer())
    fr.rehearse(p, consent=APPROVED)

    sent = built["reviewer"].last_input
    assert "test_added.py" in sent.diff
    # DERIVED, NOT HARDCODED. The reviewer must see exactly the gates that RAN — and what runs is
    # the project's own `validate:` PLUS whatever deployment floor `Manifest` inherits
    # (`org_defaults/floor.yaml`). Pinning a literal list here would make this test a statement
    # about the install rather than about the round, and it would go red the day the floor file
    # changes for reasons that have nothing to do with this module.
    from openfactory.orchestrator.validation import applicable_validations

    expected = list(applicable_validations([], _manifest()))
    assert [v.name for v in sent.validations] == expected, expected
    assert "test" in expected, "the project's own gate is not among what the reviewer saw"


def test_a_project_that_reviews_with_nothing_is_unanswered_never_green():
    p, _ = _probes(reviewer=None)
    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "review")
    assert not stage.answered
    assert run.verdict.startswith("PARTIAL")


# ── teardown, provenance, and the report itself ─────────────────────────────────────────────────

def test_the_clone_is_destroyed_even_when_the_round_fell_over():
    """The one thing worse than a failed round is a failed round that left a container holding a
    clone of the client's repository."""
    box = FakeBox(diff=())
    p, _ = _probes(box=box, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    assert box.cleaned, "a failed round leaked the clone"
    assert next(s for s in run.stages if s.name == "teardown").ok


def test_a_leaked_container_is_a_finding_and_not_a_log_line():
    """This CLI configures no logging at all, so a `log.warning` is a message to nobody — the
    exact defect `box_prove.save` was fixed for."""
    p, _ = _probes(box=FakeBox(cleanup_raises=True), reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "teardown")
    assert not stage.ok and "still on this machine" in stage.remedy
    assert run.verdict == "WOULD FAIL AT teardown"


def test_an_unstartable_box_is_a_finding_and_the_agent_never_runs():
    """BOTH HALVES, because they are now two stations' worth of blame in one message. The box that
    cannot be BUILT (a remote one, a daemon that refused) and the box that builds and cannot make a
    WORKSPACE (an unreadable repo path, a base branch that is not there) send a reader to different
    places, and a single sentence for both sent them to the wrong one half the time."""
    p, built = _probes(box=FakeBox(prepare_raises=True), reviewer=FakeReviewer())
    run = fr.rehearse(p, consent=APPROVED)

    stage = next(s for s in run.stages if s.name == "workspace")
    assert not stage.ok and "could not make a workspace" in stage.message
    assert built["agent"].calls == 0

    def _explode():
        raise RuntimeError("Cannot connect to the Docker daemon")

    p2, built2 = _probes(reviewer=FakeReviewer())
    p2.build_box = _explode
    run2 = fr.rehearse(p2, consent=APPROVED)

    stage2 = next(s for s in run2.stages if s.name == "workspace")
    assert not stage2.ok and "could not be started" in stage2.message
    assert "Docker daemon" in stage2.message
    assert built2["agent"].calls == 0


def test_a_round_measured_on_a_laptop_says_so_first():
    """A verdict about a laptop, delivered with the authority of a verdict about the factory, is
    how a client gets blamed for a docker daemon that was fine."""
    p, _ = _probes(on="local", reviewer=FakeReviewer())
    run = fr.rehearse(p, consent=APPROVED)

    assert "measured on: local" in run.header()[0]
    assert "NOT the machine that runs your tickets" in run.header()[1]
    assert all(s.measured_on == "local" for s in run.stages)


def test_every_stage_carries_provenance():
    """MUTATION: delete `measured_on=on` from `_ok` and this goes red."""
    p, _ = _probes(reviewer=FakeReviewer())
    run = fr.rehearse(p, consent=APPROVED)
    assert all(s.measured_on for s in run.stages), [s.name for s in run.stages if not s.measured_on]


def test_every_failing_stage_carries_a_remedy():
    """A finding with no remedy is a symptom handed to the one person who does not know the system.
    Structurally enforced by `_fail`; asserted here across every failure this file can produce."""
    for probes in (
        _probes(box_ready=(False, "x", "do y"))[0],
        _probes(box=FakeBox(base_resolves=False), reviewer=FakeReviewer())[0],
        _probes(box=FakeBox(diff=()), reviewer=FakeReviewer())[0],
        _probes(manifest=_manifest(validation={}), reviewer=FakeReviewer())[0],
        _probes(agent=FakeAgent(raises=True), reviewer=FakeReviewer())[0],
        _probes(box=FakeBox(cleanup_raises=True), reviewer=FakeReviewer())[0],
    ):
        run = fr.rehearse(probes, consent=APPROVED)
        for stage in run.failed:
            assert stage.remedy, f"{stage.name} failed with no remedy"


def test_an_unpriced_pass_is_named_in_the_total():
    """A total that silently omits a pass is a total a client compares against a competitor's."""
    p, _ = _probes(agent=FakeAgent(AgentRunResult(ok=True, summary="done", num_turns=4)),
                   reviewer=FakeReviewer())
    run = fr.rehearse(p, consent=APPROVED)

    assert run.unpriced_passes == 1
    assert "the real total is higher" in "\n".join(run.render())
    assert "cost not reported" in next(s for s in run.stages if s.name == "agent").line()


def test_the_verdict_and_the_stages_can_never_disagree():
    """`verdict` is a property over `stages`, so there is no stored sentence to drift."""
    p, _ = _probes(reviewer=FakeReviewer())
    run = fr.rehearse(p, consent=APPROVED)
    assert run.proven and run.exit_code == 0

    run.stages.append(fr.Stage(name="gates", ok=False, message="broke", remedy="fix",
                               measured_on="worker"))
    assert run.verdict == "WOULD FAIL AT gates" and run.exit_code == 1


def test_a_gate_that_could_not_RUN_sends_the_operator_to_the_box_and_not_to_the_code():
    """The first round is where a missing tool is most likely to be found, and the remedy it used
    to print was about the client's CODE — *"these are YOUR gates… a real ticket would enter the
    repair loop here"*. Neither half is true of a command that is not in the image: the code is
    not what is wrong, and a real ticket now holds instead of paying for repairs.
    """
    box = FakeBox(gate_rc=127, gate_out="/bin/sh: 1: pytest: not found")
    p, _ = _probes(box=box, reviewer=FakeReviewer())

    run = fr.rehearse(p, consent=APPROVED)

    gates = next(s for s in run.stages if s.name == "gates")
    assert gates.ok is False, "a gate that never ran must not report the round as proven"
    assert "could not run" in gates.message, gates.message
    assert "pytest: not found" in gates.message, "the operator is not told WHICH command"
    assert "the box, not your code" in gates.remedy, gates.remedy
    assert "YOUR gates" not in gates.remedy, (
        "the remedy still points at the client's code for a tool that is not installed")


# ── the reuse that has to keep working ──────────────────────────────────────────────────────────

#: What `_GateHost` provides. `_run_validations` is called as a plain function with that stand-in,
#: so its `self` usage has to stay inside this set — and the day it does not, this test says so
#: rather than production saying so.
GATE_HOST_ATTRS = {"sandbox", "manifest", "_emit"}


def test_the_gate_loop_stays_reusable():
    """The assertion that makes `gates_stage`'s reuse safe instead of clever.

    MUTATION: add `self.project` to `machine.JobRunner._run_validations` and this goes red by name,
    naming the attribute. The positive half is not decoration: a walker that found no `self.X` at
    all would pass the subset check while proving nothing."""
    from openfactory.orchestrator.machine import JobRunner

    source = inspect.getsource(JobRunner._run_validations)
    tree = ast.parse(re.sub(r"^    ", "", source, flags=re.M))
    used = {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name) and node.value.id == "self"
    }
    assert "sandbox" in used, "the walker saw no `self.sandbox` — it is not reading the method"
    assert used <= GATE_HOST_ATTRS, (
        f"`_run_validations` now reads self.{sorted(used - GATE_HOST_ATTRS)} — "
        "`firstrun._GateHost` does not provide it, so the first round's gate stage would raise in "
        "production and nowhere else")
    assert GATE_HOST_ATTRS <= set(fr._GateHost.__dataclass_fields__) | {"_emit"}


def test_the_first_round_does_not_write_its_own_gate_loop():
    """Reuse, asserted. A twelve-line copy would agree today and drift silently tomorrow.

    MUTATION: replace the `JobRunner._run_validations(...)` call with a local loop over
    `applicable_validations` and this goes red."""
    used = _names_used(fr)
    assert "_run_validations" in used
    assert "applicable_validations" not in used, (
        "the first round is resolving gates itself instead of calling the factory's own loop")


def test_the_stage_list_is_the_contract():
    """A control that must stay GREEN under every mutation above — if a mutation reddens THIS, it
    broke the module rather than the guard it was aimed at (a SyntaxError reddens everything and
    looks exactly like proof)."""
    assert fr.STAGES[0] == "box" and fr.STAGES[-1] == "teardown"
    assert set(fr.COSTED_STAGES) < set(fr.STAGES)
    assert fr.AGENT_PASSES == len(fr.COSTED_STAGES)
