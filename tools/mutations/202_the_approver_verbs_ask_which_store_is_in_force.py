"""#202: the approver verbs ask which store the deployment reads — one question, asked by everybody."""

TEST = "tests/test_the_approver_verbs_ask_which_store_is_in_force.py"
APPROVALS = "openfactory/approvals.py"
CLI = "openfactory/cli.py"
CATALOG = "openfactory/actions/catalog.py"

MUTATIONS = [
    # ── the question ─────────────────────────────────────────────────────────────────────────────
    ("the variable stops being in force: the file answers even while it is set", APPROVALS,
     "    if not raw:\n        return ApproverSource(variable=False",
     "    if True:\n        return ApproverSource(variable=False"),

    ("a variable holding only blanks counts as set", APPROVALS,
     '    raw = os.environ.get(VARIABLE, "").strip()',
     '    raw = os.environ.get(VARIABLE, "")'),

    ("a variable that is not JSON yields nobody and says nothing about why", APPROVALS,
     'problem=f"its value is not JSON ({exc.msg}, character {exc.pos})")',
     'problem="")'),

    ("the reason repeats the value, which is where the hashes live", APPROVALS,
     'problem=f"its value is not JSON ({exc.msg}, character {exc.pos})")',
     'problem=f"its value is not JSON: {raw}")'),

    ("a JSON array is taken for a roster", APPROVALS,
     "    if not isinstance(data, dict):",
     "    if False:"),

    ("the two unreadable shapes read the same", APPROVALS,
     "{_JSON_NAMES.get(type(data), 'value')}",
     "value"),

    ("the readers stop asking the question: `_load` reads the file whatever is in force", APPROVALS,
     "    return source().logins",
     "    path = _store_path()\n    return json.loads(path.read_text()) if path.exists() else {}"),

    # ── the writers ──────────────────────────────────────────────────────────────────────────────
    ("the store writes a file the deployment does not read", APPROVALS,
     "    if src.variable:\n        raise NotTheStoreInForce(",
     "    if False:\n        raise NotTheStoreInForce("),

    # ── the sentences ────────────────────────────────────────────────────────────────────────────
    ("the remedy sends a person to the verb that refuses them", APPROVALS,
     "        if not self.variable:\n            return f\"Run `openfactory approver add",
     "        if True:\n            return f\"Run `openfactory approver add"),

    ("over a variable nothing can parse, the remedy is still 'add the login to it'", APPROVALS,
     "        if self.problem:\n            return self.unreadable\n",
     ""),

    ("the refusal stops naming the file it left alone", APPROVALS,
     'f"store ({self.path}) on every read, so the file was left as it was.")',
     'f"store on every read, so the file was left as it was.")'),

    ("the listing names the variable whichever store answered", APPROVALS,
     "        if self.variable:\n            return (f\"`{VARIABLE}` (the variable wins",
     "        if True:\n            return (f\"`{VARIABLE}` (the variable wins"),

    ("the listing names the file whichever store answered", APPROVALS,
     "        if self.variable:\n            return (f\"`{VARIABLE}` (the variable wins",
     "        if False:\n            return (f\"`{VARIABLE}` (the variable wins"),

    # ── approver add ─────────────────────────────────────────────────────────────────────────────
    ("approver add stops asking which store is in force", CLI,
     "    if src.variable:\n        typer.echo(f\"✗ {login!r} was not saved",
     "    if False:\n        typer.echo(f\"✗ {login!r} was not saved"),

    ("the refusal exits 0, so a script reads it as saved", CLI,
     "                   f\"{src.how_to_add(login)}\")\n        raise typer.Exit(2)",
     "                   f\"{src.how_to_add(login)}\")\n        raise typer.Exit(0)"),

    ("the password is asked for before the store is", CLI,
     "    src = approvals.source()\n    if src.variable:\n        typer.echo(f\"✗ {login!r} was not",
     "    typer.prompt(f\"password for {login}\", hide_input=True)\n"
     "    src = approvals.source()\n    if src.variable:\n        typer.echo(f\"✗ {login!r} was not"),

    # ── approver list ────────────────────────────────────────────────────────────────────────────
    ("the listing stops saying what it is reading", CLI,
     '    typer.echo(f"approvers from {src.named}:" if src.logins else',
     '    typer.echo("approvers:" if src.logins else'),

    ("the source is printed among the logins, on stdout", CLI,
     '               f"no approvers yet in {src.named}. {src.how_to_add()}", err=True)',
     '               f"no approvers yet in {src.named}. {src.how_to_add()}")'),

    ("an unreadable variable lists as an empty roster and exits 0", CLI,
     "    if src.problem:\n        # not an empty roster with exit 0",
     "    if False:\n        # not an empty roster with exit 0"),

    ("an empty store stops saying how the first approver is added", CLI,
     '               f"no approvers yet in {src.named}. {src.how_to_add()}", err=True)',
     '               f"no approvers yet in {src.named}.", err=True)'),

    # ── approver remove ──────────────────────────────────────────────────────────────────────────
    ("a login the variable does not name is refused without the variable's roster", CLI,
     '            roster = src.unreadable or f"The variable names: {listed}."',
     '            roster = ""'),

    # ── the release gate ─────────────────────────────────────────────────────────────────────────
    ("the gate calls a secret it cannot read 'not provisioned'", CATALOG,
     "    if src.variable:\n        # THE SECRET IS THERE AND YIELDS NOBODY",
     "    if False:\n        # THE SECRET IS THERE AND YIELDS NOBODY"),

    ("the gate's refusal loses the reason the secret cannot be read", CATALOG,
     '        why = src.problem or "names nobody"',
     '        why = "names nobody"'),
]
