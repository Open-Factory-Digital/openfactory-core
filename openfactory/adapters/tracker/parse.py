"""Parse a ticket's board body into the Ticket contract.

Convention (shared across projects — strong convention on the human/agent interface,
ADR-0001): optional YAML front-matter (depends_on, base_branch, relevant_docs)
followed by markdown sections: `## Objective`, `## Context`, `## Acceptance criteria`
(a bullet list), `## In scope`, `## Out of scope`.

THE CONVENTION IS ON THE MEANING, NOT ON THE SPELLING. The section names used to be matched as
literal lowercased English, so a ticket whose author wrote `## Critérios de aceite` parsed as a
ticket with no acceptance criteria — and the platform then told them their ticket was incomplete.
That happened on the first real ticket of the first open-source deployment, in the language its
users write in. `## AC`, `## Definition of Done` and `## Acceptance criteria:` failed the same way
in English, against templates clients already have.

So a heading is matched by what it MEANS: case, accents, bold markers and trailing colons are
noise, and each canonical section has an alias table covering both languages. This is C-14 (#46)
— *the client's vocabulary belongs to the client* — applied to the ticket body rather than to the
board columns, and the body half is the more urgent one: a mis-named column is visible to whoever
is looking at the board, while a mis-named heading deletes the acceptance criteria in silence.

WHAT THE TABLE CANNOT DO is anticipate every client's template, so `section_names()` exists beside
it: whatever fails to match must be able to SAY what it saw. A refusal that lists the headings it
found is a thirty-second fix; "no acceptance criteria" about a ticket full of them is an argument
with the machine.
"""

from __future__ import annotations

import logging
import unicodedata

import yaml

from openfactory.contracts import AcceptanceCriterion, Ticket

log = logging.getLogger("openfactory.tracker.parse")

#: canonical section -> the spellings that mean it, already normalised (see `_normalise`).
#:
#: Deliberately conservative. Generic words that appear in templates for other reasons — an
#: unqualified "notes", "details", "summary" — are left out: capturing the wrong block is worse
#: than not capturing it, because the fallback (the ticket title as the objective) is honest while
#: a wrong capture is confidently wrong.
_ALIASES: dict[str, tuple[str, ...]] = {
    "objective": (
        "objective", "objectives", "goal", "goals", "what i want",
        "objetivo", "objetivos", "o que quero", "meta",
    ),
    "context": (
        "context", "background", "why",
        "contexto", "cenario", "por que", "porque",
    ),
    "acceptance criteria": (
        "acceptance criteria", "acceptance criterion", "acceptance", "criteria",
        "success criteria", "definition of done", "done when", "dod", "ac",
        "criterios", "criterios de aceite", "criterio de aceite",
        "criterios de aceitacao", "criterio de aceitacao",
        "criterios de sucesso", "aceite", "quando esta pronto",
    ),
    "in scope": (
        "in scope", "scope",
        "escopo", "no escopo", "dentro do escopo",
    ),
    "out of scope": (
        "out of scope", "out-of-scope", "non goals", "non-goals",
        "fora do escopo", "nao escopo", "fora de escopo",
    ),
}

_CANONICAL: dict[str, str] = {
    alias: canonical for canonical, aliases in _ALIASES.items() for alias in aliases
}


def _normalise(heading: str) -> str:
    """A heading reduced to what it MEANS: lowercase, unaccented, unadorned.

    `**Critérios de Aceite:**`, `CRITERIOS DE ACEITE` and `critérios de aceite` are one heading.
    Accents go because people write the same word both ways in the same repository, and a client
    should never lose their acceptance criteria to a missing tilde."""
    text = heading.strip()
    for _ in range(3):  # `**heading:**` needs markers, then the colon, then markers again
        text = text.strip("#*_`~ ").rstrip(":").strip()
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.lower().split())


def _split_front_matter(body: str) -> tuple[dict, str]:
    """The YAML fence a body may open with, and the markdown after it.

    A FENCE THAT DOES NOT PARSE IS BODY TEXT, NOT A DEAD TRACKER. `yaml.safe_load` raises on
    `requester: @octocat` — `@` cannot start a token — and this function is the single door of
    `get_ticket` on GitHub, Jira and Azure Boards: an unguarded load meant that one card a person
    edited by hand took every read of it down with a `ScannerError`, from `scan_todo` to the
    breakdown (found by the slice-2 design critique, 2026-09-06, verified in-tree). The keys are
    optional (`depends_on`, `base_branch`, `relevant_docs`), so the honest reading of a fence that
    cannot be read is: none of them were set, and the whole body is markdown. The warning names the
    fence's FIRST LINE and nothing more — the body is the client's, and a log is not the place to
    copy it."""
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) == 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError as exc:
                first = next((ln for ln in parts[1].splitlines() if ln.strip()), "")
                log.warning("the front matter of a ticket does not parse as YAML (first line "
                            "%r): reading the whole body as markdown, with none of the fence's "
                            "keys set — %s", first[:120], str(exc).splitlines()[0][:160])
                return {}, body
            return (fm if isinstance(fm, dict) else {}), parts[2]
    return {}, body


def _sections(md: str) -> list[tuple[str, str, str]]:
    """`(heading as written, heading normalised, body)` for each `## ` section, in order."""
    out: list[tuple[str, str, str]] = []
    heading: str | None = None
    buf: list[str] = []
    for line in md.splitlines():
        if line.startswith("## "):
            if heading is not None:
                out.append((heading, _normalise(heading), "\n".join(buf).strip()))
            heading, buf = line[3:].strip(), []
        elif heading is not None:
            buf.append(line)
    if heading is not None:
        out.append((heading, _normalise(heading), "\n".join(buf).strip()))
    return out


def section_names(body: str) -> list[str]:
    """The headings a ticket actually carries, AS WRITTEN, in order.

    As written and not normalised, because the reader of the resulting message has to find these
    headings in their own ticket — showing them `criterios de aceite` when they typed
    `Critérios de Aceite` would send them looking for a line that is not there."""
    _fm, md = _split_front_matter(body)
    return [written for written, _norm, _text in _sections(md)]


def _split_sections(md: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    for _written, norm, text in _sections(md):
        # An unrecognised heading keeps its own normalised name rather than being dropped, so a
        # future reader of this dict can see it was there. FIRST occurrence wins: a template that
        # repeats a heading is more likely to be describing than redefining.
        sections.setdefault(_CANONICAL.get(norm, norm), text)
    return sections


def _list_items(text: str) -> list[str]:
    """One string per `- ` bullet, with the lines a person wrapped it across joined back (#139).

    A WRAPPED BULLET LOST ITS TAIL IN SILENCE. This read one bullet per line, so a criterion wrapped
    to fit eighty columns kept its first line and dropped the rest — and the rest is usually the
    operative clause, the condition or the "must not". The count did not change, so nothing looked
    wrong: on one real ticket 11 of 25 criteria lost their tails, and one of them kept "create the
    file" while dropping "and never execute it". An indented line under a bullet is that bullet's,
    as Markdown reads it. A blank line ends it, and an indented `- ` is still a bullet of its
    own."""
    items: list[str] = []
    open_item = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
            open_item = True
        elif open_item and stripped and line[:1].isspace():
            items[-1] = f"{items[-1]} {stripped}"
        else:
            open_item = False
    return items


#: A Gherkin scenario's opening line, by what it MEANS (normalised as a heading is, so `Cenário:`,
#: `**Scenario:**` and `cenario:` are one). `Example` is Gherkin's own synonym for a scenario; on a
#: bullet with no steps under it, it is simply the criterion it always was.
_SCENARIO = ("scenario", "scenario outline", "scenario template", "example",
             "cenario", "esquema do cenario", "delineacao do cenario", "exemplo")
#: A step that BEGINS a scenario, and the steps that continue one. Case-sensitive, as Gherkin's
#: keywords are: a criterion that happens to open with the word "when" is not a step.
_GIVEN = ("Given", "Dado", "Dada", "Dados", "Dadas")
_STEP = ("When", "Then", "And", "But", "Quando", "Então", "Entao", "E", "Mas")
#: What else belongs to a scenario once it is open: its examples table and the heading over it.
_EXAMPLES = ("examples", "scenarios", "exemplos", "cenarios")


def _keyword(line: str) -> tuple[str, str, bool]:
    """`(kind, text, bulleted)` for one line of a criteria section. The text is the line without
    its bullet; the kind says whether it opens a scenario (`scenario`), begins one (`given`),
    continues one (`step`), belongs to one (`table`), or is a `bullet`, `prose` or `blank`."""
    stripped = line.strip()
    bulleted = stripped.startswith("- ")
    text = stripped[2:].strip() if bulleted else stripped
    if not text:
        return "blank", "", bulleted
    bare = text[4:] if text[:4] in ("[ ] ", "[x] ", "[X] ") else text
    label = _normalise(bare.split(":", 1)[0]) if ":" in bare else ""
    first = bare.split(None, 1)[0]
    if label in _SCENARIO:
        return "scenario", text, bulleted
    if first in _GIVEN:
        return "given", text, bulleted
    if first in _STEP:
        return "step", text, bulleted
    if label in _EXAMPLES or bare.startswith("|"):
        return "table", text, bulleted
    return ("bullet" if bulleted else "prose"), text, bulleted


def _criteria_items(text: str) -> list[str]:
    """The criteria in one criteria section — and ONE SCENARIO IS ONE CRITERION (#150).

    Two readings of Gherkin were both wrong. A `Scenario:` with its steps on plain lines parsed as
    NO criteria, so the gate refused a card the queue called ready. The same scenario written one
    `- ` per step parsed as THREE, and the reviewer, which maps each criterion to evidence, was
    asked whether `Given a statement that has been reconciled` had been met. A scenario is one
    promise: its text here is the whole scenario, one line per step, and that is what reaches the
    agent's brief and the reviewer.

    GHERKIN IS A SHAPE THIS READS, NOT ONE IT REQUIRES. Plenty of good criteria are not behaviour —
    a migration, a refactor, "tests cover each rule" — and they stay `- ` bullets, read as
    `_list_items` reads them. What opens a scenario is a `Scenario:` line or a `Given`; a `When` or
    a `Then` with nothing open is an ordinary criterion that starts with that word. A scenario ends
    at the next scenario, the next plain bullet or the next unindented sentence, and a `Given` after
    a `When` or `Then` starts the next one when no `Scenario:` line names them apart. A `Scenario:`
    line on its own, with no bullet and no step, is a sentence and not a criterion, and so is the
    code fence a person wraps a scenario in."""
    items: list[list[str]] = []
    counted: list[bool] = []
    state = ""      # "" | bullet | scenario | given (steps, no When/Then yet) | acted
    stepped: bool | None = None     # whether this scenario's steps are `- ` bullets
    for line in text.splitlines():
        kind, said, bulleted = _keyword(line)
        # A `- ` STEP UNDER PLAIN STEPS IS NOT THIS SCENARIO'S. Indented steps followed by `- When
        # the export fails, …` is a scenario and then a plain criterion that starts with "When".
        # The other way round is one scenario: a plain line indented under `- Given …` is inside
        # that bullet, which is exactly how `AcceptanceCriterion.bullet()` writes one.
        in_scenario = (state in ("scenario", "given", "acted")
                       and (not bulleted or stepped is not False))
        if kind == "blank":
            state = "" if state == "bullet" else state   # a scenario survives a blank line
        elif kind == "scenario":
            items.append([said])
            counted.append(bulleted)
            state, stepped = "scenario", None
        elif kind == "given" and not (in_scenario and state in ("scenario", "given")):
            items.append([said])
            counted.append(True)
            state, stepped = "given", bulleted
        elif kind in ("given", "step", "table") and in_scenario:
            items[-1].append(said)
            counted[-1] = counted[-1] or kind != "table"
            stepped = bulleted if stepped is None and kind != "table" else stepped
            state = "acted" if state == "given" and kind == "step" else state
        elif kind == "prose" and line[:1].isspace() and state:
            items[-1][-1] = f"{items[-1][-1]} {said}"
        elif bulleted:
            items.append([said])
            counted.append(True)
            state = "bullet"
        else:
            state = ""
    return ["\n".join(lines) for lines, keep in zip(items, counted, strict=True) if keep]


def criteria(body: str) -> list[str]:
    """The acceptance criteria a ticket body carries — THE platform's one opinion about it.

    The spec gate reads this through `parse_ticket_body`; triage, the queue and the product role's
    refine read it here. They used to search the body for substrings instead (`given `,
    `acceptance criteria`, `- [ ]`), so a card could be called ready by the queue and refused at
    pickup by the gate — the platform disagreeing with itself about one body of text (#150)."""
    _fm, md = _split_front_matter(body or "")
    return _criteria_items(_split_sections(md).get("acceptance criteria", ""))


def criteria_heading(body: str) -> str | None:
    """The criteria heading AS WRITTEN, or None when the body has none.

    What a refusal needs to tell *no criteria heading* from *a criteria heading with nothing under
    it that reads as a criterion* — two different fixes, and the refusal used to prescribe the first
    for both, telling a person to rename a heading to the name it already had."""
    _fm, md = _split_front_matter(body or "")
    return next((written for written, norm, _text in _sections(md)
                 if _CANONICAL.get(norm) == "acceptance criteria"), None)


def _same(text: str) -> str:
    """A section's text as an edit compares it: blank lines and trailing spaces are layout."""
    return "\n".join(line.rstrip() for line in (text or "").strip().splitlines() if line.strip())


def changed_sections(before: str, after: str) -> list[str]:
    """What an edit changed in a card's body, one name per part, in the order the card reads.

    THE NOTE AN EDIT LEAVES HAS TO SAY WHAT MOVED (#150). It said "edited the title and description"
    on every save — and the panel's form sends both on every save, so a card whose one criterion
    changed was recorded as rewritten top to bottom, and whoever read the thread could not tell what
    was different without diffing the card by hand.

    A section is compared by what it MEANS: `## Critérios de aceite` rewritten as `## Acceptance
    criteria` with the same items is not a change, and neither is a blank line. The names returned
    are the canonical keys (`objective`, `acceptance criteria`, …) for the sections the parser
    knows, the heading AS WRITTEN for one it does not, and `front matter` / `preamble` for the YAML
    fence and the text above the first heading. `[]` means the body says what it already said."""
    fm_before, md_before = _split_front_matter(before or "")
    fm_after, md_after = _split_front_matter(after or "")
    changed: list[str] = []
    if fm_before != fm_after:
        changed.append("front matter")

    def preamble(md: str) -> str:
        lines: list[str] = []
        for line in md.splitlines():
            if line.startswith("## "):
                break
            lines.append(line)
        return "\n".join(lines)

    if _same(preamble(md_before)) != _same(preamble(md_after)):
        changed.append("preamble")

    def by_meaning(md: str) -> dict[str, tuple[str, str]]:
        found: dict[str, tuple[str, str]] = {}
        for written, norm, text in _sections(md):
            key = _CANONICAL.get(norm, "")
            found.setdefault(key or norm, (written if not key else key, text))
        return found

    old, new = by_meaning(md_before), by_meaning(md_after)
    known = [key for key in _ALIASES if key in old or key in new]
    others = [key for key in [*new, *old] if key not in _ALIASES]
    for key in dict.fromkeys([*known, *others]):
        name = (new.get(key) or old.get(key))[0]
        if _same(old.get(key, ("", ""))[1]) != _same(new.get(key, ("", ""))[1]) or (
                (key in old) != (key in new)):
            changed.append(name)
    return changed


def parse_ticket_body(*, id: str, title: str, body: str, repo: str) -> Ticket:
    fm, md = _split_front_matter(body)
    s = _split_sections(md)
    return Ticket(
        id=id,
        title=title,
        objective=(s.get("objective") or title).strip(),
        context=s.get("context") or None,
        in_scope=_list_items(s.get("in scope", "")),
        out_of_scope=_list_items(s.get("out of scope", "")),
        acceptance_criteria=[
            AcceptanceCriterion(text=t) for t in _criteria_items(s.get("acceptance criteria", ""))
        ],
        depends_on=list(fm.get("depends_on", []) or []),
        relevant_docs=list(fm.get("relevant_docs", []) or []),
        repo=repo,
        base_branch=fm.get("base_branch"),
        requester=_requester(fm, md),
        requester_forge=_requester_forge(fm, md),
        raw=body,
    )


#: The prose labels older factory-written cards carry, normalised like the section headings are:
#: `**Pedido por:** <@U1>`, `**Reportado por:** <@U1>`, and ADR-0047's `Awaiting the acceptance of
#: <@U1>`. Read only when the front matter says nothing — the key is the record, the prose the past.
_REQUESTER_LABELS = ("pedido por", "reportado por", "requested by", "reported by",
                     "awaiting the acceptance of")


def _requester(fm: dict, md: str) -> str | None:
    """`requester:` in the front matter, else the first prose label a factory body wrote — and
    None, never a string, when what was written is the factory's own word for nobody."""
    from openfactory.contracts.ticket import NOBODY

    named = fm.get("requester")
    if isinstance(named, str) and named.strip():
        return named.strip() if named.strip().lower() not in NOBODY else None
    for line in md.splitlines():
        text = line.strip().replace("**", "")
        low = _normalise(text.split(":", 1)[0]) if ":" in text else _normalise(text)
        for label in _REQUESTER_LABELS:
            if low.startswith(label):
                value = text.split(":", 1)[1] if ":" in text else text[len(label):]
                # "U04ABC (octocat)" — the tracker identity rides in the parenthesis, read by
                # `_requester_forge`; the chat identity is what stands before it
                value = value.strip().rstrip(".").split(" (")[0].strip()
                # "Awaiting the acceptance of <@U1> (ADR-0047). Until then …" — the sentence
                # continues after the name, so the name is the first token there
                if label == "awaiting the acceptance of":
                    value = value.split()[0] if value.split() else ""
                return value if value and value.lower() not in NOBODY else None
    return None


def _requester_forge(fm: dict, md: str) -> str | None:
    """`requester_forge:` in the front matter, else the parenthesis on the `Pedido por` /
    `Reportado por` line (`**Pedido por:** U04ABC (octocat)`) — the body's own copy of the key,
    written because a fence does not survive a person editing the card in a vendor's rich editor
    (ADR-0048, refutation 11). None when nothing names one."""
    from openfactory.contracts.ticket import NOBODY

    named = fm.get("requester_forge")
    if isinstance(named, str) and named.strip():
        return named.strip() if named.strip().lower() not in NOBODY else None
    for line in md.splitlines():
        text = line.strip().replace("**", "")
        low = _normalise(text.split(":", 1)[0]) if ":" in text else ""
        if low and any(low.startswith(label) for label in _REQUESTER_LABELS[:4]):
            value = text.split(":", 1)[1].strip().rstrip(".")
            if " (" in value and value.endswith(")"):
                inner = value.rsplit(" (", 1)[1][:-1].strip()
                return inner if inner and inner.lower() not in NOBODY else None
            return None
    return None
