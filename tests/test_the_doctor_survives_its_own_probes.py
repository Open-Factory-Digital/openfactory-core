"""`sdlc doctor` must survive being run (C-15 follow-up, found in the onboarding walkthrough).

WHY THIS FILE EXISTS AT ALL. `doctor.py` injects every environmental fact as a callable so each
branch is testable without Docker or a network — and that worked, in the sense that `diagnose()` is
covered exhaustively. What it bought was a blind spot the size of the feature: **no test ever built
`probes_for()`**, so the bodies that talk to the real world had never been executed once. The first
time they ran was against a freshly onboarded project, and two of the seven were broken.

The two defects are different in kind and both are worth naming.

**`board_columns` asked for the wrong thing.** `BoardAdapter.columns()` returns `{ticket: column}`
— a map of CARDS. The probe did `list(board.columns())`, which on an empty board is `[]` and on a
populated one is a list of *ticket numbers*. So the check either reports "the board has no 'TO-DO'
column (found: none)" or "(found: 412, 413)". It is wrong in every case, and the case it is wrong
in most loudly is **a brand-new board**, which is the only kind that exists at onboarding time.
`sdlc doctor` failed 100% of correctly configured new projects, on the check whose whole job is to
tell a client their board is fine. The intent was never in doubt — the field's own docstring says
"the board's column names" — the probe just called the neighbouring method.

**`product_link` imported a function that does not exist.** `from openfactory.product.loader import
load_product_docs` — there is no such name, and there never was; the real entry point is
`load_product_context`, three lines further down the same module, which additionally does the
no-network short circuit for the (overwhelmingly common) case of a project with no product module.
An ImportError inside `_guarded` degrades into a finding, so the tool reported "could not check
product_link" and carried on: a broken check that looks like a failing check.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.project import Project
from openfactory.doctor import PICKUP_COLUMN, Probes, _board, diagnose, probes_for

# ── the two live probes, called for real ────────────────────────────────────────────────────────


@pytest.fixture
def bare_project(tmp_path):
    """A project with no product module — the common case, and the one that must cost no network."""
    return Project(name="fixture", repo_path=str(tmp_path))


def test_the_product_probe_can_be_called_at_all(bare_project):
    """The reachability guard. Before the fix this raised ImportError inside `_guarded`, so the
    tool told the user "could not check product_link" — a broken check wearing a failing check's
    clothes."""
    link = probes_for(bare_project).product_link()

    assert getattr(link, "kind", None) == "off"
    assert not getattr(link, "active", True)


def test_the_product_probe_touches_no_network_when_there_is_no_product_module(bare_project,
                                                                             monkeypatch):
    """A project without a `product:` section must not touch the network to find that out.

    THIS CAUGHT THE FIX ITSELF. Routing through `load_product_context` restored the no-clone short
    circuit, and then the very next line undid half of it: the token was minted *before* the call,
    so every `sdlc doctor` on every project without a product module signed a JWT and asked GitHub
    for an installation token in order to discover there was nothing to authenticate for. It is not
    the cost that matters — it is that a diagnostic which makes a network call cannot report on a
    machine with no network, which is one of the states it exists to diagnose."""
    def _boom(*a, **k):  # pragma: no cover — reaching either IS the failure
        raise AssertionError("the product probe reached the network")

    monkeypatch.setattr("openfactory.runtime.repo_cache.RepoCache.sync", _boom)
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", _boom)
    assert probes_for(bare_project).product_link() is not None


def test_the_board_probe_mints_no_token_for_a_project_with_no_board(bare_project, monkeypatch):
    """Same property, same mistake, the other probe. Most projects have no board configured — the
    port itself calls that a legitimate setup — and none of them should pay a token mint to say so.
    """
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("the board probe reached the network")

    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", _boom)
    assert probes_for(bare_project).board_columns() is None


# ── the board probe asks for column NAMES ───────────────────────────────────────────────────────


class _Board:
    """A board with six columns and one card. The two reads must not be confused."""

    def __init__(self, names, items):
        self._names, self._items = names, items

    def column_names(self):
        return list(self._names)

    def columns(self):
        return dict(self._items)

    def pickup_column(self):
        """SELF-CONSISTENT WITH THIS DOUBLE'S OWN COLUMNS, not a constant pasted in.

        A fake that answered `"TO-DO"` while listing `["A Fazer", …]` is a board that cannot
        exist, and a doctor proven against it is proven against nothing — the same trap that let
        `Ticket.state` pass a whole suite while the real contract had no such field. So it names
        the column this board actually has, which is what every real adapter does."""
        for candidate in ("TO-DO", "To Do", "A Fazer"):
            if candidate in self._names:
                return candidate
        return self._names[0] if self._names else "TO-DO"


SIX = ["Backlog", "TO-DO", "In progress", "Needs Action", "In review", "Done"]


def test_the_board_probe_returns_column_names_not_ticket_numbers(bare_project, monkeypatch):
    """THE defect, stated as a property: what comes back must be the board's columns, whatever is
    or is not sitting in them."""
    monkeypatch.setattr("openfactory.adapters.board.factory.build_board",
                        lambda project, **kw: _Board(SIX, {412: "Done", 413: "In review"}))

    assert probes_for(bare_project).board_columns() == SIX


def test_an_empty_board_is_healthy(bare_project, monkeypatch):
    """Every board is empty at onboarding. Reporting the empty one as misconfigured is the single
    most expensive false negative this tool can produce — it is the first thing a new client runs,
    and it told them the thing they had just done correctly was wrong."""
    monkeypatch.setattr("openfactory.adapters.board.factory.build_board",
                        lambda project, **kw: _Board(SIX, {}))

    finding = _board(probes_for(bare_project))
    assert finding.ok, finding.message


def test_a_board_whose_TO_DO_is_merely_UNOCCUPIED_is_healthy(bare_project, monkeypatch):
    """The same confusion with cards present: nothing in TO-DO is the normal resting state of a
    factory that has caught up, not a broken board."""
    monkeypatch.setattr("openfactory.adapters.board.factory.build_board",
                        lambda project, **kw: _Board(SIX, {412: "Done"}))

    assert _board(probes_for(bare_project)).ok


def test_a_board_that_really_lacks_the_pickup_column_still_fails(monkeypatch, tmp_path):
    """The check must not be defanged into always passing — the failure it exists for is a client
    whose board says `Todo` instead of `TO-DO`, which is silent and total."""
    finding = _board(_probes(board_columns=lambda: ["Backlog", "Todo", "Done"]))

    assert not finding.ok
    assert PICKUP_COLUMN in finding.message
    assert "Todo" in finding.message  # it must SHOW what it found, or nobody can spot the typo


def test_none_means_no_board_and_only_that(monkeypatch):
    """`None` carries exactly one meaning: the project configures no board. "Could not read" gets
    its own channel — see the three-state tests at the end of this file, and the defect that made
    them necessary."""
    assert _board(_probes(board_columns=lambda: None)).ok


def _floor_clean_manifest():
    from openfactory.contracts import Manifest

    return Manifest(version=1, base_branch="main",
                    validate={"test": "pytest -q",
                              "security": {"command": "semgrep --config=auto .",
                                           "advisory": True}})


def _probes(**overrides) -> Probes:
    base = dict(
        docker_running=lambda: (True, ""),
        harness_on_path=lambda kind: True,
        # A REAL manifest, satisfying the floor. The two-attribute stub that used to sit here could
        # not answer `declared_keys()` or carry a `validate:` block, so the manifest and floor
        # checks would have been exercised against an object no loader can produce — which is the
        # very trap the `pickup_column` double below is written to avoid.
        manifest=lambda: _floor_clean_manifest(),
        forge_reachable=lambda: (True, ""),
        board_columns=lambda: SIX,
        pickup_column=lambda: "TO-DO",
        requires_review=lambda: False,
        floor_enforced=lambda: False,
        harness_kind=lambda: "claude_code",
        product_link=lambda: type("_L", (), {"kind": "off"})(),
    )
    base.update(overrides)
    return Probes(**base)


def test_a_healthy_setup_says_so(monkeypatch):
    """The bar from the module docstring: a healthy setup must say so OUT LOUD. A tool that only
    ever reports problems cannot be trusted when it reports none."""
    report = diagnose(_probes())

    assert report.ok, [f.message for f in report.findings if not f.ok]
    # BY NAME, NOT BY COUNT. `== 8` said nothing about which check was missing and broke every
    # time one was added — the failure read "assert 9 == 8", which tells a reader neither what
    # appeared nor whether it should have. The set is the claim: a healthy project gets a line
    # about each of these, and adding a check means saying here what it is called.
    assert {f.check for f in report.findings} == {
        "docker", "harness", "manifest", "quality_floor", "forge_access",
        "board_columns", "merge_policy", "post_merge", "product_link",
    }


# ── the port grew a method, so the port must declare it ─────────────────────────────────────────


def test_the_board_port_declares_column_names():
    """`adapters/board/base.py` is explicit that the protocol is derived from what production
    actually calls. The doctor is production, and it needs this read — so it belongs in the port,
    not as an attribute the doctor hopes GitHub's implementation happens to have."""
    from openfactory.adapters.board.base import BoardAdapter

    assert hasattr(BoardAdapter, "column_names")


def test_the_github_board_satisfies_the_port_including_the_new_read():
    from openfactory.adapters.board.base import BoardAdapter
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    board = GitHubProjectBoard("owner", "1")
    assert isinstance(board, BoardAdapter)
    assert callable(board.column_names)


def test_column_names_reports_unreadable_as_None_not_as_no_columns(monkeypatch):
    """Same rule as `columns()`, and for the same reason — a rate-limited read that returns `[]`
    would tell a client to rename columns that are sitting there correctly."""
    from openfactory.adapters.tracker import github_project

    def _boom(self):
        raise RuntimeError("gh: API rate limit exceeded")

    monkeypatch.setattr(github_project.GitHubProjectBoard, "_ensure_meta", _boom)
    assert github_project.GitHubProjectBoard("owner", "1").column_names() is None


# ── three states, not two ───────────────────────────────────────────────────────────────────────
#
# Shipped broken in 1945ee3 and caught by running the doctor inside the compose worker, where the
# board really was unreadable (no credential materialised for `gh`). `column_names()` returns None
# for CANNOT READ, and `_board` already used None for THERE IS NO BOARD — so a permissions failure
# on a configured board reported "no board configured — tickets are named directly", cheerfully, as
# a PASS. The client is told their setup is fine and the poller then picks up nothing, for ever.
#
# It is the exact confusion `adapters/board/base.py` warns about in capitals, made by the person
# who had just re-read the warning to write `column_names`. Two states cannot carry three
# meanings, and the fix is not a cleverer sentinel: the probe keeps `None` for the configuration
# question it can answer honestly, and RAISES for the one it cannot.

def test_a_board_that_cannot_be_read_is_not_a_board_that_does_not_exist(bare_project, monkeypatch):
    from openfactory.doctor import BoardUnreadable

    class _Unreadable:
        def column_names(self):
            return None  # the port's "could not read"

    monkeypatch.setattr("openfactory.adapters.board.factory.build_board",
                        lambda project, **kw: _Unreadable())

    with pytest.raises(BoardUnreadable):
        probes_for(bare_project).board_columns()


def test_an_unreadable_board_fails_with_a_credential_remedy(bare_project, monkeypatch):
    """Distinct cause, distinct actionable line — the module's own stated bar. Sending somebody to
    rename a column they cannot even see is worse than saying nothing."""
    from openfactory.doctor import BoardUnreadable, _board

    def _raise():
        raise BoardUnreadable("AcmeFixtures/1")

    finding = _board(_probes(board_columns=_raise))

    assert not finding.ok
    assert "could not be read" in finding.message.lower()
    assert "AcmeFixtures/1" in finding.message
    assert "credential" in finding.remedy.lower() or "token" in finding.remedy.lower()


def test_no_board_configured_is_still_a_pass(bare_project, monkeypatch):
    """The other two states must keep working. A project with no board is a legitimate setup —
    `build_board` returns None and the port says so."""
    from openfactory.doctor import _board

    monkeypatch.setattr("openfactory.adapters.board.factory.build_board", lambda project, **kw: None)
    probes = probes_for(bare_project)

    assert probes.board_columns() is None
    assert _board(probes).ok


# ── "docker is not running" when docker is running perfectly ────────────────────────────────────
#
# The compose worker mounts the host's docker socket but the image carried no `docker` CLI, so
# `docker info` raised FileNotFoundError and the probe returned False — indistinguishable, to
# `_docker`, from a stopped daemon. The tool told the product owner to start Docker Desktop while
# Docker Desktop was serving the very container the message was printed in.
#
# The information to tell them apart was RIGHT THERE and thrown away: a missing binary is
# FileNotFoundError, a stopped daemon is a non-zero exit. `forge_reachable` in the same dataclass
# already returns `(ok, detail)` for exactly this reason — the probe was the odd one out.
#
# It matters more than a wording nit. `ContainerSandbox` shells out to `docker`, so a worker
# without the client cannot run ANY job; sending its operator to restart a daemon that is already
# up is a diagnosis that costs an afternoon.

def test_a_missing_docker_client_is_not_a_stopped_daemon():
    from openfactory.doctor import _docker

    finding = _docker(_probes(docker_running=lambda: (False, "the docker CLI is not installed")))

    assert not finding.ok
    assert "not installed" in finding.message
    assert "start docker" not in finding.remedy.lower(), (
        "told to start a daemon that is already running; the binary is what is missing"
    )
    assert "install" in finding.remedy.lower()


def test_a_stopped_daemon_still_says_start_it():
    from openfactory.doctor import _docker

    finding = _docker(_probes(docker_running=lambda: (False, "")))

    assert not finding.ok
    assert "start" in finding.remedy.lower()


def test_a_healthy_docker_passes():
    from openfactory.doctor import _docker

    assert _docker(_probes(docker_running=lambda: (True, ""))).ok


def test_the_live_probe_reports_a_missing_binary_distinctly(bare_project, monkeypatch):
    """The reachability half: `probes_for` must actually produce the distinction, not just be
    capable of carrying it."""
    import subprocess as sp

    def _no_binary(*a, **k):
        raise FileNotFoundError(2, "No such file or directory: 'docker'")

    monkeypatch.setattr(sp, "run", _no_binary)
    ok, detail = probes_for(bare_project).docker_running()

    assert ok is False
    assert "cli" in detail.lower() or "not installed" in detail.lower(), detail
