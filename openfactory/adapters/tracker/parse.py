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

import unicodedata

import yaml

from openfactory.contracts import AcceptanceCriterion, Ticket

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
        "criterios de aceite", "criterio de aceite",
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
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) == 3:
            fm = yaml.safe_load(parts[1]) or {}
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
    return [ln[2:].strip() for ln in text.splitlines() if ln.strip().startswith("- ")]


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
            AcceptanceCriterion(text=t) for t in _list_items(s.get("acceptance criteria", ""))
        ],
        depends_on=list(fm.get("depends_on", []) or []),
        relevant_docs=list(fm.get("relevant_docs", []) or []),
        repo=repo,
        base_branch=fm.get("base_branch"),
        raw=body,
    )
