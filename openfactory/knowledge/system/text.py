"""What every format's reader shares: a safe YAML loader, comments blanked, a line from an offset.

KEPT APART so that the one decision each makes is made once. `load_yaml` is the only way a YAML
document is read in this layer — the safe loader, which refuses every tag that would build a Python
object — and `blank_comments` is the only way a comment is taken out of a C-like text, keeping every
offset and every line where it was, so a line number found in the blanked text is the line in the
file.
"""

from __future__ import annotations

import bisect

import yaml


class _Loader(yaml.SafeLoader):
    """`yaml.SafeLoader`, plus the two tags the compose specification defines.

    `!reset` and `!override` only remove or replace a key while compose merges files; read on their
    own they are the value they carry. Every other tag — `!!python/object/apply:os.system` among
    them — is refused by the safe loader, and the file is reported as not parsed."""


def _as_is(loader: yaml.SafeLoader, node: yaml.Node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)


_Loader.add_constructor("!reset", _as_is)
_Loader.add_constructor("!override", _as_is)


def load_yaml(text: str):
    """One YAML document, safely. Raises `yaml.YAMLError` (and `RecursionError` on a document
    nested deeper than the interpreter will follow) — the caller files either as a parse error."""
    return yaml.load(text, Loader=_Loader)  # noqa: S506 — `_Loader` IS a SafeLoader


def documents(text: str) -> list[tuple[int, str]]:
    """`(first line, text)` of every YAML document in a stream, split at `---` lines.

    Split by text rather than by `yaml.safe_load_all` so that each document keeps the line it
    starts on — a Kubernetes file of six documents cites the one that declares the Deployment, not
    the file's first line — and so that one broken document is one parse error, not the file's."""
    out: list[tuple[int, str]] = []
    start, chunk = 1, []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.rstrip() == "---" or line.startswith("--- "):
            if any(s.strip() for s in chunk):
                out.append((start, "\n".join(chunk)))
            start, chunk = number + 1, ([line[4:]] if line.startswith("--- ") else [])
            if chunk:
                start = number
            continue
        chunk.append(line)
    if any(s.strip() for s in chunk):
        out.append((start, "\n".join(chunk)))
    return out


def blank_comments(text: str, *, line: tuple[str, ...] = ("//",),
                   block: tuple[str, str] | None = ("/*", "*/"),
                   quotes: str = "\"'") -> str:
    """`text` with every comment replaced by spaces — newlines kept — so offsets and line numbers
    in the result are the file's own. A comment marker inside a quoted string is not a comment."""
    out = list(text)
    i, n = 0, len(text)
    quote = ""
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote or ch == "\n":
                quote = ""
            i += 1
            continue
        if ch in quotes:
            quote = ch
            i += 1
            continue
        if block and text.startswith(block[0], i):
            end = text.find(block[1], i + len(block[0]))
            end = n if end < 0 else end + len(block[1])
            for j in range(i, end):
                if out[j] != "\n":
                    out[j] = " "
            i = end
            continue
        marker = next((m for m in line if text.startswith(m, i)), "")
        if marker:
            end = text.find("\n", i)
            end = n if end < 0 else end
            for j in range(i, end):
                out[j] = " "
            i = end
            continue
        i += 1
    return "".join(out)


def line_at(text: str, offset: int) -> int:
    """The 1-based line of `offset` in `text`. For one offset; a reader that asks for the line of
    every block of a file builds `Lines` once instead — counting from the start each time is
    quadratic in a file somebody else wrote."""
    return text.count("\n", 0, max(0, offset)) + 1


class Lines:
    """The line of any offset of one text, by bisection over where its newlines are."""

    def __init__(self, text: str) -> None:
        self._breaks = [i for i, ch in enumerate(text) if ch == "\n"]

    def at(self, offset: int) -> int:
        return bisect.bisect_left(self._breaks, max(0, offset)) + 1


def matching(text: str, open_at: int, pair: str = "{}") -> int:
    """The offset of the bracket that closes the one at `open_at`, or -1. Brackets inside a quoted
    string do not count. Comments must already be blanked.

    For ONE bracket. A reader that looks for the close of every block of a file asks `pairs`
    instead: this walks to the end of the file for a bracket that never closes, and doing that
    once per block is quadratic in a file somebody else wrote."""
    depth, quote, i = 0, "", open_at
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == pair[0]:
            depth += 1
        elif ch == pair[1]:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def pairs(text: str, pair: str = "{}", quotes: str = "\"'") -> dict[int, int]:
    """`{open offset: close offset}` for every bracket of `text` that closes — one pass, however
    many blocks the file has. An unclosed bracket is absent. Brackets inside a quoted string do
    not count; comments must already be blanked."""
    out: dict[int, int] = {}
    stack: list[int] = []
    quote, i, n = "", 0, len(text)
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote or ch == "\n":
                quote = ""
        elif ch in quotes:
            quote = ch
        elif ch == pair[0]:
            stack.append(i)
        elif ch == pair[1] and stack:
            out[stack.pop()] = i
        i += 1
    return out


def clip(value: object, limit: int = 200) -> str:
    """A string from a declaration, trimmed to one line and a bound: a summary is a pointer, and a
    four-kilobyte description copied into a map is the file again."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def bodies(code: str, starts: list, closes: dict[int, int]) -> list[tuple[object, int]]:
    """`(match, end of its body)` for every block a pattern found, where each match ends with its
    opening brace: the body ends at its closing brace — or, for a block that never closes, where
    the next block starts. Without that bound every unclosed block's body is the rest of the file,
    and reading each is quadratic."""
    out = []
    for i, m in enumerate(starts):
        nxt = starts[i + 1].start() if i + 1 < len(starts) else len(code)
        close = closes.get(m.end() - 1)
        out.append((m, min(close, nxt) if close is not None and close >= m.end() else nxt))
    return out


__all__ = ["Lines", "blank_comments", "bodies", "clip", "documents", "line_at", "load_yaml",
           "matching", "pairs"]
