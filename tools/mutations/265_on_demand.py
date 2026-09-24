"""Mutation plan for #265 slice 3 — a preview on demand: the enter door's chain, what a card is
judged to offer, the four routes and their rows, the steps a started preview runs, the workflow
that runs them, and the job's offer (ADR-0050 D6, D7, D10; the design's §4.3, §5.2, §5.5).

Each row takes away one rule a started preview's safety, its honesty or its ending rests on; every
row must turn `tests/test_a_preview_is_started_on_demand.py` red. The live test
(`tests/test_a_preview_starts_on_a_real_daemon.py`) is not a target: it needs a daemon and
minutes, and every property it measures is also held here against a faked runtime and forge.
"""

TEST = "tests/test_a_preview_is_started_on_demand.py"

APP = "openfactory/api/app.py"
PREVIEW = "openfactory/preview/__init__.py"
DEMAND = "openfactory/preview/demand.py"
STEPS = "openfactory/preview/steps.py"
CATALOG = "openfactory/actions/catalog.py"
VIEW = "openfactory/runtime/temporal/view.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
WORKER = "openfactory/runtime/temporal/worker.py"
MACHINE = "openfactory/orchestrator/machine.py"

MUTATIONS = [
    # ── the chain: one click opens every exposed service, and cannot be steered ──
    ("the door's next hop is read from the query string", APP,
     "                                         to=request.query_params.get(\"to\", \"\"))\n",
     "                                         to=request.query_params.get(\"to\", \"\"))\n"
     "    service = request.query_params.get(\"next\") or service\n"),
    ("the chain stops after one hop, so one click opens two services", PREVIEW,
     "    return next_, (after[0] if after else \"\"), end",
     "    return next_, \"\", end"),
    ("the chain ends on the first service offered, not the one pressed", PREVIEW,
     "        end = to\n", "        end = order[0]\n"),
    ("the chain drops the key, so every door after the first is refused", APP,
     "    query = {\"t\": request.query_params.get(\"t\", \"\"), **({\"next\": nxt} if nxt else {}), "
     "\"to\": to}",
     "    query = {**({\"next\": nxt} if nxt else {}), \"to\": to}"),
    ("a door with no chain sends the browser off its own host", APP,
     "    if service == host.service and not nxt and not to:\n        return \"/\"\n",
     "    if False:\n        return \"/\"\n"),
    ("the card's link is a door of one service: the others each need a click", APP,
     "            query.update({\"next\": nxt, \"to\": svc})",
     "            query.update({\"to\": svc})"),
    ("the router waits the default whatever the operator said", APP,
     "    owner = next((p for p in projects if getattr(p, \"name\", None) == record.project), None)",
     "    owner = None"),

    # ── what the card is judged to offer ──
    ("a deployment that names no runtime offers a start button", DEMAND,
     "        return Judged(False, refusal, stale)", "        pass"),
    ("a moved branch is never said to be stale", DEMAND,
     "        stale += [s for s in stale_of(was, forge.heads) if s not in stale]",
     "        stale += []"),
    ("the forge is asked on every read of a card", DEMAND,
     "    if hit and now - hit[0] < FORGE_TTL_SECONDS:", "    if False:"),
    ("a forge that could not be read reads as no open pull request", DEMAND,
     "    if not out and unread:", "    if False:"),
    ("a card of a requirement is read as a unit of its own", PREVIEW,
     "    return token if UNIT_RE.fullmatch(token) else card", "    return card"),

    # ── the rows behind the routes ──
    ("a second start is an error, not `starting`", CATALOG,
     "    except tv.PreviewAlreadyStarted:\n"
     "        return done(f\"a preview of {token} is already starting — it takes minutes.\",",
     "    except tv.PreviewAlreadyStarted:\n"
     "        return refused(CONFLICT, f\"a preview of {token} is already starting.\")\n"
     "        return done(f\"a preview of {token} is already starting — it takes minutes.\","),
    ("a deployment that names no runtime starts a preview anyway", CATALOG,
     "    if why:\n        return refused(CONFLICT, why[:1].upper() + why[1:])",
     "    if False:\n        return refused(CONFLICT, why[:1].upper() + why[1:])"),
    ("a record that names another project is acted on", CATALOG,
     "    if was is not None and was.project != found.name:", "    if False:"),
    ("the start row is the floor's, so the person who asked for the change cannot press it",
     CATALOG,
     "            name=\"preview_start\",\n            scope=PRODUCT,\n",
     "            name=\"preview_start\",\n"),
    ("a cookie alone stops a preview: a cross-site form can press the button", APP,
     "@app.post(\"/api/preview/{project}/{unit}/stop\", dependencies=_AUTH)",
     "@app.post(\"/api/preview/{project}/{unit}/stop\")"),
    ("a stop sent to a finished workflow is reported done", VIEW,
     "    if described.status != _Status.RUNNING:\n        return False",
     "    if False:\n        return False"),

    # ── the steps ──
    ("the unit's old stack is left under a fresh checkout", STEPS,
     "    clear(project, token, runtime)\n", ""),
    ("the old stack is taken down before its logs are kept", STEPS,
     "    runtime.logs(cp, log_dir)\n    return runtime.down(cp, workdir)",
     "    return runtime.down(cp, workdir)"),
    ("a fresh start carries what the last one noted", STEPS,
     "                notes=(), log_dir=\"\")", "                log_dir=\"\")"),
    ("the cap is never asked", STEPS,
     "    why = demand.over_cap(runtime.running(), mine=cp, cap=cap)", "    why = \"\""),
    ("the unit's own leftover counts against the cap", DEMAND,
     "    others = sorted({(rp.project, rp.unit) for rp in running if rp.compose_project != mine})",
     "    others = sorted({(rp.project, rp.unit) for rp in running})"),
    ("the cap's refusal names nobody", DEMAND,
     "    names = \", \".join(f\"{p} {u}\" for p, u in others)",
     "    names = \"several previews\""),
    ("a live preview records no heads, so `stale` can never be judged", STEPS,
     "            heads={t.pr_url: t.change_commit for t in planned.layout.trees.values()\n"
     "                   if t.has_change and t.pr_url},",
     "            heads={},"),
    ("a failed start that left nothing on the daemon keeps its work directory", STEPS,
     "    if runtime.watch(planned.compose_project) is None:", "    if False:"),
    ("a failed start is taken down at once, so nobody can read why", STEPS,
     "    if runtime.watch(planned.compose_project) is None:", "    if True:"),
    ("a crashed exposed service is never recorded failed", STEPS,
     "    if seen.state == \"running\":", "    if True:"),
    ("a rebuild's down records the unit ended", STEPS,
     "    if record:", "    if True:"),

    # ── the workflow ──
    ("a stop takes the stack down before its logs are kept", WORKFLOW,
     "        for fn, minutes in ((preview_logs, 5), (preview_down, 10)):",
     "        for fn, minutes in ((preview_down, 10), (preview_logs, 5)):"),
    ("a rebuild takes the unit down as ended", WORKFLOW,
     "                    await self._end(step, f\"rebuilt by {by}\", record=False)",
     "                    await self._end(step, f\"rebuilt by {by}\")"),
    ("a rebuild is credited to whoever started the first one", WORKFLOW,
     "                    step = step.model_copy(update={\"started_by\": by})\n", ""),
    ("one run holds the whole watch, however long the preview lives", WORKFLOW,
     "                if rounds >= _PREVIEW_ROUNDS or "
     "workflow.info().is_continue_as_new_suggested():",
     "                if False:"),
    ("the continued run starts the preview again", WORKFLOW,
     "                        \"watching\": watching, \"started_by\": step.started_by}))",
     "                        \"started_by\": step.started_by}))"),
    ("a step that died leaves whatever it made on the daemon", WORKFLOW,
     "            await self._end(step, f\"the start did not finish ({cause}) — the worker may "
     "have \"\n"
     "                                  f\"restarted during the build\")\n",
     "            self._state = \"failed\"\n"),
    ("a long step never says it is alive", ACTIVITIES,
     "        activity.heartbeat(step)", "        pass"),
    ("the worker does not run the preview's workflow", WORKER,
     "                   PreviewReapWorkflow, PreviewWorkflow,",
     "                   PreviewReapWorkflow,"),
    ("the worker does not run the preview's steps", WORKER,
     "    preview_materialise, preview_plan, preview_up, preview_watch, preview_logs, preview_down,\n",
     ""),

    # ── the offer ──
    ("a sibling's gate relabels a live preview `offered`", DEMAND,
     "    if was is not None and was.state in (preview.STARTING, preview.LIVE):", "    if False:"),
    ("the offer asks the deployment's runtime", DEMAND,
     "        runtime_kind = default_preview_runtime()\n",
     "        runtime_kind = default_preview_runtime()\n"
     "        from openfactory.adapters.preview.registry import build_runtime\n\n"
     "        build_runtime(runtime_kind).prerequisites()\n"),
    ("a project that declares no preview is offered one", DEMAND,
     "    if getattr(manifest, \"preview\", None) is None or not preview.card_of(ticket.id):",
     "    if not preview.card_of(ticket.id):"),
    ("the human gate offers nothing", MACHINE,
     "                self._offer_preview(ticket, pr, branch)\n", ""),
]
