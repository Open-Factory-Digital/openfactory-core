"""The backfill's questions, and the sixteen ways they stop being finishable.

WHAT THEY WERE. `propose_context` produced questions and rendered them into a document and a pull
request body, as `list[str]` — no identity, no state, no way to know whether one was ever dealt
with. Re-run the backfill next month and the same six arrive again, indistinguishable from six new
ones.

ROW 6 IS THE ONE TO READ FIRST. A survey that could not run produces ZERO questions, and zero
questions read as "every gap is gone". A repository that became unreadable, a clone that failed, a
walk that raised — each would close every open question and the platform would stop asking about a
codebase it can no longer see. Absence of evidence arriving as evidence of absence, and here it
does not merely misreport: it ERASES the record. `surveyed=False` is the whole guard, and row 7 is
its positive twin, because a version that simply never closed anything would satisfy row 6
perfectly.

ROWS 9-11 ARE A TRAP THE LEDGER ALREADY CARRIES A SCAR FOR. `followup.answered()` closes every open
`QUESTION` whose `subject:about` is absent from the board's live findings — closing by ABSENCE. A
question about a codebase has no board finding at all, so sharing that kind would close it on the
very next product sweep, minutes after it was opened, and would also eat the product's own
three-question budget. `DECISION` exists in `KINDS` for exactly this reason and says so; this is the
second instance.

ROWS 12-13 CUT THE OTHER WAY: the version that refuses to close anything, and the version that
tracks a question it can never re-derive and therefore chases for ever.
"""

TEST = "tests/test_the_backfills_questions_can_be_finished.py"

MUTATIONS = [
    # ── identity ────────────────────────────────────────────────────────────────────────────────
    ("questions go back to being text with no code, so nothing can be tracked, deduplicated or "
     "closed and the loop has no subject",
     "openfactory/onboarding/context.py",
     "    proposal.tracked = _survey_questions(survey_result, w)\n"
     "    proposal.questions = [q.text for q in proposal.tracked]",
     "    proposal.tracked = []\n"
     "    proposal.questions = [q.text for q in _survey_questions(survey_result, w)]"),

    ("the identity is bought by dropping the agenda: the tracked questions stop reaching the "
     "document and the pull request body a person actually reads",
     "openfactory/onboarding/context.py",
     "    proposal.questions = [q.text for q in proposal.tracked]",
     "    proposal.questions = []"),

    ("deduplication moves to the TEXT, so the same gap re-derived with different wording opens a "
     "second loop and a person is chased about what they are already looking at",
     "openfactory/onboarding/questions.py",
     "    already = {loop.about for loop in waiting",
     '    already = {loop.context.get("text", "") for loop in waiting'),

    ("questions are deduplicated across repositories, so `blind-modules` on the API silences the "
     "same gap on the front end — one deployment, many projects, one question",
     "openfactory/onboarding/questions.py",
     "               if loop.kind == CONTEXT and loop.subject == repo and loop.waiting}",
     "               if loop.kind == CONTEXT and loop.waiting}"),

    ("a CLOSED question can never be asked again, so a module that loses its description a second "
     "time is a gap nobody will ever mention",
     "openfactory/onboarding/questions.py",
     "    already = {loop.about for loop in waiting\n"
     "               if loop.kind == CONTEXT and loop.subject == repo and loop.waiting}",
     "    already = {loop.about for loop in waiting\n"
     "               if loop.kind == CONTEXT and loop.subject == repo}"),

    # ── the guard this whole change is arranged around ──────────────────────────────────────────
    ("A SURVEY THAT COULD NOT RUN CLOSES EVERYTHING. Zero questions from a failed survey read as "
     "\"every gap is gone\", so a repository that became unreadable has its entire record erased "
     "and the platform stops asking about a codebase it can no longer see",
     "openfactory/onboarding/questions.py",
     "    if not surveyed:\n        return {}",
     "    if False:\n        return {}"),

    ("nothing is ever closed — the over-cautious twin, which satisfies the guard above perfectly "
     "and leaves a list that only grows until everyone learns to ignore it",
     "openfactory/onboarding/questions.py",
     "    earned = {q.code for q in fresh}",
     "    earned = {q.code for q in fresh} | set(CODES)"),

    ("the outcome claims somebody ANSWERED, which this pass never observed and cannot know — it "
     "saw a gap close, and a ledger that records a reply it did not see is the one thing this "
     "store exists to refuse",
     "openfactory/onboarding/questions.py",
     'GAP_CLOSED = "gap-closed"',
     'GAP_CLOSED = "answered"'),

    # ── the kind, and the scar the ledger already carries ───────────────────────────────────────
    ("context questions share the product's `QUESTION` kind, so `followup.answered()` closes every "
     "one of them on the next sweep — absent from the board means resolved, and a codebase "
     "question is always absent from the board",
     "openfactory/onboarding/questions.py",
     "    return [open_loop(CONTEXT, repo, owner=\"onboarding\", ts=ts, about=q.code,",
     "    return [open_loop(QUESTION, repo, owner=\"onboarding\", ts=ts, about=q.code,"),

    ("the same, one layer down: `CONTEXT` collapses onto `QUESTION` in the ledger itself",
     "openfactory/memory/ledger.py",
     'CONTEXT = "context"',
     'CONTEXT = "question"'),

    ("`resolved` stops filtering by kind, so a product QUESTION and a tech-lead REMEDY are closed "
     "by a survey that knows nothing about either",
     "openfactory/onboarding/questions.py",
     "            if loop.kind == CONTEXT and loop.subject == repo and loop.waiting\n"
     "            and loop.about not in earned}",
     "            if loop.subject == repo and loop.waiting\n"
     "            and loop.about not in earned}"),

    # ── THE OTHER DIRECTION ─────────────────────────────────────────────────────────────────────
    ("OVER-TIGHTENED — the ledger's closed set of kinds is opened, so a kind nobody knows how to "
     "close can be recorded and the row stays open for ever, slowly teaching everyone to ignore "
     "the list. The refusal is what forced `CONTEXT` to be added with its observation written down",
     "openfactory/memory/ledger.py",
     '    if kind not in KINDS:\n        raise ValueError(',
     "    if False:\n        raise ValueError("),

    ("OVER-TIGHTENED — every question is tracked, the model's included. Their wording drifts, so "
     "each pass opens a fresh loop for a gap already open and chases a person about a question "
     "they answered last month; nothing can re-derive them, so nothing can ever close them",
     "openfactory/onboarding/context.py",
     "                proposal.questions = demoted + model_questions + proposal.questions",
     "                proposal.questions = demoted + model_questions + proposal.questions\n"
     "                proposal.tracked = proposal.tracked + [\n"
     "                    SurveyQuestion(q[:24], q) for q in demoted + model_questions]"),

    # ── the closer has to be REACHABLE, which the repository's own guard already demands ────────
    # `test_loops_are_reachable::test_EVERY_kind_has_a_reachable_closer` refuses a kind whose
    # closer no live path calls, and CONTEXT failed it until `carry` was wired into `_backfill`.
    # That is the honest order: the kind exists because something closes it.
    ("`carry` opens loops and never closes any, so the list only grows — which the ledger's own "
     "docstring calls worse than not tracking at all",
     "openfactory/onboarding/questions.py",
     "    closed = close_by_observation(\n"
     "        mine, resolved(mine, repo=repo, fresh=fresh, surveyed=surveyed))",
     "    closed = []"),

    # ROW REWRITTEN. The first version handed `carry` the whole ledger and SURVIVED — because
    # `resolved` and `to_open` each filter by kind and repository themselves, so the narrowing in
    # `carry` changes nothing observable. The claim in the docstring was wrong, not the code; it
    # now says what the line is actually for (naming the kind where the reachability guard can see
    # it) rather than pretending to be a safety net two layers already provide.
    ("`carry` closes and never opens, so a gap that appears after the first pass is never asked "
     "about — the mirror of the row above, and the half a person would notice last",
     "openfactory/onboarding/questions.py",
     "    return closed + to_open(fresh, repo=repo, waiting=mine, ts=ts)",
     "    return closed"),

    ("the backfill stops carrying its questions at all, so they are computed with an identity and "
     "then dropped — the same sentences on paper, and nothing in the ledger",
     "openfactory/onboarding/onboard.py",
     "        _carry_questions(project, proposal, surveyed=True)",
     "        pass"),
]
