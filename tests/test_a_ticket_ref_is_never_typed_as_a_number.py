"""A ticket ref is the provider's own string, everywhere (C-05, #33).

THE GUARD THE CARD ASKS FOR, and it is deliberately in two halves.

`int` is the wrong type for a ticket ref because three of the four trackers this platform claims
to support number their tickets and one does not:

    GitHub          412        fits an int
    Azure DevOps    1234       fits
    GitLab          27         fits
    Jira            CONT-412   DOES NOT

An `int` here does not fail loudly on Jira — `int("CONT-412")` raises inside whatever loop is
running, and `int(x or 0)` (the shape this codebase actually had, twice) turns every unparseable
ref into 0 and therefore into the SAME ticket. That is #69's collapse: the tech-lead's memory
reported every failure in the deployment as one ticket, silently, for as long as it shipped.

WHY TWO HALVES. A pure name-based negative guard would be the "nothing does X" shape this house
has been bitten by before: absence reads as compliance. Worse, the name that matters most here —
bare `number` — is genuinely overloaded, and the ambiguity is real rather than sloppy:

    REQUIREMENT numbers   REQ-0042   minted by THIS platform, sequential, correctly `int`
    TICKET refs           CONT-412   the tracker's, opaque, must be `str`

`module.align_card(self, number: str, *, requirement: int)` carries both in one signature. So the
negative half below scans only names that can mean nothing else, and the positive half names the
bare-`number` sites that ARE cards and asserts each one individually. Neither half alone would
have caught what the other does.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SDLC = pathlib.Path(__file__).resolve().parents[1] / "openfactory"

#: Parameter and field names that can only ever mean a tracker's ticket. Bare `number` is
#: deliberately NOT here — see the module docstring, and the positive half below, which covers it.
REF_NAMES = frozenset({
    "issue", "issue_number", "issue_ref",
    "ticket", "ticket_number", "ticket_ref",
    "in_favour_of",
})

#: The one place an int ticket number is CORRECT: inside the GitHub adapter, past the port, where
#: the vendor's own shape is the subject. `set_column` converts the ref at the entrance and this
#: private helper matches it against GraphQL's `number`, which really is an integer. Allowlisted by
#: (file, function) rather than by name so a second such site has to be argued for here.
ALLOWED = frozenset({
    ("adapters/tracker/github_project.py", "_item_id"),
    # the same integer, one helper along: the anchor of a rank placement, looked up on the
    # board by GraphQL's `number` without being added (#33, the product owner reorders)
    ("adapters/tracker/github_project.py", "_existing_item_id"),
})


def _int_annotated_refs() -> list[tuple[str, int, str, str]]:
    """`(relative path, line, where, annotation)` for every ref-named thing typed as an int."""
    found: list[tuple[str, int, str, str]] = []
    for path in sorted(SDLC.rglob("*.py")):
        rel = str(path.relative_to(SDLC))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id in REF_NAMES and _mentions_int(node.annotation):
                    found.append((rel, node.lineno, node.target.id,
                                  ast.unparse(node.annotation)))
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                args = node.args
                for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
                    if arg.arg not in REF_NAMES or not arg.annotation:
                        continue
                    if not _mentions_int(arg.annotation):
                        continue
                    if (rel, node.name) in ALLOWED:
                        continue
                    found.append((rel, arg.lineno, f"{node.name}({arg.arg})",
                                  ast.unparse(arg.annotation)))
    return found


def _mentions_int(annotation) -> bool:
    """`int`, `int | None`, `set[int]`, `list[int]` — anywhere in the annotation."""
    return any(isinstance(n, ast.Name) and n.id == "int" for n in ast.walk(annotation))


# ── the negative half: nothing unambiguously a ref is typed as a number ──────────────────────────

def test_no_unambiguous_ticket_ref_is_typed_as_an_integer():
    offenders = _int_annotated_refs()
    assert not offenders, "a ticket ref is typed as a number:\n" + "\n".join(
        f"  {f}:{line}  {where}: {ann}" for f, line, where, ann in offenders)


def test_the_guard_can_actually_SEE_an_offender(tmp_path, monkeypatch):
    """THE POSITIVE TWIN OF THE GUARD ITSELF. A scan that silently matched nothing — a broken
    walk, a typo in the name set, an `rglob` pointed at an empty tree — would pass the test above
    for ever while proving nothing. So the scanner is shown a file it MUST report."""
    offender = tmp_path / "adapters" / "fake.py"
    offender.parent.mkdir(parents=True)
    offender.write_text("def move(issue: int) -> None: ...\n", encoding="utf-8")
    monkeypatch.setattr(__name__ + ".SDLC", tmp_path)

    found = _int_annotated_refs()

    assert [(w, a) for _f, _l, w, a in found] == [("move(issue)", "int")]


def test_the_allowlist_is_not_a_place_things_quietly_accumulate():
    """Every allowlisted site must still EXIST. An entry left behind after a rename is a hole
    nobody opened on purpose — and it would be invisible, since a stale entry excuses nothing and
    reads exactly like a clean scan."""
    for rel, function in ALLOWED:
        path = SDLC / rel
        assert path.exists(), f"the allowlist names {rel}, which is gone"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
        assert function in names, f"the allowlist names {rel}:{function}, which is gone"


# ── the positive half: the overloaded name, site by site ─────────────────────────────────────────

#: Bare-`number` sites that carry a CARD, asserted one at a time because no name-based rule can
#: separate them from the requirement numbers that share the word. Each is a place where a Jira
#: deployment would have crashed or collapsed refs together.
CARD_SITES = [
    ("openfactory.product.module", "ProductModule.close_card", "number"),
    ("openfactory.product.module", "ProductModule.align_card", "number"),
    ("openfactory.product.module", "ProductModule.refine", "number"),
    ("openfactory.product.module", "ProductModule._track_defect", "number"),
    ("openfactory.product.module", "ProductModule._issue_url", "ref"),
    ("openfactory.product.board", "_last_diagnosis", "number"),
    # Not `number`, but the same ambiguity from the other side: `closed` reads as a boolean
    # everywhere else in this codebase, so it cannot go in REF_NAMES — and it carries the ref
    # of the card that was closed. The AST scan found its sibling `_closing_note` and could
    # never have found this one.
    ("openfactory.product.module", "_survivor_note", "closed"),
    ("openfactory.product.module", "_closing_note", "in_favour_of"),
    ("openfactory.product.voice", "close_confirmation", "number"),
    ("openfactory.product.voice", "card_closed", "number"),
    ("openfactory.product.voice", "survivor_unclear", "number"),
    ("openfactory.product.voice", "align_confirmation", "number"),
    ("openfactory.product.voice", "card_aligned", "number"),
    ("openfactory.product.voice", "align_refused", "number"),
    ("openfactory.product.voice", "refine_refused", "number"),
    ("openfactory.product.voice", "criteria_written", "number"),
]


@pytest.mark.parametrize("module,qualname,param", CARD_SITES,
                         ids=[f"{q}.{p}" for _m, q, p in CARD_SITES])
def test_a_bare_number_that_means_a_CARD_is_a_string(module, qualname, param):
    import importlib
    import inspect

    obj = importlib.import_module(module)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    annotation = inspect.signature(obj).parameters[param].annotation

    assert "int" not in str(annotation), (
        f"{qualname}({param}) is annotated {annotation!r} — it carries a tracker's ref")


#: The requirement side of the same word, asserted so the two axes stay legible. If one of these
#: ever becomes a string, somebody converted a REQ number by pattern-matching on the name — which
#: is the mistake this file exists to make hard in both directions.
REQUIREMENT_SITES = [
    ("openfactory.product.module", "ProductModule.accept", "number"),
    ("openfactory.product.module", "ProductModule.drop", "number"),
    ("openfactory.product.module", "ProductModule.break_down", "number"),
    ("openfactory.product.module", "ProductModule.align_card", "requirement"),
    ("openfactory.product.corpus", "Corpus.by_number", "number"),
]


@pytest.mark.parametrize("module,qualname,param", REQUIREMENT_SITES,
                         ids=[f"{q}.{p}" for _m, q, p in REQUIREMENT_SITES])
def test_a_REQUIREMENT_number_stays_an_integer(module, qualname, param):
    import importlib
    import inspect

    obj = importlib.import_module(module)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    annotation = inspect.signature(obj).parameters[param].annotation

    assert "int" in str(annotation), (
        f"{qualname}({param}) is annotated {annotation!r} — a REQ number is minted here, "
        "not read off a tracker")


# ── and the refs survive as data, not only as annotations ───────────────────────────────────────

def test_every_model_that_carries_a_ref_accepts_a_JIRA_one():
    """Annotations are not enforcement. These are the shapes a ref actually travels in, and each
    one is handed `CONT-412` — the ref no `int` field could ever have held."""
    from openfactory.product.board import Parked
    from openfactory.product.followup import Question
    from openfactory.product.needs_action import Verdict
    from openfactory.product.queue import Proposed
    from openfactory.product.role import IssueDraft
    from openfactory.product.triage import Observation, Ticket

    assert Ticket(number="CONT-412", title="t").number == "CONT-412"
    assert Observation(ticket="CONT-412", kind="no-criteria", detail="d").ticket == "CONT-412"
    assert Proposed(ticket="CONT-412", why="w").ticket == "CONT-412"
    assert Verdict(ticket="CONT-412").ticket == "CONT-412"
    assert Parked(number="CONT-412", title="t").number == "CONT-412"
    assert Question(ticket="CONT-412", code="no-criteria", text="?").ticket == "CONT-412"
    assert IssueDraft(title="t", already_on_board="CONT-412").already_on_board == "CONT-412"


def test_a_ref_the_model_receives_as_an_INTEGER_still_arrives_as_a_ref():
    """The other direction, and the one that decides whether this migration holds. A tracker's
    JSON says `"number": 412`, and a model asked for a card number answers `412` — so the coercion
    has to happen at the boundary rather than being wished for. `412 in {"412"}` is False, and
    that miss is silent: a reuse becomes a duplicate, a question reaches nobody."""
    from openfactory.product.queue import Proposed
    from openfactory.product.role import IssueDraft
    from openfactory.product.triage import Observation, Ticket

    assert Ticket(number=412, title="t").number == "412"
    assert Observation(ticket=412, kind="no-criteria", detail="d").ticket == "412"
    assert Proposed(ticket=412, why="w").ticket == "412"
    assert IssueDraft(title="t", already_on_board=412).already_on_board == "412"


def test_the_decoration_is_stripped_so_one_card_is_one_key():
    """`#412` and `412` name the same card and reach the platform from different readers — a chat
    message on one side, a board read on the other. They must land on the same key or every
    lookup between them misses."""
    from openfactory.contracts.refs import canonical_ref
    from openfactory.product.triage import Ticket

    assert canonical_ref("#412") == canonical_ref(" 412 ") == "412"
    assert Ticket(number="#CONT-412", title="t").number == "CONT-412"
