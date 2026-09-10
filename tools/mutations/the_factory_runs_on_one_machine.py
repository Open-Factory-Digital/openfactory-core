"""ADR-0049 slice 5, proven by breaking it — the whole cycle on ONE MACHINE.

FOUR CLAIMS:

  1. **The card reaches Done.** The merge is the end of the road when nothing follows it, and the
     attended driver — the one a person on one machine uses — says so in the DURABLE driver's own
     words, from one definition.
  2. **Only where nothing follows.** A project that declares a deploy watch or a promotion chain
     keeps its road; closing its card at the merge would report a deploy nobody has looked at.
  3. **The refusal reaches the person and their tree is untouched** when their own uncommitted
     edit stands where the merge would land.
  4. **A paused pass keeps its work**, and the platform's own backoff — not the vendor's reset —
     decides when the poller picks it up again.

AND THE PROBE ITSELF IS CUT, because a proof that cannot see the thing it forbids is decoration:
the cloud hook and the socket hook each have a row, and each one's twin test must go red without
it.

The guard under test is `tests/test_the_factory_runs_on_one_machine.py`, driven through
`tests/one_machine.py` — the real doors, a scripted harness, and nothing else.
"""

TEST = "tests/test_the_factory_runs_on_one_machine.py"

MACHINE = "openfactory/orchestrator/machine.py"
AFTER = "openfactory/after_merge.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
PROOF = TEST

MUTATIONS = [
    # ── 1. the card reaches Done ───────────────────────────────────────────────────────────────
    ("the attended driver stops at the merge again, and the card stays in In review for ever",
     MACHINE,
     '            if after_merge.nothing_follows(deploy=result.post_merge_deploy,\n'
     '                                           environments=result.environments):\n',
     '            if False:\n', TEST),

    ("the run says DONE and the BOARD is never told, so the panel and the card disagree", MACHINE,
     '                self._set_state(ticket, JobState.DONE)\n', "", TEST),

    ("the person is told nothing about why this was the end of the road", MACHINE,
     '                self._say_on_ticket(ticket.id, after_merge.NOTHING_FOLLOWS)\n', "", TEST),

    # ── 2. only where nothing follows ──────────────────────────────────────────────────────────
    ("a project with a promotion chain is closed at the merge, before anybody looked at the "
     "deploy", AFTER,
     '    return not deploy and not tuple(environments or ()) and not promote',
     '    return not deploy', TEST),

    ("a project whose own workflow deploys it is closed at the merge by a driver that watches "
     "nothing", AFTER,
     '    return not deploy and not tuple(environments or ()) and not promote',
     '    return not tuple(environments or ()) and not promote', TEST),

    # ── 3. one sentence, two drivers ───────────────────────────────────────────────────────────
    ("the durable driver keeps its own copy of the sentence, which is how the two drifted",
     WORKFLOW,
     '        note = after_merge.watching_a_deploy(cfg) if cfg else after_merge.NOTHING_FOLLOWS',
     '        note = "Merged — and this job is done. This project\'s manifest declares no "\\\n'
     '               "`post_merge_deploy:` and no `environments:`, so nothing here watches a "\\\n'
     '               "deploy and nobody will be asked to validate one: whatever your pipeline "\\\n'
     '               "does after this merge, the factory is not looking."', TEST),

    # ── 4. the probe itself ────────────────────────────────────────────────────────────────────
    ("the socket hook is removed — the proof stops being about ONE machine", PROOF,
     '        socket.socket.connect = no_connect\n'
     '        socket.socket.connect_ex = no_connect\n'
     '        socket.create_connection = no_connection\n'
     '        socket.getaddrinfo = no_dns',
     '        pass', TEST),

    ("the cloud hook is removed — the proof stops being about a deployment with no account",
     PROOF, '        builtins.__import__ = guarded\n', "", TEST),

]
