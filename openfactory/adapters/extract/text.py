"""The rows that read text as text: plain text, markdown, mermaid and HTML (#269 slice 1).

DETERMINISTIC, NO MODEL (`docs/knowledge-layer.md` §10). These are the bulk of any context
repository and a parser reads them exactly; a model here would cost money to be less right.

WHAT "NORMALISED" MEANS, once for every row (`normalise`): one Unicode form (NFC), one line
ending, no control characters, no trailing blanks, at most one empty line between paragraphs.
Two versions of a document that differ only in line endings then index as the same words.

THE ENCODING IS FOUND, NEVER ASSUMED, AND SAID. UTF-8 first, then the Windows code page an old
document was most likely written in, then Latin-1, which decodes any byte; the record notes which
was used when it was not UTF-8, so a garbled accent can be traced to its cause. A file with NUL
bytes in it is binary wearing a text suffix, and is refused as such rather than indexed as noise.

HTML IS REDUCED TO ITS WORDS by the standard library's parser — tags dropped, blocks kept as lines,
`<script>` and `<style>` dropped whole. Nothing in the markup is loaded, run or followed.

FRONT MATTER IS DATA, READ SAFELY. A markdown file's leading `---` block is parsed with
`yaml.safe_load` — no tag of it can construct an object — and gives the title, the date, the
authors and the AUDIENCE the document declares about itself (`contracts/document.py`).
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from html.parser import HTMLParser

import yaml

from openfactory.adapters.extract.base import Extraction, Source, unreadable

#: How much of the start is looked at for NUL bytes — enough to catch any binary format's header.
_SNIFF = 8192
#: Every control character but tab and newline.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANKS = re.compile(r"\n{3,}")
#: A leading YAML block: `---`, the block, `---` (or `...`), at the very start of the file.
_FRONT = re.compile(r"\A---[ \t]*\n(.*?)\n(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.DOTALL)
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
#: The longest title kept — a first line is sometimes a paragraph.
TITLE_CHARS = 160


def normalise(text: str) -> str:
    """One Unicode form, one line ending, no control characters, no trailing blanks, at most one
    empty line between paragraphs."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return _BLANKS.sub("\n\n", text).strip()


def decode(data: bytes) -> tuple[str | None, str]:
    """`(text, encoding)` — or `(None, why)` for bytes that are not text at all."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            return None, "it declares UTF-16 and is not valid UTF-16"
    if b"\x00" in data[:_SNIFF]:
        return None, "it holds binary data, not text"
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


def _decoded(source: Source, row: str) -> tuple[str | None, list[str], Extraction | None]:
    text, encoding = decode(source.data)
    if text is None:
        return None, [], unreadable(f"not a text file: {encoding}", row=row)
    notes = [] if encoding in ("utf-8-sig", "utf-16") else [
        f"it is not UTF-8; it was read as {encoding}, so an accented character may be wrong"]
    return text, notes, None


def first_line(text: str) -> str:
    for line in text.split("\n"):
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:TITLE_CHARS]
    return ""


def iso_date(value) -> str:
    """`YYYY-MM-DD` from a date, a datetime or a string that starts with one — else ""."""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    match = _ISO_DATE.search(str(value or ""))
    if not match:
        return ""
    try:
        return dt.date(*(int(g) for g in match.groups())).isoformat()
    except ValueError:
        return ""


def _people(value) -> list[str]:
    if isinstance(value, str):
        return [p.strip() for p in re.split(r"[;,]", value) if p.strip()]
    if isinstance(value, list):
        return [str(p).strip() for p in value if str(p or "").strip()]
    return []


def front_matter(text: str) -> tuple[dict, str, str]:
    """`(fields, body, problem)` — the leading YAML block and what follows it. A block that is
    not a mapping, or not YAML, is left in the body and named in `problem`: the document is still
    read, and the record says its front matter was not."""
    match = _FRONT.match(text)
    if not match:
        return {}, text, ""
    try:
        fields = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return {}, text, f"its front matter is not valid YAML ({str(exc).splitlines()[0][:120]})"
    if not isinstance(fields, dict):
        return {}, text, "its front matter is not a mapping, so none of it was read"
    return fields, text[match.end():], ""


class TextRow:
    """Plain text — and anything else that is text with no structure this platform reads (CSV,
    YAML, JSON): the words are indexed as they are."""

    kind = "text"

    def extract(self, source: Source) -> Extraction:
        text, notes, refused = _decoded(source, self.kind)
        if refused is not None:
            return refused
        body = normalise(text or "")
        return Extraction(readable=True, text=body, row=self.kind, title=first_line(body),
                          notes=notes)


class MarkdownRow:
    """Markdown, with its front matter read as data: `title`, `date`, `author`/`authors`, and the
    `audience` (or `visibility`) the document declares."""

    kind = "markdown"

    def extract(self, source: Source) -> Extraction:
        text, notes, refused = _decoded(source, self.kind)
        if refused is not None:
            return refused
        fields, body, problem = front_matter(text or "")
        if problem:
            notes.append(problem)
        body = normalise(body)
        fields = {str(k).strip().lower(): v for k, v in fields.items()}
        heading = _HEADING.search(body)
        title = (str(fields.get("title") or "").strip()
                 or (heading.group(1).strip() if heading else "") or first_line(body))
        declared = fields.get("audience", fields.get("visibility", ""))
        date = iso_date(fields.get("date"))
        return Extraction(readable=True, text=body, row=self.kind, title=title[:TITLE_CHARS],
                          date=date, date_from="front matter" if date else "",
                          authors=_people(fields.get("authors", fields.get("author"))),
                          audience=str(declared or "").strip(), notes=notes)


#: The words a mermaid diagram starts with — its type, which is the best title a diagram with none
#: declared has.
_MERMAID_TYPE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9-]*)", re.MULTILINE)


class MermaidRow:
    """A mermaid diagram: its source IS its text — every node label and every arrow is in it, in
    words. The title is the diagram's own (`title:` in its front matter) or its type."""

    kind = "mermaid"

    def extract(self, source: Source) -> Extraction:
        text, notes, refused = _decoded(source, self.kind)
        if refused is not None:
            return refused
        fields, body, problem = front_matter(text or "")
        if problem:
            notes.append(problem)
        body = normalise(body)
        lines = [line for line in body.split("\n") if not line.strip().startswith("%%")]
        kind = _MERMAID_TYPE.search("\n".join(lines))
        title = str(fields.get("title") or "").strip() or (
            f"a mermaid {kind.group(1)} diagram" if kind else "a mermaid diagram")
        return Extraction(readable=True, text=body, row=self.kind, title=title[:TITLE_CHARS],
                          notes=notes)


class _Words(HTMLParser):
    """An HTML body's words: tags dropped, blocks kept as lines, `<script>` and `<style>` dropped
    whole — their content is code, not words anybody wrote to a person."""

    _SKIP = ("script", "style", "head")
    _BLOCK = ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skipping += 1
        elif tag in self._BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1
        elif tag in self._BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skipping:
            self.out.append(data)


def html_words(html: str) -> str:
    reader = _Words()
    reader.feed(html)
    reader.close()
    return "".join(reader.out)


_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class HtmlRow:
    """An HTML page — an exported wiki page, a saved report: its words, and its `<title>`."""

    kind = "html"

    def extract(self, source: Source) -> Extraction:
        text, notes, refused = _decoded(source, self.kind)
        if refused is not None:
            return refused
        found = _TITLE.search(text or "")
        body = normalise(html_words(text or ""))
        title = " ".join(html_words(found.group(1)).split()) if found else ""
        return Extraction(readable=True, text=body, row=self.kind,
                          title=(title or first_line(body))[:TITLE_CHARS], notes=notes)
