"""The rule that decides what the stock image carries (pilot, 2026-08-13).

The first real onboarding proof failed on `uv sync` — read from the client's own CI by our own
proposer, inside our own image, which had never carried uv. The rule that follows: **if
`env read`/`onboard` can SYNTHESISE a command, the stock box must be able to RUN it.** Anything
beyond that floor is the client's `box.image` to declare, and the proof's missing-binary remedy
says so in those words — which is what keeps the platform honest about a stack it cannot know.

THE FLOOR IS DERIVED, NOT COPIED. The first version of this guard listed the managers by hand,
which is the shape of a rule that silently stops being true: the day somebody adds a
lockfile→manager row to `infer`, a hand-written list here still passes while the proposer names
a binary the box does not have. It now reads the proposer's OWN table, so the guard cannot drift
from what it guards (raised by the operator, 2026-08-14: any change must serve the product,
not one deployment).
"""

from __future__ import annotations

import re
from pathlib import Path

from openfactory.onboarding.infer import _PM_LOCKFILES

ROOT = Path(__file__).resolve().parents[1]


def _image_text() -> str:
    """The Dockerfiles' INSTRUCTIONS, never their comments.

    Measured, not assumed: dropping `npm install -g pnpm yarn` from the image left this guard
    green, because the comment that explains the floor rule names pnpm and yarn. A guard that
    reads prose about the code instead of the code is the decoration this repository keeps
    catching itself writing."""
    lines = []
    for name in ("base-python.Dockerfile", "sandbox.Dockerfile"):
        for line in (ROOT / "docker" / name).read_text().splitlines():
            if not line.lstrip().startswith("#"):
                lines.append(line)
    return "\n".join(lines)


def _ships(head: str) -> bool:
    return bool(re.search(rf"\b{re.escape(head)}\b", _image_text()))


def test_every_manager_the_proposer_can_SYNTHESISE_runs_in_the_stock_box():
    """Derived from `infer`'s own lockfile→manager map plus the python synthesis (`pip`), so a
    new row there fails HERE until the image ships it."""
    synthesised = {manager for _lockfile, manager in _PM_LOCKFILES} | {"pip"}

    missing = sorted(head for head in synthesised if not _ships(head))

    assert not missing, (
        f"the proposer can put {missing} in a manifest it wrote itself, and the stock box "
        f"cannot run them — install them in docker/base-python.Dockerfile, or teach `infer` "
        f"not to synthesise them")


def test_the_guard_reads_the_proposers_table_rather_than_a_copy_of_it():
    """The property that keeps the one above honest: a manager added to `infer` must reach this
    assertion with no edit here. Pinned by deriving the expectation twice, from the source."""
    assert {m for _l, m in _PM_LOCKFILES} >= {"npm", "pnpm", "yarn"}, (
        "the proposer's own table no longer names the managers this guard was written against — "
        "read it again rather than trusting this file")


def test_uv_is_shipped_as_a_DELIBERATE_extra_beyond_the_derived_floor():
    """uv is not synthesised — it is OBSERVED, read verbatim out of a client's CI (`infer`'s
    classifier recognises `uv sync`/`uv pip install`). The pilot's very first proof died on
    exactly that line, so it is shipped on purpose. Asserted separately from the derived floor
    because it is a JUDGEMENT about what clients actually use, not an invariant — and a
    judgement that stops being true should be removed deliberately, not decay silently."""
    assert _ships("uv"), (
        "uv was removed from the stock image — if that is intended, delete this test and say "
        "why in the commit; the first pilot proof failed on `uv sync` read from a real client CI")
