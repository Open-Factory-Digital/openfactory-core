"""The factory asks for help on its own board — never from the client, never in a chat line.

The product owner named this after watching Nina spend a morning telling a CLIENT that she could
not open the code, and asking them to restore her access:

    *"a PO saying that to the client makes no sense… her sitting in a loop with the client, nobody
    resolves anything, nobody knows what is going on… she should be asking the FACTORY for help…
    this should be a support ticket… maybe we need a board for the factory itself."*

Three separate defects were in that one observation, and this file pins the fixes for all three:

  1. the degradation existed NOWHERE the factory could see it — no owner, no state, no history, so
     the only reason anybody noticed is that he happened to be watching;
  2. the platform's own sentence to the client ("já avisei o time") was FALSE;
  3. and a chat message would not have fixed it either: it has no owner and does not close.

WHAT THE DESIGN TURNS ON, and what breaks if any of it is undone:

  * the impediment is a TICKET, on a board that belongs to the DEPLOYMENT — never the client's
    (ADR-0027: eleven smoke-test tickets already shipped eleven dead endpoints into one);
  * it is idempotent by a DETERMINISTIC title, so an hour of breakage is one ticket and not one
    per message — the difference between a history and a flood;
  * it closes by OBSERVATION (ADR-0021): nobody marks it resolved, the next working mount does,
    and the evidence goes in the comment;
  * and it can NEVER cost a client their answer — every failure here is swallowed into a log.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import FactoryBoard, Project, ProviderRef
from openfactory.ops import impediment
from openfactory.ops.impediment import PRODUCT_MOUNT_EMPTY, PRODUCT_NO_CODE


class _Tracker:
    """A tracker at the production seam, recording what was asked of it."""

    def __init__(self, existing: dict[str, str] | None = None, *, breaks: str = ""):
        self.tickets = dict(existing or {})      # title -> ref
        self.created: list[tuple[str, str]] = []
        self.closed: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []
        self.labels: list[tuple[str, str]] = []
        self.assigned: list[tuple[str, list[str]]] = []
        self.breaks = breaks
        self._next = 900

    def _maybe_break(self, op: str) -> None:
        if self.breaks == op:
            raise RuntimeError(f"the tracker refused to {op}")

    def find_ticket(self, *, title: str):
        self._maybe_break("find")
        return self.tickets.get(title)

    def create_ticket(self, *, title: str, body: str) -> str:
        self._maybe_break("create")
        self._next += 1
        ref = f"#{self._next}"
        self.tickets[title] = ref
        self.created.append((title, body))
        return ref

    def close_ticket(self, ref: str, reason: str, *, delivered: bool = True) -> None:
        self._maybe_break("close")
        self.closed.append((ref, reason))
        for title, r in list(self.tickets.items()):
            if r == ref:
                del self.tickets[title]

    def comment(self, ref: str, body: str) -> None:
        self.comments.append((ref, body))

    def add_label(self, ref: str, label: str) -> None:
        self._maybe_break("label")
        self.labels.append((ref, label))

    def set_assignees(self, ref: str, logins: list[str]) -> None:
        self._maybe_break("assign")
        self.assigned.append((ref, list(logins)))


def _project(*, board: FactoryBoard | None = None, language: str = "pt-BR",
             name: str = "books") -> Project:
    # `language` IS DECLARED HERE ON PURPOSE (#160). The ticket's BODY follows it — this module's
    # own comment says the title is the identity and the body is where a language may be chosen —
    # and the guards below read the Portuguese back, so the fixture has to say which language it
    # is asserting about. A test that reads a language it never declared is asserting the
    # deployment default and calling it a translation.
    return Project(name=name, repo_path="/t", language=language,
                   tracker=ProviderRef(kind="github", repo="AcmeCorp/acme-books"),
                   forge=ProviderRef(kind="github", repo="AcmeCorp/acme-books"),
                   factory_board=board,
                   product=ProductConfig(docs_repo="a/docs", channel_id="C1",
                                         admins=["U1"], agent_name="Nina"))


@pytest.fixture(autouse=True)
def _forget_what_was_observed():
    """`impediment._LAST` is process-global by design — it is what stops one forge call per client
    message. Global state that leaks between tests is the defect this repository has paid for
    twice; a suite whose result depends on file order proves nothing."""
    impediment._LAST.clear()
    yield
    impediment._LAST.clear()


def _board(**kw) -> FactoryBoard:
    kw.setdefault("tracker", ProviderRef(kind="github", repo="AcmeCorp/openfactory"))
    kw.setdefault("supervisor", "aliceferreira")
    return FactoryBoard(**kw)


# ── 1. it files, and it names somebody ──────────────────────────────────────────────────────────

def test_a_broken_capability_becomes_a_ticket_with_an_owner():
    trk = _Tracker()

    ref = impediment.report(_project(board=_board()), PRODUCT_MOUNT_EMPTY,
                            "root=/tmp/x entries=0", tracker=trk)

    assert ref and trk.created, "the impediment existed only in a log line"
    title, body = trk.created[0]
    # THE TITLE IS AN IDENTITY, NOT PROSE (#124). It is the dedup key — `find_ticket(title=…)`
    # matches exactly — so it carries a stable marker and stays in one language while the BODY
    # carries the explanation. Pinned on the marker rather than on the words, which is what let
    # the words change at all.
    assert "books" in title and "[openfactory]" in title
    assert title.isascii(), (
        "the dedup key grew a character an accent-folding tracker may normalise — the second "
        "occurrence would file a duplicate")
    assert "aliceferreira" in body, "nobody is accountable for it"
    assert trk.assigned == [(ref, ["aliceferreira"])]
    assert trk.labels == [(ref, "fabrica")]


def test_the_ticket_says_how_it_ends_and_what_it_costs():
    """A supervisor opening it cold must not need to read the source to know what to do."""
    trk = _Tracker()
    impediment.report(_project(board=_board()), PRODUCT_MOUNT_EMPTY, "detalhe", tracker=trk)

    _, body = trk.created[0]

    assert "não pede nada ao cliente" in body
    assert "sozinho, na próxima vez que a capacidade funcionar" in body
    assert "detalhe" in body

    # AND THE OTHER ROW IS REACHED. Same ticket, same facts, a project that declares English —
    # otherwise the sentence above is one this file happens to agree with rather than one the
    # deployment chose.
    trk_en = _Tracker()
    # A DIFFERENT PROJECT NAME, because `_LAST` remembers per project+cause that the ticket is
    # already open — the idempotency this module exists to provide, and it would silently make
    # the second half of this guard assert nothing.
    impediment.report(_project(board=_board(), language="en", name="livres"),
                      PRODUCT_MOUNT_EMPTY, "detail", tracker=trk_en)

    _, english = trk_en.created[0]

    assert "asks the client for nothing" in english
    assert "by itself, the next time the capability works" in english
    assert english != body


def test_a_deployment_with_no_supervisor_says_so_in_the_ticket():
    """An impediment with no owner is the silent wait wearing a hat — so the ticket says it out
    loud instead of looking like ordinary work."""
    trk = _Tracker()
    impediment.report(_project(board=_board(supervisor="")), PRODUCT_MOUNT_EMPTY, "x", tracker=trk)

    _, body = trk.created[0]

    assert "ninguém" in body and "não nomeou um supervisor" in body
    assert trk.assigned == [], "somebody was assigned who was never named"


# ── 2. one trouble, one ticket ──────────────────────────────────────────────────────────────────

def test_an_hour_of_breakage_is_ONE_ticket_not_one_per_message():
    """This runs on the path of every client message. Without dedup a capability broken for an
    hour would file a ticket per turn, and the history it exists to build becomes a flood nobody
    reads."""
    trk, project = _Tracker(), _project(board=_board())

    first = impediment.report(project, PRODUCT_MOUNT_EMPTY, "turno 1", tracker=trk)
    assert first
    calls_after_first = len(trk.created) + len(trk.tickets)
    for turn in range(2, 12):
        impediment.report(project, PRODUCT_MOUNT_EMPTY, f"turno {turn}", tracker=trk)

    assert len(trk.created) == 1, f"{len(trk.created)} tickets for one trouble"
    # STRONGER THAN "one ticket": not one forge call either. Ten client messages against a broken
    # capability must cost nothing — the App quota is shared with the poller and every job.
    assert len(trk.created) + len(trk.tickets) == calls_after_first


def test_two_different_causes_are_two_tickets():
    trk, project = _Tracker(), _project(board=_board())

    a = impediment.report(project, PRODUCT_MOUNT_EMPTY, "x", tracker=trk)
    b = impediment.report(project, PRODUCT_NO_CODE, "y", tracker=trk)

    assert a != b and len(trk.created) == 2


def test_two_deployments_never_share_a_ticket():
    """Per deployment, always. One installation must not see another's operational trouble, and
    must not have its impediment closed by somebody else's recovery."""
    trk = _Tracker()
    one = _project(board=_board())
    other = _project(board=_board()).model_copy(update={"name": "outra-empresa"})

    impediment.report(one, PRODUCT_MOUNT_EMPTY, "x", tracker=trk)
    impediment.report(other, PRODUCT_MOUNT_EMPTY, "x", tracker=trk)

    assert len(trk.created) == 2, "two deployments collapsed into one ticket"


# ── 3. it closes by observation, never by self-report ───────────────────────────────────────────

def test_the_next_working_mount_closes_it_and_says_why():
    trk, project = _Tracker(), _project(board=_board())
    ref = impediment.report(project, PRODUCT_MOUNT_EMPTY, "entries=0", tracker=trk)

    assert impediment.resolved(project, PRODUCT_MOUNT_EMPTY, "entries=37", tracker=trk) is True

    assert trk.closed == [(ref, "completed")]
    assert any("entries=37" in body for _, body in trk.comments), (
        "it closed without recording the evidence that closed it")


def test_closing_something_that_was_never_open_is_not_an_event():
    """The ordinary case — the capability works, and has been working. It must cost one lookup and
    produce no noise."""
    trk, project = _Tracker(), _project(board=_board())

    assert impediment.resolved(project, PRODUCT_MOUNT_EMPTY, "ok", tracker=trk) is False
    assert trk.closed == [] and trk.comments == []


def test_a_reopened_trouble_files_again_after_a_close():
    trk, project = _Tracker(), _project(board=_board())
    impediment.report(project, PRODUCT_MOUNT_EMPTY, "1", tracker=trk)
    impediment.resolved(project, PRODUCT_MOUNT_EMPTY, "voltou", tracker=trk)

    impediment.report(project, PRODUCT_MOUNT_EMPTY, "2", tracker=trk)

    assert len(trk.created) == 2, "a trouble that came back was swallowed as already-known"


# ── 4. reporting trouble must never become trouble ──────────────────────────────────────────────

@pytest.mark.parametrize("breaks", ["find", "create", "label", "assign"])
def test_a_tracker_that_refuses_never_costs_the_client_their_answer(breaks):
    """This runs while somebody is waiting for a reply. An impediment that raised would be a worse
    bug than the one it reports."""
    trk = _Tracker(breaks=breaks)

    ref = impediment.report(_project(board=_board()), PRODUCT_MOUNT_EMPTY, "x", tracker=trk)

    assert isinstance(ref, str)          # no exception escaped
    if breaks in ("label", "assign"):
        assert ref, "a decoration failure undid the filing itself"


def test_a_filing_the_forge_REFUSED_is_retried_and_never_remembered_as_filed():
    """THE CACHE RECORDS WHAT THE BOARD WAS OBSERVED TO HOLD, never what was attempted against it.

    Marked broken before the create returned, one throttled call — the ordinary weather on a quota
    shared with the poller and every job — suppressed that impediment for the LIFE of the worker:
    the second occurrence short-circuits on "the ticket is open and already says this" and it is
    not, no ticket is ever filed, nothing says so a second time, and the client goes on being told
    the team was warned on every refusal. That is the silent degradation this module exists to end,
    manufactured by the module."""
    trk, project = _Tracker(breaks="create"), _project(board=_board())

    assert impediment.report(project, PRODUCT_MOUNT_EMPTY, "turno 1", tracker=trk) == ""
    trk.breaks = ""                    # the rate limit passes, as rate limits do
    ref = impediment.report(project, PRODUCT_MOUNT_EMPTY, "turno 2", tracker=trk)

    assert ref and len(trk.created) == 1, "a filing that failed was remembered as a filing"
    assert "turno 2" in trk.created[0][1]


def test_a_CLOSE_the_forge_refused_is_retried_and_never_remembered_as_closed():
    """The same rule on the other side, and the same file: an impediment marked "working" on a close
    that raised leaves the ticket open with nothing left to close it — an operator who fixed it
    silently and a fix that never happened look alike again, which is what the docstring above
    forbids."""
    trk, project = _Tracker(), _project(board=_board())
    ref = impediment.report(project, PRODUCT_MOUNT_EMPTY, "entries=0", tracker=trk)
    trk.breaks = "close"
    assert impediment.resolved(project, PRODUCT_MOUNT_EMPTY, "entries=37", tracker=trk) is False

    trk.breaks = ""
    assert impediment.resolved(project, PRODUCT_MOUNT_EMPTY, "entries=41", tracker=trk) is True

    assert trk.closed == [(ref, "completed")], "the impediment was left open and never retried"


def test_a_deployment_with_no_board_is_SAID_not_silently_dropped(caplog):
    """Today's behaviour, stated. A deployment that discards its own impediments in silence is the
    exact state this module exists to end — so its absence is a warning, not a shrug."""
    with caplog.at_level("WARNING"):
        ref = impediment.report(_project(board=None), PRODUCT_MOUNT_EMPTY, "detalhe", tracker=None)

    assert ref == ""
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "OPENFACTORY_OPS_NO_BOARD" in said and "detalhe" in said


# ── 5. reached from the real degradation, not only from a test ──────────────────────────────────

def test_an_empty_MOUNT_reaches_the_factory_board(tmp_path, monkeypatch):
    """The reachability assertion. This codebase's signature defect is a capability that exists,
    passes its tests, and is reached by nothing in production — so the test drives `_log_mount`,
    which is what the real workspace builder calls."""
    from openfactory.product import module as product_module

    filed: list[tuple] = []
    monkeypatch.setattr(product_module, "_tell_the_factory",
                        lambda project, cause, detail, *, ok: filed.append((cause, ok)))
    empty = tmp_path / "vazio"
    empty.mkdir()

    product_module._log_mount(_project(board=_board()), empty, docs=empty, code=None)

    assert (PRODUCT_MOUNT_EMPTY, False) in filed, filed
    assert (PRODUCT_NO_CODE, False) in filed, "answering with no code reached nobody"


def test_a_HEALTHY_mount_closes_both_impediments(tmp_path, monkeypatch):
    from openfactory.product import module as product_module

    filed: list[tuple] = []
    monkeypatch.setattr(product_module, "_tell_the_factory",
                        lambda project, cause, detail, *, ok: filed.append((cause, ok)))
    root, docs, code = tmp_path / "view", tmp_path / "docs", tmp_path / "code"
    for d in (root, docs, code):
        d.mkdir()
        (d / "algo.md").write_text("x")

    product_module._log_mount(_project(board=_board()), root, docs=docs, code=code)

    assert (PRODUCT_MOUNT_EMPTY, True) in filed and (PRODUCT_NO_CODE, True) in filed


def test_the_factory_board_is_NEVER_the_clients_board():
    """ADR-0027, enforced where it can actually be broken: the impediment tracker is built from the
    factory board's own ref, so a deployment that forgets to declare one files nothing rather than
    falling back to the client's product board."""
    board = _board()

    assert board.tracker.repo != _project().tracker.repo
    assert impediment._tracker_for(_project(board=None), None) is None


def test_a_DECLARED_board_really_builds_a_tracker_and_points_at_itself():
    """THE BRANCH EVERY OTHER TEST HERE WALKS AROUND, and the one production depends on.

    Every test above hands `tracker=` in, so `_tracker_for`'s real work — building an adapter from
    the declared `ProviderRef` — was reached by nothing. It sits inside `report`'s catch-all, so a
    `build_tracker` that raised on this ref would have produced exactly what the code did before
    any of this existed: an empty string, one log line, and a client told the team was warned.
    Fourteen instances of "built, tested, reached by nothing" is enough to stop hoping.

    Also proves the ref needs no board coordinates: an impediment is an ISSUE, and requiring
    `board_owner`/`board_number` here would make declaring a factory board a two-step ceremony
    where the second step is silent when skipped."""
    trk = impediment._tracker_for(_project(board=_board()), None)

    assert trk is not None, "the declared board built no tracker — every impediment is a log line"
    assert getattr(trk, "repo", "") == "AcmeCorp/openfactory", (
        f"the impediment would be filed on {getattr(trk, 'repo', '?')} — see ADR-0027")
