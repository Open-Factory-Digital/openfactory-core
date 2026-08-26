"""The message a human actually needs, out of an exception chain that hides it.

WHY THIS EXISTS (#66). `str(ActivityError)` is the fixed string `"Activity task failed"`. Every
exception raised inside a Temporal activity arrives at the workflow wearing it, and the workflow's
catch-all writes that string into the park note a human reads:

    job errored after retries: Activity task failed

The real message is in `__cause__` — an `ApplicationError` carrying the original type and text.
So the platform's headline invariant (*no stall is silent*) held in form and failed in substance:
the operator is told a job stopped and handed three words they cannot act on. Worse, it silently
undoes deliberate diagnostic work upstream — `SetupFailed` carries the failing command and its
output tail so that a `dotnet restore` 401 is diagnosable in one read, and `resolve_box_image`'s
refusal exists solely to say a sentence instead of shrugging. Both are replaced by "Activity task
failed" the moment they cross an activity boundary.

NOT TEMPORAL-SPECIFIC, deliberately. The same shape appears wherever a framework wraps: an
`ExceptionGroup` from a task group, a `RetryError`, a driver exception re-raised as a generic
`OperationalError`. The placeholder list below is data, and adding a row is how the next wrapper
gets handled — not another `if isinstance(...)` at a call site that will not exist yet.

WALKS `__cause__` AND `__context__`, in that order per link. `raise X from Y` sets `__cause__` and
is the explicit signal; `__context__` is what Python sets when an exception is raised *during*
handling of another, which is how several wrappers in this codebase actually chain. Reading only
one of them meant reading the wrong one about a third of the time.
"""

from __future__ import annotations

#: Messages that carry no information — a wrapper's fixed string, or nothing at all. Compared
#: case-insensitively against the stripped text, and matched EXACTLY: a real message that merely
#: contains one of these ("activity task failed after 3 attempts: 401 from nuget.org") is the
#: informative one and must survive.
PLACEHOLDERS = frozenset({
    "activity task failed",
    "workflow task failed",
    "child workflow task failed",
    "workflow execution failed",
    "activity task cancelled",
    "activity task canceled",
    "cancelled",
    "canceled",
    "none",
    "unknown error",
})

#: How far down a chain to look. A cycle is already impossible (`_chain` tracks what it has seen);
#: this bounds the pathological case of a very deep wrap, because this runs on an error path where
#: taking a long time is its own failure.
_MAX_DEPTH = 12


def _chain(exc: BaseException):
    """`exc`, then everything it was caused by or raised during — each link exactly once.

    The `seen` set is not defensive decoration. `__context__` genuinely forms cycles: catching an
    exception inside its own `except` block and re-raising the original produces `a.__context__ is
    b` and `b.__context__ is a`, and this function runs while something is already going wrong,
    which is the worst possible moment to hang."""
    seen: set[int] = set()
    queue: list[BaseException] = [exc]
    while queue and len(seen) < _MAX_DEPTH:
        current = queue.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        # `__cause__` first: `raise X from Y` is somebody stating the reason on purpose.
        for nxt in (current.__cause__, current.__context__):
            if nxt is not None and id(nxt) not in seen:
                queue.append(nxt)


def _informative(exc: BaseException) -> str:
    text = str(exc).strip()
    return "" if not text or text.lower() in PLACEHOLDERS else text


def first_message(exc: BaseException, *, limit: int = 300) -> str:
    """The first message in the chain that says something, capped. Never empty, never raises.

    Falls back to the outermost exception's TYPE NAME when the whole chain is placeholders —
    `ActivityError` alone is still more than `Activity task failed`, because a type name tells the
    reader which layer gave up. It never returns `""`: a caller interpolating this into a park note
    would then produce "job errored after retries:" with nothing after the colon, which reads as a
    truncation bug rather than as a missing cause and sends somebody hunting the wrong thing."""
    for link in _chain(exc):
        text = _informative(link)
        if text:
            return _cap(text, limit)
    return _cap(type(exc).__name__, limit)


def describe(exc: BaseException, *, limit: int = 300) -> str:
    """`Type: message` — for a note where the reader has no other clue what layer failed.

    Separate from `first_message` because the two have genuinely different readers. A panel that
    already renders "the durable engine is unreachable" wants the message alone; a park note
    written days before anybody opens it wants the type, because `ValueError` and `TimeoutError`
    send an operator to entirely different places."""
    for link in _chain(exc):
        text = _informative(link)
        if text:
            return _cap(f"{type(link).__name__}: {text}", limit)
    return _cap(type(exc).__name__, limit)


def _cap(text: str, limit: int) -> str:
    text = " ".join(text.split())  # a stack-trace-shaped message collapses to one line
    return text if len(text) <= limit else text[: max(1, limit - 1)].rstrip() + "…"


def scrubbed(exc: object, *secrets: str, limit: int = 120) -> str:
    """`str(exc)`, with every given secret replaced and THEN truncated — in that order.

    THE ORDER IS THE FIX (adversarial review, 2026-08-04): a failed `git clone` raises
    CalledProcessError, whose text embeds the full command — including the
    `https://x-access-token:<live token>@github.com/...` URL — and the token sits well inside
    the first 120 characters, so `str(exc)[:120]` published a live GitHub App credential into
    the worker's own log stream on every clone failure. Truncation is not redaction."""
    text = str(exc)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text[:limit]
