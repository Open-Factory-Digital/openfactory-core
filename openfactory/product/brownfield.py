"""Arriving at a project that already exists — the first pass, and what it may and may not claim.

This is the common case, not the exception: the documentation repository is empty and there is a
year of code. The obvious move is to read the code and write requirements from it. That move is
wrong, and the reason is worth stating before any of the machinery below.

**A requirement says what MUST be true. Code says what IS true — including bugs, accidents, and
behaviour nobody ever chose.** Turning the second into the first freezes bugs into promises: once a
behaviour is an accepted requirement the factory DEFENDS it, so the fix that should follow reads as
a violation of what the product committed to. And the provenance would be a lie — "asked by: the
code" is not a person.

So a reverse-engineering pass produces OBSERVATIONS, never commitments. Every candidate lands with
status `observed`, carrying its evidence and where that evidence is. A human turning one into
`accepted` is the only event that converts behaviour into a promise.

THREE TIERS OF EVIDENCE, because they are not equally trustworthy:

    asked    a person asked for it — an issue, a PR, a comment with an author and a date. Real
             provenance, and the strongest thing a brownfield pass can find. It is also the tier
             most often missed, because it means reading the tracker's history rather than the code.
    tested   a test asserts it. Somebody made it a promise on purpose; that is what a test IS.
    code     the code does it and nothing asserts it. The tier most likely to be an accident, and
             the one a reader should treat with the most suspicion.

THE FIRST PASS IS ONE MILESTONE, NOT FORTY PULL REQUESTS. A team asked to review forty requirement
PRs reviews none of them, and the exercise dies in its first week. Everything from one pass lands as
a single reviewable change: an inventory, the candidates, and the questions.

AND IT DECLARES ITS OWN COVERAGE. A large codebase cannot be surveyed in one go, so the inventory
records which areas were covered and which were not. A document that implies completeness it does
not have is worse than a short one — it grants confidence exactly where none is warranted.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from openfactory.product.authoring import slugify
from openfactory.product.corpus import OBSERVED

ASKED, TESTED, CODE = "asked", "tested", "code"
_TIERS = (ASKED, TESTED, CODE)

_TIER_NOTE = {
    ASKED: "a person asked for this — the strongest evidence a first pass can find",
    TESTED: "a test asserts this, so somebody made it a promise on purpose",
    CODE: "the code does this and nothing asserts it — treat as possibly accidental",
}


class Observation(BaseModel):
    """One thing the system appears to do, and why we think so."""

    title: str = ""
    behaviour: str = ""
    #: `asked` · `tested` · `code`
    evidence: str = CODE
    #: file paths, test names, issue numbers — whatever supports the claim, verbatim
    citations: list[str] = Field(default_factory=list)
    area: str = ""

    def normalised(self) -> Observation:
        """An unknown tier degrades to `code`, the weakest — never upward. A mislabelled reading
        that claimed `asked` would borrow provenance it does not have."""
        if self.evidence not in _TIERS:
            return self.model_copy(update={"evidence": CODE})
        return self


class Baseline(BaseModel):
    """The result of one pass: what was found, what was skipped, and what could not be answered."""

    observations: list[Observation] = Field(default_factory=list)
    #: areas this pass actually looked at
    covered: list[str] = Field(default_factory=list)
    #: areas deliberately left for a later pass — stated, so nobody reads silence as completeness
    not_covered: list[str] = Field(default_factory=list)
    #: what the code could not answer: contradictions, unreadable intent, dead flags. The most
    #: valuable output of a first pass, because it is the part only a human can resolve.
    questions: list[str] = Field(default_factory=list)
    commit: str = ""

    def by_tier(self, tier: str) -> list[Observation]:
        return [o for o in self.observations if o.normalised().evidence == tier]


def render_inventory(baseline: Baseline, *, product: str, date: str = "") -> str:
    """The dated snapshot. A DERIVED artefact: regenerable, anchored to a commit, and explicitly
    not a set of promises."""
    lines = [
        f"# Baseline inventory — {product}",
        "",
        f"- **Generated:** {date or 'unrecorded'}",
        f"- **From commit:** `{baseline.commit or 'unrecorded'}`",
        "",
        "This is a **reading of the code as it is today**, not a set of requirements. Nothing here "
        "is a promise the product has made: an entry becomes a commitment only when a human "
        "confirms it and its candidate requirement moves from `observed` to `accepted`.",
        "",
        "## Coverage",
        "",
    ]
    lines += [f"- covered: `{a}`" for a in baseline.covered] or ["- covered: (nothing)"]
    if baseline.not_covered:
        lines += [f"- **not** covered: `{a}`" for a in baseline.not_covered]
    else:
        lines.append("- **not** covered: nothing was declared out of this pass — treat that as "
                     "unverified rather than as full coverage")
    lines += ["", "## What the system appears to do", ""]

    for tier in _TIERS:
        found = baseline.by_tier(tier)
        if not found:
            continue
        lines += [f"### Evidence: {tier}", "", f"_{_TIER_NOTE[tier]}_", ""]
        for obs in found:
            lines.append(f"- **{obs.title}** — {obs.behaviour}")
            for c in obs.citations:
                lines.append(f"  - `{c}`")
        lines.append("")

    if baseline.questions:
        lines += ["## What the code could not answer", "",
                  "These need a person. They are the reason this pass is a conversation and not a "
                  "report.", ""]
        lines += [f"- {q}" for q in baseline.questions]
        lines.append("")
    return "\n".join(lines)


def render_candidate(obs: Observation, *, number: int, commit: str = "", date: str = "") -> str:
    """One observation as a requirement-shaped file with status `observed`.

    Requirement-shaped so that confirming it is editing one line rather than rewriting a document,
    and so it lands in `requirements/` where it will be promoted IN PLACE — moving the file later
    would cost exactly the git history that justifies the repository existing."""
    obs = obs.normalised()
    lines = [
        f"# REQ-{number:04d} — {obs.title}",
        "",
        f"- **Status:** {OBSERVED}",
        "- **Asked by:** nobody — reverse-engineered from the code",
        f"- **Date:** {date or 'unrecorded'}",
        "- **Supersedes:** —",
        f"- **Evidence:** {obs.evidence} — {_TIER_NOTE[obs.evidence]}",
        f"- **Observed at commit:** `{commit or 'unrecorded'}`",
        "",
        "> **This is not a commitment.** It describes what the system does today. Until somebody "
        "confirms it is intended — by changing the status to `accepted` — the factory must not "
        "defend it, because a bug read off the code looks exactly like a feature.",
        "",
        "## Why",
        "",
        "Unknown: no request for this was found. If you know why it exists, replace this section — "
        "and if it turns out nobody wanted it, say so and delete the file.",
        "",
        "## What must be true",
        "",
        f"- [ ] {obs.behaviour or obs.title}",
        "",
        "## Out of scope",
        "",
        "- (not determined by a reverse-engineering pass)",
        "",
        "## Affects",
        "",
    ]
    lines += [f"- `{c}`" for c in obs.citations] or ["- (not stated)"]
    lines += [
        "",
        "## Decisions taken during execution",
        "",
        "| date | decision | where it came from |",
        "|---|---|---|",
        "",
    ]
    return "\n".join(lines)


def candidate_path(obs: Observation, *, number: int, requirements_dir: str) -> str:
    return f"{requirements_dir.rstrip('/')}/{number:04d}-{slugify(obs.title)}.md"


def milestone_files(
    baseline: Baseline, *, product: str, first_number: int,
    requirements_dir: str = "requirements", baseline_dir: str = "baseline", date: str = "",
) -> dict[str, str]:
    """Every file the first pass writes, as `path → contents`. One dict, so the milestone is one
    commit and one pull request — a team asked to review forty of them reviews none."""
    files: dict[str, str] = {
        f"{baseline_dir.rstrip('/')}/inventory.md":
            render_inventory(baseline, product=product, date=date),
    }
    for offset, obs in enumerate(baseline.observations):
        number = first_number + offset
        files[candidate_path(obs, number=number, requirements_dir=requirements_dir)] = (
            render_candidate(obs, number=number, commit=baseline.commit, date=date))
    return files


# The first-contact message lives in `voice.py`: it is the one thing here a CLIENT reads, and it
# was written in the team's language — "it all arrives as a single pull request" is a sentence that
# teaches a non-technical owner this tool is not for them.
