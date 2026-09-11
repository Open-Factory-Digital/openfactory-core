"""ADR-0049 slice 9b, proven by breaking it — the proof on the box that runs no image.

FOUR CLAIMS:

  1. **The three image stations are skipped for a box with no image**, and the proof says which
     box it is about and that it is the weaker of the two.
  2. **What it pins instead is this machine's harness**, and the gate compares the same string the
     proof recorded — an upgraded CLI is the same shape of change as a rebuilt image.
  3. **This runtime is gated like any other**, and every other imageless box keeps the exemption
     it was written for.
  4. **The proofs are recorded where this operator can write**, and an explicit path still wins.

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
]
