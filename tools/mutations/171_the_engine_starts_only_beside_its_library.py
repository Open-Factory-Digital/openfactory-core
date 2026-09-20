"""#171, proven by breaking it — the durable engine starts only beside the library its worker runs on.

The one-machine install was `pip install -e .`, which leaves out the `runtime` extra, and
`openfactory up` told the same reader to put `temporal` on the PATH. Doing that started the engine,
the worker died on `ModuleNotFoundError: No module named 'temporalio'`, and one dying process ends
the set by design — so the panel went down with it.

THREE CLAIMS:

  1. **The plan leaves the durable half out** when the library is missing: no worker to die, and no
     engine with no worker, which the doctor would read as the durable half answering.
  2. **`up` names what is missing** — the library when the binary is there, both when neither is.
     (It also declined to say "the panel works" without the library, because the page imported it
     too; #178 ended that, and the row that pinned the conditional is retired below.)
  3. **The install pages install the extra.** Read from the `pip install` lines the pages run and
     from `pyproject.toml`'s extras, never from prose.

The guard is `tests/test_the_engine_starts_only_beside_the_library_its_worker_runs_on.py`.
"""

TEST = "tests/test_the_engine_starts_only_beside_the_library_its_worker_runs_on.py"

HOST = "openfactory/runtime/host.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    ("THE DEFECT ITSELF: the engine and its worker are planned whether or not the library is here",
     HOST,
     "    if engine and the_client():\n",
     "    if engine:\n"),

    ("the library is always reported present", HOST,
     '        return importlib.util.find_spec("temporalio") is not None\n',
     '        return True\n'),

    ("the binary on the PATH without its library is started as if nothing were missing", HOST,
     "    if binary:\n        return None, RUNTIME_HINT\n",
     "    if binary:\n        return binary, \"\"\n"),

    ("with neither installed, only the binary is named — the step that led into the crash", HOST,
     '    return None, TEMPORAL_HINT if client else f"{TEMPORAL_HINT} {RUNTIME_TOO}"\n',
     '    return None, TEMPORAL_HINT\n'),

    ("up hears what is missing and says nothing", CLI,
     "    if missing:\n        typer.echo(f\"! {missing}\")\n",
     "    if False:\n        typer.echo(f\"! {missing}\")\n"),

    # RETIRED 2026-09-19: "the closing line says the panel works on an install whose page cannot
    # load". The conditional it cut is gone because the condition is — since #178 the panel's page
    # loads without `temporalio`, so `up` says "the panel works" on every install. What holds that
    # is `178_the_panel_serves_without_the_engines_client.py`, which asks every GET route of the
    # panel in an interpreter where the library cannot be found.

    ("the README installs the checkout without the extra again", "README.md",
     "pip install -e '.[runtime]'                             # the durable engine's worker runs on",
     "pip install -e .                                        # the durable engine's worker runs on"),

    ("the one-machine page installs the checkout without the extra again",
     "docs/setup/one-machine.md",
     "source .venv/bin/activate\npip install -e '.[runtime]'\nopenfactory init",
     "source .venv/bin/activate\npip install -e .\nopenfactory init"),
]
