"""WHERE a harness talks, and what it needs to get there.

The third question on this axis. `harness_kind` says which CLI, `model_for` says what it runs, and
this says which host it reaches — because for an enterprise client those are three independent
answers. The same `claude` binary talks to `api.anthropic.com`, to a Bedrock runtime endpoint in
the client's own AWS account, or to a gateway that fronts an Azure/Foundry deployment, purely on
the strength of environment variables. Which one is a client decision, and until now nothing here
could express it.

THE DEFECT THIS CLOSES. `box_prove` probed a hardcoded `https://api.anthropic.com/v1/messages`,
and that proof is what gates pickup. So:

  * a Bedrock client on a restricted network — the first one is exactly this — would be REFUSED
    pickup because a host their harness never contacts is blocked, with the failure blaming a
    network that is doing its job;
  * a client whose proxy allows `api.anthropic.com` but not their own Bedrock endpoint would PASS
    the proof and die on the first real agent call, at agent prices;
  * a Codex or Kimi deployment was being proven against Anthropic's API in either direction.

`box.env`'s own docstring already named the Bedrock and gateway routes as the reason it exists.
The mechanism was declared ready while the proof that gates pickup still assumed one vendor.

WHAT IS ASSERTED HERE IS ONLY WHAT IS CERTAIN. A required-variable list that is too eager blocks
pickup for a deployment that would have worked — the same damage as the bug, wearing a helmet. So
a route requires a variable only where its absence CANNOT work (Bedrock genuinely cannot resolve
an endpoint without a region), and everything merely likely goes in the remedy text instead. AWS
credentials are the clearest case: a task role delivers them with no variable set at all, so
demanding one would fail the deployments that are configured best.

`OPENFACTORY_HARNESS_ENDPOINT` overrides everything, because no table here can enumerate a private
VPC
endpoint or an on-prem gateway, and a guess that blocks pickup is worse than an admitted gap.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

#: The operator's escape hatch: a route nobody here anticipated.
ENDPOINT_OVERRIDE = "OPENFACTORY_HARNESS_ENDPOINT"


@dataclass(frozen=True)
class AuthRoute:
    """How the configured harness will actually reach a model."""

    #: `bedrock`, `gateway`, `anthropic`… — named in findings, so a human reads a route not a URL.
    name: str
    #: The URL to probe for reachability. EMPTY means "not known" — say so, never guess.
    endpoint: str = ""
    #: Groups of alternatives. Each group needs at least ONE of its names present in the box.
    requires: tuple[tuple[str, ...], ...] = ()
    #: What to do when this route is incomplete. Always concrete, always about `box.env`.
    remedy: str = ""
    #: Names that could not be resolved, so the endpoint could not be built.
    unresolved: tuple[str, ...] = field(default_factory=tuple)

    def missing(self, present: dict[str, str] | None) -> list[str]:
        """Which requirement GROUPS are unsatisfied, rendered as the names that would satisfy each.

        Takes what is present INSIDE THE BOX, not on the worker: the worker holding a variable that
        `box.env` does not carry through is precisely the misconfiguration this catches, and it is
        invisible from the worker's own environment."""
        env = present or {}
        return [" or ".join(group) for group in self.requires
                if not any((env.get(name) or "").strip() for name in group)]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() not in ("", "0", "false", "no")


#: Where each harness talks when nothing redirects it. Empty string = we do not know, and an
#: honest gap beats a guessed host that refuses pickup.
DEFAULT_ENDPOINTS: dict[str, str] = {
    "claude_code": "https://api.anthropic.com/v1/messages",
    "codex": "https://api.openai.com/v1/models",
    # Moonshot serves `.ai` and `.cn` estates and the CLI has never been run against either from
    # here, so this stays unknown rather than blocking a deployment on a coin flip.
    "kimi": "",
}


def declared_route(project) -> str:
    """The route a project's REGISTRY ENTRY determines, for a reader that cannot see the box.

    `resolve_route` answers from an ENVIRONMENT, and that is right for the worker and for
    `box prove`, which run where the harness runs. The panel does not. Its container carries none
    of the discriminating variables — `panel_apprunner.tf` and `panel_service.tf` enumerate its
    environment and there is no `CLAUDE_CODE_USE_BEDROCK`, no `ANTHROPIC_BASE_URL`, no harness
    credential at all — so every branch of `resolve_route` was invisible to it and it fell through
    to the last one and reported `anthropic`. A vendor name reached by ABSENCE, rendered
    identically to a resolved one: a Bedrock client's operator reads "auth: anthropic" and goes to
    ask their security team to open a host their deployment never contacts. Exactly the belief
    this module was written to end, restated by the surface meant to display it.

    So this answers from what the panel CAN see, and the registry does determine it:

      * for `opencode` the provider IS the model's prefix, and the model is a registry value;
      * otherwise the box can only receive what `box.env` NAMES, so a project that names no
        Bedrock or gateway variable cannot be taking those routes — there is no channel for the
        credential to arrive through;
      * anything else is admitted as unknown rather than guessed.
    """
    from openfactory.adapters.agent.registry import harness_kind, model_for

    if harness_kind(project, "executor") == "opencode":
        model = model_for(project, "executor") or ""
        provider = model.split("/", 1)[0].strip().lower() if "/" in model else ""
        return {"amazon-bedrock": "bedrock", "anthropic": "anthropic",
                "azure": "azure", "openai": "openai"}.get(provider, "")

    names = set(getattr(getattr(project, "box", None), "env", None) or ())
    for var, route in (("CLAUDE_CODE_USE_BEDROCK", "bedrock"),
                       ("ANTHROPIC_BASE_URL", "gateway"),
                       ("CLAUDE_CODE_USE_VERTEX", "vertex")):
        if var in names:
            return route
    # Nothing named means nothing else can reach the box: the two Anthropic-direct variables are
    # the only ones passed through by default (`container.py::_AUTH_ENV_VARS`), so this is a
    # conclusion rather than a fallback.
    return "anthropic" if project is not None else ""


def _opencode_route(project, e: dict[str, str]) -> AuthRoute:
    """OpenCode names its provider in the MODEL — `-m amazon-bedrock/anthropic.claude-…` — so for
    this harness the route is a property of `model:`, which is exactly the point of it: the same
    binary reaches a different provider by configuration alone.

    The provider ids are the observed ones (`opencode models`), including the detail that it is
    `amazon-bedrock` and not `bedrock`. An unrecognised prefix is left unknown rather than guessed;
    OpenCode's catalogue runs to 180 providers and this table will never be complete.
    """
    from openfactory.adapters.agent.registry import model_for

    model = model_for(project, "executor") or ""
    provider = model.split("/", 1)[0].strip().lower() if "/" in model else ""

    if provider == "anthropic":
        return AuthRoute(name="opencode/anthropic", endpoint=DEFAULT_ENDPOINTS["claude_code"],
                         requires=(("ANTHROPIC_API_KEY",),),
                         remedy="name ANTHROPIC_API_KEY in the project's `box.env`")
    if provider == "openai":
        return AuthRoute(name="opencode/openai", endpoint=DEFAULT_ENDPOINTS["codex"],
                         requires=(("OPENAI_API_KEY",),),
                         remedy="name OPENAI_API_KEY in the project's `box.env`")
    if provider == "amazon-bedrock":
        region = (e.get("AWS_REGION") or e.get("AWS_DEFAULT_REGION") or "").strip()
        return AuthRoute(
            name="opencode/bedrock",
            endpoint=f"https://bedrock-runtime.{region}.amazonaws.com" if region else "",
            requires=(("AWS_REGION", "AWS_DEFAULT_REGION"),),
            unresolved=() if region else ("AWS_REGION",),
            remedy="name AWS_REGION in the project's `box.env`, plus whatever delivers AWS "
                   "credentials inside the box",
        )
    if provider == "azure":
        # Foundry resources answer on more than one host shape and none was verified live, so the
        # endpoint stays unknown and the operator names it. A guessed host would refuse pickup.
        return AuthRoute(
            name="opencode/azure", endpoint="",
            requires=(("AZURE_RESOURCE_NAME",), ("AZURE_API_KEY",)),
            remedy="name AZURE_RESOURCE_NAME and AZURE_API_KEY in the project's `box.env`, and "
                   f"set {ENDPOINT_OVERRIDE} to the resource's host so reachability is proven "
                   "rather than assumed",
        )
    return AuthRoute(
        name="opencode", endpoint="",
        remedy=f"`model:` is {model!r} — set it to `provider/model` (e.g. "
               f"`amazon-bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0`) so the route is "
               f"known, or set {ENDPOINT_OVERRIDE} to the host it talks to"
        if model else
        f"`model:` is unset, so no provider is chosen and no endpoint can be proven — set it to "
        f"`provider/model`, or set {ENDPOINT_OVERRIDE}",
    )


def resolve_route(project=None, env: dict[str, str] | None = None) -> AuthRoute:
    """The route the configured harness will take for this project.

    Read from the WORKER's environment, which is where a deployment's harness credentials are
    configured; `box.env` is what carries the chosen names into the box, and whether it actually
    did is a separate finding (see `AuthRoute.missing`).
    """
    from openfactory.adapters.agent.registry import harness_kind

    e = os.environ if env is None else env

    override = (e.get(ENDPOINT_OVERRIDE) or "").strip()
    if override:
        return AuthRoute(name="declared", endpoint=override,
                         remedy=f"{ENDPOINT_OVERRIDE} names this endpoint explicitly")

    kind = harness_kind(project, "executor")

    if kind == "claude_code":
        base = (e.get("ANTHROPIC_BASE_URL") or "").strip()
        if base:
            # An LLM gateway, which is also how a Foundry-hosted Claude is reached today: the
            # harness speaks its native protocol and the gateway does the translating.
            return AuthRoute(
                name="gateway", endpoint=base,
                requires=(("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"),),
                remedy="name ANTHROPIC_BASE_URL and the gateway's key variable in the project's "
                       "`box.env` — the worker holding them is not enough, they have to reach "
                       "INSIDE the box where the harness runs",
            )
        if _truthy(e.get("CLAUDE_CODE_USE_BEDROCK")):
            region = (e.get("AWS_REGION") or e.get("AWS_DEFAULT_REGION") or "").strip()
            return AuthRoute(
                name="bedrock",
                endpoint=f"https://bedrock-runtime.{region}.amazonaws.com" if region else "",
                requires=(("CLAUDE_CODE_USE_BEDROCK",), ("AWS_REGION", "AWS_DEFAULT_REGION")),
                unresolved=() if region else ("AWS_REGION",),
                remedy="Bedrock needs CLAUDE_CODE_USE_BEDROCK and a region in the project's "
                       "`box.env`, plus whatever delivers AWS credentials inside the box. If the "
                       "account's model access is region-prefixed, `model:` in the registry has "
                       "to carry that inference profile — a bare model id is rejected",
            )
        if _truthy(e.get("CLAUDE_CODE_USE_VERTEX")):
            region = (e.get("CLOUD_ML_REGION") or e.get("VERTEX_REGION") or "").strip()
            return AuthRoute(
                name="vertex",
                endpoint=f"https://{region}-aiplatform.googleapis.com" if region else "",
                requires=(("CLAUDE_CODE_USE_VERTEX",), ("CLOUD_ML_REGION", "VERTEX_REGION")),
                unresolved=() if region else ("CLOUD_ML_REGION",),
                remedy="Vertex needs CLAUDE_CODE_USE_VERTEX and a region in the project's "
                       "`box.env`, plus whatever delivers Google credentials inside the box",
            )
        return AuthRoute(
            name="anthropic", endpoint=DEFAULT_ENDPOINTS["claude_code"],
            requires=(("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"),),
            remedy="the box passes these two through by default; if neither is set on the worker "
                   "the harness has no credential at all",
        )

    if kind == "opencode":
        return _opencode_route(project, e)

    return AuthRoute(name=kind, endpoint=DEFAULT_ENDPOINTS.get(kind, ""),
                     remedy=f"no endpoint is known for harness {kind!r} — set "
                            f"{ENDPOINT_OVERRIDE} to the host it talks to and reachability "
                            f"becomes provable instead of assumed")
