"""#33 slice 4 (the product owner's facts are files): every property of the pack is a cut.

The board rendered whole, a failed read as a gap and not an empty file, the loops filtered to the
role's own and to the open ones, the register keeping answered decisions, an unreadable ledger as
a gap, the previous pack removed, no `.git/` conjured, the mount deciding from the manifest on
disk, the section only when mounted, the section in the prompt, the measurement line — and the
client's document.
"""

TEST = "tests/test_the_product_owners_facts_are_files.py"
FACTS = "openfactory/product/facts.py"
MODULE = "openfactory/product/module.py"
ROLE = "openfactory/product/role.py"
DOC = "docs/reference/product-role.md"

MUTATIONS = [
    # ── rendering ──
    ("a failed board read renders as an empty board", FACTS,
     "    if cards is None:\n        return \"\"\n    if not cards:\n",
     "    if cards is None:\n        cards = []\n    if not cards:\n"),

    ("the file drops the state a card closed with", FACTS,
     '            tag = f" [{state}{\':\' + reason if reason else \'\'}]" if state else ""\n',
     '            tag = ""\n'),

    ("the loops file lists the tech-lead's loops too", FACTS,
     "    open_loops = sorted(waiting(rows, owner=OWNER), key=lambda x: x.ts)\n",
     "    open_loops = sorted(waiting(rows), key=lambda x: x.ts)\n"),

    ("the loops file lists answered decisions as waiting", FACTS,
     "    open_loops = sorted(waiting(rows, owner=OWNER), key=lambda x: x.ts)\n",
     "    open_loops = sorted((x for x in fold(rows) if x.owner == OWNER), key=lambda x: x.ts)\n"),

    ("the register forgets the answered ones", FACTS,
     "    decisions = sorted((x for x in fold(rows) if x.kind == DECISION and x.owner == OWNER),\n",
     "    decisions = sorted((x for x in waiting(rows) if x.kind == DECISION and x.owner == OWNER),\n"),

    ("an unreadable ledger is an empty loops file", FACTS,
     '        gaps.append(f"the open-loop ledger could not be read ({exc}) — what is waiting on a "\n'
     '                    f"person and the decisions register are unknown, not empty")\n'
     "        return files, gaps\n",
     "        rows = []\n"),

    # ── writing ──
    ("the previous pack is kept and packs accumulate", FACTS,
     "        for stale in root.glob(f\"{_PREFIX}*\"):\n            if stale.is_dir():\n"
     "                shutil.rmtree(stale, ignore_errors=True)\n",
     "        for stale in root.glob(f\"{_PREFIX}*\"):\n            if False:\n"
     "                shutil.rmtree(stale, ignore_errors=True)\n"),

    ("a `.git/` is conjured into a composed root", FACTS,
     '        if (root / ".git").is_dir():\n',
     "        if True:\n"),

    ("the manifest forgets the gaps", FACTS,
     "        (into / \"README.md\").write_text(manifest(into.name, written, list(gaps)),\n",
     "        (into / \"README.md\").write_text(manifest(into.name, written, []),\n"),

    # ── the mount and the role ──
    ("the door is announced whether or not the manifest is on disk", MODULE,
     '    if facts and root and (Path(facts) / "README.md").is_file():\n',
     "    if facts and root:\n"),

    ("documentation-only loses the pack", MODULE,
     '            return _with_facts({"docs": ".", "code": ""}, facts, root)\n',
     '            return {"docs": ".", "code": ""}\n'),

    ("the section speaks without a mount", ROLE,
     '        where = self.mounted.get("facts") or ""\n        if not where:\n            return []\n',
     '        where = self.mounted.get("facts") or ".openfactory-facts-"\n        if not where:\n            return []\n'),

    ("the section never reaches the prompt", ROLE,
     "        parts += self._bundle_section()\n        parts += self._facts_section()\n",
     "        parts += self._bundle_section()\n"),

    ("the measurement line is not written", MODULE,
     '        log.info("OPENFACTORY_PRODUCT_FACTS project=%s files=%d gaps=%d written=%s",\n'
     '                 name, len(files), len(gaps), "yes" if into else "no")\n',
     "        pass\n"),

    ("the module writes no pack at all", MODULE,
     "        self._facts_dir = self._write_facts()\n",
     "        self._facts_dir = None\n"),

    # ── the document ──
    ("the client's document forgets the pack", DOC,
     "its own **facts pack**", "its own workspace"),
]
