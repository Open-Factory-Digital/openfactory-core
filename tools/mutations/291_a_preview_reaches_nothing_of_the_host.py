"""#291, proven by breaking it — a preview reaches nothing of the machine it runs on.

Each row takes away one piece of what closes a unit's networks off from the host, or of what reads
back that they were; every row must turn `tests/test_a_preview_reaches_nothing_of_the_host.py` red.
The real-engine case in that file is the one that measures it, where a daemon is present.
"""

TEST = "tests/test_a_preview_reaches_nothing_of_the_host.py"

ASSEMBLE = "openfactory/preview/assemble.py"
BASE = "openfactory/adapters/preview/base.py"
COMPOSE = "openfactory/adapters/preview/compose.py"

MUTATIONS = [
    # ── what the networks are made as ──
    ("the unit's default network keeps its gateway on the host", ASSEMBLE,
     '    networks: dict = {"default": {"internal": True,\n'
     '                                  "driver_opts": dict(preview.ISOLATED_GATEWAY)}}\n',
     '    networks: dict = {"default": {"internal": True}}\n'),
    ("admission lets a default network with a gateway through", BASE,
     "            elif (spec.get(\"driver_opts\") or {}) != preview.ISOLATED_GATEWAY:\n",
     "            elif False:\n"),
    ("the edge is made internal and nothing more — the gateway the issue measured", COMPOSE,
     'NETWORK_EDGE_OPTS = ("--internal", *(o for key, value in preview.ISOLATED_GATEWAY.items()\n'
     '                                     for o in ("--opt", f"{key}={value}")))\n',
     'NETWORK_EDGE_OPTS = ("--internal",)\n'),
    # ── what is read back ──
    ("the engine is not asked first, so an engine that ignores the option starts the services",
     COMPOSE,
     "        problem = isolation_unhonoured(env)\n        if problem:\n"
     "            return failed(problem)\n",
     ""),
    ("an edge that already existed is trusted to be what this runtime would have made", COMPOSE,
     "        if plan.reach == \"network\":\n            problem = gateway_on_the_host(edge, env)\n"
     "            if problem:\n                return problem\n",
     ""),
    ("the default network `up` made is trusted, not read back", COMPOSE,
     "        problem = gateway_on_the_host(f\"{plan.compose_project}_default\", env)\n"
     "        if problem:\n",
     "        problem = \"\"\n        if problem:\n"),
    ("a default network with a gateway is said, and its services left running", COMPOSE,
     "            self.down(plan.compose_project, plan.workdir)\n            return failed(problem)\n",
     "            return failed(problem)\n"),
    ("a gateway in what the engine answers is not seen", COMPOSE,
     "    if gateways:\n        return (f\"the network `{network}` has an address on this machine",
     "    if False:\n        return (f\"the network `{network}` has an address on this machine"),
    ("the engine's refusal of the option is taken as a yes", COMPOSE,
     "    if made.rc:\n        return (f\"this Docker engine cannot make an internal network",
     "    if False:\n        return (f\"this Docker engine cannot make an internal network"),
    ("the network made to ask the engine is left behind", COMPOSE,
     "        _host([\"docker\", \"network\", \"rm\", probe], env=env, timeout=60)\n",
     "        pass\n"),
]
