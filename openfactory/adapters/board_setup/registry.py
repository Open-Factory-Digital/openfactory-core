"""Which tracker kinds have a board to CREATE — resolved from the kind, never from an import.

`None` IS THE ORDINARY ANSWER, and that is the one way this registry differs from the dispatching
ones: a tracker that brings its own board has nothing to create, and `init` says so rather than
refusing. An unknown kind therefore answers `None` too — the act is optional by nature, and the
tracker registry is the one that refuses an unknown kind, at the door where refusing is right.
"""

from __future__ import annotations

from collections.abc import Callable

from openfactory import plugins
from openfactory.adapters.board_setup.base import BoardCreator


def _github() -> BoardCreator:
    from openfactory.adapters.tracker.github_board_setup import create_board

    return create_board


#: kind → a builder returning the vendor's `BoardCreator`. Lazy, so the CLI's help never imports
#: a vendor module to learn that a board can be created somewhere.
BOARD_SETUPS: dict[str, Callable[[], BoardCreator]] = {
    "github": _github,
}


def board_creator(kind: str) -> BoardCreator | None:
    """The act that creates a board for `kind`, or `None` when this tracker brings its own."""
    key = (kind or "").strip().lower()
    builder = BOARD_SETUPS.get(key) or plugins.builder("board_setup", key, builtin=BOARD_SETUPS)
    return builder() if builder is not None else None
