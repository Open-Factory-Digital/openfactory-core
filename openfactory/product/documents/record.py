"""What is read about a document WITHOUT a model, and who may read it (#269 slice 1).

DETERMINISTIC FIRST (`docs/knowledge-layer.md` §10). The area, the dates, the requirements and
cards a text cites and the product's vocabulary it uses are all exact reads of the path and the
text — a regular expression is right every time it matches and costs nothing, so none of this
waits for a model or pays for one.

THE AUDIENCE LABEL (#266 decision 8, #269 point 7). A document says who may read it in one of two
ways, and the narrowest wins when they disagree:

  - WHERE IT IS: a folder named for its audience anywhere on its path — `internal/`, `private/`,
    `confidential/` (and their Portuguese spellings) make it internal; `client/`, `public/`,
    `shared/` make it the client's;
  - WHAT IT SAYS: a markdown document's front matter, `audience:` (or `visibility:`).

Nothing declared is `internal` — the safe default: an e-mail dropped into the repository without a
thought must not reach a client because nobody labelled it. A label nobody here knows is read as
internal, with a note, so no spelling can widen a document; and a document under `internal/` stays
internal whatever its front matter says. The two roles inside a product (its admins, its engineers)
are both internal readers — in a conversation of their own (`turn_audience`): that is the reading
the role's facts and briefing list documents for, and every other turn is told only how many
internal documents it is not shown.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

from openfactory.contracts.document import CLIENT, DEFAULT_AUDIENCE, INTERNAL, narrowest

#: Folder names that label everything under them.
INTERNAL_FOLDERS = frozenset({"internal", "interno", "interna", "internos", "private", "privado",
                              "privada", "confidential", "confidencial"})
CLIENT_FOLDERS = frozenset({"client", "clients", "cliente", "clientes", "public", "publico",
                            "público", "shared", "external"})

#: What front matter may say, and which label each spelling is.
_DECLARED = {
    **{word: CLIENT for word in ("client", "clients", "cliente", "clientes", "public", "publico",
                                 "público", "external", "shared", "everyone")},
    **{word: INTERNAL for word in ("internal", "interno", "interna", "private", "privado",
                                   "confidential", "confidencial", "restricted", "team",
                                   "engineer", "engineers", "engineering", "product admin",
                                   "admin", "admins")},
}


def path_audience(path: str) -> str:
    """The label the folders on `path` give it, or "" when none is named for an audience."""
    labels = []
    for folder in PurePosixPath(path).parts[:-1]:
        name = folder.strip().lower()
        if name in INTERNAL_FOLDERS:
            labels.append(INTERNAL)
        elif name in CLIENT_FOLDERS:
            labels.append(CLIENT)
    return narrowest(*labels) if labels else ""


def audience(path: str, declared: str = "") -> tuple[str, str, list[str]]:
    """`(label, where it came from, notes)` — the path's and the document's own, narrowest first."""
    notes: list[str] = []
    said = " ".join(str(declared or "").split()).lower()
    from_text = ""
    if said:
        from_text = _DECLARED.get(said, "")
        if not from_text:
            from_text = INTERNAL
            notes.append(f"its audience {said!r} is not a label this platform knows — read as "
                         f"internal")
    from_path = path_audience(path)
    sources = [name for name, value in (("path", from_path), ("front matter", from_text))
               if value]
    if not sources:
        return DEFAULT_AUDIENCE, "default", notes
    return narrowest(from_path, from_text), " and ".join(sources), notes


def turn_audience(person, *, private: bool) -> str:
    """The documents a turn may be shown: ALL OF THEM, to whoever talks to the product role.

    THE PRODUCT ROLE IS THE PRODUCT'S OWNER, and everybody who talks to it — a co-owner, an
    engineer, a client — may read everything the product exposes (the product owner's decision of
    2026-09-25, which replaces #266 decision 8 for what the role reads). Until then an internal
    document was shown only to an admin or an engineer in a conversation of their own, and every
    room and every client was told only how many there were. The labels stay what a document
    says about itself; nothing a turn reads is withheld by them. What stays private is a PERSON's
    conversation (`conversation.py`), which is not something the product exposes. `person` and
    `private` are kept for the callers: who is asking still shapes how the role speaks
    (`speaker.py`), never what it may read."""
    del person, private
    return INTERNAL


def area(path: str) -> str:
    """The top-level folder a document sits in — "" at the repository's root."""
    parts = PurePosixPath(path).parts
    return parts[0] if len(parts) > 1 else ""


_NAME_DATE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])"
                        r"(?!\d)")


def file_name_date(path: str) -> str:
    """A date written in the file's name (`2024-03-12-minutes.md`, `sla_20240312.pdf`), or ""."""
    match = _NAME_DATE.search(PurePosixPath(path).name)
    return "-".join(match.groups()) if match else ""


def commit_date(root: Path, path: str) -> str:
    """When the last commit that touched `path` was made, or "" outside a repository — the date a
    document with no date of its own is dated by, and said to be (`date_from="commit"`).

    ONLY WHEN `root` IS THE REPOSITORY'S OWN TOP: a tree that merely sits inside some other
    repository would otherwise be dated by that repository's history."""
    if not (Path(root) / ".git").exists():
        return ""
    try:
        done = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%cI", "--", path],
                              capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()[:10] if done.returncode == 0 else ""


#: `REQ-0041`, `REQ 41`, `req41`; "requirement 41", "requisito nº 41"; `requirements/0041-…`.
_REQUIREMENTS = (
    re.compile(r"\bREQ[-_ ]?0*(\d{1,5})\b", re.IGNORECASE),
    re.compile(r"\b(?:requirement|requisito|requerimento)s?\s*(?:n[ºo°.]*\s*)?#?\s*0*(\d{1,5})\b",
               re.IGNORECASE),
    re.compile(r"\brequirements?/0*(\d{1,5})-", re.IGNORECASE),
)
#: `#512`, "card 512", "cartão 512", "issue #512", "ticket 512" — never an HTML entity (`&#39;`),
#: a URL fragment, or a number with a leading zero (a colour, a code).
_CARDS = (
    re.compile(r"(?<![\w&/#])#([1-9]\d{0,5})\b(?![\w-])"),
    re.compile(r"\b(?:card|cart[ãa]o|issue|ticket)s?\s*#?\s*([1-9]\d{0,5})\b", re.IGNORECASE),
)


def requirements_cited(text: str) -> list[int]:
    found = {int(m.group(1)) for pattern in _REQUIREMENTS for m in pattern.finditer(text)}
    return sorted(n for n in found if n > 0)


def cards_cited(text: str) -> list[str]:
    found = {m.group(1) for pattern in _CARDS for m in pattern.finditer(text)}
    return sorted(found, key=int)


def entities(text: str, terms) -> list[str]:
    """The product's vocabulary — its glossary's terms — that `text` uses, whole words, any case."""
    out = []
    for term in sorted({str(t).strip() for t in terms if str(t or "").strip()}):
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE):
            out.append(term)
    return out


# ── the distillates (#269 slice 3, ADR-0053 D4) ────────────────────────────────────────────────

#: Where the platform writes what a conversation that went quiet agreed, asked and decided
#: (`product/distil.py`): one folder per conversation, under the kind of conversation it was — a
#: ROOM, which everybody in it read, or a DIRECT one, one person's alone. The folder is named by the
#: conversation's DIGEST (`index/items.py::conversation_digest`), never by its key: a private key
#: is a person's id, and this path is in a repository every one of the product's people can clone.
DISTILLATES = "conversations"
ROOM, DIRECT = "room", "direct"
_DISTILLATE = re.compile(rf"^{DISTILLATES}/({ROOM}|{DIRECT})/([0-9a-f]{{16}})/[^/]+\.md$")


def distillate_path(*, private: bool, digest: str, name: str) -> str:
    """Where one span of one conversation is written — `conversations/<room|direct>/<digest>/`."""
    return f"{DISTILLATES}/{DIRECT if private else ROOM}/{digest}/{name}"


def distillate_of(path: str) -> tuple[bool, str] | None:
    """`(private, conversation digest)` for a distillate's path — None for every other document.
    Read off the path alone, the way the audience's folder is: what a file IS never waits for a
    model, and a file that merely looks like one somewhere else in the tree is not one."""
    match = _DISTILLATE.match(str(path or ""))
    return (match.group(1) == DIRECT, match.group(2)) if match else None


# ── what one turn's view of the repository may hold (#269 slice 3, ADR-0053 D10) ───────────────

#: How much of a markdown file is read for the audience its front matter declares — the block sits
#: at the top, and a block longer than this is read as no block: the narrow reading.
_FRONT_MATTER_BYTES = 16 * 1024


def declared(root: Path, path: str) -> str:
    """The audience a markdown document declares in its front matter (`audience:` or
    `visibility:`) — "" for any other file, one without a block, or one that cannot be read. The
    same block the markdown row reads at ingestion (`adapters/extract/text.py::front_matter`)."""
    from openfactory.adapters.extract.text import decode, front_matter

    if PurePosixPath(path).suffix.lower() not in (".md", ".markdown"):
        return ""
    try:
        with (Path(root) / path).open("rb") as handle:
            head = handle.read(_FRONT_MATTER_BYTES)
    except OSError:
        return ""
    text, _problem = decode(head)
    fields, _body, _problem = front_matter(text or "")
    fields = {str(k).strip().lower(): v for k, v in fields.items()}
    return str(fields.get("audience", fields.get("visibility", "")) or "").strip()


def withheld(root: Path, reader: str, *, own: str = "", curated=None) -> list[str]:
    """Every file of the context repository at `root` that a turn read by `reader` may not be
    handed — `/`-spelled, relative to `root`, sorted.

    THE VIEW IS A PATH INTO THE PROMPT TOO. The role reads its workspace with its harness's tools,
    so a document copied into a client's view is a document a client's answer can be built from,
    whatever the index and the facts withhold. The rule is the index's, read off the same two
    places slice 1 reads it (the folder, and the document's own front matter), the narrowest
    winning and nothing declared being internal:

      - a document whose audience `reader` may not read is withheld;
      - a DIRECT conversation's distillate is withheld from every conversation but its own
        (`own`, the key of the conversation the turn answers), whoever reads — a private
        conversation's content comes back only to its person (ADR-0053 D10);
      - `curated(path)` says what is the product's curated truth — its requirements and its
        glossary, which every prompt already carries — and is shown to everybody;
      - a hidden file or folder is not a document (`.okf/`, `.openfactory/`), not decided here;
      - a symbolic link is judged by where it sits, never by what it points at."""
    from openfactory.contracts.document import may_read
    from openfactory.product.documents.ingest import documents_in
    from openfactory.product.index.items import conversation_digest

    mine = conversation_digest(own) if own else ""
    out: list[str] = []
    for path in documents_in(Path(root)):
        if curated is not None and curated(path):
            continue
        distilled = distillate_of(path)
        if distilled is not None and distilled[0] and distilled[1] != mine:
            out.append(path)
            continue
        link = (Path(root) / path).is_symlink()
        label, _from, _notes = audience(path, "" if link else declared(root, path))
        if not may_read(label, reader):
            out.append(path)
    return sorted(out)
