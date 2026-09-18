"""#138: a removal that removed nothing does not say `removed` — the store answers, the verb reads."""

TEST = "tests/test_a_name_nobody_registered_is_not_removed.py"
REGISTRY = "openfactory/registry.py"
APPROVALS = "openfactory/approvals.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    # ── the project registry ─────────────────────────────────────────────────────────────────────
    ("the registry swallows a name it does not hold again", REGISTRY,
     "            if name not in raw:\n                raise KeyError(name)\n            del raw[name]",
     "            raw.pop(name, None)"),

    ("the verb announces a removal whatever the registry said", CLI,
     "    try:\n        reg.remove(name)\n    except KeyError:",
     "    try:\n        try:\n            reg.remove(name)\n        except KeyError:\n"
     "            pass\n    except KeyError:"),

    ("the refusal exits 0, so a script still reads it as success", CLI,
     '                   f"Registered here: {_registered_here(reg, refusing=name)}.")\n'
     "        raise typer.Exit(2) from None\n    typer.echo(f\"removed {name!r}\")",
     '                   f"Registered here: {_registered_here(reg, refusing=name)}.")\n'
     "        raise typer.Exit(0) from None\n    typer.echo(f\"removed {name!r}\")"),

    ("the refusal loses its roster — the name that was meant is not on it", CLI,
     '    return ", ".join(names) if names else "none yet"',
     '    return "none yet"'),

    # ── the approver store, the same shape one table over ────────────────────────────────────────
    ("the approver store says it removed somebody it never held", APPROVALS,
     "    if login not in store:\n        return False\n    del store[login]",
     "    store.pop(login, None)"),

    ("the approver verb stops reading the store's answer", CLI,
     "    if not was_there:\n        listed =",
     "    if False:\n        listed ="),

    ("a login the environment still names is called removed", CLI,
     "    if login in still:\n        # `OPENFACTORY_APPROVERS` wins",
     "    if False:\n        # `OPENFACTORY_APPROVERS` wins"),
]
