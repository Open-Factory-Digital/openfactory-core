from openfactory.adapters.agent.base import (
    AgentContext,
    CodingAgentAdapter,
    JudgmentAgentAdapter,
    final_text,
)
from openfactory.adapters.agent.registry import (
    DEFAULT_KIND,
    HARNESSES,
    ROLE_MODELS,
    ROLES,
    addon_role,
    build_asker,
    build_executor,
    build_product,
    build_reviewer,
    build_techlead,
    harness_kind,
    known_roles,
    model_for,
)
from openfactory.adapters.agent.roles import RoleSpec

__all__ = [
    "final_text",
    "DEFAULT_KIND",
    "HARNESSES",
    "ROLES",
    "ROLE_MODELS",
    "RoleSpec",
    "addon_role",
    "known_roles",
    "model_for",
    "AgentContext",
    "ClaudeCodeAdapter",
    "CodingAgentAdapter",
    "JudgmentAgentAdapter",
    "build_asker",
    "build_executor",
    "build_product",
    "build_reviewer",
    "build_techlead",
    "harness_kind",
]

_LAZY = {
    'ClaudeCodeAdapter': 'openfactory.adapters.agent.claude_code',
}

# LAZY, and this is a contract rather than a micro-optimisation.
#
# These lines used to be plain imports, so importing the PORT loaded every implementation of it —
# `from openfactory.adapters.notify.base import Notifier` pulled the Slack adapter and, through it,
# httpx.
# Seven of the nine port packages did this. It meant the Core could not be installed without every
# vendor library, a plugin could not load one provider without all of them, and ADR-0022's claim
# that "nothing outside a provider's package names a concrete class" was true of the call sites and
# false of the package that holds them.
#
# PEP 562: the names still resolve exactly as before, on first use rather than on import.
def __getattr__(name: str):
    import importlib

    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)


def __dir__():
    return sorted(__all__)
