"""The question file: what the battery asks, and what a right answer has to contain.

TWO AUTHORS, ONE FILE (ADR-0051, decision 9). The product owner writes the questions — the id,
the text, who is asking. The implementer writes what a right answer is: the facts it must carry,
the ones it must not, the sources it must cite, or that "I do not know" is the right answer. So a
question can exist before its expected answer does, and that state is REFUSED BY NAME rather than
scored: a question with no expectation scored as a wrong answer would put the implementer's
unfinished half into the role's score.

THREE SHAPES OF FACT, because the scorer has two ways to decide and the author knows which one a
fact allows:

    7 days                          as written — deterministic, case, accents and spacing ignored
    any: [due date, overdue]        one of several spellings — deterministic
    claim: it goes out a week late  a meaning, in any words — only a judge model can decide it

A number, a name, a code identifier is a spelling; "the owner is told" is a meaning. Writing the
second as the first makes a right answer fail on a synonym, and writing the first as the second
spends a model call on what a string comparison answers exactly.

SOURCES ARE PATHS IN THE FIXTURE, and a path the fixture does not hold is refused when the file is
loaded — a typo in an expected source would otherwise fail every answer to that question as
uncited, and the score would blame the role for it.

NEVER RAISES ANYTHING BUT `BatteryRefused`, whose message is the sentence a person reads: the file,
the question and what to change.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

#: Who is asking (decision 8). Client is the default because it is who the role meets most.
Audience = Literal["client", "product admin", "engineer"]
AUDIENCES: tuple[str, ...] = ("client", "product admin", "engineer")

#: The two repositories of a fixture, as the first segment of every source path.
REPOSITORIES = ("context", "source")

#: What the runner says, and exits non-zero on, when the file holds no question. Exact, because it
#: is the sentence that tells whoever ran it whose move it is.
NO_QUESTIONS = "the battery has no questions yet; the product owner writes them (decision 9)"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class BatteryRefused(ValueError):
    """The question file cannot be run, with the sentence that says why."""


def _spelling(value: object) -> object:
    """A spelling as its author typed it. YAML reads `- 50` as an integer, and "50" is what the
    person meant, so a number is kept as its text. It reads a bare `yes`, `no`, `true` or `false`
    as a boolean, and no spelling of that is the one the author typed — so it is refused, not
    guessed."""
    if isinstance(value, bool):
        raise ValueError(f"`{str(value).lower()}` unquoted is a YAML boolean, not a spelling — "
                         f"put it in quotes")
    return str(value) if isinstance(value, int | float) else value


def _spellings(values: object) -> object:
    return [_spelling(v) for v in values] if isinstance(values, list) else values


class Spellings(BaseModel):
    """A fact the answer must carry in one of these spellings. A bare string is one spelling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    any: list[str] = Field(min_length=1)

    @field_validator("any", mode="before")
    @classmethod
    def _typed(cls, v: object) -> object:
        return _spellings(v)

    @field_validator("any")
    @classmethod
    def _no_blank(cls, v: list[str]) -> list[str]:
        spelled = [s.strip() for s in v]
        if not all(spelled):
            raise ValueError("a spelling is empty")
        return spelled

    def describe(self) -> str:
        return " | ".join(self.any)


class Claim(BaseModel):
    """A fact the answer must state in any words — the one shape only a judge model decides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: str = Field(min_length=1)

    def describe(self) -> str:
        return self.claim


Fact = Spellings | Claim


def _as_fact(value: object) -> object:
    """A bare spelling is a fact of one spelling — the shape a person writes most often."""
    value = _spelling(value)
    return {"any": [value]} if isinstance(value, str) else value


class Source(BaseModel):
    """A file the answer must cite, and any extra spellings that count as citing it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    cited_as: list[str] = Field(default_factory=list)

    @field_validator("cited_as", mode="before")
    @classmethod
    def _typed(cls, v: object) -> object:
        return _spellings(v)

    @field_validator("path")
    @classmethod
    def _in_a_repository(cls, v: str) -> str:
        v = v.strip().strip("/")
        if v.split("/", 1)[0] not in REPOSITORIES or "/" not in v or ".." in v.split("/"):
            raise ValueError(f"{v!r} is not a path in the fixture — it starts with "
                             f"{' or '.join(f'`{r}/`' for r in REPOSITORIES)}")
        return v


class Question(BaseModel):
    """One question, and — once the implementer has written it — what a right answer is."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    question: str = Field(min_length=1)
    audience: Audience = "client"
    facts: list[Fact] = Field(default_factory=list)
    must_not: list[Fact] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    expect_unknown: bool = False

    @field_validator("id")
    @classmethod
    def _id_shape(cls, v: str) -> str:
        if not _ID_RE.match(v or ""):
            raise ValueError(f"{v!r} is not an id: lowercase letters, digits and hyphens")
        return v

    @field_validator("facts", "must_not", mode="before")
    @classmethod
    def _facts(cls, v: object) -> object:
        return [_as_fact(x) for x in v] if isinstance(v, list) else v

    @field_validator("sources", mode="before")
    @classmethod
    def _sources(cls, v: object) -> object:
        return [{"path": x} if isinstance(x, str) else x for x in v] if isinstance(v, list) else v

    @model_validator(mode="after")
    def _an_expectation(self) -> Question:
        if self.expect_unknown:
            # "I do not know" carries no fact and cites nothing; a fact here would make the right
            # answer fail for leaving it out
            if self.facts or self.sources:
                raise ValueError("a question whose right answer is \"I do not know\" "
                                 "(`expect_unknown: true`) lists no facts and no sources — the "
                                 "tempting wrong answers go under `must_not`")
            return self
        if not self.facts and not self.sources:
            raise ValueError("it has no expected answer yet — its facts and sources, or "
                             "`expect_unknown: true`, are the implementer's to write "
                             "(decision 9)")
        if not self.facts:
            raise ValueError("it names sources and no fact — list what the answer must say")
        if not self.sources:
            raise ValueError("it lists facts and no source — name the file a right answer cites")
        return self


class Battery(BaseModel):
    """Every question in one file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    questions: list[Question] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> Battery:
        seen: set[str] = set()
        for q in self.questions:
            if q.id in seen:
                raise ValueError(f"the id {q.id!r} is used twice — a result row is found by it")
            seen.add(q.id)
        return self


def _where(errors: list, data: dict) -> str:
    """The first error's place, said as the question's id when there is one."""
    first = errors[0] if errors else {}
    loc = list(first.get("loc", ()))
    if len(loc) >= 2 and loc[0] == "questions" and isinstance(loc[1], int):
        try:
            qid = data["questions"][loc[1]].get("id") or f"#{loc[1] + 1}"
        except (AttributeError, IndexError, KeyError, TypeError):
            qid = f"#{loc[1] + 1}"
        field = next((str(p) for p in loc[2:] if isinstance(p, str)), "")
        return f"question {qid!r}" + (f" at `{field}`" if field else "")
    return ".".join(str(p) for p in loc) or "the file"


def load_battery(path: str | Path, *, fixture: str | Path | None = None) -> Battery:
    """The battery in `path`, validated — against `fixture` too when given, so every expected
    source is a file the fixture really holds.

    Raises `BatteryRefused` with one sentence naming the file and the question."""
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BatteryRefused(f"{path} could not be read: {exc}") from exc
    except yaml.YAMLError as exc:
        raise BatteryRefused(f"{path} is not valid YAML: {str(exc)[:300]}") from exc
    if not isinstance(data, dict):
        raise BatteryRefused(f"{path} must be a mapping with a `questions:` list, not "
                             f"{type(data).__name__}")
    try:
        battery = Battery(**data)
    except ValidationError as exc:
        errors = exc.errors()
        msg = str(errors[0].get("msg", "invalid")).removeprefix("Value error, ") if errors else ""
        raise BatteryRefused(f"{path}: {_where(errors, data)} is refused: {msg}") from exc
    if fixture is not None:
        root = Path(fixture)
        for q in battery.questions:
            missing = [s.path for s in q.sources if not (root / s.path).is_file()]
            if missing:
                raise BatteryRefused(
                    f"{path}: question {q.id!r} expects a citation of {', '.join(missing)}, which "
                    f"is not a file in the fixture at {root} — an expected source nobody can cite "
                    f"would fail every answer to it as uncited")
    return battery
