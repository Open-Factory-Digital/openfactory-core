"""#206, proven by breaking it — on GitHub the doctor never says "no gate needs a person" about
gates it could not see.

GitHub gates a merge with RULESETS (readable with read access) and with CLASSIC branch protection
(shown only to a repository administrator). #184's listing read the first, so a branch requiring
two approvals through the second answered `[]` and the doctor called it ungated.

FOUR CLAIMS:

  1. **A listing known to be incomplete is never an empty one.** Classic rules that are there
     and unreadable — a 404, a 403, a `gh` that never answered, an answer nobody understands, a
     branch that could not be read at all — answer `GatesNotListed`, except when the listing
     already names a gate a person settles, which stays named.
  2. **The administrator's read is made only when the branch says classic rules may be there**:
     `protection.enabled`, never `protected` (true under a ruleset alone), and an administrator's
     "Branch not protected" is believed where a "Not Found" is not.
  3. **Readable classic protection is typed like the rulesets**, a gate both set is named once,
     a rule that is present and switched off is not a gate, and a status check is `unknown`.
  4. **The reason reaches the person**: the row raises the port's type, the port hands it on as
     a value, the doctor quotes it — and quotes nothing else. Every refusal leaves a log line.

The guards are `tests/test_the_doctor_never_says_no_gate_about_a_branch_it_could_not_read.py`
(the row and the finding) and, for the seam, #184's own guard.
"""

TEST = "tests/test_the_doctor_never_says_no_gate_about_a_branch_it_could_not_read.py"
SEAM = "tests/test_the_doctor_names_the_gates_only_a_person_settles.py"

GITHUB = "openfactory/adapters/forge/github.py"
BASE = "openfactory/adapters/forge/base.py"
DOCTOR = "openfactory/doctor.py"

MUTATIONS = [
    # ── claim 1: incomplete is never empty ────────────────────────────────────────────────────
    ("THE DEFECT: classic rules nobody could read are answered as the listing without them",
     GITHUB,
     "        raise GatesNotListed(unseen)\n",
     "        return rows\n"),

    ("the branch is never asked whether classic rules exist", GITHUB,
     '            if classic is False or (classic is not True and branch.get("protected") '
     "is not True):\n",
     "            if True:\n"),

    ("a branch that could not be read is taken for one without classic rules", GITHUB,
     "        if branch is None:\n",
     "        if branch is None:\n            return rows\n"),

    ("an answer that is not the document expected is used as if it were", GITHUB,
     "        if not isinstance(document, expect):\n",
     "        if document is None:\n"),

    ("a `gh` that never answered is an AttributeError, not a sentence", GITHUB,
     '        if p is None:\n            return None, "gh did not answer"',
     '        if False:\n            return None, "gh did not answer"'),

    ("a gate the ruleset already names is un-named because classic rules sit beside it", GITHUB,
     '        if any(row["kind"] == "process" for row in rows):\n',
     "        if False:\n"),

    ("what everybody may read of the classic rules — the required checks — is left out", GITHUB,
     '            rows = _named_once(rows + _status_check_gates(summary.get('
     '"required_status_checks")))\n',
     "            rows = list(rows)\n"),

    # ── claim 2: when the administrator's read is made ────────────────────────────────────────
    ("`protected` decides, so every ruleset-only repository is sent to be refused", GITHUB,
     '            if classic is False or (classic is not True and branch.get("protected") '
     "is not True):\n",
     '            if branch.get("protected") is not True:\n'),

    ("a branch document that does not say `enabled` is taken for one that says false", GITHUB,
     '            if classic is False or (classic is not True and branch.get("protected") '
     "is not True):\n",
     "            if classic is not True:\n"),

    ("an administrator told `Branch not protected` is answered `could not be listed`", GITHUB,
     '            if why.startswith("Branch not protected"):\n',
     "            if False:\n"),

    ("any refusal is believed to mean there are no classic rules", GITHUB,
     '            if why.startswith("Branch not protected"):\n',
     "            if True:\n"),

    # ── claim 3: the typing ───────────────────────────────────────────────────────────────────
    ("readable classic protection is read and thrown away", GITHUB,
     "                return _named_once(rows + _classic_gates(protection))\n",
     "                return rows\n"),

    ("a gate set in both mechanisms is named twice", GITHUB,
     "                return _named_once(rows + _classic_gates(protection))\n",
     "                return rows + _classic_gates(protection)\n"),

    ("classic: a required review is not a gate", GITHUB,
     '    rows = _review_gates(approvals=reviews.get("required_approving_review_count"),\n',
     "    rows = _review_gates(approvals=0,\n"),

    ("classic: code-owner review is read under the ruleset's spelling, and never found", GITHUB,
     '                         code_owner=reviews.get("require_code_owner_reviews"),\n',
     '                         code_owner=reviews.get("require_code_owner_review"),\n'),

    ("classic: conversation resolution is not a gate", GITHUB,
     '                         conversations=enabled("required_conversation_resolution"))\n',
     "                         conversations=False)\n"),

    ("classic: signed commits are not a gate", GITHUB,
     '    if enabled("required_signatures"):\n',
     "    if False:\n"),

    ("classic: a locked branch is not a gate", GITHUB,
     '    if enabled("lock_branch"):\n',
     "    if False:\n"),

    ("classic: a rule that is present and switched OFF is listed as a gate", GITHUB,
     '        return isinstance(value, dict) and value.get("enabled") is True\n',
     "        return isinstance(value, dict)\n"),

    ("classic: the required status checks are dropped", GITHUB,
     '    return rows + _status_check_gates(protection.get("required_status_checks"))\n',
     "    return rows\n"),

    ("a status check a live answer names in `checks` and again in `contexts` is listed twice",
     GITHUB,
     '            rows = _named_once(rows + _status_check_gates(summary.get('
     '"required_status_checks")))\n',
     '            rows = rows + _status_check_gates(summary.get("required_status_checks"))\n'),

    ("only the older `contexts` list is read, the one GitHub is closing down", GITHUB,
     '        required = [*(required.get("checks") or []), *(required.get("contexts") or [])]\n',
     '        required = [*(required.get("contexts") or [])]\n'),

    ("only `checks` is read, which GitHub's documented protection does not carry", GITHUB,
     '        required = [*(required.get("checks") or []), *(required.get("contexts") or [])]\n',
     '        required = [*(required.get("checks") or [])]\n'),

    ("a required status check is typed as something a change to the code settles", GITHUB,
     '            rows.append({"name": context, "blocking": True, "kind": "unknown"})\n',
     '            rows.append({"name": context, "blocking": True, "kind": "code"})\n'),

    # ── claim 4: the reason, and the trace ────────────────────────────────────────────────────
    ("the row answers a bare None: true, and the person is told `the read failed`", GITHUB,
     "        raise GatesNotListed(unseen)\n",
     "        return None\n"),

    ("what GitHub answered is left out of the sentence", GITHUB,
     'f"be read with this credential ({why}): GitHub shows it only to a "\n',
     'f"be read with this credential: GitHub shows it only to a "\n'),

    ("a refused read leaves no trace", GITHUB,
     '            log.info("could not %s: %s", what, why)\n',
     "            pass\n"),

    ("the port swallows the row's sentence", BASE,
     "        return said\n",
     "        return None\n", SEAM),

    ("the doctor guesses when the row said why", DOCTOR,
     '        why = str(rows).strip().rstrip(".") if isinstance(rows, GatesNotListed) else ""\n',
     '        why = ""\n', SEAM),

    ("the doctor quotes any exception it is handed, transport noise included", DOCTOR,
     '        why = str(rows).strip().rstrip(".") if isinstance(rows, GatesNotListed) else ""\n',
     '        why = str(rows).strip().rstrip(".") if isinstance(rows, Exception) else ""\n', SEAM),

    ("a blank reason replaces the generic sentence with nothing", DOCTOR,
     '        why = str(rows).strip().rstrip(".") if isinstance(rows, GatesNotListed) else ""\n',
     '        why = str(rows).rstrip(".") if isinstance(rows, GatesNotListed) else ""\n', SEAM),
]
