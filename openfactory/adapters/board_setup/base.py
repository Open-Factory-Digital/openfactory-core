"""The contract of a board-setup act — what `openfactory init` calls when a tracker declares one."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class BoardSetupError(RuntimeError):
    """One failed step, with the words a person at a terminal can act on.

    NEUTRAL, so the CLI catches one type whichever vendor's act raised it. The GitHub act's own
    error is this class — re-exported from its module for the callers that always named it there."""


@runtime_checkable
class BoardCreator(Protocol):
    """The two questions creating a board asks, both of them the VENDOR's (ADR-0049 D1).

    IT USED TO BE A BARE CALLABLE, and the second question was answered by neutral code reading
    GitHub's own option names: `init` decided a board was "already attached" from `board_owner`
    and `board_number` in the registry, which is one vendor's shape of coordinate spelled in the
    one place that must work for every row. A vendor whose board has no coordinate — the
    platform's own, whose columns are rows in a file — could not be asked the question at all,
    and would have had its board recreated on every re-run of an idempotent command.

    So the row answers both, and `init` compares nothing."""

    def attached(self, project) -> str:
        """What board this project ALREADY has, as a sentence a person reads, or `""`.

        A SENTENCE RATHER THAN A BOOLEAN, because the caller prints it: GitHub says which board by
        its coordinates, the platform's own says its columns are there. A row that cannot tell
        answers `""` and its `create` is expected to be idempotent, which is what `init` promises
        whoever re-runs it."""
        ...

    def create(self, *, project, owner: str, title: str, token: str | None) -> tuple[str, str]:
        """Create the board and return `(coordinate, url)`; raise `BoardSetupError` with the remedy.

        `coordinate` IS `""` FOR A VENDOR THAT HAS NONE, and the caller writes it into the registry
        only when it is not — a board with no second object to point at has nothing to attach.

        `project` because a row may need more than a name: the platform's own writes the columns
        into this project's rows, keyed by the project the registry already knows. `owner` is where
        the board lives in the vendor's own terms and is `""` where the vendor has no such place —
        a row that NEEDS one raises `BoardSetupError` saying so, rather than the caller guessing
        which vendors do. `token` is THIS vendor's credential, resolved by the caller through the
        tracker axis — never another system's."""
        ...
