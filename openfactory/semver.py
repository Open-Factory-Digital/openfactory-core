"""Tiny semver helper for the prod version picker — show the current version and
suggest the next patch/minor/major bump (the panel lets the approver pick or edit)."""

from __future__ import annotations

import re

_V = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def parse(tag: str | None) -> tuple[int, int, int]:
    m = _V.search(tag or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else (0, 0, 0)


def _fmt(t: tuple[int, int, int]) -> str:
    return f"{t[0]}.{t[1]}.{t[2]}"


def bump(version: str | None, part: str) -> str:
    maj, mi, pa = parse(version)
    if part == "major":
        return _fmt((maj + 1, 0, 0))
    if part == "minor":
        return _fmt((maj, mi + 1, 0))
    return _fmt((maj, mi, pa + 1))


def suggest(latest: str | None) -> dict[str, str]:
    return {
        "current": _fmt(parse(latest)),
        "patch": bump(latest, "patch"),
        "minor": bump(latest, "minor"),
        "major": bump(latest, "major"),
    }
