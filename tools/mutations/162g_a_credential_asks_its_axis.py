"""#162 (doctor.py:832 and its seventeen neighbours): a credential is asked of its own axis."""

TEST = "tests/test_a_credential_is_asked_of_its_own_axis.py"
CRED = "openfactory/credentials.py"
DOCTOR = "openfactory/doctor.py"
ACT = "openfactory/runtime/temporal/activities.py"
BOX = "openfactory/runtime/boxed_job.py"

MUTATIONS = [
    # ── the resolver, both directions ───────────────────────────────────────────────────────────
    ("the tracker axis offers a GitHub mint to every vendor again", CRED,
     '    kind = str(getattr(getattr(project, "tracker", None), "kind", "") '
     'or "").strip().lower()\n'
     '    if kind and kind != "github":\n        return None',
     "    pass"),

    ("…and the reverse: it offers NOTHING to anybody, including GitHub", CRED,
     '    if kind and kind != "github":\n        return None\n'
     "    from openfactory.factory import github_app_token_from_env\n\n"
     "    return github_app_token_from_env()\n\n\ndef deployment_forge_token",
     "    return None\n\n\ndef deployment_forge_token"),

    ("a row that names no vendor at all is refused — a legacy deployment goes dark", CRED,
     '    kind = str(getattr(getattr(project, "tracker", None), "kind", "") '
     'or "").strip().lower()\n'
     '    if kind and kind != "github":',
     '    kind = str(getattr(getattr(project, "tracker", None), "kind", "") '
     'or "").strip().lower()\n'
     '    if kind != "github":'),

    ("the tracker resolver reads the FORGE's row", CRED,
     '    kind = str(getattr(getattr(project, "tracker", None), "kind", "") '
     'or "").strip().lower()\n'
     '    if kind and kind != "github":\n        return None\n'
     "    from openfactory.factory import github_app_token_from_env",
     '    kind = str(getattr(getattr(project, "forge", None), "kind", "") '
     'or "").strip().lower()\n'
     '    if kind and kind != "github":\n        return None\n'
     "    from openfactory.factory import github_app_token_from_env"),

    # ── the site the card named ─────────────────────────────────────────────────────────────────
    ("the doctor's board probe falls back to the GitHub mint again", DOCTOR,
     "        return tracker_token_for(project) or deployment_tracker_token(project)",
     "        from openfactory.factory import github_app_token_from_env\n\n"
     "        return tracker_token_for(project) or github_app_token_from_env()"),

    # ── the axis mix-up ─────────────────────────────────────────────────────────────────────────
    ("the board is read with the FORGE axis's credential again", ACT,
     "    token = tracker_token_for(project) or deployment_tracker_token(project) or None\n"
     "    tickets, error = read_board(project, token=token)",
     "    from openfactory.credentials import forge_token_for\n\n"
     "    token = forge_token_for(project) or None\n"
     "    tickets, error = read_board(project, token=token)"),

    # ── the box ─────────────────────────────────────────────────────────────────────────────────
    ("the box goes back to a process-wide credential", BOX,
     "        token = (forge_token_for(_project_for(cfg, repo_dir=None))\n"
     "                 or forge_token()             # honour OPENFACTORY_BOT_TOKEN for the "
     "GitHub path\n"
     "                 or deployment_forge_token(_project_for(cfg, repo_dir=None)))",
     "        token = forge_token()"),

    # ── the ratchet ─────────────────────────────────────────────────────────────────────────────
    # The allow-list is gone: an exemption is a `# github-only:` sentence AT THE CALL now, so a
    # widened list is not a thing that can be mutated. What can, and must go red:
    ("the ratchet stops walking", TEST,
     '    out: list[str] = []\n    for path in sorted(root.rglob("*.py")):\n'
     "        text = path.read_text()\n        lines = text.splitlines()",
     '    out: list[str] = []\n    for path in sorted(root.rglob("nothing-*.py")):\n'
     "        text = path.read_text()\n        lines = text.splitlines()"),

    ("a bare call counts as a last resort — every honest site is flagged", TEST,
     "            for value in node.values[1:]:", "            for value in node.values:"),

    ("…and the reverse: a sentence anywhere in the file exempts every call in it", TEST,
     '                near = "\\n".join(lines[max(0, value.lineno - 7):value.lineno])',
     "                near = text"),

    # The crossed-axis check was rewritten from a regex to an AST walk after adversarial review
    # (the regex could not cross a nested `)` — see 162h). Its cuts live there.

]
