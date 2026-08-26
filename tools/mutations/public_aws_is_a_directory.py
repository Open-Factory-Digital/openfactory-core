"""The AWS connector is a directory delete — each guard broken once, and required red.

Every cut below reverts one line of the change to the defect it replaced (or to the shape the
first draft of the fix would have shipped), and names the guard that must see it. A survivor is a
finding about the GUARD: tighten it, never delete the mutation.

The second wave added the cuts the review found missing: the two survivors it reported
(`start_jobs` asking the built-in table; `hasattr` in place of the port), the promotion inputs
naming the job's box (both arms of the patch), the stream's bounded tail, the vendor's kind
spelled in a core reader, and the reference deployment's own declarations in the terraform.

The third wave answers the review's three guard SURVIVORS — each planted offender it fed a scanner
is here verbatim, red — plus the table override refused by name on every shipped sink kind, and
the configuration reference stating the declared default rather than the removed inference.
"""

TEST = "tests/test_the_cloud_is_a_directory_delete.py"
DOC_TEST = "tests/test_the_documented_default_is_the_real_one.py"

REG = "openfactory/adapters/sandbox/registry.py"
ACT = "openfactory/runtime/temporal/activities.py"
IO = "openfactory/runtime/temporal/io.py"
WF = "openfactory/runtime/temporal/workflow.py"
APP = "openfactory/api/app.py"
MV = "openfactory/api/metrics_view.py"
QUERY = "openfactory/observability/query.py"
OBS = "openfactory/observability/registry.py"
DYN = "openfactory/observability/dynamo.py"
SESS = "openfactory/adapters/agent/session_store.py"
POOL = "openfactory/adapters/agent/token_pool.py"
TF_WORKER = "infra/terraform/worker_service.tf"
TF_PANEL = "infra/terraform/panel_service.tf"
TF_APPRUNNER = "infra/terraform/panel_apprunner.tf"
VIEW = "openfactory/runtime/temporal/view.py"
DOC_REF = "docs/reference/configuration.md"
DOC_ONB = "docs/ONBOARDING.md"

E2E_PROMOTION = "tests/test_temporal_workflow.py::test_promotion_runs_on_the_JOBS_box_not_the_workers"

MUTATIONS = [
    # ── the box axis ────────────────────────────────────────────────────────────────────────────
    ("a remote row without a runner is admitted (the orphaned-task defect at import)", REG,
     "    if traits.remote and remote is None:\n        raise TypeError(",
     "    if False:\n        raise TypeError("),
    ("a local row with a remote runner is admitted (two facts in one row)", REG,
     "    if not traits.remote and remote is not None:",
     "    if False:"),
    ("the box registry stops consulting the add-ons on the activity side", REG,
     "        make = plugins.builder(AXIS, key, builtin=BOXES)\n        if make is not None:",
     "        make = None\n        if make is not None:"),
    ("an add-on's row is taken on trust instead of validated", REG,
     "            return _check_row(key, make())",
     "            return make()"),
    ("the workflow's lookup starts seeing add-ons (I/O in a workflow body)", REG,
     "    return _row(kind, installed=False)[0]",
     "    return _row(kind, installed=True)[0]"),
    ("the described box's missing add-on is read as a runner", REG,
     "        if build is None:\n            raise RuntimeError(",
     "        if False:\n            raise RuntimeError("),
    ("the runner handed back by an add-on is not checked against RemoteBox", REG,
     "    if not isinstance(runner, RemoteBox):",
     "    if False:"),
    # ── the engine dispatches by trait ──────────────────────────────────────────────────────────
    ("run_job builds a LOCAL adapter for a remote add-on box (the first half)", ACT,
     "    if installed_box_traits(inp.sandbox).remote:\n        return _run_remote(inp, run_id)",
     "    if inp.sandbox == \"fargate\":\n        return _run_remote(inp, run_id)"),
    ("stop_job returns 0 for a remote add-on box (the second half)", ACT,
     "    if not installed_box_traits(inp.sandbox).remote:\n        return 0\n"
     "    return await asyncio.to_thread(lambda: remote_box(inp.sandbox).stop(_box_for(inp)))",
     "    return 0"),
    ("the promotion tail launches on a local box (the vendor KeyError, one layer up)", ACT,
     "    if not installed_box_traits(sandbox).remote:\n        raise ApplicationError(",
     "    if False:\n        raise ApplicationError("),
    ("the review pass runs inline for a remote add-on box", ACT,
     "    if not installed_box_traits(inp.sandbox).remote:  # a local box reads it inline",
     "    if True:  # a local box reads it inline"),
    ("start_jobs stops stamping the traits (the fallback always runs)", ACT,
     "language=str(getattr(project, \"language\", \"\") or \"\"), box=traits),",
     "language=str(getattr(project, \"language\", \"\") or \"\")),"),
    ("start_jobs asks the BUILT-IN table (the review's first survivor: a plugin box is refused "
     "at the stamp's only writer)", ACT,
     "    traits = installed_box_traits(inp.sandbox)\n    started: list[str] = []",
     "    from openfactory.adapters.sandbox.registry import box_traits as _bt\n"
     "    traits = _bt(inp.sandbox)\n    started: list[str] = []"),
    ("the harness watcher asks the built-in table (a plugin box that streams is never watched)",
     ACT,
     "        if not installed_box_traits(inp.sandbox).streams:",
     "        from openfactory.adapters.sandbox.registry import box_traits\n"
     "        if not box_traits(inp.sandbox).streams:"),
    # ── the workflow reads its params, and names the job's box for promotion ────────────────────
    ("the stamped traits are ignored in favour of the built-in table", IO,
     "        if self.box is not None:\n            return self.box\n        return box_traits(self.sandbox)",
     "        return box_traits(self.sandbox)"),
    ("the cleanup asks the table by kind inside the workflow body", WF,
     "        if not params.traits().remote:\n            return",
     "        if not box_traits(params.sandbox).remote:\n            return"),
    ("staging is promoted on the WORKER'S box again (nothing sets PromoteInput.sandbox)", WF,
     "            PromoteInput(project=params.project, issue=params.issue,\n"
     "                         **self._promotion_box(\n"
     "                             params, live=workflow.patched(\"promotion-box-kind\"))),",
     "            PromoteInput(project=params.project, issue=params.issue),",
     E2E_PROMOTION),
    ("the release names the box outside the patch marker (an in-flight history diverges)", WF,
     "            ReleaseInput(project=params.project, issue=params.issue, **self._approval,\n"
     "                         **self._promotion_box(\n"
     "                             params, live=workflow.patched(\"promotion-box-kind\"))),",
     "            ReleaseInput(project=params.project, issue=params.issue, **self._approval,\n"
     "                         **self._promotion_box(params, live=True)),"),
    ("the unpatched arm names the box too (a pre-marker history replays a different input)", WF,
     "        return {\"sandbox\": params.sandbox} if live else {}",
     "        return {\"sandbox\": params.sandbox}"),
    # ── the deployment's box is declared ────────────────────────────────────────────────────────
    ("default_sandbox infers a vendor's box from a vendor's variable again", IO,
     "    return explicit or DEFAULT_SANDBOX",
     "    return explicit or (\"fargate\" if os.environ.get(\"OPENFACTORY_FARGATE_CLUSTER\") "
     "else DEFAULT_SANDBOX)"),
    ("the panel reads a cluster variable instead of the box's traits", APP,
     "        return installed_box_traits(kind).remote\n    except (ValueError, TypeError) as exc:",
     "        return bool(os.environ.get(\"OPENFACTORY_FARGATE_CLUSTER\")) or kind == \"fargate\"\n"
     "    except (ValueError, TypeError) as exc:"),
    ("an unknown box on the panel is a 500 instead of a warning", APP,
     "    except (ValueError, TypeError) as exc:\n        # ValueError: a kind nobody installed.",
     "    except KeyError as exc:\n        # ValueError: a kind nobody installed."),
    ("a malformed add-on row is a 500 on every job page again", APP,
     "    except (ValueError, TypeError) as exc:\n        # ValueError: a kind nobody installed.",
     "    except ValueError as exc:\n        # ValueError: a kind nobody installed."),
    ("a missing add-on's tail is swallowed at INFO with no name (the idle feed)", APP,
     "        (log.debug if quiet else log.warning)(\n"
     "            \"the remote box's event tail cannot be built for %s#%s (%s) — the panel shows local \"\n"
     "            \"events only\", project, issue, exc)",
     "        log.info(\"remote events unavailable\")"),
    ("the stream's retries warn every time (the flood, one level up)", APP,
     "        self.tail = _remote_tail(self.project, self.issue, quiet=self.failures > 0)",
     "        self.tail = _remote_tail(self.project, self.issue)"),
    ("the stream's retry stops backing off", APP,
     "            self.next_try = tick + min(2 ** self.failures, self.MAX_WAIT)",
     "            self.next_try = tick + 1"),
    ("the generator rebuilds the tail on every tick again (the measured 5-in-5)", APP,
     "                tail = (await asyncio.to_thread(stream_tail.get, tick)) if remote else None",
     "                tail = (await asyncio.to_thread(_remote_tail, project, issue)) if remote else None"),
    ("a token pool source nobody installed is folded into the outage line again", APP,
     "        log.warning(\"the declared token pool source %r is unknown (%s) — reporting the env pool \"",
     "        log.info(\"the declared token pool source %r is unknown (%s) — reporting the env pool \""),
    # ── metrics: the port, and no fall-through ──────────────────────────────────────────────────
    ("a sink that cannot read is handed back anyway", MV,
     "    if isinstance(sink, ReadableSink):\n        return sink",
     "    return sink"),
    ("the port is discovered by hasattr again (the review's second survivor)", MV,
     "    if isinstance(sink, ReadableSink):\n        return sink",
     "    if hasattr(sink, \"scan\"):\n        return sink"),
    ("a sink that records and cannot be read is read as empty in silence", MV,
     "    if not isinstance(sink, NullMetricsSink):\n        log.warning(",
     "    if False:\n        log.warning("),
    ("the dashboard reader falls through to the table variable again", MV,
     "    sink = _configured_sink()\n    return [] if sink is None else sink.scan()",
     "    sink = _configured_sink()\n"
     "    if sink is None and os.environ.get(\"OPENFACTORY_METRICS_TABLE\"):\n"
     "        from openfactory.observability.registry import build_metrics_sink\n"
     "        return build_metrics_sink(\"dynamodb\").scan()\n"
     "    return [] if sink is None else sink.scan()"),
    ("the memory reader falls through to the table variable again", QUERY,
     "    if sink is None:\n        return []\n    return sink.records_of_kind(project, kind, limit=limit)",
     "    if sink is None:\n        import os\n"
     "        if os.environ.get(\"OPENFACTORY_METRICS_TABLE\"):\n"
     "            import boto3  # noqa: F401\n        return []\n"
     "    return sink.records_of_kind(project, kind, limit=limit)"),
    ("the explicit table override stops being registry-shaped", QUERY,
     "        sink = configured_metrics_sink(table=table_name, region=region)",
     "        sink = None"),
    ("the table override spells the vendor's kind by heart again", OBS,
     "    kind = metrics_sink_kind()\n    key = _key(kind)",
     "    kind = \"dynamodb\"\n    key = _key(kind)"),
    ("a table named on a shipped sink is handed to its builder anyway (null: dropped in silence; "
     "sqlite: KeyError 'path'; memory: a fresh empty store)", OBS,
     "    if kw.get(\"table\") and key in TABLELESS_METRICS_SINKS:",
     "    if False:"),
    ("the sqlite row leaves the tableless map (the review's measured KeyError: 'path')", OBS,
     "    \"sqlite\": \"a file, OPENFACTORY_METRICS_DB\",\n", ""),
    ("the memory row leaves the tableless map (a fresh empty store handed to the deleter)", OBS,
     "    \"memory\": \"this process's memory\",\n", ""),
    ("the null row leaves the tableless map (the override dropped into the null store)", OBS,
     "    \"null\": \"nothing — it declares no store at all\",\n", ""),
    ("the metrics registry stops consulting the add-ons", OBS,
     "    builder = METRICS_SINKS.get(key) or plugins.builder(METRICS_AXIS, key, builtin=METRICS_SINKS)",
     "    builder = METRICS_SINKS.get(key)"),
    ("the DynamoDB read swallows to [] again (#126)", DYN,
     "            log.error(\"could not read %s rows for %s (%s)\", kind, project, exc)\n"
     "            raise StoreUnreadable(f\"could not read {kind} rows for {project}: {exc}\") from exc",
     "            log.error(\"could not read %s rows for %s (%s)\", kind, project, exc)\n"
     "            return []",
     "tests/test_dynamo_metrics_sink.py"),
    ("the DynamoDB scan stops parsing its stringified numbers", DYN,
     "        for it in items:\n            for k in _NUMERIC:",
     "        for it in []:\n            for k in _NUMERIC:",
     "tests/test_dynamo_metrics_sink.py"),
    # ── the other two seams ─────────────────────────────────────────────────────────────────────
    ("the session store stops consulting the add-ons", SESS,
     "    builder = SESSION_STORES.get(chosen) or plugins.builder(AXIS, chosen, builtin=SESSION_STORES)",
     "    builder = SESSION_STORES.get(chosen)"),
    ("the token pool infers a vendor source again", POOL,
     "    return explicit or DEFAULT_SOURCE",
     "    return explicit or (\"ssm\" if os.environ.get(\"OPENFACTORY_SSM_PREFIX\") else DEFAULT_SOURCE)"),
    # ── the reference deployment stops declaring what the code now requires ─────────────────────
    ("the worker's terraform names a local box", TF_WORKER,
     "        { name = \"OPENFACTORY_SANDBOX\", value = \"fargate\" },",
     "        { name = \"OPENFACTORY_SANDBOX\", value = \"container\" },"),
    ("the ECS panel's terraform drops the token-pool source", TF_PANEL,
     "        { name = \"OPENFACTORY_TOKEN_POOL_SOURCE\", value = \"ssm\" },\n",
     ""),
    ("the App Runner panel's terraform names the environment pool", TF_APPRUNNER,
     "          OPENFACTORY_TOKEN_POOL_SOURCE      = \"ssm\"",
     "          OPENFACTORY_TOKEN_POOL_SOURCE      = \"env\""),
    # ── the three AST guards, fed a real offender ───────────────────────────────────────────────
    ("a core module imports the connector by name again", QUERY, "",
     "\n\ndef _reach():\n    from openfactory.observability.dynamo import DynamoMetricsSink\n"
     "    return DynamoMetricsSink\n"),
    ("the engine compares a box to a provider's name again", ACT, "",
     "\n\ndef _is_the_vendor(kind: str) -> bool:\n    return kind == \"fargate\"\n"),
    ("a reader spells the vendor's kind again", MV, "",
     "\n\ndef _spelled():\n    return _configured_sink.__class__(\"dynamodb\")\n"),
    # ── the three survivors the review planted, verbatim ────────────────────────────────────────
    ("the connector is imported as a NAME from a core package (the review's first survivor)",
     QUERY, "",
     "\nfrom openfactory.observability import dynamo as _reach_the_vendor  # noqa: E402,F401\n"),
    ("the vendor's box package is imported as a name from the runtime package", ACT, "",
     "\n\ndef _reach_box():\n    from openfactory.runtime import fargate\n    return fargate\n"),
    ("the vendor's session store is imported as a name from the agent package", APP, "",
     "\n\ndef _reach_store():\n    from openfactory.adapters.agent import s3_session_store\n"
     "    return s3_session_store\n"),
    ("the connector is imported through a module name spelled in pieces", MV, "",
     "\n\ndef _reach_dynamically():\n    import importlib\n"
     "    return importlib.import_module('openfactory.runtime.' + 'fargate')\n"),
    ("the workflow asks the INSTALLED table at the head of an attribute chain (the review's "
     "second survivor)", WF, "",
     "\n\ndef _peek(params):\n    return installed_box_traits(params.sandbox).remote\n"),
    ("the workflow asks the table through a module attribute", WF, "",
     "\n\ndef _peek_attr(params):\n    from openfactory.adapters.sandbox import registry\n"
     "    return registry.box_traits(params.sandbox).idempotent\n"),
    ("the engine dispatches on the provider's name by membership (the review's third survivor)",
     ACT, "",
     "\n\ndef _is_the_vendor_or_kin(kind: str) -> bool:\n    return kind in (\"fargate\", \"ecs\")\n"),
    ("the engine dispatches on the provider's name by set membership", IO, "",
     "\n\ndef _is_a_vendor_box(kind: str) -> bool:\n    return kind in {\"fargate\"}\n"),
    ("the engine dispatches on the provider's name in a match arm", VIEW, "",
     "\n\ndef _vendor_arm(kind: str) -> int:\n    match kind:\n        case \"fargate\":\n"
     "            return 1\n        case _:\n            return 0\n"),
    ("the engine dispatches on the provider's name through a dict", APP, "",
     "\n\ndef _by_dict(kind: str):\n    return {\"fargate\": True, \"container\": False}[kind]\n"),
    # ── the configuration reference states the removed inference again ─────────────────────────
    ("the reference documents the inference the code no longer has (the row live on 2026-08-26)",
     DOC_REF,
     "| `OPENFACTORY_SANDBOX` | which box every job runs in: `worktree` \\| `container` \\| the kind "
     "an installed box add-on registers (`fargate`, from the AWS add-on). Unset → `container`. "
     "**Never inferred** — a cloud deployment DECLARES `OPENFACTORY_SANDBOX=fargate`; setting only "
     "the add-on's cluster coordinates leaves every job in a local container |",
     "| `OPENFACTORY_SANDBOX` | `worktree` \\| `container`. Unset → `fargate` if "
     "`OPENFACTORY_FARGATE_CLUSTER` is set, else `container` |",
     DOC_TEST),
    ("the reference forgets the token-pool source variable", DOC_REF,
     "| `OPENFACTORY_TOKEN_POOL_SOURCE` | where the panel reads the agent-token pool from (count and "
     "ids, never a value): `env` (the default — this process's environment) \\| the kind an "
     "installed add-on registers (`ssm`, from the AWS add-on). Unset → `env`. Never inferred — the "
     "reference cloud deployment declares `ssm` |\n",
     "",
     DOC_TEST),
    ("the front door's cloud column names a cluster and not the declaration", DOC_ONB,
     "| declare it: `OPENFACTORY_SANDBOX=fargate` plus the add-on's cluster coordinates (the "
     "coordinates alone change nothing — the box is never inferred from them) |",
     "| `fargate` and a cluster; nothing else changes |",
     DOC_TEST),
]
