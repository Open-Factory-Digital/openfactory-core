"""ADR-0049 D9 (follow-up), proven by breaking it — the first hour on one machine, walked.

THREE CLAIMS, each found by running the thing rather than reading it:

  1. **`poll` asks the gate `scan_todo` asks.** It is the only scheduler this runtime has, and it
     walked past the proof that had just been made gateable.
  2. **The proof accepts the login where the box runs no image**, and still demands the variable
     where the box isolates.
  3. **`init` names the store the panel reads**, so what the factory says is there to be read.

The guard under test is `tests/test_the_one_machine_deployment_runs_unattended.py`.
"""

TEST = "tests/test_the_one_machine_deployment_runs_unattended.py"

CLI = "openfactory/cli.py"
PROVE = "openfactory/box_prove.py"
DEP = "openfactory/onboarding/deployment.py"

MUTATIONS = [
    ("the scheduler walks past the gate again, and a card runs on an unproven box", CLI,
     "    if held := gate_reason(project, sandbox=box):\n"
     "        typer.echo(f\"{name}: pickup is held — {held}\")\n        return",
     "    if False:\n"
     "        typer.echo(f\"{name}: pickup is held — {held}\")\n        return", TEST),

    ("it holds but says nothing about why, so the person is left with a queue that does not move",
     CLI,
     '        typer.echo(f"{name}: pickup is held — {held}")', '        typer.echo("")', TEST),

    ("the proof refuses a box whose harness signs in with this machine's login", PROVE,
     "    elif missing and not p.honours_image:", "    elif False:", TEST),

    ("a box that ISOLATES is let through without a credential, which is the opposite defect",
     PROVE, "    elif missing and not p.honours_image:", "    elif missing:", TEST),

    ("the file names no store, so everything the factory says is dropped again", DEP,
     "OPENFACTORY_METRICS_SINK=sqlite\nOPENFACTORY_METRICS_DB={home}/.openfactory/metrics.db\n",
     "", TEST),

    ("the store is named but has nowhere to write", DEP,
     "OPENFACTORY_METRICS_DB={home}/.openfactory/metrics.db", "OPENFACTORY_METRICS_DB=", TEST),
]
