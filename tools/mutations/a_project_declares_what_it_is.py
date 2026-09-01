"""What a project IS, and the thirteen ways a class of project quietly stops meaning anything.

The defect this closes is a sentence, not a crash: `_org_defaults` injected every framework
guideline *"into EVERY job regardless of project"*, so a proof-of-concept and a regulated bank
received the same twelve rules and the same TDD mandate. Almost every way that can regress
produces a RUNNING FACTORY rather than an error — a profile that resolves and changes nothing, a
class that is silently not applied — which is why the plan is long for a change this size.

ROWS 1-4 ARE THE FEATURE HAVING NO PRODUCTION CALLER — the way it shipped the first time,
with every behavioural test green. ROWS 5-7 ARE THE MECHANISM CEASING TO EXIST while every call
site still works. A profile that
resolves and is never read is indistinguishable from no profile at all, and the only witness is a
guideline that should have been absent and was not.

ROWS 4-6 ARE THE FAILURE DIRECTION OPENING. Each turns a hold into a shrug: a name nobody defined,
a caller that did not resolve the class, an unreadable file. All three end the same way — a project
that believes it is regulated running under the generic rules, silently, which is the one shape
this design exists to refuse.

ROWS 7-8 CUT THE OTHER WAY, the discipline this directory keeps. A version that gated everything
would satisfy rows 4-6 perfectly and be worse than the defect: `risk.py` already names the cost —
*"every simple project on `merge_policy: auto` to a human for ever"*. Row 8 is the same over-tighten
one layer up, where a project with no class at all starts paying for the feature.

ROW 9 IS THE PACKAGING TWIN, and it is the only row that is green on every developer's machine.
"""

TEST = "tests/test_a_project_declares_what_it_is.py"

MUTATIONS = [
    # ── THE FEATURE HAS NO PRODUCTION CALLER, which is how this shipped the first time ──────────
    #
    # Every row below this group mutates a function only the tests call. The first version of this
    # plan was ALL of those rows, so 9/9 red said nothing about whether a single real job resolves
    # a class. Reported by review on PR #17; these three are the rows that would have caught it.
    ("nothing in the machine resolves the manifest's class, so the whole mechanism is unreachable "
     "outside the suite and a prototype receives the mandate it waives",
     "openfactory/orchestrator/machine.py",
     "            self._profile = resolve_profile(self.manifest.profile, "
     "project_dir=self.repo_path)",
     "            self._profile = None"),

    ("the context is built without the class, so the guideline half — the ADR's headline — is "
     "inert in every real run while every behavioural test still passes",
     "openfactory/orchestrator/machine.py",
     "                            # resolved once at the top of the job; `getattr` because not "
     "every\n"
     "                            # path through this class reaches that point (the sizer builds "
     "a\n"
     "                            # context of its own), and a missing class is the ordinary "
     "case.\n"
     "                            profile=getattr(self, \"_profile\", None))",
     "                            )"),

    ("the merge gate is not told the class, which does not merely disable the strengthening: "
     "`manifest.profile and profile is None` then holds EVERY project that declares any class, "
     "for ever, so adopting a profile becomes strictly worse than not adopting one",
     "openfactory/orchestrator/machine.py",
     "            if should_auto_merge(self.manifest, result,\n"
     "                                 profile=getattr(self, \"_profile\", None)):",
     "            if should_auto_merge(self.manifest, result):"),

    ("an unresolvable class stops holding the job, so `profile: zzz-typo` runs as the generic "
     "case and the ProfileError never reaches a client",
     "openfactory/orchestrator/machine.py",
     "        except ProfileError as exc:\n"
     "            self._emit(ticket, \"note\", f\"⚠️ profile: {exc}\")\n"
     "            return self._hold(ticket, owner, str(exc), JobState.ON_HOLD)",
     "        except ProfileError:\n            self._profile = None"),

    # ── the mechanism stops being read, while everything still runs ─────────────────────────────
    ("the class is resolved and never reaches the guidelines, so the POC and the bank are the same "
     "project again and the only symptom is a TDD mandate nobody asked for",
     "openfactory/orchestrator/context.py",
     "    guidelines = _org_defaults(profile, repo_path)",
     "    guidelines = _org_defaults()"),

    ("a waive is read and not applied, so the profile resolves, the panel would name the class, and "
     "the waived guideline is injected anyway — the declaration becomes decoration",
     "openfactory/orchestrator/context.py",
     "        if p.name in waived:\n            continue",
     "        if False:\n            continue"),

    ("the merge gate stops asking the class, so a regulated project auto-merges a high-risk change "
     "exactly as it did before profiles existed",
     "openfactory/orchestrator/merge_policy.py",
     "    if profile is not None and profile.requires_human(assessment.level):\n        return False",
     "    if False:\n        return False"),

    # ── the failure direction opens: every one of these turns a hold into a shrug ────────────────
    ("a profile nobody defined degrades to no profile, so a manifest declaring `profile: regulated` "
     "on a deployment that never received the file runs as the generic case and says nothing",
     "openfactory/policy/profiles.py",
     "        raise ProfileError(\n"
     '            f"the manifest declares `profile: {name}` and no such profile exists. Looked in: "',
     "        return Profile(name=name)  # type: ignore[unreachable]\n"
     '        raise ProfileError(\n'
     '            f"the manifest declares `profile: {name}` and no such profile exists. Looked in: "'),

    ("a caller that never resolved the class is read as a project with no class, so the one moment "
     "the wiring is wrong is the moment the strengthening silently does not apply",
     "openfactory/orchestrator/merge_policy.py",
     "    if manifest.profile and profile is None:",
     "    if False:"),

    ("an empty profile file is read as a class with no opinion instead of a file that declares "
     "nothing, so a truncated or half-written profile passes as a deliberate one",
     "openfactory/policy/profiles.py",
     "    if raw is None:\n        raise ProfileError(",
     "    if raw is None:\n        return {}\n    if False:\n        raise ProfileError("),

    # ── the reverse cuts: the fix doing more damage than the defect ──────────────────────────────
    ("an undetermined risk level is treated as HIGH, which looks like prudence and sends every "
     "simple project on `merge_policy: auto` to a human for ever — the exact cost `risk.py` names",
     "openfactory/policy/profiles.py",
     "        if level is None:\n            return False",
     "        if level is None:\n            return self.risk_policy(RiskLevel.HIGH).merge == 'human'"),

    ("a project that declares NO class starts paying for the feature: the baseline it has always "
     "received is filtered through an empty profile, so the change is a migration in disguise",
     "openfactory/orchestrator/context.py",
     "    if profile is None:\n        return [p.read_text()[:_MAX_DOC_CHARS] for p in baseline]",
     "    if False:\n        return [p.read_text()[:_MAX_DOC_CHARS] for p in baseline]"),

    # ── the packaging twin, green on every developer's machine ───────────────────────────────────
    ("the one-level glob comes back, so the mechanism ships with no worked example: `prototype` "
     "resolves on the tree that wrote it and is a ProfileError on every pip install",
     "pyproject.toml",
     '"org_defaults/**/*.yaml"',
     '"org_defaults/*.yaml"',
     # ITS GUARD LIVES IN ANOTHER FILE, which is exactly why this row names its own target: the
     # first run scored it GREEN against the profile suite, and a row nobody aimed correctly is a
     # guard nobody has.
     "tests/test_the_wheel_ships_what_the_platform_needs.py"),
]
