"""A store that cannot be read authorizes nobody, and says so by name — the FILE half of #211's
question, and the ENTRIES of either store. Every cut below either authorizes somebody it should
not, loses a sentence somebody needs, prints hash material, or replaces a file it could not read.
"""

TEST = "tests/test_a_store_that_cannot_be_read_authorizes_nobody_and_says_so.py"
APPROVALS = "openfactory/approvals.py"
CLI = "openfactory/cli.py"
CATALOG = "openfactory/actions/catalog.py"

MUTATIONS = [
    # ── the file answers the way the variable does ───────────────────────────────────────────────
    ("a file that is not JSON raises out of `source()` again, as it did before", APPROVALS,
     "    text, problem = _file_text(path)\n    if problem:",
     "    text, problem = path.read_text(), ''\n    if problem:"),

    ("an unreadable file yields whoever can still be parsed out of it", APPROVALS,
     '        return {"logins": {}, "problem": f"{what} is not JSON ({exc.msg}, line {exc.lineno} "',
     '        return {"logins": json.loads(text + "}"), "problem": f"{what} is not JSON '
     '({exc.msg}, line {exc.lineno} "'),

    ("a file nobody may open is called an empty store", APPROVALS,
     '    except OSError as exc:\n        return "", f"it cannot be opened ({exc.strerror or '
     'type(exc).__name__})"',
     '    except OSError as exc:\n        return "{}", ""'),

    ("`path.exists()` decides, so a file in a directory this user may not enter reads as empty",
     APPROVALS,
     '    try:\n        text = path.read_text(encoding="utf-8")\n    except FileNotFoundError:',
     '    if not path.exists():\n        return "{}", ""\n'
     '    try:\n        text = path.read_text(encoding="utf-8")\n    except FileNotFoundError:'),

    ("a file cut short to nothing is 'Expecting value' instead of what a person can act on",
     APPROVALS,
     '    if not text.strip():',
     '    if False:'),

    # NOT "stops naming the file": `how_to_repair` names it twice more, so that cut changed the
    # wording and no claim — a mis-aimed cut, re-aimed here at the half nothing else carries.
    ("the file's refusal stops saying what is wrong with the file", APPROVALS,
     '            return (f"the approver file store, {self.path}, cannot be read — {self.problem} '
     '— so "',
     '            return (f"the approver file store, {self.path}, cannot be read — so "'),

    ("the file's refusal stops naming a remedy", APPROVALS,
     '                    f"nobody. {self.how_to_repair}")',
     '                    f"nobody.")'),

    ("the remedy for a broken file is to let a verb overwrite it", APPROVALS,
     '                f"restore it from a copy; to start the store over, move it aside "\n'
     '                f"(`mv {self.path} {self.path}.broken`) and add each approver again with "',
     '                f"restore it from a copy; or just run "'),

    # ── the entries ──────────────────────────────────────────────────────────────────────────────
    ("a value that is not a string is handed to the compare again", APPROVALS,
     "    if not isinstance(stored, str):\n        return f\"a JSON",
     "    if False:\n        return f\"a JSON"),

    ("a `scrypt$` string cut after its salt is called a hash", APPROVALS,
     "        if _DIGEST.fullmatch(hash_hex):\n            return \"\"",
     "        return \"\"\n        if _DIGEST.fullmatch(hash_hex):\n            return \"\""),

    ("a salt that is not hex is called a hash, and raises in `fromhex` as it did", APPROVALS,
     "        try:\n            bytes.fromhex(salt_hex)\n        except ValueError:\n"
     "            hash_hex = \"\"\n",
     ""),

    ("any string at all is taken for a legacy digest", APPROVALS,
     "    if _DIGEST.fullmatch(stored):\n        return \"\"",
     "    if True:\n        return \"\""),

    ("a real hash is called malformed, so nobody can approve anywhere", APPROVALS,
     "    if _DIGEST.fullmatch(hash_hex):\n            return \"\"",
     "    if False:\n            return \"\""),

    ("the compare raises on what is not a hash instead of refusing it", APPROVALS,
     "    if _not_a_hash(stored):\n        return False\n",
     ""),

    ("a malformed entry is counted among the logins a password can match", APPROVALS,
     '    return {"logins": {k: v for k, v in data.items() if k not in malformed},',
     '    return {"logins": data,'),

    ("the malformed entries are not carried, so nobody can be told which", APPROVALS,
     '            "malformed": malformed, "entries": data}',
     '            "malformed": {}, "entries": data}'),

    ("the sentence for a malformed entry repeats its value, where a hash lives", APPROVALS,
     '        return "; ".join(f"`{_sayable(login)}` is {what}"\n'
     '                         for login, what in sorted(self.malformed.items()))',
     '        return "; ".join(f"`{login}` is {self.entries[login]!r}"\n'
     '                         for login, what in sorted(self.malformed.items()))'),

    ("a login that is itself a hash is printed", APPROVALS,
     '    return login if _not_a_hash(login) else "<a login that is itself a hash>"',
     "    return login"),

    ("the answer prints its hashes when a sentence interpolates it", APPROVALS,
     "    logins: dict[str, str] = field(repr=False)",
     "    logins: dict[str, str] = field(repr=True)"),

    ("the person whose entry is malformed is told nothing that names it", APPROVALS,
     "        what = self.malformed.get(login)\n        if not what:\n            return \"\"",
     "        what = self.malformed.get(login)\n        if True:\n            return \"\""),

    # ── the writers ──────────────────────────────────────────────────────────────────────────────
    ("a write replaces a file it could not read", APPROVALS,
     "    if src.problem:\n        # REFUSED, NOT BACKED UP AND REPLACED.",
     "    if False:\n        # REFUSED, NOT BACKED UP AND REPLACED."),

    ("adding a login drops every malformed entry beside it", APPROVALS,
     "    store = {**src.entries, login: hash_password(password)}",
     "    store = {**src.logins, login: hash_password(password)}"),

    ("a malformed entry cannot be removed, because the verb cannot see it", APPROVALS,
     "    if login not in src.entries:  # a malformed entry IS there",
     "    if login not in src.logins:  # a malformed entry IS there"),

    ("removing one login drops every malformed entry beside it", APPROVALS,
     "    store = {k: v for k, v in src.entries.items() if k != login}",
     "    store = {k: v for k, v in src.logins.items() if k != login}"),

    # ── the verbs ────────────────────────────────────────────────────────────────────────────────
    ("`approver add` asks for the password before it reads the file", CLI,
     "    if src.problem:\n        # THE FILE CANNOT BE READ, SO IT IS NOT REPLACED",
     "    pw = typer.prompt(f\"password for {login}\", hide_input=True)\n"
     "    if src.problem:\n        # THE FILE CANNOT BE READ, SO IT IS NOT REPLACED"),

    ("`approver add` exits 0 over a file it refused to write", CLI,
     "                   f\"{src.how_to_repair}\")\n        raise typer.Exit(2)\n"
     "    pw = typer.prompt",
     "                   f\"{src.how_to_repair}\")\n        raise typer.Exit(0)\n"
     "    pw = typer.prompt"),

    ("`approver remove` rewrites a file it could not read", CLI,
     "    if src.problem:\n        # a file that cannot be read cannot be said to hold the login",
     "    if False:\n        # a file that cannot be read cannot be said to hold the login"),

    ("`approver list` prints a malformed entry among the approvers", CLI,
     "    for x in sorted(src.logins):\n        typer.echo(x)",
     "    for x in sorted({**src.logins, **src.malformed}):\n        typer.echo(x)"),

    ("`approver list` says nothing about the entries that cannot be used", CLI,
     "    if src.unusable:\n        # AN ENTRY THAT IS NOT A HASH",
     "    if False:\n        # AN ENTRY THAT IS NOT A HASH"),

    ("a store where nobody at all can approve lists as a roster and exits 0", CLI,
     "    if src.malformed and not src.logins:",
     "    if False:"),

    ("the entries that cannot be used are printed among the logins, on stdout", CLI,
     '        typer.echo(f"✗ {src.unusable}", err=True)\n\n\n@approver_app.command("remove")',
     '        typer.echo(f"✗ {src.unusable}")\n\n\n@approver_app.command("remove")'),

    ("a login the variable names only by a malformed entry is called unknown", CLI,
     "        if login in src.entries:  # named, even by an entry no password can match",
     "        if login in src.logins:  # named, even by an entry no password can match"),

    # ── the release gate ─────────────────────────────────────────────────────────────────────────
    ("the gate answers a malformed entry with 'bad password', for ever", CATALOG,
     "    entry = approvals.source().why_no_password_works_for(approver)",
     '    entry = ""'),

    ("the gate names the approver's malformed entry to everybody but her", CATALOG,
     'return refused(UNAVAILABLE, f"approval store not usable for this login — {entry} "',
     'return refused(UNAVAILABLE, f"approval store not usable for this login — "'),

    ("the gate's log line for a malformed entry is gone, so the operator hears nothing", CATALOG,
     '        log.error("OPENFACTORY_APPROVER_ENTRY_MALFORMED: prod approval refused — %s", entry)\n',
     ""),

    ("a file the gate cannot read is called a secret nobody provisioned", CATALOG,
     "    if src.malformed or (src.problem and not src.variable):",
     "    if False:"),

    ("the gate's refusal loses the reason the store cannot be used", CATALOG,
     '        why = (f"the file store {src.path} cannot be read: {src.problem}" if src.problem else\n'
     '               f"no entry in {src.where} is a hash: {src.malformed_named}")',
     '        why = "it is not usable"'),

    ("a typo of a password whose entry IS a hash becomes a 503", CATALOG,
     "    if approvals.list_approvers():\n        return refused(DENIED,",
     "    if False:\n        return refused(DENIED,"),

    ("the synchronous release path asks the gate about nobody", CATALOG,
     "    if not verify_approver(approver, password, manifest.prod_approvers):\n"
     "        return _approval_denied(approver)",
     "    if not verify_approver(approver, password, manifest.prod_approvers):\n"
     "        return _approval_denied()"),
]
