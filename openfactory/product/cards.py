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

1. **Draft** — the role writes the card as JSON from the conversation, its own reply and the
   triggering message (`ProductModule.draft_card`, the role's own context: it can see the board and
   the earlier cards).
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
(`product.docs_repo`). A card is product guidance — a product of N source repositories has one
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
from pathlib import Path

import yaml

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


def floor(draft: CardDraft, body: str, *, request: str, conversation: str) -> list[str]:
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
    if not description:
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
    return problems


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


def load_template(docs_path: str = "") -> str:
    """The product's card template when its context repository has a usable one, the shipped one
    otherwise.

    USABLE IS MEASURED, NOT ASSUMED: a sample card is rendered through it and must keep every
    field, pass the pickup gate, and keep the section `correct_card` rewrites (#156). A template
    that renamed the criteria heading to one the parser does not know would otherwise make every
    card fail the floor — and the product would never get a card at all."""
    own = _own(docs_path, TEMPLATE_FILE)
    if own is not None:
        text = own.read_text()
        problem = template_problem(text)
        if not problem:
            return text
        log.warning("OPENFACTORY_CARD_TEMPLATE_REFUSED path=%s — %s; the shipped template is used",
                    own, problem)
    return _shipped(TEMPLATE_FILE)


def template_problem(text: str) -> str:
    """Why `text` cannot be a card template — `""` when it can."""
    from openfactory.adapters.tracker.parse import parse_ticket_body
    from openfactory.orchestrator.machine import spec_verdict
    from openfactory.product.module import _WHAT_WAS_ASKED

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
    if not re.search(rf"(?m)^#+\s*{re.escape(_WHAT_WAS_ASKED['request'])}\s*$", body):
        return (f"it has no '## {_WHAT_WAS_ASKED['request']}' section around {{description}}, "
                f"which is the section a correction of the card rewrites")
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


def judge_prompt(rubric: Rubric, *, conversation: str, request: str, card: str) -> str:
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
        "Rules:\n"
        "- Score each criterion by the level whose description fits the card best. For a level "
        "below the top, name in `evidence` what keeps it from the next level up; for any level, "
        "quote the card or the conversation. A score without a quote is not a score.\n"
        "- Judge against THIS conversation: a fact the card states that the conversation never "
        "established is invented, however plausible it is.\n"
        "- Do not penalise the card for what the conversation never said; penalise it for what the "
        "conversation said and the card lost.\n"
        "- Do not soften a score to let a card pass.\n"
        "- Do not compute an average or a verdict — that is done from your scores.\n"
        f"- `ask`: when something the card needs was never said in the conversation, the ONE "
        f"question to ask the person to get it, in the person's language; otherwise \"\".\n\n"
        f"## Rubric `{rubric.id}` v{rubric.version} (levels {rubric.low}-{rubric.high})\n\n"
        + "\n\n".join(criteria)
        + f"\n\n## Critical failures (any one fails the card)\n\n{critical}\n\n"
        f"## The conversation (oldest first)\n\n{conversation.strip() or '(no earlier messages)'}"
        f"\n\n## The message that asked for the card\n\n{request.strip()}\n\n"
        f"## The card\n\n{card.strip()}\n\n"
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


def build_judge(project) -> Judge | None:
    """The judge as this module calls it — a prompt in, the text out — on the reviewer axis, in an
    empty directory of its own. None when this deployment has no harness that can judge: the card
    is then shown unjudged, and says so (see `compose`)."""
    from openfactory.adapters.agent.base import final_text
    from openfactory.adapters.agent.registry import build_asker
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.adapters.sandbox.registry import judging_worktree
    from openfactory.product.role import meter
    from openfactory.product.semaphore import refuse_a_model_here

    try:
        harness = build_asker(project, role=JUDGE_ROLE)
    except Exception as exc:  # noqa: BLE001 — a misconfigured judge must not lose the card
        log.warning("OPENFACTORY_CARD_JUDGE_UNAVAILABLE project=%s — %s",
                    getattr(project, "name", "?"), exc)
        return None

    def ask(prompt: str) -> str | None:
        refuse_a_model_here(JUDGE_PHASE)
        with tempfile.TemporaryDirectory(prefix="openfactory-card-judge-") as room:
            sandbox = judging_worktree(project, root=room)
            workspace = Workspace(path=Path(room), branch="main", base_branch="main")
            started = time.monotonic()
            res = harness.ask(sandbox=sandbox, workspace=workspace, prompt=prompt,
                              phase=JUDGE_PHASE)
            meter(getattr(project, "name", "") or "", getattr(harness, "name", "") or "", res,
                  JUDGE_PHASE, wall_s=round(time.monotonic() - started, 2))
        return final_text(res) if getattr(res, "ok", False) else None

    return ask


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

    @property
    def ok(self) -> bool:
        return bool(self.card) and self.draft is not None


def draft_prompt(*, conversation: str, request: str, reply: str, intake: str, title: str,
                 template: str, feedback: list[str]) -> str:
    """What the role is asked when it drafts (or redrafts) a card."""
    again = ""
    if feedback:
        again = ("\n\n## Your previous draft was not good enough\n\nChange exactly this, and keep "
                 "what was right:\n" + "\n".join(f"- {f}" for f in feedback))
    return (
        "The person asked you to open a card on the board, and you agreed. Write that card now. "
        "The card is the ONLY thing the coding agent will read: it never sees this conversation, "
        "so everything the conversation established that an implementer needs must be on the card "
        "— what was observed or asked for, where, under which conditions, what an attached file "
        "showed, which earlier card it relates to and why — and nothing the conversation did not "
        "establish. Write it in the person's language.\n\n"
        "Rules:\n"
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
        + "\n\n## Answer\n\nReturn ONLY a JSON object (no prose, no code fences):\n"
        '{"title": str, "objective": str, "description": str, "done_when": [str], '
        '"out_of_scope": [str], "related": [{"ref": str, "why": str}], "source_quote": str, '
        '"questions": [str]}'
    )


def compose(*, draft: Callable[[str], dict | None], judge: Judge | None, rubric: Rubric,
            template: str, conversation: str, request: str, reply: str = "", intake: str = "",
            title: str = "", project_name: str = "") -> Composed:
    """Draft, check and judge one card — at most `ATTEMPTS` drafts — and say what came of it.

    `draft` is the role's JSON call (a prompt in, a dict or None out); `judge` the judge's text
    call, or None when there is none. Neither runs under the product's semaphore: nothing here
    writes (ADR-0051 D8)."""
    feedback: list[str] = []
    last: Composed = Composed(rubric=f"{rubric.id}@{rubric.version}")
    for attempt in range(1, ATTEMPTS + 1):
        card = CardDraft.from_answer(draft(draft_prompt(
            conversation=conversation, request=request, reply=reply, intake=intake, title=title,
            template=template, feedback=feedback)))
        if card is None:
            log.info("[%s] the card draft could not be read (attempt %s)", project_name, attempt)
            feedback = ["your answer was not the JSON object asked for"]
            continue
        body = render(card, template)
        last = Composed(draft=card, attempts=attempt, rubric=f"{rubric.id}@{rubric.version}")
        problems = floor(card, body, request=request, conversation=conversation)
        if problems:
            _log_verdict(project_name, attempt, rubric, floor=problems)
            feedback = problems
            continue
        if judge is None:
            return Composed(draft=card, card=body, unjudged=True, attempts=attempt,
                            rubric=last.rubric)
        said = ruling(judge(judge_prompt(rubric, conversation=conversation, request=request,
                                         card=f"# {card.title}\n\n{body}")), rubric)
        if said is None:
            log.warning("OPENFACTORY_CARD_JUDGE_UNREADABLE project=%s attempt=%s — the card is "
                        "shown unjudged", project_name, attempt)
            return Composed(draft=card, card=body, unjudged=True, attempts=attempt,
                            rubric=last.rubric)
        _log_verdict(project_name, attempt, rubric, said=said)
        if said.passed:
            return Composed(draft=card, card=body, ruling=said, attempts=attempt,
                            rubric=last.rubric)
        last.ruling = said
        feedback = list(said.findings) or list(said.because)
    # TWO FAILURES FILE NOTHING. What is missing now is something only the person knows, and the
    # judge said which question gets it; the draft's own questions are the second source.
    ask = ""
    if last.ruling is not None and last.ruling.ask:
        ask = last.ruling.ask
    elif last.draft is not None and last.draft.questions:
        ask = " ".join(last.draft.questions[:2])
    last.ask = ask
    return last


def _log_verdict(project_name: str, attempt: int, rubric: Rubric, *, said: Ruling | None = None,
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
