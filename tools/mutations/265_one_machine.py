"""Mutation plan for #265 slice 6 — previews on the one-machine door: the port a name derives, a
collision refused by name, the router's loopback target and the key before it, nothing listening
on every interface, what a loopback preview reaches measured and said, the card with no runtime,
`init`'s commented lines and `doctor`'s four lines (the design's §7.2, §5.4, §8 and S12).

Each row takes away one rule the one-machine door's safety or its honesty rests on; every row must
turn `tests/test_a_preview_is_reached_on_one_machine.py` red. The live run
(`tests/test_a_preview_opens_on_one_machine.py`) is not a target: it needs a daemon and a build,
and every property it measures is also held there without one.
"""

TEST = "tests/test_a_preview_is_reached_on_one_machine.py"

PREVIEW = "openfactory/preview/__init__.py"
ASSEMBLE = "openfactory/preview/assemble.py"
STEPS = "openfactory/preview/steps.py"
COMPOSE = "openfactory/adapters/preview/compose.py"
BASE = "openfactory/adapters/preview/base.py"
NONE = "openfactory/adapters/preview/none.py"
APP = "openfactory/api/app.py"
CLI = "openfactory/cli.py"
DEPLOY = "openfactory/onboarding/deployment.py"
DOCTOR = "openfactory/doctor.py"

MUTATIONS = [
    # ── the port is the name's ──
    ("the assembler publishes a port of its own choosing, not the one the router derives",
     ASSEMBLE,
     "            port = preview.loopback_port(labels[name], loopback_range)\n",
     "            port = loopback_range[0] + len(ports)\n"),
    ("the derivation ignores the name: every service of every unit derives one port", PREVIEW,
     "    return lo + int(hashlib.sha256(label.encode()).hexdigest(), 16) % (hi - lo + 1)",
     "    return lo"),
    ("the last port of the range is never derived", PREVIEW,
     "    return lo + int(hashlib.sha256(label.encode()).hexdigest(), 16) % (hi - lo + 1)",
     "    return lo + int(hashlib.sha256(label.encode()).hexdigest(), 16) % (hi - lo)"),
    ("two services of a unit deriving one port are not refused", ASSEMBLE,
     "            if clash:\n", "            if False:\n"),
    ("a loopback deployment that names no ports is assembled anyway", ASSEMBLE,
     "    if reach == \"loopback\" and cfg.expose and not loopback_range:",
     "    if False:"),

    # ── a collision fails the start by name ──
    ("a port something already answers on is not checked before the build", COMPOSE,
     "                    for svc, port in sorted(plan.loopback_ports.items()) if _listening(port)]",
     "                    for svc, port in sorted(plan.loopback_ports.items()) if False]"),
    ("the check never sees a listener: a connect that answers is read as a free port", COMPOSE,
     "        with socket.create_connection((preview.LOOPBACK_ADDRESS, port), timeout=1):\n"
     "            return True\n",
     "        with socket.create_connection((preview.LOOPBACK_ADDRESS, port), timeout=1):\n"
     "            return False\n"),
    ("the holder is never named: another preview's port reads as another program's", COMPOSE,
     "        if project and unit:\n", "        if False:\n"),
    ("the holder is looked up among every running container, not the one publishing the port",
     COMPOSE,
     "    r = _host([\"docker\", \"ps\", \"--filter\", f\"publish={port}\", \"--format\",",
     "    r = _host([\"docker\", \"ps\", \"--filter\", \"status=running\", \"--format\","),
    ("docker's own `already allocated` is not read into the by-name sentence", COMPOSE,
     "        if plan.reach == \"loopback\" and any(s in lowered for s in (",
     "        if False and any(s in lowered for s in ("),

    # ── the router's loopback target, and the key before it ──
    ("the router targets the alias on one machine too", PREVIEW,
     "    if reach() != LOOPBACK:\n        return f\"http://{host.label}:{port}\"",
     "    if True:\n        return f\"http://{host.label}:{port}\""),
    ("on the loopback the router targets the container's port, not the one the name derives",
     PREVIEW,
     "    return f\"http://{LOOPBACK_ADDRESS}:{loopback_port(host.label, span)}\"",
     "    return f\"http://{LOOPBACK_ADDRESS}:{port}\""),
    ("a loopback deployment with no ports is routed somewhere anyway", PREVIEW,
     "    if span is None:\n        return None\n",
     "    if span is None:\n        span = (8000, 8000)\n"),
    ("on one machine the key is not asked before the port is", APP,
     "    if not preview.admits(request.cookies.get(cookie, \"\"), project=record.project,",
     "    if preview.reach() != \"loopback\" and not preview.admits(request.cookies.get(cookie, "
     "\"\"), project=record.project,"),
    ("a redirect naming the loopback target reaches the browser as it is", APP,
     "        if low == \"location\" and v.startswith(upstream_base):",
     "        if False:"),

    # ── nothing listens on every interface ──
    ("the assembler publishes on every interface", ASSEMBLE,
     "                             \"host_ip\": preview.LOOPBACK_ADDRESS, \"protocol\": \"tcp\"}]",
     "                             \"host_ip\": \"0.0.0.0\", \"protocol\": \"tcp\"}]"),
    ("the row runs a plan published on every interface", BASE,
     "    if (want is not None and first.get(\"host_ip\") == preview.LOOPBACK_ADDRESS\n",
     "    if (want is not None\n"),
    ("the row runs a plan published on a port no name derives", BASE,
     "            and str(first.get(\"published\")) == str(want)\n",
     "            and True\n"),
    ("the row runs a plan that publishes a service twice", BASE,
     "    first = entries[0] if len(entries) == 1 and isinstance(entries[0], dict) else {}",
     "    first = entries[0] if entries and isinstance(entries[0], dict) else {}"),
    ("the row runs a plan that publishes a service nobody opens", BASE,
     "            if key == \"ports\" and plan.reach == \"loopback\" and name in plan.expose:",
     "            if key == \"ports\" and plan.reach == \"loopback\":"),
    ("the panel `up` starts listens on every interface", CLI,
     "    host: str = typer.Option(\"127.0.0.1\", help=\"Bind host\"),",
     "    host: str = typer.Option(\"0.0.0.0\", help=\"Bind host\"),"),
    ("the probe's own listener listens on every interface", COMPOSE,
     "        server = http.server.ThreadingHTTPServer((preview.LOOPBACK_ADDRESS, 0), handler)",
     "        server = http.server.ThreadingHTTPServer((\"0.0.0.0\", 0), handler)"),

    # ── what a loopback preview reaches: measured, and said whichever way it fell ──
    ("the loopback edge masquerades like any bridge", COMPOSE,
     "LOOPBACK_EDGE_OPTS = (\"--opt\", \"com.docker.network.bridge.enable_ip_masquerade=false\")",
     "LOOPBACK_EDGE_OPTS = ()"),
    ("the row never measures on one machine", COMPOSE,
     "                 if plan.reach == \"loopback\" and plan.loopback_ports else ())",
     "                 if False else ())"),
    ("the probe measures a network of its own, not the unit's", COMPOSE,
     "        notes = (reach_notes(measure_reach(plan.edge_network, env=_base_env(work_root())))",
     "        notes = (reach_notes(measure_reach(\"bridge\", env=_base_env(work_root())))"),
    ("the probe container keeps its capabilities", COMPOSE,
     "        ran = _host([\"docker\", \"run\", \"--rm\", \"--network\", network, \"--cap-drop\", "
     "\"ALL\",",
     "        ran = _host([\"docker\", \"run\", \"--rm\", \"--network\", network,"),
    ("the probe's answer is read upside down", COMPOSE,
     "    return Reached(said[\"internet\"] == \"yes\", said[\"loopback\"] == \"yes\")",
     "    return Reached(said[\"internet\"] == \"no\", said[\"loopback\"] == \"yes\")"),
    ("a probe that could not run is read as nothing reached", COMPOSE,
     "        return Reached(None, None, f\"the probe on `{network}` could not run: {ran.said}\")",
     "        return Reached(False, False)"),
    ("the card claims no egress when the internet was reached", COMPOSE,
     "           f\"the way the compose stack's is.\" if r.internet else",
     "           f\"the way the compose stack's is.\" if not r.internet else"),
    ("a measurement that could not be made reads as a closed network", COMPOSE,
     "    if r.internet is None:\n", "    if False:\n"),
    ("the card never hears what the runtime measured", STEPS,
     "            notes=tuple(dict.fromkeys([*planned.notes, *result.notes])), "
     "log_dir=result.log_dir,",
     "            notes=tuple(planned.notes), log_dir=result.log_dir,"),
    ("the card stops saying who can open the port without the key", ASSEMBLE,
     "    if ports:\n        # WHAT THE LOOPBACK REACH GIVES UP",
     "    if False:\n        # WHAT THE LOOPBACK REACH GIVES UP"),

    # ── no Docker by default: the card's §7.2 sentence ──
    ("one machine with no runtime is told the general sentence", NONE,
     "    return ONE_MACHINE if own_work.declared() else REFUSAL", "    return REFUSAL"),
    ("a server with no runtime is told the one-machine sentence", NONE,
     "    return ONE_MACHINE if own_work.declared() else REFUSAL", "    return ONE_MACHINE"),
    ("with the domain still commented, the card says the domain and hides how to opt in", APP,
     "                \"why\": demand.why_not_here(default_preview_runtime(), required=False)\n",
     "                \"why\": \"\"\n"),

    # ── init's commented lines ──
    ("init opts one machine into previews instead of writing the lines commented", DEPLOY,
     "OPENFACTORY_PREVIEW_RUNTIME=none\n# OPENFACTORY_PREVIEW_RUNTIME=compose\n"
     "# OPENFACTORY_PREVIEW_REACH=loopback\n",
     "OPENFACTORY_PREVIEW_RUNTIME=compose\nOPENFACTORY_PREVIEW_REACH=loopback\n"),
    ("init's comment stops saying what a preview's containers reach", DEPLOY,
     "#   - a preview's containers can reach services listening on all interfaces of this "
     "machine,\n",
     "#   - a preview's containers are a preview's business,\n"),

    # ── doctor's four lines ──
    ("doctor says nothing about Safari", DOCTOR,
     "        out.append(Finding(\"preview_safari\", True, said))", "        pass"),
    ("doctor reads a resolver that does not answer as one that does", DOCTOR,
     "        if state.resolves:\n", "        if not state.resolves:\n"),
    ("doctor prints Safari's line for a named domain, which is DNS's business", DOCTOR,
     "    if state.domain == \"localhost\" or state.domain.endswith(\".localhost\"):\n"
     "        line = ",
     "    if True:\n        line = "),
    ("the resolver check takes any answer for this machine", DOCTOR,
     "            state.resolves = bool(found) and all(a == \"::1\" or a.startswith(\"127.\")",
     "            state.resolves = True or all(a == \"::1\" or a.startswith(\"127.\")"),
    ("doctor stops saying anyone on the machine can open a preview without the key", DOCTOR,
     "    out.append(Finding(\n        \"preview_keyless\", True,",
     "    (lambda *_: None)(Finding(\n        \"preview_keyless\", True,"),
    ("doctor says nothing of what a preview reaches on this machine", DOCTOR,
     "    out.append(Finding(\"preview_ifaces\", True, reach))", "    pass"),
    ("doctor ignores the loopback it measured", DOCTOR,
     "    if state.loopback:\n", "    if False:\n"),
    ("doctor says nothing about egress", DOCTOR,
     "    out.append(Finding(\"preview_egress\", True, egress))", "    pass"),
    ("doctor reads a reached internet as a closed one", DOCTOR,
     "    if state.internet:\n", "    if state.internet is False:\n"),
    ("doctor never measures on one machine", DOCTOR,
     "        if kind == \"compose\" and pv.reach() == pv.LOOPBACK:\n            _one_machine(state)",
     "        if False:\n            _one_machine(state)"),
    ("doctor measures on a runtime that is not ready", DOCTOR,
     "        if state.prerequisites:\n            state.unmeasured = ",
     "        if False:\n            state.unmeasured = "),
]
