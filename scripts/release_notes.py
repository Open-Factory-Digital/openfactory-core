#!/usr/bin/env python3
"""A release's notes, assembled from the line each pull request carries (#517).

    python3 scripts/release_notes.py check [--labels JSON] < <git diff --name-status>
    python3 scripts/release_notes.py preview <x.y.z>
    python3 scripts/release_notes.py assemble <x.y.z> [--date YYYY-MM-DD]
    python3 scripts/release_notes.py page <tag>

Run from the root of a checkout, like `scripts/collect-release-assets.sh`: it reads `changes/`,
`CHANGELOG.md` and `pyproject.toml` there.

WHY THE NOTES ARE NOT DRAFTED AT THE CUT ANY MORE. Until 0.5.0 they were written by hand from the
milestone's merged pull requests, once, by whoever cut the release, and they lived only on the
GitHub release page: not in the tree, not greppable, never reviewed beside the change they
describe. Drafting them was also the one step of the process an agent could get subtly wrong,
because it is the one step that is prose rather than a command. So the line is written by the
pull request, as a FRAGMENT, and reviewed with its code; the release only assembles.

A FRAGMENT is a file `changes/<ref>.<type>.md`:

  <ref>   the issue the pull request closes, or the pull request itself when it closes none; a
          security fix uses its advisory's id (`GHSA-xxxx-xxxx-xxxx`)
  <type>  the group of the notes a reader looks in, one of `TYPES` below
  text    the line, in Markdown, as somebody installing the release should read it, WITHOUT its
          number: the assembly adds `(#<ref>)` from the file name, so it cannot be wrong

ONE SENTENCE PER LINE, AND THAT IS A RULE, NOT A STYLE. The notes are published on the release
page, which renders a newline inside a paragraph as a line break (`scripts/release-page-body.sh`
says so for the install block, #531). A fragment wrapped at 100 columns would publish as broken
lines, so `check` refuses one: a new line is a `- ` sub-item, a blank line, or a code fence.

WHAT EACH COMMAND IS FOR (docs/RELEASING.md, "The release notes"):

  check     CI, on every pull request (`.github/workflows/release-note.yml`): the pull request
            adds or edits a fragment, or carries the label `no-release-note`; every fragment in
            the tree is well formed; and a package that declares a FINAL version has that
            version's notes in CHANGELOG.md, with no fragment left over in the pull request
            that declares it
  preview   before the cut: the notes the fragments make now, as `assemble` would write them;
            nothing is written
  assemble  the final's version pull request: the version's section goes to the top of
            CHANGELOG.md, the fragments it used are removed, and the notes the release page will
            carry are printed
  page      the notes part of a release's page, for `scripts/release-page-body.sh`: a final's
            section of CHANGELOG.md, or a candidate's fragments as they stand. It never fails the
            run: by the time the page is written the images are published under the tag, and a
            failed release job burns the version (docs/RELEASING.md, "When a release goes wrong")

THE STANDARD LIBRARY ONLY, AND NO NETWORK: CI runs this on a bare runner's `python3`, and the
suite runs it offline (`tests/test_a_release_is_noted_by_its_pull_requests.py`).
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

#: The groups of a release's notes, in the order its page shows them: the groups the hand-written
#: notes of 0.5.0 used, as somebody installing a release looks for them. A file's `<type>` is the
#: first column, the page's heading the second. NOT SPLIT BY AREA as 0.5.0's were: with a release
#: a week, a version carries a handful of pull requests, and six groups are enough to scan.
TYPES: tuple[tuple[str, str], ...] = (
    ("highlight", "Highlights"),
    ("behaviour", "New behaviour"),
    ("fix", "Fixes"),
    ("security", "Security"),
    ("upgrade", "Upgrade notes"),
    ("limitation", "Known limitations"),
)

#: The label that exempts a pull request which changes nothing a reader of the notes would notice:
#: documents only, tests only, and the release's own version and notes pull requests. A LABEL, not
#: a rule about paths, so the exemption is a decision the reviewer sees and can question.
LABEL = "no-release-note"

FRAGMENTS = Path("changes")
CHANGELOG = Path("CHANGELOG.md")
PYPROJECT = Path("pyproject.toml")

_NAME = re.compile(r"^(?P<ref>[0-9]+|GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})"
                   r"\.(?P<type>[a-z]+)\.md$")
_FINAL = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_EXAMPLE = "changes/<issue>.<type>.md"


def _types() -> str:
    return ", ".join(name for name, _ in TYPES)


@dataclass(frozen=True)
class Fragment:
    path: Path
    ref: str
    type: str
    text: str

    @property
    def reference(self) -> str:
        return f"#{self.ref}" if self.ref.isdigit() else self.ref

    @property
    def order(self) -> tuple[int, int, str]:
        # NUMERICALLY: as text, #10 would come before #9
        return (0, int(self.ref), "") if self.ref.isdigit() else (1, 0, self.ref)


def _wrapped_line(text: str) -> int | None:
    """The number of the first line that continues the sentence above it, or None.

    A line may follow a non-blank line only as a `- ` sub-item or inside a code fence; anything
    else continues a paragraph, and a release page renders that newline as a break."""
    previous, fenced = "", False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced, previous = not fenced, stripped
            continue
        if (not fenced and stripped and previous and not previous.startswith("```")
                and not stripped.startswith("- ")):
            return number
        previous = stripped
    return None


def read_fragments() -> tuple[list[Fragment], list[str]]:
    """Every fragment in `changes/`, and a sentence for each file there that is not one."""
    fragments: list[Fragment] = []
    problems: list[str] = []
    if not FRAGMENTS.is_dir():
        return fragments, problems
    for path in sorted(FRAGMENTS.iterdir()):
        if path.name.startswith("."):
            continue                                    # a desktop's own files, never the tree's
        shown = path.as_posix()
        named = _NAME.match(path.name)
        if not named or not path.is_file():
            problems.append(f"{shown}: a fragment is named `{_EXAMPLE}`, such as "
                            f"`changes/531.fix.md`, and this name is not one")
            continue
        if named["type"] not in dict(TYPES):
            problems.append(f"{shown}: `{named['type']}` is not a type of release note; the "
                            f"types are {_types()}")
            continue
        text = path.read_text(encoding="utf-8").strip()
        text = text[2:] if text.startswith("- ") else text     # the item's dash is the assembly's
        if not text:
            problems.append(f"{shown} is empty: it holds the line the release notes will read")
            continue
        if (number := _wrapped_line(text)) is not None:
            problems.append(f"{shown}, line {number}: a sentence goes on one line, because the "
                            f"release page shows a line break inside a paragraph as a break; a "
                            f"new line is a `- ` sub-item, a blank line or a code fence")
            continue
        fragments.append(Fragment(path, named["ref"], named["type"], text))
    return fragments, problems


def _item(fragment: Fragment) -> str:
    """One fragment as one item of the notes: its first line is the item, closed by its reference
    (before a final full stop or colon), and every line after it is indented beneath it."""
    first, *rest = fragment.text.splitlines()
    first = first.rstrip()
    tag = f" ({fragment.reference})"
    first = first[:-1] + tag + first[-1] if first.endswith((".", ":")) else first + tag
    return "\n".join([f"- {first}", *(f"  {line}" if line.strip() else "" for line in rest)])


def render(fragments: list[Fragment]) -> str:
    """The notes: one `###` group per type that has a fragment, in `TYPES` order."""
    groups = []
    for name, heading in TYPES:
        mine = sorted((f for f in fragments if f.type == name), key=lambda f: f.order)
        if mine:
            groups.append(f"### {heading}\n\n" + "\n".join(_item(f) for f in mine))
    return "\n\n".join(groups) + "\n"


def section_of(changelog: str, version: str) -> str | None:
    """The body of `## <version> (…)` in CHANGELOG.md, without its heading, or None."""
    lines = changelog.splitlines()
    heading = re.compile(rf"^## {re.escape(version)}(?: |$)")
    for start, line in enumerate(lines):
        if heading.match(line):
            end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
                       len(lines))
            return "\n".join(lines[start + 1:end]).strip() + "\n"
    return None


def _declared_version() -> str | None:
    if not PYPROJECT.is_file():
        return None
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8")).get("project", {}).get("version")


def check(labels: list[str], changed: str) -> int:
    fragments, problems = read_fragments()

    # ADDED OR EDITED, as `git diff --name-status --no-renames` spells them. A pull request that
    # only removes a fragment carries no line of its own.
    touched = [path for status, _, path in (line.partition("\t") for line in changed.splitlines())
               if status[:1] in ("A", "M")]
    carried = [path for path in touched if path.startswith(f"{FRAGMENTS.as_posix()}/")
               and _NAME.match(Path(path).name)]

    # A FINAL VERSION CARRIES ITS NOTES. The pull request that declares it is where they are
    # assembled, and where a forgotten assembly is cheapest to see: here, before the tag. A
    # fragment left beside it is only a fault in THAT pull request: after the final, a backport
    # for the next patch brings its fragment to a branch that still declares the final.
    declared = _declared_version()
    if declared and _FINAL.match(declared):
        written = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.is_file() else ""
        if section_of(written, declared) is None:
            problems.append(f"the package declares {declared}, a final release, and CHANGELOG.md "
                            f"has no section for it: run `python3 scripts/release_notes.py "
                            f"assemble {declared} --date <the release date>` on this branch")
        elif fragments and PYPROJECT.as_posix() in touched:
            problems.append(f"this pull request declares {declared}, a final release, and "
                            f"{', '.join(f.path.as_posix() for f in fragments)} were not "
                            f"assembled into its notes")

    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1

    if carried:
        print(f"This pull request carries its release note: {', '.join(carried)}.")
        return 0
    if LABEL in labels:
        print(f"This pull request carries the label `{LABEL}`: it changes nothing a reader of "
              f"the release notes would notice.")
        return 0
    print(f"This pull request carries no release note. Add `{_EXAMPLE}` with the line somebody "
          f"installing the release should read (types: {_types()}; CONTRIBUTING.md has an "
          f"example). A pull request that changes only documents or tests gets the label "
          f"`{LABEL}` instead.", file=sys.stderr)
    return 1


def _usable_fragments() -> list[Fragment] | None:
    fragments, problems = read_fragments()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return None
    return fragments


def preview(version: str) -> int:
    fragments = _usable_fragments()
    if fragments is None:
        return 1
    if not fragments:
        print(f"No release-note fragment in {FRAGMENTS.as_posix()}/: {version} has no notes yet.")
        return 0
    print(f"## {version} (unreleased)\n\n{render(fragments)}", end="")
    return 0


def assemble(version: str, date: str) -> int:
    if not _FINAL.match(version):
        print(f"`{version}` is not a final version (x.y.z): the notes are assembled for the final "
              f"release, and a candidate's page shows the fragments as they stand",
              file=sys.stderr)
        return 2
    if not _DATE.match(date):
        print(f"`{date}` is not a date (YYYY-MM-DD)", file=sys.stderr)
        return 2
    if not CHANGELOG.is_file():
        print(f"there is no {CHANGELOG} here: run this from the root of a checkout",
              file=sys.stderr)
        return 1
    written = CHANGELOG.read_text(encoding="utf-8")
    if section_of(written, version) is not None:
        print(f"CHANGELOG.md already has the notes of {version}: nothing was written",
              file=sys.stderr)
        return 1
    fragments = _usable_fragments()
    if fragments is None:
        return 1
    if not fragments:
        print(f"there is no fragment in {FRAGMENTS.as_posix()}/, so {version} would have no "
              f"notes: a change a reader should hear about is added as a fragment first",
              file=sys.stderr)
        return 1

    notes = render(fragments)
    section = f"## {version} ({date})\n\n{notes}\n"
    # NEWEST FIRST: above the first version already there, under the file's own introduction
    lines = written.splitlines(keepends=True)
    at = next((i for i, line in enumerate(lines) if line.startswith("## ")), None)
    if at is None:
        updated = written.rstrip("\n") + "\n\n" + section
    else:
        updated = "".join(lines[:at]) + section + "".join(lines[at:])
    CHANGELOG.write_text(updated.rstrip("\n") + "\n", encoding="utf-8")
    for fragment in fragments:
        fragment.path.unlink()

    print(f"CHANGELOG.md: the notes of {version}, from {len(fragments)} fragments, which were "
          f"removed: {', '.join(f.path.as_posix() for f in fragments)}", file=sys.stderr)
    print(notes, end="")
    return 0


def page(tag: str) -> int:
    if not re.match(r"^v[0-9]", tag):
        print(f"`{tag}` is not a version tag (v<x.y.z>…)", file=sys.stderr)
        return 2
    version = tag[1:].split("-", 1)[0]

    if "-" not in tag:
        written = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.is_file() else ""
        notes = section_of(written, version)
        if notes is None:
            print(f"::warning::CHANGELOG.md has no section for {version}", file=sys.stderr)
            print(f"The notes of {version} are not in CHANGELOG.md: the release manager adds them "
                  f"to this page by hand.")
        else:
            print(notes, end="")
        return 0

    # A CANDIDATE: the fragments as they stand, so whoever tests it reads what changed. One that
    # is malformed is left out and named in the run, never a reason to fail it (see `page` above).
    fragments, problems = read_fragments()
    for problem in problems:
        print(f"::warning::{problem}", file=sys.stderr)
    if not fragments:
        print(f"No release-note fragment yet: the notes of {version} are assembled at its final "
              f"release.")
        return 0
    print(f"**The notes of {version} so far**, from the pull requests this candidate carries. "
          f"The final release's page carries them as they are published.\n")
    print(render(fragments), end="")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="release_notes.py", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    checking = commands.add_parser("check", help="a fragment, or the label that exempts")
    checking.add_argument("--labels", default="[]", help="the pull request's labels, a JSON list")
    commands.add_parser("preview", help="the notes the fragments make now; writes nothing") \
        .add_argument("version")
    assembling = commands.add_parser("assemble", help="write a final version's notes")
    assembling.add_argument("version")
    assembling.add_argument("--date", default=datetime.date.today().isoformat())
    commands.add_parser("page", help="the notes part of a release's page").add_argument("tag")
    args = parser.parse_args(argv)

    if args.command == "check":
        try:
            labels = json.loads(args.labels or "[]")
        except ValueError:
            print(f"--labels takes the pull request's labels as a JSON list, such as "
                  f"'[\"{LABEL}\"]', and was given {args.labels!r}", file=sys.stderr)
            return 2
        return check([str(label) for label in labels or []], sys.stdin.read())
    if args.command == "preview":
        return preview(args.version)
    if args.command == "assemble":
        return assemble(args.version, args.date)
    return page(args.tag)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
