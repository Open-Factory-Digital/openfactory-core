"""The board must never be read one request per card again.

MEASURED 2026-07-28 against the live 256-card board:

    gh project item-list --limit 800   →  303 GraphQL points   (one request PER CARD)
    hand-written paginated query       →    1 GraphQL point    (one request per 100 cards)

The poller reads this board every three minutes. At 303 points a read that is 6,060 points/hour
against a 5,000/hour installation ceiling — the factory exhausted its own quota every hour, all by
itself, and then its own low-budget guard skipped the ticks. The board went unreadable for the
product role at exactly the moment somebody was talking to it.

Two doors, and only one had been fixed before: the incremental snapshot in `product/board.py` made
Nina's read RARE (the product owner's own correction: "it read once, swept fine, after that it
only goes for the updates"), but the poller's path in `tracker/github_project.py` was never touched
and each read still cost 303. Frequency was half the problem; price was the other half.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Every place a card list is fetched. `item-list` is the CLI subcommand that bills per card.
_COSTLY = "item-list"


def _calls_with_costly_cli() -> list[str]:
    """Functions that shell out to `gh project item-list`, by AST — a comment naming it must not
    count, and a string in a docstring explaining the ban certainly must not."""
    out = []
    for path in Path("openfactory").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                for arg in ast.walk(node):
                    if isinstance(arg, ast.Constant) and arg.value == _COSTLY:
                        out.append(f"{path}:{fn.name}")
                        break
    return out


def test_only_the_documented_fallback_may_use_the_per_card_CLI():
    """One escape hatch, named: a user-owned project the org query cannot address. Everything else
    must go through the paginated query."""
    users = sorted(set(_calls_with_costly_cli()))
    allowed = {"openfactory/adapters/tracker/github_project.py:_board_items_via_cli"}
    assert set(users) <= allowed, (
        f"these read the board one request PER CARD: {sorted(set(users) - allowed)}. "
        f"Use the BoardAdapter seam (build_board(project).columns()) — 303 points → 1."
    )


def test_the_pickup_queue_reads_through_the_cheap_path():
    """`items_in_status` is what the poller calls every three minutes; it is the single hottest
    board read in the system."""
    src = Path("openfactory/adapters/tracker/github_project.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
              and n.name == "items_in_status")
    body = ast.unparse(fn)
    assert "_board_items" in body, "the poller's read left the cheap path"
    assert _COSTLY not in body, "the poller's read bills per card again"


def test_the_product_role_shares_the_same_cheap_reader():
    """Nina's incremental snapshot made her reads rare; this keeps each one cheap. Both halves are
    needed — the incremental fix alone still paid 303 points every six hours per project, and the
    cheap read alone would still hammer the API on every message."""
    src = Path("openfactory/product/board.py").read_text()
    assert "build_board" in src, "the product path forked its own board reader again"
    # by CALL, not by string: the file's own comments explain the ban and must stay legible
    assert "openfactory/product/board.py" not in " ".join(_calls_with_costly_cli()), (
        "the product path bills per card again")


def test_an_unreadable_board_is_still_distinguishable_from_an_empty_one():
    """The cheap read must not lose the distinction that a whole class of bugs turned on: `None`
    for "could not look", `{}` for "genuinely nothing there"."""
    src = Path("openfactory/adapters/tracker/github_project.py").read_text()
    tree = ast.parse(src)
    # the distinction lives in `columns()` — the BoardAdapter contract method
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "columns")
    body = ast.unparse(fn)
    assert "return None" in body, "a failed column read no longer reports itself as unreadable"


def test_pagination_is_bounded_and_says_so_when_it_truncates():
    """A silent cap reads as "that is the whole board" — which is how a queue quietly loses its
    tail. The bound is fine; the silence is not."""
    src = Path("openfactory/adapters/tracker/github_project.py").read_text()
    tree = ast.parse(src)
    # the paging moved into `_board_items_via_graphql` when the read learned to try BOTH owner
    # roots (2026-08-14); the property is about wherever the pages are turned, so both are read
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef)
          and n.name in ("_board_items", "_board_items_via_graphql")]
    assert fn, "the paginated board read is gone entirely"
    body = "\n".join(ast.unparse(n) for n in fn)
    assert "hasNextPage" in body, "the query does not paginate — a big board loses cards"
    assert "log.warning" in body, "hitting the page bound is silent"


# ── the agents themselves ───────────────────────────────────────────────────────────────────────

def test_the_product_role_is_HANDED_the_board_never_fetches_it():
    """The product owner's question: "the agents may need to read the board, no?" — yes,
    constantly. The answer is not to give them the command.

    An agent with a terminal WILL reach for `gh project item-list` when it wants to know what is in
    progress; that is the obvious move, it costs 303 points a call, and nothing bounds how often it
    looks. The platform reads once (1 point) and injects the answer — the same architecture as the
    knowledge layer: deterministic context beforehand beats runtime exploration, and it is what
    makes the token-efficiency claim survive contact with a chatty model."""
    from openfactory.product.role import ProductRole

    class _Agent:
        name = "fake"

    section = "\n".join(ProductRole(_Agent(), board={1: "TO-DO", 2: "Done"})._board_section())
    assert "#1" in section and "TO-DO" in section, "the board is not reaching the role"
    assert "do NOT run any command" in section, "nothing tells the agent to stop fetching it"


def test_a_role_with_NO_board_is_told_so_never_handed_an_empty_one():
    """"I could not see the board" and "the board is empty" send a product owner in opposite
    directions — the third place in this codebase where that distinction had to be made explicit."""
    from openfactory.product.role import ProductRole

    class _Agent:
        name = "fake"

    missing = "\n".join(ProductRole(_Agent(), board=None)._board_section())
    empty = "\n".join(ProductRole(_Agent(), board={})._board_section())
    assert "could not be read" in missing and "do not guess" in missing
    assert "empty" in empty and "could not be read" not in empty


def test_no_agent_guidance_teaches_the_expensive_command():
    """The guidance files are the other door: an instruction saying "check the board with gh
    project item-list" would reintroduce the per-card cost inside every box, where no guard in
    this file can see it.

    SCOPED TO WHAT AN AGENT READS — `openfactory/org_defaults/`. The first version scanned every `.md` in
    the repository and promptly flagged `docs/engineering-lessons.md`, which exists to explain why
    the command is banned. A guard that cannot tell an instruction from an explanation makes the
    documentation of a rule a violation of it."""
    guidance = list(Path("openfactory/org_defaults").rglob("*.md"))
    assert guidance, "the agent guidance directory moved — this guard is scanning nothing"
    offenders = [str(p) for p in guidance if _COSTLY in p.read_text()]
    assert not offenders, f"agent guidance teaches the per-card board read: {offenders}"


# ── the same defect, through the door the fix left open (pilot, 2026-08-14) ─────────────────────

def test_the_cheap_read_serves_a_USER_owned_board_too():
    """MEASURED LIVE on the pilot's own account: 5,000 GraphQL points → 4,688 in five minutes,
    ~300 per tick — the 303-point CLI read, back, three months after it was fixed.

    The cheap query asked for `organization(login:)` only. A user-owned project answers that
    with an ERROR (not a null), which landed in the CLI fallback, so a PERSONAL-account
    deployment bought the hundredfold read every three minutes and exhausted the operator's own
    quota — while the factory's App budget sat untouched. He learned about it from an unrelated
    command failing: *"what limit? I never got any warning."*

    This is the third sighting of the organisation/user asymmetry in one week (board creation,
    board columns, and now the item read), which is why the assertion is about BOTH roots rather
    than about this one bug."""
    import inspect

    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    src = inspect.getsource(GitHubProjectBoard._board_items)
    assert '"organization", "user"' in src.replace("'", '"'), (
        "the cheap read tries only one owner root — the other kind of account falls through to "
        "the per-card CLI path, at 100x the points, every poll")

    page = inspect.getsource(GitHubProjectBoard._board_items_via_graphql)
    assert "{root}(login:$owner)" in page, (
        "the paginated query hardcodes an owner root again")


def test_a_root_that_does_not_match_is_not_yet_a_reason_to_buy_the_costly_read(monkeypatch):
    """The behaviour, not the source: an `organization` miss must try `user` BEFORE the CLI."""
    from openfactory.adapters.tracker import github_project as gp

    tried: list[str] = []

    def fake_gh_json(args, token=None):
        query = next(a for a in args if a.startswith("query="))
        root = "organization" if "organization(login:" in query else "user"
        tried.append(root)
        if root == "organization":
            raise RuntimeError("gh api graphql failed: Could not resolve to an Organization")
        return {"data": {"user": {"projectV2": {"items": {
            "pageInfo": {"hasNextPage": False},
            "nodes": [{"id": "PVTI_1", "content": {"number": 7, "repository":
                                                   {"nameWithOwner": "o/n"}},
                       "fieldValueByName": {"name": "TO-DO"}}]}}}}}

    monkeypatch.setattr(gp, "_gh_json", fake_gh_json)
    monkeypatch.setattr(gp.GitHubProjectBoard, "_board_items_via_cli",
                        lambda self: (_ for _ in ()).throw(
                            AssertionError("bought the 303-point read for a user-owned board")))

    board = gp.GitHubProjectBoard(owner="solo-dev", number="1", token="t")
    items = board._board_items()

    assert tried == ["organization", "user"], tried
    assert items and items[0]["number"] == 7 and items[0]["status"] == "TO-DO"
