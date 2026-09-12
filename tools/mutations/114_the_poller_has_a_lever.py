"""#114: the poller can be held, and the hold says what it does NOT do.

The reverses are the dangerous half here. A pause that reports "drained" interrupts the very work
it was pulled to protect; a warning printed when nothing is running trains the reader to ignore
it; and an unreadable schedule flattened to ON is the same lie `view.intake` refuses one layer
down.
"""

TEST = "tests/test_the_poller_has_a_lever.py"
CLI = "openfactory/cli.py"
SCHED = "openfactory/runtime/temporal/schedule.py"

MUTATIONS = [
    ("pausing what is already paused acts anyway, and overwrites the note explaining the hold",
     SCHED,
     '    if was_on == on:\n        return {"changed": False, "was_on": was_on, "note": str(desc.schedule.state.note or "")}\n',
     ""),

    ("the no-op reports the new note instead of the one that explains the hold", SCHED,
     '        return {"changed": False, "was_on": was_on, "note": str(desc.schedule.state.note or "")}',
     '        return {"changed": False, "was_on": was_on, "note": note}'),

    ("pause and resume are swapped", SCHED,
     "    if on:\n        await handle.unpause(note=note)\n    else:\n        await handle.pause(note=note)",
     "    if on:\n        await handle.pause(note=note)\n    else:\n        await handle.unpause(note=note)"),

    ("a pause stops saying that a running job is still running", CLI,
     '        typer.echo("  the pause holds NEW pickups only — these are already running. Wait for "\n'
     '                   "them before rolling the deployment.")',
     "        pass"),

    ("…and the reverse: the warning is printed when nothing is running", CLI,
     '    running = _in_flight(jobs)\n    if not running:\n        typer.echo("in flight: nothing")\n        return',
     '    running = _in_flight(jobs)\n    if not running:\n        typer.echo("in flight: nothing")'),

    ("a closed job is counted as in flight", CLI,
     '    return [j for j in jobs if j.get("status") == "running"]',
     "    return list(jobs)"),

    ("a schedule that could not be read is reported as ON", CLI,
     '    if not intake.get("known"):\n'
     '        typer.echo("poller: UNKNOWN — the schedule could not be read (is the engine reachable?)")\n'
     "        return\n",
     ""),

    ("an unexplained hold stops saying what it cannot be told apart from", CLI,
     '                  "\\n  note: (none — nothing records why, so the next reader cannot tell this "\n'
     '                  "from an outage)"))',
     '                  ""))'),

    ("an unreachable engine raises instead of refusing by name", CLI,
     '        typer.echo(f"✗ could not pause the poller ({str(exc)[:200]}) — the engine may be "\n'
     '                   f"unreachable. `openfactory poller status` says whether it can be read.")\n'
     "        raise typer.Exit(2) from None",
     "        raise"),

    ("the note stops naming who pulled the lever", CLI,
     '    reason = note or f"paused by {getpass.getuser()} via `openfactory poller pause`"',
     '    reason = note or ""'),
]
