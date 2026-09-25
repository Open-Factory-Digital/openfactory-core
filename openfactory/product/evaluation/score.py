"""Three verdicts on one answer — correct, cited, abstained correctly — and the totals.

EACH VERDICT SAYS WHO DECIDED IT. A score is only worth what the reader can trust about how it
was reached, and "the model judged it right" is a weaker statement than "the answer contains `7
days`". So every verdict carries `decided_by`:

    deterministic    a string comparison over the answer — reproducible, free, exact
    judge            a model read the answer against the key (a `claim`, or an abstention the
                     phrase list could not see)
    not applicable   nothing to decide: an answer whose right form is "I do not know" cites nothing
    undecided        the judge was needed and gave no readable ruling — counted apart, never as a
                     pass and never as a fail

THE JUDGE IS ASKED ONLY WHAT A STRING CANNOT ANSWER, and at most once per answer:

  - a `claim` fact, or a `claim` under `must_not` — a meaning, which only a reader can find;
  - whether the answer abstained, but ONLY when the phrase list's reading would count against the
    role: it found no "I do not know" where one was expected, or found one where an answer was.
    The phrase list is a shortcut, the way the product role's own gesture regexes are (role.py,
    QUEUE_MARKER): when it agrees with the key it decides, and when it disagrees a missing word
    costs a model call rather than a wrong score.

CITED IS WHAT THE PERSON SEES. The role is told to point at the requirement NUMBER behind a claim
and never at a documentation path (`ProductRole.answer`), and to name the code file it read — so a
requirement file is cited by `REQ-0002`, `REQ-2` or "requirement 2", and any other source by its
path inside its repository, its file name, or a spelling the question names in `cited_as`. The
role's own evidence marker is stripped before a person reads the reply, and so it counts for
nothing here either.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from pydantic import BaseModel

from openfactory.product.corpus import _FILE_RE as _REQUIREMENT_FILE
from openfactory.product.evaluation.battery import Claim, Question, Source, Spellings

log = logging.getLogger("openfactory.product.evaluation")

DETERMINISTIC, JUDGE = "deterministic", "judge"
NOT_APPLICABLE, UNDECIDED = "not applicable", "undecided"

#: A judge: the prompt in, the model's text out — or None when the run failed. The runner binds a
#: harness to this shape; the scorer never builds one, so it runs with no model at all.
Judge = Callable[[str], str | None]

#: "I do not know", in the spellings the role actually uses, in the two languages it answers in.
#: Read over `plain` text: lower case, accents gone, one kind of apostrophe.
_ABSTENTION = re.compile("|".join([
    r"\bi (?:do not|don't|dont) know\b",
    r"\bi (?:cannot|can not|can't|cant) (?:tell|say|find|confirm)\b",
    r"\bi (?:could not|couldn't|couldnt) find\b",
    r"\b(?:is|are|was|were) not (?:documented|specified|defined|recorded|decided|written down)\b",
    r"\b(?:isn't|aren't|wasn't|weren't) (?:documented|specified|defined|recorded|decided"
    r"|written down)\b",
    r"\bno (?:record|information|mention) of\b",
    r"\bnothing (?:written|documented|recorded) (?:about|on)\b",
    r"\bnao sei\b",
    r"\bnao (?:encontrei|consegui encontrar|consigo dizer|tenho essa informacao)\b",
    r"\bnao (?:esta|foi|estao|foram) (?:documentad|definid|especificad|registrad|decidid)[oa]s?\b",
    r"\bnao ha (?:registro|informacao|nada escrito)\b",
]))

_TYPOGRAPHY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                             "–": "-", "—": "-", "*": ""})


def plain(text: str) -> str:
    """The text as the comparisons read it: accents and case gone, one apostrophe, one space.

    Markdown emphasis goes too — `**7** days` is `7 days` to the person reading it."""
    flat = unicodedata.normalize("NFKD", text or "")
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", flat.translate(_TYPOGRAPHY).casefold()).strip()


def says(answer: str, spelling: str) -> bool:
    """Whether the answer carries this spelling as a whole — `7 days` is not in `17 days`."""
    want = plain(spelling)
    if not want:
        return False
    return re.search(rf"(?<![0-9a-z]){re.escape(want)}(?![0-9a-z])", plain(answer)) is not None


def cites(answer: str, source: Source) -> bool:
    """Whether the answer cites `source` in a form a person would recognise (see the module)."""
    inside = source.path.split("/", 1)[1]
    if any(says(answer, form) for form in (inside, PurePosixPath(inside).name, *source.cited_as)):
        return True
    named = _REQUIREMENT_FILE.match(PurePosixPath(inside).name)
    if not (source.path.startswith("context/") and named):
        return False
    number = int(named.group("num"))
    return re.search(rf"(?<![0-9a-z])(?:req|requirement|requisito)s?[ #:.-]*0*{number}(?![0-9])",
                     plain(answer)) is not None


def abstains_by_phrase(answer: str) -> bool:
    return _ABSTENTION.search(plain(answer)) is not None


class Verdict(BaseModel):
    """One verdict: `passed` is None when it does not apply or could not be decided."""

    passed: bool | None
    decided_by: str
    why: str = ""


class Scored(BaseModel):
    """The three verdicts on one answer, and what the answer did."""

    correct: Verdict
    cited: Verdict
    abstained_correctly: Verdict
    #: whether the answer said it does not know — None when that could not be decided
    abstained: bool | None


@dataclass(frozen=True)
class _Ruling:
    """What the judge said, item by item, in the order it was asked."""

    states: tuple[bool, ...] = ()
    asserts: tuple[bool, ...] = ()
    abstains: bool | None = None


def judge_prompt(question: Question, answer: str, *, claims: list[str], forbidden: list[str],
                 abstention: bool) -> str:
    """What the judge is asked. Only the sections this answer needs, and one JSON object back."""
    parts = [
        "You are checking ONE answer against an answer key. Do not answer the question yourself, "
        "and do not open any file: everything you need is below.",
        "",
        "## The question that was asked",
        question.question,
        "",
        "## The answer being checked (between the two lines of dashes)",
        "----------",
        answer.strip() or "(the answer was empty)",
        "----------",
    ]
    shape: list[str] = []
    if claims:
        parts += ["", "## Statements",
                  "For EACH statement, decide whether the answer states it — in any words, in any "
                  "language. Implied only vaguely is NOT stated."]
        parts += [f"{i}. {c}" for i, c in enumerate(claims, 1)]
        shape.append(f'"states": [{len(claims)} booleans, in order]')
    if forbidden:
        parts += ["", "## Forbidden statements",
                  "For EACH statement, decide whether the answer ASSERTS it as true. Mentioning "
                  "it only to deny it, or to say it is not known, is not asserting it."]
        parts += [f"{i}. {c}" for i, c in enumerate(forbidden, 1)]
        shape.append(f'"asserts": [{len(forbidden)} booleans, in order]')
    if abstention:
        parts += ["", "## Abstention",
                  "Decide whether the answer, INSTEAD of answering, says that it does not know, "
                  "cannot tell, or that the information is not available. An answer that gives "
                  "the answer and also mentions something it could not check did NOT abstain."]
        shape.append('"abstains": true or false')
    parts += ["", "Return ONLY one JSON object, no prose and no code fence: {"
              + ", ".join(shape) + "}"]
    return "\n".join(parts)


def _ruling(raw: str | None, *, claims: int, forbidden: int, abstention: bool) -> _Ruling | None:
    """The judge's JSON, checked item by item — None when any part of it cannot be read, so a
    half-read ruling is never mistaken for a whole one."""
    from openfactory.adapters.reviewer.harness import extract_json

    if not raw:
        return None
    try:
        data = json.loads(extract_json(raw))
    except (ValueError, TypeError):
        log.info("the judge did not answer in JSON: %s", raw[:200])
        return None
    if not isinstance(data, dict):
        return None
    states, asserts, abstains = data.get("states", []), data.get("asserts", []), \
        data.get("abstains")
    if claims and not (isinstance(states, list) and len(states) == claims
                       and all(isinstance(x, bool) for x in states)):
        return None
    if forbidden and not (isinstance(asserts, list) and len(asserts) == forbidden
                          and all(isinstance(x, bool) for x in asserts)):
        return None
    if abstention and not isinstance(abstains, bool):
        return None
    return _Ruling(states=tuple(states) if claims else (), asserts=tuple(asserts) if forbidden
                   else (), abstains=abstains if abstention else None)


def score(question: Question, answer: str, *, judge: Judge | None = None) -> Scored:
    """The three verdicts on `answer`. `judge` is asked at most once, and only for what the
    deterministic reading cannot decide. With no judge a claim stays `undecided`, and the phrase
    list's reading of an abstention stands — `decided_by` says so either way."""
    missing = [f.describe() for f in question.facts
               if isinstance(f, Spellings) and not any(says(answer, s) for s in f.any)]
    present = [f.describe() for f in question.must_not
               if isinstance(f, Spellings) and any(says(answer, s) for s in f.any)]
    claims = [f.claim for f in question.facts if isinstance(f, Claim)]
    forbidden = [f.claim for f in question.must_not if isinstance(f, Claim)]
    by_phrase = abstains_by_phrase(answer)
    # the phrase list decides when it agrees with the key; a disagreement is the judge's
    doubt = by_phrase != question.expect_unknown and judge is not None

    ruling: _Ruling | None = None
    asked = bool(claims or forbidden or doubt) and judge is not None
    if asked:
        prompt = judge_prompt(question, answer, claims=claims, forbidden=forbidden,
                              abstention=doubt)
        try:
            raw = judge(prompt)
        except Exception:  # noqa: BLE001 — a judge that failed is an undecided verdict, not a crash
            log.warning("the judge failed on %s", question.id, exc_info=True)
            raw = None
        ruling = _ruling(raw, claims=len(claims), forbidden=len(forbidden), abstention=doubt)

    # ── abstained: what the answer did ───────────────────────────────────────────────────────
    if not doubt:
        abstained: bool | None = by_phrase
        abstained_by = DETERMINISTIC
    else:
        abstained = ruling.abstains if ruling is not None else None
        abstained_by = JUDGE if ruling is not None else UNDECIDED

    # ── abstained correctly ─────────────────────────────────────────────────────────────────
    expected = "should have said it does not know" if question.expect_unknown \
        else "should have answered"
    if abstained is None:
        abstained_correctly = Verdict(passed=None, decided_by=UNDECIDED,
                                      why="the judge gave no readable ruling on whether it "
                                          "abstained")
    else:
        did = "said it does not know" if abstained else "answered"
        abstained_correctly = Verdict(passed=abstained == question.expect_unknown,
                                      decided_by=abstained_by, why=f"it {did}; it {expected}")

    # ── correct ─────────────────────────────────────────────────────────────────────────────
    judged_missing: list[str] = []
    judged_present: list[str] = []
    if ruling is not None:
        judged_missing = [c for c, ok in zip(claims, ruling.states, strict=True) if not ok]
        judged_present = [c for c, bad in zip(forbidden, ruling.asserts, strict=True) if bad]
    wrong = [f"missing: {m}" for m in missing] + [f"says what it must not: {p}" for p in present]
    if question.expect_unknown and abstained is False and abstained_by == DETERMINISTIC:
        wrong.append("it answered a question whose right answer is \"I do not know\"")
    if wrong:
        # a deterministic failure is final whatever the judge would say about the rest
        correct = Verdict(passed=False, decided_by=DETERMINISTIC, why="; ".join(wrong))
    elif (claims or forbidden) and ruling is None:
        correct = Verdict(passed=None, decided_by=UNDECIDED,
                          why="the judge gave no readable ruling on "
                              + ", ".join(repr(c) for c in claims + forbidden))
    elif question.expect_unknown and abstained is None:
        correct = Verdict(passed=None, decided_by=UNDECIDED,
                          why="whether it said it does not know could not be decided")
    else:
        failed = [f"missing: {m}" for m in judged_missing] + \
                 [f"says what it must not: {p}" for p in judged_present]
        if question.expect_unknown and not abstained:
            failed.append("it answered a question whose right answer is \"I do not know\"")
        needed_judge = bool(claims or forbidden) or (question.expect_unknown
                                                     and abstained_by == JUDGE)
        correct = Verdict(passed=not failed, decided_by=JUDGE if needed_judge else DETERMINISTIC,
                          why="; ".join(failed) or "every expected fact is there, and nothing "
                                                   "it must not say")

    # ── cited ───────────────────────────────────────────────────────────────────────────────
    if question.expect_unknown:
        cited = Verdict(passed=None, decided_by=NOT_APPLICABLE,
                        why="the right answer is \"I do not know\"; it cites nothing")
    else:
        uncited = [s.path for s in question.sources if not cites(answer, s)]
        cited = Verdict(passed=not uncited, decided_by=DETERMINISTIC,
                        why=("not cited: " + ", ".join(uncited)) if uncited
                        else "every expected source is cited")

    return Scored(correct=correct, cited=cited, abstained_correctly=abstained_correctly,
                  abstained=abstained)


class Tally(BaseModel):
    """One verdict, counted over the battery."""

    passed: int = 0
    failed: int = 0
    undecided: int = 0
    not_applicable: int = 0


VERDICTS = ("correct", "cited", "abstained_correctly")


def totals(scored: Iterable) -> dict[str, Tally]:
    """Each verdict counted: passed, failed, undecided, and not applicable, apart — over anything
    that carries the three verdicts, a `Scored` or a record's answer."""
    out = {name: Tally() for name in VERDICTS}
    for s in scored:
        for name in VERDICTS:
            v: Verdict = getattr(s, name)
            tally = out[name]
            if v.decided_by == NOT_APPLICABLE:
                tally.not_applicable += 1
            elif v.passed is None:
                tally.undecided += 1
            elif v.passed:
                tally.passed += 1
            else:
                tally.failed += 1
    return out
