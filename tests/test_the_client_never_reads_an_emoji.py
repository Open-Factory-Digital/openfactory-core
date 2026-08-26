"""What the client reads carries no pictographs. Their board, their tickets, their channel.

The product owner: *"muito cuidado com uso amador de emoji, isso é muito built by AI."*

He is right about the tell, and measuring it found something better than a style problem. The
platform marked every ticket it was working with the label `"🤖 sdlc-working"` — and **one vendor
refuses it outright**. Recorded live, one character at a time, in `adapters/tracker/azure_devops`:

    🤖 sdlc-working  ·  🤖sdlc-working  ·  🤖
        -> TF401407: The tag name is invalid. It contains invalid characters
    ✓ done  ·  → next
        -> accepted

Azure DevOps rejects anything outside the BMP; Jira separately rejects the space. So the emoji
bought a label that reads like a toy on a client's own board AND cost a bespoke sanitiser in two
adapters. Removing it is the cheaper engineering, not only the better manners.

TYPOGRAPHIC MARKS ARE NOT EMOJI AND ARE NOT POLICED HERE. `✓`, `✗`, `→`, `•`, `⚠` are ordinary
type, they render in every terminal and every board, and they are what professional tools have
always used. What this file forbids is the astral plane — the pictographs that render as coloured
cartoons.

TWO EXEMPTIONS, BOTH DELIBERATE, BOTH NARROW.

  * **A legacy matcher.** `_DIAGNOSIS_MARKERS` still contains the old string because it READS
    what earlier versions of this platform WROTE. Dropping it would blind the diagnosis classifier
    to every comment already posted — a regression that fails nothing and quietly stops working.
    (The working label's former spellings were once exempted here for the same reason; they left
    with the rest of the old name on 2026-08-25.)
  * **The Slack bot's conversational replies.** A chat persona in a chat product is a different
    register from a comment on somebody's ticket, and it is an opt-in add-on. Named, not swept.
"""

from __future__ import annotations

import ast
import pathlib
import re

import add_ons
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The astral plane — coloured pictographs. Deliberately NOT `✓ ✗ → • ⚠`, which are type.
PICTOGRAPH = re.compile(r"[\U0001F300-\U0001FAFF]")

#: Modules whose strings reach a client's ticket, board, channel or panel.
CLIENT_FACING = (
    "openfactory/orchestrator/machine.py",
    "openfactory/orchestrator/promotion.py",
    "openfactory/runtime/temporal/activities.py",
    "openfactory/runtime/temporal/workflow.py",
    "openfactory/contracts/decision.py",
    "openfactory/adapters/notify/slack.py",
    "openfactory/adapters/notify/panel.py",
    "openfactory/adapters/notify/telegram.py",
    "openfactory/product/board.py",
)

#: `module -> the names whose value is allowed to contain one, and why`. Each reads history.
LEGACY_READERS = {
    "openfactory/product/board.py": {"_DIAGNOSIS_MARKERS"},
}


def _strings_in(path: str):
    """Every string LITERAL in the module, with the assignment it belongs to (or None).

    The AST, not the text: a comment explaining why an emoji was removed must never fail the
    guard that removed it — that is a rule which teaches people to delete the explanation.
    """
    tree = ast.parse(add_ons.source(path).read_text())
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    for sub in ast.walk(node.value):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                            owner[id(sub)] = target.id
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, owner.get(id(node)), node.value


@pytest.mark.parametrize("path", CLIENT_FACING)
def test_no_pictograph_reaches_the_client(path):
    allowed = LEGACY_READERS.get(path, set())
    bad = [f"{path}:{line} in {name or 'a literal'} — {value[:60]!r}"
           for line, name, value in _strings_in(path)
           if PICTOGRAPH.search(value) and name not in allowed]
    assert not bad, (
        "these put a pictograph into something a client reads:\n  " + "\n  ".join(bad)
    )


def test_the_guard_can_SEE_one_it_is_given(tmp_path):
    """The positive twin. A scanner that stopped matching would report a clean codebase."""
    probe = tmp_path / "m.py"
    probe.write_text('GREETING = "🤖 hello"\nMARK = "✓ done"\n')
    tree = ast.parse(probe.read_text())
    found = [n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and PICTOGRAPH.search(n.value)]
    assert found == ["🤖 hello"], f"the scanner saw {found}"


def test_typographic_marks_are_NOT_treated_as_emoji():
    """`✓ ✗ → • ⚠` render everywhere and are what professional tools have always used. A guard
    that flagged them would force the output to be worse, and would then be deleted."""
    for mark in ("✓ done", "✗ failed", "→ next", "• info", "⚠ careful"):
        assert not PICTOGRAPH.search(mark), f"{mark!r} is being policed as a pictograph"


# ── the board label, and the migration it needs ─────────────────────────────────────────────────

def test_the_working_label_is_acceptable_to_every_tracker():
    """It was `"🤖 sdlc-working"`, which Azure DevOps refuses outright (TF401407) and Jira refuses
    the space of. A label the platform cannot actually set on two of its three trackers is not a
    marker, it is a per-vendor workaround."""
    from openfactory.orchestrator.machine import _BOT_WORKING_LABEL

    assert not PICTOGRAPH.search(_BOT_WORKING_LABEL), _BOT_WORKING_LABEL
    assert " " not in _BOT_WORKING_LABEL, (
        f"{_BOT_WORKING_LABEL!r} contains a space, which Jira labels cannot"
    )
    assert _BOT_WORKING_LABEL.isascii(), _BOT_WORKING_LABEL


def test_the_diagnosis_classifier_still_reads_the_OLD_comments():
    """The platform stopped writing `### 🔧 Tech-lead triage` and every diagnosis already on a
    client's ticket still opens with it. Dropping the marker fails nothing and quietly blinds the
    classifier to the entire history of every board that has been running."""
    from openfactory.product.board import _DIAGNOSIS_MARKERS

    assert "🔧" in _DIAGNOSIS_MARKERS, "the classifier can no longer find comments it wrote"
    assert any("tech-lead" in m for m in _DIAGNOSIS_MARKERS), (
        "…and it cannot find the ones it writes NOW either — the new heading is "
        "`### Tech-lead triage`"
    )
