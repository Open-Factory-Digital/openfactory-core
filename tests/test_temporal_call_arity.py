"""Every call into the Temporal client must fit the SDK's real signature.

THE BUG THIS EXISTS FOR. The tech-lead's rounds resumed a self-healing park with

    await handle.signal("act_on_impediment", "resume", "")

`WorkflowHandle.signal` is `(signal, arg=UNSET, *, args=[], ...)` — `args` is KEYWORD-ONLY, so the
third positional is a TypeError raised before anything reaches the server. The tech-lead's single
remediation, the one ADR-0020 is built on, failed on every attempt in every deployment. It was
invisible for two reasons at once: the handler logged no exception, and every unit test drove a
fake handle, which accepts any arguments you like.

That is the lesson worth encoding. A mock cannot fail an arity check, so tests written against
mocks prove the LOGIC and say nothing about whether the call is even callable. This binds each call
site against the genuine `inspect.signature`, which is the part a fake can never stand in for.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from temporalio import workflow as temporal_workflow
from temporalio.client import Client, WorkflowHandle

#: attribute name → the real callable whose signature it must fit. `execute_activity` and
#: `create_schedule` joined after a reviewer pointed out they sat outside the guard — the same
#: keyword-only trap (`args=[...]`) exists on the activity API, and a schedule call with the
#: wrong shape fails only at the moment a deploy tries to reconcile it.
_CHECKED = {
    "signal": WorkflowHandle.signal,
    "query": WorkflowHandle.query,
    "start_workflow": Client.start_workflow,
    "execute_workflow": Client.execute_workflow,
    "execute_activity": temporal_workflow.execute_activity,
    "create_schedule": Client.create_schedule,
}


def _call_sites():
    """(file, line, method, positional count, keyword names) for every checked call in sdlc/."""
    for path in sorted(Path("openfactory").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None)
            if name not in _CHECKED:
                continue
            if any(isinstance(a, ast.Starred) for a in node.args):
                continue  # *args — nothing static to check
            kwargs = [k.arg for k in node.keywords if k.arg]
            if any(k.arg is None for k in node.keywords):
                continue  # **kwargs — same
            yield str(path), node.lineno, name, len(node.args), kwargs


def test_there_are_call_sites_to_check():
    """A guard that silently checks nothing is the failure mode one level up."""
    assert list(_call_sites()), "no Temporal call sites found — the scan is broken"


@pytest.mark.parametrize("site", list(_call_sites()), ids=lambda s: f"{s[0]}:{s[1]}")
def test_the_call_fits_the_real_sdk_signature(site):
    path, line, name, n_pos, kwargs = site
    sig = inspect.signature(_CHECKED[name])
    # `self` is bound at the call site (handle.signal(...)) — but only for METHODS. Stand in for
    # it only when the signature actually starts with one: `workflow.execute_activity` is a free
    # function, and blindly prepending a self made every valid two-positional call site "fail".
    takes_self = next(iter(sig.parameters), None) == "self"
    try:
        sig.bind(*((["<self>"] if takes_self else []) + ["<arg>"] * n_pos),
                 **{k: "<v>" for k in kwargs})
    except TypeError as exc:
        pytest.fail(
            f"{path}:{line} calls .{name}() in a way the Temporal SDK rejects: {exc}\n"
            f"Real signature: {name}{sig}\n"
            f"Passing more than one value usually means `args=[...]` (keyword-only), not extra "
            f"positionals."
        )


def test_the_check_would_actually_catch_the_original_bug():
    """The exact call that shipped, asserted to be rejected — so this guard cannot rot into a
    tautology that passes whatever the signature happens to be."""
    sig = inspect.signature(WorkflowHandle.signal)
    with pytest.raises(TypeError):
        sig.bind("<self>", "act_on_impediment", "resume", "")
    # and the corrected shape binds cleanly
    sig.bind("<self>", "act_on_impediment", args=["resume", ""])
