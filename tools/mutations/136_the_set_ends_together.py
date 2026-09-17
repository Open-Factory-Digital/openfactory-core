"""#136, proven by breaking it — the processes `openfactory up` starts end together.

MEASURED on this machine with the real engine, worker and panel, before the change: a SIGTERM or a
SIGKILL to the supervisor left all three running, and the panel on its port; only Ctrl-C ran the
`finally` that stops the set, and a child still running after its wait was left there. After it,
both signals take all three down within five seconds and free both ports.

FOUR CLAIMS:

  1. **SIGTERM and SIGHUP stop the set** the way Ctrl-C does.
  2. **A supervisor killed outright still takes its children with it**, through a reaper that
     notices its parent is gone — and that reaper does not outlive an orderly stop.
  3. **A child that ignores the request to stop is made to.**
  4. **The panel does not wait forever for an open stream** before it exits.

The guard is `tests/test_the_set_ends_together.py`, which drives `host.run` in a real process with
real children.
"""

TEST = "tests/test_the_set_ends_together.py"

HOST = "openfactory/runtime/host.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    ("THE DEFECT ITSELF: only Ctrl-C stops the set, so `kill` and a closed terminal orphan it",
     HOST,
     '    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):\n',
     "    for sig in ():\n"),

    ("no reaper is started, so a supervisor killed with SIGKILL orphans every child", HOST,
     "        reaper = _start_reaper(started, grace=grace, say=say)\n",
     "        reaper = None\n"),

    ("the reaper never waits for its parent and stops nothing when it dies", HOST,
     "    while os.getppid() == supervisor:\n        time.sleep(every)\n",
     "    return\n"),

    ("a child that ignores SIGTERM is left running once its wait gives up", HOST,
     "        if child.poll() is None:\n            with contextlib.suppress(Exception):\n"
     "                child.kill()",
     "        if False:\n            with contextlib.suppress(Exception):\n"
     "                child.kill()"),

    ("the reaper is left running after an orderly stop, holding pids that are no longer ours",
     HOST,
     "                reaper.kill()\n",
     "                pass\n"),

    ("the panel waits for every open stream before it exits, so a SIGTERM never ends it", CLI,
     '    uvicorn.run("openfactory.api.app:app", host=host, port=port, '
     'timeout_graceful_shutdown=5)',
     '    uvicorn.run("openfactory.api.app:app", host=host, port=port)'),
]
