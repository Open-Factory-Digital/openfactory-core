"""Where the panel reads the agent-token POOL from — a seam with a free row, not a vendor call.

The cockpit shows how many harness credentials a deployment rotates through (count, ids, format —
never a value). `api/app.py::_token_pool_meta` used to answer that in two branches: the process's
own environment, or — gated on a vendor's cluster variable and a literal parameter path — a
parameter store in one cloud. The second branch was the panel importing the AWS box add-on by
name (`runtime/fargate/observe.py`), which is the coupling the core-versus-connector doctrine
forbids: a deployment on a different cloud has a pool too, and no place to say where it is.

THE SAME SHAPE AS EVERY OTHER AXIS (ADR-0022): a table keyed by kind with a free row, an explicit
choice that wins, an unknown kind that RAISES naming what is known, and add-ons joining through
the `openfactory.adapters` entry-point group (`token_pool.<kind>`). The `ssm` row is the fargate
package's and is declared by `openfactory-aws` (`addons/openfactory-aws/pyproject.toml` in the
private tree); a deployment chooses it with `OPENFACTORY_TOKEN_POOL_SOURCE=ssm`.

THE DEFAULT IS THE ENVIRONMENT, and it is not inferred from anything. A default that reached for a
vendor because a vendor's variable was set is the class `io.default_sandbox` just left.
"""

from __future__ import annotations

import os
from collections.abc import Callable

#: The entry-point axis name: `token_pool.<kind>`.
AXIS = "token_pool"
DEFAULT_SOURCE = "env"


def _from_env(**_kw) -> dict:
    """The pool this process can see, with no cloud involved. What a local deployment HAS."""
    from openfactory.adapters.agent.claude_code import _load_agent_token_pool

    pool = _load_agent_token_pool()
    return {
        "count": len(pool),
        "ids": [p["id"] for p in pool],
        "format": (pool[0]["type"] if pool else "unknown"),
        "source": "env" if pool else "n/a",
    }


#: kind → builder, each answering the cockpit's dict: {count, ids, format, source}.
TOKEN_POOL_SOURCES: dict[str, Callable[..., dict]] = {"env": _from_env}


def token_pool_source_kind() -> str:
    """Which source this deployment declares — `OPENFACTORY_TOKEN_POOL_SOURCE`, else the
    environment. Nothing is inferred: a deployment that keeps its pool elsewhere says so."""
    explicit = (os.environ.get("OPENFACTORY_TOKEN_POOL_SOURCE") or "").strip().lower()
    return explicit or DEFAULT_SOURCE


def token_pool(kind: str | None = None, **kw) -> dict:
    """The pool as `kind` holds it. RAISES on an unknown kind (naming what is installed) and on a
    source that will not answer — the panel is the one that knows an unanswered pool is reported
    from the environment instead, and says so."""
    from openfactory import plugins

    chosen = (kind or token_pool_source_kind()).strip().lower()
    builder = (TOKEN_POOL_SOURCES.get(chosen)
               or plugins.builder(AXIS, chosen, builtin=TOKEN_POOL_SOURCES))
    if builder is None:
        known = ", ".join(plugins.known(AXIS, TOKEN_POOL_SOURCES))
        raise ValueError(f"unknown token pool source {chosen!r} — known: {known}"
                         f"{plugins.install_hint(AXIS, chosen)}")
    return builder(**kw)
