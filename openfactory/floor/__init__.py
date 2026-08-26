"""Is the factory working? — asked once, answered for every surface.

THE SHAPE OF THE DEFECT THIS PACKAGE EXISTS TO END. The panel used to compute that answer in five
disconnected places, and they contradicted each other on screen: the pilot read `floor: running` in
the header, `Floor idle` in the card directly beneath it, and a `reconnecting` pill that is about
his own browser. #141 collapsed those five into one ladder — and left it in `panel.html`'s
JavaScript, which is the same defect one level up: a Slack bot asked "is the factory working?"
would have to re-implement nine rungs, and the two would drift exactly as the five did.

    the platform decides    `state(inputs, project)` — pure, nine rungs, six words
    the surfaces render     the panel, `/api/floor`, `openfactory floor`, the tech-lead's rounds

THE ONE THING THAT STAYS IN THE BROWSER, and it is a rule rather than an omission: **the server
answers about the FACTORY; only the browser can answer about the BROWSER.** "This page has heard
nothing for three minutes" is a fact about a socket in somebody's tab. The server does not know it,
and a server that asserted it would be inventing. So rung 2 is a thin shell on the client, wrapping
everything below it.

NOT `policy/floor.py`, WHICH IS A DIFFERENT WORD. That module is the framework's *floor* in the
sense of a lower bound — the non-negotiable guarantees no manifest may loosen. This one is the shop
*floor*: what is happening on it right now. Both are ordinary English and they are not the same
metaphor; a reader who lands on one should be told the other exists.
"""

from __future__ import annotations

from openfactory.floor.ladder import Cause, FloorInputs, FloorState, state
from openfactory.floor.reading import COSTLY, EVERYTHING, FAST, SLOW, gather

__all__ = ["COSTLY", "EVERYTHING", "FAST", "SLOW",
           "Cause", "FloorInputs", "FloorState", "gather", "state"]
