"""#176/#177: the CI is re-read and compared, and every environment runner is seen through."""

TEST = "tests/test_the_ci_is_read_more_than_once.py"
DOC = "openfactory/doctor.py"
INFER = "openfactory/onboarding/infer.py"

MUTATIONS = [
    # ── the comparison ───────────────────────────────────────────────────────────────────────────
    ("an undeclared check stops being reported", DOC,
     "    missing = [(key, cmd, where) for key, (cmd, where) in sorted(found.items())\n"
     "               if not any(_same_command(cmd, d) for d in declared_commands)]",
     "    missing = []"),

    ("…and the finding stops saying where to look", DOC,
     '        listed = "; ".join(key if where in key else f"{key} ({where})"\n'
     "                           for key, _cmd, where in missing[:4])",
     '        listed = "; ".join(key.split(" (")[0] for key, _cmd, _w in missing[:4])'),

    ("a validation nothing runs any more is never named", DOC,
     "    retired = sorted(\n        name for name, cmd in declared.items()",
     "    retired = sorted(\n        name for name, cmd in ()"),

    ("a narrower declared spelling reads as a difference", DOC,
     "    return left in right or right in left", "    return left == right"),

    ("an unreadable CI reads as a CI that agrees", DOC,
     '    found = p.ci_checks() if p.ci_checks else None\n    if found is None:',
     "    found = p.ci_checks() if p.ci_checks else None\n    if found is None:\n"
     '        return Finding("ci_declared", True, "every check this project\'s CI runs is '
     'declared")\n    if False:'),

    ("the comparison reads the PROPOSAL instead of what the pipelines run", DOC,
     "        for candidate in proposal.ci_commands:",
     "        for candidate in [c for f in proposal.fields.values() "
     "for c in (f.candidates or [])]:"),

    ("deploy plumbing is compared as though it were a check", DOC,
     "            if evidence.path not in with_roles or candidate.why == \"setup\":",
     "            if False:"),

    # ── the runner prefixes (#177) ───────────────────────────────────────────────────────────────
    ("every environment runner goes blind again", INFER,
     "    for candidate in (command, _RUNNER.sub(\"\", command or \"\", count=1)):",
     "    for candidate in (command,):"),

    ("…and the stripping leaks into the VALUE", INFER,
     "            role = classify(command)\n            if not role and slug_for(named):",
     '            role = classify(command)\n            command = _RUNNER.sub("", command, count=1)'
     "\n            if not role and slug_for(named):"),

    ("a launcher that is NOT transparent is stripped too", INFER,
     r'    r"|^dotnet\s+tool\s+run\s+"',
     '    r"|^dotnet\\s+tool\\s+run\\s+"\n    r"|^docker\\s+compose\\s+run\\s+\\S+\\s+"'),

    ("`uv python install` is a validation again", INFER,
     r'    (r"^(?:python[0-9.]*\s+-m\s+)?uv\s+(?:pip\s+install|sync|python\s+install)'
     r'\b", "setup"),',
     r'    (r"^(?:python[0-9.]*\s+-m\s+)?uv\s+(?:pip\s+install|sync)\b", "setup"),'),

    # ── which files carry checks ─────────────────────────────────────────────────────────────────
    ("every pipeline counts as a check file, deploys included", INFER,
     "    with_checks = sorted({cmd.evidence.path for cmd in commands\n"
     "                          if cmd.source in _CI_SOURCES and cmd.role in _CHECK_ROLES})",
     "    with_checks = sorted({cmd.evidence.path for cmd in commands\n"
     "                          if cmd.source in _CI_SOURCES})"),

    ("…and the role set is written in the manifest's spelling instead of the table's", INFER,
     '    _CHECK_ROLES = {"test", "lint", "security", "type"}',
     '    _CHECK_ROLES = {"test", "lint", "security", "types"}'),

    ("the verbatim reading collapses to one command per role", INFER,
     "        key = (cmd.command, cmd.evidence.path)",
     "        key = (cmd.role, cmd.evidence.path)"),
]
