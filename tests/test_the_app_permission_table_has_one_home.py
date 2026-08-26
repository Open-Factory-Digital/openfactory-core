"""The GitHub App permission table lives in EXACTLY one document — and none grants Workflows.

The funnel review (2026-08-09) found THREE divergent copies: the dictated-from-live table in the
onboarding doc, an older one in the cloud walkthrough's §1 (docs/DEPLOYMENT.md then; it travels
with `addons/openfactory-aws` since 2026-08-26) that RECOMMENDED `Workflows RW` — directly
against the platform's own guardrail (CI/CD is human-only; the push refusal on
`.github/workflows/**` is the feature) — and a third in docs/operations.md missing half the rows.
Whichever the reader met first looked authoritative, and the wrong one sat in the only doc that
stated where the Installation ID lives.

Two properties, each a ratchet:

  1. ONE HOME. The row-formatted table appears only in docs/setup/github.md; every other doc
     points there. A second copy is where the next drift starts.
  2. NO DOC GRANTS WORKFLOWS. Its absence from the App is the guardrail that keeps the factory
     out of CI/CD definitions; a doc recommending it un-decides an ADR in a place no reviewer
     of the code would look.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CANONICAL = Path("docs/setup/github.md")

#: The table's signature row — present wherever a COPY of the table is, and in prose nowhere.
#: (Administration became Read and write on 2026-08-13, when the pilot proved createRepository
#: needs it; the fingerprint tracks the CURRENT row, or the guard counts zero homes.)
_TABLE_MARKER = re.compile(r"Administration\W{0,6}Read and write", re.IGNORECASE)

#: A grant of the Workflows permission: the word followed closely by a read-write marker.
_WORKFLOWS_GRANT = re.compile(r"Workflows?\W{0,4}(RW\b|R/W|Read\s*(and|&)\s*write)", re.IGNORECASE)


def _docs() -> list[Path]:
    # the add-on packages' documents too: the cloud walkthrough — where the wrong copy lived —
    # moved under `addons/openfactory-aws/docs/` on 2026-08-26 and must stay in reach
    return (sorted((_ROOT / "docs").rglob("*.md")) + sorted((_ROOT / "addons").rglob("*.md"))
            + [_ROOT / "README.md", _ROOT / ".env.compose.example"])


def test_the_permission_table_has_exactly_one_home():
    homes = [p.relative_to(_ROOT) for p in _docs() if _TABLE_MARKER.search(p.read_text())]
    assert homes == [_CANONICAL], (
        f"the App permission table (or a copy) appears in {[str(h) for h in homes]} — the one "
        f"home is {_CANONICAL}; everywhere else must point there, because a second copy is "
        f"where the next contradiction starts")


def test_no_document_recommends_granting_workflows():
    granted = [str(p.relative_to(_ROOT)) for p in _docs()
               if _WORKFLOWS_GRANT.search(p.read_text())]
    assert granted == [], (
        f"{granted} recommend granting the Workflows permission — its ABSENCE is the guardrail "
        f"that keeps CI/CD human-only (see docs/setup/github.md); a client who needs "
        f"pipeline edits gets policy routing, never this checkbox")
