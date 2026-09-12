"""#115: a scripted `init` is refused ONCE, naming every answer it still owes.

The reverses are where this can go wrong quietly: a list that repeats what was just passed is a
list nobody reads twice, a conditional question listed unconditionally sends a reader to answer
something that does not apply, and a list claiming to be complete would be the confident-wrong-
name defect this repository keeps finding — the questions branch, so it cannot be.
"""

TEST = "tests/test_init_generates_the_deployment.py"
SRC = "openfactory/cli.py"

MUTATIONS = [
    ("the first unanswered question refuses again, one attempt per question", SRC,
     '            missing.append((f"--{flag}", f"one of: {\', \'.join(entry.options)}"))\n'
     '            return chosen_default or (entry.options[0] if entry.options else "")',
     '            typer.echo(f"✗ --{flag} is required")\n'
     '            raise typer.Exit(2)'),

    ("the panel pair leaves the shared list and refuses on its own again", SRC,
     '            missing.append(("--panel-exposed / --panel-local",\n'
     '                            "an unstated answer would leave the panel OPEN to anyone who can "\n'
     '                            "reach the port"))\n'
     '            answers.panel_exposed = False',
     '            typer.echo("✗ --panel-exposed or --panel-local is required — OPEN")\n'
     '            raise typer.Exit(2)'),

    ("nothing refuses at the end, so a scripted run proceeds on defaults nobody chose", SRC,
     "    if missing:\n"
     '        typer.echo("✗ this does not run in a terminal, so every answer must be passed as a flag:")',
     "    if False:\n"
     '        typer.echo("✗ this does not run in a terminal, so every answer must be passed as a flag:")'),

    ("…and the reverse: the list stops narrowing and repeats what was already passed", SRC,
     "        if value is not None:\n            return value\n        if not interactive:",
     "        if value is not None and False:\n            return value\n        if not interactive:"),

    ("a conditional question is listed even where its answer is discarded", SRC,
     '    if answers.harness == "claude_code" and answers.runtime != "local":',
     "    if True:"),

    ("the refusal claims a complete list instead of stating its bound", SRC,
     '        typer.echo("  Some questions depend on earlier answers, so passing these may reveal one "\n'
     '                   "more.\\n  Nothing was written.")',
     '        typer.echo("  Nothing was written.")'),
]
