"""What the person is looking at when they write — the page context of a message (#266 slice 5).

ADR-0051 D1 gives every message a `context: {page, card?}` and D15 puts the chat on every page of
the panel, so that "why did this stop?" typed on card #42's page is a question about #42. The role
was never told where a person stood: the product page had one box, the floor had none, and a
question asked beside a parked card reached the role as if it had been asked in a hallway.

TWO HALVES, ON TWO SIDES OF THE DOOR, AND NEITHER TRUSTS THE BROWSER.

  - `admit` runs where the message comes in, with the person who sent it. The page SAYS what it
    shows; the server decides whether that may reach the role: a context is a page, the project
    it belongs to and at most one card — nothing else, all short strings — and a card must be one
    of THIS project's, on a board THIS person may read. A context that names a card of another
    project, or a card for a credential that may not read the board, is refused with the message,
    never quietly narrowed: the person asked about something, and answering as if they had not
    would be answering a different question.
  - `looking_at` runs on the worker, inside the turn, and turns an admitted context into the
    "current state" the role reads — the card as the project's own tracker has it, with its
    latest comments, which is where the factory writes why a job stopped. It reads through the
    project's own tracker and nothing else, so even a context that slipped past `admit` could
    only ever name a card of the project the turn is for.

WHAT A CONTEXT CANNOT DO is widen what a person may read. The card's words reach the role and,
through its answer, the person who asked — and that person could open the card themselves: the
board is a floor read (`api/app.py::_scope_of_path`), so a credential scoped to the product area,
which is refused the board, is refused a card here too.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("openfactory.product.page")

#: The pages of the panel a message can be written on. A name the page does not have is refused
#: rather than passed on: it would reach the role's prompt as a claim about where somebody stood.
PAGES = frozenset({"index", "project", "board", "card", "pr", "logs", "product"})

#: The only keys a context carries. `project` is the page's own — compared with the project the
#: chat is for, and then dropped: the message already names its project.
KEYS = frozenset({"page", "project", "card"})

#: How long any one value may be. A card ref is bounded tighter below; this bounds the rest.
MAX_VALUE = 128

#: A card as a tracker names it — `42`, `#42`, `CONT-412` — the shape the action layer already
#: holds a ticket ref to (`actions._clean_ref`), repeated here because this module sits under the
#: action layer, not on it.
_BARE_REF = re.compile(r"^[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*$")
_REF_MAX = 64

#: How many of a card's latest comments the role is handed, and how much of each. The latest is
#: where the factory says why a job stopped; the rest is room for a person's reply to it.
COMMENTS = 4
COMMENT_CHARS = 600


def _refusal(why: str) -> tuple[dict, str]:
    return {}, why


def admit(project, context, *, may_read_board: bool) -> tuple[dict, str]:
    """`(context, "")` — the context as the role may be handed it — or `({}, why)`.

    `project` is the registry project the message is for; `may_read_board` is whether the person
    sending it may read that project's board (the floor scope, `Actor.may_enter`). An empty or
    missing context is admitted as `{}`: a message written nowhere in particular is still a
    message."""
    if context in (None, "", {}):
        return {}, ""
    if not isinstance(context, dict):
        return _refusal("the page context is a page, its project and a card — nothing else.")
    unknown = sorted(str(k) for k in context if k not in KEYS)
    if unknown:
        return _refusal(f"the page context carries the page, its project and a card — not "
                        f"{', '.join(unknown)}.")
    values = {k: context.get(k) for k in KEYS}
    if any(v is not None and not isinstance(v, str) for v in values.values()) \
            or any(len(v or "") > MAX_VALUE for v in values.values()):
        return _refusal("the page context is three short words — the page, its project, a card.")
    page = (values["page"] or "").strip()
    if page and page not in PAGES:
        return _refusal(f"there is no page called {page!r} on the panel.")
    name = str(getattr(project, "name", "") or "")
    said = (values["project"] or "").strip()
    # A PAGE OF ANOTHER PROJECT names cards of another project: refused before its card is read,
    # because the ref alone would be looked up on THIS project's board and could name a stranger.
    if said and said != name:
        return _refusal(f"that page belongs to {said}, and this conversation is about {name} — "
                        f"ask from {said}'s own chat, or from a page of {name}.")
    card = (values["card"] or "").strip()
    if not card:
        return ({"page": page} if page else {}), ""
    ref, why = card_of(project, card)
    if why:
        return _refusal(why)
    # THE CARD IS A FLOOR READ. A credential the board is refused to may not have a card read to
    # the role on its behalf and summarised back to it — the context would be a second door.
    if not may_read_board:
        return _refusal("this credential cannot read the board, so a card cannot be the subject "
                        "of the question — ask about it in words, or from a credential that "
                        "reads the board.")
    return {"page": page or "card", "card": ref}, ""


def card_of(project, card: str) -> tuple[str, str]:
    """`(ref, "")` — the card as this project's tracker names it — or `("", why)`.

    A BARE REF IS THIS PROJECT'S: it is looked up on this project's board and nowhere else. A ref
    that carries a repository (`owner/name#42`, C-18) is admitted only when that repository is
    this project's own; a card of a second repository on a multi-repo board is refused rather
    than guessed at, until the board can say which repositories are its own."""
    from openfactory.adapters.forge.registry import repo_of
    from openfactory.contracts.refs import split_repo_ref

    mine = repo_of(project) or ""
    repo, bare = split_repo_ref(card, default_repo=mine)
    if not bare or len(bare) > _REF_MAX or not _BARE_REF.match(bare):
        return "", f"{card!r} is not a card of this board."
    if repo != mine:
        return "", (f"that card lives in {repo}, not on "
                    f"{getattr(project, 'name', '') or 'this project'}'s board.")
    return bare, ""


def looking_at(project, context: dict | None) -> str:
    """What the person was looking at, as the role's "current state" — or "" when nothing.

    NEVER RAISES: this is read inside a turn, and a card that cannot be read costs the card and
    never the answer. The sentence then says the card could not be read, so the role does not
    answer as if the person had been looking at nothing."""
    context = context or {}
    page = str(context.get("page") or "").strip()
    card = str(context.get("card") or "").strip()
    if not card:
        return f"The person wrote this from the panel's {page} page." if page in PAGES else ""
    ref, why = card_of(project, card)
    if why:
        # a context that did not come through `admit` — a door that forgot to ask. Said in the
        # log by name; the role is told nothing about a card this project does not have.
        log.error("OPENFACTORY_PAGE_CONTEXT_REFUSED project=%s card=%r — %s",
                  getattr(project, "name", "?"), card, why)
        return ""
    head = f"The person is looking at card #{ref} on the board, and asks about it."
    try:
        return f"{head}\n{_the_card(project, ref)}"
    except Exception:  # noqa: BLE001 — the card is context; the answer must still go out
        log.warning("[%s] could not read card %s for the page context",
                    getattr(project, "name", "?"), ref, exc_info=True)
        return f"{head}\nThe card could not be read just now — say so rather than guess."


def _the_card(project, ref: str) -> str:
    """Card #ref as the project's own tracker has it: title, state, labels, the latest comments."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.credentials import deployment_tracker_token, tracker_token_for

    tracker = build_tracker(project,
                            token=tracker_token_for(project) or deployment_tracker_token(project))
    ticket = tracker.get_ticket(ref)
    lines = [f"Card #{ref}: {ticket.title}",
             f"State: {getattr(ticket, 'state', None) or 'open'}"]
    labels = [str(x) for x in (getattr(ticket, "labels", None) or []) if str(x).strip()]
    if labels:
        lines.append(f"Labels: {', '.join(labels)}")
    thread = tracker.comments(ref)
    if thread is None:
        lines.append("Its comments could not be read.")
    elif thread:
        lines.append("The latest on it, newest last:")
        for c in list(thread)[-COMMENTS:]:
            said = " ".join(str(getattr(c, "body", "") or "").split())[:COMMENT_CHARS]
            lines.append(f"- {getattr(c, 'author', '') or 'somebody'}: {said}")
    else:
        lines.append("Nobody has commented on it.")
    return "\n".join(lines)
