"""What a repository says it DECIDED: its architecture decision records, indexed across the sources.

An ADR is a numbered Markdown file in a decisions directory — `docs/adr/`, adr-tools' `doc/adr/`,
MADR's `docs/decisions/`. The index keeps its number, its title, its status and its date as the
file writes them, and where it lives. The area an ADR GOVERNS is not read out of its prose — that
would take a model — but where it sits is a fact: the repository, and the component whose code
holds its directory (`derive`), which is what `knowledge-layer.md` §9 asked of `adr-index.yaml`
without a guess.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

import yaml

from openfactory.knowledge.system.text import clip, load_yaml

#: Directory names an ADR lives under; any segment of its path may be one.
_ADR_DIRS = frozenset({"adr", "adrs", "decisions", "decision-records", "architecture-decisions",
                       "decision-log"})
#: A decision's file: a number first (`0007-use-postgres.md`, `ADR-0007-…`, `adr_7 …`).
_ADR_FILE = re.compile(r"^(?:adr[-_ ]?)?(\d{1,5})[-_. ].*\.md$", re.IGNORECASE)
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_HEADING = re.compile(r"^#[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_FIELD = re.compile(r"^[ \t]*(?:[-*][ \t]*)?\**[ \t]*(status|date)[ \t]*\**[ \t]*:[ \t]*\**[ \t]*"
                    r"(.*)$", re.IGNORECASE | re.MULTILINE)
_SECTION = re.compile(r"^#{2,3}[ \t]*(status|date)[ \t]*$", re.IGNORECASE | re.MULTILINE)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass
class AdrDecl:
    number: str
    title: str = ""
    status: str = ""
    date: str = ""


def is_adr(rel: str) -> bool:
    """Whether a repository-relative path is a decision record."""
    parts = rel.split("/")
    return bool(_ADR_FILE.match(parts[-1])) and any(p.lower() in _ADR_DIRS for p in parts[:-1])


def _first_word(text: str) -> str:
    """The status as a word: `**Proposed** — design only` → `Proposed`."""
    m = re.search(r"[A-Za-z][A-Za-z-]*", re.sub(r"[*_`\[\]]", " ", text or ""))
    return m.group(0) if m else ""


def read_adr(text: str, rel: str) -> AdrDecl:
    """Number, title, status and date of one decision record, as it writes them — front matter
    first (MADR), then `Status:` / `Date:` lines, then a `## Status` section's first line."""
    number = _ADR_FILE.match(posixpath.basename(rel))
    out = AdrDecl(number=number.group(1) if number else "")
    front: dict = {}
    if m := _FRONTMATTER.match(text):
        try:
            loaded = load_yaml(m.group(1))
        except (yaml.YAMLError, ValueError, TypeError, RecursionError):
            loaded = None       # front matter that is not YAML is prose, and is read below as such
        front = loaded if isinstance(loaded, dict) else {}
        text = text[m.end():]
    if isinstance(front.get("title"), str):
        out.title = clip(front["title"], 160)
    elif h := _HEADING.search(text):
        out.title = clip(h.group(1), 160)
    if front.get("status"):
        out.status = _first_word(str(front["status"]))
    if front.get("date") and (d := _ISO_DATE.search(str(front["date"]))):
        out.date = d.group(0)
    for f in _FIELD.finditer(text):
        key, value = f.group(1).lower(), f.group(2)
        if key == "status" and not out.status:
            out.status = _first_word(value)
        elif key == "date" and not out.date and (d := _ISO_DATE.search(value)):
            out.date = d.group(0)
    for s in _SECTION.finditer(text):
        key = s.group(1).lower()
        following = next((ln for ln in text[s.end():].splitlines() if ln.strip()), "")
        if key == "status" and not out.status:
            out.status = _first_word(following)
        elif key == "date" and not out.date and (d := _ISO_DATE.search(following)):
            out.date = d.group(0)
    return out


__all__ = ["AdrDecl", "is_adr", "read_adr"]
