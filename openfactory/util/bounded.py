"""A dict that cannot grow without limit — because three places needed one and two forgot.

THIS MODULE EXISTS BECAUSE THE LESSON WAS LEARNED ONCE AND NOT COPIED. `product_channel._PENDING`
carries a `_MAX_PENDING = 200` and the comment explaining why ("an unbounded dict in a long-lived
worker is a leak"). `bot._PENDING`, written for the same purpose in the same process, has no cap at
all. The panel's `_state_cache` keeps one entry per job that ever reached a terminal state and
removes none. Same process lifetime, same shape, three different answers.

That is the `final_text()` story again (see `openfactory/adapters/agent/base.py`): a workaround
discovered
once, copied by hand to some callers and not others, with no single place that could be fixed. The
fix is not another cap — it is one implementation the caller cannot forget to bound, because the
bound is a constructor argument.

Eviction is insertion-order (FIFO), not LRU. For every caller here the oldest entry is the least
valuable — the unconfirmed draft nobody answered, the state of a job that finished long ago — and
FIFO costs one dict operation where LRU costs bookkeeping on every read. If a caller ever needs
recency, that is a different class and should say so.
"""

from __future__ import annotations

import threading


class BoundedDict[K, V]:
    """A thread-safe mapping that evicts the oldest entry when it would exceed `maxsize`.

    Deliberately NOT a `dict` subclass: inheriting would expose `update`, `setdefault` and
    `__ior__`, each of which can grow the mapping past the bound without going through `__setitem__`
    on every Python version. A small explicit surface cannot be bypassed by accident.
    """

    __slots__ = ("_data", "_lock", "_maxsize", "evicted")

    def __init__(self, maxsize: int) -> None:
        if maxsize < 1:
            raise ValueError(f"maxsize must be at least 1, got {maxsize}")
        self._data: dict[K, V] = {}
        self._lock = threading.Lock()
        self._maxsize = maxsize
        #: How many entries were dropped. A cap that silently discards is indistinguishable from a
        #: cap that is never reached — and the difference decides whether the number is too small.
        self.evicted = 0

    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            if key not in self._data and len(self._data) >= self._maxsize:
                self._data.pop(next(iter(self._data)), None)
                self.evicted += 1
            self._data[key] = value

    def __getitem__(self, key: K) -> V:
        with self._lock:
            return self._data[key]

    def get(self, key: K, default: V | None = None) -> V | None:
        with self._lock:
            return self._data.get(key, default)

    def pop(self, key: K, default: V | None = None) -> V | None:
        with self._lock:
            return self._data.pop(key, default)

    def clear(self) -> None:
        """Safe on a bounded mapping — it can only shrink. Kept because tests need a clean slate
        between cases, and a cache with no way to reset makes them order-dependent."""
        with self._lock:
            self._data.clear()

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._data

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
