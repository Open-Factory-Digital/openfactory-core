"""The rows that read XML diagrams: draw.io and SVG (#269 slice 1), over a parser that refuses
entities.

NO ENTITY IS EVER DEFINED OR RESOLVED. `defusedxml` is not a dependency of this platform, so the
refusal is written here, explicitly, on the standard library's expat:

  - a document type declaration WITH AN INTERNAL SUBSET is refused — that subset is where entities
    are declared, and a document that declares its own is refused before its first element;
  - any entity declaration, parsed or unparsed, is refused (belt and braces, should expat ever
    report one outside a subset);
  - an external entity reference is refused, and parameter entities are never parsed, so no DTD
    is fetched from a file or a network;
  - the tree is bounded — elements and depth — so a document cannot make the parser build a
    structure larger than any real diagram.

A plain `<!DOCTYPE svg PUBLIC …>` with no subset is allowed: it names a DTD that is never read, and
many exported SVGs carry one.

A DRAW.IO FILE MAY BE COMPRESSED. Each page's content is then base64, raw-deflated and
URL-encoded; it is inflated with a hard ceiling on what one page may inflate to, so a small file
cannot expand into memory the platform does not have, and the inner XML goes through the same
parser.

WHAT A DIAGRAM SAYS, AS TEXT. Every shape's label, and every connector as `from → to` with its own
label: "Order service → Payments: charges the card" is what a person reading the diagram
understands and what a question about it will use. A label written in HTML (draw.io's `html=1`)
is reduced to its words by the standard library's HTML parser, which executes nothing.
"""

from __future__ import annotations

import base64
import binascii
import zlib
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote
from xml.parsers import expat

from openfactory.adapters.extract.base import Extraction, Source, unreadable
from openfactory.adapters.extract.text import TITLE_CHARS, normalise

#: The largest tree built from one document, and its deepest nesting.
MAX_ELEMENTS = 200_000
MAX_DEPTH = 256
#: What one compressed draw.io page may inflate to.
MAX_INFLATED = 16 * 1024 * 1024


class Refused(ValueError):
    """The XML asked for something this parser does not do — said in a sentence."""


@dataclass
class Element:
    tag: str
    attrs: dict[str, str]
    children: list[Element] = field(default_factory=list)
    text: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        """The tag without a namespace prefix — `svg:text` and `text` are one element here."""
        return self.tag.rsplit(":", 1)[-1].rsplit("}", 1)[-1]

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def words(self) -> str:
        return "".join(self.text).strip()


def parse(data: bytes | str) -> Element:
    """The document's tree — or `Refused` for anything that declares or resolves an entity, and
    `expat.ExpatError` for XML that is not well formed."""
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.buffer_text = True
    root: list[Element] = []
    stack: list[Element] = []
    count = [0]

    def doctype(name, system_id, public_id, has_internal_subset):
        if has_internal_subset:
            raise Refused("it declares a document type of its own, where entities are defined — "
                          "refused, so nothing in it can be expanded or fetched")

    def entity(*_args):
        raise Refused("it declares an entity — refused, so nothing in it can be expanded or "
                      "fetched")

    def external(*_args):
        raise Refused("it refers to an external entity — refused, nothing is fetched")

    def start(tag, attrs):
        count[0] += 1
        if count[0] > MAX_ELEMENTS:
            raise Refused(f"it holds more than {MAX_ELEMENTS} elements")
        if len(stack) >= MAX_DEPTH:
            raise Refused(f"it nests deeper than {MAX_DEPTH} levels")
        element = Element(tag=tag, attrs=dict(attrs))
        (stack[-1].children if stack else root).append(element)
        stack.append(element)

    def end(_tag):
        stack.pop()

    def chars(data):
        if stack:
            stack[-1].text.append(data)

    parser.StartDoctypeDeclHandler = doctype
    parser.EntityDeclHandler = entity
    parser.UnparsedEntityDeclHandler = entity
    parser.ExternalEntityRefHandler = external
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    parser.Parse(data, True)
    if not root:
        raise Refused("it holds no element")
    return root[0]


class _Words(HTMLParser):
    """An HTML label's words — tags dropped, a line break kept as a space. Parsing only: nothing
    in the markup is loaded, run or followed."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "div", "p", "li"):
            self.out.append(" ")

    def handle_data(self, data):
        self.out.append(data)


def label_words(label: str) -> str:
    """A draw.io label as words: its HTML, if any, reduced to text, and its whitespace collapsed."""
    if "<" in label and ">" in label:
        reader = _Words()
        reader.feed(label)
        reader.close()
        label = "".join(reader.out)
    return " ".join(label.split())


def inflate(page: str) -> str:
    """A compressed draw.io page's XML: base64, then raw deflate, then URL-encoding — bounded."""
    try:
        raw = base64.b64decode("".join(page.split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise Refused(f"a page is neither XML nor draw.io's compressed form ({exc})") from exc
    inflater = zlib.decompressobj(-zlib.MAX_WBITS)
    try:
        out = inflater.decompress(raw, MAX_INFLATED + 1)
    except zlib.error as exc:
        raise Refused(f"a compressed page could not be inflated ({exc})") from exc
    if len(out) > MAX_INFLATED or inflater.unconsumed_tail:
        raise Refused(f"a compressed page inflates past {MAX_INFLATED // (1024 * 1024)} MB")
    return unquote(out.decode("utf-8", errors="replace"))


def _pages(root: Element) -> list[tuple[str, Element]]:
    """`(name, mxGraphModel)` per page — inline or compressed; a bare model is one page."""
    if root.name == "mxGraphModel":
        return [("", root)]
    pages = []
    for diagram in (e for e in root.walk() if e.name == "diagram"):
        name = diagram.attrs.get("name", "")
        model = next((c for c in diagram.children if c.name == "mxGraphModel"), None)
        if model is None and diagram.words():
            model = parse(inflate(diagram.words()))
        if model is not None:
            pages.append((name, model))
    return pages


def _page_lines(model: Element) -> list[str]:
    """A page's shapes and connectors as lines — `- label`, `- from → to: label`."""
    labels: dict[str, str] = {}
    cells: list[dict[str, str]] = []
    for element in model.walk():
        if element.name in ("UserObject", "object"):
            # A shape with properties: the id and the label are on the wrapper, the geometry and
            # the edge/vertex flags on the mxCell inside it.
            inner = next((c for c in element.children if c.name == "mxCell"), None)
            cell = {**(inner.attrs if inner else {}), **element.attrs}
            cell["value"] = element.attrs.get("label", cell.get("value", ""))
            cells.append(cell)
        elif element.name == "mxCell" and "id" in element.attrs:
            cells.append(dict(element.attrs))
    edges = {c["id"] for c in cells if c.get("edge") == "1" and c.get("id")}
    edge_labels: dict[str, list[str]] = {}
    for cell in cells:
        words = label_words(cell.get("value", ""))
        if not words:
            continue
        if cell.get("parent") in edges:
            # a label placed ON a connector is a child cell of that connector
            edge_labels.setdefault(cell["parent"], []).append(words)
        elif cell.get("edge") != "1":
            labels[cell.get("id", "")] = words
    lines = [f"- {words}" for words in labels.values()]
    for cell in cells:
        if cell.get("edge") != "1":
            continue
        said = [label_words(cell.get("value", "")), *edge_labels.get(cell.get("id", ""), [])]
        said = [w for w in said if w]
        source = labels.get(cell.get("source", ""), "")
        target = labels.get(cell.get("target", ""), "")
        if not (source or target or said):
            continue
        line = f"- {source or '(unlabelled)'} → {target or '(unlabelled)'}"
        lines.append(line + (f": {'; '.join(said)}" if said else ""))
    return lines


class DrawioRow:
    """A draw.io (diagrams.net) file: every page, its shapes and its connectors, as words."""

    kind = "drawio"

    def extract(self, source: Source) -> Extraction:
        try:
            pages = _pages(parse(source.data))
        except Refused as exc:
            return unreadable(f"a diagram this platform will not parse: {exc}", row=self.kind)
        except expat.ExpatError as exc:
            return unreadable(f"not well-formed XML ({exc})", row=self.kind)
        if not pages:
            return unreadable("a draw.io file with no page in it", row=self.kind)
        out: list[str] = []
        for name, model in pages:
            lines = _page_lines(model)
            out += [f"# {name}" if name else "# (a page)", *(lines or ["(no labelled shape)"]), ""]
        text = normalise("\n".join(out))
        named = next((name for name, _ in pages if name), "")
        return Extraction(readable=True, text=text, row=self.kind,
                          title=(named or "a draw.io diagram")[:TITLE_CHARS])


#: The SVG elements whose content is words a person reads.
_SVG_WORDS = ("title", "desc", "text")


class SvgRow:
    """An SVG: the words it carries — its title, its description and every text element. An SVG
    of shapes alone has no words to read and says so: its content is the picture, which a vision
    row may be configured to describe."""

    kind = "svg"

    def extract(self, source: Source) -> Extraction:
        try:
            root = parse(source.data)
        except Refused as exc:
            return unreadable(f"an SVG this platform will not parse: {exc}", row=self.kind)
        except expat.ExpatError as exc:
            return unreadable(f"not well-formed XML ({exc})", row=self.kind)
        words = []
        for element in root.walk():
            if element.name in _SVG_WORDS:
                said = " ".join("".join(e.words() + " " for e in element.walk()).split())
                if said:
                    words.append(said)
        if not words:
            return unreadable("an SVG with no words in it — its content is only shapes",
                              row=self.kind)
        title = next((" ".join(e.words().split()) for e in root.walk() if e.name == "title"
                      and e.words()), "")
        return Extraction(readable=True, text=normalise("\n".join(words)), row=self.kind,
                          title=(title or words[0])[:TITLE_CHARS])
