"""Mutation plan for #265 slice 1, the pure core — a preview's shape is read from the base branch,
admitted key by key, and assembled for one change (ADR-0050 D2–D4, D8).

Each row takes away one rule a preview's safety or honesty rests on; every row must turn
`tests/test_the_shape_is_read_and_admitted.py` red.
"""

TEST = "tests/test_the_shape_is_read_and_admitted.py"
READ = "openfactory/preview/read.py"
ADMIT = "openfactory/preview/admit.py"
ASSEMBLE = "openfactory/preview/assemble.py"

MUTATIONS = [
    # ── reading: the base, never the change ──
    ("the change's compose file is read instead of the base's", READ,
     '    base = layout.root(tree, "base")',
     '    base = layout.root(tree, "change")'),
    ("a compose file that is a link out of the checkout is read", READ,
     "    real = os.path.realpath(path)",
     "    real = os.path.normpath(path)"),
    ("the pre-scan lets an `include:` through to the CLI", READ,
     '        if "include" in doc:',
     "        if False:"),
    ("the compose CLI runs with the worker's whole environment", READ,
     "env=reduced_env(), timeout=120,",
     "env=dict(os.environ), timeout=120,"),
    # ── admission: a whitelist ──
    ("a key in no set passes to the runtime", ADMIT,
     '                refused.append(f"`{key}` is not a key a preview reads (service `{name}`).")',
     "                kept[key] = value"),
    ("a top-level volume keeps the name the client gave it", ADMIT,
     '            elif key == "name":\n'
     '                refused.append(f"volume `{vol}` is named `{value}`',
     '            elif key == "name":\n'
     '                kept[key] = value; str(f"volume `{vol}` is named `{value}`'),
    ("a profiled service runs anyway", ADMIT,
     "        if name in profiled or name in excluded:\n            continue",
     "        if name in excluded:\n            continue"),
    ("a dependency on an excluded service is pruned in silence", ADMIT,
     "            if dep in excluded:\n                refused.append(",
     "            if dep in excluded:\n                len("),
    # ── admission: on disk ──
    ("paths are judged as strings, so a link out of the checkout passes", ADMIT,
     '    """The root `path` lies in once every link is followed, or ""."""\n'
     "    real = os.path.realpath(path)",
     '    """The root `path` lies in once every link is followed, or ""."""\n'
     "    real = os.path.normpath(path)"),
    ("the daemon may still create a bind source nobody admitted", ADMIT,
     'if k != "create_host_path"}',
     "if True}"),
    # ── admission: names, never the process's environment ──
    ("an unlisted name keeps its reference, so the compose process's environment fills it", ADMIT,
     '            if name in allowed:\n'
     '                out.append("${" + allowed[name] + op + arg + "}")',
     '            if True:\n'
     '                out.append("${" + allowed.get(name, name) + op + arg + "}")'),
    ("`${X:?}` on a name nobody listed is not refused", ADMIT,
     '                if op in (":?", "?"):\n                    required.append(name)',
     '                if op in (":?", "?"):\n                    pass'),
    ("a build reads the run-time names", ADMIT,
     '                build = _walk(svc["build"], by(build_list))',
     '                build = _walk(svc["build"], by(run_names))'),
    # ── what is said ──
    ("an env file the repository does not have is made optional without a word", ADMIT,
     '                item["required"] = False\n                notes.append(',
     '                item["required"] = False\n                len('),
    ("every dropped and set key is dropped in silence", ADMIT,
     "notes=[*said.sentences(), *notes])",
     "notes=[*notes])"),
    # ── assembly: from the change, derived ──
    ("a service from the change still builds from base", ASSEMBLE,
     "{n: (_reroot(s, layout) if from_change.get(n) else s)",
     "{n: (s if from_change.get(n) else s)"),
    ("any path that merely starts with an input's name makes a service from the change", ASSEMBLE,
     'path.startswith(rel.rstrip("/") + "/")',
     'path.startswith(rel.rstrip("/"))'),
    ("a changed service keeps the client's image tag", ASSEMBLE,
     '        if from_change.get(name) and "build" in svc:\n            svc.pop("image", None)',
     '        if from_change.get(name) and "build" in svc:\n            pass'),
    ("an unchanged service that names an image is built from base instead of pulled", ASSEMBLE,
     '        elif not from_change.get(name) and "image" in svc:\n'
     '            svc.pop("build", None)',
     '        elif not from_change.get(name) and "image" in svc:\n            pass'),
    ("a change no service is made from is previewed as if it were in it", ASSEMBLE,
     "    elif changed and not prove and not any(from_change.values()):",
     "    elif False:"),
    # ── assembly: what the operator sets ──
    ("a build receives the run-time names too", ASSEMBLE,
     "            for container, worker in policy.names_for(name, build=True).items():",
     "            for container, worker in policy.names_for(name).items():"),
    ("a registry name reaches a container as its value", ASSEMBLE,
     '            env[container] = "${" + worker + "}"',
     '            env[container] = os.environ.get(worker, "")'),
    ("a label of the client's is kept beside the platform's", ASSEMBLE,
     '        svc["labels"] = {\n',
     '        svc["labels"] = {**(services_in[name].get("labels") or {}),\n'),
    ("a preview keeps every capability", ASSEMBLE,
     '"cap_drop": ["ALL"],',
     '"cap_drop": [],'),
    # re-pinned 2026-09-25 (#291): the default network also carries its isolated gateway, on a
    # line of its own, so the cut is at `internal`, claim unchanged
    ("the preview's own network reaches out", ASSEMBLE,
     '    networks: dict = {"default": {"internal": True,\n',
     '    networks: dict = {"default": {"internal": False,\n'),
    ("a volume is left to compose's default name", ASSEMBLE,
     '{v: {**(spec or {}), "name": f"{compose_project}_{v}"}',
     "{v: {**(spec or {})}"),
    ("the operator's service budget is not checked", ASSEMBLE,
     "    if count > policy.max_services:",
     "    if False:"),
]
