"""ADR-0041: the measurement the decision rests on cannot decay in silence.

The reverses matter as much as the claim: a table that names a harness nobody can drive inflates
the evidence, and an ADR with no stated way to be wrong is a preference wearing a decision's form.
"""

TEST = "tests/test_the_facts_stay_files_for_every_harness.py"
DOC = "docs/adr/0041-facts-are-files-not-a-protocol.md"
REG = "openfactory/adapters/agent/registry.py"

MUTATIONS = [
    ("a fifth harness joins the registry and the ADR keeps claiming it measured everything", REG,
     '    "opencode": _opencode,\n', '    "opencode": _opencode,\n    "gemini": _opencode,\n'),

    ("…and the reverse: the table measures a harness nobody can select", DOC,
     "| Kimi | `--plan` |", "| Kimi | `--plan` |\n| Aider | reads the repo |"),

    ("a measured harness quietly leaves the table", DOC, "| Codex | `-s read-only` |", ""),

    ("the decision stops saying what would reverse it", DOC, "supersede", "revisit"),

    
]
