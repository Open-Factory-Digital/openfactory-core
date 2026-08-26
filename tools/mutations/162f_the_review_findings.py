"""#162, second pass: what the adversarial review measured (2026-08-20).

Seventeen confirmed findings, five lenses converging on one root cause — a pydantic DEFAULT read as
a client's declaration. The reverses matter as much as the fixes: `""` must mean "nobody said",
never "ignore the file".
"""

TEST = "tests/test_no_checkout_assumes_a_branch_name.py"
KNOW = "tests/test_knowledge_pipeline.py"
MANIFEST = "openfactory/contracts/manifest.py"
PRODUCT = "openfactory/contracts/product.py"
CACHE = "openfactory/runtime/repo_cache.py"
ACT = "openfactory/runtime/temporal/activities.py"
LOADER = "openfactory/product/loader.py"
MOD = "openfactory/product/module.py"

MUTATIONS = [
    # ── the root cause: a default read as a declaration ─────────────────────────────────────────
    ("the manifest cannot tell a declared base branch from its schema default", MANIFEST,
     '        return self.base_branch if "base_branch" in self.declared_keys() else ""',
     "        return self.base_branch"),

    ("…and the reverse: it reports nothing even when the file DOES declare one", MANIFEST,
     '        return self.base_branch if "base_branch" in self.declared_keys() else ""',
     '        return ""'),

    ("the refresh reads the default as a declaration again", ACT,
     "    declared = manifest.declared_base_branch     # the FILE's word, never the schema default",
     "    declared = manifest.base_branch", KNOW),

    ("the preflight does too", ACT,
     "    declared = manifest.declared_base_branch\n"
     "    if declared and declared != current_branch(repo_path):",
     "    declared = manifest.base_branch\n"
     "    if declared and declared != current_branch(repo_path):"),

    # ── the cache answered from itself, not from the repository ─────────────────────────────────
    ("an unnamed sync is answered from the CACHE — a moved default branch is served for ever",
     CACHE, "                wanted = base_branch or remote_default_branch(clone_url) "
     "or current_branch(master)",
     "                wanted = base_branch or current_branch(master)", KNOW),

    ("an unnamed sync has NO fallback when the remote will not answer", CACHE,
     "                wanted = base_branch or remote_default_branch(clone_url) "
     "or current_branch(master)",
     "                wanted = base_branch or remote_default_branch(clone_url)"),

    ("…and the reverse: an unreachable remote throws away a working checkout", CACHE,
     "    rc, out = _git([\"ls-remote\", \"--symref\", clone_url, \"HEAD\"])\n"
     "    if rc != 0:\n"
     '        return ""',
     '    rc, out = _git(["ls-remote", "--symref", clone_url, "HEAD"])\n'
     '    if rc != 0:\n        raise RuntimeError("unreachable")'),

    ("the reclone reuses a name inferred from the tree it has just deleted", CACHE,
     '                    rc, out = _git(["clone", *(["--branch", base_branch] if base_branch '
     'else []),\n                                    clone_url, str(master)])',
     '                    rc, out = _git(["clone", *(["--branch", wanted] if wanted else []),\n'
     "                                    clone_url, str(master)])"),

    ("the symref answer is parsed as the whole line", CACHE,
     '            return line.split("refs/heads/", 1)[1].split()[0].strip()',
     "            return line.strip()"),

    # ── the docs repo, the site the sweep wrongly excluded ──────────────────────────────────────
    ("the docs branch reads its default as a declaration", PRODUCT,
     '        return self.docs_branch if "docs_branch" in self.model_fields_set else ""',
     "        return self.docs_branch"),

    ("the loader stops asking and names `main` for every context repo", LOADER,
     "                          cfg.declared_docs_branch)", '                          "main")'),

    # ── the baseline's declared half ────────────────────────────────────────────────────────────
    ("the baseline ignores a declared base branch", MOD,
     '        path = RepoCache().sync(f"{self.project.name}-source", url,\n'
     '                                load_manifest_base_branch(self.project, default=""))',
     '        path = RepoCache().sync(f"{self.project.name}-source", url, "")'),

    # ── the guards themselves ───────────────────────────────────────────────────────────────────
    ("the refresh harness invents a manifest that declares `main`", KNOW,
     '    declared = {"base_branch": base_branch} if base_branch else {}',
     '    declared = {"base_branch": base_branch or "main"}', KNOW),

    ("the ratchet's argument extraction is neutered", TEST,
     "            branch = node.args[2] if len(node.args) > 2 else next(\n"
     '                (k.value for k in node.keywords if k.arg == "base_branch"), None)',
     "            branch = None"),

    ("the ratchet stops walking the package", TEST,
     '    for path in sorted(package.rglob("*.py")):',
     '    for path in sorted(package.rglob("nothing-*.py")):'),
]
