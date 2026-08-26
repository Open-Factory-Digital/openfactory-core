"""Public core, wave 2: every registry opens to the loader; init, project init, conformance and
the worker derive from them.

Each cut puts one measured defect back — a registry that stops asking the loader, a gate that
moves back in front of a lookup, a hand copy that returns, a fallback that goes silent — and the
guard that owns it must go red. A survivor is a finding about the guard.
"""

TEST = "tests/test_the_doors_derive_from_the_registries.py"
STRANGER = "tests/test_a_stranger_can_add_an_adapter.py"
VOICE = "tests/test_the_open_distribution_has_a_voice.py"

ENV = "openfactory/adapters/environment/registry.py"
IDENT = "openfactory/identity/registry.py"
BOARD = "openfactory/adapters/board/factory.py"
NOTIFY = "openfactory/adapters/notify/registry.py"
WORKER = "openfactory/runtime/temporal/worker.py"
DEPLOY = "openfactory/onboarding/deployment.py"
CLI = "openfactory/cli.py"
CONF = "openfactory/conformance/adapters.py"
PLUGINS = "openfactory/plugins.py"

MUTATIONS = [
    # ── the registries stop asking ──────────────────────────────────────────────────────────────
    ("the CI registry stops consulting the loader", ENV,
     "    added = plugins.builder(AXIS, kind, builtin=OBSERVERS)\n",
     "    added = None\n", STRANGER),

    ("the CI registry hands an add-on the caller's credential", ENV,
     "        return added(project, token=None)\n",
     "        return added(project, token=token)\n"),

    ("the CI refusal stops saying whether the kind was inherited", ENV,
     '    origin = ("named by `forge.options.ci`" if declared_ci(project)\n'
     '              else "inherited from the forge kind, because the project names no '
     '`forge.options.ci`")\n',
     '    origin = "unknown"\n'),

    ("the identity registry stops consulting the loader", IDENT,
     "    builder = IDENTITIES.get(kind) or plugins.builder(AXIS, kind, builtin=IDENTITIES)\n",
     "    builder = IDENTITIES.get(kind)\n", STRANGER),

    ("the identity registry uses whatever an add-on hands back", IDENT,
     "    if not isinstance(provider, IdentityProvider):\n",
     "    if False:\n"),

    ("the board registry stops consulting the loader", BOARD,
     "    builder = BOARDS.get(kind) or plugins.builder(AXIS, kind, builtin=BOARDS)\n",
     "    builder = BOARDS.get(kind)\n", STRANGER),

    ("the coordinates gate moves back in front of the board lookup", BOARD,
     "    builder = BOARDS.get(kind) or plugins.builder(AXIS, kind, builtin=BOARDS)\n"
     "    if builder is not None:\n",
     "    builder = BOARDS.get(kind) or plugins.builder(AXIS, kind, builtin=BOARDS)\n"
     "    if not (options.get('board_owner') and options.get('board_number')) and kind not in "
     "BOARDS:\n        return None\n"
     "    if builder is not None:\n"),

    ("BOARD_KINDS stops being the table's projection", BOARD,
     "BOARD_KINDS = tuple(BOARDS)\n",
     'BOARD_KINDS = ("github", "jira", "azure_devops", "acme")\n'),

    ("the notifier registry stops consulting the loader", NOTIFY,
     "    builder = NOTIFIERS.get(kind) or plugins.builder(AXIS, kind, builtin=NOTIFIERS)\n",
     "    builder = NOTIFIERS.get(kind)\n"),

    ("a channel-only add-on falls back in SILENCE", NOTIFY,
     '        log.warning("project %s speaks through %r, which %s; its notifications go to %s "\n'
     '                    "(install a `%s.%s` entry point to change that)",\n'
     '                    name or "?", kind, reason, type(fallback).__name__, AXIS, kind)\n',
     "        pass\n"),

    ("a kind neither axis knows RAISES from the notifier", NOTIFY,
     '                    name or "?", kind, reason, type(fallback).__name__, AXIS, kind)\n'
     "        return fallback\n",
     '                    name or "?", kind, reason, type(fallback).__name__, AXIS, kind)\n'
     "        if not _channel_knows(kind):\n            raise ValueError(kind)\n"
     "        return fallback\n"),

    ("a non-notifier from an add-on is used as if it could speak", NOTIFY,
     "    if not isinstance(built, Notifier):\n",
     "    if False:\n"),

    ("the inferred panel steps in front of Telegram again", NOTIFY,
     "    if declared or kind != DEFAULT_KIND:\n",
     "    if True:\n", VOICE),

    ("a row that cannot post falls back in SILENCE (the reviewer's Slack-without-a-token)",
     NOTIFY,
     "        log.warning(\"project %s speaks through %r, but that notifier cannot post — "
     "missing %s; \"\n"
     "                    \"its notifications go to %s until that is filled in\",\n"
     "                    name or \"?\", kind, lacked, type(fallback).__name__)\n",
     "        pass\n"),

    ("the Slack row answers a bare None — what was missing is lost", NOTIFY,
     "    if missing:\n        return CannotPost(missing)\n",
     "    if missing:\n        return None\n"),

    ("the warning fires for a row that CAN post too", NOTIFY,
     "    if declared or kind != DEFAULT_KIND:\n        return built\n",
     "    if declared or kind != DEFAULT_KIND:\n"
     "        log.warning('project %s speaks through %r, but that notifier cannot post', "
     "name, kind)\n"
     "        return built\n"),

    # ── the worker ──────────────────────────────────────────────────────────────────────────────
    ("the worker starts one adapter per PROJECT, doubling Slack's sockets", WORKER,
     "        if kind not in by_kind:\n"
     "            by_kind[kind] = project\n"
     "            kinds.append(kind)\n",
     "        by_kind[kind + str(len(kinds))] = project\n"
     "        kinds.append(kind + str(len(kinds)))\n"),

    ("the worker starts only the first kind it meets", WORKER,
     "    for kind in kinds:\n"
     "        try:\n"
     "            adapter = build_channel(by_kind[kind])\n",
     "    for kind in kinds[:1]:\n"
     "        try:\n"
     "            adapter = build_channel(by_kind[kind])\n"),

    ("a channel that cannot start takes the worker down", WORKER,
     "        except Exception as exc:  # noqa: BLE001 — one channel's failure is a line, "
     "not a dead worker\n",
     "        except ImportError as exc:\n"),

    ("no projects means no listener at all — not even the panel", WORKER,
     '        kinds, by_kind = ["panel"], {"panel": None}\n',
     "        kinds, by_kind = [], {}\n"),

    ("main goes back to the project-less build", WORKER,
     "    _channels = start_channel_listeners(projects)  # noqa: F841 — held: they own the "
     "listeners\n",
     "    from openfactory.adapters.channel import build_channel\n"
     "    _channels = build_channel()  # noqa: F841\n"
     "    _channels.start_listeners()\n"),

    # ── init ────────────────────────────────────────────────────────────────────────────────────
    ("the forge vocabulary is a hand copy again", DEPLOY,
     '    return tuple(plugins.known("forge", _table("forge")))\n',
     '    return tuple(sorted(_table("forge")))\n'),

    ("the shipped set is a hand copy one row short (jira rendered as an add-on)", DEPLOY,
     "    return tuple(_table(axis))\n",
     '    return tuple(k for k in _table(axis) if k != "jira")\n'),

    ("an installed add-on counts as shipped — its placeholder and to-do line vanish", DEPLOY,
     "    return tuple(_table(axis))\n",
     "    return choices(axis)\n"),

    ("an add-on answer renders NOTHING — the file that looks configured", DEPLOY,
     "    for axis, kind in answers.add_ons():\n"
     "        if axis in (\"forge\", \"tracker\"):\n"
     "            parts.append(_add_on_block(axis, kind, out))\n",
     "    pass\n"),

    ("the add-on's to-do line is dropped", DEPLOY,
     "    out.remaining.append(\n"
     "        f\"add the variables the `{kind}` {axis} add-on documents",
     "    (\n"
     "        f\"add the variables the `{kind}` {axis} add-on documents"),

    ("the question's options freeze at import", DEPLOY,
     "    @property\n"
     "    def options(self) -> tuple[str, ...]:\n"
     "        return self.choose()\n",
     "    @property\n"
     "    def options(self) -> tuple[str, ...]:\n"
     "        return tuple(k for k in self.choose() if k != 'acme')\n"),

    # ── project init ────────────────────────────────────────────────────────────────────────────
    ("the known-forge list stops reading the add-ons", CLI,
     '    return plugins.known("forge", FORGES)\n',
     "    return sorted(FORGES)\n"),

    ("--provider is a bypass rather than a name the registry knows", CLI,
     "    if chosen and chosen not in _known_forges():\n"
     "        raise ValueError(\n",
     "    if False:\n"
     "        raise ValueError(\n"),

    ("--provider lets a SHIPPED kind claim a foreign host (the #162 door, reopened by flag)",
     CLI,
     "    if chosen and chosen in _installed_forges():\n",
     "    if chosen and chosen in _known_forges():\n"),

    ("a shipped kind named over ANOTHER shipped kind's host is waved through", CLI,
     "    if owner == chosen:\n"
     "        return \"\"\n"
     "    if owner:\n"
     "        raise ValueError(\n",
     "    if owner:\n"
     "        return \"\"\n"
     "    if False:\n"
     "        raise ValueError(\n"),

    ("the shipped-host table loses a shipped forge", CLI,
     '    return {"github": github,\n'
     '            "azure_devops": {"dev.azure.com", "ssh.dev.azure.com", "visualstudio.com"}}\n',
     '    return {"github": github}\n'),

    ("--provider is read and the row is written as GitHub anyway", CLI,
     '        kind = (provider or "").strip().lower() or "github"\n',
     '        kind = "github"\n'),

    ("the refusal stops naming the installed add-on", CLI,
     "                       + (f\"  · an installed add-on's host: re-run with --provider \"\n"
     "                          f\"<{'|'.join(installed)}> — the add-on claims the host by "
     "name\\n\"\n"
     "                          if installed else \"\")\n",
     '                       + ""\n'),

    # ── conformance ─────────────────────────────────────────────────────────────────────────────
    ("a factory FUNCTION is judged the instance again", CLI,
     "    elif inspect.isroutine(target):\n"
     "        adapter = target()\n"
     "    else:\n"
     "        adapter = target\n",
     "    else:\n"
     "        adapter = target\n"),

    ("a CLASS is judged the instance (its unbound methods satisfy the port)", CLI,
     "    if isinstance(target, type):\n"
     "        adapter = target()\n"
     "    elif isinstance(target, protocol):\n",
     "    if isinstance(target, protocol):\n"),

    ("an INSTANCE that fails the port is CALLED (the reviewer's half channel)", CLI,
     "    else:\n"
     "        adapter = target\n"
     "    findings = check(adapter)\n",
     "    else:\n"
     "        adapter = target()\n"
     "    findings = check(adapter)\n"),

    ("`callable` replaces `isroutine` — an instance with a __call__ is called", CLI,
     "    elif inspect.isroutine(target):\n",
     "    elif callable(target):\n"),

    ("the notifier check stops naming its port", CONF,
     "    if not isinstance(notifier, Notifier):\n",
     "    if False:\n"),

    ("the identity check stops listing what the instance lacks", CONF,
     '            "identity.protocol", f"does not satisfy IdentityProvider (missing: '
     '{missing})",\n',
     '            "identity.protocol", "does not satisfy IdentityProvider",\n'),

    ("the harness check goes shape-only", CONF,
     "            result = harness.execute(sandbox=sandbox, workspace=workspace, "
     "context=context)\n",
     "            from openfactory.contracts import AgentRunResult as _R\n"
     "            result = _R(ok=True)\n"),

    ("the forge check stops asking about a foreign host", CONF,
     "        if got != _FOREIGN_URL or carries_credentials(got):\n",
     "        if False:\n"),

    ("the observer check believes an optimistic health", CONF,
     "        elif alive:\n",
     "        elif False:\n"),

    ("the box check starts running things", CONF,
     "    try:\n"
     "        lines = box.tail()\n",
     "    box.run(workspace=None, command='true', timeout=1)\n"
     "    try:\n"
     "        lines = box.tail()\n"),

    ("a conformance row loses its port", CONF,
     '    "ci": (check_observer, EnvironmentObserver),\n',
     '    "ci": (check_observer, object),\n'),

    # ── the published list ──────────────────────────────────────────────────────────────────────
    ("an axis is published that no registry asks for", PLUGINS,
     '    "notifier", "identity", "role", "session_store", "token_pool", "box_runner",\n',
     '    "notifier", "identity", "role", "session_store", "token_pool", "box_runner", '
     '"widget",\n',
     STRANGER),

    ("an axis is asked for that the list does not publish", PLUGINS,
     '    "notifier", "identity", "role", "session_store", "token_pool", "box_runner",\n',
     '    "notifier", "identity", "role", "session_store", "token_pool",\n',
     STRANGER),
    ("a notifier row that raises takes the whole round down with it",
     "openfactory/adapters/notify/registry.py",
     "    try:\n        built = builder(project)\n    except Exception as exc:",
     "    try:\n        built = builder(project)\n    except AssertionError as exc:"),
]
