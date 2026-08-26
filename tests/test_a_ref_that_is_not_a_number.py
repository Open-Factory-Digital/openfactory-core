"""A ticket ref that is not a number must not crash the product role (C-04).

`contracts/ticket.py` documents a ref as opaque — `"#142"` or `"PROJ-31"` — and `tracker/jira.py`
honours it. `product/` does not: five sites call `int(str(ref).lstrip("#"))`, and
`int("CONT-412")` is a `ValueError`.

THIS IS A DIFFERENT CLASS FROM THE REST OF THE REF WORK, which is why it is its own card. The
`lstrip("#")` sites produce a wrong string and a 404 — bad, visible, recoverable. These *raise*,
in the middle of the product role's write path, after the issues have already been filed. The
delivery lands and the client is never told, which is the failure ADR-0025 exists to prevent.

WHAT THIS CARD DOES NOT DO. It does not make `product/` provider-neutral: `number: int` is that
module's domain type across ~50 signatures, and `BoardAdapter` itself is typed with an integer
issue id. That is C-05 and it needs the persisted-shape migration recorded on issue #33. What this
does is make a non-numeric ref DEGRADE — the work is reported, the courtesy that needs a number is
skipped and says so — instead of taking the whole pass down with it.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.refs import ref_number

# ── the primitive ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref,expected", [
    ("#412", 412),
    ("412", 412),
    (412, 412),
    ("  #412 ", 412),
])
def test_a_numeric_ref_still_yields_its_number(ref, expected):
    """Every existing caller must keep working: GitHub refs really are numeric, and the board API
    genuinely takes an integer."""
    assert ref_number(ref) == expected


@pytest.mark.parametrize("ref", ["CONT-412", "PROJ-1", "abc", "", None, "#", "12a", "1.5"])
def test_a_ref_that_is_not_a_number_returns_None_rather_than_raising(ref):
    """None, not 0. Zero is a valid-looking issue number and would send a comment to whatever
    ticket happens to be #0 — or silently match nothing, which is worse because it looks fine."""
    assert ref_number(ref) is None


def test_it_never_raises_for_anything():
    """Called from inside the product role's write path, after the work has already been filed.
    Anything that escapes here abandons a delivery the client was about to be told about."""
    for weird in [object(), [], {}, 3.7, b"412", float("nan")]:
        ref_number(weird)


def test_zero_is_refused_because_no_tracker_issues_it():
    """`_as_ticket_number` used to return 0 on failure, so a Jira ref became issue #0 — a value
    that reads as a number all the way down."""
    assert ref_number("0") is None
    assert ref_number(0) is None


def test_a_negative_is_refused():
    assert ref_number("-5") is None


# ── the five sites that used to crash ───────────────────────────────────────────────────────────

def test_the_product_module_has_no_bare_int_of_a_ref():
    """The reachability guard. The primitive can be perfect and unused — which is this
    repository's signature defect, recorded nine times."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for rel in ("openfactory/product/module.py", "openfactory/product/release.py", "openfactory/product/followup.py",
                "openfactory/product/channel.py"):
        path = root / rel
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "int"):
                continue
            src = ast.unparse(node)
            if any(w in src for w in ("ref", "ticket", "issue")) and "lstrip" in src:
                offenders.append(f"{rel}:{node.lineno} — {src}")
    assert not offenders, (
        "these still call int() on a provider's ref, which raises for a Jira one:\n  "
        + "\n  ".join(offenders)
    )


def test_a_delivery_note_survives_a_non_numeric_ref():
    """`module.py:1271` sorted `{int(str(r.ref).lstrip("#")) for r in results}` to tell the client
    what landed. With a Jira ref the whole notification raised — the issues were filed and the
    client was never told, which is precisely what ADR-0025 exists to prevent."""
    from openfactory.contracts.refs import ref_numbers

    class _R:
        def __init__(self, ref):
            self.ok, self.ref = True, ref

    mixed = [_R("#12"), _R("CONT-412"), _R("#3")]
    assert ref_numbers(r.ref for r in mixed) == [3, 12]


def test_ref_numbers_drops_what_it_cannot_read_rather_than_the_whole_list():
    from openfactory.contracts.refs import ref_numbers

    assert ref_numbers(["CONT-1", "CONT-2"]) == []
    assert ref_numbers([]) == []


def test_ref_numbers_deduplicates_and_sorts():
    """The original was a sorted set, and callers render it as "#3, #12". Losing either property
    would change what a client reads."""
    from openfactory.contracts.refs import ref_numbers

    assert ref_numbers(["#12", "12", "#3"]) == [3, 12]


# ── the whole point ─────────────────────────────────────────────────────────────────────────────

def test_a_jira_shaped_result_set_does_not_take_the_pass_down():
    """The integration-level statement of the card: whatever the product role does with a set of
    refs, a non-numeric one must not raise out of it."""
    from openfactory.contracts.refs import ref_number, ref_numbers

    refs = ["CONT-412", "#7", "PROJ-9", "1234", None, ""]
    assert ref_numbers(refs) == [7, 1234]
    assert [ref_number(r) for r in refs] == [None, 7, None, 1234, None, None]
