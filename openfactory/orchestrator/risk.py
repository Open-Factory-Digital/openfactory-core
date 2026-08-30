"""What risk a change carries, and the declaration that says so.

`RiskLevel` is declared per component and documented as *"drives how strong the human gate is"*
(`contracts/state.py:60`). One place reads it — `merge_policy.is_auto_mergeable` asks whether any
touched component is `HIGH` — and that place throws the answer away: it returns a boolean, so
nobody reading a merged pull request can tell whether it touched a high-risk area. The information
existed at the moment of the decision and was discarded.

THE HOLE THIS CLOSES, and it is the same inversion this codebase names elsewhere as the sharpest
idea it has:

> *A file nothing describes is the least safe file to change, not the freest — reading the gate as
> "no concept, no objection" inverts it.*

`resolve_touched_components` returns only components whose glob matched. A diff path that matches
NO declared component simply is not in the list, so:

  * `is_auto_mergeable` loops over an empty list, finds no `HIGH`, and permits the merge;
  * the pull request body prints its "Touched components" line only when the list is non-empty, so
    the change reports NOTHING about components — silence, which a reader takes for "no components
    were involved" rather than "these paths are declared by nobody".

A project that declares components and then changes a path outside all of them has changed the part
of its repository nobody thought about, and that is precisely the change that auto-merges today.

THE DISTINCTION THAT KEEPS THIS FROM BREAKING SIMPLE PROJECTS. `components` defaults to `{}` and a
manifest without any is ordinary and correct — most projects do not need the concept. So:

    declares_nothing   the manifest declares NO components. Components are not this project's
                       mechanism, and risk is simply not being expressed. Nothing is gated on it.
    undeclared_paths   the manifest DOES declare components, and this change went outside all of
                       them. That is the silence worth catching.

Only the second gates. Treating both alike would send every simple project on `merge_policy: auto`
to a human for ever, which is the fix doing more damage than the defect.

WHAT IS NOT FIXED HERE, stated so it is not mistaken for done: `RiskLevel.LOW` is read by nothing.
`low` and `normal` are the same behaviour, and a client who writes `risk: low` gets exactly what
`normal` gets. Making `low` mean something is LOOSENING, and loosening needs the recorded,
named decision this platform does not have a mechanism for yet — a waiver or a profile. Until then
the honest thing is that this module says so rather than implying a gradient it does not have.
"""

from __future__ import annotations

from dataclasses import dataclass

from openfactory.contracts.manifest import Manifest
from openfactory.contracts.state import RiskLevel

#: Undeclared paths kept on the assessment. It travels into a pull request body a person reads, so
#: a change that moved four hundred files does not print four hundred lines — the count is exact
#: either way (`undeclared_count`).
MAX_UNDECLARED_SHOWN = 12

#: Highest first. `LOW` is here for completeness of the ordering, not because anything reads it.
_ORDER: tuple[RiskLevel, ...] = (RiskLevel.HIGH, RiskLevel.NORMAL, RiskLevel.LOW)


@dataclass(frozen=True)
class RiskAssessment:
    """The risk one change carries — the verdict AND the declaration that produced it.

    A verdict with no reason is a verdict nobody can argue with, and every gate in this platform
    that refuses something names what refused it.
    """

    #: the highest level among the components this change touched. None means NOTHING declared it:
    #: either the manifest declares no components at all, or this change went outside every one it
    #: does declare. `declares_nothing` tells those apart, and they are not the same fact.
    level: RiskLevel | None = None
    #: the components carrying `level`, sorted — the reason, not just the answer
    driven_by: tuple[str, ...] = ()
    #: every component this change touched, sorted
    touched: tuple[str, ...] = ()
    #: diff paths no declared component claims, sorted and capped at `MAX_UNDECLARED_SHOWN`
    undeclared_paths: tuple[str, ...] = ()
    #: how many there really were, so the cap above never reads as the total
    undeclared_count: int = 0
    #: the manifest declares no components AT ALL — components are not this project's mechanism,
    #: which is different from a project that uses them and changed something outside them
    declares_nothing: bool = False

    @property
    def undeclared(self) -> bool:
        """Did this change touch a path the manifest's own components do not cover?

        False when the manifest declares nothing: a project that does not use components has not
        failed to declare anything, and a gate that treated the two alike would send every simple
        project to a human for ever."""
        return bool(self.undeclared_paths) and not self.declares_nothing

    @property
    def needs_a_human(self) -> bool:
        """The merge-gate question, in one place so the answer and its reason cannot drift.

        HIGH stays what it has always been. Undeclared is the addition, and it tightens: a change
        in a part of the repository the manifest never described is the one this platform knows
        least about, and the least it can do is show it to somebody."""
        return self.level == RiskLevel.HIGH or self.undeclared

    @property
    def note(self) -> str:
        """One line, never empty. A reader of a merged pull request has to be able to see what the
        gate saw, and an assessment that says nothing when it found nothing is indistinguishable
        from one that never ran."""
        if self.declares_nothing:
            return "risk: not expressed — this manifest declares no components"
        parts: list[str] = []
        if self.level is None:
            parts.append("risk: UNDECLARED — nothing the manifest describes covers this change")
        else:
            named = f" ({', '.join(self.driven_by)})" if self.driven_by else ""
            parts.append(f"risk: {self.level.value}{named}")
        if self.undeclared_paths:
            shown = ", ".join(f"`{p}`" for p in self.undeclared_paths)
            more = (f" and {self.undeclared_count - len(self.undeclared_paths)} more"
                    if self.undeclared_count > len(self.undeclared_paths) else "")
            parts.append(f"{self.undeclared_count} path(s) no component declares: {shown}{more}")
        return " · ".join(parts)


def _build(manifest: Manifest, touched, undeclared: list[str],
           undeclared_count: int) -> RiskAssessment:
    """THE ONLY PLACE A `RiskAssessment` IS CONSTRUCTED, and that is the design, not tidiness.

    Two entries reach it — `assess`, from a diff, at the moment the change is resolved; and
    `of_attempt`, from what the attempt recorded, at the merge gate. Two builders would be two
    answers to "is this high risk", drifting the day one of them learned something. This module has
    already watched that happen elsewhere in this tree twice."""
    components = dict(getattr(manifest, "components", None) or {})
    if not components:
        return RiskAssessment(declares_nothing=True, undeclared_count=undeclared_count,
                              undeclared_paths=tuple(sorted(undeclared)[:MAX_UNDECLARED_SHOWN]))
    known = sorted(n for n in set(touched) if n in components)
    level: RiskLevel | None = None
    driven: tuple[str, ...] = ()
    for candidate in _ORDER:
        named = tuple(n for n in known if components[n].risk == candidate)
        if named:
            level, driven = candidate, named
            break
    return RiskAssessment(
        level=level,
        driven_by=driven,
        touched=tuple(known),
        undeclared_paths=tuple(sorted(undeclared)[:MAX_UNDECLARED_SHOWN]),
        undeclared_count=undeclared_count,
    )


def assess(diff_paths: list[str] | None, manifest: Manifest) -> RiskAssessment:
    """Read a change's risk off the manifest, from the diff. Pure, total, and never raises.

    `diff_paths` of None or `[]` means nothing changed — there is no risk to assess and no silence
    to catch. Neither is a refusal.
    """
    from openfactory.orchestrator.validation import _touches

    components = dict(getattr(manifest, "components", None) or {})
    paths = list(diff_paths or [])
    if not components:
        return _build(manifest, (), paths, len(paths))

    touched: set[str] = set()
    undeclared: list[str] = []
    for path in paths:
        owners = [name for name, comp in components.items() if _touches(path, comp.path)]
        if owners:
            touched.update(owners)
        else:
            undeclared.append(path)
    return _build(manifest, touched, undeclared, len(undeclared))


def of_attempt(manifest: Manifest, result) -> RiskAssessment:
    """The assessment for a finished attempt, from what the attempt recorded.

    The merge gate does not hold the diff — it holds a `RunResult`, whose `touched_components` was
    resolved from that diff after execution (ADR-0001 D-6, *the source of truth is the DIFF, not
    any label*). `undeclared_paths` is the half that was never recorded, so the gate could not see
    it and permitted the merge; recording it is most of this change.

    An attempt from before that field existed carries `undeclared_count` 0, which reads as "nothing
    was outside" — and that IS what the platform used to believe. It is not silently upgraded to
    "unknown" here: an old result cannot answer a question nobody asked it, and inventing a gate
    for it would refuse merges on evidence that does not exist."""
    return _build(manifest,
                  tuple(getattr(result, "touched_components", ()) or ()),
                  list(getattr(result, "undeclared_paths", ()) or ()),
                  int(getattr(result, "undeclared_count", 0) or 0))
