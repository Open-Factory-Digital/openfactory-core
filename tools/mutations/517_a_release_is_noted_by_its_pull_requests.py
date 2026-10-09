"""A release's notes are assembled from a line each pull request carries (#517), proven by
breaking it.

Run:  .venv/bin/python tools/mutate.py tools/mutations/517_a_release_is_noted_by_its_pull_requests.py

The notes were drafted by hand at the cut and lived only on the release page. Now each pull request
carries a fragment, `changes/<issue>.<type>.md`, and `scripts/release_notes.py` checks, assembles
and pages them. The claims, each put back the way it could break:

  the check     a pull request without a fragment or the label fails; only that label exempts;
                removing a fragment is not carrying one; a misnamed, unknown-typed or wrapped
                fragment is refused; a final version is declared only with its notes, and only
                its own pull request is refused for a fragment left beside it
  the assembly  the version goes on top, its fragments are removed, references close each line
                before its full stop, in numeric order, under the groups in the order a reader
                looks
  the page      a final's reads CHANGELOG.md; the release page carries the notes; nothing about
                the notes ever fails the release run
  the CI        it runs again when a label changes, reads the event's labels, fetches the base and
                diffs the pull request against it
  the docs      they give only commands the script has, teach its types in its order, and name
                its label
"""

TEST = "tests/test_a_release_is_noted_by_its_pull_requests.py"
SCRIPT = "scripts/release_notes.py"
PAGE = "scripts/release-page-body.sh"
WORKFLOW = ".github/workflows/release-note.yml"
RELEASING = "docs/RELEASING.md"
CONTRIBUTING = "CONTRIBUTING.md"

MUTATIONS = [
    # ── the check ───────────────────────────────────────────────────────────────────────────
    ("THE DEFECT: a pull request with no line and no label passes", SCRIPT,
     '          f"`{LABEL}` instead.", file=sys.stderr)\n    return 1\n',
     '          f"`{LABEL}` instead.", file=sys.stderr)\n    return 0\n'),

    ("any label exempts a pull request", SCRIPT,
     "    if LABEL in labels:\n",
     "    if labels:\n"),

    ("a pull request that only removes a fragment is read as carrying one", SCRIPT,
     'if status[:1] in ("A", "M")]',
     'if status[:1] in ("A", "M", "D")]'),

    ("a fragment of a type the notes have no group for is accepted", SCRIPT,
     '        if named["type"] not in dict(TYPES):\n',
     "        if False:\n"),

    ("a file in changes/ that is not a fragment is skipped instead of refused", SCRIPT,
     "        if not named or not path.is_file():\n            problems.append(",
     "        if not named or not path.is_file():\n            continue\n            problems.append("),

    ("a sentence wrapped over two lines is accepted, and publishes as broken lines", SCRIPT,
     "        if (number := _wrapped_line(text)) is not None:\n",
     "        if (number := _wrapped_line(text)) is not None and False:\n"),

    ("a final version is declared without its notes", SCRIPT,
     "        if section_of(written, declared) is None:\n",
     "        if False:\n"),

    ("the final's version pull request leaves a fragment out of its notes", SCRIPT,
     "        elif fragments and PYPROJECT.as_posix() in touched:\n",
     "        elif False:\n"),

    ("after the final, every backport is refused for the fragment it brings", SCRIPT,
     "        elif fragments and PYPROJECT.as_posix() in touched:\n",
     "        elif fragments:\n"),

    # ── the assembly ────────────────────────────────────────────────────────────────────────
    ("the assembly leaves the fragments it used behind, to be listed again", SCRIPT,
     "    for fragment in fragments:\n        fragment.path.unlink()\n",
     "    for fragment in fragments:\n        pass\n"),

    ("the assembly writes the new version under the older ones", SCRIPT,
     '        updated = "".join(lines[:at]) + section + "".join(lines[at:])\n',
     '        updated = written.rstrip("\\n") + "\\n\\n" + section\n'),

    ("the references sort as text, #10 before #9", SCRIPT,
     '        return (0, int(self.ref), "") if self.ref.isdigit()',
     '        return (0, 0, self.ref) if self.ref.isdigit()'),

    ("a line is published without its reference", SCRIPT,
     '    tag = f" ({fragment.reference})"\n',
     '    tag = ""\n'),

    ("the reference lands after the full stop", SCRIPT,
     '    first = first[:-1] + tag + first[-1] if first.endswith((".", ":")) else first + tag\n',
     "    first = first + tag\n"),

    ("a fragment written with its own dash publishes as an empty item", SCRIPT,
     '        text = text[2:] if text.startswith("- ") else text',
     "        text = text"),

    ("sub-items are not indented under their line", SCRIPT,
     '*(f"  {line}" if line.strip() else "" for line in rest)',
     "*(line for line in rest)"),

    ("the groups come in another order than the one a reader looks in", SCRIPT,
     '    ("highlight", "Highlights"),\n    ("behaviour", "New behaviour"),\n',
     '    ("behaviour", "New behaviour"),\n    ("highlight", "Highlights"),\n'),

    # ── the page ────────────────────────────────────────────────────────────────────────────
    ("a final's page reads the fragments instead of its section of CHANGELOG.md", SCRIPT,
     '    if "-" not in tag:\n        written = CHANGELOG',
     "    if False:\n        written = CHANGELOG"),

    ("a final whose notes are missing fails the run that published its images", SCRIPT,
     "            print(notes, end=\"\")\n        return 0\n",
     "            print(notes, end=\"\")\n        return 1\n"),

    ("the release page stops carrying the notes", PAGE,
     'python3 "$(dirname "$0")/release_notes.py" page "$tag" \\\n',
     "true \\\n"),

    ("a page whose notes cannot be written fails the release run", PAGE,
     '    || echo "The notes of this release could not be written here: the release manager adds '
     'them to this page by hand."\n',
     ""),

    # ── the CI ──────────────────────────────────────────────────────────────────────────────
    ("the label is added and the check is not run again", WORKFLOW,
     "    types: [opened, synchronize, reopened, labeled, unlabeled]\n",
     "    types: [opened, synchronize, reopened]\n"),

    ("the check reads no pull request's labels", WORKFLOW,
     "          LABELS: ${{ toJSON(github.event.pull_request.labels.*.name) }}\n",
     '          LABELS: "[]"\n'),

    ("the base is not fetched, so there is nothing to diff against", WORKFLOW,
     "          fetch-depth: 2\n",
     "          fetch-depth: 1\n"),

    ("the step diffs the merge against the pull request instead of the base", WORKFLOW,
     "git diff --name-status --no-renames HEAD^1 HEAD",
     "git diff --name-status --no-renames HEAD^2 HEAD"),

    # ── the documents ───────────────────────────────────────────────────────────────────────
    ("the process names a command the script does not have", RELEASING,
     "| `python3 scripts/release_notes.py preview x.y.z` |",
     "| `python3 scripts/release_notes.py draft x.y.z` |"),

    ("the one-time setup forgets the label the check reads", RELEASING,
     "  `no-release-note`, which exempts a pull request from the release-note check.\n",
     "  `release-note-exempt`, which exempts a pull request from the release-note check.\n"),

    ("CONTRIBUTING.md teaches a type the check refuses", CONTRIBUTING,
     "`behaviour` (new or changed behaviour)",
     "`feature` (new or changed behaviour)"),
]
