"""The risk verdict, and the fourteen ways a change nobody described merges unattended again.

THE HOLE. `RiskLevel` is declared per component and documented as *"drives how strong the human
gate is"*. One place read it: `merge_policy` looped over the components the diff MATCHED and looked
for `HIGH`. `resolve_touched_components` returns only what matched — so a change whose every path
matched no component walked an EMPTY list, found no `HIGH`, and merged with nobody looking. The
pull request body printed its "Touched components" line only when the list was non-empty, so that
change also said nothing at all: silence, which reads as "no components were involved" rather than
"these paths are declared by nobody".

That is *no concept, no objection* — the inversion this codebase names elsewhere as the sharpest
idea it has — sitting in the gate that decides whether a person ever sees the merge.

ROWS 5-7 ARE THE FIX DOING MORE DAMAGE THAN THE DEFECT, and they are the reason this is not four
lines. `components` defaults to `{}` and a manifest without any is ordinary and correct. A project
that does not use components has not FAILED to declare anything, and a version that gated it would
send every simple project on `merge_policy: auto` to a human for ever. The distinction between
"declares nothing" and "declares some and missed these" is load-bearing in both directions.

ROWS 12-14 CUT THE OTHER WAY, the discipline this directory adopted with the trajectory plan:
restore the defect AND over-tighten the fix, because "the gate that now refuses everything" is the
failure an over-eager correction produces and only the reverse cut can see it.
"""

TEST = "tests/test_a_path_nothing_declares_is_not_the_freest.py"

MUTATIONS = [
    # ── the defect, restored ────────────────────────────────────────────────────────────────────
    ("an undeclared path stops gating — the hole exactly as it shipped: a change outside every "
     "component the manifest declares merges with nobody looking at it",
     "openfactory/orchestrator/risk.py",
     "        return self.level == RiskLevel.HIGH or self.undeclared",
     "        return self.level == RiskLevel.HIGH"),

    ("a path matching no component is quietly dropped instead of recorded, so the assessment "
     "reports a clean change and the count it would have gated on is zero",
     "openfactory/orchestrator/risk.py",
     "        else:\n            undeclared.append(path)",
     "        else:\n            pass"),

    ("the merge gate stops asking the assessment and walks the matched components again — two "
     "answers to \"is this high risk\", which is how the two drift",
     "openfactory/orchestrator/merge_policy.py",
     "    return not of_attempt(manifest, result).needs_a_human",
     "    return not any((manifest.components.get(n) and\n"
     "                    manifest.components[n].risk.value == \"high\")\n"
     "                   for n in result.touched_components)"),

    ("the attempt records the components it matched and not the paths it could not place, so the "
     "gate reads what it always read and the new half never reaches it",
     "openfactory/orchestrator/machine.py",
     "            result.undeclared_paths = list(assessment.undeclared_paths)\n"
     "            result.undeclared_count = assessment.undeclared_count",
     "            pass"),

    # ── the fix doing more damage than the defect ───────────────────────────────────────────────
    ("a manifest that declares NO components is gated too, so every simple project on "
     "`merge_policy: auto` — the common case, and the one the operator thesis depends on — goes "
     "to a human for ever",
     "openfactory/orchestrator/risk.py",
     "        return bool(self.undeclared_paths) and not self.declares_nothing",
     "        return bool(self.undeclared_paths)"),

    ("\"declares nothing\" and \"declares some and missed these\" render identically, so a reader "
     "draws the same conclusion from a project that is fine and one that is not",
     "openfactory/orchestrator/risk.py",
     '            return "risk: not expressed — this manifest declares no components"',
     '            return "risk: UNDECLARED — nothing the manifest describes covers this change"'),

    ("a component-less manifest is treated as one that declares components, so the empty-dict "
     "branch never fires and the distinction has no code behind it",
     "openfactory/orchestrator/risk.py",
     "    if not components:\n        return RiskAssessment(declares_nothing=True,",
     "    if False:\n        return RiskAssessment(declares_nothing=True,"),

    # ── the verdict loses its reason ────────────────────────────────────────────────────────────
    ("the assessment names no component, so a refused merge is a verdict nobody can argue with — "
     "the one thing every other gate in this platform does not do",
     "openfactory/orchestrator/risk.py",
     "            level, driven = candidate, named",
     "            level, driven = candidate, ()"),

    ("only the FIRST component at the driving level is named, so a change touching two high-risk "
     "areas reports one and a reader goes to look at half of it",
     "openfactory/orchestrator/risk.py",
     "        named = tuple(n for n in known if components[n].risk == candidate)",
     "        named = tuple(n for n in known if components[n].risk == candidate)[:1]"),

    ("the pull request says nothing about risk, so the verdict the gate reached is invisible on "
     "the very pull request the gate decided about",
     "openfactory/orchestrator/machine.py",
     '        risk_note = risk_of_attempt(self.manifest, result).note\n'
     '        if not risk_note.startswith("risk: not expressed"):\n'
     '            lines += ["", risk_note]',
     "        pass"),

    # ROW REWRITTEN. The first version added a default to a parameter every caller already passes
    # — a no-op that mutated nothing and "survived" a guard that was never at risk. A cut that does
    # not cut is worse than no cut: it reports coverage that was never exercised.
    ("the cap on undeclared paths becomes the COUNT, so a change that moved four hundred files "
     "reports twelve of them and reads as complete about the other three hundred and eighty-eight",
     "openfactory/orchestrator/risk.py",
     "        undeclared_paths=tuple(sorted(undeclared)[:MAX_UNDECLARED_SHOWN]),\n"
     "        undeclared_count=undeclared_count,",
     "        undeclared_paths=tuple(sorted(undeclared)[:MAX_UNDECLARED_SHOWN]),\n"
     "        undeclared_count=min(undeclared_count, MAX_UNDECLARED_SHOWN),"),

    # ── THE OTHER DIRECTION ─────────────────────────────────────────────────────────────────────
    ("OVER-TIGHTENED — any risk above `low` gates, so `normal`, which is the DEFAULT every "
     "component gets, stops auto-merging. The gate now refuses nearly everything, and it refuses "
     "it on a value nobody chose",
     "openfactory/orchestrator/risk.py",
     "        return self.level == RiskLevel.HIGH or self.undeclared",
     "        return self.level != RiskLevel.LOW or self.undeclared"),

    ("OVER-TIGHTENED — a change that touched nothing at all is treated as undeclared, so an empty "
     "diff needs a human and the repair loop can never close one",
     "openfactory/orchestrator/risk.py",
     "        return bool(self.undeclared_paths) and not self.declares_nothing",
     "        return not self.touched and not self.declares_nothing"),

    # ROW REWRITTEN, for the same reason as the cap row: `undeclared_count` is a pydantic field
    # with a default, so `hasattr` is ALWAYS true and the first version's branch could never fire.
    ("OVER-TIGHTENED — a change that placed every path is read as unplaceable, so a project whose "
     "components cover everything is gated on every merge and the declaration it wrote earns it "
     "nothing",
     "openfactory/orchestrator/risk.py",
     "        return bool(self.undeclared_paths) and not self.declares_nothing",
     "        return not self.declares_nothing"),
]
