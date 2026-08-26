"""A client's board carries the client's product — ADR-0027.

WHAT THIS EXISTS TO PREVENT, described from the wreckage. Eleven tickets whose only purpose was to
watch the pipeline move — "Add GET /heartbeat endpoint (live autonomy demo)", "(panel e2e test)",
"Add GET /autonomy endpoint (autonomy proof)" — went through planning, execution, review and merge,
and landed eleven constant-returning endpoints in a client's accounting product. `/healthz/ready`
answers `{"ready": true}` in production without touching a dependency, because we needed something
to watch a deploy with.

Nobody decided that. There was no field to consult and no gate to fail, so the question of whose
product was receiving the code was never asked once.

TWO CHOICES HERE ARE DELIBERATE.

**Declared, not inferred.** Test work is recognised by a LABEL somebody puts on it, never by
guessing from the title. `Project` already carries the reasoning in its own comments — what
somebody declares beats what the machine infers — and a title heuristic would do both wrong things:
miss a smoke ticket named like product work, and one day block a real ticket for containing the
word "demo".

**Refused where it is cheap.** At admission, before a workflow, a box, an agent pass or a merge.
A check that only fires after the merge is not a guard; it is a report about damage already done.
"""

from __future__ import annotations

import logging

log = logging.getLogger("openfactory.policy")

#: The label that marks a ticket as existing to exercise the factory rather than to build the
#: product. Put on deliberately — that act is the declaration.
TEST_WORK_LABEL = "factory-test"


def is_test_work(labels: list[str] | None) -> bool:
    """Whether these labels declare factory-test work. Case- and space-insensitive, because a
    label typed by a human in a web UI is not going to be canonical."""
    return any((x or "").strip().lower() == TEST_WORK_LABEL for x in (labels or []))


def refusal_for(project, issue: str, labels: list[str] | None) -> str:
    """"" when this ticket may run here, else WHY it may not, in one line for a log and a comment.

    A string rather than a boolean: a job that vanishes with no reason is the silent failure this
    codebase keeps paying for, and the person who labelled the ticket needs to be told which
    project would have accepted it.
    """
    if not is_test_work(labels):
        return ""
    if getattr(project, "accepts_test_work", False):
        return ""
    name = getattr(project, "name", "?")
    return (
        f"#{issue} is labelled `{TEST_WORK_LABEL}` and {name!r} does not accept test work. "
        f"A client's board carries the client's product (ADR-0027) — eleven smoke-test tickets "
        f"once shipped eleven dead endpoints into one. Run it against a project with "
        f"`accepts_test_work: true`, or drop the label if this is real product work."
    )


def admissible(project, issue: str, labels: list[str] | None) -> bool:
    """The gate itself. Logs the refusal loudly: a ticket that silently never starts is
    indistinguishable from a poller that stopped."""
    why = refusal_for(project, issue, labels)
    if not why:
        return True
    log.warning("REFUSED %s", why)
    print(f"OPENFACTORY_TEST_WORK_REFUSED: {why}", flush=True)
    return False
