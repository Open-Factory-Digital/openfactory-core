"""ADR-0049 slice 9b, proven by breaking it — the proof on the box that runs no image.

FOUR CLAIMS:

  1. **The three image stations are skipped for a box with no image**, and the proof says which
     box it is about and that it is the weaker of the two.
  2. **What it pins instead is this machine's harness**, and the gate compares the same string the
     proof recorded — an upgraded CLI is the same shape of change as a rebuilt image.
  3. **This runtime is gated like any other**, and every other imageless box keeps the exemption
     it was written for.
  4. **The proofs are recorded where this operator can write**, and an explicit path still wins.
  5. **A missing tool is not blamed on an image that does not exist** on this door, and still is
     on the door that has one.
  6. **A vendor's bad afternoon is not a verdict on this box** (the review of #109): only `auth`
     fails the proof, the rest are advisory, and the one paid call is recorded.
  7. **The harness is asked one real question** on this box and only on this box — the credential
     here is a login no variable reveals, and an isolating box's credential IS the variable.

The guard under test is `tests/test_the_proof_on_the_host.py`.
"""

TEST = "tests/test_the_proof_on_the_host.py"

PROVE = "openfactory/box_prove.py"

MUTATIONS = [
    # ── 1. the stations a box with no image does not have ──────────────────────────────────────
    ("an image is pulled for a box that runs none, so the proof fails for a reason it invented",
     PROVE,
     "    if not p.honours_image:\n        proof.image = \"\"",
     "    if False:\n        proof.image = \"\"", TEST),

    ("the proof stops saying which box it is about, and reads as the container one", PROVE,
     '            f"this box runs no image — the proof is about THIS MACHINE"',
     '            f"proven"', TEST),

    ("the trade is no longer stated, so a host proof reads as strong as a container one", PROVE,
     "            f\"{f' ({proof.toolchain})' if proof.toolchain else ''}. It is the weaker of the "
     "two: \"\n            f\"a container proof pins a toolchain everybody shares, and this one "
     "pins yours\"))",
     '            f"."))', TEST),

    # ── 2. what it pins instead ────────────────────────────────────────────────────────────────
    ("the proof pins nothing about this machine, so an upgraded harness is invisible", PROVE,
     "        proof.toolchain = (p.machine_stamp() or \"\").strip()", "        pass", TEST),

    ("the gate stops comparing it, which is the same silence one tick later", PROVE,
     '    if machine and proof.toolchain and machine != proof.toolchain:',
     '    if False:', TEST),

    # THE HOLD WHOSE REMEDY COULD NEVER CLEAR IT (review of #105). The toolbox is the image side's
    # fact; comparing it against a proof that never recorded one made a host proof stale on every
    # tick, and `box prove` wrote the same empty field again.
    ("a host proof is judged against a toolbox volume it never had", PROVE,
     '    if proof.image and variant and proof.toolbox != variant:',
     '    if variant and proof.toolbox != variant:', TEST),

    ("an image proof stops noticing its toolbox moving, which is what that field is FOR", PROVE,
     '    if proof.image and variant and proof.toolbox != variant:',
     '    if False:', TEST),

    ("the gate derives the harness binary itself, so the two spellings can drift apart", PROVE,
     '    # THE SAME EXPRESSION UNDER ITS OWN NAME. This re-derived '
     '`harness_binary(harness_kind(...))`\n'
     '    # three hundred lines below the helper that IS that expression: they agreed, and '
     'nothing made\n'
     '    # them agree tomorrow — which is what the docstring above promises not to do (review of '
     '#105).\n'
     '    binary = _harness_binary(project)',
     '    from openfactory.adapters.agent.registry import harness_binary, harness_kind\n'
     '    binary = harness_binary(harness_kind(project, "executor"))', TEST),

    # ── 3. the gate ────────────────────────────────────────────────────────────────────────────
    ("this runtime goes back to being ungated — a card picked up with nothing checked", PROVE,
     "            if not own_work.declared():\n                return None",
     "            return None", TEST),

    ("every imageless box is gated, including the cloud one whose image is baked", PROVE,
     "        if not box_traits((sandbox or \"\").strip().lower()).honours_image:",
     "        if False:", TEST),

    # ── 4. where the proofs go ─────────────────────────────────────────────────────────────────
    ("the proofs go back to a service directory this operator cannot write", PROVE,
     "    if own_work.declared():\n        from openfactory import namespace\n\n"
     "        return namespace.operator_path(\"proofs\")",
     "    if False:\n        from openfactory import namespace\n\n"
     "        return namespace.operator_path(\"proofs\")", TEST),

    ("an explicit path is second-guessed after all", PROVE,
     '    named = (os.environ.get("OPENFACTORY_PROOFS") or "").strip()\n    if named:\n'
     '        return Path(named)',
     '    named = ""\n    if named:\n        return Path(named)', TEST),

    ("the harness remedy sends somebody to check a mount that is not there", PROVE,
     '            ("the toolbox is mounted read-only at /opt/openfactory-toolbox; check the box\'s "\n'
     '             "mount and that the entry is executable") if p.honours_image else',
     '            ("the toolbox is mounted read-only at /opt/openfactory-toolbox; check the box\'s "\n'
     '             "mount and that the entry is executable") if True else', TEST),

    # ── 5. the remedy is about the box this IS ─────────────────────────────────────────────────
    ("a box with no image sends the reader to declare one", PROVE,
     "    if not honours_image:\n"
     '        return (f"`{head}` is not on your PATH, and this box runs your commands on THIS '
     'machine — "',
     "    if False:\n"
     '        return (f"`{head}` is not on your PATH, and this box runs your commands on THIS '
     'machine — "', TEST),

    ("the box that DOES run an image loses the sentence written for it", PROVE,
     "            remedy = (_missing_tool_remedy(cmd, image, honours_image=p.honours_image)",
     "            remedy = (_missing_tool_remedy(cmd, image, honours_image=False)", TEST),

    # ── 6. the one question (the demo's second defect, 2026-09-11) ─────────────────────────────
    ("the harness is never asked, and a signed-out machine proves a box again", PROVE,
     "    if not p.honours_image and p.harness_answers is not None:", "    if False:", TEST),

    ("a harness that could not answer is recorded as having answered", PROVE,
     "        elif asked[0]:", "        elif True:", TEST),

    # ── 6. the cause decides whether this box failed ───────────────────────────────────────────
    ("a rate limit fails the proof again, so a vendor's afternoon holds every card", PROVE,
     '        elif asked[2] == "auth":', "        elif True:", TEST),

    ("the vendor's finding blocks after all, which is what `advisory` exists not to do", PROVE,
     "                 \"and everything else here was proven\"),\n"
     "                advisory=True))",
     "                 \"and everything else here was proven\")))", TEST),

    ("a rate limit is given the sign-in remedy — the wrong cause, with confidence", PROVE,
     '    if reason == "rate_limit":', "    if False:", TEST),

    ("the window it lifts in is measured and dropped", PROVE,
     '        when = f" (resets {got.retry_at})" if got.retry_at else ""',
     '        when = ""', TEST),

    ("every cause is flattened into one, which is what the sentence then names wrongly", PROVE,
     '    if reason == "auth":', "    if reason:", TEST),

    ("the one call that costs money records nothing", PROVE,
     "        record_one_pass(project=project.name, ticket=f\"prove:{project.name}\",\n"
     "                        role=_PROVE_ROLE, result=got)",
     "        pass", TEST),

    ("the backfill keeps its own books again", "openfactory/onboarding/spend.py",
     "    record_one_pass(project=project, ticket=f\"backfill:{repo}\", role=BACKFILL_ROLE, "
     "result=result)",
     "    return None", TEST),

    ("every container proof spends an agent call for a credential it can already see", PROVE,
     "    if not p.honours_image and p.harness_answers is not None:",
     "    if p.harness_answers is not None:", TEST),

    ("a harness with no read-only primitive is blamed instead of reported", PROVE,
     "        if asked is None:", "        if False:", TEST),

    ("the remedy stops naming the sign-in, so the one thing to do is missing", PROVE,
     'f"`{p.harness_name()}` yourself and sign in, then re-run this. A card picked up "',
     'f"something. A card picked up "', TEST),

    ("the question is asked of some other harness than the one that writes this code", PROVE,
     "            agent = build_executor(project)", "            agent = build_executor(None)",
     TEST),

    ("the question is asked outside the box, proving a login where the job does not run", PROVE,
     "            got = ask(sandbox=box, workspace=workspace, prompt=_ONE_WORD, phase=\"prove\")",
     "            got = ask(sandbox=None, workspace=workspace, prompt=_ONE_WORD, phase=\"prove\")",
     TEST),
]
