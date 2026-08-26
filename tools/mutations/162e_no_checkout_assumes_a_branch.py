"""#162 (product/module.py:767 + the four siblings): no checkout assumes a branch name."""

TEST = "tests/test_no_checkout_assumes_a_branch_name.py"
MOD = "openfactory/product/module.py"
ACT = "openfactory/runtime/temporal/activities.py"
KNOW = "tests/test_knowledge_pipeline.py"   # where the refresh is driven BEHAVIOURALLY

MUTATIONS = [
    ("the product role's source checkout names `main` again", MOD,
     '            return RepoCache().sync(f"{self.project.name}-source", self._clone_url(repo),\n'
     '                                    load_manifest_base_branch(self.project, default=""))',
     '            return RepoCache().sync(f"{self.project.name}-source",\n'
     '                                    self._clone_url(repo), "main")'),

    ("…and the reverse: a DECLARED base branch is ignored", MOD,
     '                                    load_manifest_base_branch(self.project, default=""))',
     '                                    "")'),

    ("the baseline's checkout names `main` again", MOD,
     '        path = RepoCache().sync(f"{self.project.name}-source", url,\n'
     '                                load_manifest_base_branch(self.project, default=""))',
     '        path = RepoCache().sync(f"{self.project.name}-source", url, "main")'),

    ("the workspace is told `main` whatever it actually holds", MOD,
     '        landed = current_branch(path) or "main"',
     '        landed = "main"'),

    ("…and the reverse: an unreadable tree hands the workspace an EMPTY branch name", MOD,
     '        landed = current_branch(path) or "main"',
     "        landed = current_branch(path)"),

    ("the knowledge refresh names `main` again — it dies on its first line, silently", ACT,
     '    repo_path = RepoCache().sync(project.name, url,\n'
     '                                 load_manifest_base_branch(project, default=""))',
     '    repo_path = RepoCache().sync(project.name, url, "main")'),

    # The re-sync's own cut moved to 162f — the adversarial review showed the condition had a
    # deeper defect than the literal `main` (a schema DEFAULT read as a declaration), so the
    # claim worth cutting is the one stated there.
    ("the refresh's re-sync compares against `main` instead of what it landed on", ACT,
     "    declared = manifest.declared_base_branch     # the FILE's word, never the schema "
     "default\n    if declared and declared != current_branch(repo_path):\n"
     "        repo_path = RepoCache().sync(project.name, url, declared)",
     '    if manifest.base_branch != "main":\n'
     "        repo_path = RepoCache().sync(project.name, url, manifest.base_branch)", KNOW),

    ("the ratchet stops walking the package", TEST,
     "    for path in sorted(package.rglob(\"*.py\")):",
     "    for path in sorted(package.rglob(\"nothing-*.py\")):"),
]
