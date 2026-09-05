"""The knowledge gate — the cuts that would read it as "no concept, no objection".

ROW 1 IS THE INVERSION ITSELF: a file nothing describes called clear. Every other row is a way
of arriving at the same inversion by a side door.

ROWS 2-6 ARE THE VERDICTS: the exemption ignored (every test file dark, and a gate that is always
dark is switched off); the checker's answer discarded (a moved citation read as holding); a
recorded unknown never blocking; a placeholder in an example file blocking like a real secret; a
file the bundle never saw owed a concept it could not have.

ROWS 7-8 ARE THE STANCE: stale read as green; nothing published read as clear.

ROW 9 IS THE MERGE POLICY letting an enforced dark change merge unattended.

ROWS 10-12 ARE THE MACHINE: the station never runs; a dark change under `enforce` is announced
as ready instead of parked with the question; the body carries no account of the gate.

ROW 13 IS THE CLI'S CHANGE SET dropping untracked files — the reference gate's own warning.
"""

TEST = "tests/test_a_file_nothing_describes_is_the_least_safe_to_change.py"

MUTATIONS = [
    ("a file nothing describes is clear — 'no concept, no objection'",
     "openfactory/knowledge/gate.py",
     '        files.append(FileVerdict(path, NO_CONCEPT, f"nothing describes this {kind or \'file\'}"))',
     '        files.append(FileVerdict(path, CLEAR, f"nothing describes this {kind or \'file\'}"))'),

    ("the coverage table's exemption is ignored, so every test and document is dark",
     "openfactory/knowledge/gate.py",
     "        if kind in excused:\n            files.append(FileVerdict(path, EXEMPT,",
     "        if False:\n            files.append(FileVerdict(path, EXEMPT,"),

    ("the checker's answer is discarded — a moved citation reads as holding",
     "openfactory/knowledge/gate.py",
     "            if broken:\n                files.append(FileVerdict(path, STALE,",
     "            if False:\n                files.append(FileVerdict(path, STALE,"),

    ("a recorded unknown never blocks",
     "openfactory/knowledge/gate.py",
     "        blocking = [g for g in gaps.get(path, ()) if _blocks(g)]",
     "        blocking = []"),

    ("a placeholder in an example file blocks like a real secret",
     "openfactory/knowledge/gate.py",
     '        return (getattr(gap, "severity", "") or "high") == "high"',
     "        return True"),

    ("a file the bundle never saw is owed a concept it could not have",
     "openfactory/knowledge/gate.py",
     "        if inventory is not None and not kind:\n            files.append(FileVerdict(path, NEW_FILE,",
     "        if False:\n            files.append(FileVerdict(path, NEW_FILE,"),

    ("a stale description reads as green",
     "openfactory/knowledge/gate.py",
     "        if STALE in verdicts:\n            return AMBER",
     "        if STALE in verdicts:\n            return GREEN"),

    ("nothing published reads as clear",
     "openfactory/knowledge/gate.py",
     "        return GateReport(tuple(FileVerdict(p, NO_BUNDLE, _NO_BUNDLE_REASON) for p in paths))",
     "        return GateReport(tuple(FileVerdict(p, CLEAR, _NO_BUNDLE_REASON) for p in paths))"),

    ("an enforced dark change merges unattended",
     "openfactory/orchestrator/merge_policy.py",
     '            and result.knowledge_stance in {"amber", "dark"}):',
     "            and False):"),

    ("the station never runs",
     "openfactory/orchestrator/machine.py",
     '        mode = getattr(self.manifest, "okf_gate", "advise")\n        if mode == "off":\n            return',
     '        mode = getattr(self.manifest, "okf_gate", "advise")\n        if True:\n            return'),

    ("a dark change under `enforce` is announced as ready instead of parked with the question",
     "openfactory/orchestrator/machine.py",
     '                if (getattr(self.manifest, "okf_gate", "advise") == "enforce"\n'
     '                        and result.knowledge_stance == "dark"):',
     '                if (getattr(self.manifest, "okf_gate", "advise") == "enforce"\n'
     '                        and False):'),

    ("the pull request carries no account of the gate",
     "openfactory/orchestrator/machine.py",
     "        if result.knowledge_stance:\n            from openfactory.knowledge.gate import render_gate_lines",
     "        if False:\n            from openfactory.knowledge.gate import render_gate_lines"),

    ("the change set drops untracked files — the file it would have blocked is never seen",
     "openfactory/knowledge/gate.py",
     '        out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],',
     '        out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],'),
]
