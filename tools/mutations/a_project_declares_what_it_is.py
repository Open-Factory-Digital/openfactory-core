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

ROWS 10-17 ARE `gates:` LANDING ITS CONSUMER — the field that shipped once, was read by nothing,
and was pulled rather than left silently inert (ADR-0044, "What is NOT decided here"). The same
two failure shapes recur one layer up: rows 10-12 are the hold/promotion mechanism existing and
not being reached or applied (the field ships inert a second time, differently); row 13 is the
undefined-role check narrowing to only the level today happens to exercise; row 14 is the reverse
cut — a project with no risk assessed starts being promoted anyway; row 15 is a no-profile project
starting to pay, the same shape as row 8 one layer up; row 16 is the `_GateHost` reuse boundary
`_run_validations` was deliberately kept clear of, given its own regression proof by name; row 17
is the blank-string accident on the new field, the same one rows already guard on `waive`/`extend`.
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

    # ── `gates:` LANDS ITS CONSUMER — the field ADR-0044 shipped inert once already ──────────────
    ("the undefined-role hold never fires, so a profile naming a gate role no layer defines "
     "resolves silently and promotes nothing — the exact defect `gates:` shipped with once, one "
     "call site later",
     "openfactory/orchestrator/machine.py",
     "        # A GATE THE PROFILE NAMES MUST ALREADY EXIST TO BE PROMOTED. Checked here, "
     "statically,\n"
     "        # the same point and for the same reason the floor is checked above — before any "
     "agent\n"
     "        # call. `RiskPolicy.gates` can only promote a role some other layer already runs; "
     "a role\n"
     "        # nothing defines is the exact silent no-op `gates:` shipped with once (ADR-0044).\n"
     "        if (gate_issue := profile_gate_reason(self.manifest, self._profile)) is not None:\n"
     "            self._emit(ticket, \"note\", f\"⚠️ profile gates: {gate_issue}\")\n"
     "            return self._hold(ticket, owner, gate_issue, JobState.ON_HOLD)\n",
     ""),

    ("promotion is computed and never applied, so a HIGH-risk change under `regulated` still runs "
     "`security` advisory — the finding is reported and the merge and repair loop never see it",
     "openfactory/orchestrator/machine.py",
     "            advisory = gate.advisory and name not in promoted_gates",
     "            advisory = gate.advisory"),

    ("`gates` stops accumulating across the `extends` chain, so every profile's risk policy "
     "resolves with nothing to promote regardless of what its YAML declares",
     "openfactory/policy/profiles.py",
     "            for g in pol.gates:\n                if g not in gates:\n"
     "                    gates.append(g)",
     ""),

    ("the undefined-role check narrows to a single level, so a typo at `normal` in a profile only "
     "ever exercised at `high` ships silently and is never caught",
     "openfactory/policy/conformance.py",
     "    for level in RiskLevel:",
     "    for level in [RiskLevel.HIGH]:"),

    ("a risk level of `None` is treated as HIGH for promotion, so a project with no risk assessed "
     "at all — no components, or a change outside every declared one — starts being promoted "
     "anyway, the same over-tighten `requires_human` already refuses for `merge`",
     "openfactory/policy/profiles.py",
     "        if level is None:\n            return frozenset()\n"
     "        return frozenset(self.risk_policy(level).gates)",
     "        if level is None:\n            level = RiskLevel.HIGH\n"
     "        return frozenset(self.risk_policy(level).gates)"),

    ("a project with NO profile starts paying for the feature: `getattr` still returns `None`, "
     "but the guard that keeps it a no-op is gone, so the call crashes instead of skipping",
     "openfactory/orchestrator/machine.py",
     "        promoted = profile.promoted_gates(self._risk.level) if profile is not None "
     "else frozenset()",
     "        promoted = profile.promoted_gates(self._risk.level) if True else frozenset()",
     "tests/test_a_suite_that_stopped_collecting_is_not_a_green_suite.py"),

    ("`_run_validations` reads `self._profile`/`self._risk` directly instead of taking promotion "
     "as a parameter, which reopens the exact reuse boundary this design was built around: "
     "`onboarding.firstrun._GateHost` carries neither, so the first round's gate stage would raise",
     "openfactory/orchestrator/machine.py",
     "            advisory = gate.advisory and name not in promoted_gates",
     "            advisory = gate.advisory and name not in ("
     "self._profile.promoted_gates(self._risk.level) if self._profile else frozenset())",
     "tests/test_onboarding_firstrun.py"),

    ("the blank-strip validator on `gates` is cut, so a stray blank entry under `gates:` promotes "
     "nothing while reading as though it promoted something — the same accident `waive`/`extend` "
     "already guard on the sibling model",
     "openfactory/contracts/profile.py",
     "    @field_validator(\"gates\")\n    @classmethod\n"
     "    def _no_blanks(cls, v: list[str]) -> list[str]:\n"
     "        # The same accident `GuidelinePolicy._no_blanks` guards on a sibling field: a stray "
     "`-`\n"
     "        # under `gates:` would otherwise promote nothing while reading as though it "
     "promoted\n"
     "        # something.\n"
     "        return [s for s in (x.strip() for x in v) if s]",
     "    @field_validator(\"gates\")\n    @classmethod\n"
     "    def _no_blanks(cls, v: list[str]) -> list[str]:\n        return v"),
]
