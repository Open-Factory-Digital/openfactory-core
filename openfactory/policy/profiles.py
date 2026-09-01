"""Resolve a project's profile — the cascade layer that says what the project IS.

WHERE PROFILES LIVE, and it is the placement rule this codebase already wrote down about `model`
(*"the client declares what to validate, not which model writes their code"*): a profile changes
**how code is written**, so it belongs to whoever maintains the code, in a diff a human reads.

    framework   openfactory/org_defaults/profiles/*.yaml            worked examples, in the wheel
    project     <checkout>/.openfactory/profiles/*.yaml              the client's own, in a PR

Callers pass the CHECKOUT ROOT; this module appends `.openfactory/profiles`.

THE PROJECT LAYER WINS, and that is the opposite of `role_prompt`'s rule on purpose. There, an
ADD-ON package offering a `techlead.md` is refused, because a third-party package silently changing
what the tech-lead means for every project on the deployment is a supply-chain problem. Here the
overriding layer is the client's own repository declaring their own policy — that is not a
third party and it is the entire point. The two rules disagree because the threat models do.

A NAME THAT DOES NOT RESOLVE IS A HOLD, NOT A SHRUG. If the manifest says `profile: regulated` and
nothing defines `regulated`, the honest reading is that this project believes it is running under
rules the platform never applied. Degrading to "no profile" would run a regulated project as the
generic case — dropping the strengthening the class exists to add, silently, in exactly the
installation where nobody is watching. So resolution raises and the caller holds the project. The
failure direction is closed, the same way the floor's is.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from openfactory.contracts.profile import MAX_EXTENDS_DEPTH, Profile, RiskPolicy
from openfactory.contracts.state import RiskLevel

log = logging.getLogger("openfactory.policy.profiles")

FRAMEWORK_PROFILES_DIR = Path(__file__).resolve().parent.parent / "org_defaults" / "profiles"

#: Where a client's own profiles live, RELATIVE TO THE CHECKOUT ROOT — and the function owns this
#: rather than the caller. An earlier version joined only `profiles/`, which made every user-facing
#: sentence in the repo (`.openfactory/profiles/<name>.yaml`, in the docstring, the manifest
#: comment, `project.yaml.example` and the ADR) true only if every caller remembered to pass
#: `repo/.openfactory`. Nothing established that, so a client following the documentation got a
#: `ProfileError`. The one contract a client has to get right is now the one thing the code states.
PROJECT_PROFILES_SUBDIR = Path(".openfactory") / "profiles"


class ProfileError(Exception):
    """A profile was named and could not be honoured. Never degraded into an absent profile."""


class ResolvedProfile:
    """One profile with its `extends` chain already flattened.

    Kept as a plain object rather than a model because it is a RESULT, not a declaration: nothing
    parses it, one thing builds it, and several things read it.
    """

    def __init__(self, chain: list[Profile]) -> None:
        #: outermost last — the profile the manifest actually named is `chain[-1]`
        self.chain = chain

    @property
    def name(self) -> str:
        return self.chain[-1].name if self.chain else ""

    @property
    def names(self) -> tuple[str, ...]:
        """The whole chain, base first — what a PR body prints so a reader sees the composition
        rather than only the leaf that happens to be named."""
        return tuple(p.name for p in self.chain)

    @property
    def summary(self) -> str:
        for p in reversed(self.chain):
            if p.summary:
                return p.summary
        return ""

    def waived_guidelines(self) -> tuple[str, ...]:
        """Framework baseline filenames this class does not operate under, accumulated.

        ACCUMULATED AND NEVER UN-WAIVED: a profile that extends another cannot resurrect a
        guideline its base dropped. Allowing it would make the strength of a class depend on the
        order two authors happened to write their files in, and a reader could no longer answer
        "does this project do TDD?" from the leaf alone.
        """
        out: list[str] = []
        for p in self.chain:
            for name in p.guidelines.waive:
                if name not in out:
                    out.append(name)
        return tuple(out)

    def replaced_guidelines(self) -> dict[str, str]:
        """`{framework filename: path in the checkout}`, outermost wins."""
        out: dict[str, str] = {}
        for p in self.chain:
            out.update(p.guidelines.replace)
        return out

    def extra_guidelines(self) -> tuple[str, ...]:
        """Extra checkout-relative paths, base first, de-duplicated with the first position kept."""
        out: list[str] = []
        for p in self.chain:
            for path in p.guidelines.extend:
                if path not in out:
                    out.append(path)
        return tuple(out)

    def risk_policy(self, level: RiskLevel) -> RiskPolicy:
        """The accumulated policy at one risk level.

        `merge` is `human` if ANY layer in the chain says so: the strongest opinion in the chain is
        the one that survives, so extending a stricter base can never relax it.
        """
        merge: str | None = None
        for p in self.chain:
            pol = p.risk.get(level)
            if pol is not None and pol.merge == "human":
                merge = "human"
        return RiskPolicy(merge=merge)

    def requires_human(self, level: RiskLevel | None) -> bool:
        """Whether this class sends `level` to a person regardless of `merge_policy: auto`.

        `None` IS NOT READ AS HIGH, and the first draft of this method got that wrong in a way its
        own test caught. `orchestrator/risk.py` separates two things that both arrive here as
        "no level": a manifest that declares NO components (ordinary — most projects do not need
        the concept) and a change that went OUTSIDE every component a manifest does declare (the
        silence worth catching). Treating `None` as HIGH collapses them, and `risk.py` names the
        cost of exactly that: it *"would send every simple project on `merge_policy: auto` to a
        human for ever, which is the fix doing more damage than the defect"*.

        The dangerous half is already gated, and gated BEFORE this is asked: `should_auto_merge`
        refuses on `RiskAssessment.needs_a_human`, which is where `undeclared_paths` lives. So a
        profile adds its opinion to a level that was actually determined, and adds nothing to a
        project that simply does not use components.
        """
        if level is None:
            return False
        return self.risk_policy(level).merge == "human"


def _read(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ProfileError(f"the profile at {path} could not be read ({exc})") from exc
    if raw is None:
        raise ProfileError(
            f"the profile at {path} is empty — a file that declares nothing is not a class of "
            f"project, and a project pointing at it would run under rules nobody wrote")
    if not isinstance(raw, dict):
        raise ProfileError(
            f"the profile at {path} must be a YAML mapping, not {type(raw).__name__}")
    return raw


def _locate(name: str, project_dir: Path | None) -> Path | None:
    if project_dir is not None:
        candidate = project_dir / PROJECT_PROFILES_SUBDIR / f"{name}.yaml"
        if candidate.is_file():
            return candidate
    shipped = FRAMEWORK_PROFILES_DIR / f"{name}.yaml"
    return shipped if shipped.is_file() else None


def load_profile(name: str, *, project_dir: Path | None = None) -> Profile:
    """One profile by name, project layer first. Raises `ProfileError` if it does not resolve."""
    path = _locate(name, project_dir)
    if path is None:
        looked = [str(FRAMEWORK_PROFILES_DIR / f"{name}.yaml")]
        if project_dir is not None:
            looked.insert(0, str(project_dir / PROJECT_PROFILES_SUBDIR / f"{name}.yaml"))
        raise ProfileError(
            f"the manifest declares `profile: {name}` and no such profile exists. Looked in: "
            + ", ".join(looked)
            + f". Available here: {', '.join(available_profiles(project_dir)) or 'none'}")
    data = _read(path)
    declared = data.get("name")
    if declared is not None and str(declared).strip() != name:
        # `profiles/bank.yaml` declaring `name: regulated` would resolve under `bank`, report
        # `regulated` in `names` — the very field a PR body prints so a reader can see the
        # composition — and be invisible to a sibling's `extends: regulated`. The reader would be
        # shown a name the manifest never wrote.
        raise ProfileError(
            f"the profile at {path} declares `name: {declared}` and is filed as `{name}`. The "
            f"filename is the address a manifest and an `extends:` use, so the two cannot differ.")
    data["name"] = name
    try:
        return Profile.model_validate(data)
    except ValidationError as exc:
        raise ProfileError(f"the profile at {path} is not valid: {exc}") from exc


def available_profiles(project_dir: Path | None = None) -> list[str]:
    """Every profile name resolvable here — the project's own and the shipped examples."""
    names = {p.stem for p in FRAMEWORK_PROFILES_DIR.glob("*.yaml")} if (
        FRAMEWORK_PROFILES_DIR.is_dir()) else set()
    if project_dir is not None:
        d = project_dir / PROJECT_PROFILES_SUBDIR
        if d.is_dir():
            names |= {p.stem for p in d.glob("*.yaml")}
    return sorted(names)


def resolve_profile(name: str | None, *, project_dir: Path | None = None) -> ResolvedProfile | None:
    """Flatten `name` and everything it extends. `None` in, `None` out — a project that declares
    no profile is ordinary and correct, and most projects will not need one.

    That `None` is the same distinction `orchestrator/risk.py` draws between `declares_nothing`
    and `undeclared_paths`: not declaring a class is a legitimate configuration, and it is not the
    same fact as naming a class that could not be found.
    """
    if name is None or not name.strip():
        return None
    chain: list[Profile] = []
    seen: list[str] = []
    current: str | None = name.strip()
    while current is not None:
        if current in seen:
            raise ProfileError(
                "profile `extends` forms a cycle: " + " → ".join([*seen, current])
                + ". A class of project cannot be defined in terms of itself.")
        if len(seen) >= MAX_EXTENDS_DEPTH:
            raise ProfileError(
                f"profile `extends` is nested deeper than {MAX_EXTENDS_DEPTH} "
                f"({' → '.join([*seen, current])}). That is a declaration to flatten, not a "
                f"hierarchy to walk.")
        seen.append(current)
        profile = load_profile(current, project_dir=project_dir)
        chain.append(profile)
        current = profile.extends
    # base first: the profile the manifest named is applied last, so it wins.
    chain.reverse()
    return ResolvedProfile(chain)
