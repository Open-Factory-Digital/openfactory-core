"""The requirements themselves — parsed, indexed, and checked for the ways a corpus rots.

ADR-0019 names the failure mode of this whole design: if execution outcomes stop reaching the
documents, the repository becomes a wish-list describing a product nobody built, contradicting the
code with total confidence. That failure is silent by nature — nothing crashes, a file simply stops
being true — so it has to be *detected* rather than waited for. This module is that detector, and
the reason it exists before the agent that writes into the corpus does.

TWO RULES THROUGHOUT

1. **Parsing never raises.** A malformed requirement is a finding, not a crash. A single bad file
   must not make the whole corpus unreadable — that would take the product role offline over one
   typo, which is a far worse outcome than one requirement being flagged.
2. **Every finding names the file.** A validator that reports "3 problems" without saying where is
   a validator nobody runs twice.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

#: `0001-slug.md` — the number is the identity, and it comes from the FILENAME rather than the
#: heading so that two files can never claim the same id while looking different on disk.
_FILE_RE = re.compile(r"^(?P<num>\d{4})-(?P<slug>[a-z0-9][a-z0-9-]*)\.md$")

#: `# REQ-0001 — title`
_TITLE_RE = re.compile(r"^#\s+REQ-(?P<num>\d{4})\s*[—–-]\s*(?P<title>.+?)\s*$", re.MULTILINE)

#: `- **Status:** accepted` — tolerant of the bold markers being dropped, because a human editing
#: a markdown file by hand should not lose a requirement's status to a missing asterisk.
def _field_re(name: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*[-*]\s*\**{name}:?\**\s*:?\s*(?P<value>.*?)\s*$",
                      re.MULTILINE | re.IGNORECASE)


#: THE status-line pattern — one regex for reading AND rewriting. The writers in `authoring.py`
#: (`_set_status_accepted`, `_mark_superseded`) locate the line with this exact object: each once
#: carried its own stricter pattern, so a file this parser read perfectly well was one the writers
#: silently failed to flip — and an accept was answered "já estava acordado" over a requirement
#: still `proposed`. Sharing the object, not a copy, is what makes that drift impossible.
_STATUS_RE = _field_re("Status")
_ASKED_RE = _field_re("Asked by")
_DATE_RE = _field_re("Date")
_SUPERSEDES_RE = _field_re("Supersedes")

#: the number in `superseded-by 0007`
_SUPERSEDED_BY_RE = re.compile(r"superseded[-\s]?by\s*:?\s*(?:REQ-)?(\d{4})", re.IGNORECASE)

#: `observed` is NOT a weaker `proposed`, and the difference is the whole reason it exists.
#:
#: `proposed` means a PERSON asked for this. `observed` means the code currently behaves this way
#: and somebody reverse-engineered it — nobody has said it is intended. Collapsing the two would
#: freeze bugs into promises: once a behaviour is an accepted requirement the factory DEFENDS it,
#: so a future fix reads as a violation. Anything reverse-engineered therefore lands as `observed`
#: and stays there until a human confirms it, which is the only event that turns behaviour into a
#: commitment.
PROPOSED, ACCEPTED, SUPERSEDED = "proposed", "accepted", "superseded"
OBSERVED = "observed"

#: Abandoned — decided against, with nothing taking its place. A SEPARATE STATUS FROM `superseded`,
#: and the distinction is the record's honesty rather than taxonomy: `superseded-by NNNN` says "read
#: that one instead", so using it for a requirement nobody replaced would point the reader at a
#: document that does not exist, and `_cross_check`'s own dangling-pointer rule would (rightly)
#: call it an error.
#:
#: This status exists because the product owner asked the obvious product question the platform had
#: no answer to: *"something that will no longer be done — isn't that very common in a conversation
#: with a PO?"* It is, and until now the only way to retire anything was to WRITE SOMETHING ELSE,
#: which is the exact opposite of what "we are not doing this" means.
DROPPED = "dropped"
_KNOWN_STATUS = {PROPOSED, ACCEPTED, SUPERSEDED, OBSERVED, DROPPED}

#: the scaffold shipped with a new documentation repo. It is not a requirement and must never be
#: counted as one, or every corpus starts life with a permanently unfinished entry.
TEMPLATE_NUMBER = 0


class Finding(BaseModel):
    """One problem with the corpus. `level` is `error` (this requirement cannot be trusted) or
    `warn` (it can, but something is decaying)."""

    level: str
    code: str
    path: str
    message: str


class Requirement(BaseModel):
    number: int
    slug: str
    path: str
    title: str = ""
    status: str = PROPOSED
    superseded_by: int | None = None
    asked_by: str = ""
    date: str = ""
    supersedes: list[int] = Field(default_factory=list)
    #: source repos / areas the requirement says it affects, verbatim — never resolved here. A
    #: citation that no longer resolves is a flag for a human to review the requirement, never an
    #: error and never silently repaired (ADR-0019: requirement↔code drift cannot be checksummed).
    affects: list[str] = Field(default_factory=list)
    #: whether the file records anything under "Decisions taken during execution" — the write-back
    #: loop, and the single measurable signal that the corpus is still alive
    has_decisions: bool = False
    body: str = ""

    #: how strongly the behaviour is evidenced, for a reverse-engineered entry: `asked` (a human
    #: asked for it in an issue or PR — real provenance), `tested` (a test asserts it, so somebody
    #: made it a promise on purpose), `code` (the code does it, with nothing asserting it — the
    #: most likely to be accidental). Empty for an authored requirement, which needs no tier.
    evidence: str = ""

    @property
    def is_promise(self) -> bool:
        """Whether the factory should DEFEND this. Only an accepted requirement is a commitment;
        an observed one is a reading of the code that nobody has confirmed."""
        return self.status == ACCEPTED

    @property
    def is_live(self) -> bool:
        """Whether this requirement still describes what the product should do. Superseded and
        dropped ones are kept deliberately — the history of what was decided and then reversed is
        what stops the same question being asked a third time — but they must never be handed to an
        agent as current truth.

        The two dead states are one predicate here and two facts everywhere else: `superseded`
        sends the reader to a replacement, `dropped` says there is none."""
        return self.status not in (SUPERSEDED, DROPPED)


class Corpus(BaseModel):
    """Every requirement in a documentation repo, plus what is wrong with it."""

    requirements: list[Requirement] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)

    def by_number(self, number: int) -> Requirement | None:
        return next((r for r in self.requirements if r.number == number), None)

    def live(self) -> list[Requirement]:
        return [r for r in self.requirements if r.is_live]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    def observed(self) -> list[Requirement]:
        """Reverse-engineered readings awaiting confirmation."""
        return [r for r in self.requirements if r.status == OBSERVED]

    def promises(self) -> list[Requirement]:
        return [r for r in self.requirements if r.is_promise]

    def summary(self) -> str:
        """Counted so that "we have 40 requirements" cannot quietly mean "40 readings of the code
        and no decisions" — the distinction the `observed` status exists to preserve."""
        obs = len(self.observed())
        parts = [f"{len(self.requirements)} requirements",
                 f"{len(self.promises())} accepted"]
        if obs:
            parts.append(f"{obs} observed (unconfirmed)")
        return (f"{', '.join(parts)} — {len(self.errors)} errors, "
                f"{len(self.findings) - len(self.errors)} warnings")


def _status_of(text: str, path: str) -> tuple[str, int | None, list[Finding]]:
    """The status, plus the requirement that replaced it. Unknown text does NOT become `accepted`:
    an unreadable status must never promote a draft into something the factory will build."""
    m = _STATUS_RE.search(text)
    raw = (m.group("value") if m else "").strip()
    # strip a trailing markdown comment, which the template uses to list the allowed values
    raw = re.sub(r"<!--.*?-->", "", raw).strip().lower()
    if not raw:
        return PROPOSED, None, [Finding(
            level="warn", code="status-missing", path=path,
            message="no `Status:` line; treated as `proposed` (never as accepted — an unreadable "
                    "status must not promote a draft into something the factory will build)")]
    sup = _SUPERSEDED_BY_RE.search(raw)
    if sup:
        return SUPERSEDED, int(sup.group(1)), []
    if raw.startswith(SUPERSEDED):
        return SUPERSEDED, None, [Finding(
            level="error", code="superseded-without-target", path=path,
            message="status is `superseded` but names no replacement; write "
                    "`superseded-by NNNN` so the reader can follow the decision")]
    word = raw.split()[0]
    if word in _KNOWN_STATUS:
        return word, None, []
    return PROPOSED, None, [Finding(
        level="error", code="status-unknown", path=path,
        message=f"unknown status {raw!r}; expected `proposed`, `accepted`, `dropped` or "
                f"`superseded-by NNNN`. Treated as `proposed`.")]


def _numbers(value: str) -> list[int]:
    return [int(n) for n in re.findall(r"\b(\d{4})\b", value or "")]


def _section(text: str, heading: str) -> str:
    """The body of one `## Heading` section, or "" — used to read the parts of a requirement whose
    presence is itself information."""
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(?P<body>.*?)(?=^##\s|\Z)",
                  text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return (m.group("body") if m else "").strip()


def _bullets(block: str) -> list[str]:
    out = []
    for line in block.splitlines():
        s = line.strip()
        if s.startswith(("-", "*")) and len(s) > 2:
            item = s[1:].strip().strip("`")
            if item and not item.startswith("["):  # skip checkbox criteria
                out.append(item)
    return out


def parse_requirement(path: Path, text: str) -> tuple[Requirement | None, list[Finding]]:
    """One requirement file. Returns `(None, findings)` only when the FILENAME is unusable — the
    number is the identity, so without it there is nothing to record the problem against."""
    name = path.name
    fm = _FILE_RE.match(name)
    if not fm:
        return None, [Finding(
            level="error", code="filename", path=name,
            message="expected `NNNN-slug.md` (lowercase slug). The number is the requirement's "
                    "identity and is read from the filename, so two files can never claim the "
                    "same id while looking different on disk.")]

    number, slug = int(fm.group("num")), fm.group("slug")
    findings: list[Finding] = []

    tm = _TITLE_RE.search(text)
    title = tm.group("title").strip() if tm else ""
    if not tm:
        findings.append(Finding(level="warn", code="title-missing", path=name,
                                message="no `# REQ-NNNN — title` heading"))
    elif int(tm.group("num")) != number:
        findings.append(Finding(
            level="error", code="number-mismatch", path=name,
            message=f"the heading says REQ-{tm.group('num')} but the filename says "
                    f"{number:04d}; the filename wins, and one of the two is a copy-paste"))

    status, superseded_by, status_findings = _status_of(text, name)
    findings += status_findings

    asked = _ASKED_RE.search(text)
    date = _DATE_RE.search(text)
    supersedes = _SUPERSEDES_RE.search(text)

    req = Requirement(
        number=number, slug=slug, path=name, title=title, status=status,
        superseded_by=superseded_by,
        asked_by=_clean(asked.group("value") if asked else ""),
        date=_clean(date.group("value") if date else ""),
        supersedes=_numbers(supersedes.group("value") if supersedes else ""),
        affects=_bullets(_section(text, "Affects")),
        has_decisions=bool(_decision_rows(text)),
        body=text,
    )

    # Provenance is not decoration: a requirement nobody can trace back to a person and a date is
    # one nobody can question later. Only warn — a requirement without it is still a requirement.
    if status == ACCEPTED and not req.asked_by:
        findings.append(Finding(level="warn", code="no-asker", path=name,
                                message="accepted, but records no `Asked by:` — the trace back to "
                                        "whoever wanted it is gone"))
    if status == ACCEPTED and not req.date:
        findings.append(Finding(level="warn", code="no-date", path=name,
                                message="accepted, but records no `Date:`"))
    return req, findings


def _clean(value: str) -> str:
    return re.sub(r"<!--.*?-->", "", value or "").strip().strip("<>").strip()


#: The heading of the decision register, WRITTEN ONCE. The renderer creates this section, this
#: module reads it, `_cross_check` complains when an agreed requirement has nothing in it, and
#: `authoring.record_decision` appends to it. Four places agreeing on a string by having all been
#: typed the same way is three chances for the fourth to drift — and the one that drifts is the
#: WRITER, whose rows then land in a section nothing reads while the file looks correct.
DECISIONS_HEADING = "Decisions taken during execution"


def find_decisions_table(text: str) -> tuple[int, int] | None:
    """`(start, end)` of the decision table's byte range inside `text`, or None.

    THE WRITER'S HALF OF THE READER BELOW, and it is here rather than in `authoring` so the two
    cannot disagree about what the table is. A writer with its own idea of where the section ends
    appends rows outside it: `has_decisions` stays False, `no-write-back` keeps firing, and the
    client is looking at a decision the corpus swears was never recorded.
    """
    m = re.search(rf"^##\s+{re.escape(DECISIONS_HEADING)}\s*$(?P<body>.*?)(?=^##\s|\Z)",
                  text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return (m.start("body"), m.end("body")) if m else None


def _decision_rows(text: str) -> list[str]:
    """Rows written back under "Decisions taken during execution" — the write-back loop. The
    template's header and separator rows are not decisions."""
    block = _section(text, DECISIONS_HEADING)
    rows = []
    for line in block.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not any(cells):
            continue
        joined = " ".join(cells).lower()
        if set(joined) <= set("-: ") or joined.startswith("date "):
            continue  # separator / header
        rows.append(s)
    return rows


def load_corpus(requirements_dir: str | Path) -> Corpus:
    """Every `NNNN-slug.md` under a directory, parsed and cross-checked.

    A missing directory is a finding, not an exception: the product module must be able to report
    "your requirements repo has no requirements yet" rather than fail to start."""
    root = Path(requirements_dir)
    if not root.is_dir():
        return Corpus(findings=[Finding(
            level="error", code="no-directory", path=str(root),
            message="the requirements directory does not exist")])

    reqs: list[Requirement] = []
    findings: list[Finding] = []
    seen: dict[int, str] = {}

    for path in sorted(root.iterdir()):
        if not path.is_file() or path.suffix != ".md":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # unreadable file — a finding, never a crash
            findings.append(Finding(level="error", code="unreadable", path=path.name,
                                    message=f"could not be read: {exc}"))
            continue
        req, file_findings = parse_requirement(path, text)
        findings += file_findings
        if req is None:
            continue
        if req.number == TEMPLATE_NUMBER:
            continue  # the scaffold, not a requirement
        if req.number in seen:
            findings.append(Finding(
                level="error", code="duplicate-number", path=path.name,
                message=f"REQ-{req.number:04d} is already defined by {seen[req.number]}; "
                        f"a requirement's number is its identity and two files cannot share one"))
            continue
        seen[req.number] = path.name
        reqs.append(req)

    findings += _cross_check(reqs)
    return Corpus(requirements=reqs, findings=findings)


def _by_slug(reqs: list[Requirement]) -> dict[str, list[Requirement]]:
    """Requirements grouped by the slug in their filename, oldest number first.

    The slug is derived from the title by the same `slugify` the writer uses, so it is the one
    identity two files can share without sharing a number."""
    groups: dict[str, list[Requirement]] = {}
    for r in sorted(reqs, key=lambda x: x.number):
        if r.slug:
            groups.setdefault(r.slug, []).append(r)
    return groups


def _cross_check(reqs: list[Requirement]) -> list[Finding]:
    """The checks no single file can make on its own — dangling links between requirements, and the
    decay this whole module exists to catch."""
    out: list[Finding] = []
    known = {r.number for r in reqs}

    # TWO LIVE FILES CARRYING ONE SLUG ARE ONE PROMISE WEARING TWO NUMBERS, and the corpus can say
    # so without anybody's judgment: the slug comes from the title, so an identical slug is an
    # identical title. Observed in production on 2026-07-30 — `0002-totais-de-iva-…` and
    # `0003-totais-de-iva-…`, both live, one of them accepted. The two supersede paths that
    # existed both require the DRAFTER to know it is replacing something; here it did not, because
    # the conversation called the new text "the final version of requirement 2" and this platform
    # has no update-in-place, so the rewrite minted a new number and left its own predecessor
    # standing. An error rather than a warning: the factory picks whichever it reads first.
    for slug, group in _by_slug(reqs).items():
        live = [r for r in group if r.is_live]
        if len(live) < 2:
            continue
        listed = ", ".join(f"REQ-{r.number:04d} ({r.status})" for r in live)
        out.append(Finding(
            level="error", code="same-promise-twice", path=live[-1].path,
            message=f"{listed} are all live and share one title ({slug!r}) — that is one promise "
                    f"under several numbers, and the factory will defend whichever it reads "
                    f"first. Exactly one of them may stay live; the rest belong "
                    f"`superseded-by` it."))

    for r in reqs:
        if r.superseded_by is not None:
            if r.superseded_by not in known:
                out.append(Finding(
                    level="error", code="dangling-superseded-by", path=r.path,
                    message=f"says it was superseded by REQ-{r.superseded_by:04d}, which does not "
                            f"exist. The reader is sent to a dead end, which is worse than no "
                            f"pointer at all."))
            elif r.superseded_by == r.number:
                out.append(Finding(level="error", code="self-superseded", path=r.path,
                                   message="says it was superseded by itself"))
        for target in r.supersedes:
            replaced = next((x for x in reqs if x.number == target), None)
            if replaced is None:
                out.append(Finding(
                    level="error", code="dangling-supersedes", path=r.path,
                    message=f"claims to supersede REQ-{target:04d}, which does not exist"))
            elif replaced.status != SUPERSEDED:
                # the two halves of one decision must agree, or the corpus asserts both that a
                # requirement was replaced and that it is still current
                out.append(Finding(
                    level="error", code="supersede-not-mutual", path=r.path,
                    message=f"claims to supersede REQ-{target:04d}, but that file's status is "
                            f"{replaced.status!r}. Set it to `superseded-by {r.number:04d}`: as it "
                            f"stands the corpus says one requirement is replaced AND current."))

        # THE ROT SIGNAL. An accepted requirement that has been built but records nothing learned
        # is how this repository turns into a wish-list. A warning, deliberately: it is a prompt to
        # write back, not a claim that the requirement is wrong.
        if r.status == ACCEPTED and not r.has_decisions:  # observed entries are exempt: nothing
            # has been executed against a reading of the code that nobody has confirmed yet
            out.append(Finding(
                level="warn", code="no-write-back", path=r.path,
                message="accepted, but records no decisions taken during execution. If work has "
                        "happened against it, what was learned has not reached the document — the "
                        "way this corpus decays into a wish-list nobody trusts."))
    return out
