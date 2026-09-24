"""Mutation plan for #265 slice 2 — the preview axis, the `compose` and `none` rows, the reaper
through the row, and the deployment that names them (ADR-0050 D4, D7, D8, D10, D11).

Each row takes away one rule a preview's safety, its ending or its honesty rests on; every row
must turn its guard red. The live test (`tests/test_a_preview_runs_on_a_real_daemon.py`) is not a
target here: it needs a daemon and minutes, and every property it measures is also held against
the faked daemon these rows break.
"""

TEST = "tests/test_the_compose_row_runs_what_was_admitted.py"
AXIS_TEST = "tests/test_the_preview_axis.py"
REAP_TEST = "tests/test_a_preview_is_ended_by_the_reaper.py"
DEPLOY_TEST = "tests/test_a_deployment_can_run_a_preview.py"

COMPOSE = "openfactory/adapters/preview/compose.py"
NONE = "openfactory/adapters/preview/none.py"
BASE = "openfactory/adapters/preview/base.py"
REAP = "openfactory/preview/reap.py"
PREVIEW = "openfactory/preview/__init__.py"
DOCTOR = "openfactory/doctor.py"
PREFLIGHT = "openfactory/preflight.py"
DEPLOY = "openfactory/onboarding/deployment.py"
IO = "openfactory/runtime/temporal/io.py"

MUTATIONS = [
    # ── the reduced environment: nothing of the factory's reaches the compose process ──
    ("the compose process runs with the worker's whole environment", COMPOSE,
     '    env = {k: os.environ[k] for k in ("PATH", "DOCKER_HOST", "DOCKER_CERT_PATH",\n'
     '                                      "DOCKER_TLS_VERIFY") if os.environ.get(k)}\n'
     '    env["HOME"] = os.path.join(wd, "home")\n',
     '    env = dict(os.environ)\n'
     '    env["HOME"] = os.path.join(wd, "home")\n'),
    ("the planted secret: a name the registry could never admit is handed over when a plan names "
     "it", COMPOSE,
     "            if worker in os.environ and not preview_name_refused(worker):\n",
     "            if worker in os.environ:\n"),
    ("every OPENFACTORY_PREVIEW_* of the worker — the panel's key with them — reaches the process",
     COMPOSE,
     "    for svc in plan.expose:\n"
     '        env[f"OPENFACTORY_PREVIEW_URL_{url_var(svc)}"]',
     '    env.update({k: v for k, v in os.environ.items()\n'
     '                if k.startswith("OPENFACTORY_PREVIEW_")})\n'
     "    for svc in plan.expose:\n"
     '        env[f"OPENFACTORY_PREVIEW_URL_{url_var(svc)}"]'),

    # ── `none` refuses by name ──
    ("`none` stops refusing: a deployment that runs nothing reads as ready", NONE,
     "        return [REFUSAL]\n", "        return []\n", AXIS_TEST),
    ("a deployment that names nothing runs previews on its daemon anyway", IO,
     "    return explicit or DEFAULT_PREVIEW_RUNTIME\n", '    return explicit or "compose"\n',
     AXIS_TEST),

    # ── one edge network per unit ──
    ("two units share one edge network, so each can resolve the other", COMPOSE,
     "        edge = plan.edge_network\n", '        edge = "openfactory-pv-shared-edge"\n'),
    ("`down` derives a network every unit shares", COMPOSE,
     '    return f"{compose_project}-edge"\n', '    return "openfactory-pv-edge"\n'),
    # re-pinned in slice 6: the loopback edge's options became `LOOPBACK_EDGE_OPTS`, shared with
    # the network `doctor` measures on, so the line is one line now
    ("the edge network routes out: it is no longer internal", COMPOSE,
     '        opts = ["--internal"] if plan.reach == "network" else list(LOOPBACK_EDGE_OPTS)\n',
     '        opts = [] if plan.reach == "network" else list(LOOPBACK_EDGE_OPTS)\n'),
    ("the panel is never connected, so nobody can open a preview", COMPOSE,
     '        if connect_panel and plan.reach == "network" and self.panel_container:\n',
     "        if False:\n"),
    ("`down` leaves the panel on the unit's network", COMPOSE,
     "        if self.panel_container:\n"
     '            _host(["docker", "network", "disconnect", "-f", edge, self.panel_container],',
     "        if False:\n"
     '            _host(["docker", "network", "disconnect", "-f", edge, self.panel_container],'),

    # ── readiness by `ps`, never `--wait` ──
    ("readiness is asked of `up --wait`, so a one-shot fails the stack", COMPOSE,
     '        ran = _host([*base, "up", "-d", "--build"], env=env, timeout=self.start_timeout)\n',
     '        ran = _host([*base, "up", "-d", "--build", "--wait"], env=env,\n'
     "                    timeout=self.start_timeout)\n"),
    ("a non-zero exit is not the failure", COMPOSE,
     "                if code != 0:\n", "                if False:\n"),
    ("an exposed service's healthcheck is not waited for", COMPOSE,
     "                if svc in checked:\n", "                if False:\n"),
    ("the settle watch is skipped", COMPOSE,
     "        problem = self._settle(plan, base, env)\n", '        problem = ""\n'),

    # ── the data step ──
    ("the data step never falls back to /bin/sh", COMPOSE,
     "                if no_shell(ran):\n"
     '                    ran = _host([*exec_, "/bin/sh", "-c", command], env=env,',
     "                if False:\n"
     '                    ran = _host([*exec_, "/bin/sh", "-c", command], env=env,'),
    ("an image with no shell is said as a bare exit code", COMPOSE,
     "                    if no_shell(ran):\n", "                    if False:\n"),
    ("an unauthorized pull is said as the daemon's raw error", COMPOSE,
     '        if any(s in lowered for s in ("unauthorized", "pull access denied", '
     '"denied: requested",\n',
     '        if False and any(s in lowered for s in ("unauthorized", "pull access denied", '
     '"denied: requested",\n'),

    # ── what is never run ──
    ("a plan admission would refuse is run anyway", COMPOSE,
     "        why = refusals(plan)\n        if why:\n"
     '            return PreviewUp(ok=False, why="refused before anything ran: "',
     "        why = []\n        if why:\n"
     '            return PreviewUp(ok=False, why="refused before anything ran: "'),
    ("the row stops checking that a volume is named under the unit", BASE,
     '        if str(spec.get("name") or "") != f"{cp}_{vol}":\n', "        if False:\n"),
    ("a proof runs a change", COMPOSE,
     "        if any(t.has_change for t in plan.layout.trees.values()) or "
     "any(plan.from_change.values()):\n",
     "        if False:\n"),

    # ── logs before any down; a down that deletes only what it made ──
    ("a proof takes the stack down before its logs are kept", COMPOSE,
     "            self.logs(plan.compose_project, self.log_dir(plan))\n"
     "            self.down(plan.compose_project, plan.workdir)\n",
     "            self.down(plan.compose_project, plan.workdir)\n"
     "            self.logs(plan.compose_project, self.log_dir(plan))\n"),
    ("the reaper takes a stack down without keeping its logs", REAP,
     "        runtime.logs(cp, where)             # before ANY down\n", "", REAP_TEST),
    ("a work directory is deleted outside `workdir_is_ours`", COMPOSE,
     "    if not workdir_is_ours(workdir):\n        if workdir and os.path.lexists(workdir):\n",
     "    if False:\n        if workdir and os.path.lexists(workdir):\n"),
    ("`workdir_is_ours` stops asking where the directory is", COMPOSE,
     "                and p.parent.resolve() == Path(work_root()).resolve())\n",
     "                and True)\n"),

    # ── reading what runs: exited stacks included ──
    ("`running()` hides exited stacks from the reaper", COMPOSE,
     '        argv = ["docker", "ps", "-a", "--filter", f"label={preview.LABEL}"]\n',
     '        argv = ["docker", "ps", "--filter", f"label={preview.LABEL}"]\n'),

    # ── materialise ──
    ("the checkout shares object files with the cache a container could write through", COMPOSE,
     '            r = _git("clone", "--local", "--no-hardlinks", "--quiet",\n',
     '            r = _git("clone", "--local", "--quiet",\n'),
    ("the change is checked out at the branch's tip, not at the head the forge reported",
     COMPOSE,
     "    head = s.head or _git(", "    head = _git("),
    ("a work directory is reused", COMPOSE,
     "    if os.path.lexists(workdir):\n        _remove_workdir(workdir)\n",
     "    if False:\n        _remove_workdir(workdir)\n"),

    # ── the reaper's rules ──
    ("a pull request that could not be read ends the preview", REAP,
     '"until its time is up", url, exc)\n            return False\n',
     '"until its time is up", url, exc)\n            continue\n', REAP_TEST),
    ("a failed unit is taken down the tick it is seen, before anyone can read why", REAP,
     "                if now - since >= policy.keep_failed_minutes * 60:\n",
     "                if True:\n", REAP_TEST),
    ("a start that will never finish is never ended", REAP,
     "            if was.state != preview.STARTING:\n                continue\n",
     "            if True:\n                continue\n", REAP_TEST),
    ("the orphan sweep takes a work directory that is still young", REAP,
     "            if entry.stat(follow_symlinks=False).st_mtime > horizon:\n",
     "            if False:\n", REAP_TEST),

    # ── the deployment and its doors ──
    ("a preview domain same-site with a plain-http panel is let through", PREVIEW,
     '    if shared != registrable(panel):\n        return ""\n',
     '    if True:\n        return ""\n', DEPLOY_TEST),
    ("a required project on a none runtime reads as fine", DOCTOR,
     "        if state.required:\n", "        if False:\n", DEPLOY_TEST),
    ("doctor forgets the names the worker does not hold", DOCTOR,
     "    if state.missing_env:\n", "    if False:\n", DEPLOY_TEST),
    ("preflight stops asking for the plugin a compose preview runs through", PREFLIGHT,
     "    if not present:\n        problems.append(", "    if False:\n        problems.append(",
     DEPLOY_TEST),
    ("init leaves the preview key for somebody to fill", DEPLOY,
     "OPENFACTORY_PREVIEW_SECRET={p.secret()}\n", "OPENFACTORY_PREVIEW_SECRET=\n", DEPLOY_TEST),
    ("the panel's container is not the name the worker connects", "docker-compose.yml",
     "    container_name: openfactory-panel\n", "    container_name: panel\n", DEPLOY_TEST),
    ("the worker image loses the compose plugin", "docker/worker.Dockerfile",
     "COPY --from=compose-plugin /docker-compose /usr/local/lib/docker/cli-plugins/"
     "docker-compose\n", "", DEPLOY_TEST),
]
