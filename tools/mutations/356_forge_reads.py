"""`openfactory certify` reads the forge: the branch's protection, the credential's grants and the
platform's releases, each through an optional capability of the forge row, and a read nobody could
make is `unknown`, never `pass` (#356, core change 4, slice 3).

Run:  .venv/bin/python tools/mutate.py tools/mutations/356_forge_reads.py

The claims, each a row below that must go RED:

  THE PORT — only a real answer is believed: a double, a row without the capability and a row that
  raises are all "could not read".

  GITHUB — the rulesets settle what they set; classic protection is consulted when the branch says
  it has some, and a branch with none is OFF, not unread; classic protection that allows force
  pushes does not block them; an auto-merge switch GitHub did not show is unread, not off; an empty
  or missing scope header is not "granted nothing"; an App's permissions are read from its
  installation, never by minting; drafts and candidates are not releases; a URL on another host is
  never read with this credential.

  AZURE REPOS — only a blocking policy protects; a repository setting is not a pull request policy;
  a merge-commit strategy is not linear history; force pushes are blocked only where a pull request
  is required; auto-complete is never assumed; an unreadable listing is no answer, not an open
  branch; a PAT's scopes are never claimed.

  THE CONTROLS — a `None` read never passes (C-WORKFLOWS, C-BRANCH, C-VERSION); a credential that
  can write workflows fails; a fact read as off fails and beats one unread; the latest release is
  the highest version, not the first listed; the release before the latest passes; a development
  build is not a release.

  THE PACK — the forge is asked, with the credential a job holds, about every repository where it
  lives, and the releases are read from the package's own Repository URL.
"""

TEST = "tests/test_certify_reads_the_forge.py"

BASE = "openfactory/adapters/forge/base.py"
GITHUB = "openfactory/adapters/forge/github.py"
ADO = "openfactory/adapters/forge/azure_devops.py"
CONTROLS = "openfactory/certify/controls.py"
PACK = "openfactory/certify/pack.py"

T = "tests/test_certify_reads_the_forge.py"
CMD = "tests/test_certify_deployment_writes_only_when_told.py"

MUTATIONS = [
    # ── the port ────────────────────────────────────────────────────────────────────────────────
    ("a double's answer is believed as a branch protection", BASE,
     "    return said if isinstance(said, BranchProtection) else None",
     "    return said", T + "::test_a_forge_that_cannot_answer_is_no_answer"),

    ("a row that raises is read as a protected branch", BASE,
     "        log.info(\"%s could not read the protection of %s (%s)\", type(forge).__name__, "
     "branch,\n                 str(exc)[:160])\n        return None",
     "        log.info(\"%s could not read the protection of %s (%s)\", type(forge).__name__, "
     "branch,\n                 str(exc)[:160])\n        return BranchProtection(pr_required=True, "
     "linear_history=True, force_push_blocked=True, auto_merge_enabled=True)",
     T + "::test_a_forge_that_cannot_answer_is_no_answer"),

    ("a double's answer is believed as the credential's grants", BASE,
     "    if not isinstance(said, set | frozenset) or not all(isinstance(p, str) for p in said):\n"
     "        return None\n    return frozenset(said)",
     "    try:\n        return frozenset(said)\n    except TypeError:\n        return frozenset()",
     T + "::test_a_forge_that_cannot_answer_is_no_answer"),

    ("a double's answer is believed as the releases list", BASE,
     "    if not isinstance(said, list) or not all(isinstance(t, str) for t in said):\n"
     "        return None\n    return said",
     "    return said if said is not None else None",
     T + "::test_a_forge_that_cannot_answer_is_no_answer"),

    # ── GitHub ──────────────────────────────────────────────────────────────────────────────────
    ("a ruleset's pull_request rule is not read", GITHUB,
     '            "pr_required": True if "pull_request" in types else None,',
     '            "pr_required": None,',
     T + "::test_a_ruleset_settles_what_unreadable_classic_protection_cannot"),

    ("classic protection is never consulted", GITHUB,
     "        classic = self._classic_protection(target, name, where)",
     "        classic = None",
     T + "::test_github_reads_classic_protection_when_the_branch_says_it_has_some"),

    ("a branch with no protection at all reads as unread, not as off", GITHUB,
     "            return off\n        protection, why",
     "            return None\n        protection, why",
     T + "::test_github_reads_an_unprotected_branch_as_off_not_as_unread"),

    ("classic protection a credential may not read reads as off", GITHUB,
     '            return off if why.startswith("Branch not protected") else None',
     "            return off",
     T + "::test_classic_protection_this_credential_may_not_read_leaves_its_facts_unread"),

    ("force pushes classic protection allows read as blocked", GITHUB,
     '                "force_push_blocked": not on("allow_force_pushes")}',
     '                "force_push_blocked": True}',
     T + "::test_github_reads_classic_protection_when_the_branch_says_it_has_some"),

    ("an auto-merge switch GitHub did not show reads as off", GITHUB,
     "auto_merge_enabled=auto if isinstance(auto, bool) else None)",
     "auto_merge_enabled=auto if isinstance(auto, bool) else False)",
     T + "::test_an_auto_merge_switch_github_did_not_show_is_unread_not_off"),

    ("an empty scope header is read as granted nothing", GITHUB,
     "                return scopes or None",
     "                return scopes",
     T + "::test_a_token_whose_grants_github_does_not_list_is_no_answer"),

    ("a missing scope header is read as granted nothing", GITHUB,
     '                 "installation token, whose permissions it does not publish to the token")\n'
     "        return None",
     '                 "installation token, whose permissions it does not publish to the token")\n'
     "        return frozenset()",
     T + "::test_a_token_whose_grants_github_does_not_list_is_no_answer"),

    ("an App's permissions are not read from its installation", GITHUB,
     "        if isinstance(app, GitHubAppTokenProvider):",
     "        if False:",
     T + "::test_an_app_s_permissions_are_read_from_its_installation_signed_with_its_own_key"),

    ("drafts and candidates are listed as releases", GITHUB,
     '                and r.get("draft") is not True and r.get("prerelease") is not True]',
     "]",
     T + "::test_github_lists_the_published_releases_and_leaves_out_drafts_and_candidates"),

    ("a URL on another host is read with this credential", GITHUB,
     '        if parts.scheme != "https" or (parts.hostname or "").lower() != self._host() \\',
     '        if parts.scheme != "https" \\',
     T + "::test_a_repository_on_another_host_is_not_read_with_this_credential"),

    # ── Azure Repos ─────────────────────────────────────────────────────────────────────────────
    ("an optional policy counts as protection", ADO,
     "                    and _policy_applies(c, repository_id, ref) and _policy_blocks(c)]",
     "                    and _policy_applies(c, repository_id, ref)]",
     T + "::test_azure_counts_only_what_blocks_a_pull_request"),

    ("a repository setting counts as requiring a pull request", ADO,
     "        pr_required = bool(types & _PULL_REQUEST_POLICIES)",
     "        pr_required = bool(types)",
     T + "::test_azure_counts_only_what_blocks_a_pull_request"),

    ("a merge-commit strategy reads as linear history", ADO,
     '    if settings.get("allowNoFastForward") is True or '
     'settings.get("allowRebaseMerge") is True:',
     "    if False:",
     T + "::test_azure_history_is_linear_only_without_merge_commits"),

    ("a branch with no policy reads force pushes as blocked", ADO,
     "                                force_push_blocked=True if pr_required else None,",
     "                                force_push_blocked=True,",
     T + "::test_azure_reads_a_branch_with_no_policy_as_open"),

    ("auto-complete is assumed on, a pass nobody read", ADO,
     "                                auto_merge_enabled=None)",
     "                                auto_merge_enabled=True)",
     T + "::test_a_fully_protected_azure_branch_is_unknown_for_c_branch_never_pass"),

    ("an unreadable policy listing reads as an open branch", ADO,
     '            log.info("could not read the branch policies of %s (%s)", target, '
     "str(exc)[:160])\n            return None",
     '            log.info("could not read the branch policies of %s (%s)", target, '
     "str(exc)[:160])\n"
     "            return BranchProtection(pr_required=False, linear_history=False)",
     T + "::test_azure_policies_that_could_not_be_read_are_no_answer"),

    ("a PAT's scopes are claimed as granted nothing", ADO,
     '                 "the credential of %s is granted is not read", self.repo)\n'
     "        return None",
     '                 "the credential of %s is granted is not read", self.repo)\n'
     "        return frozenset()",
     T + "::test_azure_never_reads_a_credential_s_scopes_and_says_so_without_asking"),

    # ── the controls ────────────────────────────────────────────────────────────────────────────
    ("a None read of the credential's grants passes", CONTROLS,
     "        if p.permissions is None:\n            results.append(UNKNOWN)",
     "        if p.permissions is None:\n            results.append(PASS)", T),

    ("a row that cannot say which grants reach the CI passes", CONTROLS,
     "        if not p.ci_permissions:\n            results.append(UNKNOWN)",
     "        if not p.ci_permissions:\n            results.append(PASS)",
     T + "::test_c_workflows"),

    ("a credential that can write workflows passes", CONTROLS,
     "        if reach:\n            results.append(FAIL)",
     "        if False:\n            results.append(FAIL)", T + "::test_c_workflows"),

    ("a None read of the branch protection passes", CONTROLS,
     "            if got is None:\n                results.append(UNKNOWN)",
     "            if got is None:\n                results.append(PASS)", T),

    ("a fact nobody read passes", CONTROLS,
     "            results.append(FAIL if off else UNKNOWN if unread else PASS)",
     "            results.append(FAIL if off else PASS)", T + "::test_c_branch"),

    ("a fact read as off is only unknown", CONTROLS,
     "            results.append(FAIL if off else UNKNOWN if unread else PASS)",
     "            results.append(UNKNOWN if off or unread else PASS)", T + "::test_c_branch"),

    ("a None read of the releases passes", CONTROLS,
     "        return UNKNOWN, (f\"the platform's published releases could not be read",
     "        return PASS, (f\"the platform's published releases could not be read", T),

    ("the latest release is the first one listed", CONTROLS,
     "    published = sorted({v for v in map(_release, r.releases) if v}, reverse=True)",
     "    published = [v for v in map(_release, r.releases) if v]", T + "::test_c_version"),

    ("the release before the latest fails", CONTROLS,
     "    if len(published) > 1 and running == published[1]:",
     "    if False:", T + "::test_c_version"),

    ("a development build or a candidate counts as a release", CONTROLS,
     '_RELEASE = re.compile(r"v?(\\d+)\\.(\\d+)\\.(\\d+)")',
     '_RELEASE = re.compile(r"v?(\\d+)\\.(\\d+)\\.(\\d+).*")', T + "::test_c_version"),

    # ── the pack ────────────────────────────────────────────────────────────────────────────────
    ("the forge is never asked", PACK,
     "    if forge is not None:\n        reading.permissions = credential_permissions_of(forge)",
     "    if False:\n        reading.permissions = credential_permissions_of(forge)", CMD),

    ("the releases are never read", PACK,
     "        releases = _releases(forges)",
     "        releases = None",
     T + "::test_a_deployment_whose_forge_answers_everything_is_certified_from_it"),

    ("a foreign repository is asked about the default repository's branch", PACK,
     '    return branch_protection_of(forge, branch, repo="" if repo.default else repo.identity)',
     '    return branch_protection_of(forge, branch, repo="")',
     T + "::test_every_repository_is_asked_where_it_lives"),

    ("the forge is asked with a stored credential only, never the job's provider", PACK,
     "                           token_provider=None if token else "
     "deployment_forge_provider(project))",
     "                           token_provider=None)",
     T + "::test_the_job_s_credential_is_the_one_asked__an_app_deployment_reads_its_installation"),

    ("the releases home is not the package's Repository URL", PACK,
     '        if label.strip().lower() == "repository":',
     '        if label.strip().lower() == "homepage":',
     T + "::test_the_releases_home_is_the_package_s_own_repository_url"),
]
