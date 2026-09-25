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

    ("a directory that is configured and not there stops warning, so a typo in "
     "OPENFACTORY_GUIDELINES_DIR reads exactly like a deployment that never configured one: "
     "every job runs without the organisation's standards and nothing says so",
     "openfactory/orchestrator/context.py",
     "    if operator.missing:",
     "    if False:",
     "tests/test_context.py"),
]
