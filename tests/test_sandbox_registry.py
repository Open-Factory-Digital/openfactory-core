"""The box is an axis with a registry, and the lifecycle stops naming a vendor (C-10).

ADR-0022 graded eight axes and marked **sandbox** as "fine": two implementations, a Protocol,
dispatch. That was the one row it got wrong, and the reason it escaped is that **Fargate does not
look like an adapter.** It is not an implementation of `SandboxAdapter`; it is a parallel path
selected by `if sandbox == "fargate"` in roughly eight places — three of them inside the Temporal
workflow body, where a change breaks replay for jobs in flight.

READING THOSE THREE CAREFULLY SHOWS THEY ARE NOT THE SAME QUESTION, and that is the whole design:

    workflow.py:444   `if params.sandbox != "fargate": return`   → is the box REMOTE?
    workflow.py:486   `_RETRY_FARGATE if ... else _ONCE`         → is re-running it IDEMPOTENT?
    workflow.py:728   the same again

The second and third are not about Fargate at all. The comment beside them says so: *"fargate is
idempotent (re-attach/reconcile) so it retries; the local coarse path re-runs the agent + dup
comments, so it stays single-attempt."* That is a property OF THE BOX, and it belongs with the box.

So the registry carries traits, not just builders, and the lifecycle asks a question instead of
naming a provider. The branch at :444 remains — *where a job runs* genuinely differs — but it now
asks `remote` rather than `== "fargate"`, which is the difference between a lifecycle that knows
about a vendor and one that knows about a capability. Removing the branch entirely is the effects
model in ADR-0033, not this card.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.sandbox.base import SandboxAdapter
from openfactory.adapters.sandbox.registry import BOXES, box_traits, build_sandbox

# ── it is an axis like the other eight ──────────────────────────────────────────────────────────

def test_the_axis_dispatches_through_a_table():
    assert isinstance(BOXES, dict) and BOXES


def test_every_box_the_platform_has_is_registered():
    assert {"worktree", "container", "fargate"} <= set(BOXES)


@pytest.mark.parametrize("kind", ["nope", "docker", "", "FARGATE_TYPO"])
def test_an_unknown_kind_raises_naming_what_is_supported(kind):
    """ADR-0022 §1. Falling back would run the job somewhere nobody chose and report clean numbers
    for the wrong thing."""
    with pytest.raises(ValueError, match="unknown box"):
        box_traits(kind)
    with pytest.raises(ValueError, match="unknown box"):
        build_sandbox(kind)


def test_the_error_names_the_known_kinds():
    with pytest.raises(ValueError) as e:
        box_traits("nope")
    assert "container" in str(e.value) and "fargate" in str(e.value)


@pytest.mark.parametrize("kind", ["worktree", "container"])
def test_a_local_box_builds_something_that_satisfies_the_contract(kind, tmp_path):
    assert isinstance(build_sandbox(kind, root=tmp_path, image="x"), SandboxAdapter)


def test_a_remote_box_has_no_local_adapter_to_build(tmp_path):
    """Fargate is not a `SandboxAdapter` and pretending otherwise is what hid this for months: the
    launcher runs the whole job inside the task. Asking for one must say so, not return a lie."""
    with pytest.raises(ValueError, match="remote"):
        build_sandbox("fargate", root=tmp_path)


# ── the traits the lifecycle actually asks about ────────────────────────────────────────────────

@pytest.mark.parametrize("kind,remote", [("worktree", False), ("container", False),
                                         ("fargate", True)])
def test_remote_says_whether_the_worker_can_see_the_box(kind, remote):
    assert box_traits(kind).remote is remote


@pytest.mark.parametrize("kind,idempotent", [("worktree", False), ("container", False),
                                             ("fargate", True)])
def test_idempotent_says_whether_re_running_is_safe(kind, idempotent):
    """Not a synonym for `remote`, even though today they coincide. Fargate is retryable because
    the launcher RE-ATTACHES to a running task and reconciles a finished one; the local path
    re-invokes the agent and duplicates tracker comments. A future remote box without re-attach
    would be remote and NOT idempotent, and conflating the two would silently start retrying it."""
    assert box_traits(kind).idempotent is idempotent


def test_the_two_traits_are_independent():
    """Asserted directly so nobody later 'simplifies' one into the other.

    `honours_image` joined them (ADR-0037 D4) and is required POSITIONALLY on purpose: a new box
    must answer whether `box.image` can take effect in it, because the alternative — a default —
    is how `worktree` came to ignore the declaration in silence while being the CLI's default.
    `streams` joined on the same terms (C-39, #82): whether a caller can read the box's output
    WHILE the command runs, or only after the process dies. `isolates_resources` joined on the
    same terms again (#106): whether the box bounds anything beyond the code state, which is what
    decides whether a durable job — an agent running on the worker itself — may use it. It
    replaced a literal `!= "fargate"`, and the SSH runner below is exactly why: it isolates, and
    it is not Fargate. This runner is the case the traits were kept independent for — remote, not
    idempotent, blind, isolating — and it would have to answer each for itself rather than
    inherit an assumption from the word "remote". `transfers_state` joined on the same terms
    (#118): whether a paused session can be taken out of the box and put back into the next one,
    which is what decides whether a rate-limit pause costs a second agent pass. The SSH runner
    answers True there while being remote and blind — three traits, three different answers, from
    one box."""
    from openfactory.adapters.sandbox.registry import BoxTraits

    hypothetical = BoxTraits(name="ssh", remote=True, honours_image=True,
                             idempotent=False, streams=False, isolates_resources=True,
                             transfers_state=True)
    assert hypothetical.remote and not hypothetical.idempotent
    assert hypothetical.isolates_resources and not hypothetical.streams
    assert hypothetical.transfers_state, (
        "remote does not imply unreachable state — an SSH runner can `scp` a session back")


def test_traits_are_a_pure_lookup(monkeypatch):
    """It is called from inside a Temporal workflow body, which must be deterministic: no I/O, no
    clock, no environment. A trait that read `os.environ` would replay differently on a worker
    started with a different configuration."""
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "worktree")
    monkeypatch.setenv("OPENFACTORY_FARGATE_CLUSTER", "x")
    assert box_traits("fargate").remote is True
    monkeypatch.delenv("OPENFACTORY_FARGATE_CLUSTER")
    assert box_traits("fargate").remote is True


# ── the lifecycle stops naming a vendor ─────────────────────────────────────────────────────────

def test_the_workflow_body_names_no_provider():
    """The reachability guard for the whole card. Everything above can pass while `workflow.py`
    still branches on the string — which is the state this found."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parent.parent / "openfactory/runtime/temporal/workflow.py"
    offenders = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(src.read_text().splitlines(), 1)
        if '"fargate"' in line and not line.strip().startswith("#")
    ]
    assert not offenders, (
        "the lifecycle still names a box provider — 'where a job runs' is an engine concern "
        "(docs/core/02 E4, ADR-0033 §5):\n  " + "\n  ".join(offenders)
    )


def test_the_composition_root_dispatches_rather_than_branching():
    """`factory.py` chose with a ternary: `ContainerSandbox(...) if kind == "container" else
    WorktreeSandbox(...)` — which silently gave a worktree for ANY unknown kind, including a typo,
    and a worktree isolates only the code state. Untrusted work in a non-sandbox, from a typo."""
    import inspect

    from openfactory import factory

    src = inspect.getsource(factory.build_runner)
    assert "build_sandbox" in src
    assert 'sandbox == "container"' not in src
