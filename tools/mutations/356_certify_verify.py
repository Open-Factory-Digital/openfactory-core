"""`openfactory certify verify`: a pack checked offline the way the submissions bot checks it — its
members, its schema, its checksums, its signature, and every threshold, each by id (#356, second
slice, part A).

Run:  .venv/bin/python tools/mutate.py tools/mutations/356_certify_verify.py

The claims, each a row below that must go RED:

  THE PACK ITSELF — a member that is not a plain file is a finding; the schema is checked; every
  file is in SHA256SUMS and its digest holds (which is what covers `pack.json`); `pack.json`'s own
  checksums hold too; a pack without SHA256SUMS is a finding; `certify deployment` writes it.

  THE SIGNATURE — not built: an unsigned pack is a finding, a `pack.sig` this build cannot check
  is a finding, and `--allow-unsigned` is the one way past it.

  THE THRESHOLDS — an `unknown` control is never a pass, whatever a thresholds file says; the
  profile table decides what is required, never the pack's own flags; a security control that
  fails is a finding; each number is held at its edge (20 jobs, half merged, under a tenth unknown
  parks, 7 days); an outcome not measured fails as "not measured", never as zero; no job is no
  share; no proof is no pass; C-VERSION must pass; a practitioner of whitespace names nobody; the
  shipped file carries the issue's numbers; a file this build cannot enforce whole is refused.

  THE COMMAND — exit 2 for a pack that cannot be read and for a profile it does not know;
  `--profile` is the profile verified against.
"""

TEST = "tests/test_certify_verify_holds_a_pack_to_its_thresholds.py"

VERIFY = "openfactory/certify/verify.py"
PACK = "openfactory/certify/pack.py"
CLI = "openfactory/cli.py"
REFUSALS = "openfactory/cli_refusals.py"
SHIPPED = "openfactory/certify/thresholds.yaml"

T = TEST + "::"

MUTATIONS = [
    # ── the pack itself ─────────────────────────────────────────────────────────────────────────
    ("a member that is not a regular file is skipped in silence", VERIFY,
     '                    problems.append(f"{name}: not a regular file")',
     "                    pass",
     T + "test_a_member_that_is_not_a_plain_file_is_a_finding"),

    ("the schema is not checked", VERIFY,
     "    errors = validate(bundle.document)",
     "    errors = []",
     T + "test_a_schema_violation_is_one_finding_per_error"),

    ("a digest SHA256SUMS lists is not compared", VERIFY,
     "            elif _sha256(files[name]) != digest:\n"
     '                fail(f"{name}: its SHA-256 is not the one {SUMS_FILE} lists")',
     "            elif False:\n"
     '                fail(f"{name}: its SHA-256 is not the one {SUMS_FILE} lists")',
     T + "test_a_pack_json_changed_after_writing_is_caught_by_sha256sums"),

    ("a file SHA256SUMS does not list passes", VERIFY,
     "        for name in sorted(set(files) - set(listed) - {SUMS_FILE, SIGNATURE_FILE}):",
     "        for name in ():",
     T + "test_a_file_slipped_in_or_taken_out_is_a_finding"),

    ("pack.json's own checksums are not compared", VERIFY,
     '        elif f"sha256:{_sha256(files[name])}" != digest:',
     "        elif False:",
     T + "test_a_diagnostic_changed_after_writing_fails_both_lists"),

    ("a pack without SHA256SUMS passes", VERIFY,
     '    if SUMS_FILE not in files:\n        fail(f"the pack carries no {SUMS_FILE}")',
     "    if SUMS_FILE not in files:\n        pass",
     T + "test_a_pack_without_sha256sums_is_a_finding"),

    ("certify deployment writes no SHA256SUMS", PACK,
     "    ordered[SUMS_FILE] = sha256sums(ordered)",
     "    pass",
     T + "test_the_pack_certify_wrote_holds_together_and_is_unsigned"),

    # ── the signature ───────────────────────────────────────────────────────────────────────────
    ("an unsigned pack passes", VERIFY,
     '    return [Result("signature", False, UNSIGNED)]',
     '    return [Result("signature", True, UNSIGNED)]',
     T + "test_a_pack_that_meets_every_threshold_exits_0_only_when_unsigned_is_allowed"),

    ("--allow-unsigned is ignored", VERIFY,
     "    if allow_unsigned:\n"
     '        return [Result("signature", True, ALLOWED_UNSIGNED, skipped=True)]',
     "    if False:\n"
     '        return [Result("signature", True, ALLOWED_UNSIGNED, skipped=True)]',
     T + "test_a_pack_that_meets_every_threshold_exits_0_only_when_unsigned_is_allowed"),

    ("a pack.sig nobody can check passes", VERIFY,
     '        return [Result("signature", False, f"{SIGNATURE_FILE} is present and this build '
     'cannot "',
     '        return [Result("signature", True, f"{SIGNATURE_FILE} is present and this build '
     'cannot "',
     T + "test_a_present_signature_this_build_cannot_check_is_a_finding_too"),

    # ── the thresholds ──────────────────────────────────────────────────────────────────────────
    ("a threshold that asks for it accepts unknown as a pass", VERIFY,
     '    accept = [a for a in t.params["accept"] if a in _MAY_BE_ACCEPTED]',
     '    accept = list(t.params["accept"])',
     T + "test_no_thresholds_file_can_make_unknown_a_pass"),

    ("a thresholds file may accept unknown", VERIFY,
     '    "required_controls": ({"accept": _strings(_MAY_BE_ACCEPTED)}, _required_controls),',
     '    "required_controls": ({"accept": _strings(frozenset(c.RESULTS))}, _required_controls),',
     T + "test_no_thresholds_file_can_make_unknown_a_pass"),

    ("the pack's own required flags decide what is required", VERIFY,
     "    required = [ident for ident in c.CONTROL_IDS if ident in c.PROFILES[profile]]",
     '    required = [e.get("id") for e in document.get("controls") or [] if e.get("required")]',
     T + "test_what_is_required_is_the_profile_table_never_the_packs_own_flags"),

    ("a failing security control passes", VERIFY,
     '        elif entry.get("result") == c.FAIL:',
     "        elif False:",
     TEST + "::test_a_security_control_that_fails_is_a_finding_on_every_profile"),

    ("twenty jobs are not enough", VERIFY,
     "    if jobs < least:",
     "    if jobs <= least:",
     T + "test_twenty_jobs_meet_the_threshold"),

    ("exactly half merged is not enough", VERIFY,
     "    if merged / jobs < least:",
     "    if merged / jobs <= least:",
     T + "test_half_the_jobs_reach_the_merge"),

    ("unknown parks at a tenth of the jobs pass", VERIFY,
     "    if unknown / jobs >= below:",
     "    if unknown / jobs > below:",
     T + "test_unclassified_parks_stay_under_a_tenth_of_the_jobs"),

    ("a card waiting exactly seven days fails", VERIFY,
     "    if oldest > days:",
     "    if oldest >= days:",
     T + "test_no_card_waits_more_than_seven_days_in_needs_action"),

    ("an unmeasured job count reads as zero", VERIFY,
     '    missing = _not_measured(t, outcomes, "jobs")\n'
     "    if missing:\n"
     "        return [missing]\n"
     '    jobs, least = outcomes["jobs"], t.params["min"]',
     '    jobs, least = outcomes["jobs"] or 0, t.params["min"]',
     T + "test_an_outcome_not_measured_fails_as_not_measured_never_as_zero"),

    ("no job in the window passes the merged share", VERIFY,
     '        return [Result(t.id, False, "no job ended in the window, so no share of them '
     'merged")]',
     '        return [Result(t.id, True, "no job ended in the window, so no share of them '
     'merged")]',
     T + "test_no_job_in_the_window_is_no_share_of_them"),

    ("a pack with no proof passes", VERIFY,
     '        return [Result(t.id, False, "the pack carries no box proof")]',
     '        return [Result(t.id, True, "the pack carries no box proof")]',
     T + "test_every_proof_is_valid_and_a_pack_with_none_fails"),

    ("C-VERSION passes unless it fails", VERIFY,
     '    if entry.get("result") != c.PASS:',
     '    if entry.get("result") == c.FAIL:',
     T + "test_the_version_threshold_is_c_version"),

    ("a practitioner of whitespace is a practitioner", VERIFY,
     '    named = str(document.get("practitioner") or "").strip()',
     '    named = str(document.get("practitioner") or "")',
     T + "test_a_practitioner_of_whitespace_names_nobody"),

    ("the shipped file asks for two jobs", SHIPPED,
     "    check: min_jobs\n    min: 20",
     "    check: min_jobs\n    min: 2",
     T + "test_the_shipped_thresholds_are_the_issues_numbers"),

    ("a parameter a check does not take is accepted", VERIFY,
     "        if unknown:\n"
     '            raise ThresholdsError(f"{ident}: `{check}` takes no `{unknown[0]}`")',
     "        if False:\n"
     '            raise ThresholdsError(f"{ident}: `{check}` takes no `{unknown[0]}`")',
     T + "test_a_thresholds_file_this_build_cannot_enforce_is_refused"),

    ("a value of the wrong kind is accepted", VERIFY,
     "            wrong = rule(params[name])",
     '            wrong = ""',
     T + "test_a_thresholds_file_this_build_cannot_enforce_is_refused"),

    # ── the command ─────────────────────────────────────────────────────────────────────────────
    ("a pack that cannot be read exits 1", CLI,
     '        typer.echo(f"✗ the pack cannot be read: {exc}. Nothing was verified.", err=True)\n'
     "        raise typer.Exit(2) from None",
     '        typer.echo(f"✗ the pack cannot be read: {exc}. Nothing was verified.", err=True)\n'
     "        raise typer.Exit(1) from None",
     T + "test_a_pack_that_cannot_be_read_exits_2_and_judges_nothing"),

    ("a profile this build does not know is not refused", REFUSALS,
     "    if profile is not None and profile not in PROFILES:",
     "    if False:",
     T + "test_an_unknown_profile_is_refused_by_name"),

    ("--profile is ignored: the pack's claim is always verified", VERIFY,
     '    judged = profile or str(bundle.document.get("profile") or "")',
     '    judged = str(bundle.document.get("profile") or "")',
     T + "test_a_pack_is_verified_as_another_profile_when_asked"),
]
