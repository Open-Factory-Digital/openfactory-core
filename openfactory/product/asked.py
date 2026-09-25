"""Has this been asked before — by whom, and where it lives (#33, slice 5).

"KNOWS EVERYTHING EVERYONE ASKED" IS NOT A TRANSCRIPT FEATURE. The truth about what was asked
lives in the BOARD (a ticket somebody filed), the REQUIREMENTS CORPUS (a promise somebody wrote
and who asked for it) and the OPEN LOOPS (a decision the role asked a person for) — three
places the product role already reads. Built on the transcript it would recognise a repeat only
in the SAME conversation, which is precisely the case it must catch across people: Ana asks on
Monday, Bruno asks on Thursday from another browser, and the right answer to Bruno is "this was
asked for already, it is #123, in To Do" — not a second draft of the same requirement. Not "Ana
asked for it": what Bruno may learn is that the request exists, never who else talks to the
product (ADR-0051 D9), so a conversation reads the section with `name_people=False`.

A STRUCTURED READ, NOT A MODEL PASS. Token overlap between the message and each candidate's
title, with the accents and the stopwords of both languages the clients write in taken out and
inflection folded by a five-letter stem (`relatório`/`relatórios`, `exportar`/`export`,
`mensal`/`mensais`). It is deliberately crude: its job is to put the two or three plausible
matches in front of the role WITH their references, so the role can say so and point — the
judgment of "is this the same request" stays the model's, and a miss costs nothing but the
section's absence. A false match is cheap too: the role reads the titles and disagrees.

AND THE WHOLE MEMORY, THROUGH THE INDEX (#269 slice 3, ADR-0053 D7). The three reads above are a
window: the board as a turn reads it, the decisions still open. "Was this done before?" is the
guardian's first question, and its answer is often years old — a card closed as not planned in
2022, a requirement dropped at a review, a document, a conversation distilled after it went quiet.
The module hands in what the product's index found for the message (`found`, the hits of
`index/retrieval.py::done_before`: requirements whatever became of them, closed cards of any age,
documents, distillates), searched BEFORE any lock and in the turn's own scope — the audience it may
be shown, a private conversation's distillate only to itself. Each hit is held to the same word
overlap as everything else here, and cited by what it is and when, never by who asked.

WHAT IT RETURNS IS RENDERED INTO THE PROMPT AS A SECTION, deterministically, before the pass —
the architecture every other fact here follows (ADR-0041's spirit, the knowledge layer's letter).
It answers "was this asked, by whom, where", never "is it done": what became of a ticket is the
board's own word (`state`, `column`), quoted and never inferred.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from openfactory.memory.ledger import DECISION, waiting

#: Words that carry no request. Both languages the clients write in, and the verbs of wanting —
#: "quero", "gostaria", "preciso", "want", "need" — which every request contains and no title does.
STOPWORDS = frozenset("""
a o os as um uma uns umas de do da dos das em no na nos nas por para com sem que e ou se nao
mais menos muito pouco ja tambem isso isto aqui ali la ele ela eles elas nos voces meu minha
seu sua nosso nossa este esta esse essa aquele aquela tem ter tinha temos ha havia foi ser sera
esta estao sao era vai vao pode podem poder fazer feito faz como quando onde qual quais quem
porque pois entao ainda so apenas cada todo toda todos todas outro outra novo nova
quero queria gostaria preciso precisamos queremos podemos poderia possivel favor
the a an of to and or in on at for with without by from is are was were be been being it its
this that these those there here we you they i he she them us our your my his her can could
should would will do does did have has had not no yes also just only more less very much
want wanted need needs like would please new make made get got
""".split())

#: A token this short says nothing on its own.
MIN_TOKEN = 3
#: Two stems agree when their first five letters do: `relatorio`/`relatorios`, `mensal`/`mensais`,
#: `export`/`exportar`. Shorter tokens must match whole.
STEM = 5
#: How much of the shorter side must overlap, and how many words at least. One shared word is a
#: coincidence; two on the same topic are a lead.
MIN_SCORE = 0.5
MIN_SHARED = 2
#: How many candidates the section carries. More is a list the role skims; three it reads.
LIMIT = 3


@dataclass(frozen=True)
class Match:
    kind: str       # ticket | requirement | decision | document | conversation
    ref: str        # `#123` | `REQ-0007` | the decision's key | where the document is
    title: str
    where: str      # column and state | the requirement's path | when and in which channel
    who: str = ""   # who asked, when the source records it
    score: float = 0.0
    shared: int = 0  # how many words agreed — the tie-breaker between two full-score leads


def tokens(text: str) -> set[str]:
    """The words that carry meaning: lower-cased, unaccented, stopwords out, short ones out."""
    folded = unicodedata.normalize("NFKD", str(text or ""))
    plain = "".join(c for c in folded if not unicodedata.combining(c)).lower()
    return {w for w in re.split(r"[^a-z0-9]+", plain)
            if len(w) >= MIN_TOKEN and w not in STOPWORDS}


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    return len(a) >= STEM and len(b) >= STEM and a[:STEM] == b[:STEM]


def overlap(query: set[str], candidate: set[str]) -> tuple[int, float]:
    """`(shared words, share of the shorter side)` — the shorter side, so a two-word request
    against a long body scores on the request and a long request against a short title scores
    on the title."""
    if not query or not candidate:
        return 0, 0.0
    shared = sum(1 for q in query if any(_same(q, c) for c in candidate))
    return shared, shared / min(len(query), len(candidate))


def already_asked(text: str, *, cards=None, corpus=None, loops=(), found=(),
                  limit: int = LIMIT) -> list[Match]:
    """The strongest matches for `text` across the board, the corpus, the open decisions and what
    the product's index `found` — best first, at most `limit`. Empty when nothing plausible was
    asked before."""
    query = tokens(text)
    if not query:
        return []
    matches: list[Match] = []
    for card in cards or ():
        title = str(getattr(card, "title", "") or "").strip()
        body = str(getattr(card, "body", "") or "")[:400]
        shared, score = _best(query, tokens(title), tokens(f"{title} {body}"))
        if _plausible(shared, score):
            state = str(getattr(card, "state", "") or "")
            reason = str(getattr(card, "state_reason", "") or "")
            column = str(getattr(card, "column", "") or "").strip() or "no column"
            where = f"{column}, {state}{' as ' + reason if reason else ''}" if state else column
            matches.append(Match("ticket", f"#{getattr(card, 'number', '?')}", title, where,
                                 who=", ".join(str(a) for a in (getattr(card, "assignees", None)
                                                                or ())),
                                 score=score, shared=shared))
    for req in getattr(corpus, "requirements", None) or ():
        title = str(getattr(req, "title", "") or "").strip() or str(getattr(req, "slug", ""))
        slug = str(getattr(req, "slug", "") or "").replace("-", " ")
        shared, score = _best(query, tokens(title), tokens(f"{title} {slug}"))
        if _plausible(shared, score):
            number = getattr(req, "number", 0) or 0
            status = str(getattr(req, "status", "") or "")
            superseded = getattr(req, "superseded_by", None)
            where = str(getattr(req, "path", "") or "") + (f" ({status})" if status else "")
            if superseded:
                where += f", superseded by REQ-{int(superseded):04d}"
            matches.append(Match("requirement", f"REQ-{int(number):04d}", title, where,
                                 who=str(getattr(req, "asked_by", "") or ""), score=score,
                                 shared=shared))
    for loop in waiting(list(loops), kind=DECISION):
        asked = str((loop.context or {}).get("asked", "") or "").strip()
        shared, score = _best(query, tokens(asked), tokens(f"{asked} {loop.subject}"))
        if _plausible(shared, score):
            when = (loop.ts or "")[:10]
            where = f"a decision still open, asked {when or 'at an unknown date'}"
            if loop.about:
                where += f" in {loop.about}"
            matches.append(Match("decision", loop.subject, asked or loop.subject, where,
                                 score=score, shared=shared))
    # THE WHOLE MEMORY (ADR-0053 D7): what the index found, where the three reads above did not
    # already say it — the board's window and the corpus name a card or a requirement first
    listed = {m.ref for m in matches}
    for hit in _every(found):
        match = _from_the_index(query, hit)
        if match is not None and match.ref not in listed:
            listed.add(match.ref)
            matches.append(match)
    # BEST FIRST: the share of the shorter side, then how many words agreed — two leads that
    # both cover a short title whole are told apart by which one the request has more of.
    matches.sort(key=lambda m: (-m.score, -m.shared, m.kind, m.ref))
    return matches[:limit]


def _every(found):
    """Each hit, and each item listed under one — what a live requirement replaced is the likeliest
    "this was asked before" of all."""
    for hit in found or ():
        yield hit
        yield from getattr(hit, "history", None) or ()


#: How an index item's standing is said, beside where it is.
_STANDING = {"superseded": "superseded", "dropped": "dropped", "unreadable": "could not be read"}


def _from_the_index(query: set[str], hit) -> Match | None:  # noqa: C901 — one branch per kind
    """One hit of the product's index as a lead — or None when it shares too little with the
    request, or is of a kind nothing is asked in. Cited by what it is and when: the index keeps
    nobody's name, and none is added here."""
    kind = str(getattr(hit, "kind", "") or "")
    title = " ".join(str(getattr(hit, "title", "") or "").split())
    text = str(getattr(hit, "text", "") or "")
    shared, score = _best(query, tokens(title), tokens(f"{title} {text}"))
    if not _plausible(shared, score):
        return None
    date = str(getattr(hit, "date", "") or "")[:10]
    dated = f", dated {date}" if date else ", undated"
    status = str(getattr(hit, "status", "") or "")
    said = _STANDING.get(status, "")
    successors = tuple(getattr(hit, "successors", ()) or ())
    if status == "superseded" and successors:
        said = "superseded by " + ", ".join(f"REQ-{int(n):04d}" for n in successors)
    number = getattr(hit, "number", None)
    source = str(getattr(hit, "source", "") or "")
    if kind == "requirement" and number is not None:
        name = title.split(" — ", 1)[-1]
        return Match("requirement", f"REQ-{int(number):04d}", name,
                     f"{source} ({said or 'current'}){dated}", score=score, shared=shared)
    if kind == "card":
        ref, _, name = title.partition(" — ")
        how = str(getattr(hit, "origin", "") or "").removeprefix("the board — ")
        where = f"{how}, last moved {date or 'at an unknown date'}"
        if said:
            where += f"; what it cited was {said}"
        return Match("ticket", ref.strip() or source, name.strip() or title, where, score=score,
                     shared=shared)
    if kind == "decision":
        if number is not None:
            ref, where = f"REQ-{int(number):04d}", (f"a decision in the register of "
                                                   f"REQ-{int(number):04d}{dated}")
        else:
            ref, where = f"`{source}`", (f"a decision a model read in `{source}`{dated} — cite "
                                         f"the document")
        if said:
            where += f" ({said})"
        return Match("decision", ref, " ".join(text.split())[:200], where, score=score,
                     shared=shared)
    if kind == "distillate":
        said_there = " ".join(line.strip(" -#") for line in text.splitlines()
                              if line.strip() and not line.lstrip().startswith("#"))
        where = (f"what a conversation came to, as a model distilled it{dated} — evidence of what "
                 f"was said, never a decision")
        return Match("conversation", f"`{source}`", said_there[:200] or title, where,
                     score=score, shared=shared)
    if kind == "document":
        origin = str(getattr(hit, "origin", "") or "").split(",")[0]
        return Match("document", f"`{source}`", title or source,
                     f"{origin}{dated}" + (f" ({said})" if said else ""), score=score,
                     shared=shared)
    return None




def _best(query: set[str], *candidates: set[str]) -> tuple[int, float]:
    return max((overlap(query, c) for c in candidates), key=lambda t: (t[1], t[0]),
               default=(0, 0.0))


def _plausible(shared: int, score: float) -> bool:
    return shared >= MIN_SHARED and score >= MIN_SCORE


def render(matches: list[Match], *, name_people: bool = True) -> str:
    """The prompt section — or "" when there is nothing to say, so no section is drawn.

    `name_people=False` is how a CONVERSATION reads it (ADR-0051 D9, `ProductModule.already_asked`):
    a match was asked for by somebody, usually in another conversation, and the role never names a
    person from outside the one it is in — not even when the saved record names its requester, as
    a requirement's front matter does. What was asked, and where it lives, is what crosses."""
    if not matches:
        return ""
    lines = [
        "# Possibly already asked (checked for you across the board, the requirements and the "
        "open decisions — and the product's memory: its closed cards of any age, its dropped and "
        "superseded requirements, its documents and its distilled conversations)",
        "",
        "If one of these IS what the person is asking for, say so and point at it by its "
        "reference — do not draft it again. If none is, ignore this list; it is a lead, not a "
        "verdict.",
        "",
    ]
    for m in matches:
        who = f", asked by {m.who}" if m.who and name_people else ""
        lines.append(f"- {m.kind} {m.ref} «{m.title}» — {m.where}{who}")
    return "\n".join(lines) + "\n"
