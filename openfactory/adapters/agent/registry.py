"""Which harness plays each role — resolved from config, not from imports.

The platform was agnostic in its protocols and hardcoded in its composition root: a concrete
adapter was instantiated in six places, so a second harness meant editing six files instead of
changing one value. This module is the seam that closed that.

FOUR SHIPPED ROLES, named after what they DO and after the prompt files that define them
(`org_defaults/roles/*.md`), so what you configure and what shapes its behaviour share a name:

    executor   writes the code   plan · execute · repair · continue · recover   (runs in the box)
    reviewer   reviews the diff  review                                         (runs in the box)
    techlead   judges            size · advise · diagnose · chat                (runs on the worker)
    product    decides WHAT      requirements · issue authoring (ADR-0019)      (runs on the worker)

`techlead` covers the sizer too — same nature (read-only judgment), same place, and nobody wants
those two on different engines. Split it later if that stops being true.

AND ANY NUMBER OF ADD-ON ROLES, because the role axis is an axis (docs/core/07 §2: a platform is
extensible when a stranger can add the third without editing our files). A package declares

    [project.entry-points."openfactory.adapters"]
    "role.qa" = "openfactory_qa:role"          # a builder returning `roles.RoleSpec`

and `qa` resolves through `harness_kind` / `model_for` / `build_asker(project, role="qa")`, is
accepted by `set-model --role qa` and shown by the panel cockpit, with its own `harness:` / `model:`
line in the registry. WHAT THE CORE DOES NOT DO for an add-on role is INVOKE it: the pipeline has
one reviewer slot and no stage seam, so the add-on that ships the role is the thing that calls
`build_asker(project, role="qa")` and does something with the answer — composing its prompt from
`roles.role_prompt(<its name>)` itself, because `ask()` takes the prompt whole and no builder here
prepends one. The role axis gives it a configuration line, a prompt and a language — not a place
in the lifecycle (that is an ADR, not a registry row).

CONFIGURED IN ONE LINE, because most deployments use one harness everywhere:

    harness: codex                      # all three roles

    harness:                            # …or per role, when they differ
      executor: codex
      reviewer: claude_code             # a genuinely independent second opinion
      techlead: claude_code

Resolution per role: the env override, then the project's `harness`, then `DEFAULT_KIND`. The env
vars exist ONLY as an operational escape hatch for an experiment — the registry is baked into the
worker image, so without them trying another harness would cost an image rebuild and a roll. They
are not the normal way to configure this.

An unknown kind RAISES. Falling back to a default would let a whole run use a harness nobody chose
and report clean numbers for the wrong thing.

AND WHICH MODEL IT RUNS — `model_for`, resolved the same way from `Project.model`, in the same two
shapes. Every adapter had always accepted a model and every builder here had always forwarded a
`model=` kwarg, but no caller ever passed one: built, forwarded, reached by nothing. So the only
control that worked was the process-wide `OPENFACTORY_EXECUTOR_MODEL` — one value for the whole
worker,
moved only by an environment change and a roll — and two per-client decisions had nowhere to live:
which PROVIDER serves a client (their own Bedrock account, an Azure or gateway endpoint) and which
TIER they pay for. `harness` says which CLI; `model` says what it runs. Both are one line each.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from openfactory import plugins
from openfactory.adapters.agent.roles import RoleSpec

log = logging.getLogger("openfactory.roles")

DEFAULT_KIND = "claude_code"

#: THE SHIPPED ROLES, and the env var that overrides each. Four rows, and the fifth is not a row:
#: a role added from outside declares a `role.<name>` entry point whose builder returns a
#: `roles.RoleSpec`, and joins `known_roles()` at lookup time without a line here. What stays
#: closed is the meaning of THESE names — an add-on declaring `role.techlead` is refused and
#: logged, for the reason `plugins.py` gives.
ROLES: dict[str, str] = {
    "executor": "OPENFACTORY_HARNESS_EXECUTOR",
    "reviewer": "OPENFACTORY_HARNESS_REVIEWER",
    "techlead": "OPENFACTORY_HARNESS_TECHLEAD",
    # ADR-0019. Its own axis rather than a share of `techlead`, because the two judge different
    # things: the tech-lead reasons about a failure in a codebase, the product role about whether a
    # request contradicts something the product already promises. A deployment may reasonably want
    # a different engine for each — and the module is opt-in, so most projects never resolve this.
    "product": "OPENFACTORY_HARNESS_PRODUCT",
}

#: role → the env var that overrides its MODEL. Same status as `ROLES`: an operational escape
#: hatch, never the normal configuration path — `model:` in the registry is.
#:
#: `OPENFACTORY_EXECUTOR_MODEL` is not new here. All three adapters already read it themselves as
#: their
#: own fallback, so resolving it here as well changes nothing: the value is identical whether it
#: arrives as an argument or is picked up inside the constructor. What IS new is that the other
#: three roles get one at all — before this, a deployment could not move the tech-lead's model
#: without moving the executor's too.
ROLE_MODELS: dict[str, str] = {
    "executor": "OPENFACTORY_EXECUTOR_MODEL",
    "reviewer": "OPENFACTORY_REVIEWER_MODEL",
    "techlead": "OPENFACTORY_TECHLEAD_MODEL",
    "product": "OPENFACTORY_PRODUCT_MODEL",
}


def _claude(**kw: object):
    from openfactory.adapters.agent.claude_code import ClaudeCodeAdapter

    # THE ROLE HAS TO REACH HERE. This adapter keeps two model slots and chooses between them by
    # phase, not by build: every read-only call — plan, and the `ask()` that sizing, review,
    # diagnosis and chat are all built on — runs `planner_model`, and only the coding calls run
    # `executor_model`. Filling the single legacy `model=` would set BOTH, silently moving the
    # model of whichever path this build is not for.
    slot = "executor_model" if kw.get("role") == "executor" else "planner_model"
    return ClaudeCodeAdapter(log_dir=kw.get("log_dir"), language=kw.get("language"),
                             **{slot: kw.get("model") or None})


def _codex(**kw: object):
    from openfactory.adapters.agent.codex import CodexAdapter

    return CodexAdapter(model=kw.get("model"), log_dir=kw.get("log_dir"),
                        language=kw.get("language"))


def _kimi(**kw: object):
    from openfactory.adapters.agent.kimi import KimiAdapter

    return KimiAdapter(model=kw.get("model"), log_dir=kw.get("log_dir"),
                        language=kw.get("language"))


def _opencode(**kw: object):
    from openfactory.adapters.agent.opencode import OpenCodeAdapter

    return OpenCodeAdapter(model=kw.get("model"), log_dir=kw.get("log_dir"),
                           language=kw.get("language"))


#: kind → builder. Adding a harness is ONE entry here plus its module. That is the seam's whole
#: claim, and a test asserts no call site ever goes back to naming a class directly.
HARNESSES: dict[str, Callable[..., object]] = {
    "claude_code": _claude,
    "codex": _codex,
    "kimi": _kimi,
    # the provider-agnostic line: one binary that reaches Anthropic, Bedrock, Azure, Vertex or any
    # OpenAI-compatible endpoint, so which provider serves a client is `model:` rather than a
    # different harness (openfactory/adapters/agent/opencode.py)
    "opencode": _opencode,
}


#: kind → the CLI it actually shells out to, where the two differ. Everything else IS its own
#: binary name. One table, because three separate copies of this had already drifted: `doctor`
#: hardcoded a three-entry map under a comment promising it did not, `box_prove` inlined its own,
#: and the ADR-0037 bare-name guard listed adapter files by hand — so a fourth harness joined the
#: registry while remaining invisible to the check that exists to keep it honest.
HARNESS_BINARIES: dict[str, str] = {"claude_code": "claude"}


def harness_binary(kind: str) -> str:
    """The executable name for a harness kind."""
    return HARNESS_BINARIES.get(kind, kind)


#: The key a dict-shaped `harness:` / `model:` uses for every role it does not name. Named once,
#: because it is read in two places (here and the registry file's unknown-key warning) and
#: REFUSED in a third: an add-on role called `default` would make `harness: {default: codex}` say
#: two things — that role's engine, and everybody else's fallback.
FALLBACK_KEY = "default"


def _configured(project, role: str, field: str = "harness") -> str:
    """What a project declares for one role — accepting both shapes of `harness`/`model`."""
    h = getattr(project, field, None) if project is not None else None
    if isinstance(h, str):
        return h.strip()
    if isinstance(h, dict):
        # a per-role entry wins; the fallback key covers the rest; anything unset falls through
        return str(h.get(role) or h.get(FALLBACK_KEY) or "").strip()
    return ""


#: Add-on roles already refused, one line each — the registry is consulted on every job and a
#: broken add-on would otherwise say the same sentence every time a harness is resolved.
_REFUSED_SAID: set[str] = set()


def _refuse(kind: str, why: str) -> None:
    if kind not in _REFUSED_SAID:
        _REFUSED_SAID.add(kind)
        log.warning("add-on role %r is ignored: %s. Every other role is unaffected; the name "
                    "will show as UNKNOWN until the add-on is fixed", kind, why)


def _valid_role(kind: str, build: Callable[..., object]) -> RoleSpec | None:
    """The spec `role.<kind>` declares, or None with the reason logged once.

    An add-on that fails here is not half-registered: the name resolves nowhere, so a project
    that configures it gets the same loud `unknown role` a typo gets — which names what IS
    installed. The alternative, honouring a spec that is partly wrong, is a role that resolves a
    harness and reads a prompt somebody else wrote."""
    from openfactory import environ
    from openfactory.adapters.agent.roles import shipped_prompt_names

    try:
        spec = build()
    except Exception as exc:  # noqa: BLE001 — one bad add-on may not disable the others
        _refuse(kind, f"its builder raised {exc.__class__.__name__}: {exc}")
        return None
    if not isinstance(spec, RoleSpec):
        _refuse(kind, f"its builder returned {type(spec).__name__}, not a RoleSpec")
        return None
    if spec.name != kind:
        # the entry point's name is the key everything resolves by; a spec that calls itself
        # something else would make `role.qa` answer to two names, one of them unlisted
        _refuse(kind, f"the entry point says {kind!r} and the spec says {spec.name!r}")
        return None
    if kind in shipped_prompt_names():
        # `sizer`, `planner`, `coordinator`, `recovery` are prompt files rather than config rows,
        # so `plugins.builder` does not see the collision — but `role_prompt()` reads the shipped
        # file first and would silently ignore the add-on's text
        _refuse(kind, f"{kind!r} is a role prompt this package ships; built-ins win a collision")
        return None
    if kind == FALLBACK_KEY:
        _refuse(kind, f"{kind!r} is the key a per-role `harness:`/`model:` uses for every role "
                      f"it does not name; a role by that name would make one line mean two things")
        return None
    taken_phase = _shipped_phase_taken_by(kind)
    if taken_phase:
        # a phase is where `human_facing` is read (`roles.needs_language_directive` attributes
        # `<name>` and `<name>_*` to the add-on), so a role named `size` with `human_facing=False`
        # would decide the language of the tech-lead's sizing
        _refuse(kind, f"{taken_phase!r} is a phase this package passes, and a role owns the phases "
                      f"spelled after it; a role by that name would decide the language of a "
                      f"shipped prompt")
        return None
    for env in (spec.harness_env, spec.model_env):
        why = environ.reserved(env)
        if why:
            _refuse(kind, f"{env} is {why}; an add-on cannot read a variable that already means "
                          f"something else")
            return None
    return spec


def _shipped_phases() -> frozenset[str]:
    from openfactory.adapters.agent.roles import CODING_PHASES, HUMAN_PHASES, MACHINE_PHASES

    return CODING_PHASES | HUMAN_PHASES | MACHINE_PHASES


def _shipped_phase_taken_by(kind: str) -> str | None:
    """The shipped phase an add-on called `kind` would own by the `<name>`/`<name>_*` rule, or
    None. `product` is refused earlier as a shipped role; this catches `size`, `chat`, `review`."""
    for phase in sorted(_shipped_phases()):
        if _phase_belongs_to(phase, kind):
            return phase
    return None


def _phase_belongs_to(phase: str, role: str) -> bool:
    """The one spelling of "this phase is that role's": the name itself, or the name and an
    underscore-joined suffix — how the shipped product role labels its own (`product_confirm`)."""
    return phase == role or phase.startswith(f"{role}_")


def _addon_roles() -> dict[str, RoleSpec]:
    """Every add-on role this deployment installed and this registry accepts, by name.

    Built-ins win a collision, and the collision is said out loud — the reason is in `plugins.py`:
    an add-on that could redefine `techlead` is a supply chain, not an extension.

    AND ONE VARIABLE BINDS ONE ROLE. `RoleSpec` refuses a spec whose two env names are the same;
    this is the same rule across specs — `role.qa` and `role.sec` both reading `SHARED_HARNESS`
    would be one exported variable moving two roles, and a `sec` model override that is `qa`'s
    harness override would hand a harness name to a model slot. The second claimant is refused by
    name (the loader lists kinds sorted, so which one is second is stable), and the first keeps
    the variable."""
    for kind in plugins.shadowed("role", ROLES):
        _refuse(kind, f"{kind!r} is a role this package ships; built-ins win a collision")
    out: dict[str, RoleSpec] = {}
    claimed: dict[str, str] = {}  # env var → the accepted role reading it
    for kind in plugins.known("role", ROLES):
        build = plugins.builder("role", kind, builtin=ROLES)
        if build is None:
            continue  # a shipped role: its row is the table above, not an entry point
        spec = _valid_role(kind, build)
        if spec is None:
            continue
        clash = next((env for env in (spec.harness_env, spec.model_env) if env in claimed), None)
        if clash is not None:
            _refuse(kind, f"{clash} is already read by the installed {claimed[clash]!r} role; one "
                          f"variable cannot bind two roles")
            continue
        claimed[spec.harness_env] = claimed[spec.model_env] = kind
        out[kind] = spec
    return out


def addon_role(role: str) -> RoleSpec | None:
    """The spec of an ADD-ON role, or None — which is a real answer: a shipped role has no spec
    by design (its prompt is a file, its env names are the tables), so None here means "not an
    add-on", never "could not look". `known_roles()` is the question for "is this a role at all"."""
    return _addon_roles().get(role)


def addon_for_phase(phase: str) -> RoleSpec | None:
    """The add-on role whose phase this is, or None — the reader of `RoleSpec.human_facing`.

    A phase is the label a role hands `ask()` and the row it meters under; an add-on's are its
    name and `<name>_<anything>` (`_phase_belongs_to`). Two add-ons cannot both own a phase: a
    role's name is a lowercase identifier and `qa_x` belongs to `qa` only, unless a role is named
    `qa_x` itself — in which case the longer name wins, as the more specific claim."""
    owners = [spec for name, spec in _addon_roles().items() if _phase_belongs_to(phase, name)]
    if not owners:
        return None
    return max(owners, key=lambda spec: len(spec.name))


def known_roles() -> list[str]:
    """Every role this deployment can resolve — shipped plus installed, sorted.

    The one list every surface reads: the resolvers below, `ProjectRegistry.set_model`, the
    registry's unknown-key warning and the panel cockpit. A role that resolves here and is listed
    nowhere would be a role a person cannot configure or see, and the refusal message has to name
    the row a stranger just installed or it tells them the platform does not support it."""
    return sorted({*ROLES, *_addon_roles()})


def _role_envs(role: str) -> tuple[str, str, str]:
    """`(harness env var, model env var, default harness kind)` for a role, shipped or add-on.

    UNREGISTERED RAISES, naming what is known — a typo must never resolve to a default: a run that
    silently used a harness nobody chose would report clean numbers for the wrong thing."""
    if role in ROLES:
        return ROLES[role], ROLE_MODELS[role], DEFAULT_KIND
    spec = addon_role(role)
    if spec is None:
        raise ValueError(f"unknown role {role!r} — known: {', '.join(known_roles())}")
    return spec.harness_env, spec.model_env, spec.harness or DEFAULT_KIND


def harness_kind(project=None, role: str = "executor") -> str:
    """Which harness serves `role` for this project, by the documented resolution order."""
    harness_env, _, default = _role_envs(role)
    return (
        (os.environ.get(harness_env) or "").strip()
        or _configured(project, role)
        or default
    )


def model_for(project=None, role: str = "executor") -> str | None:
    """Which MODEL serves `role` for this project — same resolution order as `harness_kind`.

    None means "the harness's own default", which is what every deployment got before this
    existed and what most still want: the model is a decision only some clients have made.

    The value is passed to the harness UNVALIDATED and uninterpreted (see `Project.model`).
    """
    _, model_env, _ = _role_envs(role)
    return (
        (os.environ.get(model_env) or "").strip()
        or _configured(project, role, "model")
        or None
    )


def _build(kind: str, **kw: object):
    builder = HARNESSES.get(kind) or plugins.builder('harness', kind, builtin=HARNESSES)
    if builder is None:
        _known = ', '.join(plugins.known('harness', HARNESSES))
        raise ValueError(
            f"unknown harness {kind!r} — known: {_known}. Refusing to fall "
            f"back to {DEFAULT_KIND!r}: a run that silently used a harness nobody chose would "
            f"report clean numbers for the wrong thing."
        )
    return builder(**kw)


def _language_of(project) -> str | None:
    return getattr(project, "language", None)


def _judging(kind: str, role: str, project=None):
    """A harness instance that can serve a judging role, or a loud failure. Checked at BUILD time
    so a misconfiguration surfaces when the job starts, not when it parks hours later and the
    diagnosis silently fails."""
    from openfactory.adapters.agent.roles import can_judge

    agent = _build(kind, language=_language_of(project), role=role,
                   model=model_for(project, role))
    if not can_judge(agent):
        raise ValueError(
            f"harness {kind!r} cannot serve the {role} role: it does not implement `ask()`, the "
            f"read-only primitive every judging role is built on (see agent/roles.py)."
        )
    return agent


def build_executor(project=None, *, log_dir: Path | None = None):
    """The harness that WRITES CODE for this project."""
    return _build(harness_kind(project, "executor"), log_dir=log_dir,
                  language=_language_of(project), role="executor",
                  model=model_for(project, "executor"))


#: A harness may ship its OWN implementation of a role. When it does, that one wins — see
#: `_native_first` for why. Only `claude_code` has one today, because only it has production miles.
#: A builder here takes `model=` (may be None), like every other builder on this axis.
NATIVE_REVIEWERS: dict[str, Callable[..., object]] = {}


def _register_native_reviewers() -> None:
    from openfactory.adapters.reviewer.claude_code import ClaudeCodeReviewer

    NATIVE_REVIEWERS.setdefault("claude_code", ClaudeCodeReviewer)


_TECHLEAD_METHODS = ("size", "advise", "diagnose", "chat")


def _native_first(agent, methods: tuple[str, ...]) -> bool:
    """Whether this harness implements a role ITSELF, rather than needing the generic path.

    The generic implementations (over `ask()`) are what give a Claude-free deployment a reviewer
    and a tech-lead at all. But for a harness that already HAS these — Claude does, and they run
    in production today — routing through the generic path would swap a proven invocation for an
    unproven one: the two use different CLI output formats and different parsers, so "the prompt is
    identical" is not the same as "the behaviour is identical". Stability beats uniformity on a
    path that already works; the generic path earns its way in by being the only option elsewhere.
    """
    return all(callable(getattr(agent, m, None)) for m in methods)


def build_techlead(project=None):
    """The tech-lead + sizer, over whichever harness this project judges with."""
    from openfactory.adapters.agent.techlead import HarnessTechLead

    kind = harness_kind(project, "techlead")
    agent = _judging(kind, "techlead", project)
    return agent if _native_first(agent, _TECHLEAD_METHODS) else HarnessTechLead(agent)


def build_product(project=None):
    """The harness that reasons about REQUIREMENTS for this project (ADR-0019).

    Judging, like the tech-lead: read-only over the requirements corpus, the board and the code. So
    it is checked for `ask()` at build time — a misconfiguration surfaces when the module starts
    rather than when someone asks it a question in Slack and gets silence."""
    return _judging(harness_kind(project, "product"), "product", project)


def build_asker(project=None, *, role: str = "techlead"):
    """The RAW judging harness for `role` — the one thing `ask()` can be called on directly.

    Every other builder on this axis answers a named job (`build_techlead` may return a wrapper
    that speaks `size`/`advise`/`diagnose`/`chat`, `build_reviewer` a reviewer). A caller that
    needs the read-only primitive ITSELF — `onboarding/context.agent_ask` is the first — had only
    two options, and both are wrong: `build_techlead` returns `HarnessTechLead` on any harness
    without native tech-lead methods, and that class exposes `_ask`, not `ask`, so `can_judge`
    answers False and the pass refuses on exactly the harnesses the generic path exists to serve;
    `build_product` has `ask` but resolves the PRODUCT role's harness and model, so a deployment
    that pointed the product role at a cheap engine would silently get it here too.

    Raises at build time when the configured harness cannot judge, like every other judging
    builder — a misconfiguration is a fact to learn before the client is in the room."""
    return _judging(harness_kind(project, role), role, project)


def build_reviewer(project=None):
    """The independent reviewer, over whichever harness this project reviews with."""
    from openfactory.adapters.reviewer.harness import HarnessReviewer

    kind = harness_kind(project, "reviewer")
    _register_native_reviewers()
    native = NATIVE_REVIEWERS.get(kind)
    if native is not None:
        # a native reviewer takes `model=` like every other builder on this axis — otherwise the
        # ONE role a deployment is most likely to want on a different model is the one that
        # cannot have it
        return native(model=model_for(project, "reviewer"))
    return HarnessReviewer(_judging(kind, "reviewer", project))
