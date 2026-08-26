"""What the product role has LEARNED about the business — the third kind of artefact, and the one
that has to be kept furthest from the other two.

    a requirement   is a DECISION we made          "a reconciled statement cannot change"
    the code map    is DERIVED from ground truth   "that rule lives in rules.py"
    a fact          is TRUE OR FALSE about the world "the law requires five years of retention"

A fact is not ours to decide, which is exactly what makes it safe to write down: it can be
attributed, and it can be checked. It is also what makes it dangerous to confuse with a requirement,
because the factory DEFENDS requirements — and a sentence somebody said in a channel is not
something to defend.

SO THE SAME DISCIPLINE, A THIRD TIME. `observed` is not `accepted` for a requirement; `learned` is
not `confirmed` for a fact. Anything picked up from a conversation lands as `learned`: attributed,
usable, and never authoritative. Someone with the product in their head confirming it is the only
event that changes that.

ATTRIBUTION IS NOT OPTIONAL. A fact with no source is a rumour with formatting, and it is worse than
no fact at all — it reads exactly like the ones that are true, and nobody can go back and ask.

AND THE PROBLEM WE CANNOT SOLVE, STATED RATHER THAN HIDDEN. A requirement can be superseded; a code
map has checksums. A fact about the world just quietly stops being true — the law changes, the
client's process changes — and nothing here will notice. Every entry therefore carries the date it
was learned, an old unconfirmed one is treated with less confidence, and the oldest are surfaced for
review. That converts "rots invisibly" into "shows up for somebody to decide", which is the most
this design can honestly claim.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

LEARNED, CONFIRMED, RETIRED = "aprendido", "confirmado", "aposentado"
_KNOWN_STATUS = {LEARNED, CONFIRMED, RETIRED}

#: `### term` starts an entry. A heading rather than a table row because a term's explanation runs
#: to a paragraph, and because a human has to be able to edit this by hand without counting pipes.
_ENTRY_RE = re.compile(r"^###\s+(?P<term>.+?)\s*$", re.MULTILINE)


def _field(block: str, name: str) -> str:
    m = re.search(rf"^\s*[-*]\s*\**{name}:?\**\s*:?\s*(?P<v>.*?)\s*$",
                  block, re.MULTILINE | re.IGNORECASE)
    return re.sub(r"<!--.*?-->", "", m.group("v")).strip() if m else ""


#: After how long an unconfirmed fact is worth asking about again. Not a truth — a prompt. Long
#: enough that a busy month does not generate a review queue nobody asked for.
STALE_DAYS = 120


class Fact(BaseModel):
    """One thing the role believes about the business, and where it got it."""

    term: str
    body: str = ""
    status: str = LEARNED
    #: who said it. A name, because "the channel" cannot be gone back to and asked.
    source: str = ""
    #: where it was said — a permalink, so a reader can see the whole exchange rather than a
    #: sentence somebody lifted out of it
    where: str = ""
    learned_on: str = ""
    path: str = ""

    @property
    def authoritative(self) -> bool:
        """Whether this may be stated as fact rather than as something somebody said. Only a
        confirmed entry qualifies: everything else is attributed when it is used."""
        return self.status == CONFIRMED

    @property
    def live(self) -> bool:
        return self.status != RETIRED

    def age_days(self, today: date | None = None) -> int | None:
        try:
            then = date.fromisoformat(self.learned_on)
        except (ValueError, TypeError):
            return None
        return max(0, ((today or date.today()) - then).days)

    def stale(self, today: date | None = None) -> bool:
        """Old, unconfirmed, and therefore worth asking about — never worth deleting on its own."""
        age = self.age_days(today)
        return self.status == LEARNED and age is not None and age > STALE_DAYS


class Finding(BaseModel):
    level: str
    code: str
    term: str
    message: str


class Domain(BaseModel):
    facts: list[Fact] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)

    def live(self) -> list[Fact]:
        return [f for f in self.facts if f.live]

    def confirmed(self) -> list[Fact]:
        return [f for f in self.facts if f.authoritative and f.live]

    def stale(self, today: date | None = None) -> list[Fact]:
        return [f for f in self.live() if f.stale(today)]

    def get(self, term: str) -> Fact | None:
        want = (term or "").strip().lower()
        return next((f for f in self.facts if f.term.strip().lower() == want), None)

    def summary(self) -> str:
        live = self.live()
        conf = len([f for f in live if f.authoritative])
        return (f"{len(live)} termos ({conf} confirmados, {len(live) - conf} aprendidos), "
                f"{len(self.stale())} para revisar")


def parse_facts(text: str, *, path: str = "") -> tuple[list[Fact], list[Finding]]:
    """Every `### term` block in one file. Never raises: a malformed entry is a finding, and one
    bad block must not cost the file."""
    facts: list[Fact] = []
    findings: list[Finding] = []
    marks = list(_ENTRY_RE.finditer(text or ""))
    for i, m in enumerate(marks):
        term = m.group("term").strip()
        block = (text[m.end(): marks[i + 1].start()] if i + 1 < len(marks) else text[m.end():])
        status = (_field(block, "Status") or LEARNED).lower()
        if status not in _KNOWN_STATUS:
            findings.append(Finding(level="error", code="status-unknown", term=term,
                                    message=f"status {status!r} desconhecido; tratado como "
                                            f"{LEARNED!r}"))
            status = LEARNED
        source = _field(block, "Fonte") or _field(block, "Source")
        fact = Fact(
            term=term, status=status, source=source,
            where=_field(block, "Onde") or _field(block, "Where"),
            learned_on=_field(block, "Data") or _field(block, "Date"),
            body=_body_of(block), path=path,
        )
        if not source:
            # A fact with no source is a rumour with formatting: it reads exactly like the true
            # ones, and nobody can go back and ask.
            findings.append(Finding(level="error", code="no-source", term=term,
                                    message="sem fonte — não dá para voltar e perguntar a ninguém"))
        if not fact.learned_on:
            findings.append(Finding(level="warn", code="no-date", term=term,
                                    message="sem data, então não há como saber se envelheceu"))
        facts.append(fact)
    return facts, findings


def _body_of(block: str) -> str:
    """The prose, with the metadata bullets stripped."""
    lines = [ln for ln in block.splitlines()
             if not re.match(r"^\s*[-*]\s*\**(status|fonte|source|onde|where|data|date)\b",
                             ln, re.IGNORECASE)]
    return "\n".join(lines).strip()


def load_domain(directory: str | Path) -> Domain:
    """Every fact under a directory. A missing directory is an empty Domain, not an error: a
    product that has not been talked about yet is the normal starting state."""
    root = Path(directory)
    if not root.is_dir():
        return Domain()
    facts: list[Fact] = []
    findings: list[Finding] = []
    seen: dict[str, str] = {}
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.suffix != ".md":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(Finding(level="error", code="unreadable", term=path.name,
                                    message=str(exc)))
            continue
        parsed, found = parse_facts(text, path=path.name)
        findings += found
        for fact in parsed:
            key = fact.term.strip().lower()
            if key in seen:
                # Two entries for one term is the failure that matters here: whichever the reader
                # finds first wins, and they may say different things.
                findings.append(Finding(
                    level="error", code="duplicate-term", term=fact.term,
                    message=f"já definido em {seen[key]} — duas respostas para a mesma pergunta"))
                continue
            seen[key] = path.name
            facts.append(fact)
    return Domain(facts=facts, findings=findings)


def render_fact(fact: Fact) -> str:
    """One entry, in the shape a human edits by hand."""
    return "\n".join([
        f"### {fact.term}",
        "",
        f"- **Status:** {fact.status}",
        f"- **Fonte:** {fact.source or 'não registrada'}",
        f"- **Onde:** {fact.where or '—'}",
        f"- **Data:** {fact.learned_on or 'não registrada'}",
        "",
        fact.body.strip() or "(sem descrição)",
        "",
    ])


def render_file(facts: list[Fact], *, title: str, intro: str = "") -> str:
    """A whole file, regenerated from its entries. Sorted, so a batch of new terms produces a diff
    a person can read instead of a reshuffle."""
    head = [f"# {title}", ""]
    if intro:
        head += [intro, ""]
    head += [
        "> **`aprendido` não é `confirmado`.** Uma entrada aprendida veio de uma conversa e está "
        "atribuída a quem disse — é utilizável, nunca autoritativa. Só alguém que conhece o "
        "produto confirmando muda isso.",
        "",
    ]
    body = [render_fact(f) for f in sorted(facts, key=lambda f: f.term.lower())]
    return "\n".join(head + body)


def glossary_index(domain: Domain, *, limit: int = 200) -> str:
    """The terms, for a prompt: what is known and how much to trust each one.

    Compact on purpose — the definitions live in the checkout and the role opens the ones it needs,
    exactly as it does with requirements."""
    live = domain.live()
    if not live:
        return "(ainda não há vocabulário registrado sobre este produto)"
    rows = ["| termo | status | fonte |", "|---|---|---|"]
    for f in sorted(live, key=lambda x: x.term.lower())[:limit]:
        rows.append(f"| {f.term} | {f.status} | {f.source or '—'} |")
    return "\n".join(rows)
