"""The query pipeline: metadata filters → lexical → semantic → re-rank, and the supersession rule
(#269 slice 2, ADR-0053 D3, D5, D9, D10, D12).

FILTERS FIRST, IN THE QUERY ITSELF (D10). The product, the audience and — for a line of a
conversation, and for a conversation's distillate — whose conversation it is and whether it was
said to the role are a WHERE clause on every read this module makes: the full-text match, the
vector scan, the requirements the supersession rule reads and the successor it pulls in. A hit the
conversation may not read is never a candidate, so nothing ranked, fused or rendered can carry it:
a filter applied after ranking leaks through the answer built from the hits; one applied before it
has nothing to leak. A room is filtered for everybody in it: its audience is the client's, whoever
asked (`turn_audience`).

LEXICAL, THEN SEMANTIC (ADR-0024 §5's order, D9). SQLite's FTS5 with BM25 over the title, the text
and the item's exact references; then, when the deployment has an embedder, the cosine of the
query's vector with every filtered item's. Without one the search still runs — words, metadata and
time — and `Found.degraded` says so, on every search, in the words the role reads.

THE RE-RANK, DECIDED HERE (ADR-0053 "Left open"): an EXACT-TERM TIER, then RECIPROCAL RANK FUSION.

  - The tier: how many of the query's exact terms the item carries — a requirement number
    ("requirement 41", "REQ-0041"), a card ("#512", "card 512"), a quoted phrase, or a name the
    index holds rarely (a client's, a system's). An item in a higher tier comes first whatever its
    fused score. That is what makes "exact terms beat semantic neighbours" a property of the
    order, not of a tuned weight: an embedding places #512 near #513 and near every statement
    about statements, and the one card the person named must not lose to them by a decimal.
  - Within a tier, RRF (k = 60): each stage contributes 1/(60 + rank). No calibration between
    BM25's scale and a cosine's, no second model per turn (a cross-encoder re-ranker is a model
    call paid on every search — the cost ADR-0053 says must be measured before it is spent), and
    it is deterministic, so a test can pin an order.
  - Then the newest first, as the last tie-breaker.

SUPERSESSION, AT READ TIME (D3). A superseded item is NEVER HANDED OVER AS CURRENT: it is returned
only in the `history` of what superseded it, marked, and the search pulls the successor in when the
query did not match it. What is superseded is read from the curated truth — the corpus's
`superseded-by` — and never guessed:

  - a requirement superseded by another, and every row of its decision register, are superseded by
    the live end of its chain;
  - a document, each decision a model read in it, a closed card and a conversation's distillate,
    that cite requirements of which NONE is live are superseded by the successors of the ones that
    were superseded — or, when they were all dropped, are `dropped` themselves. One that cites a
    live requirement speaks for today, even if it also names the old one (the minutes that reversed
    a decision cite both); the card that built the 2021 rule is history once the rule is.

Computed when the search reads, because the corpus can supersede a requirement without any document
changing. A superseded item whose successor cannot be shown to this conversation is not listed at
all — counted in `Found.withheld` — because the rule is "only together with what replaced it".

NEVER UNDER THE SEMAPHORE (ADR-0053 D7): the search refuses to run while the product's semaphore
on what becomes work is held (`semaphore.refuse_a_model_here`) — its semantic stage is a model, and
the lock is for a comparison and a write.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field

from openfactory.contracts.document import AUDIENCES, CLIENT, may_read
from openfactory.product.index.items import (
    CARD,
    CURRENT,
    DECISION,
    DISTILLATE,
    DOCUMENT,
    DROPPED,
    REQUIREMENT,
    SUPERSEDED,
    UNREADABLE,
    conversation_digest,
)
from openfactory.product.index.store import Index, ref_token, unpack

log = logging.getLogger("openfactory.product.index")

#: Reciprocal rank fusion's constant — the one the method was published with; it damps the lead of
#: a first place so two stages that agree beat one that is sure.
RRF_K = 60
#: How many candidates each stage hands to the fusion.
CANDIDATES = 100
DEFAULT_LIMIT = 8
#: A semantic neighbour below this cosine is not a candidate: a query about nothing the product
#: holds must come back empty, not with the eight least-unrelated things in it.
SEMANTIC_FLOOR = 0.3
#: How much of an item a hit carries, and how many superseded items one hit lists under it.
EXCERPT_CHARS = 700
HISTORY_PER_HIT = 4
#: A name counts as an exact term only while it is rare in the index — a client's name is; "invoice"
#: in an invoicing product is not. At most this many items, or this share of them.
NAME_MAX_ITEMS = 8
NAME_MAX_SHARE = 0.05
#: How far a chain of supersessions is followed before it is called broken.
MAX_CHAIN = 20


@dataclass(frozen=True)
class Query:
    """One search. `audience` is who may be shown the hits (`documents/record.py::turn_audience`);
    `own` the key of the conversation searching — a private conversation's lines come back only
    to it; `exclude` a conversation left out (the one already in the prompt); `overheard` whether
    a line said in a group to somebody else may be a hit — only for a search somebody asked for
    (ADR-0053 D12), never for the engine's own before a turn."""

    text: str
    audience: str = CLIENT
    own: str = ""
    exclude: str = ""
    overheard: bool = False
    limit: int = DEFAULT_LIMIT
    kinds: tuple[str, ...] = ()


@dataclass
class Hit:
    """One item found, with everything its citation needs and how it was ranked."""

    id: str
    grp: str
    kind: str
    source: str
    title: str
    text: str
    date: str
    date_from: str
    origin: str
    audience: str
    status: str
    locator: str = ""
    requirements: tuple[int, ...] = ()
    cards: tuple[str, ...] = ()
    #: the requirement's own number, for a requirement item
    number: int | None = None
    #: the live requirements that superseded it — set for a superseded or history item
    successors: tuple[int, ...] = ()
    addressed: bool = True
    exact: int = 0
    score: float = 0.0
    lexical: int | None = None
    semantic: int | None = None
    #: not matched by the query: here because it superseded a hit
    pulled: bool = False
    #: what this item superseded, oldest first — shown with it, never on its own
    history: list[Hit] = field(default_factory=list)


@dataclass
class Found:
    query: Query
    hits: list[Hit]
    #: why the semantic stage did not run, or ran on part of the index — "" when it ran whole
    degraded: str = ""
    embedder: str = ""
    #: superseded items that matched and whose successor could not be shown — never listed
    withheld: int = 0
    #: items the filters let this conversation search, and how many of them have no vector yet
    searched: int = 0
    unembedded: int = 0


# ── exact terms ─────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Exact:
    requirements: frozenset[int] = frozenset()
    cards: frozenset[str] = frozenset()
    phrases: tuple[str, ...] = ()
    names: tuple[str, ...] = ()


_QUOTED = re.compile(r"[\"“”«»]([^\"“”«»\n]{3,80})[\"“”«»]")
_CAPITALISED = re.compile(r"(?<![\w#])([A-ZÀ-Ý][\w'’-]{2,}|[A-Z]{2,}\d*)(?![\w])")
#: Capitalised words that are not names: a question's first word, the references' own words.
_NOT_NAMES = frozenset("""
what when where which who whom whose why how the this that these those is are was were do does did
can could should would will shall may might and but for with about from into today yesterday please
hello hi dear thanks thank our your their its there here then also any all some none each every
req requirement requirements card cards ticket tickets issue issues document documents decision
decisions minutes email mail
o a os as um uma que qual quais quando onde como por porque quem hoje ontem oi ola obrigado
obrigada bom boa dia tarde noite sobre para com sem isso isto esse essa este esta requisito
requisitos cartao cartoes decisao decisoes documento documentos ata atas
""".split())


def fold(text: str) -> str:
    """Lower-cased, accents stripped — how two spellings of one word are compared."""
    flat = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in flat if not unicodedata.combining(c)).lower()


def exact_terms(text: str) -> Exact:
    """The query's exact terms: requirement numbers and card refs as slice 1 reads them in a
    document (`documents/record.py`), quoted phrases, and capitalised words that may be names —
    which of those ARE names the index decides (`_rare_names`)."""
    from openfactory.product.documents.record import cards_cited, requirements_cited

    phrases = tuple(dict.fromkeys(m.group(1).strip() for m in _QUOTED.finditer(text or "")))
    names = tuple(dict.fromkeys(
        word for word in (m.group(1) for m in _CAPITALISED.finditer(text or ""))
        if fold(word) not in _NOT_NAMES and not word.upper().startswith("REQ")))
    return Exact(requirements=frozenset(requirements_cited(text or "")),
                 cards=frozenset(c.lower() for c in cards_cited(text or "")), phrases=phrases,
                 names=names)


def _quote(word: str) -> str:
    """A word as an FTS5 string — whatever a person typed stays a word, never an operator."""
    return '"' + word.replace('"', '""') + '"'


def _rare_names(con: sqlite3.Connection, exact: Exact, total: int, where: str,
                params: list) -> tuple[str, ...]:
    """The capitalised words of the query that are rare among what THIS conversation may search —
    counted under the same filter as every other read, so what a conversation may not see cannot
    change how its own search is ordered."""
    ceiling = max(NAME_MAX_ITEMS, int(total * NAME_MAX_SHARE))
    kept = []
    for name in exact.names:
        words = re.findall(r"\w+", fold(name))
        if not words:
            continue
        phrase = '"' + " ".join(words).replace('"', '""') + '"'
        try:
            seen = con.execute(
                f"SELECT count(*) FROM fts JOIN items ON items.rowid = fts.rowid "  # nosec B608
                f"WHERE fts MATCH ? AND {where}", [phrase, *params]).fetchone()
        except sqlite3.OperationalError:
            continue
        if 0 < int(seen[0]) <= ceiling:
            kept.append(name)
    return tuple(kept)


def _exact_tier(row: sqlite3.Row, exact: Exact) -> int:
    """How many of the query's exact terms the item carries — and the item that IS the requirement
    or the card named counts twice, so "requirement 41" is answered by REQ-0041 before every
    document that cites it."""
    number = _number(row)
    cited = set(_ints(row["requirements"]))
    tier = sum(2 if n == number else 1 for n in exact.requirements if n == number or n in cited)
    cards = {c.lower().lstrip("#") for c in str(row["cards"]).split()}
    itself = row["kind"] == CARD
    tier += sum(2 if itself else 1 for c in exact.cards if c in cards)
    if exact.phrases or exact.names:
        hay = fold(f"{row['title']}\n{row['text']}")
        tier += sum(1 for phrase in exact.phrases if fold(phrase) in hay)
        tier += sum(1 for name in exact.names
                    if re.search(rf"(?<!\w){re.escape(fold(name))}(?!\w)", hay))
    return tier


def _ints(spelled: object) -> list[int]:
    return [int(x) for x in str(spelled or "").split() if x.isdigit()]


# ── the filters ─────────────────────────────────────────────────────────────────────────────────

def _filters(key: str, query: Query) -> tuple[str, list]:
    """The WHERE clause every read of this module carries — see the module's docstring."""
    allowed = [label for label in AUDIENCES if may_read(label, query.audience)]
    clauses = ["items.product = ?", f"items.audience IN ({','.join('?' * len(allowed))})",
               # a line of a conversation: somebody's private one only to it, a line said to
               # somebody else only when a person or the role asked for a search, and the
               # conversation already in front of the role not at all
               "(items.kind != 'turn' OR ((items.private = 0 OR items.conversation = ?) "
               "AND (? = 1 OR items.addressed = 1) AND items.conversation != ?))",
               # a conversation's distillate: a private conversation's only to it (#269 slice 3)
               "(items.kind != 'distillate' OR items.private = 0 OR items.conversation = ?)"]
    params: list = [key, *allowed, conversation_digest(query.own) or "-",
                    1 if query.overheard else 0, conversation_digest(query.exclude) or "-",
                    conversation_digest(query.own) or "-"]
    if query.kinds:
        clauses.append(f"items.kind IN ({','.join('?' * len(query.kinds))})")
        params += list(query.kinds)
    return " AND ".join(clauses), params


# ── the stages ──────────────────────────────────────────────────────────────────────────────────

#: The words a question is built from and no answer is about — "what HOLDS TODAY about X?" is a
#: question about X, and an item that happens to say "an account holds…" is not an answer to it.
#: Both languages the clients write in.
_ASKING = frozenset("""
hold holds held today now currently current still anymore tell know say said says mean means
give show find look search please regarding concerning
vale valem hoje agora atual atualmente ainda diz dizer sabe saber mostra mostrar procura
procurar busca buscar favor respeito
""".split())


def _lexical(con: sqlite3.Connection, query: Query, exact: Exact, where: str,
             params: list) -> list[int]:
    from openfactory.memory.recall import tokens

    words = [w for w in dict.fromkeys(tokens(query.text)) if w not in _ASKING]
    words += [ref_token("req", n) for n in sorted(exact.requirements)]
    words += [ref_token("card", c) for c in sorted(exact.cards)]
    if not words:
        return []
    match = " OR ".join(_quote(w) for w in dict.fromkeys(words))
    rows = con.execute(
        f"SELECT items.rowid FROM fts JOIN items ON items.rowid = fts.rowid "  # nosec B608
        f"WHERE fts MATCH ? AND {where} ORDER BY bm25(fts, 2.0, 1.0, 10.0) LIMIT ?",
        [match, *params, CANDIDATES]).fetchall()
    return [int(r[0]) for r in rows]


def _cosines(query: list[float], rows: list[sqlite3.Row]) -> list[tuple[float, int]]:
    """`(cosine, rowid)` for every row — numpy when it is installed (the `embed` extra brings it),
    `math.sumprod` when it is not. Vectors are stored unit-length, so a dot product is a cosine."""
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None and rows:
        matrix = np.frombuffer(b"".join(r[1] for r in rows), dtype="<f4").reshape(len(rows), -1)
        scores = matrix @ np.asarray(query, dtype="<f4")
        return [(float(s), int(r[0])) for s, r in zip(scores, rows, strict=True)]
    return [(math.sumprod(query, unpack(r[1])), int(r[0])) for r in rows]


def _semantic(con: sqlite3.Connection, query: Query, where: str, params: list,
              embedder) -> tuple[list[int], str]:
    """The candidates by meaning, best first — and why there are none, when there cannot be."""
    made_by = Index.meta(con, "embedder")
    if made_by and made_by != embedder.id:
        return [], (f"the index's vectors were made by {made_by}, not by this deployment's "
                    f"{embedder.id}; they are being made again")
    try:
        vector = embedder.embed([query.text])[0]
    except Exception:  # noqa: BLE001 — the words still find what they find
        log.warning("the %s row failed on a query", embedder.id, exc_info=True)
        return [], (f"the {embedder.id} row failed on the query (the reason is in the "
                    f"platform's log)")
    size = 4 * len(vector)
    rows = con.execute(f"SELECT items.rowid, items.vector FROM items WHERE {where} "  # nosec B608
                       f"AND items.vector IS NOT NULL AND length(items.vector) = ?",
                       [*params, size]).fetchall()
    scored = sorted((s for s in _cosines(vector, rows) if s[0] >= SEMANTIC_FLOOR),
                    reverse=True)[:CANDIDATES]
    return [rowid for _score, rowid in scored], ""


# ── supersession ────────────────────────────────────────────────────────────────────────────────

def _number(row: sqlite3.Row) -> int | None:
    """The requirement an item is, or is a row of the register of — read off its group."""
    match = re.match(r"^req:(\d+)$", str(row["grp"]))
    return int(match.group(1)) if match else None


def _ends(number: int | None, requirements: dict[int, sqlite3.Row]) -> tuple[int, ...]:
    """The live requirement at the end of `number`'s chain of successors — `()` when the chain
    breaks, loops, or ends in one nobody may be shown."""
    seen: set[int] = set()
    here = number
    while here is not None and here not in seen and len(seen) < MAX_CHAIN:
        seen.add(here)
        row = requirements.get(here)
        if row is None:
            return ()
        if row["status"] != SUPERSEDED:
            return (here,) if row["status"] == CURRENT else ()
        here = row["successor"]
    return ()


def _standing(row: sqlite3.Row,
              requirements: dict[int, sqlite3.Row]) -> tuple[str, tuple[int, ...]]:
    """`(status, successors)` of one item as of this read — see the module's docstring."""
    status = str(row["status"])
    if row["kind"] == REQUIREMENT or str(row["grp"]).startswith("req:"):
        if status == SUPERSEDED:
            return SUPERSEDED, _ends(row["successor"], requirements)
        return status, ()
    if row["kind"] in (DOCUMENT, DECISION, CARD, DISTILLATE) and status != UNREADABLE:
        cited = [n for n in _ints(row["requirements"]) if n in requirements]
        if cited and not any(requirements[n]["status"] == CURRENT for n in cited):
            replaced = [n for n in cited if requirements[n]["status"] == SUPERSEDED]
            if replaced:
                ends = tuple(dict.fromkeys(e for n in replaced
                                           for e in _ends(requirements[n]["successor"],
                                                          requirements)))
                return SUPERSEDED, ends
            return DROPPED, ()
    return status, ()


def _hit(row: sqlite3.Row, *, status: str, successors: tuple[int, ...] = ()) -> Hit:
    return Hit(id=str(row["id"]), grp=str(row["grp"]), kind=str(row["kind"]),
               source=str(row["source"]), title=str(row["title"]),
               text=str(row["text"])[:EXCERPT_CHARS], date=str(row["date"]),
               date_from=str(row["date_from"]), origin=str(row["origin"]),
               audience=str(row["audience"]), status=status, locator=str(row["locator"]),
               requirements=tuple(_ints(row["requirements"])),
               cards=tuple(str(row["cards"]).split()), number=_number(row),
               successors=successors, addressed=bool(row["addressed"]))


def _day(date: str) -> str:
    return str(date or "")[:10]


# ── the search ──────────────────────────────────────────────────────────────────────────────────

def search(index: Index, query: Query, *, embedder=None, degraded: str = "") -> Found:
    """Search one product's index for `query` — see the module's docstring for the order.

    `embedder` is the deployment's row (`adapters/embed/registry.py::for_the_index`), or None with
    `degraded` saying why there is none."""
    from openfactory.product.semaphore import refuse_a_model_here

    refuse_a_model_here("product_search")
    with index.open() as con:
        where, params = _filters(index.key, query)
        counted = con.execute(f"SELECT count(*), count(items.vector) FROM items "  # nosec B608
                              f"WHERE {where}", params).fetchone()
        searched, unembedded = int(counted[0]), int(counted[0]) - int(counted[1])
        exact = exact_terms(query.text)
        exact = Exact(requirements=exact.requirements, cards=exact.cards, phrases=exact.phrases,
                      names=_rare_names(con, exact, searched, where, params))
        lexical = _lexical(con, query, exact, where, params)
        semantic: list[int] = []
        why = degraded or ("" if embedder is not None else "no embedder is configured")
        if embedder is not None:
            semantic, why = _semantic(con, query, where, params, embedder)
        if not why and unembedded:
            why = (f"{unembedded} of the {searched} items this conversation may search have no "
                   f"vector yet — those are found by their words only")
        fused: dict[int, float] = {}
        ranks: dict[int, dict[str, int]] = {}
        for stage, found in (("lexical", lexical), ("semantic", semantic)):
            for rank, rowid in enumerate(found, start=1):
                fused[rowid] = fused.get(rowid, 0.0) + 1.0 / (RRF_K + rank)
                ranks.setdefault(rowid, {})[stage] = rank
        requirements = {}
        for row in con.execute(f"SELECT items.rowid, items.* FROM items WHERE {where} "  # nosec B608
                               f"AND items.kind = 'requirement'", params):
            number = _number(row)
            if number is not None:
                requirements[number] = row
        rows = {}
        if fused:
            marks = ",".join("?" * len(fused))
            rows = {int(r["rowid"]): r for r in con.execute(
                f"SELECT items.rowid, items.* FROM items WHERE {where} "  # nosec B608
                f"AND items.rowid IN ({marks})", [*params, *fused])}
    candidates: list[Hit] = []
    for rowid, row in rows.items():
        status, successors = _standing(row, requirements)
        hit = _hit(row, status=status, successors=successors)
        hit.exact, hit.score = _exact_tier(row, exact), fused[rowid]
        hit.lexical = ranks[rowid].get("lexical")
        hit.semantic = ranks[rowid].get("semantic")
        candidates.append(hit)
    hits, withheld = _assemble(candidates, requirements, limit=query.limit)
    found = Found(query=query, hits=hits, degraded=why, withheld=withheld, searched=searched,
                  unembedded=unembedded,
                  embedder=getattr(embedder, "id", "") if embedder is not None else "")
    log.info("OPENFACTORY_PRODUCT_INDEX_SEARCH product=%s hits=%d lexical=%d semantic=%d "
             "withheld=%d degraded=%s", index.key, len(hits), len(lexical), len(semantic),
             withheld, "yes" if why else "no")
    return found


def _order(hit: Hit) -> tuple:
    """The tier, then the fused score, then the newest — and an undated item after a dated one."""
    day = _day(hit.date)
    return (-hit.exact, -hit.score, 0 if day else 1, tuple(-ord(c) for c in day))


def _assemble(candidates: list[Hit], requirements: dict[int, sqlite3.Row], *,
              limit: int) -> tuple[list[Hit], int]:
    """The hits in their order, one per source, every superseded one under what replaced it."""
    best: dict[str, Hit] = {}
    for hit in sorted(candidates, key=_order):
        best.setdefault(hit.grp, hit)
    current = [h for h in best.values() if h.status != SUPERSEDED]
    superseded = [h for h in best.values() if h.status == SUPERSEDED]
    by_number = {h.number: h for h in current if h.number is not None}
    withheld = 0
    for old in sorted(superseded, key=_order):
        homes = []
        for number in old.successors:
            home = by_number.get(number)
            if home is None and number in requirements:
                # THE SUCCESSOR IS PULLED IN: the query matched only what it replaced, and a
                # superseded item is never handed over without what holds today
                home = _hit(requirements[number], status=CURRENT)
                home.pulled = True
                by_number[number] = home
                current.append(home)
            if home is not None:
                # it stands where what it replaced stood — the query asked about that
                home.exact = max(home.exact, old.exact)
                home.score = max(home.score, old.score)
                homes.append(home)
        if not homes:
            withheld += 1
            continue
        for home in homes:
            home.history.append(old)
    # A REQUIREMENT THAT HOLDS TODAY BRINGS WHAT IT REPLACED, even when the query matched only it:
    # "what holds today about X?" is answered with the timeline that led to it (D3)
    for home in list(by_number.values()):
        listed = {h.number for h in home.history}
        for number, row in sorted(requirements.items()):
            if (row["status"] == SUPERSEDED and number not in listed
                    and home.number in _ends(row["successor"], requirements)):
                home.history.append(_hit(row, status=SUPERSEDED, successors=(home.number,)))
    # THE NEWEST OF IT, TOLD OLDEST FIRST: when a chain is longer than a hit lists, what goes is
    # the far past — never the link that replaced the others last
    for home in current:
        home.history = sorted(home.history, key=lambda h: (_day(h.date), h.id))[-HISTORY_PER_HIT:]
    return sorted(current, key=_order)[:max(1, limit)], withheld
