"""The ONE event loop a process keeps for engine reads asked from a thread (GitHub issue #147).

WHO HAS NO LOOP OF THEIR OWN. `techlead/conversation.py::gather_jobs` is synchronous on purpose:
`techlead_ask` runs the whole answer on a worker thread (`asyncio.to_thread`), because answering
clones a repository, shells out and runs an agent process. To read the engine from there it opened
a loop of its own — `asyncio.run(_run())`, once per QUESTION.

WHY THAT WAS A LEAK AND NOT JUST A COST. `view.connect()` pools the read side's client keyed by the
loop that made it, and that part is right: a client handed to a loop that did not make it is a
broken read. So a fresh loop per question was a fresh client per question — and the installed
`temporalio` (1.32.0, re-checked 2026-09-18: `Client`, `ServiceClient` and the bridge client under
them expose no `close`, `aclose`, `shutdown`, `__aexit__` or `__del__`) has nothing to release one
with. Measured on a throwaway dev server, counting the process's established connections to the
engine's port after each `gather_jobs`:

    before:  1, 2, 3, 4, 5, 6
    after:   1, 1, 1, 1, 1, 1

It is #134 one layer down, on a human-scale clock instead of a poll tick.

SO THE LOOP OUTLIVES THE QUESTION, and the pool is left exactly as it is. A caller with no loop
runs its reads HERE, on one loop the process keeps, which makes the pool's key the same from one
question to the next. The other shape the issue names — the worker lends the gatherer its own
client — would thread a client through `answer()` and every front end that calls it, and would
hand the read side a client made by `connection.connect()`, the one-shot door `view.connect()`'s
docstring keeps apart from the pool on purpose.

NO ENGINE IMPORT HERE, deliberately: this file knows about loops and threads, not about Temporal,
so importing it costs a caller nothing it does not already have.

WHAT SHARES THE POOL WITH IT. In the worker, nothing: the worker's own loop connects through
`connection.connect()` and never reads through `view.connect()`. The panel reads through the pool
on its one loop and never runs the tech-lead (`actions/catalog.py::_ask` dispatches the question to
the worker). A process that read the engine from BOTH its own loop and this one would see the two
take turns emptying the pool — it holds one entry, total — and no process in this tree does.

AND ONE CALLER THAT IS NOT A READ (#201). `product/release.py::release` delivers a client's
production approval from a thread, in the worker AND in the panel, and it runs here for the reason
the gatherer does: it was a loop and a client per approval. It does NOT take the pool's client, and
the paragraph above is why — in the panel that would be exactly the process that reads from both
loops. Measured on a dev server, six approvals with the panel's loop re-reading after each: 13
clients opened through the pool, 2 with a client the release path keeps for itself.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass
class _Standing:
    loop: asyncio.AbstractEventLoop
    thread: threading.Thread


_STANDING: _Standing | None = None
#: The first question makes the loop, and the first TWO may arrive together — `techlead_ask` runs
#: each on its own pool thread.
_MAKING = threading.Lock()


def from_a_thread[T](read: Callable[[], Awaitable[T]]) -> T:
    """Run `read()` on the standing loop and hand its answer — or its exception — to the caller.

    `read` IS CALLED HERE, NOT BY THE CALLER, so a caller that is refused has made no coroutine
    for nobody to await.

    A CALLER THAT IS ITSELF RUNNING A LOOP IS REFUSED. Waiting here blocks the calling thread, and
    a blocked loop stalls everything it serves — in the worker, every activity. `asyncio.run`
    refused the same caller (it raises inside a running loop), so nothing that worked stops
    working; the sentence now says what to do instead.

    NO DEADLINE OF ITS OWN. Every engine read somebody waits for is already bounded where it is
    made (`view._within`, #159) and that bound runs on this loop as it did on the caller's. A
    second, outer number would be one more thing to disagree with the first.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "this thread is running an event loop, and waiting here for the engine would stall "
            "it — await the read directly, or call this from a worker thread "
            "(`asyncio.to_thread`)")
    loop = _the_loop()   # before `read()`: a loop that cannot be made leaves no coroutine behind
    return asyncio.run_coroutine_threadsafe(read(), loop).result()


def _the_loop() -> asyncio.AbstractEventLoop:
    global _STANDING

    with _MAKING:
        # A LOOP THAT ENDED IS REPLACED, not asked for ever. Nothing in this tree stops it, but a
        # `SystemExit` or `KeyboardInterrupt` raised inside a read ends `run_forever`, and every
        # question after that would be refused until somebody restarted the worker — with nothing
        # anywhere saying that is the remedy. The replacement is a new loop, so a new pool key and
        # one new client: a client per DEATH of the loop, not per question.
        if _STANDING is None or not _STANDING.thread.is_alive():
            loop = asyncio.new_event_loop()
            # A DAEMON, because it has no work of its own to finish: a read in flight when the
            # process exits is a read nobody is waiting for any more, and a thread that is not a
            # daemon would hold the worker open after its own shutdown had completed.
            thread = threading.Thread(target=_serve, args=(loop,), daemon=True,
                                      name="openfactory-engine-reads")
            thread.start()
            _STANDING = _Standing(loop=loop, thread=thread)
        return _STANDING.loop


def _serve(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    finally:
        # CLOSED, so a caller that raced the ending is REFUSED (`Event loop is closed`) instead of
        # handing a read to a loop that will never run it and waiting on the answer for ever.
        loop.close()


def _forget_the_standing_loop() -> None:
    """Stop the standing loop and forget it, so the next caller makes one. A seam for the suite,
    the way `view.reset_clients` is: a case that needs to BE the first caller forgets it first, and
    ends the thread it made when it is done."""
    global _STANDING

    with _MAKING:
        if _STANDING is not None and _STANDING.thread.is_alive():
            _STANDING.loop.call_soon_threadsafe(_STANDING.loop.stop)
            _STANDING.thread.join(timeout=5)
        _STANDING = None
