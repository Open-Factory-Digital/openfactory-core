"""One refresh machinery for every credential that expires on its own (#373).

A vendor's short-lived credential — a JWT minted from a person's CLI login, a token its identity
provider issues to the workload itself — needs the same four guarantees, and they were learned the
hard way on the first one (`adapters/azure_devops.py`, the `az` login):

    renewed early    a token read at the start of a call whose round trip takes up to a minute
                     must not expire in flight; a clock minutes out of step must not matter
    held             one mint per lifetime, not one per HTTP call
    one mint at once N threads reaching an expiry together wait for ONE mint, not N
    kept on failure  a refresh that fails does not evict a token that is still valid — a mint
                     fails for reasons that pass on their own, and dropping a token still good for
                     fifty minutes turns a blip into the mid-job failure this exists to prevent

They lived inside `az_token`, tied to the one source they were written for. A second source that
copied them would fork the hardest-won part of that file, so they live here, and a source plugs in
its mint: a callable answering `(token, epoch expiry)` or None. It is open to an add-on vendor's
row the same way — import it, hand it a mint.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

#: Seconds before a token's stated expiry at which a fresh one is minted rather than reused. The
#: credential is read at the START of a call bounded by a sixty-second timeout, so a margin under a
#: minute can hand out a token that expires in flight; five minutes also absorbs a clock a few
#: minutes out of step with the vendor's, which is ordinary on a laptop that has been asleep.
REFRESH_MARGIN_SECONDS = 300

Mint = Callable[[], "tuple[str, float] | None"]


class ShortLivedToken:
    """A token `mint` answers, held until `margin` seconds before it expires — never raises,
    never logs the value. Called like a provider: `token()` is the current token or None."""

    def __init__(self, mint: Mint, *, margin: float = REFRESH_MARGIN_SECONDS) -> None:
        self._mint = mint
        self._margin = margin
        self._held: tuple[str, float] | None = None
        #: HELD ACROSS THE MINT, not just across the read: releasing it before the mint would
        #: spawn one mint per waiting thread to obtain N copies of the same token.
        self._lock = threading.Lock()

    def __call__(self) -> str | None:
        with self._lock:
            held = self._held
            if held is not None and time.time() < held[1] - self._margin:
                return held[0]
            minted = self._mint()
            if minted is not None:
                self._held = minted
                return minted[0]
            # A FAILED REFRESH DOES NOT EVICT A TOKEN THAT IS STILL VALID — see the module.
            if held is not None and time.time() < held[1]:
                return held[0]
            return None

    def forget(self) -> None:
        """Drop the held token, so the next call mints. For a test, and for nothing else: a held
        token is the machinery working."""
        with self._lock:
            self._held = None


__all__ = ["REFRESH_MARGIN_SECONDS", "ShortLivedToken"]
