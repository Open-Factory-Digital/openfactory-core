"""The operator's central standards, and the five ways they quietly stop applying (#318).

EVERY ROW HERE ENDS IN A RUNNING FACTORY. That is the whole reason the plan exists: this feature
has no crash to regress into. A deployment whose standards silently stop reaching the agent looks
exactly like one whose standards are applied — the jobs run, the gates pass, the pull requests
open, and the only witness is a rule the organisation wrote down that no change follows. The
ticket was filed against precisely that shape (*"every such job runs without the organisation's
standards and NOTHING fails: the agent simply knows less"*), so a guard that does not bite would
reproduce the defect inside the fix.

ROWS 1-2 ARE CONTAINMENT, which is the security half: these documents are read into the prompt,
so a link out of the configured directory puts whatever it points at in front of the model. Row 1
cuts the check itself; row 2 cuts the *audibility* of the half that is refused silently — the
in-bounds link `os.walk(followlinks=False)` will not descend. Row 2 is the one this plan was
opened for, from the review of PR #328: the posture was already right and the silence was the
defect.

ROWS 3-5 ARE THE TIERS CEASING TO MEAN ANYTHING while every call site still works — the order
reversed so the deployment outranks the project, the on-demand tier inlined into every prompt,
and the misconfiguration warning removed so a directory nobody populated reads as a directory
nobody needed.
"""

TEST = "tests/test_operator_guidelines.py"

MUTATIONS = [
    # ── containment: what reaches the prompt ────────────────────────────────────────────────────
    ("the containment check is cut, so a symlink under the operator directory pointing at "
     "/etc/passwd is resolved, read, and inlined into the prompt of every job on the deployment",
     "openfactory/orchestrator/operator_guidelines.py",
     "    if cand == root_r or not cand.is_relative_to(root_r):",
     "    if False:"),

    ("an IN-BOUNDS symlinked subtree goes back to being skipped in silence: the walk still refuses "
     "to follow it — which is correct — but the operator is no longer told, so documents they "
     "placed and linked are absent from the index with nothing saying why (review of #328)",
     "openfactory/orchestrator/operator_guidelines.py",
     "                if _contained(root, sub) is not None:\n"
     "                    _log.warning(\n"
     "                        \"operator reference %s is a symlink and is NOT descended, so the "
     ".md \"\n"
     "                        \"files under it are not indexed — this walk never follows a link, "
     "even \"\n"
     "                        \"one that stays inside %s. Move those documents under %s, or point "
     "%s \"\n"
     "                        \"at the directory that really holds them.\", sub, root, ref_root, "
     "ENV_VAR)",
     "                _contained(root, sub)"),

    # ── the tiers stop meaning anything, while everything still runs ─────────────────────────────
    ("the two tiers swap, so the DEPLOYMENT outranks the project instead of the other way round: "
     "a repository that deliberately replaces a central rule is overruled by the central one, and "
     "the manifest's last word — the property the cascade is built on — is gone",
     "openfactory/orchestrator/context.py",
     "    guidelines = _org_defaults(profile, repo_path,\n"
     "                               {p.name for p in operator.guideline_docs})\n"
     "    guidelines += _resolve_tier(operator.guideline_docs, profile, repo_path,\n"
     "                                source=\"operator's own\")",
     "    guidelines = _resolve_tier(operator.guideline_docs, profile, repo_path,\n"
     "                               source=\"operator's own\")\n"
     "    guidelines += _org_defaults(profile, repo_path,\n"
     "                                {p.name for p in operator.guideline_docs})",
     "tests/test_context.py"),

    ("`reference/` is inlined instead of indexed, so a long central standard ships in full on "
     "every job — the cost the on-demand tier exists to avoid, and the one that walks straight "
     "back into the argv ceiling that parked this ticket's own first run",
     "openfactory/orchestrator/operator_guidelines.py",
     "    guideline_docs = _contained_md(root, list(root.glob(\"*.md\")))",
     "    guideline_docs = _contained_md(root, list(root.glob(\"*.md\"))"
     " + list((root / REFERENCE_SUBDIR).glob(\"*.md\")))"),

    # ── the on-demand tier the agent must be able to OPEN (review of #328) ──────────────────────
    ("the index goes back to labelling a reference document relative to the operator directory, "
     "so the agent opens nothing — the label resolves inside the CHECKOUT, where it finds either "
     "no such file or, when the project has a `reference/` of its own, the wrong one entirely",
     "openfactory/orchestrator/context.py",
     "            index_lines += [\n"
     "                f\"{reference_root.rstrip('/')}/\"\n"
     "                f\"{operator_guidelines.reference_label(operator.dir, p)} — "
     "{_doc_summary(p)}\"\n"
     "                for p in operator.reference_docs\n"
     "            ]",
     "            index_lines += [\n"
     "                f\"{operator_guidelines.reference_label(operator.dir, p)} — "
     "{_doc_summary(p)}\"\n"
     "                for p in operator.reference_docs\n"
     "            ]",
     "tests/test_context.py"),

    ("a box that cannot reach the directory has its documents indexed anyway, which is the worse "
     "half of the same defect: the agent spends a tool call on a path that resolves nowhere and "
     "reads it as a document somebody deleted",
     "openfactory/orchestrator/context.py",
     "    if operator.dir is not None and operator.reference_docs:\n        if reference_root:",
     "    if operator.dir is not None and operator.reference_docs:\n        if True:",
     "tests/test_context.py"),

    ("the worktree box stops answering where the directory is, so a deployment on the one-machine "
     "door indexes nothing and the on-demand tier silently does not exist",
     "openfactory/adapters/sandbox/worktree.py",
     "        try:\n            return str(Path(host_dir).resolve())\n        except OSError:\n"
     "            return None",
     "        return None",
     "tests/test_the_box_says_where_the_operator_guidelines_are.py"),

    ("the container mounts the operator's standards WRITABLE, so a job can rewrite the rules the "
     "next job on this deployment is given",
     "openfactory/adapters/sandbox/container.py",
     '            run_cmd += ["-v", f"{self.guidelines}:{GUIDELINES_MOUNT}:ro"]',
     '            run_cmd += ["-v", f"{self.guidelines}:{GUIDELINES_MOUNT}"]',
     "tests/test_the_box_says_where_the_operator_guidelines_are.py"),

    ("a container asked about a directory it did NOT mount answers with the mount point anyway, "
     "so the index sends the agent to another organisation's standards",
     "openfactory/adapters/sandbox/container.py",
     "            if Path(self.guidelines).resolve() != Path(host_dir).resolve():\n"
     "                return None",
     "            pass",
     "tests/test_the_box_says_where_the_operator_guidelines_are.py"),

    # ── the journal note says which standards a change was written against ───────────────────────
    ("the note counts a REPLACED central rule as applied, so the one fact it exists to state — "
     "which standards this change was written against — is wrong exactly when a project "
     "deliberately differs from the organisation",
     "openfactory/orchestrator/operator_guidelines.py",
     "    swapped = _substitutions(profile, tier, repo_path)",
     "    swapped = {}",
     "tests/test_operator_guidelines.py"),

    ("a replacement whose file is missing from the checkout reads as replaced, when "
     "`_resolve_tier` kept the ORIGINAL — the same defect in the other direction",
     "openfactory/orchestrator/operator_guidelines.py",
     "        doc = _inside_checkout(repo_path, substitute)\n        if doc is not None and "
     "doc.is_file():\n            out[name] = substitute",
     "        out[name] = substitute",
     "tests/test_operator_guidelines.py"),

    ("a profile that addresses a name BOTH tiers carry stops being warned about, so one `waive:` "
     "drops two documents and reads as though it dropped one",
     "openfactory/orchestrator/context.py",
     "    _warn_if_a_name_lives_in_both_tiers(profile, operator)",
     "    pass",
     "tests/test_context.py"),

    ("a directory that is configured and not there stops warning, so a typo in "
     "OPENFACTORY_GUIDELINES_DIR reads exactly like a deployment that never configured one: "
     "every job runs without the organisation's standards and nothing says so",
     "openfactory/orchestrator/context.py",
     "    if operator.missing:",
     "    if False:",
     "tests/test_context.py"),
]
