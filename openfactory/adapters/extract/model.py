"""The model a document is read with, when a parser cannot read it (#269 slice 1).

THE REPO'S OWN MODEL SEAM, NOT A NEW ONE. The vision row and the record's summary reach a model
the way the evaluation battery's judge does (#266, `product/evaluation/run.py`): the RAW judging
harness of a role (`adapters/agent/registry.py::build_asker`), asked a read-only prompt in a room
of its own through `ask()`. So the harness and the model are the role's configuration — its
`harness:` and `model:` lines — and a deployment that swaps them swaps nothing here.

WHICH ROLE: THE REVIEWER'S, OR A DECLARED ONE. The reviewer is the platform's independent reader
of somebody else's work, on an axis of its own, which is the battery's reason too. A deployment
that wants documents read by another engine names a role — shipped or an add-on's `role.<name>`
— in `OPENFACTORY_DOCUMENTS_ROLE`, and that role's harness and model read them.

A ROOM WITH ONE FILE IN IT. The harness stands in a scratch directory holding the document it is
asked about and nothing else, and it is asked read-only. What it answers is a model's, and every
record says so (`contracts/document.py::Derived`).

NEVER A LIVE CALL FROM THE SUITE. With no harness handed in, the one here is built from this
deployment's configuration, which spends tokens — so inside pytest it is not built, and the row or
step records why, like any other model it could not reach.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("openfactory.extract")

#: The variable that names the role documents are read with, and the role it names by default.
ROLE_ENV = "OPENFACTORY_DOCUMENTS_ROLE"
DEFAULT_ROLE = "reviewer"

#: What a room's checkout is called — a scratch directory is not a repository, and the harness
#: needs a branch name to be handed one.
_BRANCH = "main"


def role() -> str:
    return (os.environ.get(ROLE_ENV) or "").strip() or DEFAULT_ROLE


def _under_test() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def asker(project) -> tuple[object | None, str]:
    """`(harness, "")` — the configured role's raw judging harness — or `(None, why)`."""
    if _under_test():
        return None, ("no model is called inside the test suite — hand the row or the step a "
                      "harness of its own")
    try:
        from openfactory.adapters.agent.registry import build_asker

        return build_asker(project, role=role()), ""
    except Exception as exc:  # noqa: BLE001 — an unconfigured model is a reason, never a crash
        return None, f"no model can read documents on this deployment ({str(exc)[:200]})"


def described(harness, project) -> str:
    """`harness/model` of what answered — the configuration it was built from, or what a harness
    handed in says of itself."""
    name = str(getattr(harness, "name", "") or "")
    model = str(getattr(harness, "model", "") or "")
    if not name:
        try:
            from openfactory.adapters.agent.registry import harness_kind, model_for

            name, model = harness_kind(project, role()), model_for(project, role()) or ""
        except Exception as exc:  # noqa: BLE001 — a description is a label, never a reason to fail
            log.info("the documents role's harness could not be described (%s) — labelled by "
                     "its class", exc)
            name = type(harness).__name__
    return f"{name}/{model or 'default'}"


def ask(harness, project, room: Path, prompt: str, *, phase: str) -> tuple[str | None, str]:
    """`(text, "")` — the model's whole answer — or `(None, why)`. Read-only, in `room`."""
    from openfactory.adapters.agent.base import final_text
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.adapters.sandbox.registry import judging_worktree

    try:
        res = harness.ask(sandbox=judging_worktree(project, root=room),
                          workspace=Workspace(path=room, branch=_BRANCH, base_branch=_BRANCH),
                          prompt=prompt, phase=phase)
    except Exception as exc:  # noqa: BLE001 — a harness that raised is a model that did not answer
        return None, f"the model did not answer ({str(exc)[:200]})"
    if not getattr(res, "ok", False):
        said = str(getattr(res, "summary", "") or "")[:200]
        return None, f"the model did not answer ({said or 'no reason given'})"
    text = (final_text(res) or "").strip()
    return (text, "") if text else (None, "the model answered with nothing")
