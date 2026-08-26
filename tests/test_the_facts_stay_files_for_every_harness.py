"""ADR-0041 rests on a measurement, and a measurement decays in silence.

The decision not to adopt a tool protocol — MCP or otherwise — turns on one fact: **every harness
this platform can drive already reads files read-only**, so a filesystem is the one tool all of
them have. That was checked against each registered harness's read-only invocation and written
into a table in the ADR.

The way that goes wrong is not somebody arguing with it. It is a fifth harness joining
`HARNESSES` — the registry is a one-line change by design — while the document that rests on the
list keeps claiming it measured everything. The ADR then reads as evidence when it is a stale
snapshot, which is worse than having written nothing.

The same shape as `HARNESS_BINARIES`: three hand-written copies of the harness list had already
drifted before that table existed, and a fourth harness joined the registry while staying
invisible to the check that existed to keep it honest.
"""

from __future__ import annotations

from pathlib import Path

from openfactory.adapters.agent.registry import HARNESSES

DOC = (Path(__file__).parent.parent / "docs" / "adr"
       / "0041-facts-are-files-not-a-protocol.md")


def test_the_adr_exists_where_the_index_points():
    assert DOC.exists(), "ADR-0041 is indexed and missing"


def test_every_registered_harness_was_actually_MEASURED():
    """Names the harness, so a reader of the failure knows which row to go and check rather than
    being told the document is stale."""
    text = DOC.read_text()

    unmeasured = [kind for kind in HARNESSES if kind.replace("_", " ") not in text.lower()
                  and kind not in text]

    assert not unmeasured, (
        f"ADR-0041 decides against a tool protocol because EVERY harness reads files, and "
        f"{unmeasured} joined the registry without being measured — go and check how each one "
        f"reads, add it to the table, or supersede the ADR")


def test_and_the_table_does_not_claim_a_harness_this_deployment_cannot_DRIVE():
    """The reverse. A row for a harness nobody can select is a measurement of nothing, and it
    inflates the evidence the decision rests on."""
    named = set()
    for line in DOC.read_text().splitlines():
        if not line.startswith("|"):
            continue
        cell = line.split("|")[1].strip()
        if not cell or set(cell) <= set("-: ") or cell == "harness":   # header and separator
            continue
        named.add(cell.lower().replace(" ", "_"))

    assert named, "the table this decision rests on is not there at all"
    assert named <= {k.lower() for k in HARNESSES}, (
        f"ADR-0041 measures {sorted(named - {k.lower() for k in HARNESSES})}, which nobody can "
        f"select — the evidence is broader than the product")


def test_the_decision_says_what_would_REVERSE_it():
    """An ADR that only argues one way is a position, not a decision. This one is a trade whose
    inputs can change, and the successor needs to know which measurement to redo."""
    text = DOC.read_text().lower()

    assert "supersede" in text and "registry" in text, (
        "nothing says what would make this decision wrong — the next person cannot tell whether "
        "it was reasoned or merely preferred")
