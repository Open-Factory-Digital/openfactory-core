"""A card the product role opens is DRAFTED, CHECKED and JUDGED before a person is asked to
confirm it (#383).

THE CARD IS THE ONLY THING THE CODING AGENT READS. The ticket gesture used to write the message that
asked for the card — "pode criar um card novo e siga para a correção" — as the card's whole body,
with the title cut at 80 characters, after a conversation in which the role had read a screenshot,
found the earlier card about the same screen and restated the defect precisely. None of that reached
the board, the person had said yes to a title, and triage then flagged the card as having nothing
that says when it is done. A product owner who files that card is failing at the one job the role
exists for.

So the gesture no longer writes what was said last. It runs one bounded loop, the one the other
judged artefacts of this platform already run (ADR-0006's review → repair):

1. **Draft** — the product role's engine writes the card as JSON from the conversation, the
   role's own reply and the triggering message, in a room with nothing to open (`in_a_room`): the
   prompt carries everything a card is written from.
2. **Floor** — deterministic checks that no rubric can switch off: a title within `TITLE_LIMIT`, a
   description that is not the request to open a card, something that says when it is done, a quote
   that was really said, and the pickup gate's own verdict on the rendered body (`spec_verdict`). A
   draft that fails the floor is redrafted without spending the judge.
3. **Judge** — a model that did not write the card scores it against the rubric: one level per
   criterion, with evidence, and any critical failure. It runs on the REVIEWER axis
   (`build_asker(role="reviewer")`), so a deployment can put it on a different engine from the
   product role — a judge sharing its author's model shares its blind spots.
4. **Verdict in code** — the average, the floor and the critical failures are computed here, never
   by the model, so a verdict is one a person can recompute from the scores in the log.
5. **One redraft** with the floor's problems or the judge's findings. A second failure files
   nothing: the role asks the person the question the judge said is missing.

A card that clears is shown WHOLE in the confirmation, so the yes approves the body that will be
written — the trust contract the defect path already keeps with its restatement.

THE BAR IS THE PRODUCT'S. The template and the rubric ship in `org_defaults/cards/`; a product
replaces either by committing `cards/template.md` or `cards/rubric.yaml` to its context repository
(`product.docs_repo`) — or `cards/template.<language>.md`, one per language it speaks (#429).
A card is product guidance — a product of N source repositories has one
context repository, which is where the role already reads and writes requirements. A file that
cannot be used is refused by name in the log and the shipped one is used instead.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from openfactory.util.bounded import BoundedDict

log = logging.getLogger(__name__)

#: THE BOUND ON A CARD'S TITLE, told to the role and checked before anything is staged. It used to
#: be a blind `[:80]` applied twice (the gesture and `file_ticket`), so a title the person had
#: confirmed reached the board cut mid-word. Nothing slices it now: a longer title is a floor
#: problem and the draft is asked again.
TITLE_LIMIT = 80

#: One draft, and one redraft with what the floor or the judge found — ADR-0006's bound. A third try
#: at the same conversation is a loop; what is missing then is information only the person has.
ATTEMPTS = 2

#: The phases of the two model calls, metered like every other product call.
DRAFT_PHASE = "product_card_draft"
JUDGE_PHASE = "product_card_judge"

#: The judge's axis. Not the product role's own: see this module's docstring, step 3.
JUDGE_ROLE = "reviewer"

#: Where a product's own template and rubric live, relative to its context repository.
OVERRIDE_DIR = "cards"
TEMPLATE_FILE = "template.md"
#: THE TWO KINDS OF CARD THE ROLE WRITES, each with its own template (#392): a card a person asked
#: for, and a defect — reality disagreeing with a promise. The same loop, the same rubric; the
#: layout differs where the card's readers look for different sections (`module._WHAT_WAS_ASKED`).
_TEMPLATES = {"ticket": TEMPLATE_FILE, "defect": "defect-template.md"}
_SECTION_OF = {"ticket": "request", "defect": "defect"}
#: THE LAYOUT IS WRITTEN IN A LANGUAGE, AND THE MODEL WRITES IN THE LAYOUT'S (#429). The shipped
#: templates were Portuguese only: a project speaking English got English frames around a card
#: whose headings — and, following them, every sentence the drafter wrote — were Portuguese. So a
#: template exists per language, `template.<language>.md` beside the unsuffixed one, which is in
#: `voice.DEFAULT_LANGUAGE`; a language with no file of its own gets the default's.
RUBRIC_FILE = "rubric.yaml"

_DEFAULTS = Path(__file__).resolve().parent.parent / "org_defaults" / OVERRIDE_DIR

#: The fields a draft carries and a template may place — the whole vocabulary of `{name}`.
FIELDS = ("objective", "description", "done_when", "out_of_scope", "related", "source_quote")

Judge = Callable[[str], "str | None"]


# ── the draft ───────────────────────────────────────────────────────────────────────────────────

@dataclass
class CardDraft:
    """What the role wrote for one card — the JSON it answered, typed."""

    title: str = ""
    objective: str = ""
    description: str = ""
    done_when: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    source_quote: str = ""
    questions: list[str] = field(default_factory=list)

    @classmethod
    def from_answer(cls, raw: dict | None) -> CardDraft | None:
        """The draft in `raw`, or None when the answer carried none — never a half-typed default
        that would look like a card somebody wrote."""
        if not isinstance(raw, dict):
            return None

        def text(key: str) -> str:
            value = raw.get(key)
            return " ".join(str(value).split()) if isinstance(value, (str, int, float)) else ""

        def items(key: str) -> list[str]:
            value = raw.get(key)
            if not isinstance(value, list):
                return []
            out = []
            for item in value:
                if isinstance(item, dict):
                    # `related` may come as {ref, why}: said as one line, the reference first
                    ref = str(item.get("ref") or "").strip()
                    why = str(item.get("why") or "").strip()
                    item = f"{ref} — {why}" if ref and why else (ref or why)
                line = " ".join(str(item).split())
                if line:
                    out.append(line)
            return out

        draft = cls(title=text("title"), objective=text("objective"),
                    description=str(raw.get("description") or "").strip(),
                    done_when=items("done_when"), out_of_scope=items("out_of_scope"),
                    related=items("related"), source_quote=text("source_quote"),
                    questions=items("questions"))
        return draft if (draft.title or draft.description) else None


def render(draft: CardDraft, template: str) -> str:
    """The card's markdown: `template` with each `{field}` filled — and every section whose fields
    are all empty left out, so a card with nothing out of scope has no empty heading saying so.

    A SECTION is a `## ` heading and what follows it up to the next one. Text before the first
    heading is kept as it is."""
    values = {
        "objective": draft.objective or draft.title,
        "description": draft.description,
        "done_when": "\n".join(f"- {c}" for c in draft.done_when),
        "out_of_scope": "\n".join(f"- {c}" for c in draft.out_of_scope),
        "related": "\n".join(f"- {c}" for c in draft.related),
        "source_quote": "\n".join(f"> {line}" for line in draft.source_quote.splitlines()
                                  if line.strip()),
    }
    kept = []
    for section in _sections(template):
        named = _placeholders(section)
        if named and not any(values.get(n, "").strip() for n in named):
            continue
        kept.append(_fill(section, values))
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip() + "\n"


def _sections(template: str) -> list[str]:
    return [part for part in re.split(r"(?m)^(?=## )", template) if part]


def _placeholders(text: str) -> list[str]:
    return re.findall(r"\{([a-z_]+)\}", text)


def _fill(section: str, values: dict[str, str]) -> str:
    # NOT `str.format`: a template is a product's own file, and a literal brace in its prose (a
    # JSON example, a set) must be text, not a KeyError that loses the card
    return re.sub(r"\{([a-z_]+)\}", lambda m: values.get(m.group(1), m.group(0)), section)


# ── the floor: what no rubric can switch off ───────────────────────────────────────────────────

def _said(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def floor(draft: CardDraft, body: str, *, request: str, conversation: str,
          described: bool = True, language: str | None = None) -> list[str]:
    """What is wrong with `draft` before any model looks at it — `[]` when nothing is.

    Written for the drafting model to read on its redraft, so each problem says what to change."""
    from openfactory.adapters.tracker.parse import parse_ticket_body
    from openfactory.orchestrator.machine import spec_verdict

    problems = []
    if not draft.title:
        problems.append("the card has no title")
    elif len(draft.title) > TITLE_LIMIT:
        problems.append(f"the title has {len(draft.title)} characters; the limit is {TITLE_LIMIT} "
                        f"— write a shorter one, never a cut one")
    description = _said(draft.description)
    if not described:
        # A CARD OF A REQUIREMENT CARRIES NO DESCRIPTION OF ITS OWN (#392): its objective and its
        # criteria are the work, and the requirement it cites is the rest. The echo check goes
        # with the description check, and on purpose: there is no message here for a card to
        # echo — the instruction to break the requirement down is ours. Whether the card is
        # faithful to its front of the requirement is the judge's to score (`REQUIREMENT_NOTE`).
        pass
    elif not description:
        problems.append("the card has no description of the work")
    elif description == _said(request) or len(description) < 20:
        # THE DEFECT THIS MODULE EXISTS FOR: the message that asked for the card, as the card
        problems.append("the description is the request to open the card, not a description of "
                        "the work — say what was observed or asked for, where and under which "
                        "conditions, as the conversation established it")
    if not draft.done_when:
        problems.append("nothing says when the work is done — write the observable behaviour the "
                        "conversation said 'fixed' means")
    if draft.source_quote and _said(draft.source_quote) not in _said(f"{conversation}\n{request}"):
        # A QUOTE IS PROVENANCE: attributed words somebody did not say are an invented source
        problems.append("the quote in source_quote is not in the conversation — quote the "
                        "person's words exactly, or leave it empty")
    refused = spec_verdict(parse_ticket_body(id="draft", title=draft.title, body=body, repo=""))
    if refused:
        problems.append(f"the factory's pickup gate would refuse this card: {refused}")
    # THE CARD IS IN THE LANGUAGE IT WAS ASKED FOR (#429). The layout and the instruction name it;
    # this is what checks the model obeyed — an English conversation got a Portuguese card because
    # nothing did. Only a CLEAR miss refuses (`language.written`): a refusal costs a redraft.
    from openfactory.language.written import base, not_in

    written = "\n".join([draft.title, draft.objective, draft.description, *draft.done_when])
    other = not_in(written, language)
    if other:
        wanted = _LANGUAGE_NAMES.get(base(language), language)
        problems.append(f"the card is written in {_LANGUAGE_NAMES.get(other, other)}, and the "
                        f"conversation's language is {wanted} — write every field in {wanted}, "
                        f"except the person's own words in source_quote")
    return problems


#: The names the floor's feedback uses for a language `language.written` recognised.
_LANGUAGE_NAMES = {"en": "English", "pt": "Portuguese"}


# ── the rubric and the template: shipped, or the product's own ─────────────────────────────────

@dataclass(frozen=True)
class Criterion:
    id: str
    name: str
    question: str
    levels: dict[int, str]


@dataclass(frozen=True)
class Rubric:
    id: str
    version: str
    low: int
    high: int
    average: float
    lowest: int
    criteria: tuple[Criterion, ...]
    critical: dict[str, str]
    #: where it was read from — the shipped file or the product's — said in every verdict's log line
    source: str = ""

    @classmethod
    def parse(cls, text: str, *, source: str = "") -> Rubric:
        """The rubric in `text`, or ValueError naming what is wrong with it."""
        raw = yaml.safe_load(text)
        if not isinstance(raw, dict):
            raise ValueError("the rubric is not a mapping")
        scale = raw.get("scale") or {}
        passing = raw.get("pass") or {}
        low, high = int(scale.get("min", 1)), int(scale.get("max", 5))
        if low >= high:
            raise ValueError(f"the scale runs from {low} to {high}")
        criteria = []
        for item in raw.get("criteria") or []:
            if not isinstance(item, dict) or not str(item.get("id") or "").strip():
                raise ValueError("a criterion has no id")
            levels = {int(k): " ".join(str(v).split())
                      for k, v in (item.get("levels") or {}).items()}
            criteria.append(Criterion(id=str(item["id"]).strip(),
                                      name=str(item.get("name") or item["id"]).strip(),
                                      question=" ".join(str(item.get("question") or "").split()),
                                      levels=levels))
        if not criteria:
            raise ValueError("the rubric names no criteria")
        if len({c.id for c in criteria}) != len(criteria):
            raise ValueError("two criteria share an id")
        critical = {str(c["id"]).strip(): " ".join(str(c.get("description") or "").split())
                    for c in raw.get("critical_failures") or [] if isinstance(c, dict)
                    and str(c.get("id") or "").strip()}
        average, lowest = float(passing.get("average", high)), int(passing.get("floor", low))
        if not (low <= average <= high and low <= lowest <= high):
            raise ValueError(f"the pass bar ({average}, floor {lowest}) is outside the scale")
        return cls(id=str(raw.get("id") or "rubric"), version=str(raw.get("version") or "0"),
                   low=low, high=high, average=average, lowest=lowest,
                   criteria=tuple(criteria), critical=critical, source=source)


def _shipped(name: str) -> str:
    return (_DEFAULTS / name).read_text()


def _in_language(name: str, language: str | None) -> str:
    """`template.md` as `template.<language>.md`; the name itself for no language."""
    lang = (language or "").strip()
    if not lang:
        return name
    stem, dot, ext = name.rpartition(".")
    return f"{stem}.{lang}.{ext}" if dot else f"{name}.{lang}"


def _shipped_for(name: str, language: str | None) -> str:
    """The shipped layout for `language` — its own file when one ships, the default's otherwise."""
    own = _in_language(name, language)
    return _shipped(own) if (_DEFAULTS / own).is_file() else _shipped(name)


def _own(docs_path: str, name: str) -> Path | None:
    if not docs_path:
        return None
    path = Path(docs_path) / OVERRIDE_DIR / name
    return path if path.is_file() else None


def load_rubric(docs_path: str = "") -> Rubric:
    """The product's rubric when its context repository has a usable one, the shipped one
    otherwise — and a product file that cannot be used is SAID, never silently replaced: a product
    that believes it raised its bar and runs on the default is the quiet failure."""
    own = _own(docs_path, RUBRIC_FILE)
    if own is not None:
        try:
            return Rubric.parse(own.read_text(), source=f"{OVERRIDE_DIR}/{RUBRIC_FILE}")
        except Exception as exc:  # noqa: BLE001 — a product's file must never lose the card
            log.warning("OPENFACTORY_CARD_RUBRIC_REFUSED path=%s — %s; the shipped rubric is used",
                        own, exc)
    return Rubric.parse(_shipped(RUBRIC_FILE), source="shipped")


def load_template(docs_path: str = "", kind: str = "ticket", language: str | None = None) -> str:
    """The product's card template when its context repository has a usable one, the shipped one
    otherwise — each in `language` when there is one in it (#429): the product's
    `cards/template.<language>.md` first, then its `cards/template.md`, then the shipped layout in
    that language. THE PRODUCT'S OWN STILL WINS over a shipped one in the right language: a product
    that wrote its layout decided what its cards look like.

    USABLE IS MEASURED, NOT ASSUMED: a sample card is rendered through it and must keep every
    field, pass the pickup gate, and keep the section `correct_card` rewrites (#156). A template
    that renamed the criteria heading to one the parser does not know would otherwise make every
    card fail the floor — and the product would never get a card at all."""
    name = _TEMPLATES[kind]
    for candidate in dict.fromkeys((_in_language(name, language), name)):
        own = _own(docs_path, candidate)
        if own is None:
            continue
        text = own.read_text()
        problem = template_problem(text, kind)
        if not problem:
            return text
        log.warning("OPENFACTORY_CARD_TEMPLATE_REFUSED path=%s — %s; the shipped template is used",
                    own, problem)
    return _shipped_for(name, language)


def template_problem(text: str, kind: str = "ticket") -> str:
    """Why `text` cannot be a template for a card of `kind` — `""` when it can."""
    from openfactory.adapters.tracker.parse import parse_ticket_body
    from openfactory.orchestrator.machine import spec_verdict
    from openfactory.product.module import _WHAT_WAS_ASKED, _section_re

    unknown = sorted(set(_placeholders(text)) - set(FIELDS))
    if unknown:
        return (f"it names fields no draft has: {', '.join(unknown)} "
                f"(the fields: {', '.join(FIELDS)})")
    missing = [f for f in ("description", "done_when") if f"{{{f}}}" not in text]
    if missing:
        return f"it leaves out {', '.join(missing)}, which every card must carry"
    sample = CardDraft(title="t", objective="o", description="d " * 12, done_when=["c"],
                       out_of_scope=["x"], related=["r"], source_quote="q")
    body = render(sample, text)
    refused = spec_verdict(parse_ticket_body(id="sample", title="t", body=body, repo=""))
    if refused:
        return f"the pickup gate refuses what it renders: {refused}"
    # FOUND BY WHAT IT MEANS, UNDER ANY NAME IT HAS (#429): `_section_re` is the reader a
    # correction uses, so a layout it can read is one a correction can rewrite — in either language
    section = _WHAT_WAS_ASKED[_SECTION_OF[kind]]
    if not _section_re(section).search(body):
        return (f"it has no '## {section}' section around {{description}} (or that section "
                f"under another name the platform reads), which is the section a correction of "
                f"the card rewrites")
    return ""


# ── the judge ──────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Ruling:
    """What the judge said and what the code concluded from it."""

    scores: dict[str, int]
    evidence: dict[str, str]
    critical: tuple[str, ...]
    findings: tuple[str, ...]
    ask: str
    average: float
    passed: bool
    #: why it did not pass, in the code's words — `()` when it passed
    because: tuple[str, ...] = ()


def judge_prompt(rubric: Rubric, *, conversation: str, request: str, card: str,
                 source_note: str = "", reply: str = "", answer: str = "") -> str:
    """The judge's whole prompt: the rubric, the conversation, the card, and the answer's shape.
    SELF-CONTAINED — the judge stands in an empty directory and has nothing else to open."""
    criteria = []
    for c in rubric.criteria:
        ladder = "\n".join(f"    {n}: {text}" for n, text in sorted(c.levels.items()))
        criteria.append(f"- `{c.id}` — {c.name}. {c.question}\n{ladder}")
    critical = "\n".join(f"- `{k}` — {v}" for k, v in rubric.critical.items()) or "- (none)"
    ids = ", ".join(f'"{c.id}": {rubric.low}-{rubric.high}' for c in rubric.criteria)
    return (
        "You are an impartial reviewer of a card that another agent drafted for a software "
        "factory's board, from a conversation with a person. The card is the ONLY thing the coding "
        "agent will read. You do not rewrite the card and you do not suggest a better one: you "
        "score it.\n\n"
        + (f"{source_note.strip()}\n\n" if source_note.strip() else "")
        + "Rules:\n"
        "- Score each criterion by the level whose description fits the card best. For a level "
        "below the top, name in `evidence` what keeps it from the next level up; for any level, "
        "quote the card or the conversation. A score without a quote is not a score.\n"
        "- Judge against THIS conversation: a fact the card states that the conversation never "
        "established is invented, however plausible it is.\n"
        "- Do not penalise the card for what the conversation never said; penalise it for what the "
        "conversation said and the card lost.\n"
        "- Do not soften a score to let a card pass.\n"
        "- Do not compute an average or a verdict — that is done from your scores.\n"
        "- BE BRIEF: `evidence` is one short sentence per criterion, quoting at most a dozen "
        "words; at most three `findings`, one line each. Nothing outside the JSON.\n"
        "- Describing a screen, a control or a message by what it shows is as good as its name: "
        "never mark a card down for a name the conversation did not give.\n"
        f"- `ask`: ONLY when a fact without which an implementer cannot start, or cannot tell "
        f"when the work is done, was never said in the conversation — the ONE question that gets "
        f"it, in the person's language. Never for a name, a label or wording. Otherwise \"\".\n\n"
        f"## Rubric `{rubric.id}` v{rubric.version} (levels {rubric.low}-{rubric.high})\n\n"
        + "\n\n".join(criteria)
        + f"\n\n## Critical failures (any one fails the card)\n\n{critical}\n\n"
        f"## The conversation (oldest first)\n\n{conversation.strip() or '(no earlier messages)'}"
        f"\n\n## The message that asked for the card\n\n{request.strip()}\n\n"
        # THE JUDGE SEES WHAT THE AUTHOR SAW. Measured live: the draft was written from the role's
        # reply (it had read the code and the board) and from the person's answer to the held
        # question, and the judge was shown neither. It scored the CSS analysis and the related
        # cards "invented", and the person's own "claramente isso é um bug" "a claim never
        # made", and the person was shown both as the review's objections.
        + (f"## What the product role replied (it read the code and the board; what it "
           f"established there counts as context, but nothing in it is the person's words)"
           f"\n\n{reply.strip()}\n\n" if reply.strip() else "")
        + (f"## The person's answer to the question the card was held on\n\n"
           f"{answer.strip()}\n\n" if answer.strip() else "")
        + f"## The card\n\n{card.strip()}\n\n"
        "## Answer\n\nReturn ONLY a JSON object (no prose, no code fences):\n"
        f'{{"scores": {{{ids}}}, "evidence": {{"<criterion id>": str}}, '
        '"critical": ["<critical failure id>"], "findings": [str], "ask": str}\n'
        "`findings` are what the author must change, one per line, most important first."
    )


def ruling(answer: str | None, rubric: Rubric) -> Ruling | None:
    """The judge's answer read against `rubric`, with the verdict computed — or None when the
    answer is not a complete scoring. PARTIAL IS NONE: a missing criterion read as a default level
    would be a score nobody gave."""
    from openfactory.adapters.reviewer.harness import extract_json

    if not answer:
        return None
    try:
        raw = json.loads(extract_json(answer))
    except Exception as exc:  # noqa: BLE001 — a judge that answered in prose
        log.info("the card judge's answer was not JSON (%s) — read as no scoring", exc)
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("scores"), dict):
        return None
    scores: dict[str, int] = {}
    for c in rubric.criteria:
        value = raw["scores"].get(c.id)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
            return None
        if not rubric.low <= int(value) <= rubric.high:
            return None
        scores[c.id] = int(value)
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    critical = tuple(str(k) for k in (raw.get("critical") or []) if str(k) in rubric.critical)
    findings = tuple(" ".join(str(f).split()) for f in (raw.get("findings") or [])
                     if str(f).strip())
    average = round(sum(scores.values()) / len(scores), 2)
    because = []
    if critical:
        because.append(f"critical failure: {', '.join(critical)}")
    if average < rubric.average:
        because.append(f"average {average} below {rubric.average}")
    low = sorted(k for k, v in scores.items() if v < rubric.lowest)
    if low:
        because.append(f"below the floor of {rubric.lowest}: {', '.join(low)}")
    return Ruling(scores=scores, evidence={str(k): str(v) for k, v in evidence.items()},
                  critical=critical, findings=findings,
                  ask=" ".join(str(raw.get("ask") or "").split()), average=average,
                  passed=not because, because=tuple(because))


def in_a_room(project, harness, phase: str) -> Judge:
    """`harness.ask` as a prompt in and the text out, in an empty directory of its own, metered as
    `phase` and refused under the product's semaphore.

    BOTH CALLS OF THE LOOP STAND HERE, AND THE DRAFT'S FIRST RUN IS WHY. On the first live card
    the draft ran in the role's workspace — the docs, every source, the facts — and spent 27 turns
    and two minutes exploring the code before writing a card whose every fact was already in the
    prompt; the redraft spent 20 more. A card is written from the conversation, and the prompt
    carries the conversation: there is nothing in a checkout it needs, and a directory with nothing
    to open is the cheapest way to say so."""
    from openfactory.adapters.agent.base import final_text
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.adapters.sandbox.registry import judging_worktree
    from openfactory.product.role import meter
    from openfactory.product.semaphore import refuse_a_model_here

    def ask(prompt: str) -> str | None:
        refuse_a_model_here(phase)
        with tempfile.TemporaryDirectory(prefix="openfactory-card-") as room:
            # A Path, whatever the box does with a str: correct at every merge order, and harmless
            # beside the box's own normalisation (#380, in #382) — review of #390
            sandbox = judging_worktree(project, root=Path(room))
            workspace = Workspace(path=Path(room), branch="main", base_branch="main")
            started = time.monotonic()
            res = harness.ask(sandbox=sandbox, workspace=workspace, prompt=prompt, phase=phase)
            meter(getattr(project, "name", "") or "", getattr(harness, "name", "") or "", res,
                  phase, wall_s=round(time.monotonic() - started, 2))
        return final_text(res) if getattr(res, "ok", False) else None

    return ask


def as_json(ask: Judge) -> Callable[[str], dict | None]:
    """A text call read as one JSON object — None when the answer is not one."""
    from openfactory.adapters.reviewer.harness import extract_json

    def call(prompt: str) -> dict | None:
        text = ask(prompt)
        if not text:
            return None
        try:
            parsed = json.loads(extract_json(text))
        except Exception as exc:  # noqa: BLE001 — a model that answered in prose
            log.info("the card draft was not JSON (%s) — read as no draft", exc)
            return None
        return parsed if isinstance(parsed, dict) else None

    return call


def build_judge(project) -> Judge | None:
    """The judge, on the reviewer axis, in a room of its own. None when this deployment has no
    harness that can judge: the card is then shown unjudged, and says so (see `compose`)."""
    from openfactory.adapters.agent.registry import build_asker

    try:
        harness = build_asker(project, role=JUDGE_ROLE)
    except Exception as exc:  # noqa: BLE001 — a misconfigured judge must not lose the card
        log.warning("OPENFACTORY_CARD_JUDGE_UNAVAILABLE project=%s — %s",
                    getattr(project, "name", "?"), exc)
        return None
    return in_a_room(project, harness, JUDGE_PHASE)


# ── the loop ───────────────────────────────────────────────────────────────────────────────────

@dataclass
class Composed:
    """What the loop ended with. `card` is set when there is a card to show for the yes; `ask` when
    there is not, and the person must be asked something first."""

    draft: CardDraft | None = None
    card: str = ""
    ruling: Ruling | None = None
    #: the card was not judged — no judge, or an answer that could not be read — and the
    #: confirmation must say so
    unjudged: bool = False
    ask: str = ""
    attempts: int = 0
    rubric: str = ""
    #: the card is shown although the judge still blocks it — the person already answered the
    #: judge's question once, and the remaining findings travel with the card for their yes
    disputed: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.card) and self.draft is not None


@dataclass(frozen=True)
class Answered:
    """The person's answer to the question a card was held on, with what the loop had then."""

    question: str
    answer: str
    draft: CardDraft
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpenQuestion:
    """A card the loop could not show yet, waiting for the person's answer to one question."""

    request: str
    ask: str
    draft: CardDraft
    findings: tuple[str, ...]
    at: float
    #: which card the question was held for (`_TEMPLATES`), and what the gesture carried beside
    #: it — a defect's cited requirement — so the answer stages the same kind of card
    kind: str = "ticket"
    extra: tuple[tuple[str, object], ...] = ()


#: HOW LONG A HELD QUESTION WAITS — the staged proposal's own TTL
#: (`staging.PROPOSAL_TTL_SECONDS`), because a question is answered on the same clock a proposal
#: is confirmed on; a guard holds the two together. WRITTEN ON THE RECORD as its deadline (#452),
#: so every process ages a question by the deadline it was held with.
QUESTION_TTL_SECONDS = 2 * 60 * 60
#: This process's copy of the questions it held, one per person and conversation, the oldest
#: evicted past the bound. A COPY (#452): the record is the store's (`hold_question`), and the copy
#: is read only where there is no store to ask, or the store missed the hold's write.
_OPEN: BoundedDict[str, OpenQuestion] = BoundedDict(500)

#: How a held question's record is closed: taken by the answer, aged out on read, or replaced by a
#: later hold of this process whose own record did not land.
TAKEN, EXPIRED, REPLACED = "taken", "expired", "replaced"


def hold_question(key: str, composed: Composed, request: str, *, kind: str = "ticket",
                  extra: dict | None = None, project=None, conversation: str = "") -> None:
    """Keep the card a blocked loop ended with, so the person's next message ANSWERS its question.

    THE ANSWER USED TO START THE WHOLE TURN AGAIN. On the first live card the judge blocked twice
    and asked; the person answered, and that answer was a new message like any other: the product
    role's full answer (143 s, 16 turns exploring the code), a new gesture, and the whole loop from
    the first draft — nine model calls and about ten minutes for one card. The question is held
    here instead, under the person's own key in that conversation, and the answer goes straight to
    one redraft (`compose(answered=...)`).

    IN THE STORE, AS A HOLD — NOT IN THIS PROCESS ALONE, AND NOT AS A STAGED PROPOSAL (#452). It
    was kept in this process on purpose, the cost written as "only the shortcut". Measured, the
    cost was the answer: the worker restarted, the person's "it's the Home screen" arrived as a new
    message, and the role started the card over — the question forgotten in public. A staged entry
    is still the wrong record: it carries buttons on the panel, a place in the product's write
    sequence and an intake transition, and a question is none of those. So it is a `held` row
    (`messages.HELD`) under `waiting.question_token(key)`, carrying the request, the draft, the
    findings and its written deadline, read by whichever process the answer reaches
    (`held_question`). `conversation` is where it was asked, said on the record for the readers
    that list a conversation's waits (`waiting.in_conversation`)."""
    if composed.draft is None:
        return
    held = OpenQuestion(
        request=request, ask=composed.ask, draft=composed.draft,
        findings=tuple(composed.ruling.findings) if composed.ruling else (),
        at=time.time(), kind=kind, extra=tuple(sorted((extra or {}).items())))
    _OPEN[key] = held
    if project is None:
        return
    from openfactory.memory import messages
    from openfactory.product.waiting import question_token

    # THE ROW'S STAMP IS THE HOLD'S OWN MOMENT, so a copy and its record compare as one hold
    if not messages.hold(getattr(project, "name", "") or "", held.ask,
                         token=question_token(key), channel=conversation or key,
                         payload=_freeze_question(held),
                         expires=_iso(held.at + QUESTION_TTL_SECONDS), now=_iso(held.at)):
        log.warning("the card question held for %s was not written — its answer reaches only "
                    "this process, and a restart reads it as a new message", key)


def held_question(key: str, *, project=None) -> OpenQuestion | None:
    """The question held under `key` — or None when there is none or it is too old. Read, not
    taken: the answer closes it (`close_question`) once its redraft is in hand.

    THE STORE'S RECORD FIRST (#452), so the process the answer reaches — a restarted worker, a
    second one — finds the question another process asked. This process's copy decides only where
    the store cannot (`_from_the_store`). One conversation's turns are taken one at a time
    (`ConversationWorkflow`), so no second process reads the record between this read and the
    write that closes it."""
    local = _OPEN.get(key)
    stored = _from_the_store(key, project, local)
    if stored is not _NOT_ASKED:
        if stored is None:
            _OPEN.pop(key, None)
        return stored
    held = local
    if held is None or time.time() - held.at > QUESTION_TTL_SECONDS:
        _OPEN.pop(key, None)
        return None
    return held


def close_question(key: str, *, project=None) -> None:
    """The question held under `key`, closed: answered, or declined.

    CLOSED WITH THE REDRAFT IN HAND, NOT WHEN IT IS READ (#452). The redraft is a draft and a
    judgement — one to four minutes of model calls — and a worker that dies in them has its turn
    run again on another (`conversation.TURN_RETRY`). A question closed on read was gone for that
    retry, and the person's answer reached it as a new message: the restart this record exists
    for, inside one turn."""
    _OPEN.pop(key, None)
    if project is None:
        return
    from openfactory.memory import messages
    from openfactory.product.waiting import question_token

    messages.release(getattr(project, "name", "") or "", token=question_token(key), answer=TAKEN)


#: The store had nothing to say about this key, and this process's copy decides.
_NOT_ASKED = object()


def _from_the_store(key: str, project, local: OpenQuestion | None):
    """The held question as the store says it — the question, None, or `_NOT_ASKED` when there is
    no store to ask, it holds nothing under `key`, or `local` was held after its latest record
    (that hold's own write did not land; the older record is closed as `REPLACED`)."""
    if project is None:
        return _NOT_ASKED
    from openfactory.memory import messages
    from openfactory.product.waiting import past, question_token, seconds

    name = getattr(project, "name", "") or ""
    token = question_token(key)
    try:
        found = [(m, closed) for m, closed in messages.held(name) if m.token == token]
    except Exception:  # noqa: BLE001 — a store that cannot be read leaves this process's copy
        log.info("could not read the card question held for %s", key, exc_info=True)
        return _NOT_ASKED
    if not found:
        return _NOT_ASKED
    row, closed = found[-1]
    asked_at = seconds(row.ts)
    # the record is stamped with the hold's own moment (`hold_question`), to the microsecond the
    # stamp keeps: a copy more than a millisecond younger is a later hold, never the same one
    if local is not None and (asked_at is None or local.at > asked_at + 0.001):
        if closed is None:
            messages.release(name, token=token, answer=REPLACED)
        return _NOT_ASKED
    if closed is not None:
        # TAKEN OR AGED OUT ELSEWHERE — a copy this process kept is that same question, stale
        return None
    if past(row.expires, time.time()):
        messages.release(name, token=token, answer=EXPIRED)
        return None
    return _thaw_question(row.payload)


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat()


def _freeze_question(held: OpenQuestion) -> str:
    """The held question as JSON another process rebuilds whole (`_thaw_question`)."""
    from dataclasses import asdict

    return json.dumps({"request": held.request, "ask": held.ask, "draft": asdict(held.draft),
                       "findings": list(held.findings), "at": held.at, "kind": held.kind,
                       "extra": [list(pair) for pair in held.extra]},
                      ensure_ascii=False, default=str)


def _thaw_question(payload: str) -> OpenQuestion | None:
    """The held question back, or None — never a half-built one: a redraft from a draft that lost
    its criteria would be the card the person already answered for, worse."""
    from dataclasses import fields

    try:
        raw = json.loads(payload)
        kind = str(raw.get("kind") or "ticket")
        if kind not in _TEMPLATES:
            raise ValueError(f"no card of kind {kind!r}")
        names = {f.name for f in fields(CardDraft)}
        draft = CardDraft(**{k: v for k, v in dict(raw["draft"]).items() if k in names})
        return OpenQuestion(request=str(raw["request"]), ask=str(raw.get("ask") or ""),
                            draft=draft, findings=tuple(str(f) for f in raw.get("findings") or ()),
                            at=float(raw["at"]), kind=kind,
                            extra=tuple((str(k), v) for k, v in raw.get("extra") or ()))
    except Exception:  # noqa: BLE001 — an unreadable record is a question gone, said
        log.warning("could not read a held card question back — its answer is read as a new "
                    "message", exc_info=True)
        return None


#: What the role is told it is writing, by kind — the one sentence that differs (#392).
_ASKED = {
    "ticket": ("The person asked you to open a card on the board, and you agreed. Write that card "
               "now. "),
    "defect": ("The person reported something the product does wrong, and you read it as a broken "
               "promise to register for a fix. Write that defect card now: `description` says what "
               "is happening — what was observed, where, under which conditions, and what should "
               "happen instead — and `done_when` is the behaviour the fix restores. "),
}


def draft_prompt(*, conversation: str, request: str, reply: str, intake: str, title: str,
                 template: str, feedback: list[str], kind: str = "ticket",
                 language: str | None = None) -> str:
    """What the role is asked when it drafts (or redrafts) a card — in `language` when one is
    named (#429): "the person's language" left the model to infer it, and it inferred it from
    the layout."""
    from openfactory.product.voice import language_rules

    written_in = (f"Write every field in {language}, the conversation's language — whatever "
                  f"language the layout below or the documents are in — except `source_quote`, "
                  f"which is the person's words as they said them."
                  if language else "Write it in the person's language.")
    rules = language_rules(language) if language else ""
    again = ""
    if feedback:
        again = ("\n\n## Your previous draft was not good enough\n\nChange exactly this, and keep "
                 "what was right:\n" + "\n".join(f"- {f}" for f in feedback))
    return (
        _ASKED[kind]
        + "The card is the ONLY thing the coding agent will read: it never sees this conversation, "
        "so everything the conversation established that an implementer needs must be on the card "
        "— what was observed or asked for, where, under which conditions, what an attached file "
        "showed, which earlier card it relates to and why — and nothing the conversation did not "
        f"establish. {written_in}\n\n"
        + (f"{rules}\n\n" if rules else "")
        + "Rules:\n"
        f"- `title`: at most {TITLE_LIMIT} characters, naming the part of the product and the "
        "problem or wish. Never the request itself.\n"
        "- `description`: your restatement of the work. NEVER the message that asked for the card "
        "(\"cria um card\", \"pode seguir\") — that message is the gesture, not the work.\n"
        "- `done_when`: observable statements a reviewer can check without opening the code, "
        "covering what the conversation said 'fixed' means. Never HOW to build it.\n"
        "- `out_of_scope`: only what the conversation excluded; [] otherwise.\n"
        "- `related`: earlier cards or requirements the conversation connected to this one, each "
        "as {\"ref\": \"#N\", \"why\": str}; [] otherwise.\n"
        "- `source_quote`: the person's own words that best describe the problem, copied EXACTLY "
        "from the conversation; \"\" if none describe it.\n"
        "- `questions`: what an implementer needs that the conversation never said. Do not invent "
        "an answer to fill a field — ask.\n"
        "- Nothing private or unrelated to the work from the conversation goes on the card.\n\n"
        f"## The card's layout (for your orientation; you only fill the fields)\n\n{template}\n"
        f"\n## The conversation (oldest first)\n\n{conversation.strip() or '(no earlier messages)'}"
        + (f"\n\n## What you know about this request so far\n\n{intake.strip()}" if intake else "")
        + f"\n\n## The message that asked for the card\n\n{request.strip()}"
        + (f"\n\n## Your reply to it\n\n{reply.strip()}" if reply else "")
        + (f"\n\n## The title you proposed\n\n{title.strip()}" if title else "")
        + again
        + "\n\n## Answer\n\nAnswer at once with ONLY a JSON object (no prose, no code fences, "
        "nothing to look up — everything the card is written from is above):\n"
        '{"title": str, "objective": str, "description": str, "done_when": [str], '
        '"out_of_scope": [str], "related": [{"ref": str, "why": str}], "source_quote": str, '
        '"questions": [str]}'
    )


def compose(*, draft: Callable[[str], dict | None], judge: Judge | None, rubric: Rubric,
            template: str, conversation: str, request: str, reply: str = "", intake: str = "",
            title: str = "", project_name: str = "",
            answered: Answered | None = None, kind: str = "ticket",
            language: str | None = None) -> Composed:
    """Draft, check and judge one card — at most `ATTEMPTS` drafts — and say what came of it.

    `draft` is the role's JSON call (a prompt in, a dict or None out); `judge` the judge's text
    call, or None when there is none. Neither runs under the product's semaphore: nothing here
    writes (ADR-0051 D8).

    `answered` is the person's answer to the question an earlier run was held on: ONE redraft from
    the draft it held, with the answer and the findings, and — when the judge still blocks — the
    card is shown anyway with what the judge still says (`disputed`). The person was asked once;
    asking again is the loop the answer exists to end, and their yes is still the only write."""
    feedback: list[str] = []
    rounds = ATTEMPTS
    if answered is not None:
        rounds = 1
        feedback = [f"You asked the person: {answered.question or 'what was missing'} — and they "
                    f"answered: {answered.answer.strip()}. Use their answer.",
                    "Your previous draft, to keep what was right and change what the answer "
                    "changes: " + json.dumps(answered.draft.__dict__, ensure_ascii=False),
                    *answered.findings]
    last: Composed = Composed(rubric=f"{rubric.id}@{rubric.version}")
    from openfactory.product import progress

    for attempt in range(1, rounds + 1):
        # WHAT THE PERSON WAITS THROUGH, SAID WHILE THEY WAIT (#395): the loop is minutes of model
        # calls, and each names itself on the surface that can show it
        progress.stage("card_draft", step=attempt, of=rounds)
        card = CardDraft.from_answer(draft(draft_prompt(
            conversation=conversation, request=request, reply=reply, intake=intake, title=title,
            template=template, feedback=feedback, kind=kind, language=language)))
        if card is None:
            log.info("[%s] the card draft could not be read (attempt %s)", project_name, attempt)
            feedback = ["your answer was not the JSON object asked for"]
            continue
        body = render(card, template)
        last = Composed(draft=card, attempts=attempt, rubric=f"{rubric.id}@{rubric.version}")
        problems = floor(card, body, request=request, conversation=conversation,
                         language=language)
        if problems:
            log_verdict(project_name, attempt, rubric, floor=problems)
            feedback = problems
            continue
        if judge is None:
            return Composed(draft=card, card=body, unjudged=True, attempts=attempt,
                            rubric=last.rubric)
        progress.stage("card_review", step=attempt, of=rounds)
        said = ruling(judge(judge_prompt(
            rubric, conversation=conversation, request=request, card=f"# {card.title}\n\n{body}",
            reply=reply, answer=answered.answer if answered is not None else "")), rubric)
        if said is None:
            log.warning("OPENFACTORY_CARD_JUDGE_UNREADABLE project=%s attempt=%s — the card is "
                        "shown unjudged", project_name, attempt)
            return Composed(draft=card, card=body, unjudged=True, attempts=attempt,
                            rubric=last.rubric)
        log_verdict(project_name, attempt, rubric, said=said)
        if said.passed:
            return Composed(draft=card, card=body, ruling=said, attempts=attempt,
                            rubric=last.rubric)
        last.ruling = said
        feedback = list(said.findings) or list(said.because)
    if (answered is not None and last.draft is not None and last.ruling is not None
            and not last.ruling.passed):
        return Composed(draft=last.draft, card=render(last.draft, template), ruling=last.ruling,
                        attempts=last.attempts, rubric=last.rubric, disputed=True)
    # TWO FAILURES FILE NOTHING. What is missing now is something only the person knows, and the
    # judge said which question gets it; the draft's own questions are the second source.
    ask = ""
    if last.ruling is not None and last.ruling.ask:
        ask = last.ruling.ask
    elif last.draft is not None and last.draft.questions:
        ask = " ".join(last.draft.questions[:2])
    last.ask = ask
    return last


def log_verdict(project_name: str, attempt: int, rubric: Rubric, *, said: Ruling | None = None,
                floor: list[str] | None = None) -> None:
    _record_verdict(project_name, attempt, rubric, said=said, floor=floor)
    _say_verdict(project_name, attempt, rubric, said=said, floor=floor)


#: HOW LONG A BREAKDOWN MAY SPEND CHECKING ITS CARDS (review of #390). Each card of a requirement
#: costs up to three model calls here (judge, redraft, judge — about 100 to 234 s measured live),
#: and the breakdown's activity has one attempt, because a retry after a partial success would
#: file the same work twice. So the breakdown stops starting new cards past this budget and says
#: which fronts it did not reach, instead of dying at its timeout with cards on the board that
#: nothing reports. The activity's own timeout (`ProductBreakdownWorkflow`) sits above it.
BREAKDOWN_BUDGET_SECONDS = 45 * 60


#: What the judge is told when the card executes a requirement instead of a conversation (#392).
REQUIREMENT_NOTE = (
    "HERE THE SOURCE IS NOT A CONVERSATION: it is the accepted requirement below, and the card "
    "executes one front of it. Read \"the conversation\" as that requirement and \"the message "
    "that asked for the card\" as the instruction to break it into cards. A card that promises "
    "less than its front of the requirement lost something; one that promises more invented it.")


def vet_issue(fields: dict, *, body_of: Callable[[dict], str], source: str, rubric: Rubric,
              judge: Judge | None, redraft: Callable[[str], dict | None] | None,
              project_name: str = "") -> tuple[dict | None, str]:
    """One card of a requirement's breakdown, checked by the floor and the judge before it is
    filed — `(fields, "")` to file (possibly redrafted once), `(None, why)` to refuse (#392).

    THE THIRD PEN. A requested card and a defect go through `compose`; the cards a requirement is
    broken into were written straight to the board, with nothing between the role's first answer and
    the tracker. `fields` is the issue as the role drafted it (title, objective,
    acceptance_criteria, out_of_scope); `body_of` renders the body the tracker will receive, so the
    floor's pickup-gate check reads exactly that. No person is in this loop, so a card the judge
    still blocks after one redraft is NOT filed: the breakdown says which front and why."""
    ask = "Break the requirement into cards; this card executes one front of it."
    feedback: list[str] = []
    for attempt in range(1, ATTEMPTS + 1):
        card = CardDraft(title=str(fields.get("title") or "").strip(),
                         objective=str(fields.get("objective") or "").strip(),
                         done_when=[str(c) for c in fields.get("acceptance_criteria") or []],
                         out_of_scope=[str(c) for c in fields.get("out_of_scope") or []])
        body = body_of(fields)
        problems = floor(card, body, request=ask, conversation=source, described=False)
        said = None
        if problems:
            log_verdict(project_name, attempt, rubric, floor=problems)
            feedback = problems
        elif judge is None:
            return fields, ""
        else:
            said = ruling(judge(judge_prompt(rubric, conversation=source, request=ask,
                                             card=f"# {card.title}\n\n{body}",
                                             source_note=REQUIREMENT_NOTE)), rubric)
            if said is None:
                # UNREAD IS NOT FILED (review of #390). The requested card and the defect show an
                # unjudged card to a person before the yes; here nobody is in the loop, so a judge
                # that could not be read must not become a write on the client's board. The cost
                # is stated: a judge that cannot answer holds the breakdown's cards back, and the
                # breakdown says which and why — the direction an unknown must fail in.
                log.warning("OPENFACTORY_CARD_JUDGE_UNREADABLE project=%s attempt=%s — the "
                            "requirement's card is NOT filed", project_name, attempt)
                return None, "a revisão automática não respondeu"
            log_verdict(project_name, attempt, rubric, said=said)
            if said.passed:
                return fields, ""
            feedback = list(said.findings) or list(said.because)
        if attempt == ATTEMPTS or redraft is None:
            break
        again = redraft(
            "Rewrite this ONE card of the requirement below so it can be filed. Change exactly "
            "what is listed, keep what was right, and never promise more than the requirement.\n\n"
            "## What to change\n\n" + "\n".join(f"- {f}" for f in feedback)
            + f"\n\n## The card as drafted\n\n{json.dumps(fields, ensure_ascii=False)}"
            f"\n\n## The requirement\n\n{source.strip()}\n\n## Answer\n\nAnswer at once with "
            "ONLY a JSON object (no prose, no code fences): {\"title\": str, \"objective\": str, "
            "\"acceptance_criteria\": [str], \"out_of_scope\": [str]}")
        if not isinstance(again, dict):
            # the same input would reach the same verdict: a judge call spent for nothing
            break
        fields = {**fields, **{k: again[k] for k in
                               ("title", "objective", "acceptance_criteria", "out_of_scope")
                               if k in again}}
    return None, "; ".join(feedback[:3]) or "it did not pass the review"


def _record_verdict(project_name: str, attempt: int, rubric: Rubric, *,
                    said: Ruling | None = None, floor: list[str] | None = None) -> None:
    """THE VERDICT AS A ROW, BESIDE THE CALL'S COST. The log line alone was the calibration record,
    and on the first deployment that ran it the worker logged warnings only: two verdicts that
    blocked a card left nothing anybody could read back. A row in the metrics store is kept
    whatever the log level, and it is where the draft's and the judge's costs already are.
    Best-effort, like every row there."""
    try:
        from openfactory.observability.metrics import MetricRecord
        from openfactory.observability.registry import deployment_metrics_sink

        extra: dict = {"rubric": f"{rubric.id}@{rubric.version}", "source": rubric.source,
                       "attempt": attempt}
        if said is None:
            extra.update(verdict="floor", problems=list(floor or []))
        else:
            extra.update(verdict="pass" if said.passed else "block", average=said.average,
                         scores=dict(said.scores), critical=list(said.critical),
                         because=list(said.because), findings=list(said.findings),
                         ask=said.ask)
        deployment_metrics_sink().record(MetricRecord(
            project=project_name, ticket="_product_card_verdict_",
            ts=datetime.now(UTC).isoformat(), kind="card_verdict", role="product_card_verdict",
            extra=extra))
    except Exception as exc:  # noqa: BLE001
        log.warning("could not record the card verdict (%s)", exc)


def _say_verdict(project_name: str, attempt: int, rubric: Rubric, *, said: Ruling | None = None,
                 floor: list[str] | None = None) -> None:
    """ONE LINE PER VERDICT, with everything needed to recompute it — the calibration record. A
    rubric whose verdicts cannot be read back against the conversations they judged cannot be
    tuned; it can only be argued about."""
    if said is None:
        log.info("OPENFACTORY_CARD_JUDGED project=%s attempt=%s rubric=%s@%s source=%s "
                 "verdict=floor problems=%s", project_name, attempt, rubric.id, rubric.version,
                 rubric.source, json.dumps(floor or [], ensure_ascii=False))
        return
    log.info("OPENFACTORY_CARD_JUDGED project=%s attempt=%s rubric=%s@%s source=%s verdict=%s "
             "average=%s scores=%s critical=%s", project_name, attempt, rubric.id, rubric.version,
             rubric.source, "pass" if said.passed else "block", said.average,
             json.dumps(said.scores), ",".join(said.critical) or "-")
