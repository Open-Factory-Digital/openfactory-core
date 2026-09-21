"""Proven by breaking it — a manifest nobody could read is not a manifest whose commands match.

The box freshness gate asks "have this box's `setup:`/`validate:` changed since it was proven?".
When it could not read the manifest it answered with the PROOF'S OWN HASH — `commands =
proof.commands_hash`, commented "do not block on a question we cannot ask" — which makes
`proof.commands_hash != commands` false by construction. That dimension became structurally
incapable of disagreeing, and no test of behaviour could see it: the gate opens either way.

THREE CLAIMS:

  1. **The question is recorded as unasked**, not answered — nothing feeds the comparison the
     value it is compared against.
  2. **The degrade is kept**: an unreachable checkout still opens the gate, because a flaky forge
     must not park every card on every foreign repository. It is now said, in the log, twice —
     where the read failed and where the comparison was skipped.
  3. **Everything the process CAN measure still gates**: a manifest that reads and whose commands
     moved still holds, and so do the image digest, the toolbox variant and the machine version.

The guard is `tests/test_the_proof_gates_pickup.py`.
"""

TEST = "tests/test_the_proof_gates_pickup.py"

BOX = "openfactory/box_prove.py"

MUTATIONS = [
    # ── claim 1: a question nobody asked is not an answer ─────────────────────────────────────
    ("THE DEFECT ITSELF: the comparison is fed the value it is compared against, so the "
     "commands can never be found to have moved", BOX,
     "        commands = None\n",
     "        commands = proof.commands_hash\n"),

    ("…by the other door: the freshness check treats 'not compared' as 'compared and equal'",
     BOX,
     "    if commands is None:\n",
     "    if False:\n"),

    ("the skip is silent, so a deployment whose manifest never reads looks exactly like one "
     "whose commands are the ones proved", BOX,
     '        log.info("the manifest could not be read here (the proof recorded %r) — not '
     'judging "\n',
     '        log.debug("", ) or log.debug("the manifest could not be read here (the proof '
     'recorded %r) — not judging "\n'),

    # ── claim 2: the degrade is kept ──────────────────────────────────────────────────────────
    ("an unreadable manifest holds the gate, so a flaky forge parks every card on every "
     "foreign repository", BOX,
     "        commands = None\n",
     '        return f"the manifest could not be read — {run_it}"\n'),

    # ── claim 3: what the process CAN measure still gates ─────────────────────────────────────
    ("a manifest that READS and whose commands moved no longer holds anything", BOX,
     "    elif proof.commands_hash != commands:\n",
     "    elif False:\n"),
]
