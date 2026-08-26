"""Boards, by provider — chosen from the project's tracker kind, never imported by name.

The factory is the whole point: before it, `GitHubProjectBoard` was constructed directly in six
places, so "agnostic" was true of tickets and quietly false of columns.
"""

from openfactory.adapters.board.base import BoardAdapter
from openfactory.adapters.board.factory import BOARD_KINDS, BOARDS, build_board

__all__ = ["BOARD_KINDS", "BOARDS", "BoardAdapter", "build_board"]
