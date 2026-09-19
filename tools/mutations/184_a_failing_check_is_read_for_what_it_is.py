"""#184, proven by breaking it — a failing forge check is read for what it IS.

The port answered one word for "the PR's checks" and the merge watch turned `failure` into a code
repair. On a live Azure DevOps deployment a rejected OPTIONAL policy, with no build anywhere, cost
two agent passes over an empty log and parked the card `CI still failing`.

FIVE CLAIMS:

  1. **The table decides, once, for every forge.** Only a blocking check that could be about the
     code, WITH a failing log, is repaired; a blocking process check or a red check with nothing
     to act on is asked about; a non-blocking check never changes the path.
  2. **Each forge's rows say what its checks are** — Azure DevOps by `isBlocking` and the policy
     TYPE, GitHub by `--required` and whether the check is one of the repository's own workflows
     — and Azure's failing log comes from the build the red evaluation names, not from a second
     source that can disagree with the verdict.
  3. **A row that never heard of this keeps working**, read from its aggregate as `unknown`; and a
     test double is not a declaration.
  4. **Nothing is launched unless the table says repair** — asked again at the point of action,
     so a job that arrives on the old one-word verdict is held to it too.
  5. **The watch asks instead of repairing, and jobs already in it replay what they recorded.**
     The marker row is red through a REAL replay: a history recorded on the pre-marker arm, put
     back through `Replayer`.

The guard is `tests/test_a_failing_check_is_read_for_what_it_is.py`.
"""

TEST = "tests/test_a_failing_check_is_read_for_what_it_is.py"

CHECKS = "openfactory/contracts/checks.py"
ADO = "openfactory/adapters/forge/azure_devops.py"
GITHUB = "openfactory/adapters/forge/github.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
#: RE-PINNED 2026-09-19: the gate the repair asks moved here so the box goes through it too
#: (`184_the_repair_brief_states_the_failure_it_was_given.py`). Same lines, new home.
REPAIRABLE = "openfactory/runtime/repairable.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
VIEW = "openfactory/runtime/temporal/view.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── claim 1: the table ────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF, IN THE TABLE: a check that cannot stop the merge is counted as a gate",
     CHECKS,
     "    blocking = [c for c in checks if c.blocking and c.bucket != SKIP]\n",
     "    blocking = [c for c in checks if c.bucket != SKIP]\n"),

    ("a red check with no failure log is handed to a repair anyway — the blind pass", CHECKS,
     "    fixable = [c for c in failing if c.kind != PROCESS and c.evidence.strip()]\n",
     "    fixable = [c for c in failing if c.kind != PROCESS]\n"),

    ("a check only a person settles is repaired as soon as a log arrives beside it", CHECKS,
     "    fixable = [c for c in failing if c.kind != PROCESS and c.evidence.strip()]\n",
     "    fixable = [c for c in failing if c.evidence.strip()]\n"),

    ("the question does not carry the row's remedy, so the person is told a name and no way out",
     CHECKS,
     '            f"forge" + (f": {\' \'.join(remedies)}" if remedies else "."))\n',
     '            f"forge.")\n'),

    ("a truthy non-bool is read as `blocking`, and a missing one as advisory", CHECKS,
     "        blocking=blocking if isinstance(blocking, bool) else True,\n",
     "        blocking=bool(blocking),\n"),

    # ── claim 2: the rows ─────────────────────────────────────────────────────────────────────
    ("Azure DevOps: an optional policy is a red gate again in the aggregate", ADO,
     "               for e in evaluations if _policy_blocks(e)]\n",
     "               for e in evaluations]\n"),

    ("Azure DevOps: every policy says it blocks, whatever `isBlocking` says", ADO,
     "    return blocking if isinstance(blocking, bool) else True\n",
     "    return True\n"),

    ("Azure DevOps: a work-item policy is read as a build somebody can fix", ADO,
     "        return \"unknown\"\n    return \"process\"\n",
     "        return \"unknown\"\n    return \"code\"\n"),

    ("Azure DevOps: a status some other service posted claims to be about the code", ADO,
     "    if type_id == _STATUS_POLICY:\n        return \"unknown\"\n",
     "    if type_id == _STATUS_POLICY:\n        return \"code\"\n"),

    ("Azure DevOps: the log is read from the branch's builds again, not the build the verdict "
     "named", ADO,
     "        failed: list[dict] = [{\"id\": build_id} for build_id in named]\n",
     "        failed: list[dict] = []\n"),

    ("Azure DevOps: a process policy carries no remedy", ADO,
     "            if kind == \"process\":\n",
     "            if kind == \"never\":\n"),

    ("GitHub: every check is `blocking`, so an advisory e2e gates the merge", GITHUB,
     '             "blocking": r.get("name") in required,\n',
     '             "blocking": True,\n'),

    ("GitHub: a status another app posted claims to be one of the repository's workflows", GITHUB,
     '             "kind": "code" if str(r.get("workflow") or "").strip() else "unknown",\n',
     '             "kind": "code",\n'),

    ("GitHub: the failing log is read from the DEFAULT repository's runs (C-18), so a red build "
     "on a card routed elsewhere has no evidence and is asked about instead of repaired", GITHUB,
     "        repo = self._repo_of_pr(pr)\n        runs = self._gh([\n",
     "        repo = self.repo\n        runs = self._gh([\n"),

    ("GitHub: an unreadable answer reads as `no checks`", GITHUB,
     '            raise RuntimeError(f"gh pr checks failed: {_redact(p.stderr)}")\n',
     "            return []\n"),

    # ── claim 3: a row that never heard of this ───────────────────────────────────────────────
    ("an add-on's untyped rows are trusted as if it had declared them", CHECKS,
     '    return getattr(forge, "checks_are_typed", False) is True\n',
     "    return True\n"),

    ("any truthy answer is a declaration, so a mock forge is a typed one", CHECKS,
     '    return getattr(forge, "checks_are_typed", False) is True\n',
     '    return bool(getattr(forge, "checks_are_typed", False))\n'),

    ("a verdict outside the port's four reads as green", CHECKS,
     '        return [Check(name="the forge\'s checks", bucket=PENDING, state=verdict)]\n',
     '        return [Check(name="the forge\'s checks", bucket=PASS, state=verdict)]\n'),

    # ── claim 4: the point of action ──────────────────────────────────────────────────────────
    ("the repair launches whatever the table says", ACTIVITIES,
     "        if held is not None:\n            return held\n",
     "        if held is not None:\n            pass\n"),

    ("an unreadable forge is repaired blind instead of held", REPAIRABLE,
     "    if decision is not None and decision.action == REPAIR:\n",
     "    if decision is None or decision.action == REPAIR:\n"),

    ("the repair's own hold loses the mark, so a resume pays for a whole agent pass", REPAIRABLE,
     "                     merge_refused=True, code_changed=False, note=note), \"\"\n",
     "                     code_changed=False, note=note), \"\"\n"),

    ("the old activity goes back to the forge's one-word aggregate", ACTIVITIES,
     "    return (await read_ci_checks(inp)).verdict\n",
     "    forge = _forge_for(ProjectRegistry().get(inp.project))\n"
     "    return await asyncio.to_thread(lambda: forge.pr_ci_status(pr=inp.pr_url))\n"),

    # ── claim 5: the watch ────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF, IN THE WATCH: a check to ask about is sent to the repair", WORKFLOW,
     '                        "asked" if asked.action == ASK else asked.verdict)\n',
     "                        asked.verdict)\n"),

    ("the new read is not behind its marker, so a job already in the watch cannot replay",
     WORKFLOW,
     '                if workflow.patched("checks-are-read-for-what-they-are"):\n',
     "                if True:\n"),

    ("the watch does not keep what the repair's hold refers to, so the resume re-runs the agent",
     WORKFLOW,
     "                    if rep.merge_refused:\n",
     "                    if False:\n"),

    # ── the panel ─────────────────────────────────────────────────────────────────────────────
    ("the job detail hands the forge's rows through untyped", VIEW,
     "            return checks.as_rows([c for c in map(checks.from_row, rows) if c is not None])\n",
     "            return rows\n"),

    ("the panel draws an advisory check as a red gate", PANEL,
     '<span class="badge ${adv?"b-dim":(_CIB[c.bucket]||"b-dim")}"',
     '<span class="badge ${(_CIB[c.bucket]||"b-dim")}"'),
]
