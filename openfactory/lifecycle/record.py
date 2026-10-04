"""One record of what happened to each card (ADR-0055 D4, D5).

Rows of kind `card_transition` in the deployment's metrics store, written only through its
`KeyedSink` capability, under keys this module chooses:

    card#<ref>#<seq:08d>                              one transition, at the card's sequence number
    card#<ref>#<seq:08d>#effect#<n:02d>#<try:04d>     one outcome of that transition's n-th effect

THE SEQUENCE NUMBER IS THE CONDITION. A transition is written only if no row holds its card's next
number, so of two transitions racing for one card exactly one is recorded and the other learns it
lost (D5). The EVENT ID is the transition's identity: the same event arriving again — a retried
request, a double click — finds its own row and is answered from it, never decided twice.

APPEND-ONLY, LIKE THE LEDGER. An effect that is applied again writes a new outcome row with the
next try number; the newest try is the effect's outcome. Nothing here is ever rewritten.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from openfactory.lifecycle.table import MOVES_NOTHING

log = logging.getLogger("openfactory.lifecycle.record")

KIND = "card_transition"

#: The prefix every key of this record starts with. Never a digit, so a key can never meet a
#: time-keyed row's sort key in the same table (`dynamo_key`).
_PREFIX = "card#"


def _card_key(card: str) -> str:
    return f"{_PREFIX}{card}#"


def transition_key(card: str, seq: int) -> str:
    return f"{_card_key(card)}{seq:08d}"


def outcome_key(card: str, seq: int, index: int, attempt: int) -> str:
    return f"{transition_key(card, seq)}#effect#{index:02d}#{attempt:04d}"


@dataclass(frozen=True)
class Row:
    """One recorded transition."""

    card: str
    seq: int
    event_id: str
    event: str
    by: str
    why: str = ""
    before: str = ""
    after: str = ""
    effects: tuple[str, ...] = ()
    facts: dict = field(default_factory=dict)
    ts: str = ""
    #: the newest outcome of each effect, by its index; an index absent here was never applied
    outcomes: dict[int, tuple[str, int]] = field(default_factory=dict)

    def outcome(self, index: int) -> str:
        return self.outcomes.get(index, ("", 0))[0]

    def attempts(self, index: int) -> int:
        return self.outcomes.get(index, ("", 0))[1]


@dataclass(frozen=True)
class History:
    """A card's transitions, oldest first."""

    rows: tuple[Row, ...] = ()

    @property
    def next_seq(self) -> int:
        return (self.rows[-1].seq + 1) if self.rows else 1

    @property
    def latest(self) -> Row | None:
        return self.rows[-1] if self.rows else None

    @property
    def latest_move(self) -> Row | None:
        """The newest transition that MOVED the card — the record's word on where the card is. A
        promise moves nothing (`table.MOVES_NOTHING`, #414), so it never stands for it: the sweep
        supersedes an older transition's late effect only by a newer move (`executor.converge`),
        an observed change is judged against the last move (`card.transition`, `observed`), and
        "the work on it stopped" is read off the last move (`card.back_in_the_backlog`)."""
        return next((r for r in reversed(self.rows) if r.event not in MOVES_NOTHING), None)

    def by_event_id(self, event_id: str) -> Row | None:
        return next((r for r in self.rows if r.event_id == event_id), None)


class Unrecordable(RuntimeError):
    """This deployment's store cannot keep the record — said by name, never as an empty history."""


def keyed_sink():
    """The deployment's store, when it can keep this record; raises `Unrecordable` naming it
    otherwise. A store that cannot write a row only if its key is absent would turn the second of
    two racing transitions into an overwrite of the first, so it is refused for this use (D5)."""
    from openfactory.observability.metrics import KeyedSink
    from openfactory.observability.registry import deployment_metrics_sink, metrics_sink_kind

    sink = deployment_metrics_sink()
    if not isinstance(sink, KeyedSink):
        raise Unrecordable(
            f"the metrics store this deployment runs ({metrics_sink_kind()!r}) cannot write a row "
            f"only if its key is absent, so it cannot keep a card's record")
    return sink


def _parse(rows: list[dict], card: str) -> History:
    found: dict[int, dict] = {}
    outcomes: dict[int, dict[int, tuple[str, int]]] = {}
    head = _card_key(card)
    for raw in rows:
        sk = str(raw.get("sk") or "")
        if not sk.startswith(head):
            continue
        parts = sk[len(head):].split("#")
        extra = raw.get("extra") or {}
        try:
            seq = int(parts[0])
        except ValueError:
            continue
        if len(parts) == 1:
            found[seq] = {**extra, "ts": raw.get("ts", "")}
        elif len(parts) == 4 and parts[1] == "effect":
            index, attempt = int(parts[2]), int(parts[3])
            mine = outcomes.setdefault(seq, {})
            if attempt >= mine.get(index, ("", 0))[1]:
                mine[index] = (str(extra.get("outcome") or ""), attempt)
    return History(rows=tuple(
        Row(card=card, seq=seq, event_id=str(x.get("event_id") or ""),
            event=str(x.get("event") or ""), by=str(x.get("by") or ""),
            why=str(x.get("why") or ""), before=str(x.get("before") or ""),
            after=str(x.get("after") or ""), effects=tuple(x.get("effects") or ()),
            facts=dict(x.get("facts") or {}), ts=str(x.get("ts") or ""),
            outcomes=outcomes.get(seq, {}))
        for seq, x in sorted(found.items())))


def read(sink, project: str, card: str) -> History:
    """`card`'s history. Raises `StoreUnreadable` when the store will not answer: an unread
    history is not an empty one, and a door that took it for one would number a transition 1
    again."""
    return _parse(sink.records_under(project, _card_key(card)), card)


def cards(sink, project: str) -> dict[str, History]:
    """Every card of `project` with a history, and its history — what the sweep walks."""
    by_card: dict[str, list[dict]] = {}
    for raw in sink.records_under(project, _PREFIX):
        sk = str(raw.get("sk") or "")
        card = str(raw.get("ticket") or "")
        if card and sk.startswith(_card_key(card)):
            by_card.setdefault(card, []).append(raw)
    return {card: _parse(rows, card) for card, rows in by_card.items()}


def write(sink, project: str, row: Row) -> bool:
    """Record `row` at its sequence number; False when another transition took that number."""
    from openfactory.adapters.board_db import now_iso
    from openfactory.observability.metrics import MetricRecord

    return sink.record_if_absent(MetricRecord(
        project=project, ticket=row.card, ts=row.ts or now_iso(), kind=KIND,
        extra={"event_id": row.event_id, "event": row.event, "by": row.by, "why": row.why,
               "before": row.before, "after": row.after, "effects": list(row.effects),
               "facts": dict(row.facts)}),
        key=transition_key(row.card, row.seq))


def write_outcome(sink, project: str, row: Row, index: int, outcome: str) -> None:
    """Record what applying `row`'s `index`-th effect came to, as its next try. Never raises: the
    effect happened or failed whatever its record says, and the sweep reads a missing outcome as
    one still to apply."""
    from openfactory.adapters.board_db import now_iso
    from openfactory.observability.metrics import MetricRecord

    attempt = row.attempts(index) + 1
    for _ in range(3):
        try:
            if sink.record_if_absent(MetricRecord(
                    project=project, ticket=row.card, ts=now_iso(), kind=KIND,
                    extra={"event_id": row.event_id, "effect": row.effects[index],
                           "outcome": outcome}),
                    key=outcome_key(row.card, row.seq, index, attempt)):
                return
        except Exception as exc:  # noqa: BLE001 — see the docstring
            log.warning("OPENFACTORY_CARD_OUTCOME_UNRECORDED card=%s seq=%s effect=%s (%s)",
                        row.card, row.seq, row.effects[index], exc)
            return
        attempt += 1   # a sweep wrote this try first; the newest try is still ours to write
