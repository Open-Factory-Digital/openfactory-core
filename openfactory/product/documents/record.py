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
are both internal readers; slice 3 enforces the label in answers, this carries it on every record.
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
