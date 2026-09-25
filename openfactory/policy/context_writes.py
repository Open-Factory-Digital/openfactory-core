"""What automation may put into a product's CONTEXT repository without a person (#265 §6.4, §8).

THE CONTEXT REPOSITORY'S BASE IS WRITTEN BY MACHINES, and some of what it holds now decides what
runs. `product.yaml`'s `preview:` and the compose file it names say which code a preview builds on
the operator's daemon, and the preview reads them from the base branch — so whatever lands on that
branch without a person is, from then on, trusted like something a person merged. The writers
that land there on their own are driven by an LLM role reading channel messages and code:

- `authoring.land_open_proposals` opens AND merges every `req/*` branch;
- `authoring.record_fact` commits straight to the base;
- the knowledge pipeline (`knowledge/pipeline.py::publish_bundle`) commits `.okf/`.

THE BOUNDARY IS ENFORCED AT THOSE WRITERS, NOT GUESSED AT BY THE READER. Git cannot tell a
person-merged commit from a bot-landed one on a squash-merging forge (the design's §13), so the
rule is that each writer lands ONLY the paths it exists to write — and `.openfactory/`, the
platform's own directory, never: the sweep leaves open, and says why, any proposal that touches a
path outside the requirements; a direct writer stages an allow-listed path or nothing.

Pure: paths in, paths out.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable

#: The platform's own directory in any repository — the shape of a preview lives under it, and no
#: writer that lands without a person may touch it, whatever else it is allowed.
PLATFORM_DIR = ".openfactory/"

#: What `record_fact` exists to write: a learned fact, one file under `domain/`.
FACTS = ("domain/",)

#: What the knowledge pipeline exists to write: a source's module map under `.okf/`.
KNOWLEDGE = (".okf/",)


def _clean(path: str) -> str:
    """`path` as one repository-relative spelling, or "" when it is not one (absolute, `~`, a
    `..` that climbs out, empty)."""
    raw = str(path or "").strip()
    if not raw or raw.startswith(("/", "~")) or "\\" in raw:
        return ""
    norm = posixpath.normpath(raw)
    if norm in (".", "..") or norm.startswith("../"):
        return ""
    return norm


def outside(paths: Iterable[str], allowed: Iterable[str]) -> list[str]:
    """Every path of `paths` a writer allowed `allowed` may NOT land: one that is not a plain
    path inside the repository, one that is neither an allowed file nor under an allowed
    directory, and — whatever `allowed` says — one under `.openfactory/`."""
    exact = {_clean(a.rstrip("/")) for a in allowed if a} - {""}
    prefixes = tuple(a + "/" for a in exact)
    out = []
    for path in paths:
        norm = _clean(path)
        if (not norm or norm.startswith(PLATFORM_DIR) or norm + "/" == PLATFORM_DIR
                or not (norm in exact or norm.startswith(prefixes))):
            out.append(str(path))
    return out


#: `diff --git a/<path> b/<path>` — each side quoted by git when the path needs it
_QUOTED = r'"{side}/((?:[^"\\]|\\.)*)"'
_HEADER = re.compile(rf'^diff --git (?:{_QUOTED.format(side="a")}|a/(\S+)) '
                     rf'(?:{_QUOTED.format(side="b")}|b/(\S+))$')
#: `--- a/<path>` / `+++ b/<path>` — `/dev/null` names no path
_SIDE = re.compile(rf'^(?:---|\+\+\+) (?:{_QUOTED.format(side="[ab]")}|[ab]/(\S.*?))\s*$')


def diff_paths(diff: str) -> list[str] | None:
    """Every path a unified diff touches — both sides of every file header, so a rename out of
    a directory counts as touching where it went. None when a diff with content names no file:
    what it changes could not be read, which is never "nothing"."""
    found: list[str] = []
    for line in (diff or "").splitlines():
        m = _HEADER.match(line) or _SIDE.match(line)
        if not m:
            continue
        found += [g for g in m.groups() if g]
    if not found and (diff or "").strip():
        return None
    return list(dict.fromkeys(found))
