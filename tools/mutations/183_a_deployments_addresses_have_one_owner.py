"""#183: a deployment's addresses have one owner, and the starter says what it started."""

TEST = "tests/test_a_deployments_addresses_have_one_owner.py"
LISTENERS = "openfactory/listeners.py"
HOST = "openfactory/runtime/host.py"
CLI = "openfactory/cli.py"
VIEW = "openfactory/runtime/temporal/view.py"
LOCAL = "openfactory/adapters/tracker/local.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
DOCTOR = "openfactory/doctor.py"
INIT = "openfactory/onboarding/deployment.py"
PREFLIGHT = "openfactory/preflight.py"
COMPOSE = "docker-compose.yml"

MUTATIONS = [
    # ── the starter ──────────────────────────────────────────────────────────────────────────────
    ("the engine starts on a literal again, whatever was declared", HOST,
     '"--port", str(engine_port),', '"--port", "7233",'),

    ("…and its UI on another", HOST,
     '"--ui-port", str(ui_port)]))', '"--ui-port", "8080"]))'),

    ("the children inherit the shell again instead of being handed what was started", HOST,
     "                started.append((name, subprocess.Popen(argv, env=env)))",
     "                started.append((name, subprocess.Popen(argv)))"),

    ("`up` resolves the addresses and keeps them to itself", CLI,
     "    code = host.run(deployment.plan, say=typer.echo, env=deployment.env)",
     "    code = host.run(deployment.plan, say=typer.echo)"),

    ("nothing `up` started is announced to anybody", LISTENERS,
     "        if tell:\n            publish[listener.reach_vars[0]] = where",
     "        if False:\n            publish[listener.reach_vars[0]] = where"),

    ("a declared local port is ignored and the default started instead", LISTENERS,
     '    return at, declared, "", False',
     '    return listener.default_port, declared, "", False'),

    ("`--panel-port` loses to the line the env file carries, so the links stay where they were",
     LISTENERS, "    if asked and asked != at:", "    if False and asked and asked != at:"),

    ("the engine's second name is no longer a declaration", LISTENERS,
     '("TEMPORAL_ADDRESS", "TEMPORAL_ENDPOINT"))', '("TEMPORAL_ADDRESS",))'),

    # ── the refusals ─────────────────────────────────────────────────────────────────────────────
    ("an engine declared on another machine gets a second one started beside it", LISTENERS,
     "    if host not in _THIS_MACHINE:\n        if not listener.scheme:",
     "    if host not in _THIS_MACHINE:\n        if False:"),

    ("two lines naming different ports for one listener are both 'honoured'", LISTENERS,
     "    if wanted and wanted != at:", "    if False:"),

    ("a port variable that is not a port is a traceback, not a sentence", LISTENERS,
     "    if not raw.isdigit() or not 0 < int(raw) < 65536:", "    if False:"),

    ("an engine address with no port starts on the default in silence", LISTENERS,
     "    if at is None:\n        raise CannotHonour(", "    if False:\n        raise CannotHonour("),

    # ── no guess for an address a person clicks ──────────────────────────────────────────────────
    ("the engine UI is guessed again", VIEW,
     '        return "https://cloud.temporal.io"\n    return ""',
     '        return "https://cloud.temporal.io"\n    return "http://localhost:8233"'),

    ("a workflow path is appended to no address at all", VIEW,
     '/history" if base else ""', '/history"'),

    ("the panel's address is guessed again", LOCAL,
     '    return PANEL.declared().rstrip("/")',
     '    return (PANEL.declared() or PANEL.local()).rstrip("/")'),

    ("the cockpit links somebody else's console when no engine is declared", APP,
     '    temporal_base, namespace = "", ""',
     '    temporal_base, namespace = "https://cloud.temporal.io", ""'),

    ("the greyed Engine button has no sentence", APP,
     '        "engine_ui_hint": "" if temporal else _engine_ui_unsaid(),',
     '        "engine_ui_hint": "",'),

    ("the engine frame never says the UI is unknown", APP,
     '"ui_hint": "" if base else _engine_ui_unsaid()}', '"ui_hint": ""}'),

    ("a running card's engine link is an anchor built from an empty address", PANEL,
     '      ${engineLink(j.temporal_url,"chip","engine ↗")}</div>',
     '      <a class="chip" href="${esc(safeUrl(j.temporal_url))}" target="_blank">engine ↗</a>'
     '</div>'),

    # ── the doctor ───────────────────────────────────────────────────────────────────────────────
    ("the doctor stops asking about the engine's UI", DOCTOR,
     '    ui_up, ui_where = answered.get("engine UI", (True, ""))',
     '    ui_up, ui_where = True, ""'),

    ("the doctor looks on the default port, not where `up` starts the listener", DOCTOR,
     '            where = listener.declared() or up_starts.get(listener.name, "")',
     "            where = listener.declared() or listener.local()"),

    ("a declaration `up` refuses is probed as if it were fine", DOCTOR,
     '            return {"refused": (False, str(exc))}', "            up_starts = {}"),

    ("the refusal reaches the doctor and is not reported", DOCTOR,
     '    if "refused" in answered:', '    if "never" in answered:'),

    # ── init, preflight, compose ─────────────────────────────────────────────────────────────────
    ("`init` stops declaring where the engine's UI is", INIT,
     "{ENGINE_UI.reach_vars[0]}={ENGINE_UI.local()}\n", ""),

    ("preflight goes back to a table of its own", PREFLIGHT,
     "PUBLISHED_PORTS: tuple[tuple[str, str, int], ...] = tuple(\n"
     "    (listener.name, listener.port_var, listener.default_port) for listener in LISTENERS)",
     'PUBLISHED_PORTS: tuple[tuple[str, str, int], ...] = (\n'
     '    ("panel", "PANEL_PORT", 8787), ("engine UI", "TEMPORAL_UI_PORT", 8080),\n'
     '    ("engine", "TEMPORAL_PORT", 7233))'),

    ("the compose panel links the UI on a port the stack does not publish", COMPOSE,
     "      TEMPORAL_UI_URL: ${TEMPORAL_UI_URL:-http://localhost:${TEMPORAL_UI_PORT:-8080}}\n"
     "      # UNSET MEANS OPEN",
     "      TEMPORAL_UI_URL: http://localhost:8233\n      # UNSET MEANS OPEN"),

    ("a UI address declared past compose is overwritten by the file", COMPOSE,
     "      TEMPORAL_UI_URL: ${TEMPORAL_UI_URL:-http://localhost:${TEMPORAL_UI_PORT:-8080}}\n"
     "      # Credentials.",
     "      TEMPORAL_UI_URL: http://localhost:${TEMPORAL_UI_PORT:-8080}\n"
     "      # Credentials."),
]
