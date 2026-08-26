"""The cockpit may not assert a vendor it did not resolve.

The product owner's words when the panel told an OpenCode-on-Bedrock project it was running Claude
Code: *"this is a multi-harness project with a token pool — hardcoded things at this stage are not
acceptable."*
That one was fixed by resolving the harness per role. The same class survived one section lower —
`S("CI checks (GitHub)")`, a literal on a list an Azure Pipelines project fills — so the fix was a
value, not a rule, and the next hardcoded name would have arrived the same way.

WHY THE SECTION HEADINGS AND NOT THE WHOLE FILE. The panel legitimately names GitHub in places
where GitHub is genuinely the subject: the budget tooltip renders the vendor's name as the
adapter reported it on `/api/budget` (`"GitHub"` on a deployment whose tracker is one), and
renaming that would make it LESS
true. A guard that failed on those would be turned off within a week — and a guard that is off
guards nothing. `S(...)` is the section-title helper, every heading goes through it, and a heading
is exactly where a vendor name reads as a statement of fact about the client's infrastructure.

An operator debugging a red check under a heading that says GitHub goes looking on github.com. That
is the cost, and it is not cosmetic.
"""

from __future__ import annotations

import pathlib
import re

PANEL = pathlib.Path(__file__).resolve().parents[1] / "openfactory" / "api" / "panel.html"

#: Vendors this platform dispatches to by configuration. Deliberately not "every proper noun":
#: these are the names that, printed as fact, are WRONG for some registered project today.
VENDORS = ("GitHub", "GitLab", "Jira", "Azure", "Bitbucket", "Slack", "Claude", "Codex",
           "OpenCode", "Bedrock", "Anthropic")

#: `${S("…")}` — the section-title helper. The capture is the literal text only; an interpolated
#: `${…}` inside the argument is a RESOLVED value and is exactly what this guard wants to see.
_HEADING = re.compile(r'\bS\(\s*"([^"]*)"')


def _literal_headings() -> list[str]:
    return _HEADING.findall(PANEL.read_text())


def test_the_panel_exists_and_this_guard_can_see_its_headings():
    """A negative guard needs a positive twin: `[]` headings would pass the test below silently.

    Absence reads as compliance. If the helper is renamed or the regex drifts, the vendor check
    below goes green while guarding nothing — which is how three guards in this repository stayed
    green over a live defect.
    """
    headings = _literal_headings()
    assert len(headings) >= 4, (
        f"only found {headings} — the S(...) heading helper moved, so the vendor guard below is "
        f"no longer reading anything"
    )
    assert "platform gates (sandbox)" in headings, (
        "the known heading vanished; re-anchor this guard before trusting it"
    )


def test_no_section_heading_hardcodes_a_provider():
    """A heading states a fact. It may only state one the panel actually resolved."""
    offenders = [
        (heading, vendor)
        for heading in _literal_headings()
        for vendor in VENDORS
        if vendor.lower() in heading.lower()
    ]
    assert not offenders, (
        "these headings name a vendor the panel did not resolve, so they are false for every "
        "project on a different provider: "
        + "; ".join(f"{h!r} says {v}" for h, v in offenders)
        + ". Resolve it from the project (see view.py::_ci_provider) and interpolate it."
    )
