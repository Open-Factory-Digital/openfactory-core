"""The developer's guide runs, and `openfactory explain` says what the job does (#81).

The claims, and the cuts that would make each one false while everything still runs:

ROWS 1-10 ARE THE TRACE LYING ABOUT THE PROMPT. `build_context` writes it from the branch that
decided each file, and every cut here leaves the job's prompt exactly as it was while the record
of it goes wrong: a waived file left out, a replacement recorded as kept, the inlined text dropped
(so the trace's texts are no longer the context), the operator's tier filed under the framework, a
refusal recorded as a typo, a missing file not recorded, a constraint named by an absolute path, a
profile's own addition filed under the framework, a profile line that names nothing left out, and
a kept file that loses the replacement it was meant to have.

ROW 11 IS THE ROLE PROMPT'S SOURCE: the one-layer answer stops finding the shipped file.

ROWS 12-16 ARE EXPLAIN ITSELF: it resolves no profile, an address is refused as a missing
directory, the profile refusal stops saying where it looked, a Portuguese label falls back to
English, and the CLI drops `--language`.

ROWS 17-19 ARE WHAT IT PRINTS: the operator's header vanishes, `--full` prints nothing more, and
the fenced brief — the card's words, behind a random marker — is printed after all.

ROWS 20-22 ARE WHAT IT MUST NEVER DO: read the knowledge bundle (which can fetch), let a refusal
escape as a traceback, or accept a language nobody wrote.
"""

TEST = "tests/test_the_developer_guide_runs.py"

CONTEXT = "openfactory/orchestrator/context.py"
EXPLAIN = "openfactory/orchestrator/explain.py"
ROLES = "openfactory/adapters/agent/roles.py"
PROFILES = "openfactory/policy/profiles.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    # ── the trace lies about the prompt ──────────────────────────────────────────────────────────
    ("a waived framework file is skipped and not traced, so explain never shows what the class "
     "removed",
     CONTEXT,
     "            _dropped(trace, layer, p.name, WAIVED, chain)\n",
     ""),

    ("a replaced file is traced as kept, so explain says the framework's rule applied when the "
     "project's did",
     CONTEXT,
     "                                 fate=REPLACED, detail=substitute))",
     "                                 detail=substitute))"),

    ("the trace stops carrying what was inlined, so its texts are no longer the context",
     CONTEXT,
     "        trace.append(Traced(layer, name, fate, detail, text))",
     "        trace.append(Traced(layer, name, fate, detail))"),

    ("the operator's tier is traced as the framework's, so the deployment's standard reads as "
     "the package's",
     CONTEXT,
     "source=\"operator's own\", layer=OPERATOR, trace=trace)",
     "source=\"operator's own\", trace=trace)"),

    ("a guideline refused for leaving the repository is traced as missing, so an escape reads "
     "like a typo",
     CONTEXT,
     "            _dropped(trace, named_by, g, REFUSED, _why_refused(repo_path, g))",
     "            _dropped(trace, named_by, g, MISSING)"),

    ("a guideline the checkout lacks is not traced, so explain shows the project naming nothing",
     CONTEXT,
     "            _dropped(trace, named_by, g, MISSING)\n",
     ""),

    ("a constraint is traced by its absolute path, not the checkout path the manifest's glob "
     "matched",
     CONTEXT,
     '        _kept(trace, "docs.constraints", p.relative_to(repo_path).as_posix(),',
     '        _kept(trace, "docs.constraints", str(p),'),

    ("a profile's own added guideline is traced as the framework's",
     CONTEXT,
     "            out.append(_kept(trace, PROFILE, extra, doc.read_text()[:_MAX_DOC_CHARS]))",
     "            out.append(_kept(trace, FRAMEWORK, extra, doc.read_text()[:_MAX_DOC_CHARS]))"),

    ("a profile line that names no file any tier has is not traced, so explain shows a waive "
     "that changes nothing as though it were not written",
     CONTEXT,
     "        _dropped(trace, PROFILE, name, MISSING,\n",
     "        (lambda *_a: None)(trace, PROFILE, name, MISSING,\n"),

    ("a framework file kept because its replacement is missing loses why it was kept",
     CONTEXT,
     '                         detail=substitute or ""))',
     '                         detail=""))'),

    # ── the role prompt's one layer ──────────────────────────────────────────────────────────────
    ("the role prompt's source stops finding the shipped file, so a shipped role reads as missing",
     ROLES,
     "    if path.exists():\n        return SHIPPED, path",
     "    if False:\n        return SHIPPED, path"),

    # ── explain itself ───────────────────────────────────────────────────────────────────────────
    ("explain resolves no profile, so a project that waives tdd.md is shown keeping it",
     EXPLAIN,
     "        return resolve_profile(manifest.profile, project_dir=checkout)",
     "        return None"),

    ("an address is no longer refused as one, and reads as a directory that is not there",
     EXPLAIN,
     "    if _is_an_address(target):",
     "    if False:"),

    ("a profile that resolves nowhere stops saying where it was looked for",
     PROFILES,
     "            name=name, looked=tuple(looked))",
     "            name=name)"),

    ("a Portuguese label falls back to English",
     EXPLAIN,
     '    "kept": {"en": "kept", "pt-BR": "mantido"},',
     '    "kept": {"en": "kept", "pt-BR": "kept"},'),

    ("the command drops `--language`, so a pt-BR reader is answered in English",
     CLI,
     "        typer.echo(ex.explain(checkout, language=language, full=full), nl=False)",
     '        typer.echo(ex.explain(checkout, language="en", full=full), nl=False)'),

    # ── what it prints ───────────────────────────────────────────────────────────────────────────
    ("the operator's directory is not named, so its rows appear with no source",
     EXPLAIN,
     '        lines.append(f"  {labels[1].ljust(width)}  {operator_guidelines.ENV_VAR}={directory}")\n',
     "        pass\n"),

    ("`--full` prints nothing more than the table",
     EXPLAIN,
     "        if full and text:",
     "        if False:"),

    ("the fenced brief is printed after all — the card's words, behind a marker drawn at random",
     EXPLAIN,
     "    if said:\n        out += [\"\", _say(SAY, \"log\", language)]",
     "    from openfactory.adapters.agent.base import ticket_brief\n"
     "    out.append(ticket_brief(context))\n"
     "    if said:\n        out += [\"\", _say(SAY, \"log\", language)]"),

    # ── what it must never do ────────────────────────────────────────────────────────────────────
    ("explain reads the knowledge bundle, which can fetch a branch",
     EXPLAIN,
     '        context = ctx.build_context(manifest, checkout, ctx._BLANK_CARD, knowledge_map="",',
     "        context = ctx.build_context(manifest, checkout, ctx._BLANK_CARD, knowledge_map=None,"),

    ("a refusal escapes as a traceback",
     CLI,
     "    except ex.Refused as refused:",
     "    except ZeroDivisionError as refused:"),

    ("a language nobody wrote is accepted and answered in English",
     EXPLAIN,
     "    if language not in LANGUAGES:",
     "    if False:"),
]
