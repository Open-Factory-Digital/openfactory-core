"""The four silent gates, and the ten ways the guard against them becomes decoration.

Every row here produces a factory that runs, refuses correctly, and tells nobody why — which is
the state the platform was in when review found the same defect four times in one round. None of
them is an error; all of them are a human opening a pull request that looks exactly like one that
was simply ready to read.

ROWS 1-4 ARE THE FOUR GATES GOING SILENT AGAIN, one each. Two of them (`protected`, `census`) were
shipped that way and caught by review; two (`added_suppressions`, `profile`) were shipped that way
and caught by this guard when it was first written.

ROWS 5-7 ARE THE DECLARATION ROTTING. A gate added without declaring itself, a declared fact
quietly dropped, and an exemption reduced to a label nobody can argue with — the three ways a
mechanically-checked contract goes back to being prose.

ROWS 8-10 ARE THE GUARD ITSELF BECOMING DECORATION, which is the failure this whole file is a
response to. A branch walker that does not descend, a local resolution that stops at the variable
name, and a reachability check that no longer knows how many gates there are: each leaves a green
suite that has verified nothing.

ROWS 11-13 ARE THE ANY-TEST'S OWN BLIND SPOT REOPENING (review, #21): `names & declared` only
needed ONE name in a branch's condition to match, so a branch naming two facts — one declared, one
not — passed silently, and bumping the branch-count assertion (the only thing that DID go red) was
the natural, wrong response. Row 11 is the new `_facts_of` helper losing its anchor to `result`/
`manifest`, which makes the added ALL-test vacuous; rows 12-13 are `PART_OF_ANOTHER_FACT` eroding
the same two ways `SAYS_NOTHING_AND_WHY` already guards against for itself — a label instead of a
reason, and a name that collides with a fact already owed its own sentence.
"""

TEST = "tests/test_a_gate_that_holds_says_so_where_the_person_decides.py"

MUTATIONS = [
    # ── the four gates go silent again ───────────────────────────────────────────────────────────
    ("the verifier's-own-inputs gate holds the merge and the pull request says nothing about "
     "WHICH input changed — how `protected.reason` shipped, written and called by nothing",
     "openfactory/orchestrator/machine.py",
     '        if protected_note:\n            lines += ["", protected_note]',
     '        if False:\n            lines += ["", protected_note]'),

    ("the census gate holds the merge and the pull request never names the tests that stopped "
     "being collected — the signal that survives a count the noise moved the wrong way",
     "openfactory/orchestrator/machine.py",
     '        if census_note:\n            lines += ["", census_note]',
     '        if False:\n            lines += ["", census_note]'),

    ("a suppression that survived the repair loop holds the merge in silence, as it has since "
     "ADR-0011: a gate that was SILENCED reads exactly like a gate that passed",
     "openfactory/orchestrator/machine.py",
     "        if result.added_suppressions:\n"
     '            found = ", ".join(f"`{k}`" for k in sorted(set(result.added_suppressions)))',
     '        if False:\n            found = ""',

     ),

    ("the project's CLASS sends an ordinary change to a person and the pull request does not say "
     "so, so a regulated client reads a manifest that says `auto`, a risk note that says `normal`, "
     "and a platform that appears to have ignored their own configuration",
     "openfactory/orchestrator/machine.py",
     "        profile = getattr(self, \"_profile\", None)\n"
     "        if self.manifest.profile and profile is None:",
     "        profile = None\n        if False:"),

    # ── the declaration rots ─────────────────────────────────────────────────────────────────────
    ("a new gate holds the merge without declaring itself, so nothing ever checks that the pull "
     "request body learned to say it — which is how all four above arrived",
     "openfactory/orchestrator/merge_policy.py",
     "    if result.protected_hits:\n        return False",
     "    if result.protected_hits:\n        return False\n"
     "    if result.code_changed is False:\n        return False"),

    ("a declared fact is dropped from the table, so the gate that reads it goes unchecked and the "
     "contract silently covers less than it claims",
     "openfactory/orchestrator/merge_policy.py",
     '    "protected_hits":       "protected_hits",\n',
     ""),

    ("an exemption becomes a label rather than a reason, which is indistinguishable from a gate "
     "somebody forgot — the exact thing this guard exists to tell apart",
     "openfactory/orchestrator/merge_policy.py",
     '    "merge_policy": "not a hold. `merge_policy: human` is the project\'s own standing '
     'decision, "\n'
     '                    "made in its manifest before this ticket existed; announcing it on every "\n'
     '                    "pull request would be the platform explaining the client\'s configuration "\n'
     '                    "back to them, on every pull request, for ever.",',
     '    "merge_policy": "not a hold.",'),

    # ── the guard becomes decoration ─────────────────────────────────────────────────────────────
    ("the branch walker stops descending, so every gate nested inside another `if` — the whole "
     "suppression block — disappears from what this guard can see",
     TEST,
     "                walk(child, names)\n            else:\n                walk(child, outer)",
     "                pass\n            else:\n                walk(child, outer)"),

    ("a condition that reads a LOCAL stops being resolved to what fed it, so any gate hides behind "
     "a variable name — `before = result.test_census_before` is already that shape",
     TEST,
     "                for name in list(names):\n                    names |= resolved.get(name, set())",
     "                for name in list(names):\n                    pass"),

    # A TENTH ROW WAS WRITTEN AND REMOVED, and the removal is the finding. It weakened this file's
    # own branch-count assertion (`== 11` → `>= 0`) — a cut inside the single assertion that would
    # have to catch it, so no suite can be red for it. A row that cannot be killed is a row that
    # teaches the plan is complete when it is not. The property it aimed at is held by row 8
    # instead, which needs that count to be exact.

    # ── ANY → ALL: the declaration check gains a second, stricter half (review, #21) ────────────
    ("`_facts_of` stops recognising `result`/`manifest` as fact-bearing roots, so the ALL-test "
     "vacuously passes every branch — the exact ANY-test blind spot this change closes reopens",
     TEST,
     '            if isinstance(root, ast.Name) and root.id in ("result", "manifest"):\n'
     "                out.add(n.attr)",
     "            if False:\n                out.add(n.attr)"),

    ("a `PART_OF_ANOTHER_FACT` entry is reduced to a label, indistinguishable from a gate somebody "
     "forgot — the same erosion `SAYS_NOTHING_AND_WHY` already guards against for its own table",
     "openfactory/orchestrator/merge_policy.py",
     '    "test_census_after": "qualifies `test_census_before`, not a fact of its own. The two are '
     'one "\n'
     '                         "comparison — before against after — and `_pr_body`\'s census line "\n'
     '                         "already reads both to render the delta a person sees.",',
     '    "test_census_after": "qualifies test_census_before.",'),

    ("a name in `PART_OF_ANOTHER_FACT` collides with `HOLDS_THE_MERGE`, so the same fact is both "
     "owed its own sentence and waved through as somebody else's qualifier",
     "openfactory/orchestrator/merge_policy.py",
     '    "test_census_after": "qualifies `test_census_before`',
     '    "test_census_before": "qualifies `test_census_before`'),
]
