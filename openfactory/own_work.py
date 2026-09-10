"""Whose machine is the worker? — the one declaration a host deployment makes (ADR-0049 D9).

A DURABLE JOB RUNS AN AGENT ON THE WORKER ITSELF, unattended, for hours. That is why
`durable_refusal` refuses a box that bounds nothing but the code state: on a hosted deployment the
worker is shared infrastructure, and arbitrary code from a ticket must not run in its filesystem
beside the scheduler and its credentials.

ON ONE MACHINE THAT REASONING INVERTS, and it is the same fact read from the other side: the worker
IS the person's own laptop, running as them, and their coding agent already runs there every time
they type `claude`. There is no boundary to cross because there are not two parties. So the
refusal accepts a DECLARATION in place of the isolation — one variable, written by `openfactory
init` on the `local` runtime and never on `compose`.

IT IS A DECLARATION AND NOT AN INFERENCE, deliberately. The platform could guess — "the sandbox is
a worktree, so this must be somebody's laptop" — and that guess is exactly wrong on the deployment
that matters: a shared build server with `OPENFACTORY_SANDBOX=worktree` set by somebody who did not
think about it. A person says this about their own machine, in one line their operations team can
grep for.
"""

from __future__ import annotations

import os

#: The variable. Named for what it declares — that the work on this board belongs to whoever owns
#: this machine — rather than for the mechanism it unlocks.
VARIABLE = "OPENFACTORY_OWN_WORK"

_TRUE = ("1", "true", "yes", "on")


def declared() -> bool:
    """Whether this deployment has said the worker is its own machine."""
    return (os.environ.get(VARIABLE) or "").strip().lower() in _TRUE


#: What a refusal adds when the declaration is absent — the way out, named, for the one operator
#: this is about: somebody running the factory unpacked on their own host.
THE_WAY_OUT = (f"If this worker IS your own machine — the factory running on your host, with the "
               f"agent you already run there — say so with {VARIABLE}=1 and this refusal steps "
               f"aside. `openfactory init` writes it for the `local` runtime.")
