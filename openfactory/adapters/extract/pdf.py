"""The rows that read a PDF: its text layer, and OCR for one that has none (#269 slice 1).

THE TEXT LAYER, WITH `pypdf`, IN A PROCESS OF ITS OWN. A PDF is the most elaborate format a
context repository holds and the one most often built to hurt a parser, so the row never parses
one in the worker: it hands the bytes to a child (`python -m openfactory.adapters.extract.pdf`) that
limits its own CPU before it reads a byte, is killed at `PDF_SECONDS`, starts with an environment
that holds no credential of this deployment, and answers one JSON `Extraction` on stdout. A PDF
that hangs the parser costs one child and one "stopped after N seconds", never a worker thread.
`pypdf` is pure Python and interprets nothing — no JavaScript, no form action, no launch — and it
bounds its own decompression (`pypdf.filters`' output ceilings).

`pypdf` IS OPTIONAL — the `ingest` extra. Without it the row answers, in a sentence, that PDF
support is not installed here and how to install it; the rest of the repository is read.

A PROTECTED PDF IS UNREADABLE, AND SAYS SO. One encrypted with an empty user password — the usual
"no printing, no copying" flags — opens and is read; one that needs a password is recorded as
protected, never guessed at.

NO TEXT LAYER IS A SCANNED PDF, AND IT IS HANDED ON, NOT DROPPED. When most pages carry no text the
row answers `fallback="scanned"` and the dispatcher asks the `scanned` type's row once — OCR by
default. A page without text inside an otherwise textual PDF is named in the notes.

OCR THROUGH TWO BINARIES THAT MAY NOT BE THERE. `pdftoppm` (poppler) renders the pages and
`tesseract` reads them; either absent is "OCR not available", in words, and never a crash. Each
runs in a scratch directory of its own with a timeout, on as many pages as `MAX_OCR_PAGES`. The
same row reads an image, when a deployment configures OCR rather than a vision model for images
(`OPENFACTORY_EXTRACT_ROWS=image=ocr`). Everything OCR reads is marked as read from pixels.

IN THE LANGUAGES THE DOCUMENTS ARE WRITTEN IN (#337). Tesseract with no `-l` reads English, and a
Portuguese scan read as English loses every accent and half its words. The languages wanted are
`OPENFACTORY_OCR_LANGS` (`por+eng` unless a deployment says otherwise), and only those this
machine's tesseract actually has are asked for — a language pack missing is a narrower reading,
never a failed one, and the notes say which languages read it.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from openfactory.adapters.extract.base import Extraction, Source, unreadable
from openfactory.adapters.extract.text import TITLE_CHARS, iso_date, normalise

#: The child's wall clock and CPU ceiling, per PDF.
PDF_SECONDS = 120
#: The most pages read from one PDF's text layer; the rest are named in the notes.
MAX_PAGES = 2000
#: The most characters the child hands back — the dispatcher cuts again at its own limit.
MAX_CHILD_TEXT = 4_000_000
#: A page with fewer letters and digits than this has no text layer worth the name.
PAGE_LETTERS = 16
#: What the child may address — enough for any honest PDF, too little for a bomb to take the host.
CHILD_MEMORY = 2 * 1024 * 1024 * 1024

#: How OCR is bounded: pages rendered, the rendering resolution, and each binary's clock.
MAX_OCR_PAGES = 50
OCR_DPI = 200
RENDER_SECONDS = 180
OCR_SECONDS = 90
#: The languages OCR reads in, `+`-separated, as tesseract names them (#337).
OCR_LANGS_ENV = "OPENFACTORY_OCR_LANGS"
DEFAULT_OCR_LANGS = "por+eng"

#: The remedy for a missing library, said once.
INSTALL_PDF = ("PDF support is not installed on this machine — install the package's `ingest` "
               "extra (from a checkout: pip install -e '.[ingest]'; the worker image carries it)")


# ── the text layer ───────────────────────────────────────────────────────────────────────────────

def _child_env() -> dict[str, str]:
    """What the child starts with: where to find this package and its libraries, and nothing else
    — no token, no key, no configuration of this deployment reaches a process parsing a
    stranger's file."""
    here = str(Path(__file__).resolve().parents[3])
    return {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": here,
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}


class PdfRow:
    """A PDF's text layer, page by page, read in a child process."""

    kind = "pdf"

    def __init__(self, *, seconds: float = PDF_SECONDS) -> None:
        self.seconds = seconds

    def extract(self, source: Source) -> Extraction:
        try:
            done = subprocess.run(  # noqa: S603 — our own interpreter and module, bytes on stdin
                [sys.executable, "-m", "openfactory.adapters.extract.pdf"], input=source.data,
                capture_output=True, timeout=self.seconds, env=_child_env(), check=False)
        except subprocess.TimeoutExpired:
            return unreadable(f"the PDF was still being read after {self.seconds:.0f} seconds — "
                              f"stopped, so one file cannot hold the others up", row=self.kind)
        except OSError as exc:
            return unreadable(f"the PDF reader could not be started ({exc})", row=self.kind)
        if done.returncode != 0:
            said = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            return unreadable(f"the PDF reader stopped (exit {done.returncode}"
                              f"{': ' + said[-1][:200] if said else ''})", row=self.kind)
        try:
            return Extraction.model_validate_json(done.stdout)
        except ValueError as exc:
            return unreadable(f"the PDF reader answered something that is not a reading ({exc})",
                              row=self.kind)


def read_pdf(data: bytes) -> Extraction:
    """The text layer of a PDF — what the child runs. Never raises."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return unreadable(INSTALL_PDF, row=PdfRow.kind)
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                opened = reader.decrypt("")
            except Exception as exc:  # noqa: BLE001 — an encryption this reader cannot open
                return unreadable(f"a protected PDF: it is encrypted in a way this reader "
                                  f"cannot open ({exc})", row=PdfRow.kind)
            if not opened:
                return unreadable("a protected PDF: it needs a password to be opened",
                                  row=PdfRow.kind)
        return _text_layer(reader)
    except Exception as exc:  # noqa: BLE001 — a PDF this reader cannot parse is unreadable
        return unreadable(f"a PDF this reader could not parse ({type(exc).__name__}: "
                          f"{str(exc)[:200]})", row=PdfRow.kind)


def _text_layer(reader) -> Extraction:
    total = len(reader.pages)
    pages: list[str] = []
    empty: list[int] = []
    notes: list[str] = []
    size = 0
    for number, page in enumerate(reader.pages, start=1):
        if number > MAX_PAGES:
            notes.append(f"only the first {MAX_PAGES} of its {total} pages were read")
            break
        text = normalise(page.extract_text() or "")
        if sum(ch.isalnum() for ch in text) < PAGE_LETTERS:
            empty.append(number)
        pages.append(f"[page {number}]\n{text}")
        size += len(text)
        if size > MAX_CHILD_TEXT:
            notes.append(f"its text was cut after page {number}, at {MAX_CHILD_TEXT} characters")
            break
    read = len(pages)
    if not read or len(empty) * 2 > read:
        return unreadable("no text layer — a scanned PDF, or one made of pictures",
                          row=PdfRow.kind, fallback="scanned", pages=total)
    if empty:
        notes.append("no text layer on page(s) " + ", ".join(str(n) for n in empty[:40])
                     + (" …" if len(empty) > 40 else "") + " — a picture there was not read")
    title, authors, date, unread = _metadata(reader)
    notes += unread
    text = "\n\n".join(pages)
    return Extraction(readable=True, text=text, row=PdfRow.kind, pages=total,
                      title=(title or _first_words(pages))[:TITLE_CHARS], authors=authors,
                      date=date, date_from="metadata" if date else "", notes=notes)


def _metadata(reader) -> tuple[str, list[str], str, list[str]]:
    """`(title, authors, date, notes)` from the document information dictionary — each empty when
    absent; one that could not be read is a note, and a malformed date in the metadata costs the
    date, never the document."""
    try:
        meta = reader.metadata or {}
    except Exception as exc:  # noqa: BLE001 — a broken info dictionary is no metadata, said
        return "", [], "", [f"its metadata could not be read ({type(exc).__name__})"]
    title = " ".join(str(getattr(meta, "title", "") or "").split())
    author = " ".join(str(getattr(meta, "author", "") or "").split())
    notes: list[str] = []
    try:
        created = getattr(meta, "creation_date", None)
    except Exception as exc:  # noqa: BLE001 — pypdf raises on a date it cannot parse
        created = None
        notes.append(f"the date in its metadata could not be read ({type(exc).__name__})")
    return title, [author] if author else [], iso_date(created) if created else "", notes


def _first_words(pages: list[str]) -> str:
    for page in pages:
        for line in page.split("\n")[1:]:
            if line.strip():
                return line.strip()
    return ""


def _limit_this_process() -> None:
    """The child's own ceilings, set before it reads a byte: CPU seconds everywhere, and address
    space where the kernel honours it (not every one does — the parent's clock still holds)."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (PDF_SECONDS, PDF_SECONDS))
        if sys.platform.startswith("linux"):
            resource.setrlimit(resource.RLIMIT_AS, (CHILD_MEMORY, CHILD_MEMORY))
    except (ImportError, ValueError, OSError):
        pass


def main() -> int:
    """The child: a PDF's bytes on stdin, one JSON `Extraction` on stdout."""
    _limit_this_process()
    extraction = read_pdf(sys.stdin.buffer.read())
    sys.stdout.write(extraction.model_dump_json())
    return 0


# ── OCR ──────────────────────────────────────────────────────────────────────────────────────────

def wanted_languages() -> list[str]:
    """The languages a deployment wants OCR to read in (`OPENFACTORY_OCR_LANGS`), in its order."""
    import re

    raw = os.environ.get(OCR_LANGS_ENV) or DEFAULT_OCR_LANGS
    return list(dict.fromkeys(w.strip() for w in re.split(r"[+,;\s]+", raw) if w.strip()))


def _tool_env() -> dict[str, str]:
    keep = ("PATH", "TESSDATA_PREFIX", "LANG", "LC_ALL")
    return {k: os.environ[k] for k in keep if k in os.environ}


class OcrRow:
    """OCR: `pdftoppm` renders a PDF's pages, `tesseract` reads each — or reads an image directly.
    `which` and `run` are the two binaries' doors, replaceable in a test."""

    kind = "ocr"

    def __init__(self, *, which=None, run=None, pages: int = MAX_OCR_PAGES) -> None:
        # resolved when the row is built, not when this module was imported
        self._which = which or shutil.which
        self._run = run or subprocess.run
        self.pages = pages

    def languages(self, tesseract: str) -> str:
        """The wanted languages this tesseract has, `+`-joined — "" when it has none of them, and
        tesseract then reads in its own default."""
        import re

        wanted = wanted_languages()
        try:
            done = self._run([tesseract, "--list-langs"], capture_output=True,
                             timeout=OCR_SECONDS, env=_tool_env(), check=False)
        except (subprocess.TimeoutExpired, OSError):
            return ""
        listed = (done.stdout or b"")
        listed = listed.decode("utf-8", "replace") if isinstance(listed, bytes) else str(listed)
        # BY NAME, WHATEVER ITS CASE (review of #340): `POR+eng` asks for Portuguese, and a
        # language dropped for its capitals would narrow the reading with only the note to say so.
        # The name tesseract is handed is its own spelling, from its own list.
        have = {line.strip().lower(): line.strip() for line in listed.splitlines()
                if re.fullmatch(r"[A-Za-z_]+", line.strip())}
        return "+".join(dict.fromkeys(have[w.lower()] for w in wanted if w.lower() in have))

    def extract(self, source: Source) -> Extraction:
        tesseract = self._which("tesseract")
        if not tesseract:
            return unreadable("OCR not available: tesseract is not installed on this machine",
                              row=self.kind)
        with tempfile.TemporaryDirectory(prefix="openfactory-ocr-") as scratch:
            room = Path(scratch)
            if source.type == "image":
                image = room / f"image{Path(source.path).suffix.lower() or '.png'}"
                image.write_bytes(source.data)
                images, notes = [image], []
            else:
                images, notes, refused = self._render(source, room)
                if refused is not None:
                    return refused
            # ASKED ONCE THERE ARE PAGES TO READ: a PDF that would not render costs no call
            langs = self.languages(tesseract)
            read = []
            for number, image in enumerate(images, start=1):
                try:
                    done = self._run([tesseract, str(image), "stdout",
                                      *(["-l", langs] if langs else [])], capture_output=True,
                                     timeout=OCR_SECONDS, env=_tool_env(), check=False)
                except subprocess.TimeoutExpired:
                    notes.append(f"page {number} took longer than {OCR_SECONDS}s and was skipped")
                    continue
                text = normalise((done.stdout or b"").decode("utf-8", "replace"))
                read.append(f"[page {number}]\n{text}" if len(images) > 1 else text)
        text = "\n\n".join(read)
        if sum(ch.isalnum() for ch in text) < PAGE_LETTERS:
            return unreadable("OCR found no legible text in it", row=self.kind, from_image=True)
        notes.append("the text was read from pixels by OCR — a character or a number may be wrong"
                     + (f" (languages: {langs})" if langs else ""))
        return Extraction(readable=True, text=text, row=self.kind, from_image=True,
                          pages=len(images), title=next(
                              (line.strip() for line in text.split("\n")
                               if line.strip() and not line.startswith("[page ")), "")[
                              :TITLE_CHARS], notes=notes)

    def _render(self, source: Source, room: Path):
        pdftoppm = self._which("pdftoppm")
        if not pdftoppm:
            return [], [], unreadable(
                "OCR not available: pdftoppm (poppler) is not installed, so the pages cannot be "
                "rendered for tesseract", row=self.kind)
        document = room / "document.pdf"
        document.write_bytes(source.data)
        try:
            done = self._run([pdftoppm, "-r", str(OCR_DPI), "-gray", "-png", "-l", str(self.pages),
                              str(document), str(room / "page")], capture_output=True,
                             timeout=RENDER_SECONDS, env=_tool_env(), check=False)
        except subprocess.TimeoutExpired:
            return [], [], unreadable(f"its pages could not be rendered for OCR within "
                                      f"{RENDER_SECONDS} seconds", row=self.kind)
        images = sorted(room.glob("page*.png"))
        if done.returncode != 0 or not images:
            said = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            return [], [], unreadable("its pages could not be rendered for OCR"
                                      + (f" ({said[-1][:200]})" if said else ""), row=self.kind)
        # THE PAGE COUNT IS NOT PARSED HERE: this process never parses a PDF. Rendering stopped
        # at the limit is the one thing it can see, and it is said.
        notes = ([f"at most the first {self.pages} pages were read by OCR"]
                 if len(images) >= self.pages else [])
        return images, notes, None


if __name__ == "__main__":  # pragma: no cover — the child's entry point
    sys.exit(main())
