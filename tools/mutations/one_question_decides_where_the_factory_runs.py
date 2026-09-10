"""ADR-0049 slice 8, proven by breaking it — one question decides where the factory runs.

FOUR CLAIMS:

  1. **The runtime is asked first**, and its vocabulary is read live rather than written here.
  2. **`local` asks for no credential** and switches on the four things D9 names — in absolute
     paths, because an env file is read by processes and not by a shell.
  3. **The declaration is the boundary's stand-in, and only where somebody made it.** `compose`
     never writes it; a deployment that has not said it is refused by name; and it does not
     invent a box the registry has never heard of.
  4. **`openfactory up` starts the worker only where there is an engine**, and the doctor says
     which of the processes answer — asked only where they are this operator's to start.

The guard under test is `tests/test_one_question_decides_where_the_factory_runs.py`.
"""

TEST = "tests/test_one_question_decides_where_the_factory_runs.py"

DEP = "openfactory/onboarding/deployment.py"
BOXES = "openfactory/adapters/sandbox/registry.py"
DOC = "openfactory/doctor.py"
CLI = "openfactory/cli.py"
HOST = "openfactory/runtime/host.py"
OWN = "openfactory/own_work.py"

MUTATIONS = [
    # ── 1. the question ────────────────────────────────────────────────────────────────────────
    ("the runtime question is asked after the ones it decides", DEP,
     '    Question("runtime", "Where should the FACTORY itself run — this machine, or Docker?",',
     '    Question("zzz-runtime", "Where should the FACTORY itself run — this machine, or Docker?",',
     TEST),

    ("the vocabulary is hand-written, so an installed add-on's box is not offered", DEP,
     '    hosted = tuple(k for k in plugins.known(AXIS, BOXES) if k not in ("worktree", "container"))\n'
     '    return ("local", "compose", *hosted)',
     '    return ("local", "compose")', TEST),

    ("the default sends a person to Docker before they have run anything", DEP,
     '"credentials your vendors need", _runtimes, "local"),',
     '"credentials your vendors need", _runtimes, "compose"),', TEST),

    # ── 2. what `local` renders ────────────────────────────────────────────────────────────────
    ("the local runtime renders nothing, so the file says where none of it runs", DEP,
     '    if answers.runtime == "local":\n'
     '        parts.append(_host_runtime_block(answers, p))\n', "", TEST),

    ("the declaration is left out of the file that is supposed to make it", DEP,
     "OPENFACTORY_OWN_WORK=1\n", "", TEST),

    ("the paths are written with a tilde a process cannot expand", DEP,
     '    home = p.home().rstrip("/")', '    home = "~"', TEST),

    ("the harness asks for a token variable on a runtime that has a login", DEP,
     '    if a.runtime == "local":\n'
     '        # A CHECK, NOT A PASTE.', '    if False:\n'
     '        # A CHECK, NOT A PASTE.', TEST),

    # ── 3. the declaration ─────────────────────────────────────────────────────────────────────
    ("a durable job runs in a box that bounds nothing, on a deployment that never said so",
     BOXES,
     '    if own_work.declared():\n        return ""', '    if True:\n        return ""', TEST),

    ("the refusal stops naming the way out, so the one operator it is about cannot find it",
     BOXES,
     '            f"pass --sandbox container) to bound the work. " + own_work.THE_WAY_OUT)',
     '            f"pass --sandbox container) to bound the work.")', TEST),

    ("the declaration is heard from any value at all, including the ones that mean no", OWN,
     '    return (os.environ.get(VARIABLE) or "").strip().lower() in _TRUE',
     '    return VARIABLE in os.environ', TEST),

    # ── 4. the processes ───────────────────────────────────────────────────────────────────────
    # THE CUT IS THE INDENT. Deleting the line would leave the worker unstarted, which is what
    # the guard already asks for on a machine with no engine — a mutation the test survives by
    # agreeing with it. Moving it OUT of the `if engine:` block is the defect: the worker starts
    # with nothing to connect to, exits, and takes the panel with it under the rule that one
    # dying process ends the set.
    ("the worker is started with no engine to connect to, and takes the panel down with it", HOST,
     '        plan.append(("worker", [sys.executable, "-m", "openfactory.runtime.temporal.worker"]))\n'
     '    plan.append(("panel",',
     '    plan.append(("worker", [sys.executable, "-m", "openfactory.runtime.temporal.worker"]))\n'
     '    plan.append(("panel",', TEST),

    ("the doctor asks about processes on a deployment whose stack is somebody else's", DOC,
     "        processes=_processes_probe if own_work.declared() else None,",
     "        processes=_processes_probe,", TEST),

    ("a stopped engine is reported as fine, which is what it already looks like", DOC,
     '    if panel_up and not engine_up:', '    if False:', TEST),
]
