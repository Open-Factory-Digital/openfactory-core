"""#267 slice 1 (the read model of the product), proven by breaking it.

FOUR CLAIMS, each cut here and each required to go red:

  1. **Spend is excluded** — by key wherever it rides, by route for the cost dashboard, and in the
     factory's own sentences about it; a cut at any of the three reaches the role's files.
  2. **Each layer is fed** — now (the floor, the jobs, their detail, their pull requests, the loops,
     the tech-lead's diagnosis), history (the whole board and its columns, the finished jobs, the
     version in production), meaning (the bodies, the threads, the requirements, who asked) — and
     the product is the union of its registry projects and nothing else.
  3. **The guard discovers the panel's routes itself** — by path, by query parameter, and by what
     a person opens on them; a stream it cannot read is withheld whole or it is a hole.
  4. **Nobody is named across conversations** — the withholding of known people, of private
     conversations' keys, of the people only a loop knows; the requester said as a relation; the
     speaker named only in a view of the turn's own.

The guard under test is `tests/test_the_read_model.py`, run on `tests/the_product_bed.py`.
"""

TEST = "tests/test_the_read_model.py"

MODEL = "openfactory/product/model.py"
MODULE = "openfactory/product/module.py"
GUARD = "tests/test_the_read_model.py"

MUTATIONS = [
    # ── 1. spend is excluded ───────────────────────────────────────────────────────────────────
    ("the spend entry stops naming spend keys, so a finished job's `cost_usd` enters the model "
     "and is rendered with the rest of its detail", MODEL,
     "        keys=SPEND_KEYS),",
     "        keys=()),"),

    ("the cost dashboard is no longer withheld, so the guard demands the role be shown what each "
     "pass cost and on which model", MODEL,
     '        paths=("/api/metrics:*",),',
     "        paths=(),"),

    ("the factory's own sentences about spend pass through — the pull request's `Cost:` line and "
     "the cost-ceiling park reach the files", MODEL,
     "        text = pattern.sub(said, text)",
     "        text = text"),

    ("the files leave without the spend withholding", MODEL,
     "    return scrub_credentials(scrub_spend(names.redact(text)))",
     "    return scrub_credentials(names.redact(text))"),

    # ── 2. each layer is fed ───────────────────────────────────────────────────────────────────
    ("now: the floor's verdict is never fed", MODEL,
     '    floor = (reads.get("floors") or {}).get(name)',
     "    floor = None"),

    ("now: the live jobs are never fed", MODEL,
     '        "jobs": None if unread else [scrub(r) for r in live],',
     '        "jobs": [],'),

    ("now: a job's detail — review, checks, gates, why — is never fed", MODEL,
     "        row[\"detail\"] = withhold(detail, DETAIL_ROUTE) if isinstance(detail, dict) "
     "else None",
     '        row["detail"] = None'),

    ("now: the pull requests on the floor are never read", MODEL,
     "    return {url: pull_request(forge, url) for url in urls}",
     "    return {}"),

    # RE-PINNED (slices 1–3 joined): the call now carries the conversation's agenda reader
    ("now: what waits on whom loses the ledger", MODEL,
     '        "loops": _loops_of(member, model, loops_seen),',
     '        "loops": [],'),

    ("now: the tech-lead's diagnosis is not carried with the parked job", MODEL,
     '        row["diagnosis"] = _diagnosis(threads.get(str(row.get("issue") or "")))',
     '        row["diagnosis"] = ""'),

    ("history: the board is read through the 300-card window again", MODEL,
     "    tickets, error = read_board(member, limit=0)",
     "    tickets, error = read_board(member)"),

    ("history: the board's columns are never fed", MODEL,
     '            out["columns"] = made.column_names()',
     '            out["columns"] = None'),

    ("history: the finished jobs are never fed", MODEL,
     '        "finished": None if unread else [scrub(r) for r in finished],',
     '        "finished": [],'),

    ("history: the version in production is never fed", MODEL,
     '        return {"latest_tag": forge.latest_tag()}',
     '        return {"latest_tag": None}'),

    ("meaning: the cards' threads are never fed", MODEL,
     '            cards[ref]["comments"] = thread',
     '            cards[ref]["comments"] = None'),

    ("meaning: the cards' bodies are never fed", MODEL,
     '            "updated_at": ticket.updated_at or "", "body": body,',
     '            "updated_at": ticket.updated_at or "", "body": "",'),

    ("meaning: the requirements are never fed", MODEL,
     "    model.requirements = _requirements(corpus, model)",
     "    model.requirements = None"),

    ("meaning: who asked for a card is never read off it", MODEL,
     "    requester, forge = _requester_of(member, ticket, body)",
     '    requester, forge = "", ""'),

    ("the product is one registry project, not the union of its members", MODEL,
     "    return [project, *sorted(others, key=lambda p: p.name)]",
     "    return [project]"),

    # RE-LABELLED 2026-09-24, after the plan's one full run: this row was written as "another
    # product's jobs enter this product's model" and SURVIVED, correctly — `_engine_reads` keeps
    # only the product's members, so this filter separates one MEMBER from another and never
    # another product. What it lets through is a sibling member's job under the wrong name
    # (acme-api#7 as acme-web#7), which no test pinned; `test_each_member_s_jobs_are_its_own` now
    # does. The cut the old label meant is the membership row below.
    ("a member's jobs are listed under every member of the product — acme-api#7 filed as "
     "acme-web#7", MODEL,
     '    rows = [dict(r) for r in (reads.get("jobs") or []) if r.get("project") == name]',
     '    rows = [dict(r) for r in (reads.get("jobs") or [])]'),

    # ADDED 2026-09-24 with the re-label above: another product's registry project is taken for a
    # member, and its board, jobs, loops and release enter this product's model.
    ("another product's registry project is taken for a member of this one", MODEL,
     "                  if p.name != project.name and product_key(p) == key]",
     "                  if p.name != project.name]"),

    # ── 3. the guard discovers the routes itself ───────────────────────────────────────────────
    ("the discovery forgets a route that takes the project as a query parameter", GUARD,
     '            and ("{project}" in r.path\n'
     '                 or any(q.name == "project" for q in r.dependant.query_params))]',
     '            and ("{project}" in r.path)]'),

    ("the discovery finds only the routes the project closes", GUARD,
     '            and ("{project}" in r.path\n',
     '            and (r.path.endswith("{project}")\n'),

    ("the guard never opens a card or a pull request — it reads the board without its drawer",
     GUARD,
     "    for name in names:\n        combos = [{**c, name: v} for c in combos for v in "
     "_fill(name, member)]",
     "    for name in []:\n        combos = [{**c, name: v} for c in combos for v in "
     "_fill(name, member)]"),

    ("every route reads as a stream, so nothing is walked and every one must be withheld whole",
     GUARD,
     '    return "StreamingResponse" in str(route.endpoint.__annotations__.get("return", ""))',
     "    return True"),

    # ── 4. nobody is named across conversations ────────────────────────────────────────────────
    ("a private conversation's key is rendered as it is — `person:<id>` of somebody the platform "
     "knows from nothing else", MODEL,
     '        text = _PRIVATE_KEY.sub(self._conversation, str(text or ""))',
     '        text = str(text or "")'),

    ("the known people are not withheld where they ride — a requester's id inside a card's body",
     MODEL,
     "            text = self._pattern.sub(self._person, text)",
     "            text = text"),

    ("the requester is said as whoever asked, not as a relation", MODEL,
     "        return YOUR_OWN if self.speaker and _bare(who) == _bare(self.speaker) else "
     "THEIR_REQUESTER",
     "        return who"),

    ("a person the platform knows only from a loop is not collected, so her id in a comment is "
     "rendered", MODEL,
     "        model.people.update(v for k, v in context.items() if k in PEOPLE_KEYS and v)",
     "        pass"),

    # re-pinned 2026-09-24 (#269): the same line hands the pack the documents' audience too
    ("the speaker is named as \"you\" in a view another conversation's turn may read", MODULE,
     '    return {"model": model, "speaker": module._facts_for if own else "", "audience": '
     'audience}',
     '    return {"model": model, "speaker": module._facts_for, "audience": audience}'),
]
