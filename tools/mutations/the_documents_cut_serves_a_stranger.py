"""The documents cut, proven by breaking it — every claim the 2026-08-26 cut added has a red twin.

TWO KINDS OF CUT, DELIBERATELY MIXED. The first kind edits the DOCUMENTS: a row whose cell sends a
reader nowhere, an index that names a document the export drops, a citation put back where it
rotted. The second kind edits the GUARDS themselves, and those are the ones written hostile — not
"restore the old text" but "keep every vocabulary word and invert the condition", because that is
the cut a reviewer lands. Each of the second kind is aimed at the verifier that must see it.

The guards under test:
  · `tests/test_the_public_documents_serve_a_stranger.py` — this package's own;
  · `tests/test_the_public_cut_is_written_down.py` — the table and the link walk it already held.
"""

TEST = "tests/test_the_public_documents_serve_a_stranger.py"

SERVE = "tests/test_the_public_documents_serve_a_stranger.py"
CUT = "tests/test_the_public_cut_is_written_down.py"
STATUS = "docs/STATUS.md"
INDEX = "docs/core/README.md"
VENDOR = "tests/test_the_docs_name_no_vendor_as_the_core.py"
DRIFT = "tests/test_the_docs_do_not_drift.py"
FRONT_DOOR = "tests/test_the_documentation_has_one_front_door.py"

MUTATIONS = [
    # ── rescue before you exclude: the row has to name a home a reader can open ───────────────
    ("a row keeps every word of its sentence and stops naming a path — the prose still reads "
     "like a home, and there is nothing to open", STATUS,
     "| `docs/core/05-open-questions.md` | the answers are in `LICENSE`, `NOTICE`, "
     "`CONTRIBUTING.md` and `docs/STATUS.md` |",
     "| `docs/core/05-open-questions.md` | the answers are in the licence, the notice, the "
     "contributing page and this page |", SERVE),

    ("a row sends the reader to another document that leaves with it", STATUS,
     "| `docs/core/01-reality-check.md` | a dated audit of this tree; `docs/STATUS.md` answers "
     "the same question and a guard keeps it current |",
     "| `docs/core/01-reality-check.md` | a dated audit of this tree; "
     "`docs/core/05-open-questions.md` answers the same question |", SERVE),

    ("HOSTILE: the home check keeps the word `excluded` in its own name and stops asking it — a "
     "home that leaves with the document then counts as a home", SERVE,
     "        reachable = [p for p in named if exists(p) and not _is_excluded(p, cells)]",
     "        reachable = [p for p in named if exists(p) or _is_excluded(p, cells)]", SERVE),

    ("HOSTILE: the home check judges no row at all, because `.md` becomes `.m`", SERVE,
     '        if not path.endswith(".md"):',
     '        if not path.endswith(".mdx"):', SERVE),

    # ── the design directory: six file rows, never a directory row ────────────────────────────
    ("the directory is excluded as a directory, which takes the extensibility document with it",
     STATUS,
     "| `docs/core/01-reality-check.md` |",
     "| `docs/core/` | the design rationale |\n| `docs/core/01-reality-check.md` |", SERVE),

    ("the index itself is excluded, so the public tree ships three numbered files and no front "
     "page", STATUS,
     "| `docs/core/01-reality-check.md` |",
     "| `docs/core/README.md` | the dossier's index |\n| `docs/core/01-reality-check.md` |",
     SERVE),

    ("every design document leaves — the directory ships empty and the six file rows are gone",
     STATUS,
     "| `docs/core/01-reality-check.md` | a dated audit",
     "| `docs/core/00-vision.md` | the vision |\n| `docs/core/02-boundary.md` | the boundary |\n"
     "| `docs/core/07-extensibility.md` | the extension model |\n"
     "| `docs/core/README.md` | the index |\n| `docs/core/01-reality-check.md` | a dated audit",
     SERVE),

    ("the index stops naming the extensibility document, so nothing in the public tree reaches it",
     INDEX,
     "| [Extensibility](07-extensibility.md) |",
     "| Extensibility |", SERVE),

    ("the index names a document the export drops", INDEX,
     "## The bar these three hold themselves to",
     "See also [the licensing record](04-business-and-licensing.md).\n\n"
     "## The bar these three hold themselves to", SERVE),

    # ── the pointers no other scanner reads ───────────────────────────────────────────────────
    ("the citation comes back in NOTICE, which travels into every fork under Apache §4(d)",
     "NOTICE",
     "That split is deliberate and it is the whole protection strategy.",
     "That split is deliberate and it is the whole protection strategy (docs/core/04 §5).",
     SERVE),

    ("…and in the build metadata, where no document scanner looks", "pyproject.toml",
     "# APACHE-2.0, and the choice has a reason rather than a preference behind it.",
     "# APACHE-2.0, and the reasoning is in docs/core/04 §5 rather than a preference.", SERVE),

    ("…and in a `.gitignore` comment, on the line that explains the blast radius", ".gitignore",
     "# is published as `openfactory-core`. A client's internal addresses reaching a public "
     "repository",
     "# is published from docs/core/03, Phase 3. A client's internal addresses reaching a public "
     "repository", SERVE),

    ("…and in the prose of the page every reader is told to read first", STATUS,
     "*installation* belongs to one org. One deployment serves one organisation, and that is now",
     "*installation* belongs to one org. This is the model docs/core/04 sells, and it is now",
     SERVE),

    ("HOSTILE: the `.gitignore` exemption keeps its `rules` and stops asking WHICH one — one "
     "ignore rule under docs/ then exempts every dead citation in the file", SERVE,
     "            if doc in rules:",
     '            if any(rule.startswith("docs") for rule in rules):', SERVE),

    ("HOSTILE: the STATUS exemption keeps the word `rows` and strips the whole page instead of "
     "the table — the prose citations then have nowhere to be found", SERVE,
     '        rows = re.compile(r"^\\| `[^`]+` \\| .+? \\|$", re.M)\n        return rows.sub("", text)',
     '        rows = re.compile(r"[\\s\\S]*", re.M)\n        return rows.sub("", text)', SERVE),

    ("HOSTILE: an add-on package prefix becomes the empty string, so every citation `resolves` "
     "inside a package and the sweep reports nothing", SERVE,
     '    return [f"{add_ons.public_tree_signal()}{d.name}/" for d in sorted(signal.iterdir()) if d.is_dir()]',
     '    return ["", *(f"{add_ons.public_tree_signal()}{d.name}/" for d in sorted(signal.iterdir()))]',
     SERVE),

    # ── a guard never reads a path the export does not have ───────────────────────────────────
    ("a guard reads an excluded document again, the way two did on 2026-08-26", VENDOR,
     '    for rel, must_say in (("docs/ONBOARDING.md", ("add-on", "if you later add a cloud", "none of them a cloud")),\n'
     '                          ("docs/architecture.md", ("add-on",))):',
     '    for rel, must_say in (("docs/ONBOARDING.md", ("add-on", "if you later add a cloud", "none of them a cloud")),\n'
     '                          ("docs/site-guide.md", ("add-on",)),\n'
     '                          ("docs/architecture.md", ("add-on",))):', SERVE),

    ("HOSTILE: the read scan keeps its `routed` variable and treats every read as routed", SERVE,
     "        if routed:\n            continue",
     "        if routed or True:\n            continue", SERVE),

    ("HOSTILE: the read scan keeps walking, but only the receiver's own node — `(ROOT / 'x.md')"
     "` is then invisible and only a bare literal is seen", SERVE,
     "        for n in ast.walk(receiver):",
     "        for n in [receiver]:", SERVE),

    # ── a git ref says whose history it is ────────────────────────────────────────────────────
    ("the status line keeps the words `the source tree this page is written in` and drops the "
     "binding — attribution as prose, unresolvable for a reader of the export", STATUS,
     "Status as of **2026-08-26**, main at `c1ed6f4` of `openfactory`, the source tree this page is\nwritten in",
     "Status as of **2026-08-26**, main at `c1ed6f4`, in the source tree this page is\nwritten in",
     SERVE),

    ("the version tag loses its binding, and a tag rots exactly like a sha", STATUS,
     "`v1.1.0` tag of `openfactory`.", "`v1.1.0` tag.", SERVE),

    ("the binding names a repository nothing publishes — the shape is right and the answer is "
     "invented", STATUS,
     "main at `c1ed6f4` of `openfactory`,", "main at `c1ed6f4` of `the-old-tree`,", SERVE),

    ("HOSTILE: the published names become every word on the page, so any binding satisfies the "
     "check", SERVE,
     '    names = {name, f"{name}-core"}\n    for cell in _cells().values():\n'
     '        names |= set(re.findall(r"openfactory-[a-z]+", cell))\n    return names',
     '    names = {name, f"{name}-core"}\n'
     '    names |= set(re.findall(r"[\\w.-]+", STATUS.read_text()))\n    return names', SERVE),

    ("HOSTILE: the binding may sit in any sentence on the page rather than the ref's own — one "
     "attributed line then attributes every bare ref under it", SERVE,
     '        sentence = text[start:end if end > 0 else len(text)]',
     '        sentence = text',
     SERVE),

    # ── excluded is not deleted ───────────────────────────────────────────────────────────────
    ("the table excludes a document this tree does not have — a stale line is not a list", STATUS,
     "| `docs/site-guide.md` | website copy source;",
     "| `docs/core/08-the-plan.md` | it was deleted |\n| `docs/site-guide.md` | website copy source;",
     SERVE),

    # ── the count guards cover every shipped document, not four names ─────────────────────────
    ("a shipped document outside the old four names the wrong number of decision records",
     "docs/glossary.md",
     "# Glossary — the canonical vocabulary",
     "# Glossary — the canonical vocabulary\n\nGrounded in 39 decision records.", DRIFT),

    ("…and one grows its own test count beside the page that is supposed to be its only home",
     "docs/pipeline-stations.md",
     "- [`architecture.md`](architecture.md) — how the panel, the durable engine and the boxes fit",
     "- 4,971 tests cover these stations\n"
     "- [`architecture.md`](architecture.md) — how the panel, the durable engine and the boxes fit",
     DRIFT),

    ("HOSTILE: the derived set keeps its name and collapses back to the two pages at the root",
     DRIFT,
     '    return ["README.md", "CONTRIBUTING.md", *sorted(docs)]',
     '    return ["README.md", "CONTRIBUTING.md", *sorted(docs)[:0]]', DRIFT),

    ("HOSTILE: the history exclusion is misspelled, so the decision records are held to today's "
     "numbers and every count guard starts reporting the past", DRIFT,
     '            if p and not p.startswith("docs/adr/") and p != "docs/STATUS.md" and ships(p)]',
     '            if p and not p.startswith("docs/adrs/") and p != "docs/STATUS.md" and ships(p)]',
     DRIFT),

    ("HOSTILE: the cut's exclusion is inverted while keeping the name `ships` — the documents "
     "that leave come back into the set and the ones that ship drop out", DRIFT,
     "        return not any(rel == p or (p.endswith('/') and rel.startswith(p)) for p in excluded)"
     .replace("'", '"'),
     "        return any(rel == p or (p.endswith('/') and rel.startswith(p)) for p in excluded)"
     .replace("'", '"'), DRIFT),

    # ── the moved runbook is not linked as though it were still here ──────────────────────────
    ("a reference page links the incident file at its old path, which moved with the package",
     "docs/configuration.md",
     "the `openfactory-aws` package's own `docs/runbook.md` (incident response on that deployment) and",
     "[`runbook.md`](runbook.md) (incident response) and", FRONT_DOOR),

    # ── and the link walk still sees what it was written for ──────────────────────────────────
    ("a document that stays links to one that leaves", INDEX,
     "[Vision](00-vision.md)", "[Vision](01-reality-check.md)", CUT),
]
