"""Conformance — is a project runnable? (ADR-0001 D-3)

The framework owns the *slots* and which are required; the project fills them
(directly or via a cascade default). A project that leaves a required slot empty
with no default does not run jobs. This is the gate that makes "onboard a repo" a
standard, checkable act rather than a leap of faith.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from openfactory.contracts import Manifest
from openfactory.contracts.state import RiskLevel
from openfactory.policy import floor
from openfactory.policy.presets import available_stacks, load_preset, org_default_validation
from openfactory.policy.profiles import ResolvedProfile


class ConformanceIssue(BaseModel):
    level: str  # "error" (blocks running) | "warning" (allowed, but costs autonomy)
    message: str


class ConformanceReport(BaseModel):
    ok: bool
    issues: list[ConformanceIssue]


def _effective_validation(manifest: Manifest) -> set[str]:
    """The validation roles available after the cascade: deployment ∪ presets ∪ repo ∪ components.

    THE DEPLOYMENT TERM IS NOT READ HERE, and that is deliberate rather than an omission. It is
    already inside `manifest.validation`: `Manifest._inherit_the_deployment_floor` merges
    `org_defaults/floor.yaml` into the repo-wide mapping at construction. Reading the file a second
    time in this function would let the two copies disagree — and the copy that matters is the one
    in the model, because that is the one `orchestrator/validation.applicable_validations` runs.
    A floor inspected from one source and executed from another is the defect this whole change
    exists to close.
    """
    roles: set[str] = set(manifest.validation)
    for comp in manifest.components.values():
        roles |= set(load_preset(comp.stack).get("validate", {}))
        roles |= set(comp.validation)
    return roles


def _command_of(gate) -> str:
    """The shell string behind either shape a gate may hold, via the one place that knows both."""
    from openfactory.orchestrator.validation import (
        as_gate,  # late: policy ← orchestrator is a cycle
    )

    return as_gate(gate).command


def inherited_floor_roles(manifest: Manifest) -> set[str]:
    """Which repo-wide roles this project got from the DEPLOYMENT rather than from its own file.

    WHY ANYONE NEEDS TO KNOW. A default that quietly satisfies the floor is the trap this change
    was warned about: every project passes conformance, nobody has read a scanner's output, and
    the floor is decorative in a new way. So the inheritance is reported — in `check`, on the
    surface a human reads before the first ticket — with the command it will run, so "we have a
    security gate" is a claim somebody can check rather than a colour on a report.

    COMPARED BY COMMAND, because the model deliberately keeps no provenance: `declared_keys()`
    answers whether the FILE wrote `validate:` at all, not which roles inside it are the client's.
    A project that independently writes the identical command is reported as inheriting it, which
    is true in every sense that matters — the same command runs either way.
    """
    defaults = org_default_validation() or {}
    return {role for role, gate in defaults.items()
            if role in manifest.validation
            and _command_of(manifest.validation[role]) == _command_of(gate)}


#: The one-line fix for each role the floor requires, keyed BY ROLE — and the key is the whole
#: point.
#:
#: TWO DEFECTS LIVED IN THE SINGLE SHARED SENTENCE THIS REPLACES, and the second was created by the
#: fix for the first. The original ended "adopt a preset that carries one (`stack: security-oss`
#: ships free advisory scanners)", and `Manifest(stack='security-oss')` is a ValidationError —
#: `Manifest` has no `stack` field and is `extra="forbid"`. So the platform printed an instruction
#: its own schema refuses, to the one reader with no way to know that: a client on their first day.
#: That was corrected to a schema-valid snippet, still shared by every role, still naming SECURITY.
#:
#: Then `org_defaults/floor.yaml` landed and made `security` inherited by every project — so on a
#: healthy install `test` is now the ONLY role that can be missing, and that shared sentence became
#: the only refusal a client can ever see. Measured: a manifest missing `test` was told to write
#: `security: "<your scanner>"` or to add a `stack: security-oss` component; both load, and neither
#: declares a `test` gate, so `floor_reason` returned the identical sentence afterwards. With the
#: floor unconditional that is a HOLD LOOP — the client does exactly what they were told and the
#: next tick holds again with the same words. A remedy that does not remedy is a failure wearing an
#: answer's clothes, which is what this function exists to prevent, so the text is per-role and
#: `tests/test_the_floor_is_a_deployment_default_not_a_transcription.py` APPLIES each one and
#: asserts the refusal lifts, rather than only asserting that it parses.
_ROLE_REMEDY: dict[str, str] = {
    # No `stack:` preset is offered for `test`, deliberately: `python` ships `test: pytest` but
    # `node` and `terraform` ship none, so pointing at "a preset" would be right for one client in
    # three. The command is the project's, which is also why `floor.yaml` defaults no `test` gate.
    "test": (
        'Declare a `test:` gate under `validate:` in `.openfactory/project.yaml` — e.g. '
        '`test: "pytest -q"`, or whatever one command runs this project\'s tests. There is no '
        'default the platform can guess: a command that exits 0 having tested nothing is a green '
        'light over an empty set.'
    ),
    "security": (
        'Declare a `security:` gate under `validate:` in `.openfactory/project.yaml` (`security: '
        '"<your scanner>"`), or put the role on a component — `components: {scan: {path: "**", '
        'stack: security-oss}}` — which is the schema-valid way to adopt the free advisory '
        'scanners.'
    ),
}

#: For a role added to `floor.REQUIRED_VALIDATION_ROLES` without a sentence written for it. Vague
#: but never WRONG, which is the only acceptable behaviour for a message nobody has reviewed;
#: `test_every_required_role_has_a_remedy_that_actually_LIFTS_the_refusal` fails the moment a third
#: role arrives, so this is a floor under the failure and not a way to avoid writing one.
_GENERIC_REMEDY = 'Declare a `{role}:` gate under `validate:` in `.openfactory/project.yaml`.'


def floor_reason(manifest: Manifest) -> str | None:
    """Why this project may not run a paid agent pass, or None.

    THE FLOOR WAS ONLY EVER CHECKED BY A CLI COMMAND. `REQUIRED_VALIDATION_ROLES` had exactly one
    reader — `check`, below — whose only caller is `openfactory conformance <name>`, which nothing
    in the
    job path invokes. So a project registered with a thin `validate:` block ran the agent, passed
    every gate vacuously (`all([])` was True), and was eligible for auto-merge: its entire quality
    floor was the empty set. Nothing would ever have told the client.

    HERE, AND NOT AT PICKUP, for a boring reason: the poller has no checkout. On the deployed
    worker `repo_path` is a placeholder that only exists inside the job, so the manifest cannot be
    read on a tick without fetching every repository every three minutes. This is the earliest
    point where the manifest is genuinely in hand — the runner has just been built — and it is
    still before any agent call, which is what the cost of the refusal is measured in.
    """
    available = _effective_validation(manifest)
    missing = sorted(r for r in floor.REQUIRED_VALIDATION_ROLES if r not in available)
    if not missing:
        return None
    roles = ", ".join(f"`{m}`" for m in missing)
    remedy = " ".join(_ROLE_REMEDY.get(m, _GENERIC_REMEDY.format(role=m)) for m in missing)
    remedy += " The next tick picks it up."
    if "security" in missing and org_default_validation() is None:
        # A DIFFERENT FAULT WEARING THE SAME SENTENCE. Every project inherits a `security` gate
        # from `org_defaults/floor.yaml`, so this role can only be missing when that file could
        # not be read — which is a broken INSTALL, not a client who forgot a line. Blaming the
        # client's repository here would send a stranger editing a file that is already correct.
        remedy = (
            "This deployment could not read its own default gates "
            "(`openfactory/org_defaults/floor.yaml`), so no project inherits one — see the "
            "OPENFACTORY_FLOOR_UNREADABLE line in the worker log. Fix the install, or declare "
            "`security:` under `validate:` in `.openfactory/project.yaml` to proceed without it."
        )
    return (
        f"this project declares no {roles} validation, and the platform's floor requires "
        f"{'both' if len(missing) > 1 else 'it'}. Nothing was run: a gate that does not exist "
        f"cannot pass, and a job whose gates are empty would report green having proven nothing. "
        f"{remedy}"
    )


def profile_gate_reason(manifest: Manifest, profile: ResolvedProfile | None) -> str | None:
    """A gate role the project's profile names at some risk level that no layer defines, or None.

    THE SAME POINT AND FOR THE SAME REASON `floor_reason` IS CHECKED: statically, from the
    manifest alone, before any agent call — the earliest a job has both a manifest and a resolved
    profile in hand. `RiskPolicy.gates` MAY ONLY EVER ADD: a risk level promotes a role already
    declared somewhere — the floor, a stack preset, repo-wide `validate:`, or a component
    override — from advisory to blocking. It cannot invent a command nobody wrote. A role a
    profile names that no layer defines is what `gates:` shipped with, once, before its consumer
    existed: `gates: [scurity]` (a typo) validated, resolved, and promoted nothing while a client
    believed their high-risk changes ran a security gate (ADR-0044, "What is NOT decided here").
    This turns that silent no-op into a hold with a voice.

    EVERY LEVEL THE PROFILE DECLARES, NOT ONLY THE ONE TODAY'S DIFF WILL REACH. There is no diff
    yet at this point in the job, and a `high`-only typo must not wait for the first high-risk
    ticket to be the one that catches it.
    """
    if profile is None:
        return None
    available = _effective_validation(manifest)
    by_level: dict[RiskLevel, list[str]] = {}
    for level in RiskLevel:
        undefined = sorted(g for g in profile.risk_policy(level).gates if g not in available)
        if undefined:
            by_level[level] = undefined
    if not by_level:
        return None
    parts = "; ".join(
        f"`{level.value}`: {', '.join(f'`{g}`' for g in roles)}"
        for level, roles in by_level.items()
    )
    return (
        f"this project's profile (`{' → '.join(profile.names)}`) names a gate role no layer "
        f"defines — {parts}. A profile may only promote a role that already runs somewhere — the "
        f"floor, a stack preset, repo-wide `validate:`, or a component's own override — never "
        f"invent one. Declare the role under `validate:` in `.openfactory/project.yaml`, put it "
        f"on a component, or adopt a stack preset that ships it; or, if it's a typo, fix it in "
        f"the profile. The next tick picks it up."
    )


def check(manifest: Manifest, repo_root: Path) -> ConformanceReport:
    issues: list[ConformanceIssue] = []

    # 0. Can this INSTALL state its own floor? Reported before anything about the project, because
    #    a missing `org_defaults/floor.yaml` makes the next check blame a client repository for a
    #    gate the platform failed to supply. An error, not a warning: it is the only issue in this
    #    report that no edit to `.openfactory/project.yaml` can fix.
    if org_default_validation() is None:
        issues.append(
            ConformanceIssue(
                level="error",
                message="this install cannot read its own default gates "
                "(openfactory/org_defaults/floor.yaml) — no project inherits a floor gate, so "
                "every "
                "project must declare `test` and `security` itself. Reinstall or rebuild the "
                "worker image; the worker log carries the OPENFACTORY_FLOOR_UNREADABLE line with "
                "the "
                "exact path and reason",
            )
        )

    # 1. The floor's required validation roles must be satisfiable somewhere.
    available = _effective_validation(manifest)
    for role in floor.REQUIRED_VALIDATION_ROLES:
        if role not in available:
            issues.append(
                ConformanceIssue(
                    level="error",
                    message=f"floor requires a '{role}' validation but none is "
                    f"declared or inherited from a preset",
                )
            )

    # 1b. WHICH ROLES ARE THE DEPLOYMENT'S AND NOT THIS PROJECT'S. Reported at warning level, and
    #     the level is the argument: inheriting the floor is a supported, correct configuration —
    #     it is what stops "adopt a security gate" from meaning "edit forty repositories" — but a
    #     client who reads `ok: True` and believes their own team declared a security scanner has
    #     been misled by a report that was technically true. Naming the command turns the claim
    #     into something checkable, and names the one-line way to replace it.
    for role in sorted(inherited_floor_roles(manifest)):
        cmd = _command_of(manifest.validation[role])
        issues.append(
            ConformanceIssue(
                level="warning",
                message=f"the '{role}' gate is the DEPLOYMENT's default, not this project's — it "
                f"runs on every diff as `{cmd[:120]}{'…' if len(cmd) > 120 else ''}`. Declare "
                f"`{role}:` under `validate:` to replace it with your own",
            )
        )

    # NOTE FOR THE NEXT READER, since its absence is the surprising part: there is deliberately no
    # "the deployment default overrode your preset's gate" issue here, because it never does.
    # `Manifest._inherit_the_deployment_floor` pins each touched component's preset command onto
    # the component before putting the default repo-wide, so per-component precedence keeps the
    # stronger scanner winning for its own diffs. If that pinning is ever removed, this is the
    # report that would have to grow the warning back.

    # 2. Declared component stacks must resolve to a known preset.
    known = set(available_stacks())
    for name, comp in manifest.components.items():
        if comp.stack not in known:
            issues.append(
                ConformanceIssue(
                    level="error",
                    message=f"component {name!r} uses unknown stack {comp.stack!r} "
                    f"(known: {sorted(known)})",
                )
            )

    # 3. Declared doc paths should exist (else the ticket points at fantasms).
    for role, glob in (
        ("constraints", manifest.docs.constraints),
        ("architecture", manifest.docs.architecture),
    ):
        if glob and not any(repo_root.glob(glob)):
            issues.append(
                ConformanceIssue(
                    level="warning",
                    message=f"docs.{role} glob {glob!r} matches no files",
                )
            )

    # 4. Thin docs are allowed but cost autonomy (D-9) — surface it, don't block.
    if not manifest.docs.constraints:
        issues.append(
            ConformanceIssue(
                level="warning",
                message="no docs.constraints (ADRs) declared — expect a stronger "
                "human gate; documentation is the investment that buys autonomy",
            )
        )

    ok = not any(i.level == "error" for i in issues)
    return ConformanceReport(ok=ok, issues=issues)
