"""What people wrote on the pull request reaches the adjust pass, without being retyped (#330).

Run:  .venv/bin/python tools/mutate.py tools/mutations/330_a_reviewers_comments_reach_the_pass.py

Row 1 is the defect as it would ship without the signal: the job drops `address`. Rows 2-5 break
the pass: the forge's words not asked for, not read, read and nothing standing still launched, and
the pull request not told what the pass took. Rows 6-7 make "could not look" read as "nothing to
do". Rows 8-12 break the two rows' listings: resolved threads, the platform's own comments, a
withdrawn request, a closed Azure thread, the factory's own Azure comment. Row 13 spends a pass the
verb should have refused. Rows 14-15 unbound the brief. Row 16 offers the verb on every forge.
"""

TEST = "tests/test_a_reviewers_comments_reach_the_pass.py"

WF = "openfactory/runtime/temporal/workflow.py"
ACT = "openfactory/runtime/temporal/activities.py"
BASE = "openfactory/adapters/forge/base.py"
GH = "openfactory/adapters/forge/github.py"
ADO = "openfactory/adapters/forge/azure_devops.py"
CAT = "openfactory/actions/catalog.py"
BRIEF = "openfactory/review/threads.py"
REG = "openfactory/adapters/forge/registry.py"

MUTATIONS = [
    ("THE GAP: the job drops `address`, and the answer reports success and does nothing", WF,
     '        if answer in ("merge", "adjust", "address", "discard", "review"):',
     '        if answer in ("merge", "adjust", "discard", "review"):'),

    ("the job sends an empty instruction instead of asking for the comments", WF,
     # re-pinned 2026-10-04: the input also carries which change of the card it is (#448)
     'source=REVIEW_THREAD if threads else "", by=who,\n',
     'source="", by=who,\n'),

    ("the pass never reads the pull request", ACT,
     "    if inp.source == REVIEW_THREAD:\n",
     "    if False:\n"),

    ("a pull request with nothing standing still launches an agent", ACT,
     "    if isinstance(found, CommentsNotListed) or not found:\n",
     "    if isinstance(found, CommentsNotListed):\n"),

    ("the pull request is not told which comments the pass took", ACT,
     "    _say_on_the_pull_request(forge, inp.pr_url, threads.what_was_carried(\n"
     "        carried, by=inp.by, pass_number=inp.attempt))\n",
     ""),

    ("a row that keeps no comments answers an empty list, which reads as nothing to do", BASE,
     '        return CommentsNotListed(f"{name} keeps no review comments this platform can read")',
     "        return []"),

    ("a read that failed answers an empty list", BASE,
     '        return CommentsNotListed(f"{name} could not list the review comments on this pull "\n'
     '                                 f"request ({str(exc)[:160]})")',
     "        return []"),

    ("GitHub carries threads somebody already resolved", GH,
     '            if thread.get("isResolved"):\n',
     "            if False:\n"),

    ("GitHub carries the platform's own comments", GH,
     '                if c.get("viewerDidAuthor") or not str(c.get("body") or "").strip():',
     '                if not str(c.get("body") or "").strip():'),

    ("GitHub carries a request for changes its author has since withdrawn", GH,
     'if r.get("viewerDidAuthor") or not who or r.get("state") == "COMMENTED":',
     'if r.get("viewerDidAuthor") or not who or r.get("state") != "CHANGES_REQUESTED":'),

    ("Azure DevOps carries threads somebody marked fixed", ADO,
     '            if thread.get("isDeleted") or str(thread.get("status") or "") not in '
     'self._STANDING:',
     '            if thread.get("isDeleted"):'),

    ("Azure DevOps carries the factory's own comments", ADO,
     "                        or (me and author.get(\"id\") == me)\n",
     ""),

    ("the verb spends a pass on a pull request with nothing standing", CAT,
     "    if not comments:\n        return refused(CONFLICT, f\"#{issue}: nothing people wrote",
     "    if False:\n        return refused(CONFLICT, f\"#{issue}: nothing people wrote"),

    ("one pass carries every comment, however many", BRIEF,
     "        if len(carried) >= MAX_COMMENTS or used + len(block) > MAX_CHARS:\n",
     "        if False:\n"),

    ("one long comment crowds out the rest", BRIEF,
     "        if len(body) > MAX_ONE:\n",
     "        if False:\n"),

    ("the verb is offered on a forge that keeps no comments", REG,
     '    return callable(getattr(forge, "review_comments", None))',
     "    return True"),
]
