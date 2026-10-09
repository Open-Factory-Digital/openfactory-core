"""`openfactory certify deployment`: a pack that names nobody, controls that answer from what was
read, a published schema every pack meets, and a command that writes only when told (#356,
core change 6, first slice).

Run:  .venv/bin/python tools/mutate.py tools/mutations/356_certify_deployment.py

The claims, each a row below that must go RED:

  REDACTION — pseudonyms come from a per-pack salt and the salt is never written; identifiers,
  URLs, e-mail addresses, hosts, paths, the floor's credential formats, PEM blocks and the values
  of credential-shaped variables are each dropped by their own rule; the practitioner is the one
  name kept and the consenting person is not; a box proof's advisory output is withheld;
  `redactions.json` is written even when nothing was redacted; and a pack in which anything
  survived is never written.

  CONTROLS — the profile table decides `n/a`; the reads this slice does not make (forge, releases)
  answer `unknown`, never `pass`; `unknown` never combines into a pass; and each control computed
  locally fails on the deployment fact it is about.

  THE SCHEMA — the validator refuses a keyword it does not enforce, follows `$ref`, and enforces
  `enum`, `pattern` and `additionalProperties`; outcomes are `not_measured`, never zeros, and the
  signature is `null`.

  THE COMMAND — a missing flag is refused by name before anything is read; `--dry-run` and the
  absence of `--yes` write nothing; the checksums are the files'; the summary says what the pack
  does not contain.
"""

TEST = "tests/test_a_pack_names_nobody.py"

REDACT = "openfactory/certify/redact.py"
PACK = "openfactory/certify/pack.py"
CONTROLS = "openfactory/certify/controls.py"
SCHEMA = "openfactory/certify/schema.py"
CLI = "openfactory/cli.py"
REFUSALS = "openfactory/cli_refusals.py"

NAMES = "tests/test_a_pack_names_nobody.py"
CTRL = "tests/test_certify_controls_answer_from_what_was_read.py"
SCH = "tests/test_the_pack_has_a_published_schema.py"
CMD = "tests/test_certify_deployment_writes_only_when_told.py"
OWN_RULE = NAMES + "::test_urls_addresses_hosts_paths_and_long_secrets_are_dropped_by_their_own_rule"

MUTATIONS = [
    # ── redaction ───────────────────────────────────────────────────────────────────────────────
    ("pseudonyms are numbered alphabetically, not by the per-pack salt", REDACT,
     "            order = sorted((i for i in given if len(i.strip()) >= 2), key=lambda i: hmac.new(\n"
     '                salt, f"{category}\\0{i}".encode(), hashlib.sha256).digest())',
     "            order = sorted(i for i in given if len(i.strip()) >= 2)",
     NAMES + "::test_pseudonyms_are_stable_within_a_pack_and_unrelated_across_packs"),

    ("the salt itself is written into the log", REDACT,
     '            "salt_id": self.salt_id,',
     '            "salt_id": self.salt_id,\n            "salt": self.salt.hex(),',
     NAMES + "::test_the_salt_is_never_written_only_its_id"),

    ("identifiers are not replaced by their pseudonyms", REDACT,
     "            text = self._names.sub(rename, text)",
     "            text = text",
     NAMES + "::test_a_deployment_full_of_real_names_yields_a_pack_that_names_nobody"),

    ("URLs are left to the path rule", REDACT,
     '        text = _URL.sub(drop("url", "[url]"), text)',
     "        text = text", OWN_RULE),

    ("e-mail addresses are kept", REDACT,
     '        text = _EMAIL.sub(drop("email", "[email]"), text)',
     "        text = text", OWN_RULE),

    ("paths are kept", REDACT,
     '        if "/" in core and not re.fullmatch(r"[\\d/]+", core):',
     "        if False:", OWN_RULE),

    ("hostnames are kept", REDACT,
     "        if _IPV4.fullmatch(core) or _HOST.fullmatch(core):",
     "        if False:", OWN_RULE),

    ("the floor's credential formats are not applied", REDACT,
     '        text = self._floor.sub(drop("credential", "[credential]"), text)',
     "        text = text", NAMES + "::test_every_credential_format_the_floor_scans_for_is_dropped"),

    ("a PEM block's body and footer survive its header", REDACT,
     '        text = _PEM.sub(drop("credential", "[credential]"), text)',
     "        text = text",
     NAMES + "::test_a_pem_private_key_is_dropped_header_body_and_footer"),

    ("a variable name the customer chose is kept", REDACT,
     '            text = self._variables.sub(drop("variable", "[variable]"), text)',
     "            text = text",
     NAMES + "::test_a_variable_name_the_customer_chose_is_dropped_and_the_platforms_are_kept"),

    ("the values of credential-shaped variables are not dropped", REDACT,
     "        for secret in self._secrets:",
     "        for secret in ():",
     NAMES + "::test_a_deployment_full_of_real_names_yields_a_pack_that_names_nobody"),

    ("a name merely SHAPED like a credential is not one", REDACT,
     "    return bool(set(words) & _SECRET_WORDS) and words[-1] not in _ABOUT_A_SECRET",
     "    return False",
     NAMES + "::test_the_value_of_every_credential_variable_is_dropped_whatever_its_name"),

    ("the environment's credential values are never collected", PACK,
     "    named = {k for k, v in env.items() if holds_a_credential(k)}",
     "    named: set[str] = set()",
     NAMES + "::test_the_value_of_every_credential_variable_is_dropped_whatever_its_name"),

    ("the practitioner is redacted like everybody else", PACK,
     '        "practitioner": practitioner,',
     '        "practitioner": redactor.person(practitioner),',
     NAMES + "::test_a_deployment_full_of_real_names_yields_a_pack_that_names_nobody"),

    ("the consenting person is kept by name", PACK,
     '        "consent": ({"by": redactor.person(consented[0]),',
     '        "consent": ({"by": consented[0],',
     NAMES + "::test_the_consenting_person_is_a_pseudonym_too"),

    ("a box proof's advisory output reaches the pack", PACK,
     "        out.box_lines = _withheld(st).lines()",
     "        out.box_lines = st.lines()",
     NAMES + "::test_a_box_proofs_advisory_output_is_withheld_and_logged"),

    ("redactions.json is written only when something was redacted", PACK,
     '    files["redactions.json"] = _dumps(redactor.log())',
     '    if redactor.replaced or redactor.dropped:\n'
     '        files["redactions.json"] = _dumps(redactor.log())',
     NAMES + "::test_redactions_json_is_written_even_when_nothing_was_redacted"),

    ("a pack in which something survived is handed back anyway", PACK,
     "    if leaked:",
     "    if False:",
     NAMES + "::test_a_pack_in_which_anything_survived_is_never_written"),

    # ── controls ────────────────────────────────────────────────────────────────────────────────
    # re-pinned 2026-10-05: the forge and releases reads are built, so no control is NOT_BUILT
    # any more; the claim now lives where an unread branch protection is answered (#356)
    ("a read this slice does not make answers pass", CONTROLS,
     "            if got is None:\n                results.append(UNKNOWN)",
     "            if got is None:\n                results.append(PASS)", CTRL),

    ("a control the profile does not require is evaluated as required", CONTROLS,
     "        if spec.id not in required:",
     "        if False:", CTRL),

    ("the light profile requires every control", CONTROLS,
     '    "light": frozenset(SECURITY_CONTROLS + EVERY_PACK),',
     '    "light": frozenset(CONTROL_IDS),', CTRL),

    ("an unknown answer combines into a pass", CONTROLS,
     "    for result in (FAIL, UNKNOWN, PASS, INFO):",
     "    for result in (FAIL, PASS, UNKNOWN, INFO):", CTRL),

    ("a panel token of whitespace counts as set", CONTROLS,
     '        if (r.env.get(name) or "").strip():',
     "        if name in r.env:", CTRL),

    ("a secrets file readable by others passes", CONTROLS,
     "    if f.mode is None or f.mode & 0o077:",
     "    if f.mode is None:", CTRL),

    ("a secrets file tracked by git passes", CONTROLS,
     '    if f.tracked:\n        problems.append("it is tracked by git")\n',
     "", CTRL),

    ("a stored token passes where the vendor offers a minted credential", CONTROLS,
     "                            if p.forge_mints else",
     "                            if False else", CTRL),

    ("the deployment's generic token passes", CONTROLS,
     '    "generic": (FAIL, "the deployment\'s generic token (OPENFACTORY_BOT_TOKEN or "',
     '    "generic": (PASS, "the deployment\'s generic token (OPENFACTORY_BOT_TOKEN or "', CTRL),

    ("the credential is read off the variables, not the platform's resolution", PACK,
     "        source = credentials.forge_credential_source(project)",
     '        source = "deployment:" if os.environ.get("OPENFACTORY_GH_APP_ID") else ""', CTRL),

    ("the allow list passes on a box that does not honour it", CONTROLS,
     "    return (PASS if not lacking and container else FAIL), \"; \".join(said), []",
     "    return (PASS if not lacking else FAIL), \"; \".join(said), []", CTRL),

    ("a repository with no test gate passes", CONTROLS,
     '        return (PASS, "declares `test`") if "test" in _roles(m) else \\',
     '        return (PASS, "declares `test`") if "security" in _roles(m) else \\', CTRL),

    ("components with no risk: high pass", CONTROLS,
     "        if high:\n            return PASS",
     "        if True:\n            return PASS", CTRL),

    ("a floor without .openfactory/** passes", CONTROLS,
     "    if wanted in r.floor_protected:",
     "    if r.floor_protected:", CTRL),

    ("more than one job at a time passes instead of being information", CONTROLS,
     "    if value == 1:",
     "    if value >= 1:", CTRL),

    ("a retention under thirty days passes", CONTROLS,
     "    return (PASS if days >= RETENTION_FLOOR_DAYS else FAIL), said, pointer",
     "    return PASS, said, pointer", CTRL),

    ("a red post_merge line passes", CONTROLS,
     '                results.append(PASS if line == "ok" else FAIL)',
     "                results.append(PASS)", CTRL),

    ("named approvers pass without being able to sign", CONTROLS,
     "                able = [a for a in named if a in r.approvers]",
     "                able = named", CTRL),

    ("an unreadable proof passes", CONTROLS,
     "                results.append(UNKNOWN)\n"
     '                said.append(f"{who}: the proof could not be read")',
     "                results.append(PASS)\n"
     '                said.append(f"{who}: the proof could not be read")', CTRL),

    ("a red doctor passes", CONTROLS,
     '        results.append(PASS if p.doctor.get("ok") is True and not red else FAIL)',
     "        results.append(PASS)", CTRL),

    # ── the schema ──────────────────────────────────────────────────────────────────────────────
    ("the validator silently accepts a keyword it does not enforce", SCHEMA,
     "    if unknown:",
     "    if False:", SCH),

    ("`$ref` is not followed, so no control entry is checked", SCHEMA,
     '    if "$ref" in schema:',
     "    if False:", SCH),

    ("`enum` is not enforced", SCHEMA,
     '    if "enum" in schema and value not in schema["enum"]:',
     "    if False:", SCH),

    ("`additionalProperties: false` is not enforced", SCHEMA,
     "            elif extra is False:",
     "            elif extra is None:", SCH),

    ("outcomes are reported as measured zeros", PACK,
     '        "outcomes": {"status": "not_measured", "reason": OUTCOMES_REASON},',
     '        "outcomes": {"status": "measured", "reason": "0 jobs"},', CMD),

    ("the pack claims a signature it does not carry", PACK,
     '        "signature": None,',
     '        "signature": "pack.sig",', CMD),

    # ── the command ─────────────────────────────────────────────────────────────────────────────
    ("an empty --practitioner is not refused", REFUSALS,
     '        if not (given[flag] or "").strip():',
     "        if given[flag] is None:", CMD),

    ("--dry-run writes the pack too", CLI,
     '        typer.echo(f"— --dry-run: nothing was written. With --yes this writes {target}.")',
     "        certify.write(built, target)\n"
     '        typer.echo(f"— --dry-run: nothing was written. With --yes this writes {target}.")',
     CMD),

    ("the pack is written without --yes", CLI,
     "    if not yes:\n        typer.echo(built.files[\"summary.md\"].rstrip(\"\\n\"))",
     "    if False:\n        typer.echo(built.files[\"summary.md\"].rstrip(\"\\n\"))", CMD),

    ("the checksums are not the files'", PACK,
     '    document["checksums"] = {path: "sha256:" + hashlib.sha256(text.encode()).hexdigest()',
     '    document["checksums"] = {path: "sha256:" + hashlib.sha256(b"").hexdigest()', CMD),

    ("the summary stops saying what the pack does not contain", PACK,
     '        "## What this pack does not contain yet",',
     '        "## Notes on this pack",', CMD),
]
