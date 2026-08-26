"""#162 (activities.py:616): the base branch is asked, never assumed.

The reverses matter as much as the fix: `""` must mean "nobody said", not "ignore what the caller
asked for", and an unnamed sync must not throw away a working checkout on every round.
"""

TEST = "tests/test_the_base_branch_is_asked_not_assumed.py"
CACHE = "openfactory/runtime/repo_cache.py"
LOADER = "openfactory/loader.py"
ACT = "openfactory/runtime/temporal/activities.py"
FACTORY = "openfactory/factory.py"
ONBOARD = "openfactory/onboarding/propose_manifest.py"

MUTATIONS = [
    # ── the weld ────────────────────────────────────────────────────────────────────────────────
    ("the preflight clones the literal `main` again", ACT,
     '    asked = load_manifest_base_branch(project, default="")',
     '    asked = "main"'),

    ("the repo fetch falls back to `main` again", FACTORY,
     '                                load_manifest_base_branch(project, default=""))',
     "                                load_manifest_base_branch(project))"),

    ("the helper's unknown becomes `main` whatever the caller asked for", LOADER,
     "    return named or default", '    return named or "main"'),

    # ── the cache ───────────────────────────────────────────────────────────────────────────────
    ("an unnamed sync clones a branch called nothing", CACHE,
     '                    rc, out = _git(["clone", *(["--branch", base_branch] '
     'if base_branch else []),\n                                    clone_url, str(master)])',
     '                    rc, out = _git(["clone", "--branch", base_branch, clone_url, '
     "str(master)])"),

    ("…and the reverse: a NAMED branch is ignored, every sync lands on the default", CACHE,
     '                    rc, out = _git(["clone", *(["--branch", base_branch] '
     'if base_branch else []),\n                                    clone_url, str(master)])',
     '                    rc, out = _git(["clone", clone_url, str(master)])'),

    # The remote-vs-cache cuts live in 162f, whose TEST file holds their guards — this plan
    # predates `remote_default_branch` existing.

    ("a detached HEAD reads as a branch called HEAD", CACHE,
     '    return named if (rc == 0 and named and named != "HEAD") else ""',
     '    return named or ""'),

    ("a tree that is not a checkout is asked anyway", CACHE,
     '    if not (at / ".git").exists():   # modules and one of them stores them as text\n'
     '        return ""', "    pass"),

    # ── the re-sync comparison ──────────────────────────────────────────────────────────────────
    ("the re-sync compares against the literal `main` again", ACT,
     "    declared = manifest.declared_base_branch\n"
     "    if declared and declared != current_branch(repo_path):\n"
     "        repo_path = RepoCache().sync(cache_key, url, declared)",
     '    if manifest.base_branch != "main":\n'
     "        repo_path = RepoCache().sync(cache_key, url, manifest.base_branch)"),

    # ── one home ────────────────────────────────────────────────────────────────────────────────
    ("onboarding grows its own copy of the git question back", ONBOARD,
     "    from openfactory.runtime.repo_cache import current_branch\n\n"
     '    return current_branch(checkout) or "main"',
     '    rc, out = _git(["-C", str(checkout), "rev-parse", "--abbrev-ref", "HEAD"])\n'
     '    named = (out or "").strip().splitlines()[0].strip() if out else ""\n'
     '    return named if (rc == 0 and named and named != "HEAD") else "main"'),

    ("…and the reverse: its own unknown stops being `main`, so a proposal names nothing", ONBOARD,
     '    return current_branch(checkout) or "main"', "    return current_branch(checkout)"),
]
