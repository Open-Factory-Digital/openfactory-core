"""The gather between the sizing and the plan (ADR-0048) — the pure half.

Everything here is a decision over data the activity already fetched: which files the sizer's
`touches` name, whether an answer the product role gave is ESTABLISHED, what the question to a
person is about, how the sweep recognises the answer, and what the answer becomes in the bundle.
No clock, no network, no tracker — `runtime/temporal/activities.py::_do_gather` and
`_do_card_question_sweep` do the fetching and call in here, so every rule below is testable
without either.

THE RULES THE CRITIQUE LEFT (ADR-0048, "the refutations this design keeps"):
- a directory is expanded to files before the gate judges it (15) — an empty expansion is
  "nothing to judge", never dark;
- an answer counts as established only when everything it cites VERIFIED — every concept fresh,
  every requirement real — never on the collapsed grade, which "média" reaches from a fabricated
  requirement number (3);
- the requester is matched in the tracker's own namespace, after the question, and never against
  the platform's own posting identity or an empty author (9, 25);
- the marker is short, ASCII, and the FIRST line of the comment the platform authored (25).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from openfactory.knowledge.contracts import Concept, ConceptSource

#: How many questions one card may carry to a person. Three is the most a comment can ask and
#: still be answered in one sitting; past that the factory is dumping its ignorance on the card.
QUESTIONS_PER_CARD = 3

#: The ceiling on the files one directory expands to — a `src/` in `touches` must not turn into
#: a judgement over the whole repository.
MAX_FILES_PER_TOUCH = 200

#: How many of the bundle's own open questions about ONE file ride the card's comment beside the
#: factory's question (ADR-0048 §7). They are shown, never a trigger; the person's answer retires
#: them. Two, because a comment that lists an author's every caveat about a file is the flood the
#: three-questions-per-card bound exists to prevent.
OPEN_QUESTIONS_PER_FILE = 2

#: The first line of every question the factory posts. ASCII, no `<`, `>`, `&`, so it survives
#: every vendor's storage and rendering unchanged (and is VISIBLE to the client on all three — an
#: HTML comment would be worse: escaped, and visible).
MARKER = "[openfactory:question]"


def question_hash(paths: list[str]) -> str:
    """The identity of a question: what it is ABOUT, not how it was worded — so the same files
    asked about on two cards, or re-worded next round, fold onto one `about`."""
    joined = "\n".join(sorted({str(p).strip().replace("\\", "/") for p in paths if str(p).strip()}))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


def marker_for(qhash: str) -> str:
    return f"{MARKER} {qhash}"


def expand_touches(touches: list[str], repo: Path, *, inventory_paths: list[str] | None = None,
                   ) -> list[str]:
    """The FILES the sizer's `touches` name, repo-relative, deduplicated, in order.

    A path that is a file stays. A path that is a directory expands to the bundle's inventory
    rows beneath it when the bundle has an inventory (the denominator the gate judges against),
    else to the files under it on disk — bounded by `MAX_FILES_PER_TOUCH`. A path that is
    neither — the sizer expects the change to CREATE it — is dropped: there are no bytes for a
    concept to describe, and the gate, which cannot tell a new file from an old one without an
    inventory, would have called it dark (refutation 16: `new-file` is green)."""
    out: list[str] = []
    seen: set[str] = set()
    inv = [p.replace("\\", "/") for p in (inventory_paths or [])]

    def add(p: str) -> None:
        p = p.replace("\\", "/").strip().lstrip("./").rstrip("/")
        if p and p not in seen:
            seen.add(p)
            out.append(p)

    for raw in touches:
        rel = str(raw).strip().replace("\\", "/").lstrip("./")
        if not rel:
            continue
        here = repo / rel.rstrip("/")
        if here.is_file() and not rel.endswith("/"):
            add(rel)
            continue
        if here.is_dir():
            prefix = rel.rstrip("/") + "/"
            under = [p for p in inv if p.startswith(prefix)] if inv else sorted(
                str(f.relative_to(repo)).replace("\\", "/") for f in here.rglob("*")
                if f.is_file() and ".git" not in f.parts)
            for p in under[:MAX_FILES_PER_TOUCH]:
                add(p)
    return out


def established(answer) -> bool:
    """Whether the product role's answer stands on evidence that VERIFIED (ADR-0048 §4).

    `reading.verified` is what `product/reading.bound` checked: each cited concept is `fresh`,
    `stale` or `missing`; each cited requirement exists or does not. Established means every
    citation checked out AND there was at least one — an answer that cites nothing is an opinion,
    however confidently graded. The collapsed `confidence` is deliberately not read."""
    if answer is None or not getattr(answer, "ok", False):
        return False
    reading = getattr(answer, "reading", None)
    verified = getattr(reading, "verified", None) or {}
    concepts = dict(verified.get("concepts") or {})
    requirements = dict(verified.get("requirements") or {})
    if not concepts and not requirements:
        return False
    return (all(v == "fresh" for v in concepts.values())
            and all(bool(v) for v in requirements.values()))


def answer_after(comments, *, asked_at: str, requester: str, poster: str):
    """The first comment that answers the question: newer than it, by the requester in the
    tracker's namespace, not by the platform itself, and not anonymous. None when nobody has.

    `comments` is oldest-first, as every adapter returns them. A quoted reply reproducing the
    marker is still an answer — the author decides, not the text."""
    who = (requester or "").strip()
    own = (poster or "").strip()
    if not who:
        return None
    for c in comments or ():
        author = (getattr(c, "author", "") or "").strip()
        when = getattr(c, "created_at", "") or ""
        if author != who or (own and author == own):
            continue
        if asked_at and when and when <= asked_at:
            continue
        if (getattr(c, "body", "") or "").strip().startswith(MARKER):
            continue  # the platform's own question, re-signed by a vendor that hides the bot
        return c
    return None


def concept_from_answer(*, path: str, question: str, answer: str, by: str, at: str,
                        repo: str = "", fingerprint: str = "") -> Concept:
    """What a person's answer becomes in the bundle: a concept about the file the question was
    about, signed by them (`generated_by="human:<id>"` — a person's word is a signature, where a
    machine pass's is an event). This is what stops the next card from asking again: the file has
    a concept, the gate says `clear`, and the answer is where the next reader looks."""
    text = " ".join((answer or "").split())
    name = Path(path).name or path
    return Concept(
        type="policy", title=f"{name} — what the requester established",
        description=text[:400], status="draft",
        generated_by=f"human:{(by or '').strip() or 'unknown'}", generated_at=at,
        sources=[ConceptSource(repo=repo, path=path, fingerprint=fingerprint)],
        what_it_does=text[:1000],
        caveats=[f"Recorded from an answer on the card, to the question: {question[:300]}"],
    )
