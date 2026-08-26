"""The framework floor — the non-negotiable guarantees (ADR-0001 D-2, layer 1).

No project manifest may loosen these. This module is the single place they live,
so "what the platform guarantees regardless of project" is auditable in one file.
"""

from __future__ import annotations

# Commands/roles a project can never remove. Enforced during conformance and by
# the orchestrator (a job cannot reach REVIEWING while a required gate is red).
REQUIRED_VALIDATION_ROLES: frozenset[str] = frozenset({"test", "security"})

# WHAT ACTUALLY DENIES EACH ACTION, and where. This was a `frozenset` of four English phrases
# named `GLOBAL_DENY`, referenced by nothing anywhere in the repository — an audit found it as the
# single occurrence of its own name. The module docstring above claims this file makes "what the
# platform guarantees regardless of project" auditable in one place; it was auditable and inert,
# in the file a security review opens first.
#
# A frozenset of prose can never be enforced: "push to protected branch" is not an interceptable
# operation, it is a description of one. Removing it would lose a true statement; leaving it
# implied an enforcement point that does not exist. So it says what enforces it, and each entry
# names code somebody can go and read — which is what the docstring promised in the first place.
#
# A test asserts every path named here still exists, so this cannot rot into prose again.
GLOBAL_DENY: dict[str, str] = {
    # The agent never holds a push credential: the worktree box strips every forge token from the
    # workload's environment, and the framework — not the agent — publishes the branch.
    "push --force": "openfactory/adapters/sandbox/worktree.py::_scrubbed_env (_FORGE_CRED_VARS)",
    "push to protected branch": "openfactory/adapters/sandbox/worktree.py::_scrubbed_env "
                                "(_FORGE_CRED_VARS); the forge's own branch protection is the "
                                "second line, and is the client's to configure",
    # Deploys are the CLIENT's pipeline (ADR-0005): the platform triggers a merge or a tag and
    # OBSERVES. There is no code path in this repository that deploys anything.
    "access production": "openfactory/runtime/temporal/workflow.py::_promote (approval-gated, "
                         "and the "
                         "release itself is the client's own CI — ADR-0005)",
    # The credential POOL never enters the box; the adapter picks one active token and delivers it
    # to the CLI, and `box.env` names — never values — are what a project may add.
    "read secrets directly": "openfactory/adapters/sandbox/worktree.py::_scrubbed_env "
                             "(_AGENT_CRED_VARS, _AWS_CRED_VARS); "
                             "openfactory/adapters/sandbox/container.py::_passthrough_env",
}
