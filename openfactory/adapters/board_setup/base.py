"""The contract of a board-setup act — what `openfactory init` calls when a tracker declares one."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class BoardSetupError(RuntimeError):
    """One failed step, with the words a person at a terminal can act on.

    NEUTRAL, so the CLI catches one type whichever vendor's act raised it. The GitHub act's own
    error is this class — re-exported from its module for the callers that always named it there."""


@runtime_checkable
class BoardCreator(Protocol):
    def __call__(self, *, owner: str, title: str, token: str | None) -> tuple[str, str]:
        """Create the board and return `(number, url)`; raise `BoardSetupError` with the remedy.

        `owner` is where the board lives in the vendor's own terms (a GitHub login or org), and
        `title` the name a person will see. `token` is THIS vendor's credential, resolved by the
        caller through the tracker axis — never another system's."""
        ...
