"""`openfactory init` refuses over the file THIS RUN will write, proven by breaking it.

Found by running the first command of a demonstration (2026-09-11): in a directory holding a
`.env.compose`, `init` refused before asking where the factory runs — about a file the answer
would not have touched.

FOUR CLAIMS:

  1. **The destination follows the answer** — `local` writes the host file, not the stack's.
  2. **The refusal is asked of the real destination**, after that answer, and not before it.
  3. **The rule itself did not loosen**: the file the run would write is still refused, and
     `--force` is still the only way past it.
  4. **The message names the file at risk**, which is the one somebody has to decide about.

The guard under test is `tests/test_the_refusal_reads_the_file_it_would_write.py`.
"""

TEST = "tests/test_the_refusal_reads_the_file_it_would_write.py"

CLI = "openfactory/cli.py"

MUTATIONS = [
    # ── 1. the destination follows the answer ──────────────────────────────────────────────────
    ("the default destination stops following the answer, so `local` writes the stack's file",
     CLI,
     '    if answers.runtime == "local" and out == _COMPOSE_ENV:',
     "    if False:", TEST),

    # ── 2. the moment the question is asked ────────────────────────────────────────────────────
    ("the refusal moves back before the first question, over the file the answer would not touch",
     CLI,
     "    dest = Path(out).expanduser()\n\n    def _refuse_to_overwrite(where: Path) -> None:",
     "    dest = Path(out).expanduser()\n"
     "    if dest.exists() and not force:\n"
     '        typer.echo(f"✗ {dest} already exists — re-run with --force to overwrite it")\n'
     "        raise typer.Exit(2)\n\n    def _refuse_to_overwrite(where: Path) -> None:", TEST),

    ("the refusal is never asked at all, and a hand-pasted file is silently rewritten", CLI,
     "    # NOW the destination is known, and it is the one this run will write.\n"
     "    _refuse_to_overwrite(dest)",
     "    # NOW the destination is known, and it is the one this run will write.\n"
     "    pass", TEST),

    # ── 3. the rule did not loosen ─────────────────────────────────────────────────────────────
    ("an existing file is overwritten without being asked about", CLI,
     "        if where.exists() and not force:", "        if False:", TEST),

    ("--force stops being the way past it, so the refusal can never be cleared", CLI,
     "        if where.exists() and not force:", "        if where.exists():", TEST),

    # ── 4. the message names the file at risk ──────────────────────────────────────────────────
    ("the refusal names the default rather than the file it is about", CLI,
     '            typer.echo(f"✗ {where} already exists — re-run with --force to overwrite it "',
     '            typer.echo(f"✗ a file already exists — re-run with --force to overwrite it "',
     TEST),
]
