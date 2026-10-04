"""A change made in the vendor's own interface enters through the card's door (ADR-0055 D8).

THE DEFECT THIS ENDS. On a hosted tracker a person closes, reopens or drags a card on the vendor's
own screen, and no code of ours runs. The door knew every consumer of a change made through the
platform; a change made beside it reached none of them: a card closed on GitHub as not planned kept
its requester's promise open for ever, and nobody told them it would not be built.

THE BOARD SWEEP, ON THE HOURLY ROUND (`techlead_watch`, beside `converge`). It reads the board once,
compares each card the platform holds a belief about with what the tracker shows, and hands the
door every difference the tracker's row can report (`tracker/base.py::observes`) as an event with
`by=OBSERVED`. The door judges it against what the platform last knew and applies what follows
MINUS THE WRITES TO THE CARD, which the vendor's interface already made (`table.consequences`).

    what the platform holds      the record's latest transition; else an open promise about the
                                 card (a delivery waiting on it, a question asked on it)
    what is compared             open and now closed      `closed`, delivered or not as the row
                                                          says why (`ports.withdrawn`)
                                 closed and now open      `reopened`
                                 open and now gone        `removed` — only a row that can tell an
                                                          absence from a failed read
                                 backlog, now in TO-DO    `promoted`
                                 TO-DO, now in backlog    `reordered`

WHAT IS NOT AN OBSERVED CHANGE, ON PURPOSE:

- a move into the factory's own columns (in progress, in review, needs action, done): the box's
  progress marks are not card events (D7) and the record never holds them, so a card the record
  last placed at a pull request reads as moved by every mark the next pass writes — reading them
  as a person's drag would be a story nobody lived. The box's outcomes the record DOES hold since
  it hands them back (#414): they reach it through the door, never by observation;
- the close of a card some other card was SPLIT from: the splitter closes it as not delivered and
  its work lives in its children (`triage.delivered_numbers`), so its promise is not cancelled.
"""

from __future__ import annotations

import logging

from openfactory.lifecycle.table import OBSERVED, CardEvent, State

log = logging.getLogger("openfactory.lifecycle.observed")

#: The states the platform holds a card closed in. A `delivered` card is closed on every row.
_CLOSED = frozenset({State.CLOSED, State.DELIVERED, State.REMOVED})


def _held(project, ports) -> dict[str, State | None]:
    """`{card: where the platform last placed it}` — the record's latest transition, else `None`
    (open, placed nowhere the platform knows) for a card it only promised something about."""
    from openfactory.contracts.refs import canonical_ref
    from openfactory.lifecycle import record
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import CARD_QUESTION, DELIVERY, fold
    from openfactory.product.events import issues_of
    from openfactory.product.followup import cancelled_cards

    held: dict[str, State | None] = {}
    try:
        for loop in fold(loop_store.read(ports.name)):
            if not loop.waiting:
                continue
            if loop.kind == DELIVERY:
                for card in issues_of(loop) - cancelled_cards(loop):
                    held[card] = None
            elif loop.kind == CARD_QUESTION:
                held[canonical_ref(loop.subject)] = None
    except Exception:  # noqa: BLE001 — an unread ledger promises nothing this round
        log.info("[%s] the ledger could not be read to observe the board", ports.name,
                 exc_info=True)
    try:
        for card, history in record.cards(ports.sink(), ports.name).items():
            latest = history.latest
            if latest is not None:
                try:
                    held[card] = State(latest.after) if latest.after else None
                except ValueError:
                    continue
    except Exception:  # noqa: BLE001 — a store that cannot answer holds nothing this round
        log.info("[%s] the card record could not be read to observe the board", ports.name,
                 exc_info=True)
    return held


def _change(card: str, was: State | None, ticket, *, can: frozenset[str], ports,
            split: set[str]) -> tuple[CardEvent, dict] | None:
    """The event `card`'s tracker shows happened since the platform last placed it in `was`, with
    the facts it carries — or None: nothing changed, or nothing this row can report did."""
    from openfactory.adapters.board.base import stage_key
    from openfactory.lifecycle.ports import withdrawn

    held_open = was not in _CLOSED
    if ticket is None:
        if not held_open or "removed" not in can:
            return None
        try:
            ports.tracker.get_ticket(card)
        except KeyError:
            return CardEvent.REMOVED, {}
        except Exception:  # noqa: BLE001 — a failed read is not an absence
            log.info("could not read #%s to tell whether it was removed", card, exc_info=True)
        return None
    is_open = str(getattr(ticket, "state", "") or "open") == "open"
    column = str(getattr(ticket, "column", "") or "")
    key = stage_key(ports.board, column) if column else ""
    if held_open and not is_open:
        if "closed" not in can or card in split:
            return None
        return CardEvent.CLOSED, {"delivered": not withdrawn(ticket), "column": key}
    if not held_open and is_open:
        if was is State.REMOVED or "reopened" not in can:
            return None
        return CardEvent.REOPENED, {}
    if is_open and was is State.BACKLOG and key == "todo" and "promoted" in can:
        return CardEvent.PROMOTED, {}
    if is_open and was is State.TODO and key == "backlog" and "reordered" in can:
        return CardEvent.REORDERED, {}
    return None


def observe(project, *, ports=None, tickets=None) -> list[str]:
    """Hand the card's door every change the tracker shows that the platform does not hold —
    `by=OBSERVED`. Returns one line per change it handed; never raises (the next round looks
    again). `tickets` is a board already read, for a caller that holds one."""
    from openfactory.adapters.tracker.base import observes
    from openfactory.contracts.refs import canonical_ref, split_parent_of
    from openfactory.lifecycle.card import transition
    from openfactory.lifecycle.ports import Ports

    ports = ports or Ports(project)
    said: list[str] = []
    try:
        can = observes(ports.tracker)
        if not can:
            return said
        held = _held(project, ports)
        if not held:
            return said
        if tickets is None:
            from openfactory.product.board import read_board

            tickets, error = read_board(project, tracker=ports.tracker, limit=0)
            if error:
                log.info("[%s] the board could not be read to observe it (%s)", ports.name, error)
                return said
        by_ref = {canonical_ref(t.number): t for t in tickets}
        split = {split_parent_of(getattr(t, "title", "")) for t in tickets} - {""}
    except Exception:  # noqa: BLE001 — see the docstring
        log.warning("[%s] the board could not be observed this round", ports.name, exc_info=True)
        return said
    for card, was in sorted(held.items()):
        try:
            change = _change(card, was, by_ref.get(card), can=can, ports=ports, split=split)
            if change is None:
                continue
            event, facts = change
            moved = transition(project, card, event, by=OBSERVED, ports=ports,
                               facts={**facts, "before": was.value if was else ""})
        except Exception:  # noqa: BLE001 — one card must not stop the round for the rest
            log.warning("[%s] #%s: an observed change could not go through its door", ports.name,
                        card, exc_info=True)
            continue
        line = f"#{card} {event.value}, observed: " + (moved.refused or ", ".join(
            f"{n}={o}" for n, o in moved.effects) or "nothing follows")
        log.info("OPENFACTORY_CARD_OBSERVED project=%s %s", ports.name, line)
        said.append(line)
    return said
