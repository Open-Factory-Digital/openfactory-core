"""A probe set is pinned whole, and a budget nothing spends is not a defect.

TWO GUARDS, ONE ACCIDENT. The export's first CI run over the public repository went red on three
tests (`3 failed, 7902 passed, 161 skipped`) because a new probe — `api_budget` — answered
differently on a machine that was not the author's, exactly as `agent_credential` had three days
earlier. Underneath the class sat a product question nobody had asked: the stranger following
docs/ONBOARDING.md §2 was being told "NOT ready — fix the FAIL lines above" over an API quota
nothing was spending yet.

So the cuts come in two halves. The first restores the shapes that made a test read the machine;
the second restores the verdict a stranger got. Every one must go RED.
"""

DOCTOR = "openfactory/doctor.py"
CLI = "openfactory/cli.py"
HELPER = "tests/pinned_probes.py"
REVIEW = "tests/test_the_review_findings_stay_fixed.py"
ONBOARDING = "docs/ONBOARDING.md"

TEST = "tests/test_a_probe_set_is_pinned_whole.py"
BUDGET = "tests/test_a_budget_nothing_spends_is_not_a_defect.py"

# ── THE GUARD HALF: a member nobody pinned ──────────────────────────────────────────────────────

MUTATIONS = [
    # THE ACCIDENT ITSELF, in the form it will take next time: a sixteenth member joins the
    # dataclass and no green answer joins with it. Absence must not read as compliance.
    ("doctor.Probes grows a member with no green answer", DOCTOR,
     "    open_proposal: Callable[[], str] | None = None",
     "    open_proposal: Callable[[], str] | None = None\n"
     "    #: (mutation) the probe nobody has pinned yet\n"
     "    quota_reset_horizon: Callable[[], int] | None = None"),

    # THE HELPER GOING QUIET INSTEAD OF LOUD — the same defect one layer in: a member with no
    # answer would simply fall back to the dataclass's default and the check would vanish.
    ("the helper stops refusing a member it has no green answer for", HELPER,
     "    if unanswered:\n        raise AssertionError(",
     "    if unanswered:\n        unanswered = []\n    if unanswered:\n        raise AssertionError("),

    # A "GREEN" ANSWER THAT IS NOT GREEN. The table cannot be believed on its own word; the
    # baseline is green only if the real `diagnose` says so.
    ("a green answer stops being green", HELPER,
     '    "docker_running": lambda: (True, ""),',
     '    "docker_running": lambda: (False, ""),'),

    # THE OPTIONAL PROBES LEFT OUT, which is the state the nine call sites were in: their checks
    # do not fail, they stop being run at all — built, tested, reached by nothing.
    ("the helper skips every optional member, so four checks never run", HELPER,
     "        if member.name in over:\n            continue  # the caller is measuring this one",
     "        if member.name in over:\n            continue  # the caller is measuring this one\n"
     "        if member.default is not dataclasses.MISSING:\n            continue"),

    # A TEST GOING BACK TO THE MACHINE, in the aliased spelling nine call sites used.
    ("a test builds its probe set out of the real `probes_for` again", REVIEW,
     '    monkeypatch.setattr(doc, "probes_for", lambda _project: a_fully_pinned_probe_set(\n'
     '        box_gate=lambda: "the box has never been proven — run `openfactory box prove '
     'demo`"))',
     "    import dataclasses\n"
     "    real = doc.probes_for\n"
     '    monkeypatch.setattr(doc, "probes_for", lambda p: dataclasses.replace(\n'
     "        real(p),\n"
     '        box_gate=lambda: "the box has never been proven — run `openfactory box prove '
     'demo`"))',
     TEST),

    # AND THE DETECTOR ITSELF, because a sweep that says "nothing in this directory does X" is
    # worth exactly what it can see: five probes in one day here have passed for the wrong reason.
    ("the sweep stops following the `real = doc.probes_for` alias", TEST,
     "            aliases.update(t.id for t in node.targets if isinstance(t, ast.Name))",
     "            pass"),
]

# ── THE PRODUCT HALF: the verdict a stranger reads at §2 ────────────────────────────────────────

MUTATIONS += [
    # THE DEFECT AS SHIPPED: the finding carries no attribution, so the closing verdict calls a
    # registered-but-unproven project broken.
    ("an unreadable budget carries no attribution again", DOCTOR,
     '                not_yet="box_proof")', '                not_yet="")', BUDGET),

    # THE READER OF THAT ATTRIBUTION. `awaiting` alone is what the verdict used to consult, and
    # it cannot express "this is true and nothing needs it yet".
    ("the verdict stops reading the attribution", CLI,
     "                      if not f.ok and (f.awaiting or f.not_yet\n"
     '                                       or f.check in ("manifest", "box_proof"))}',
     "                      if not f.ok and (f.awaiting\n"
     '                                       or f.check in ("manifest", "box_proof"))}',
     BUDGET),

    # UNKNOWN READING AS "NOTHING IS EXPOSED". A probe set with no gate cannot show that pickup is
    # held, and the louder answer is the safe one.
    ("a probe set with no gate excuses the budget anyway", DOCTOR,
     "    if gate is None or gate.ok or p.foreign_proofs is None:",
     "    if gate is not None and gate.ok:", BUDGET),

    # …and the same absence one member further in: no `foreign_proofs` probe, no way to know the
    # board goes unread.
    ("a probe set that cannot answer the second half is excused anyway", DOCTOR,
     "    if gate is None or gate.ok or p.foreign_proofs is None:\n        return False\n"
     "    return not p.foreign_proofs()",
     "    if gate is None or gate.ok:\n        return False\n"
     "    return p.foreign_proofs is None or not p.foreign_proofs()", BUDGET),

    # C-18's HALF DROPPED: a held gate taken as proof that nothing is scanning, on exactly the
    # deployments where a proven foreign repo keeps the board being read every tick.
    ("the excuse ignores a foreign repo that is already proven", DOCTOR,
     "    return not p.foreign_proofs()", "    return True", BUDGET),

    # THE PROOF-NAME SHAPE, which is what tells a foreign proof from the default repo's own.
    ("the default repo's own proof counts as a foreign one", "openfactory/box_prove.py",
     '        return any((root or PROOF_DIR).glob(f"{project}--*.json"))',
     '        return any((root or PROOF_DIR).glob(f"{project}*.json"))', BUDGET),

    # AND THE POLLER GOING BACK TO ITS OWN COPY of the condition the doctor now quotes.
    ("the poller spells the foreign-proof condition itself again",
     "openfactory/runtime/temporal/activities.py",
     "        if not _bp.foreign_proofs_recorded(inp.project):",
     '        if not any(_bp.PROOF_DIR.glob(f"{inp.project}--*.json")):', BUDGET),

    # TWO ANSWERS TO ONE QUESTION, and an expensive one: `gate_reason` resolves a checkout and
    # asks docker for a digest.
    ("the budget check asks the gate a second time instead of reading its finding", DOCTOR,
     '            "api_budget", lambda: _api_budget(probes, pickup_held=_pickup_is_held(probes, '
     'gate))))',
     '            "api_budget", lambda: _api_budget(probes, pickup_held=bool(\n'
     "                probes.box_gate and probes.box_gate()))))", BUDGET),

    # A VENDOR WITH NO QUOTA READING AS BROKEN — every Jira and Azure Boards deployment failing
    # for being itself.
    ("a tracker that publishes no budget reads as a failed read", DOCTOR,
     "    if budget == NOT_REPORTED:", "    if budget is Ellipsis:", BUDGET),

    # THE REASON DROPPED ON THE FLOOR, which is what left the stranger with "could not be read"
    # and a remedy asking him to re-run by hand the call the platform had just made.
    ("the port's own reason stops reaching the screen", DOCTOR,
     '        why = f" ({budget})" if isinstance(budget, BudgetUnreadable) else ""',
     '        why = ""', BUDGET),

    # …and its wiring: the probe swallowing the refusal makes the sentence above unreachable.
    ("the probe swallows the port's refusal again", DOCTOR,
     "            return exc", "            return None", BUDGET),

    # A REMEDY HE CANNOT EXECUTE AT THAT STEP — the half of a diagnostic that matters.
    ("the held remedy sends him to a call he has no credential for", DOCTOR,
     '                "nothing here is yours to fix at this point in the sequence: prove the box "',
     '                "run the tracker\'s own CLI/API call with this project\'s credential "',
     BUDGET),

    # AND THE DOCUMENT, because nobody is standing next to him to explain the line.
    ("§2 stops telling the operator this line is expected there", ONBOARDING,
     "**`api_budget` may be red here too, and it is in the same category.**",
     "**About that budget line.**", BUDGET),
]
