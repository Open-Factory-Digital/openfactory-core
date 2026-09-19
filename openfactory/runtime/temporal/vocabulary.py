"""The engine's own words, importable WITHOUT the engine's client (#178).

THREE NAMES, ONE DEFINITION EACH, AND NO `temporalio` ON THE WAY TO THEM. Which states need a
person, the `action.kind` a job carries while its pull request waits, and the sentence that says
what that wait is on are decided by the durable half — and read by surfaces that must serve
without it: the panel's page renders all three, the tech-lead's snapshot reads the second, and the
attention bar counts the first.

THEY LIVED BESIDE THE CODE THAT PRODUCES THEM, in `view.py` and `workflow.py`, which both import
`temporalio` at the top. So the page paid for the engine's client to read three literals, and an
install made without the `runtime` extra had a panel process that was up and a page that was not.
Measured on `main` at `1512d0a`, the app served through `TestClient` with `temporalio` made
unimportable and a local project registered, every GET route asked once: **12 of 41** answered 500
with `ModuleNotFoundError: No module named 'temporalio'` — `/` and every other page route
(`/p/…`, `/logs…`, `/product/…`), `/api/floor` and `/api/attention` — while three modules said in
their docstrings that the panel is built to serve without that extra. With this module in place
the same sweep answers no 500.

`view.py` and `workflow.py` IMPORT THESE FROM HERE, so `tv.ATTENTION_STATES`, `tv.MERGE_WAIT` and
`workflow.merge_wait_note` are still the names every other caller already uses; what changed is
which of the modules is safe to import. The one hand copy that existed for exactly this reason
(`techlead/conversation.py::_MERGE_WAIT_KIND`, "spelled here because importing
`runtime.temporal.view` costs `temporalio`") is now bound to the definition instead.

KEEP THIS MODULE FREE OF ENGINE IMPORTS — of `temporalio`, and of any sibling that imports it
(`view`, `workflow`, `activities`, `connection`, `schedule`, `poller`, `worker`).
`tests/test_the_panel_serves_without_the_engines_client.py` holds that line: it imports the app
and the floor in an interpreter where `temporalio` cannot be found, and asks every GET route.
"""

from __future__ import annotations

# The DOMAIN outcome (merged / needs_refinement / on_hold / paused / awaiting_approval /
# failed) is what an operator actually needs — the raw Temporal status can't tell a clean
# merge from a needs-refinement (both "completed"). These are the ones that wait for a person.
ATTENTION_STATES = {
    "failed", "needs_refinement", "on_hold", "blocked", "paused", "awaiting_prod_approval",
    "awaiting_your_merge",  # the PR is ready and only the OPERATOR's merge advances the queue
}

#: The `action.kind` a job carries while its pull request waits for a person.
#:
#: THREE SURFACES READ THIS ONE STRING and they must never disagree about it: the panel paints the
#: `Merge · Adjust… · Discard` row from it, the chat decides from it which job a typed "merge" is
#: about, and the attention bar counts it. It is a constant here, reached by the only line that
#: produces it (`view.py`), because a second spelling would not fail — it would quietly mean
#: "nothing is waiting", which is a sentence every one of those surfaces is willing to say.
MERGE_WAIT = "merge_wait"

#: What the worker half of the deployment calls itself when it announces its build (#135). The
#: panel reads it back off the shared state volume, and `openfactory doctor` reads it to say which
#: half runs a different build — by importing `worker.py`, until the static sweep of #178 found it:
#: one string, at the price of `temporalio`. `worker.WORKER_ROLE` is still the worker's name for it.
WORKER_ROLE = "worker"


def merge_wait_note(auto: bool) -> str:
    """What the standing PR wait is ON, in the engine's own words — ONE definition (#148).

    The merge loop is shared by both paths, and for a long time so was this sentence: a PR on the
    HUMAN path was told "waiting for CI / the merge" to a reader who *was* the wait. Naming the
    wrong blocker is worse than naming none — it sends somebody to wait out a build that already
    finished. Pure, so the guard can read it straight rather than driving the engine."""
    return "waiting for CI / the merge" if auto else "waiting for your review and merge"
