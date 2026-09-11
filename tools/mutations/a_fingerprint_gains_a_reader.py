"""The checker: `ConceptSource.fingerprint` gains its first reader, and the reader must be right.

ADR-0045's measurement — two writers, zero readers — is closed by `knowledge/check.py`. A checker
that exists and is wrong is worse than the promise it replaces, because a reader now TRUSTS the
verdict. So every row below makes the checker lie in one specific way, and the guard file must see
each lie.

ROWS 1-2 ARE THE CORE: the comparison itself. A hash compared the wrong way round, or a moved
file called fresh, is a checker that never invalidates anything — which is exactly the state before
it existed, with a green light on top.

ROW 3 IS THE ASYMMETRY THAT MATTERS TO A READER: "missing" and "stale" are repaired differently,
and a checker that collapses them sends the reader to re-read a file that is not there.

ROW 4 IS THE WORST-OF RULE, AND IT SURVIVED THE FIRST RUN. Taking the FIRST source's verdict
instead of the worst makes a concept with one fresh citation and one moved one read as fresh —
half-supported claims presented whole. The first guard for it moved `billing/refunds.py` and left
`billing/rules.py` alone, and the mutant passed it: `_verified_rules` returns sources SORTED BY
PATH, so the moved file happened to be first and "first" agreed with "worst". A guard whose fixture
puts the weak source where the wrong rule would also find it is decoration. The guard now moves
`rules.py`, which sorts last, and asserts the order it depends on — so the two rules disagree and
only the right one is green.

ROW 5 IS THE HONESTY OF ABSENCE: an unverifiable source counted as fresh turns "we could not
measure" into "we measured and it holds", the failure this repository names by memory.

ROWS 6-7 ARE THE WIRING. A checker nobody calls is the previous state with more code; a gap that
is computed and not returned is the tech-lead reading a stale bundle as current.

ROW 8 IS THE EXIT CODE, which is the whole point of a separate pass: a CI hook reads nothing else.
"""

TEST = "tests/test_a_fingerprint_gains_a_reader.py"

MUTATIONS = [
    ("the hash comparison is inverted, so a moved file is fresh and an unchanged one is stale",
     "openfactory/knowledge/check.py",
     "    if actual != fingerprint:",
     "    if actual == fingerprint:"),

    ("a moved file is called fresh — the checker never invalidates anything, which is the state "
     "before it existed with a green light on top",
     "openfactory/knowledge/check.py",
     "        return SourceCheck(rel, STALE,\n"
     "                           f\"bytes moved: recorded {fingerprint[:12]}…, now {actual[:12]}…\")",
     "        return SourceCheck(rel, FRESH)"),

    ("a file that is gone is reported as stale, sending the reader to re-read a file that is not "
     "there",
     "openfactory/knowledge/check.py",
     '        return SourceCheck(rel, MISSING, "not in this checkout")',
     '        return SourceCheck(rel, STALE, "not in this checkout")'),

    ("the concept takes its FIRST source's verdict instead of the worst, so one fresh citation "
     "hides a moved one",
     "openfactory/knowledge/check.py",
     "        verdict = max((c.verdict for c in checks), key=_SEVERITY.__getitem__, default=UNSOURCED)",
     "        verdict = checks[0].verdict if checks else UNSOURCED"),


    ("a directory source — the fallback when no citation survived — is called missing, so the "
     "concept is broken on every refresh and re-authored, paid for, forever",
     "openfactory/knowledge/check.py",
     '        return SourceCheck(rel, UNVERIFIABLE, "a directory — no verified citation to hash")',
     '        return SourceCheck(rel, MISSING, "a directory — no verified citation to hash")'),

    ("a source with no fingerprint is counted as fresh — 'we could not measure' becomes 'we "
     "measured and it holds'",
     "openfactory/knowledge/check.py",
     '        return SourceCheck(rel, UNVERIFIABLE, "no fingerprint was recorded when this was written")',
     '        return SourceCheck(rel, FRESH)'),

    ("the tech-lead fetches the bundle and never checks it — the previous state with more code",
     "openfactory/techlead/conversation.py",
     "    report = check_concepts(got.path, source)",
     "    report = check_concepts(got.path / 'nowhere', source)"),

    ("the gap is computed and not returned, so a stale bundle reaches the pack as current",
     "openfactory/techlead/conversation.py",
     "    return got.path, [gap] if gap else []",
     "    return got.path, []"),

    ("the separate pass reports and exits 0 regardless, so a CI hook can never refuse on it",
     "openfactory/cli.py",
     "    if not report.holds:\n        raise typer.Exit(code=1)",
     "    if not report.holds:\n        pass"),
]
