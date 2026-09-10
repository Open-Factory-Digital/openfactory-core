"""What follows a merge — the question and the sentence, said once (ADR-0049 slice 5).

THE CARD COULD NOT REACH DONE, AND IT WAS FIXED ON ONE PATH ONLY. `JobState.MERGED` maps to *In
review* on purpose: a merged change is still overseen while it deploys, and the column past it is
written by the promotion tail, which runs only for a manifest that declares `environments:`. A
project without them — which is every project this platform's own onboarding creates — therefore
merged, freed the floor, and left its card in *In review* for ever. The durable workflow learned
that on 2026-08-16 (`workflow.patched("merge-is-the-end-when-nothing-follows")`), and
`orchestrator/machine.py` — what `openfactory run` and `poll` build, the driver a person on ONE
MACHINE uses before anything durable is started — never did. Two drivers, one question, opposite
answers; found by running the one-machine proof, not by reading either of them.

So the question and the words live here, once, and both drivers ask them.

WHO MAY SAY WHICH SENTENCE. `watching_a_deploy` is the durable path's alone: it spawns the watcher
(`_spawn_deploy_watch`) and can honestly say the factory is looking. The attended driver watches
nothing, so it settles at the merge only when NOTHING follows at all and says the other sentence —
a run that promised a watch nobody is performing would be a worse lie than the silence this fixes.
"""

from __future__ import annotations


def nothing_follows(*, deploy: object = None, environments: object = (), promote: bool = False,
                    ) -> bool:
    """Whether the merge is the end of the road: no deploy watch, no promotion chain, nobody asked.

    `promote` is the durable path's start-time flag; the attended driver has no promotion tail at
    all, so it passes nothing and reads the same answer."""
    return not deploy and not tuple(environments or ()) and not promote


#: What a project that declares neither is told — and the file that changes it. Not a template: the
#: reader is being told what THIS project declared, which is why the two sentences are separate.
NOTHING_FOLLOWS = (
    "Merged — and this job is done. This project's manifest declares no "
    "`post_merge_deploy:` and no `environments:`, so nothing here watches a deploy "
    "and nobody will be asked to validate one: whatever your pipeline does after this "
    "merge, the factory is not looking. Declare either of them in "
    "`.openfactory/project.yaml` to change that — see ONBOARDING §13.")


def watching_a_deploy(cfg) -> str:
    """What a project that DOES declare a post-merge deploy is told — said only by a
    driver that really watches it."""
    return (
        f"Merged — and this job is done. This project's own `{cfg.workflow}` deploys it; "
        f"the factory is watching that run for up to {cfg.timeout_minutes} minutes and "
        f"will report the {cfg.env} outcome here. Nothing is promoted past it: the "
        f"manifest declares no `environments:`, so there is no chain to walk and no "
        f"approval to ask for.")
