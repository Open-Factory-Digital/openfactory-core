"""What a turn of the product role leaves on the worker is bounded, and an unmoved source costs
one question (#369).

Run:  .venv/bin/python tools/mutate.py tools/mutations/369_what_a_turn_leaves_on_the_worker_is_bounded.py

The product role runs in the worker — the perennial half of a deployment — and reads every source
of its product from the repository cache. Measured with `tools/measure_a_turns_footprint.py` on the
four-source fixture, before this change: every unmoved turn fetched each source and ran the whole
checkout on it (60 git processes, 10 round trips to a forge, per turn); a product whose sources
move every turn parked a snapshot per move per source for its thirty-minute grace (195 after 40
turns, 418 KB per turn on a 1.3 MB working set — 2.6 MB per turn on a filesystem that cannot
hardlink, where the fallback copied whole trees in silence); the purge ran only inside a sync that
succeeded, so a full disk stopped the one thing that empties it; and three API paths composed a
view of the product and never released it.

Rows 1-3 are the unmoved turn: one question to the forge, the tear a killed checkout leaves, and
what the cone left out remembered for the commit. Rows 4-5 bound the trash by generations per
key. Rows 6-7 run the purge whether or not the sync succeeded, in each cache. Row 8 says out loud
that a root cannot hardlink. Row 9 is the cache's own volume in compose; row 10 the one-machine
door's cache beside its registry rather than in /tmp; row 11 an API path releasing the view it
composed.
"""

TEST = "tests/test_every_source_is_mounted.py"

CACHE = "openfactory/runtime/repo_cache.py"
LIFECYCLE = "tests/test_repo_cache_lifecycle.py"
DISTRIBUTION = "tests/test_the_oss_distribution.py"
UNATTENDED = "tests/test_the_one_machine_deployment_runs_unattended.py"

MUTATIONS = [
    ("TODAY'S COST: an unmoved source is fetched and checked out again on every turn", CACHE,
     "            if (tip and _head(master) == tip and current_branch(master) == branch\n"
     "                    and not _worktree_dirty(master)):",
     "            if False:"),

    ("a master on the right commit with a torn tree is served as it is", CACHE,
     "                    and not _worktree_dirty(master)):",
     "                    and True):"),

    ("the unmoved turn no longer says what the checkout left out", CACHE,
     "                self.left_out = self._left_out_remembered(master)",
     "                self.left_out = []"),

    ("TODAY'S DEFECT: a key that moves faster than the grace parks a tree per move", CACHE,
     "_KEEP_DISPLACED = 2\n",
     "_KEEP_DISPLACED = 10 ** 6\n",
     LIFECYCLE),

    ("another key's displaced trees are counted against this one", CACHE,
     "            if not entry.name.startswith(f\"{project}{_SLOT_SEP}\"):\n"
     "                continue\n",
     "            if False:\n"
     "                continue\n",
     LIFECYCLE),

    ("the whole cache purges only after a sync that succeeded", CACHE,
     "                try:\n"
     "                    return self._sync(project, clone_url, base_branch)\n"
     "                finally:\n",
     "                served = self._sync(project, clone_url, base_branch)\n"
     "                if served is not None:\n"
     "                    self._purge_displaced()\n"
     "                return served\n"
     "                if False:\n",
     LIFECYCLE),

    ("the sparse cache purges only after a sync that succeeded", CACHE,
     "                try:\n"
     "                    return self._sync_sparse(project, public, base_branch, env)\n"
     "                finally:\n",
     "                served = self._sync_sparse(project, public, base_branch, env)\n"
     "                if served is not None:\n"
     "                    self._purge_displaced()\n"
     "                return served\n"
     "                if False:\n",
     LIFECYCLE),

    ("a root that cannot hardlink copies whole trees in silence", CACHE,
     "            self._say_linkless(exc)\n",
     "",
     LIFECYCLE),

    ("the repository cache shares the registry's volume", "docker-compose.yml",
     "      - openfactory_repos:/var/lib/openfactory/repos\n",
     "",
     DISTRIBUTION),

    ("the one-machine door leaves the cache in /tmp", "openfactory/onboarding/deployment.py",
     "OPENFACTORY_REPO_CACHE={home}/.openfactory/repos\n",
     "",
     UNATTENDED),

    ("an API call composes a view of the product and never releases it",
     "openfactory/runtime/temporal/activities.py",
     "    try:\n"
     "        return module.propose_queue(limit=limit)\n"
     "    finally:\n"
     "        engine.release(module)     # its view of the product goes with it (#369)\n",
     "    return module.propose_queue(limit=limit)\n"),
]
