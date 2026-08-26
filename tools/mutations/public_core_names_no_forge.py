"""The public core names no forge (2026-08-26): the API budget is a question on the tracker
port with THREE answers, the forge credential is a question on the credential registry, and the
reference harnesses stand on their own.

Each cut is one way the claim comes apart: a vendor answers `None` again; the floor renders a
declared absence as a failure, or a failure as fine, or judges by a number of its own; the
doctor passes an unreadable probe; the doctor asks one vendor by name; the poller parks every
project on one vendor's quota, or skips the whole tick; the announcement reaches a project still
being scanned; the neutral route invents `ok`; the mint reaches a vendor whose row declares
none, through either door; the vendor-default table closes again; the release path mints for
any forge; the login is not discovered; `init` decides by the vendor's name; a sibling import
returns; the brief drops the card's Context or In-scope; the reference harness reads roles from
its own copy; the reference tracker stops reporting, or stops raising; the worker forgets the
activity; the panel composes a line nothing reads; the ladder spells a vendor.
"""

TEST = "tests/test_public_core_names_no_forge.py"

_FLOOR_TEST = "tests/test_the_floor_is_a_platform_capability.py"
_TEMPORAL_TEST = "tests/test_temporal_workflow.py"
_FIRST_HOUR_TEST = "tests/test_the_first_hour_fails_by_name.py"

_FORGE_PROVIDER_OLD = (
    "                          token_provider=(None if forge_token_for(project)\n"
    "                                          else deployment_forge_provider(project))),\n"
    "        # WHICH harness writes the code is config, not an import (agent/registry.py)\n")
_FORGE_PROVIDER_NEW = (
    "                          token_provider=(None if forge_token_for(project)\n"
    "                                          else _bot_token_provider())),\n"
    "        # WHICH harness writes the code is config, not an import (agent/registry.py)\n")

MUTATIONS = [
    # ── the port's three answers ────────────────────────────────────────────────────────────────
    ("the Jira tracker answers None instead of the declared sentinel",
     "openfactory/adapters/tracker/jira.py",
     "        return NOT_REPORTED\n",
     "        return None\n"),
    ("the reference tracker stops reporting a budget it has",
     "openfactory/adapters/tracker/github.py",
     "        return github_rate(self.token)\n",
     '        return "not_reported"\n'),
    ("the reference probe returns a sentinel on failure instead of raising",
     "openfactory/adapters/tracker/github_project.py",
     "        raise BudgetUnreadable(\n"
     '            f"could not read the GitHub rate limit ({str(exc)[:200]})") from exc\n',
     '        return "not_reported"  # noqa: RET\n'),
    # ── the floor renders each state as itself ──────────────────────────────────────────────────
    ("a declared absence renders as a failed read",
     "openfactory/floor/reading.py",
     "            if answer == NOT_REPORTED:\n                row.update(state=\"not_reported\")\n",
     "            if answer == NOT_REPORTED:\n                row.update(state=\"unread\")\n"),
    ("a failed read renders as fine",
     "openfactory/floor/reading.py",
     "        except BudgetUnreadable as exc:\n            row.update(state=\"unread\", error=str(exc)[:200])\n",
     "        except BudgetUnreadable as exc:\n            row.update(state=\"ok\", error=str(exc)[:200])\n"),
    ("the floor judges by a number of its own instead of the adapter's floor",
     "openfactory/floor/reading.py",
     '                    state="low" if answer.low else "ok", vendor=answer.vendor or kind,\n',
     '                    state="low" if answer.remaining < 200 else "ok", vendor=answer.vendor or kind,\n',
     _FLOOR_TEST),
    ("the summary is the first row, not the worst",
     "openfactory/floor/reading.py",
     "    worst = min(rows, key=lambda r: _STATE_RANK.get(str(r.get(\"state\")), 99))\n",
     "    worst = rows[0]\n"),
    ("a shared credential is probed once per project",
     "openfactory/floor/reading.py",
     "        if key in rows:\n            rows[key][\"projects\"].append(name)\n            continue\n",
     "        if False:\n            continue\n"),
    ("the ladder spells the vendor itself",
     "openfactory/floor/ladder.py",
     '        vendor = str(budget.get("vendor") or budget.get("kind") or "API")\n',
     '        vendor = "GitHub"\n',
     _FLOOR_TEST),
    # ── the doctor ──────────────────────────────────────────────────────────────────────────────
    ("an unreadable budget passes the doctor's check",
     "openfactory/doctor.py",
     "    if not isinstance(budget, Budget):\n        return Finding(\n            \"api_budget\", False,\n",
     "    if not isinstance(budget, Budget):\n        return Finding(\n            \"api_budget\", True,\n"),
    ("an unreadable budget is rendered as a declared absence",
     "openfactory/doctor.py",
     "    if budget == NOT_REPORTED:\n",
     "    if budget is None or budget == NOT_REPORTED:\n"),
    ("the doctor asks one vendor by name again, with the project's tracker credential",
     "openfactory/doctor.py",
     "            return build_tracker(project, token_provider=_board_credential(project)).budget()\n",
     "            from openfactory.adapters.tracker.github_project import github_rate\n"
     "            return github_rate(_board_credential(project)())\n"),
    # ── the poller and its announcement ─────────────────────────────────────────────────────────
    ("a spent vendor parks every project",
     "openfactory/runtime/temporal/poller.py",
     "        projects = [p for p in projects if str(p.get(\"project\")) not in paused]\n",
     "        projects = list(projects)\n",
     _TEMPORAL_TEST),
    ("one spent vendor skips the whole tick",
     "openfactory/runtime/temporal/poller.py",
     "        if paused and not projects:\n",
     "        if paused:\n",
     _TEMPORAL_TEST),
    ("the pause is announced to projects still being scanned",
     "openfactory/runtime/temporal/activities.py",
     "        if inp.projects and str(getattr(project, \"name\", \"\") or \"\") not in inp.projects:\n            continue\n",
     "        if False:\n            continue\n"),
    ("the activity reads nothing",
     "openfactory/runtime/temporal/activities.py",
     "    return await asyncio.to_thread(budgets)\n",
     "    return []\n"),
    ("the worker forgets the activity",
     "openfactory/runtime/temporal/worker.py",
     "    available_slots, preflight_check, split_ticket, tracker_budgets,\n",
     "    available_slots, preflight_check, split_ticket,\n",
     _TEMPORAL_TEST),
    # ── the neutral route and the panel ─────────────────────────────────────────────────────────
    ("the route invents ok",
     "openfactory/api/app.py",
     "    return {\"summary\": budget_summary(rows), \"rows\": rows}\n",
     "    return {\"summary\": {\"state\": \"ok\"}, \"rows\": rows}\n"),
    ("the panel composes a budget line nothing reads",
     "openfactory/api/panel.html",
     "  el.title=[fs.detail,fs.meta,budgetLine(_budget)].filter(Boolean).join(\" — \")||fs.clause;\n",
     "  el.title=[fs.detail,fs.meta].filter(Boolean).join(\" — \")||fs.clause;\n"),
    # ── the credential is the vendor's row ──────────────────────────────────────────────────────
    ("a vendor with no mint gets the reference mint anyway",
     "openfactory/credentials.py",
     "    return row.mint() if row is not None and row.mint is not None else None\n",
     "    if row is not None and row.mint is not None:\n        return row.mint()\n"
     "    from openfactory.factory import github_app_token_from_env\n\n"
     "    return github_app_token_from_env()\n"),
    ("a vendor with no provider gets the reference minter through the other door",
     "openfactory/credentials.py",
     "    return row.provider() if row is not None and row.provider is not None else None\n",
     "    if row is not None and row.provider is not None:\n        return row.provider()\n"
     "    from openfactory.factory import _bot_token_provider\n\n"
     "    return _bot_token_provider()\n"),
    ("the vendor-default table closes again",
     "openfactory/credentials.py",
     "    row = _row(kind)\n    return (row.env or \"\") if row is not None else \"\"\n",
     "    return {\"jira\": \"JIRA_API_TOKEN\", \"azure_devops\": \"AZURE_DEVOPS_PAT\"}.get(kind, \"\")\n"),
    ("build_runner hands every forge the reference minter",
     "openfactory/factory.py",
     _FORGE_PROVIDER_OLD,
     _FORGE_PROVIDER_NEW),
    ("the release path mints for any forge and overrides the project's own token",
     "openfactory/actions/catalog.py",
     "    forge = build_forge(p, token=forge_token_for(p) or deployment_forge_token(p))\n"
     "    return p, manifest, forge\n",
     "    from openfactory.factory import github_app_token_from_env\n\n"
     "    forge = build_forge(p, token=github_app_token_from_env())\n"
     "    return p, manifest, forge\n"),
    ("the login is never discovered",
     "openfactory/credentials.py",
     "        return row.discover()\n",
     "        return None\n"),
    ("no tracker declares a board to create",
     "openfactory/adapters/board_setup/registry.py",
     "    return builder() if builder is not None else None\n",
     "    return None\n"),
    ("init stops asking the registry",
     "openfactory/cli.py",
     "    create_board = board_creator(tracker_kind or \"github\")\n",
     "    create_board = None\n",
     _FIRST_HOUR_TEST),
    # ── the harnesses ───────────────────────────────────────────────────────────────────────────
    ("a sibling import returns",
     "openfactory/adapters/agent/codex.py",
     "",
     "\nimport openfactory.adapters.agent.claude_code  # noqa: E402,F401\n"),
    ("the brief drops the card's Context",
     "openfactory/adapters/agent/base.py",
     "    if t.context:\n        parts += [\"\", \"## Context\", t.context]\n",
     ""),
    ("the brief drops the card's In-scope list",
     "openfactory/adapters/agent/base.py",
     "    if t.in_scope:\n        parts += [\"\", \"## In scope\"] + [f\"- {x}\" for x in t.in_scope]\n",
     ""),
    ("the reference harness keeps a brief of its own",
     "openfactory/adapters/agent/claude_code.py",
     "        return ticket_brief(context)\n",
     "        return ticket_brief(context).split(\"## In scope\")[0]\n"),
    ("the reference harness stops reading the planner role from the one home",
     "openfactory/adapters/agent/claude_code.py",
     "        role = role_prompt(\"planner\")\n",
     "        role = \"\"\n"),
    # ── the review's cuts (2026-08-26): identity, rank, the gate, the marker, the row ──────────
    ("the budget rows are keyed by the credential's VALUE again, which the mint renews",
     "openfactory/floor/reading.py",
     "        key = (kind, tracker_credential_source(project))\n",
     "        key = (kind, tracker_token_for(project) or deployment_tracker_token(project) or \"\")\n"),
    ("two DIFFERENT credentials collapse into one probe",
     "openfactory/floor/reading.py",
     "        key = (kind, tracker_credential_source(project))\n",
     "        key = (kind, \"\")\n"),
    ("a project's own variable reads as the generic pair's identity",
     "openfactory/credentials.py",
     "            return f\"env:{named}\", value\n",
     "            return f\"generic:{axis}\", value\n"),
    ("a vendor with no mint gets a deployment identity anyway",
     "openfactory/credentials.py",
     "    return f\"deployment:{kind}\" if row is not None and row.mint is not None else \"\"\n",
     "    return f\"deployment:{kind}\"\n"),
    ("low no longer outranks unread",
     "openfactory/floor/reading.py",
     "_STATE_RANK = {\"low\": 0, \"unread\": 1, \"ok\": 2, \"not_reported\": 3}\n",
     "_STATE_RANK = {\"low\": 0, \"unread\": 0, \"ok\": 2, \"not_reported\": 3}\n"),
    ("unread no longer outranks ok",
     "openfactory/floor/reading.py",
     "_STATE_RANK = {\"low\": 0, \"unread\": 1, \"ok\": 2, \"not_reported\": 3}\n",
     "_STATE_RANK = {\"low\": 0, \"unread\": 1, \"ok\": 1, \"not_reported\": 3}\n"),
    ("the poller loses its replay gate",
     "openfactory/runtime/temporal/poller.py",
     "        if workflow.patched(\"tracker-budgets\"):\n",
     "        if True:\n",
     _TEMPORAL_TEST),
    ("the pre-seam arm schedules the live activity",
     "openfactory/runtime/temporal/poller.py",
     "            _PRE_SEAM_BUDGET_ACTIVITY,\n",
     "            tracker_budgets,\n",
     _TEMPORAL_TEST),
    ("the pre-seam arm scans before it reads the budget",
     "openfactory/runtime/temporal/poller.py",
     "        budget = await workflow.execute_activity(\n            _PRE_SEAM_BUDGET_ACTIVITY,\n",
     "        await workflow.execute_activity(\n            scan_projects,\n"
     "            start_to_close_timeout=timedelta(minutes=1),\n            retry_policy=_RETRY,\n"
     "        )\n        budget = await workflow.execute_activity(\n            _PRE_SEAM_BUDGET_ACTIVITY,\n",
     _TEMPORAL_TEST),
    ("the marker forgets the vendor",
     "openfactory/runtime/temporal/activities.py",
     "    return f\"rate-pause-{slug}-{reset_epoch}.said\" if slug else f\"rate-pause-{reset_epoch}.said\"\n",
     "    return f\"rate-pause-{reset_epoch}.said\"\n"),
    ("the poller does not tell the announcement which vendor",
     "openfactory/runtime/temporal/poller.py",
     "                               kind=str(row.get(\"kind\") or \"\"),\n",
     "",
     _TEMPORAL_TEST),
    ("a non-row add-on value is handed out as a row",
     "openfactory/adapters/credential/registry.py",
     "    if not isinstance(row, CredentialRow):\n",
     "    if False:\n"),
    ("the announcement names the reference vendor instead of the row's kind",
     "openfactory/runtime/temporal/poller.py",
     '                               kind=str(row.get("kind") or ""),\n',
     '                               kind="github",\n',
     "tests/test_temporal_workflow.py"),
]
