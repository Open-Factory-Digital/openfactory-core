"""The module map's declared blindness, and the nine ways it goes quiet again.

THE DEFECT. The bundle has surveyed its own coverage since coverage existed — `files_read`,
`files_unread`, `unread_extensions`, `unreadable_paths`, with a deliberate three-way split between
never-measured, measured-and-clean, and blind. Checksummed into the derived key, published to the
knowledge branch, and never rendered: `render_module_map` emitted its header and its module entries
and stopped. Measured on this repository, 2026-08-29: 688 files read, 111 walked and not read, and
not one word about the 111 in 6,164 characters of injected map — inside a function whose docstring
argues that an omission must be visible rather than assumed away.

ROWS 6 AND 7 ARE THE ONES WORTH READING. The coverage sentence rides in the HEADER rather than in a
section of its own, and that placement is the fix rather than a detail: everything else in this
rendering is sheddable. Detail levels drop fields; the last resort drops whole modules. A coverage
note that lived anywhere else would disappear exactly when the map got thin — which is when an
agent most needs telling that it is partial.

ROW 3 IS THE ONE A REVIEWER WILL WANT TO ARGUE WITH. A renderer that warned on every map would pass
every other guard here and would be strictly worse than saying nothing, because a warning that is
always present carries no information. The measured-and-clean sentence is what keeps the blind one
meaning something.
"""

TEST = "tests/test_the_map_says_what_it_does_not_cover.py"

MUTATIONS = [
    # ── the defect, restored ────────────────────────────────────────────────────────────────────
    ("the coverage sentence never reaches the header — the defect exactly as it shipped: the map "
     "declares its blindness to a YAML file nobody reads and says nothing to the agent",
     "openfactory/knowledge/render.py",
     "    header = _HEADER.format(commit=commit) + _coverage(bundle.manifest)",
     "    header = _HEADER.format(commit=commit)"),

    ("the counts are dropped, so an agent is told WHICH kinds are unread and never how much of "
     "the repository that is",
     "openfactory/knowledge/render.py",
     ('        out.append(f"COVERAGE: built from {read} source file(s); {missed} more were walked '
      'and "\n'
      '                   f"NOT read.")'),
     '        out.append("COVERAGE:")'),

    ("the unread kinds are dropped, so the counts say 111 files are missing and nothing says what "
     "they are — an agent cannot tell a stack it should ask about from generated noise",
     "openfactory/knowledge/render.py",
     "    if unread:\n        shown = unread[:_MAX_UNREAD_SUFFIXES]",
     "    if False:\n        shown = unread[:_MAX_UNREAD_SUFFIXES]"),

    ("a directory the walk could not OPEN goes unmentioned — the blindness the counts cannot "
     "express, so a repository the process cannot read surveys identically to one read whole",
     "openfactory/knowledge/render.py",
     "    if unreadable:\n        shown_paths = unreadable[:_MAX_UNREADABLE_PATHS]",
     "    if False:\n        shown_paths = unreadable[:_MAX_UNREADABLE_PATHS]"),

    # ── the three states collapse into two ──────────────────────────────────────────────────────
    ("a bundle that NEVER MEASURED its coverage renders as one that measured and found nothing — "
     "an old bundle silently acquires a completeness it never had",
     "openfactory/knowledge/render.py",
     ('        return ("COVERAGE: this bundle predates coverage measurement, so how much of the "\n'
      '                "repository the map below describes is UNKNOWN. An area missing from it is '
      'not "\n'
      '                "evidence that the area does not exist.\\n")'),
     '        return ""'),

    ("a measured-and-clean bundle says nothing, so the coverage note appears only when there is "
     "bad news — and its ABSENCE becomes the claim, which is the defect wearing a hat",
     "openfactory/knowledge/render.py",
     '        out.append("Every file walked was read and every directory opened.")',
     "        pass"),

    # ── it must survive both degradations ───────────────────────────────────────────────────────
    ("the coverage sentence is appended AFTER the modules instead of riding in the header, so it "
     "is the first thing dropped when the map overflows — gone exactly when the map is thinnest "
     "and the agent most needs to know it is partial",
     "openfactory/knowledge/render.py",
     "    kept: list[str] = [header]",
     "    kept: list[str] = [_HEADER.format(commit=commit)]"),

    ("degrading detail also drops the coverage sentence, for the same reason and one path earlier",
     "openfactory/knowledge/render.py",
     "    for detail in (3, 2, 1, 0):\n        lines = [header]",
     "    for detail in (3, 2, 1, 0):\n        lines = [_HEADER.format(commit=commit)]"),

    # ── bounds, and the blank nobody would report ───────────────────────────────────────────────
    ("the cap on unread kinds stops saying it is a cap, so a repository with twenty unread stacks "
     "reports eight and reads as complete about the rest — the same defect, one level down",
     "openfactory/knowledge/render.py",
     "        rest = len(unread) - len(shown)\n",
     "        rest = 0\n"),

    ("a file with no extension renders as a blank before its count (` ×6`), which a reader takes "
     "for a bug in the platform rather than a fact about their repository",
     "openfactory/knowledge/render.py",
     "f\"{u.suffix or '(no extension)'} ×{u.files}\"",
     'f"{u.suffix} ×{u.files}"'),

    ("an empty module map starts injecting a header about nothing, so every caller's "
     "`if knowledge_map:` becomes true for a repository the generator could not map at all",
     "openfactory/knowledge/render.py",
     "    modules = bundle.module_map.modules\n    if not modules:\n        return \"\"",
     "    modules = bundle.module_map.modules\n    if False:\n        return \"\""),
]
