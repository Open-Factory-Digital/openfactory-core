"""The published map describes a BRANCH, and until now only a merge could refresh it.

`KnowledgeRefreshInput`'s own docstring says what the refresh is about — *"the refresh is about the
BASE BRANCH's new state, not about one ticket"* — and exactly one thing acted on that sentence:
`JobWorkflow._refresh_knowledge`, reached from `result.state == JobState.MERGED` and from nowhere
else. So on `merge_policy: human` — the platform's own default, and what a pilot actually runs — a
job ends at `PR_OPEN`, the refresh never fires, and the bundle a client's NEXT ticket reads stays
as old as the last thing somebody happened to merge. A description of `main` was a hostage of one
ticket's outcome.

THE FIX IS A SCHEDULE, AND THE MERGE TRIGGER STAYS. After a merge the worktree is already there
and the map is already known to be behind, so it remains the cheapest moment to refresh — it just
stops being the only one. Both halves are asserted here, because removing either one is a change
somebody could make while believing they were simplifying.

AND THE SEAM THIS FILE EXISTS FOR. A Schedule starts a workflow BY STRING NAME
(`ScheduleActionStartWorkflow("KnowledgeRefreshWorkflow", ...)`). A name that does not match a
registered workflow type fails at RUN time, every tick, for ever — and a schedule whose runs all
fail looks exactly like a schedule over a quiet repository. Nothing in this codebase checked that
seam for any workflow; the guard below derives both sides from the source rather than keeping a
list somebody has to remember.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

_WORKFLOW_FILES = (
    Path("openfactory/runtime/temporal/workflow.py"),
    Path("openfactory/runtime/temporal/poller.py"),
)
_WORKER = Path("openfactory/runtime/temporal/worker.py")
_SCHEDULE = Path("openfactory/runtime/temporal/schedule.py")


def _defined_workflows() -> set[str]:
    """Every class carrying `@workflow.defn`. Derived from source — a hand-kept list here would be
    the same class of bug one level up, which `test_schedules_are_reachable.py` says in as many
    words about its own."""
    out: set[str] = set()
    for path in _WORKFLOW_FILES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and any(
                    "workflow.defn" in ast.unparse(d) for d in node.decorator_list):
                out.add(node.name)
    return out


def _registered_workflows() -> set[str]:
    """The names in the worker's `workflows=[...]`."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(_WORKER.read_text(encoding="utf-8"))):
        if isinstance(node, ast.keyword) and node.arg == "workflows" and isinstance(
                node.value, ast.List):
            out |= {e.id for e in node.value.elts if isinstance(e, ast.Name)}
    return out


def _scheduled_workflow_names() -> set[str]:
    """Every workflow a Schedule starts, read off the string literal it is started by."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(_SCHEDULE.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "ScheduleActionStartWorkflow"
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            out.add(node.args[0].value)
    return out


def test_every_scheduled_workflow_name_is_a_workflow_that_exists():
    """THE SEAM. A schedule names its workflow as a STRING; a typo, a rename, or a workflow that
    was never registered fails at run time on every tick and is invisible in a green suite — and
    on the panel it reads as a watcher that has nothing to say, not as one that cannot run."""
    registered = _registered_workflows()

    unknown = sorted(n for n in _scheduled_workflow_names() if n not in registered)

    assert not unknown, (
        f"these schedules start workflows the worker does not register: {unknown}. Every tick "
        f"would fail with an unregistered type, for ever, and quietly — register them in "
        f"`worker.py`'s `workflows=[...]` or fix the name in `schedule.py`.")


def test_every_workflow_the_platform_defines_is_registered_on_the_worker():
    """The wider half of the same defect: a workflow written and imported but left out of the
    worker's list is invisible until something invokes it. `test_temporal_workflow.py` makes this
    claim for ACTIVITIES against a hand-kept list of names; this one derives both sides."""
    unregistered = sorted(_defined_workflows() - _registered_workflows())

    assert not unregistered, (
        f"workflows defined and never registered on the worker: {unregistered}. Anything that "
        f"starts one — a schedule, an action, another workflow — fails with an unregistered type.")


def test_the_map_has_a_refresh_that_no_merge_gates():
    """The thesis. Before this, `_refresh_knowledge` under `JobState.MERGED` was the only publisher,
    so a `merge_policy: human` project's map could age indefinitely."""
    from openfactory.runtime.temporal import schedule as sched

    assert hasattr(sched, "ensure_okf_refresh"), "the scheduled refresh is gone"
    assert sched.OKF_SCHEDULE_PREFIX, "the refresh schedule has no id prefix to reconcile by"
    assert "KnowledgeRefreshWorkflow" in _scheduled_workflow_names(), (
        "nothing schedules the knowledge refresh any more — the map is back to waiting for a merge")


def test_the_merge_still_refreshes_the_map():
    """AND THE OTHER HALF, because a schedule is not a reason to drop the cheapest trigger. After a
    merge the worktree is already there and the map is already known to be behind. Removing this
    would look like simplification and would cost every project the freshest refresh it gets."""
    workflow_src = _WORKFLOW_FILES[0].read_text(encoding="utf-8")
    tree = ast.parse(workflow_src)

    merged_branches = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.If) and "JobState.MERGED" in ast.unparse(n.test)
        and "_refresh_knowledge" in ast.unparse(n)]

    assert merged_branches, (
        "no branch refreshes the knowledge map on merge any more — the schedule was meant to be a "
        "SECOND trigger, not a replacement for the one that runs when the tree is already there")


def test_the_refresh_skips_a_disabled_project():
    """A disabled project's floor is deliberately off. Refreshing a map nobody will read is work
    nobody asked for — the same reasoning `ensure_techlead_watch` records for its own rounds.

    AST rather than a substring, because the docstring explains the gate it is asserted to have."""
    from openfactory.runtime.temporal import schedule as sched

    tree = ast.parse(textwrap.dedent(inspect.getsource(sched.ensure_okf_refresh)))
    reads = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}

    assert "enabled" in reads, "a disabled project now gets a refresh schedule it will never use"


def test_a_tick_that_overlaps_the_previous_one_is_dropped():
    """SKIP, like every other schedule here. A refresh clones and walks a repository; a big one on
    a slow disk can outlast its own interval, and queuing those turns a slow repository into a
    backlog that never drains."""
    from temporalio.client import ScheduleOverlapPolicy

    from openfactory.runtime.temporal import schedule as sched

    built = sched._okf_schedule("demo", sched.OKF_EVERY_HOURS)

    assert built.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert built.action.execution_timeout is not None, (
        "an unbounded run under SKIP stops the schedule for ever the first time one hangs")


def test_an_orphaned_refresh_schedule_is_retired_like_its_neighbours():
    """`retire_orphan_schedules` deletes per-project schedules whose project is gone. A prefix
    missing from its list is a schedule that fires for ever for a project this deployment does not
    have — which is the exact live defect that function was written for, and adding a third
    per-project schedule without adding its prefix reintroduces it."""
    from openfactory.runtime.temporal import schedule as sched

    tree = ast.parse(textwrap.dedent(inspect.getsource(sched.retire_orphan_schedules)))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}

    assert "OKF_SCHEDULE_PREFIX" in names, (
        "the refresh schedule's prefix is not retired with the others — a removed project keeps a "
        "refresh firing against a registry that no longer has it")
