"""Mutation plan for #266 slice 0 — the product role's evaluation battery (ADR-0051 decision 9).

Each row takes one rule away: a verdict (correct, cited, abstained correctly), the empty-battery
refusal, the runner's one door, or the rule that the battery never runs inside `make test`. Every
row must turn tests/test_the_evaluation_battery.py red.
"""

TEST = "tests/test_the_evaluation_battery.py"
SCORE = "openfactory/product/evaluation/score.py"
RUN = "openfactory/product/evaluation/run.py"
MAKEFILE = "Makefile"

MUTATIONS = [
    # ── correct ──────────────────────────────────────────────────────────────────────────────
    ("correct: a fact the answer leaves out no longer counts", SCORE,
     "if isinstance(f, Spellings) and not any(says(answer, s) for s in f.any)]",
     "if False]"),
    ("correct: saying what it must not no longer counts", SCORE,
     "if isinstance(f, Spellings) and any(says(answer, s) for s in f.any)]",
     "if False]"),
    ("correct: `7 days` is found inside `17 days`", SCORE,
     'return re.search(rf"(?<![0-9a-z]){re.escape(want)}(?![0-9a-z])", plain(answer)) is not None',
     "return want in plain(answer)"),
    ("correct: a claim the judge says is missing still passes", SCORE,
     "judged_missing = [c for c, ok in zip(claims, ruling.states, strict=True) if not ok]",
     "judged_missing = []"),
    ("correct: a forbidden claim the judge finds still passes", SCORE,
     "judged_present = [c for c, bad in zip(forbidden, ruling.asserts, strict=True) if bad]",
     "judged_present = []"),
    ("correct: a claim the judge could not rule on passes instead of staying undecided", SCORE,
     "elif (claims or forbidden) and ruling is None:",
     "elif False:"),
    # ── cited ────────────────────────────────────────────────────────────────────────────────
    ("cited: every answer counts as cited", SCORE,
     "uncited = [s.path for s in question.sources if not cites(answer, s)]",
     "uncited = []"),
    ("cited: naming a requirement's number does not cite it", SCORE,
     'if not (source.path.startswith("context/") and named):',
     "if True:"),
    ("cited: REQ-0020 cites requirement 2", SCORE,
     "0*{number}(?![0-9])",
     "0*{number}"),
    ("cited: an answer that should be \"I do not know\" is held to citations", SCORE,
     "cited = Verdict(passed=None, decided_by=NOT_APPLICABLE,",
     "cited = Verdict(passed=True, decided_by=DETERMINISTIC,"),
    # ── abstained correctly ──────────────────────────────────────────────────────────────────
    ("abstained correctly: the phrase list is never read", SCORE,
     "by_phrase = abstains_by_phrase(answer)",
     "by_phrase = False"),
    ("abstained correctly: the key is ignored — every abstention is right", SCORE,
     "abstained_correctly = Verdict(passed=abstained == question.expect_unknown,",
     "abstained_correctly = Verdict(passed=True,"),
    ("abstained correctly: a phrase reading that counts against the role is never sent to the "
     "judge", SCORE,
     "doubt = by_phrase != question.expect_unknown and judge is not None",
     "doubt = False"),
    ("abstained correctly: an abstention the judge could not rule on is taken as the key's", SCORE,
     "abstained = ruling.abstains if ruling is not None else None",
     "abstained = ruling.abstains if ruling is not None else question.expect_unknown"),
    # ── the empty battery ────────────────────────────────────────────────────────────────────
    ("an empty battery runs instead of refusing with the sentence", RUN,
     "if not battery.questions:",
     "if False:"),
    # ── through the one door, a conversation per question ────────────────────────────────────
    ("the runner asks the module around the turn engine", RUN,
     "replies = engine.turn(project, message, module=module)",
     "replies = [engine.Reply(text=module.answer(q.question).text)]"),
    ("every question shares one conversation", RUN,
     'conversation=f"evaluation-{q.id}"',
     'conversation="evaluation"'),
    # ── never inside `make test` ─────────────────────────────────────────────────────────────
    ("a live run inside the suite is no longer refused", RUN,
     "if (agent is None or judge is None) and _under_test():",
     "if False:"),
    ("the refusal no longer sees that pytest is running", RUN,
     'return bool(os.environ.get("PYTEST_CURRENT_TEST"))',
     "return False"),
    ("`make test` runs the battery", MAKEFILE,
     "\tpython -m pytest -q\n",
     "\tpython -m pytest -q && python -m openfactory.product.evaluation\n"),
    ("`make check` reaches the battery", MAKEFILE,
     "check: test lint ## test + lint (what deploy runs first)",
     "check: test lint eval-product ## test + lint (what deploy runs first)"),
    ("`make eval-product` no longer runs the battery", MAKEFILE,
     "\tpython -m openfactory.product.evaluation\n",
     "\t@echo the battery\n"),
]
