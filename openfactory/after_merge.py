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


def no_local_promotion(box: str, step: str = "staging") -> tuple[str, str]:
    """`(what, remedy)` — why a promotion chain cannot be walked on a LOCAL box, and the way out.

    ONE SENTENCE, TWO SPEAKERS (#172). The promotion phase runs the box program with
    `OPENFACTORY_PROMOTE_PHASE` set, and only a remote box runs that program; a local box runs a
    `JobRunner`, which has no promotion verb. `_run_promotion` said so — but only AFTER THE MERGE,
    the one moment it costs the most: the change is on the base, the job ends failed,
    `_finish_at_the_merge` never runs and the card never reaches Done. Reported by a deployment
    whose manifest declared `environments:` on a local box: `openfactory doctor` said
    `ok post_merge after a merge: the promotion chain observes …`, `openfactory conformance` said
    the project was runnable, and the job failed after the merge with this refusal. The doctor now
    says the same words before any card is taken, and it asks this function for them so the two
    cannot drift apart.

    `staging` IS THE DEFAULT because it is the first promotion phase the durable workflow runs
    (`promote_staging`), whatever the manifest calls its stages — `step` is the box program's
    verb, not an environment name. Not called `phase`: here a `phase` with a default is an AGENT
    phase, and `test_every_phase_the_tree_passes_sits_in_EXACTLY_one_set` holds every such
    default to one of the agent phase sets (it went red on the first draft of this function).

    BOTH KEYS in the remedy, because dropping `environments:` alone leaves `promote:` naming stages
    nothing declares, and the manifest refuses to load
    (`Manifest._the_chain_names_only_declared_environments`)."""
    what = (f"the {step!r} promotion phase has no implementation for the local {box!r} box: "
            f"promotion runs the box program on a remote box only")
    remedy = ("run the deployment on a remote box, or drop `environments:` (and `promote:`, which "
              "names them) from the manifest until a local promotion exists")
    return what, remedy


def watching_a_deploy(cfg) -> str:
    """What a project that DOES declare a post-merge deploy is told — said only by a
    driver that really watches it."""
    return (
        f"Merged — and this job is done. This project's own `{cfg.workflow}` deploys it; "
        f"the factory is watching that run for up to {cfg.timeout_minutes} minutes and "
        f"will report the {cfg.env} outcome here. Nothing is promoted past it: the "
        f"manifest declares no `environments:`, so there is no chain to walk and no "
        f"approval to ask for.")
