"""Task AD — the only thing that reads the preflight document refuses; it does not raise.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_the_document_check_refuses.py

The Python block inside `scripts/e2e-verify.sh` checked the document's shape with bare `assert`s
(Roberto, 2026-09-04). Three distinct failures for one reader: `doc["schema"]` on a document with
no schema raises KeyError before the assert message is ever built; an AssertionError prints a
traceback about our subscripts rather than a line about their install; and `python3 -O` deletes
assert statements, so the whole check is one word away from not existing.

The cuts restore each of those, plus the two ways the guards themselves could stop measuring: by
reading the block as text instead of running it, and by losing the positive twin so a block that
refuses every document would pass.

The last cut is the one worth reading. Two OLDER guards in this file asserted the literal string
`finding["remedy"]` appeared in the script — and both went red when the check was rewritten to
`finding.get("remedy", "")`, which is strictly stronger. A guard that a correct improvement breaks
is measuring a spelling. Both now run the block against a red finding with a blank remedy.
"""

TEST = "tests/test_the_end_to_end_install_is_a_script_the_suite_can_run.py"

VERIFY = "scripts/e2e-verify.sh"

MUTATIONS = [
    # ── the shapes that used to raise ────────────────────────────────────────────────────────────
    ("TODAY'S DEFECT: the schema is subscripted rather than fetched, so a document without one "
     "raises KeyError — a traceback about us instead of a sentence about their install",
     VERIFY,
     'schema = doc.get("schema")\nif not isinstance(schema, str) or not schema.startswith(',
     'schema = doc["schema"]\nif not isinstance(schema, str) or not schema.startswith('),

    ("the shape checks go back to bare asserts, which print a traceback and which -O deletes",
     VERIFY,
     'findings = doc.get("findings")\nif not isinstance(findings, list) or not findings:',
     'assert doc["findings"], "preflight named nothing at all"\nif False:'),

    ("a finding is trusted to be an object, so a list of strings raises TypeError inside the loop",
     VERIFY,
     "    if not isinstance(finding, dict):",
     "    if False:"),

    ("the missing-key check goes, so `finding[\"answered\"]` raises on a finding without it",
     VERIFY,
     '    missing = {"check", "answered", "ok"} - set(finding)',
     "    missing = set()"),

    ("the document is trusted to be an object, so a JSON list raises AttributeError",
     VERIFY,
     "if not isinstance(doc, dict):",
     "if False:"),

    # ── the promise that makes tolerating a red preflight safe ───────────────────────────────────
    ("a red finding no longer has to say what to do about it — the one rule that makes a job "
     "which tolerates red preflights meaningful",
     VERIFY,
     '    if finding["answered"] and not finding["ok"] and not str(finding.get("remedy", "")).strip():',
     "    if False:"),

    ("any schema is accepted, so a document from some other tool passes as a preflight",
     VERIFY,
     'or not schema.startswith("openfactory.preflight/"):',
     "or False:"),

    ("an empty findings list is accepted — preflight reporting nothing about a machine",
     VERIFY,
     "if not isinstance(findings, list) or not findings:",
     "if not isinstance(findings, list):"),

    # ── the guards ───────────────────────────────────────────────────────────────────────────────
    ("the guard reads the block as text instead of running it, so it can only ever check spelling "
     "— which is how the two older guards in this file came to be broken by an improvement",
     TEST,
     "    argv = [sys.executable] + ([\"-O\"] if optimised else []) + [str(program), str(document)]\n"
     "    return subprocess.run(argv, capture_output=True, text=True, timeout=60)",
     "    argv = [sys.executable, \"-c\", \"import sys; sys.exit(0)\"]\n"
     "    return subprocess.run(argv, capture_output=True, text=True, timeout=60)"),

    # ── two cuts that first attacked the guards and SURVIVED, re-aimed at the script ─────────────
    #
    # Both removed an assertion whose property another test in this file also makes — duplicate
    # coverage, not a weak guard, and nothing the suite can be asked to catch. Aimed at the script
    # they are regressions, and each is red only because of the assertion the surviving cut had
    # removed. (The third survivor was a real gap: no document put a non-object inside `findings`,
    # so the per-finding isinstance check was unmeasured. That one got a test, not a re-aim.)

    ("every finding must carry a remedy, not only the red ones — so a healthy machine's document "
     "is refused and no install could ever pass",
     VERIFY,
     '    if finding["answered"] and not finding["ok"] and not str(finding.get("remedy", "")).strip():',
     '    if not str(finding.get("remedy", "")).strip():'),

    ("`refuse` prints the problem and swallows the remedy — the half a reader acts on",
     VERIFY,
     '    sys.exit(f"{problem}\\n  remedy: {remedy}")',
     '    sys.exit(problem)'),
]
