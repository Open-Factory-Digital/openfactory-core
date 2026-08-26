"""The panel's Board button was a hand-welded github.com URL (#162, `api/app.py:1769`).

    board = f"https://github.com/{_owner_kind(owner)}/{owner}/projects/{num}"

GitHub Projects v2 vocabulary — `board_owner`, `board_number`, and an `/orgs/` vs `/users/` root
GitHub has and the others do not — spelled out on the REFERENCE SURFACE of a product sold as
vendor-agnostic. An Azure or Jira deployment's operator clicked it and landed on a github.com page
that does not exist.

The panel had already paid for this class once at the same line: the `/orgs/` root shipped for a
user-owned board and 404ed on somebody's own account (2026-08-14). The fix then was to ask GitHub
which kind of owner it was — correct, and it left a `gh api` subprocess call about one vendor
inside the panel.

A board URL is provider knowledge, like `clone_url` and `ticket_url`: the host, the path shape,
and the asymmetries. `BoardAdapter.url()` is where it lives now, and the panel asks.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from openfactory.adapters.board.base import BoardAdapter

#: `openfactory/` — the package, NOT `openfactory/adapters`. `base.py` is two directories
#: down (`adapters/board/base.py`), and getting this wrong made the walk below skip every
#: file it listed: `.parent.parent` was `adapters/`, which the walk then excludes entirely.
_PACKAGE = Path(inspect.getfile(BoardAdapter)).parent.parent.parent

# ── 1. every registered board can say where it lives ────────────────────────────────────────────

def test_the_contract_declares_it():
    assert hasattr(BoardAdapter, "url")
    doc = inspect.getdoc(BoardAdapter.url) or ""
    assert '""' in doc, "the empty answer is the whole contract here and the docstring omits it"


def test_every_registered_board_implements_it():
    """Walked from the factory, not from a list of vendors: a fourth board added without this
    fails the suite rather than showing an operator a button that goes nowhere."""
    import importlib
    import re as _re

    from openfactory.adapters.board import factory

    src = inspect.getsource(factory)
    # THE PROTOCOL ITSELF IS NOT AN IMPLEMENTATION, and excluding it is what lets the safety net
    # below mean something: `factory.py` imports `BoardAdapter` for its type hint, so `classes` was
    # never empty and the assert could not fire however the regex rotted.
    classes = {m.group(2) for m in _re.finditer(
        r"from (openfactory\.adapters\.[\w.]+) import (\w*Board\w*)", src)} - {"BoardAdapter"}
    assert len(classes) >= 3, (
        f"the walk found {sorted(classes)} — this deployment builds three boards, so the regex "
        f"has rotted and this guard is measuring nothing")

    missing = []
    for name in sorted(classes):
        module = next(m.group(1) for m in _re.finditer(
            r"from (openfactory\.adapters\.[\w.]+) import (\w*Board\w*)", src) if m.group(2) == name)
        cls = getattr(importlib.import_module(module), name)
        if not callable(getattr(cls, "url", None)):
            missing.append(name)

    assert "BoardAdapter" not in classes, (
        "the Protocol is being counted as an implementation — it satisfies every check by "
        "construction, so the safety net above can never fire")
    assert not missing, f"these boards cannot say where they live: {missing}"


def test_the_conformance_gate_NAMES_the_method_a_board_is_missing():
    """An integrator's board written before today fails `isinstance` the moment the port grows a
    method. "does not satisfy BoardAdapter" is not a repair; the missing name is."""
    from openfactory.conformance.adapters import check_board

    class _Older:
        """Everything the port had yesterday, and not `url`."""

        def columns(self): return {}
        def column_names(self): return []
        def pickup_column(self): return "TO-DO"
        def items_in_status(self, status): return []
        def add_item(self, *, issue_url): return None
        def set_column(self, *, issue, issue_url, name): return True
        def set_status(self, *, issue, issue_url, state, needs_person=None): return True

    said = " ".join(f.detail for f in check_board(_Older()))

    assert "url" in said, f"the gate refuses a board without saying what it lacks: {said}"


# ── 2. each vendor's own shape ──────────────────────────────────────────────────────────────────

def test_a_github_ORG_board_links_to_orgs(monkeypatch):
    from openfactory.adapters.tracker import github_project as gp

    monkeypatch.setitem(gp._OWNER_KIND, "acme", "orgs")
    board = gp.GitHubProjectBoard("acme", "7")

    assert board.url() == "https://github.com/orgs/acme/projects/7"


def test_and_a_USER_board_links_to_users(monkeypatch):
    """The 404 this line already shipped once."""
    from openfactory.adapters.tracker import github_project as gp

    monkeypatch.setitem(gp._OWNER_KIND, "solo-dev", "users")
    board = gp.GitHubProjectBoard("solo-dev", "3")

    assert board.url() == "https://github.com/users/solo-dev/projects/3"


def test_a_github_ENTERPRISE_board_links_to_their_own_host(monkeypatch):
    """`clone_url` and `ticket_url` both honour `GH_HOST`; a board link that did not would send an
    Enterprise operator to a public github.com page about a board they do not have there."""
    from openfactory.adapters.tracker import github_project as gp

    monkeypatch.setenv("GH_HOST", "github.acme.com")
    monkeypatch.setitem(gp._OWNER_KIND, "acme", "orgs")

    assert gp.GitHubProjectBoard("acme", "7").url().startswith("https://github.acme.com/orgs/")


def test_an_AZURE_board_links_to_dev_azure_com():
    from openfactory.adapters.board.azure_devops import AzureBoardsBoard

    board = AzureBoardsBoard(organization="contoso", project="Payments", team="Core", board="Kanban")

    assert board.url() == "https://dev.azure.com/contoso/Payments/_boards/board/t/Core/Kanban"


@pytest.mark.parametrize("coords,expected", [
    ({}, "https://dev.azure.com/contoso/Payments/_boards"),
    ({"team": "Core"}, "https://dev.azure.com/contoso/Payments/_boards/board/t/Core"),
])
def test_and_it_DEGRADES_with_the_coordinates_it_has(coords, expected):
    """A fabricated team name is a 404, and a 404 reads to an operator as "the platform lost my
    board". `…/_boards` is the project's board hub — a page that exists, one click away."""
    from openfactory.adapters.board.azure_devops import AzureBoardsBoard

    board = AzureBoardsBoard(organization="contoso", project="Payments", **coords)

    assert board.url() == expected


def test_a_JIRA_board_links_to_the_projects_own_page():
    """A Jira project may have several boards and this adapter is given none — it works from the
    project key. `/browse/<KEY>` always exists; a fabricated board id does not."""
    from openfactory.adapters.board.jira import JiraProjectBoard

    tracker = type("T", (), {"site": "https://acme.atlassian.net", "project_key": "FX"})()

    assert JiraProjectBoard(tracker).url() == "https://acme.atlassian.net/browse/FX"


def test_and_the_jira_link_comes_from_the_TRACKERS_site():
    """Not from a second copy — a deployment that moves its Jira instance moves both together."""
    from openfactory.adapters.board.jira import JiraProjectBoard

    tracker = type("T", (), {"site": "https://moved.atlassian.net", "project_key": "FX"})()

    assert JiraProjectBoard(tracker).url().startswith("https://moved.atlassian.net/")


@pytest.mark.parametrize("missing", [{"site": "", "project_key": "FX"},
                                     {"site": "https://acme.atlassian.net", "project_key": ""}])
def test_a_board_missing_a_coordinate_says_NOTHING(missing):
    from openfactory.adapters.board.jira import JiraProjectBoard

    assert JiraProjectBoard(type("T", (), missing)()).url() == ""


def test_a_github_board_with_no_number_says_nothing_either():
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    assert GitHubProjectBoard("acme", "").url() == ""


# ── 3. the ratchet ──────────────────────────────────────────────────────────────────────────────

#: The hosts a neutral module must not BUILD a URL on. Recognising one (a parser reading a clone
#: URL a human pasted) and NAMING one to a person ("go to dev.azure.com → User settings") are
#: different acts and neither is flagged — the shape below is what a URL literal looks like.
#:
#: A SUFFIX, NOT A PREFIX. Every Atlassian Cloud URL is a tenant subdomain
#: (`https://acme.atlassian.net/…`), so a check for `https://atlassian.net` matched nothing at all
#: and the third guarded vendor was not guarded. Adversarial review, 2026-08-20.
VENDOR_HOSTS = ("github.com", "dev.azure.com", "atlassian.net")
MARKER = "vendor-url-ok:"
_URL = re.compile(r"https?://([A-Za-z0-9.\-{}]*)")


def _built_urls(root) -> list[str]:
    """Every `https://…<vendor-host>…` spelled outside `adapters/`, unless the line says why.

    THE PROPERTY IS CONSTRUCTION, not mention. The first version of this flagged any occurrence of
    a host and caught seven remedy sentences telling an operator where to get a PAT — advice that
    is useless without the vendor's name. A ratchet that fires on honest code teaches people to
    widen its exemption list, which is how a ratchet stops being one.

    WHAT IT CANNOT SEE, stated rather than implied: a host held in a VARIABLE. `base = HOSTS[kind]`
    then `f"https://{base}/…"` is a vendor URL this walk will not flag, and no static check can
    decide it. The walk covers the shape the defect has actually taken twice — a literal — and the
    behavioural guards above cover the rest.
    """
    from pathlib import Path

    from conftest import code_only

    out: list[str] = []
    for path in sorted(Path(root).rglob("*.py")):
        if "adapters" in path.parts:      # where a vendor's name belongs
            continue
        raw = path.read_text().splitlines()
        # TWO READINGS OF THE SAME LINE. The host is looked for in the CODE — prose naming a
        # vendor is honest and must not fire. The exemption is looked for in the RAW text, because
        # it is a comment and `code_only` is what removes those. `code_only` pads to the source's
        # own line count, so the two line up; the assert says so out loud.
        code = code_only(path.read_text()).splitlines()
        assert len(code) == len(raw), f"the stripper stopped preserving line numbers ({path})"
        starts = _statement_starts(path.read_text())
        for line_no, line in enumerate(code, start=1):
            host = _URL.search(line)
            if not host or not any(host.group(1).endswith(h) for h in VENDOR_HOSTS):
                continue
            if _excused(raw, starts.get(line_no, line_no), line_no):
                continue
            out.append(f"{path.name}:{line_no}")
    return out


def _statement_starts(source: str) -> dict[int, int]:
    """line number → the line its enclosing STATEMENT begins on.

    A URL usually lands on a continuation line — the second line of a wrapped call — while the
    comment justifying it sits above the statement. Anchoring the exemption to the raw line meant
    every real exemption in this package was rejected, which is a ratchet nobody can satisfy
    honestly: the next person deletes it.
    """
    import ast

    out: dict[int, int] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover — the suite would be red long before this walk
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                # the INNERMOST statement wins, so a nested one does not inherit its parent's start
                out[line] = max(out.get(line, 0), node.lineno)
    return out


def _excused(raw: list[str], stmt_line: int, line_no: int) -> bool:
    """Whether this URL's own statement carries a `# vendor-url-ok: <reason>` COMMENT.

    THREE THINGS THE FIRST VERSION GOT WRONG, all found by adversarial review:

      · it read a six-line window, so one comment excused every vendor URL written under it;
      · it required no reason after the colon, so `# vendor-url-ok:` alone was a silencer;
      · it read the marker anywhere in the raw text, so a DOCSTRING or a message string containing
        the words granted the exemption.

    So: the marker must sit in a comment, in the CONTIGUOUS comment block immediately above the
    line (or on the line itself), and something must follow the colon.
    """
    def _reason(text: str) -> bool:
        _, sep, rest = text.partition("#")
        if not sep:
            return False
        head, sep2, why = rest.partition(MARKER)
        return bool(sep2) and bool(why.strip()) and not head.strip()

    if any(_reason(raw[n - 1]) for n in range(stmt_line, line_no + 1)):
        return True
    for above in range(stmt_line - 2, -1, -1):
        stripped = raw[above].strip()
        if not stripped.startswith("#"):
            return False
        if _reason(raw[above]):
            return True
    return False


def test_no_neutral_module_BUILDS_a_vendor_URL():
    """The class, not the site. A vendor's URL shape belongs in `adapters/<vendor>/` — the panel
    is the one somebody notices, and it took two goes to find it there.

    Prose is stripped first: every paragraph explaining this rule names the host it forbids."""
    offenders = _built_urls(_PACKAGE)

    assert not offenders, (
        "a neutral module spells a vendor's URL — ask the port (`BoardAdapter.url`, "
        "`TrackerAdapter.ticket_url`, `ForgeAdapter.clone_url`), or say `# vendor-url-ok: <why>` "
        f"on the line when the shape really is the point: {offenders}")


def test_the_ratchet_actually_WALKS_the_package():
    """THE BUG THIS GUARD HAD. `inspect.getfile(BoardAdapter).parent.parent` is
    `openfactory/adapters` — and the walk skips every path containing `adapters`, so it inspected
    ZERO files and passed vacuously. A weld appended to `api/metrics_view.py` changed nothing in
    7096 tests. Mutating the walk went red the whole time, because the VERIFIER below drives it
    against a temp directory: what nothing checked was the ROOT."""
    from pathlib import Path

    walked = [p for p in Path(_PACKAGE).rglob("*.py") if "adapters" not in p.parts]

    assert len(walked) > 100, f"the ratchet inspects {len(walked)} files — it is guarding nothing"
    assert any(p.name == "app.py" and p.parent.name == "api" for p in walked), (
        "the panel — where this defect was found twice — is not in the walk")


def test_and_it_can_SEE_one_while_leaving_HONEST_prose_alone(tmp_path):
    """Verify the verifier, through the same walk. Every shape it must tell apart is live in this
    package."""
    (tmp_path / "sample.py").write_text(
        'url = f"https://github.com/{owner}/projects/{n}"\n'            # built  → flagged
        'help = "get a PAT at dev.azure.com → User settings"\n'          # named  → fine
        'if raw.startswith("git@ssh.dev.azure.com:v3/"):\n    pass\n'   # parsed → fine
        "# vendor-url-ok: help text showing the shape to paste\n"
        'echo("https://dev.azure.com/<org>/<project>/_git/<repo>")\n'    # excused → fine
        'jira = f"https://{site}.atlassian.net/browse/{key}"\n')         # tenant → flagged

    assert _built_urls(tmp_path) == ["sample.py:1", "sample.py:7"]  # the parse case is 2 lines


@pytest.mark.parametrize("body,why", [
    ("# vendor-url-ok:\nurl = \"https://github.com/x\"\n", "a marker with no reason"),
    ('"""vendor-url-ok: in a docstring"""\nurl = "https://github.com/x"\n', "prose, not a comment"),
    ("# vendor-url-ok: the line below\nurl = \"https://github.com/a\"\n"
     'other = "https://github.com/b"\n', "one reason covering a second URL"),
])
def test_and_an_exemption_cannot_be_had_CHEAPLY(tmp_path, body, why):
    """Three ways the first version could be silenced without saying anything."""
    (tmp_path / "cheat.py").write_text(body)

    assert _built_urls(tmp_path), f"the ratchet was silenced by {why}"


def test_and_the_ratchet_can_SEE_one(tmp_path):
    """Verify the verifier — through `code_only`, which is what makes the walk above safe to run
    over files whose prose names the very hosts it rejects."""
    from conftest import code_only

    source = ('# github.com in a comment does not count\n'
              '"""and neither does a docstring naming dev.azure.com."""\n'
              'url = "https://github.com/orgs/acme/projects/7"\n')
    code = code_only(source)

    assert "github.com" in code
    assert code.splitlines()[0].strip() == "" and "dev.azure.com" not in code
