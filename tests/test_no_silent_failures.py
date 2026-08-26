"""No failure disappears without a trace.

The house invariant says a stall must either self-heal or ask a human. It says nothing about the
third case, which is the one that actually happened: a failure that does neither and is simply
swallowed. On 2026-07-26 the only Slack alert for a parked job lived inside a `try` whose `except`
was a bare `pass`; the operation failed, nothing was written anywhere, and #478 sat unmentioned for
eighteen hours while the floor was held.

Swallowing is often RIGHT — a broken notifier must not fail a job, a malformed line must not stop a
replay. What is never right is doing it silently. This test pins that: an exception may be handled
however the situation deserves, but something must be able to find out it happened.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: What counts as SAYING something. Deliberately narrow: an earlier version counted a bare
#: `return`/`continue`, which passed 42 handlers that returned `None`, `[]` or `{}` after
#: swallowing a failure — the caller then cannot tell "nothing there" from "could not look".
#: A handler now qualifies one of two ways: it says something here, or it names the exception in
#: what it returns (checked separately, on the `as exc` binding).
#: What counts as leaving a trace. `RunResult(`/`WriteResult(`/`Finding(` are here because building
#: a result that CARRIES the failure forward is louder than a log line, not quieter: a RunResult with
#: ON_HOLD parks the ticket, names the exception in the note, and puts it on Slack and the panel.
#: What counts as SAYING something. Deliberately narrow: an earlier version counted a bare
#: `return`/`continue`, which passed 42 handlers that returned `None`, `[]` or `{}` after
#: swallowing a failure — the caller then cannot tell "nothing there" from "could not look".
#: A handler now qualifies one of two ways: it says something here, or it names the exception in
#: what it returns (checked separately, on the `as exc` binding).
#: What counts as leaving a trace. Not only logging: raising, returning a value the caller reports,
#: recording a finding or emitting a journal line all keep the failure visible.
_SPEAKS = (
    "log.", "logger", "logging", "print(", "activity.logger", "workflow.logger",
    "raise", "_emit", "notify",
)


def _is_catch_all(node: ast.ExceptHandler) -> bool:
    """Whether this handler catches ANYTHING, rather than one condition it expects.

    Naming the exception is itself a statement: `except ScheduleAlreadyRunningError` followed by an
    update is the idempotent path, and `except TypeError` followed by the old call signature is a
    compatibility branch. Neither is a failure being swallowed. `except Exception` is different —
    it catches the expected condition AND everything nobody thought of, and that second half is
    where a real fault disappears."""
    if node.type is None:
        return True
    names = [node.type] if not isinstance(node.type, ast.Tuple) else list(node.type.elts)
    return any(getattr(n, "id", "") in ("Exception", "BaseException") for n in names)


#: The one way to be silent on purpose. Written in the source, next to the handler, so the claim
#: "this is not a failure" is argued where a reviewer reads it rather than in a list somewhere else
#: that nobody revisits. Allowlists rot; a sentence beside the code is re-read every time it moves.
#:
#: Reserved for handlers where the exception is EXPECTED CONTROL FLOW — a JSON stream carries
#: non-JSON lines by design, and skipping them is parsing, not error handling. It is not a way to
#: quiet a failure somebody would rather not deal with.
_DELIBERATE = "# not-a-failure:"


def _silent_handlers() -> list[str]:
    out: list[str] = []
    for path in sorted(Path("openfactory").rglob("*.py")):
        try:
            source = path.read_text()
            tree = ast.parse(source)
        except SyntaxError:  # pragma: no cover — a file that will not parse fails elsewhere
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or not _is_catch_all(node):
                continue
            body = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
            if any(token in body for token in _SPEAKS):
                continue
            # OR it carries the exception onward — `return degrade(f"manifest: {exc}")` and
            # `return ProductAnswer(ok=False, error=str(exc))` hand the reason to a caller whose
            # job is to report it, which is louder than a log, not quieter. The test for this is
            # the BINDING: a handler that never names the exception cannot be passing it on.
            if node.name and node.name in body:
                continue
            span = "\n".join(lines[node.lineno - 1: (node.end_lineno or node.lineno)])
            if _DELIBERATE in span:
                continue
            out.append(f"{path}:{node.lineno}")
    return out


def test_no_exception_is_swallowed_without_a_trace():
    """A bare `except: pass` is a failure that never happened as far as anybody can tell.

    If this fails, the fix is not to widen `_SPEAKS`. It is to decide what should happen when that
    operation fails and say so — a warning naming what was being attempted, or a returned value the
    caller reports. "It is only best-effort" is the reason to log, not the reason not to."""
    silent = _silent_handlers()
    assert silent == [], (
        "these swallow an exception with no trace at all:\n  " + "\n  ".join(silent))


def test_the_detector_would_actually_catch_one():
    """A guard nobody can fail is not a guard."""
    tree = ast.parse("try:\n    x()\nexcept Exception:\n    pass\n")
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    body = ast.unparse(ast.Module(body=handler.body, type_ignores=[]))
    assert _is_catch_all(handler)
    assert not any(token in body for token in _SPEAKS)


def test_a_NAMED_exception_taking_a_defined_branch_is_not_a_swallow():
    """`except ScheduleAlreadyRunningError: update_it()` is the idempotent path, not a failure
    disappearing. Requiring a log there would teach people to add noise to pass a test."""
    tree = ast.parse("try:\n    x()\nexcept KeyError:\n    y = 1\n")
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    assert not _is_catch_all(handler)


def test_the_token_pool_says_when_it_falls_back_to_ONE_credential():
    """The find that made this sweep worth doing. A typo in `OPENFACTORY_AGENT_TOKENS` left a deployment
    with a single credential and no failover, looking exactly like one that never configured a pool
    — until the day that credential failed and there was nothing to rotate to."""
    src = Path("openfactory/adapters/agent/claude_code.py").read_text()
    block = src[src.index("OPENFACTORY_AGENT_TOKENS"):][:2000]
    assert "no failover" in block
    assert "log.warning" in block


def test_the_cleanup_that_leaves_a_task_BILLING_is_never_silent():
    """A cleanup that did not run leaves a Fargate task alive with nothing watching it. Best-effort
    is the right behaviour; silent is not, because the cost is real and ongoing."""
    src = Path("openfactory/runtime/temporal/workflow.py").read_text()
    block = src[src.index("CLEANUP FAILED"):][:400]
    assert "billing" in block


def test_a_bare_fallback_without_the_exception_is_NOT_a_trace():
    """The rule that matters, asserted directly.

    An earlier version of this guard counted a bare `return` as speaking, which passed 42 handlers
    that returned `None`, `[]` or `{}` after swallowing a failure. The caller then cannot tell
    "there was nothing there" from "I could not look" — and in this system those two answers send
    the factory in opposite directions: an unreadable board became "TO-DO is empty", so the
    tech-lead's idle-floor finding could never fire."""
    tree = ast.parse("try:\n    x()\nexcept Exception:\n    return []\n")
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    body = ast.unparse(ast.Module(body=handler.body, type_ignores=[]))
    assert not any(token in body for token in _SPEAKS)
    assert handler.name is None, "nothing was bound, so nothing could have been passed on"


def test_carrying_the_exception_onward_DOES_count():
    """`return degrade(f"manifest: {exc}")` hands the reason to a caller whose job is to report it
    — louder than a log, not quieter."""
    tree = ast.parse("try:\n    x()\nexcept Exception as exc:\n    return degrade(str(exc))\n")
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    body = ast.unparse(ast.Module(body=handler.body, type_ignores=[]))
    assert handler.name and handler.name in body


def test_deliberate_silence_must_be_argued_in_the_source():
    """`# not-a-failure:` is the only exemption, and it lives beside the handler on purpose: an
    allowlist in a test file is a claim nobody re-reads when the code moves."""
    exempt = []
    for path in sorted(Path("openfactory").rglob("*.py")):
        if _DELIBERATE in path.read_text():
            exempt.append(str(path))
    # Small and reviewable, or the exemption has become a habit rather than an argument.
    assert len(exempt) <= 4, f"deliberate silence is spreading: {exempt}"


def test_the_workers_own_sink_call_actually_constructs(tmp_path, monkeypatch):
    """THE EXACT CALL `_metrics_sink()` makes, frozen. `_build`'s first parameter was named
    `table` — also a legitimate sink kwarg (the DynamoDB table name) — so this call died with
    "got multiple values for argument 'table'" for as long as the registry existed, and
    `messages.write`'s never-raise rule swallowed it: the panel's whole proactive voice, the
    coordinator's pickups, the park alerts — every message row — delivered to an exception.
    Found the first minute a PanelNotifier actually tried to speak (2026-08-05)."""
    from vendor_addons import install

    from openfactory.observability.registry import build_metrics_sink

    sink = build_metrics_sink("sqlite", table=None, path=str(tmp_path / "m.db"))
    assert sink is not None

    install(monkeypatch, "metrics.dynamodb")  # the vendor row is an add-on; installed for the call
    dynamo = build_metrics_sink("dynamodb", table="openfactory-job-metrics", path=None)
    assert getattr(dynamo, "table_name", "") == "openfactory-job-metrics"


def test_a_message_written_through_the_default_sink_lands(tmp_path, monkeypatch):
    """One level up, end to end: `messages.say` through `_metrics_sink()` — the path every
    coordinator announcement takes on a real worker."""
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "m.db"))
    from openfactory.memory import messages

    assert messages.say("demo", "o tech-lead fala e alguém ouve") is True
