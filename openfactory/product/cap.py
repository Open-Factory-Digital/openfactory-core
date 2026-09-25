"""A ceiling on concurrent turns, per product and per deployment, that orders nothing (ADR-0051 D4).

WHY IT EXISTS. Conversations run in parallel (D3): ten people in ten conversations are ten model
runs at once, on a worker that runs eight activities in all — the factory's own jobs, reviews and
polls among them. Parallel by default needs a ceiling that is DECLARED rather than discovered the
day a provider's rate limit or a bill finds it. So a turn takes a slot of its product and a slot
of the deployment before the engine is asked anything, and gives both back when it ends, however
it ends.

IT ORDERS NOTHING. Which waiting turn gets the next free slot is whichever asks first — there is no
queue here, and none is wanted: order is the conversation's business (one turn at a time inside
it, D3), and across conversations nothing is ordered at all. A turn waiting for a slot is a turn
whose conversation shows it busy; past the bound it is handed off like any long turn (D6).

WHERE IT HOLDS. In the process that runs the turns — the worker's `conversation_turn` activity —
which is where the spend happens. A deployment runs one worker (the reference deployment, and the
compose file); a deployment that runs several gets each worker's ceiling, and that is stated in
`docs/configuration.md` rather than discovered.

THE READ-ONLY FAST PATH TAKES NO SLOT: it spends no model call (`engine.FAST`), which is what the
ceiling bounds.

`_products` grows by product key — bounded by the registry, never by traffic.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

log = logging.getLogger("openfactory.product.cap")

#: The documented defaults (`docs/configuration.md`). Two turns of one product at once is two
#: people answered side by side, which is the point of parallel conversations; four across the
#: deployment is half the worker's eight activity slots, leaving the other half to the factory's
#: own work — a product conversation must never be what starves a running job's checks.
DEFAULT_PER_PRODUCT = 2
DEFAULT_PER_DEPLOYMENT = 4

#: The two variables an operator sets to move them.
PER_PRODUCT_ENV = "OPENFACTORY_PRODUCT_TURNS_PER_PRODUCT"
PER_DEPLOYMENT_ENV = "OPENFACTORY_PRODUCT_TURNS_PER_DEPLOYMENT"


def _declared(name: str, default: int) -> int:
    """A positive whole number from the environment, or the default — and a value that is not one
    is said in the log rather than obeyed: a ceiling of 0 would stop every conversation, and a
    typo that did that silently would read as a role that never answers."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        log.error("%s=%r is not a positive whole number — using the default, %d", name, raw,
                  default)
        return default
    return value


class Ceiling:
    """The two counting semaphores: one per product, one for the deployment.

    A turn acquires its product's slot FIRST and the deployment's second, and every turn does it
    in that order, so no two turns can each hold what the other waits for."""

    def __init__(self, *, per_product: int, per_deployment: int) -> None:
        self.per_product = per_product
        self.per_deployment = per_deployment
        self._deployment = threading.BoundedSemaphore(per_deployment)
        self._products: dict[str, threading.BoundedSemaphore] = {}
        self._lock = threading.Lock()

    def _of(self, product: str) -> threading.BoundedSemaphore:
        with self._lock:
            slot = self._products.get(product)
            if slot is None:
                slot = self._products[product] = threading.BoundedSemaphore(self.per_product)
            return slot

    @contextmanager
    def hold(self, product: str, *, abandoned: threading.Event | None = None) -> Iterator[None]:
        """A slot of `product` and one of the deployment, for as long as the block runs.

        `abandoned` is set by a caller that stopped waiting — the activity was cancelled, its
        worker is shutting down — and a turn still waiting for a slot then gives up with
        `Abandoned` instead of running, later, for nobody."""
        mine = self._of(product)
        _take(mine, abandoned)
        try:
            _take(self._deployment, abandoned)
            try:
                yield
            finally:
                self._deployment.release()
        finally:
            mine.release()


class Abandoned(RuntimeError):
    """A turn stopped waiting for a slot because whoever asked for it is gone."""


#: How often a waiting turn looks up to see whether it was abandoned.
_WAIT_TICK = 0.5


def _take(slot: threading.BoundedSemaphore, abandoned: threading.Event | None) -> None:
    while not slot.acquire(timeout=_WAIT_TICK):
        if abandoned is not None and abandoned.is_set():
            raise Abandoned("the turn was abandoned while it waited for a slot")


_CEILING: Ceiling | None = None
_CEILING_LOCK = threading.Lock()


def ceiling() -> Ceiling:
    """This process's ceiling, built once from the environment the first time a turn asks."""
    global _CEILING
    with _CEILING_LOCK:
        if _CEILING is None:
            _CEILING = Ceiling(per_product=_declared(PER_PRODUCT_ENV, DEFAULT_PER_PRODUCT),
                               per_deployment=_declared(PER_DEPLOYMENT_ENV,
                                                        DEFAULT_PER_DEPLOYMENT))
            log.info("product turns: at most %d per product, %d on this worker",
                     _CEILING.per_product, _CEILING.per_deployment)
        return _CEILING


def reset() -> None:
    """Forget the ceiling, so the next turn reads the environment again — for a test that sets
    one, and for nothing else."""
    global _CEILING
    with _CEILING_LOCK:
        _CEILING = None
