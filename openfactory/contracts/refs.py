"""Reading a ticket reference without assuming whose it is (C-04).

`contracts/ticket.py` documents a ref as the PROVIDER's own opaque string — `#142` on GitHub,
`PROJ-31` on Jira, `1234` on Azure DevOps — and `tracker/jira.py` honours that. `product/` did not:
five sites called `int(str(ref).lstrip("#"))`, and `int("CONT-412")` is a `ValueError`.

WHY THIS IS ITS OWN CARD, SEPARATE FROM THE WIDER REF WORK. The `lstrip("#")` sites elsewhere
produce a wrong string and a 404 — bad, visible, recoverable. These *raise*, inside the product
role's write path, AFTER the issues have already been filed. The delivery lands and the client is
never told, which is exactly the failure ADR-0025 exists to prevent.

WHAT THIS IS NOT. It does not make `product/` provider-neutral. `number: int` is that module's
domain type across some fifty signatures, and `BoardAdapter.set_column` is itself typed with an
integer issue id. That is C-05, and it needs a migration of shapes already persisted as dict keys
and set members (issue #33). What lives here is the narrower promise: a non-numeric ref DEGRADES —
the work is reported, the courtesy that needs a number is skipped and says so — rather than taking
the pass down with it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

log = logging.getLogger("openfactory.refs")


def ref_number(ref: object) -> int | None:
    """The integer a provider's ref carries, or `None` when it does not carry one.

    **`None`, never `0`.** The function this replaces returned `0` on failure, which reads as a
    number all the way down: a comment addressed to issue #0, or a lookup that silently matches
    nothing and looks like an empty result. A value that cannot be distinguished from a real one
    is worse than an absent one.

    **Never raises.** Its callers are mid-write, after work has been filed. Anything that escapes
    here abandons a delivery somebody was about to be told about.
    """
    try:
        text = str(ref).strip().lstrip("#").strip()
    except Exception as exc:  # noqa: BLE001 — an object whose __str__ raises is still not a ref
        log.debug("a value that cannot even be stringified is not a ref (%r): %s", type(ref), exc)
        return None
    if not text.isdigit():  # rejects "", "CONT-412", "12a", "1.5", "-5" and "  "
        return None
    value = int(text)
    return value if value > 0 else None  # no tracker issues a zero


def ref_numbers(refs: Iterable[object]) -> list[int]:
    """The numeric refs in a collection, deduplicated and sorted — skipping what is not numeric.

    Sorted and unique because callers render the result to a client as "#3, #12"; losing either
    property changes what somebody reads. Skipping rather than failing because the alternative is
    what this card exists to fix: one Jira ref in a set of results taking the whole notification
    down after the work had already been done.
    """
    return sorted({n for n in (ref_number(r) for r in refs) if n is not None})


def canonical_ref(ref: object) -> str:
    """The provider's own ref, without the decoration a human types: `#189` → `189`.

    ONE SPELLING, because `#189` and `189` must never be two tickets. This is the form the ledger
    has always persisted and the form `openfactory.actions._clean_ref` produces, so nothing
    migrates."""
    return str(ref or "").strip().lstrip("#").strip()


def split_repo_ref(ref: object, default_repo: str = "") -> tuple[str, str]:
    """`('owner/name', bare ref)` — a ref may carry its own repository (C-18).

    THE PRODUCT IS NOT A REPOSITORY. One board routes cards to several source repositories, and a
    bare number is ambiguous the moment a second repo joins: `#3` on `fx-multirepo` names one
    issue in `…-api` and a different one in `…-web`. The wire form `owner/name#3` carries the
    repository WITH the ticket, so every consumer — the tracker call, the clone, the board move,
    the issue URL — acts on the card's own repo instead of the project's default.

    A bare ref (`'12'`, `'#12'`, `'CONT-412'`) resolves to `default_repo` — the single-repo case
    stays byte-for-byte what it always was, which is what keeps workflow ids, journal names and
    dedup stable for every project that exists today. The `#` split takes the LAST `#` and demands
    a `/` on its left, so a Jira ref containing a dash and a human-typed `#189` both stay bare."""
    # the human decoration comes off FIRST: '#owner/name#3' must never read '#owner/name' as a
    # repository. No forge allows '#' in an owner or repo name, so this is always safe.
    text = str(ref or "").strip().lstrip("#").strip()
    repo, sep, tail = text.rpartition("#")
    if sep and "/" in repo and tail:
        return repo, tail
    return default_repo, canonical_ref(text)


def qualify_ref(repo: str, ref: object, default_repo: str = "") -> str:
    """The wire form of a ref that lives in `repo`: bare when that IS the default repo,
    `owner/name#<ref>` otherwise (C-18).

    Qualified ONLY when it must be: the bare spelling is what every persisted key, workflow id
    and journal stem already uses, so qualifying the common case would split one ticket into two
    identities — the exact defect `canonical_ref` exists to prevent, one level up."""
    bare = canonical_ref(ref)
    if not repo or repo == default_repo:
        return bare
    return f"{repo}#{bare}"


def ref_label(ref: object) -> str:
    """A ref as a PERSON reads it — `#510` on GitHub, `CONT-412` on Jira, `""` for nothing.

    `#` IS GITHUB'S PUNCTUATION, not the platform's, and the sites that render one wrote `f"#{c}"`
    because every ref they had ever seen was a number. On a Jira board that produces `#CONT-412`,
    which is not how anybody there writes a ticket and not what a reader can paste back.

    One home, because the question — how do I show this ref to somebody — recurs at every sentence
    a client reads, and the answer is provider-shaped.
    """
    text = str(ref or "").strip()
    if not text:
        return ""
    return f"#{text.lstrip('#')}" if text.lstrip("#").isdigit() else text


def ref_sort_key(ref: object) -> tuple[str, int, str]:
    """Order refs the way a person expects, without making the ref itself a number (C-05).

    THIS IS WHAT THE `int` TYPING WAS ACTUALLY BUYING. Nothing in this codebase does arithmetic on
    a ticket ref — there is no site that adds, averages or subtracts one. What the `int` bought was
    ORDERING: `sorted([2, 10])` is `[2, 10]` while `sorted(["2", "10"])` is `["10", "2"]`, so a
    board sorted as strings comes back shuffled. Board order is what an operator reads.

    So identity and ordering are separated. The ref stays the provider's own string — because it is
    what goes BACK to the provider, and a comment on `CONT-412` needs `CONT-412`, not `412`. The
    number is extracted only here, only to sort.

    THE PREFIX SORTS FIRST, and that is the part a plain `int(...)` would get wrong. A Jira board
    routinely spans several projects, so `CONT-412` and `PROJ-412` sit on it together. Reducing
    both to `412` would not merely mis-order them — it would make them EQUAL, and a platform that
    thinks two tickets are one moves the wrong card and comments on the wrong ticket, silently.
    That is the same shape as the `int(...) or 0` collapse that made the tech-lead's memory report
    every failure as one ticket (#69).

        CONT-2, CONT-10, PROJ-1  →  ('CONT', 2, …), ('CONT', 10, …), ('PROJ', 1, …)

    The raw ref is the last element so the ordering is TOTAL: two refs that share a prefix and a
    number (which no tracker issues, but a malformed registry might) still order deterministically
    instead of depending on the sort's stability.
    """
    raw = canonical_ref(ref)
    number = ref_number(raw)
    if number is not None:
        return ("", number, raw)  # a plain numeric ref: GitHub, Azure DevOps, GitLab
    prefix, _, tail = raw.rpartition("-")
    digits = ref_number(tail)
    if prefix and digits is not None:  # the Jira / Linear shape: PROJ-123
        return (prefix.upper(), digits, raw)
    # Anything else keeps a stable, if arbitrary, place rather than raising mid-render.
    return (raw.upper(), 0, raw)
