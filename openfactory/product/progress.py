"""What a turn is doing NOW, told while the person waits (#395).

A TURN IS A CHAIN OF MODEL CALLS, AND THE PERSON SAW NONE OF IT. Measured on a live deployment: the
answer 143 s, a draft 40 s, a judge 100 s, a redraft 34 s, another judge — with ~0 s of platform
time between them. The person got the receipt, then the hand-off at the bound, then minutes of
nothing, and concluded the product was broken. The engine was working the whole time; it simply
had two moments it could tell anyone about ("I am on it", "here is the answer") and nothing in
between (`engine.py`'s "takes no callbacks", `confirm.receipt`'s "at most once, ever").

A STAGE IS PRESENCE, NEVER A REPLY. It is not a `Reply`, not recorded in the transcript, not put in
the outbox a chat add-on reads, and never read back to the model: it says WHAT the role is doing
("lendo o quadro"), never what it found. A surface that can edit in place (the panel's typing
bubble) shows the latest one and replaces it; a surface that cannot hears it once, inside the
hand-off it already gets at the bound (`voice.handed_off(stage=…)`) — never a message per stage.

ONE HOOK, CALLABLE FROM ANYWHERE INSIDE A TURN. The sink is a context variable the running turn
installs (`reporting`), so a stage deep inside the module says `stage("board")` without a parameter
threaded through every signature on the way. No sink installed (a chat add-on calling the engine
directly, a test, a background thread the turn started) and it does nothing. It NEVER RAISES into
the turn: a status that could not be told costs the status, never the answer.

`STAGES` is every name a caller may say; `voice.stage_text` has a sentence for each in every
language it speaks, and a test holds the two together.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Iterator
from contextvars import ContextVar

log = logging.getLogger("openfactory.product.progress")

#: WHAT A TURN CAN BE DOING, in the order a turn usually meets them. THE LAST TWO HAVE NO CALLER
#: YET (review of #398): they are the card loop's — the role drafts a card and a judge reviews it
#: before the yes, the ~174 s of the chain #395 measured after the answer — and that loop arrives
#: with #390 (`product/cards.py`), not on this branch. Once both land, the loop calls
#: `stage("card_draft", step=n, of=N)` before each draft and `stage("card_review", step=n, of=N)`
#: before each judge, and the sentences (with their `{step}/{of}`) are already here. Until then
#: `answering` covers the answer and the card loop is still silent.
STAGES = ("reading", "answering", "board", "drafting", "breaking_down", "writing",
          "card_draft", "card_review")

#: The running turn's sink: `(stage, counts)`, or None outside a turn.
_SINK: ContextVar[Callable[[str, dict], None] | None] = ContextVar("openfactory_turn_progress",
                                                                   default=None)


@contextlib.contextmanager
def reporting(sink: Callable[[str, dict], None] | None) -> Iterator[None]:
    """Every `stage` said inside this block goes to `sink` — and none after it."""
    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)


def stage(name: str, **counts: int) -> None:
    """The running turn is now doing `name` — reported to its sink, when it has one.

    `counts` are the numbers a stage's sentence carries (`step`, `of`). A name that is not one of
    `STAGES` is a caller's bug, logged and not reported: a surface must never show a stage no
    language has words for."""
    sink = _SINK.get()
    if sink is None:
        return
    if name not in STAGES:
        log.warning("a turn reported the stage %r, which no language has words for", name)
        return
    try:
        sink(name, dict(counts))
    except Exception:  # noqa: BLE001 — a status that could not be told must never cost the answer
        log.warning("could not report the turn's stage %r", name, exc_info=True)
