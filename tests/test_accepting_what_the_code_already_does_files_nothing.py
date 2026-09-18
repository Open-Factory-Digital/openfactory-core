"""Accepting a reading of the code records the promise and files NOTHING (#182).

THE DEFECT. `product baseline` reverse-engineers a codebase into `observed` entries, each one a
description of something the system ALREADY DOES, and the product page offers Accept on every one
of them. Accepting one ran the same chain as accepting a freshly written requirement: the promise
was recorded and then the breakdown asked the role to *"Break the requirement below into issues"*
— about behaviour that is already built. An empty answer is an error there, so the only shapes the
role could answer in were "create it" and "already on the board". At best one model call per
acceptance and nothing filed; at worst a Backlog of cards for delivered behaviour, which a later
promote turns into spend. Found on a deployment with a 65-entry baseline waiting to be confirmed.

AND THE CORE COULD NOT TELL, THOUGH ITS MODEL SAID IT COULD. `Requirement.evidence` was declared
and documented — "Empty for an authored requirement" — and `parse_requirement` never set it:
measured on `1512d0a`, a file `render_candidate` wrote with `Evidence: tested` parsed with
`evidence == ""`. `Observed at commit:` was written and read by nothing at all.

WHAT IS DRIVEN HERE. A real documentation repository (git, on disk) holding one entry exactly as
`render_candidate` writes it and one exactly as `render_requirement` writes it; the real
`ProductModule` over the real corpus loader; the real catalog row and the real chat executor. The
two things that SPEND are doubled and counted — the engine client the catalog starts the breakdown
workflow on, and the harness the role calls — so every case can say NOT CALLED for the reading of
the code and CALLED for the authored requirement. A guard that only proved the first half would
pass on a module that files nothing for anybody.
"""

from __future__ import annotations

import asyncio
import inspect
import subprocess
from pathlib import Path

import pytest

from openfactory.actions import catalog
from openfactory.actions.base import Actor
from openfactory.contracts import AgentRunResult
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product import confirm as confirm_mod
from openfactory.product.authoring import _set_status_accepted, render_requirement
from openfactory.product.brownfield import ASKED, CODE, TESTED, Observation, render_candidate
from openfactory.product.config import ProductLink
from openfactory.product.corpus import UNRECORDED, load_corpus, parse_requirement
from openfactory.product.loader import ProductContext
from openfactory.product.module import ProductModule
from openfactory.product.role import RequirementDraft

DOCS = "acmecorp/acme-books-documentation"
ADMIN = "U0BJZADMIN"
COMMIT = "9f2c1ab"

#: the authored requirement, and the reading of the code
AUTHORED, OBSERVED_N = 7, 12
_OBSERVED_FILE = "0012-exports-the-ledger-as-csv.md"
_AUTHORED_FILE = "0007-pacote-de-fecho.md"

#: what the harness answers when it IS asked to break something down
_ONE_ISSUE = ('{"issues": [{"title": "Gerar o pacote de fecho", "objective": "o", '
              '"acceptance_criteria": ["c"]}]}')


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    for key, value in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"),
                       ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(key, value)


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _candidate(evidence: str = TESTED, *, commit: str = COMMIT) -> str:
    """One entry EXACTLY as `product baseline` writes it — the production writer, not a fixture
    that resembles it."""
    return render_candidate(
        Observation(title="Exports the ledger as CSV",
                    behaviour="a closed month can be exported as a CSV file",
                    evidence=evidence, citations=["ledger/export.py", "tests/test_export.py"]),
        number=OBSERVED_N, commit=commit, date="2026-09-18")


def _authored() -> str:
    return render_requirement(
        RequirementDraft(title="Pacote de fecho", why="o cliente fecha o mês",
                         must_be_true=["o fecho gera o pacote completo"]), number=AUTHORED)


@pytest.fixture
def origin(tmp_path):
    src = tmp_path / "docs-origin"
    src.mkdir()
    _git("init", "-q", "-b", "main", cwd=src)
    _git("config", "user.email", "t@t", cwd=src)
    _git("config", "user.name", "t", cwd=src)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=src)
    (src / "requirements").mkdir()
    (src / "requirements" / _AUTHORED_FILE).write_text(_authored())
    (src / "requirements" / _OBSERVED_FILE).write_text(_candidate())
    _git("add", "-A", cwd=src)
    _git("commit", "-qm", "seed", cwd=src)
    return src


class _Harness:
    """The thing that costs money. Every prompt it is handed is one model call."""

    name = "recording"

    def __init__(self):
        self.prompts: list[str] = []

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        return AgentRunResult(ok=True, summary=_ONE_ISSUE)


class _Tracker:
    def __init__(self):
        self.created: list[str] = []

    def find_ticket(self, *, title):
        return None

    def create_ticket(self, *, title, body):
        self.created.append(title)
        return f"#{900 + len(self.created)}"

    def comment(self, ref, body):
        pass


class _Board:
    def add_item(self, *, issue_url):
        return True

    def set_column(self, *, issue, issue_url, name):
        return True


def _project(language: str = "en") -> Project:
    return Project(name="books", repo_path="/work/books", language=language,
                   product=ProductConfig(docs_repo=DOCS, admins=[ADMIN]))


def _module(origin, monkeypatch, *, language: str = "en"):
    """The production module over the real corpus loader, as it stands on `main` of the docs
    repository RIGHT NOW — read again on every call, which is what `_corpus_changed` forces in
    production after the acceptance has been written."""
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda project, repo="", *, token=None: str(origin))
    _git("reset", "-q", "--hard", "main", cwd=origin)   # the working tree follows the pushed flip
    ctx = ProductContext(
        link=ProductLink(active=True, docs_repo=DOCS, kind="ok", reason="fine"),
        corpus=load_corpus(origin / "requirements"),
        docs_path=str(origin), docs_commit="abc123", requirements_dir="requirements")
    harness, tracker = _Harness(), _Tracker()
    mod = ProductModule(_project(language), token="", context=ctx, agent=harness)
    mod._read_board = lambda **_: ([], "")                     # noqa: SLF001 — the module's seam
    mod._tracker = lambda: tracker                             # noqa: SLF001
    mod._board_or_default = lambda _b: _Board()                # noqa: SLF001
    mod._open_delivery = lambda *_a, **_k: None                # noqa: SLF001
    # AFTER A WRITE THE MODULE RE-READS, as production does. Without this the second act of an
    # acceptance would ask the corpus from before the flip and be refused as "not a promise" —
    # red for a reason that has nothing to do with this card.
    real_changed = mod._corpus_changed                         # noqa: SLF001

    def _changed(result):
        kept = real_changed(result)
        if getattr(result, "ok", False):
            _git("reset", "-q", "--hard", "main", cwd=origin)
            mod._context = ProductContext(                     # noqa: SLF001
                link=ctx.link, corpus=load_corpus(origin / "requirements"),
                docs_path=str(origin), docs_commit="abc124", requirements_dir="requirements")
        return kept

    mod._corpus_changed = _changed                             # noqa: SLF001
    return mod, harness, tracker


def _on_main(origin, name: str) -> str:
    return _git("show", f"main:requirements/{name}", cwd=origin).stdout


class _Engine:
    """The engine client the catalog row dispatches on. `started` is every workflow it was asked
    to run — the breakdown is an agent pass on the worker, so a start IS the spend."""

    def __init__(self):
        self.started: list[tuple[str, object]] = []

    async def execute_workflow(self, name, inp, **_kw):
        self.started.append((name, inp))
        return [{"ok": True, "ref": "books#41", "detail": "", "url": "", "existed": False}]


@pytest.fixture
def engine(monkeypatch):
    client = _Engine()

    async def _connected():
        return client, None

    monkeypatch.setattr(catalog, "_connected", _connected)
    return client


def _panel_actor() -> Actor:
    return Actor(id=ADMIN, display="Bia Rocha", via="api", admin=True)


def _through_the_catalog(mod, monkeypatch):
    monkeypatch.setattr(catalog, "_product_module",
                        lambda _n, **_kw: (mod, mod.project, None))


# ── 1. the core can tell: the requirement's own data is read ────────────────────────────────────

@pytest.mark.parametrize("tier", [ASKED, TESTED, CODE])
def test_an_entry_the_baseline_wrote_PARSES_with_its_evidence_and_its_commit(tier):
    req, findings = parse_requirement(Path(_OBSERVED_FILE), _candidate(tier))

    assert req is not None and req.status == "observed"
    assert req.evidence == tier, (
        f"`Evidence: {tier}` is in the file and the model still says {req.evidence!r} — the field "
        f"every rule about a reverse-engineered entry would have to read")
    assert req.observed_at == COMMIT, "the commit the behaviour was read at is written and not read"
    assert req.came_from_the_code is True
    assert not [f for f in findings if f.code.startswith("evidence")]


def test_an_AUTHORED_requirement_carries_neither_and_did_not_come_from_the_code():
    req, _ = parse_requirement(Path(_AUTHORED_FILE), _authored())

    assert req is not None
    assert (req.evidence, req.observed_at) == ("", "")
    assert req.came_from_the_code is False, (
        "a requirement a person asked for would be accepted with no work filed")


def test_a_commit_NOBODY_recorded_is_absence_and_the_evidence_still_speaks():
    req, _ = parse_requirement(Path(_OBSERVED_FILE), _candidate(commit=""))

    assert UNRECORDED in _candidate(commit=""), "precondition: the writer's placeholder is there"
    assert req.observed_at == "", "the placeholder was read as a commit"
    assert req.came_from_the_code is True


def test_the_commit_ALONE_is_enough():
    """A person who deletes the Evidence line while tidying has not made the behaviour unbuilt."""
    text = "\n".join(ln for ln in _candidate().splitlines() if "**Evidence:**" not in ln)
    req, _ = parse_requirement(Path(_OBSERVED_FILE), text)

    assert (req.evidence, req.observed_at) == ("", COMMIT)
    assert req.came_from_the_code is True


def test_a_tier_nobody_defined_is_a_FINDING_and_still_a_reading_of_the_code():
    """The failure direction is chosen: an entry that says it was evidenced, in a word this build
    does not know, files nothing and says so — visible and recoverable — rather than costing a
    model call and a Backlog of cards for built behaviour."""
    text = _candidate().replace(f"**Evidence:** {TESTED}", "**Evidence:** strong")
    req, findings = parse_requirement(Path(_OBSERVED_FILE), text)

    assert req.evidence == "strong" and req.came_from_the_code is True
    (finding,) = [f for f in findings if f.code == "evidence-unknown"]
    assert finding.level == "warn" and finding.path == _OBSERVED_FILE
    for tier in (ASKED, TESTED, CODE):
        assert tier in finding.message, "the finding does not name what it expected"


def test_the_ACCEPTANCE_keeps_both_lines_so_the_promise_records_what_it_was_confirmed_against():
    """Write → accept → parse. The flip rewrites three lines of the header and must not cost the
    two that say where the entry came from — they are what every later rule reads."""
    flipped, outcome = _set_status_accepted(_candidate(), accepted_by=f"<@{ADMIN}>",
                                            day="2026-09-19")
    req, _ = parse_requirement(Path(_OBSERVED_FILE), flipped)

    assert outcome == "flipped" and req.is_promise
    assert (req.evidence, req.observed_at) == (TESTED, COMMIT)
    assert req.came_from_the_code is True


# ── 2. the act reports it ───────────────────────────────────────────────────────────────────────

def test_the_module_s_acceptance_SAYS_there_is_nothing_to_build(origin, monkeypatch):
    mod, _h, _t = _module(origin, monkeypatch)

    observed = mod.accept(OBSERVED_N, actor=ADMIN)
    authored = mod.accept(AUTHORED, actor=ADMIN)

    assert observed.ok and authored.ok
    assert "**Status:** accepted" in _on_main(origin, _OBSERVED_FILE), "the promise was not written"
    assert observed.nothing_to_build is True
    assert authored.nothing_to_build is False, "an authored requirement would get no work"


def test_a_SECOND_acceptance_of_the_same_reading_still_says_so(origin, monkeypatch):
    """`existed` is the catalog's retry door — it re-runs the breakdown — so the answer has to be
    the same the second time or the second click files what the first one rightly did not."""
    mod, _h, _t = _module(origin, monkeypatch)
    assert mod.accept(OBSERVED_N, actor=ADMIN).ok

    again = mod.accept(OBSERVED_N, actor=ADMIN)

    assert again.ok and again.existed and again.nothing_to_build is True


# ── 3. the panel's door: the catalog row ────────────────────────────────────────────────────────

def test_the_catalog_accepts_a_reading_of_the_code_and_STARTS_NOTHING(origin, monkeypatch, engine):
    mod, harness, tracker = _module(origin, monkeypatch)
    _through_the_catalog(mod, monkeypatch)

    out = asyncio.run(catalog._product_accept(project="books", number=str(OBSERVED_N),
                                              by=_panel_actor(), yes=True))

    assert out.ok, out.message
    assert "**Status:** accepted" in _on_main(origin, _OBSERVED_FILE), "the promise was not written"
    assert engine.started == [], (
        f"accepting what the code already does started {engine.started[0][0]} — an agent pass "
        f"asked to invent work for behaviour that is built")
    assert harness.prompts == [] and tracker.created == []
    assert out.data["filed"] == [] and out.data["nothing_to_build"] is True
    said = out.message.lower()
    assert "already does" in said and "nothing to build" in said, out.message
    assert "defend" in said, "the answer does not say what the acceptance DID do"
    assert "could not" not in said, "a decision not to file is being told as a failure to file"


def test_and_an_AUTHORED_requirement_still_gets_its_work(origin, monkeypatch, engine):
    """The other half. Without it the case above passes on a row that files nothing for anybody."""
    mod, _h, _t = _module(origin, monkeypatch)
    _through_the_catalog(mod, monkeypatch)

    out = asyncio.run(catalog._product_accept(project="books", number=str(AUTHORED),
                                              by=_panel_actor(), yes=True))

    assert out.ok, out.message
    assert [name for name, _ in engine.started] == ["ProductBreakdownWorkflow"]
    assert engine.started[0][1].number == AUTHORED
    assert engine.started[0][1].asked_for is False, "the automatic chain claims a person asked"
    assert "books#41" in out.message and out.data["nothing_to_build"] is False


def test_the_catalog_answers_in_the_PROJECTS_language(origin, monkeypatch, engine):
    mod, _h, _t = _module(origin, monkeypatch, language="pt-BR")
    _through_the_catalog(mod, monkeypatch)

    out = asyncio.run(catalog._product_accept(project="books", number=str(OBSERVED_N),
                                              by=_panel_actor(), yes=True))

    assert out.ok and engine.started == []
    assert "já faz" in out.message and "nothing to build" not in out.message.lower(), out.message


# ── 4. the conversation's door: the staged yes ──────────────────────────────────────────────────

def _confirmed_in_chat(mod, number: int, *, lang: str = "en") -> str:
    return confirm_mod._confirm_accept(mod.project, {"kind": "accept", "number": number},
                                       module=mod, user=ADMIN, lang=lang)


def test_the_chat_accepts_a_reading_of_the_code_and_the_ROLE_IS_NOT_CALLED(origin, monkeypatch):
    mod, harness, tracker = _module(origin, monkeypatch)
    reached: list[int] = []
    real = mod.break_down
    mod.break_down = lambda number, **kw: (reached.append(number), real(number, **kw))[1]

    said = _confirmed_in_chat(mod, OBSERVED_N)

    assert "**Status:** accepted" in _on_main(origin, _OBSERVED_FILE)
    assert reached == [], (
        "the acceptance said there was nothing to build and the executor went to the breakdown "
        "anyway — it is the sink that stopped it, after re-reading the corpus for nothing")
    assert harness.prompts == [], (
        "the chat's acceptance asked the model to break built behaviour into issues:\n"
        + harness.prompts[0][:300] if harness.prompts else "")
    assert tracker.created == []
    assert "already does" in said.lower() and "nothing to build" in said.lower(), said


def test_and_the_chat_still_breaks_an_AUTHORED_requirement_down(origin, monkeypatch):
    mod, harness, tracker = _module(origin, monkeypatch)

    said = _confirmed_in_chat(mod, AUTHORED)

    assert len(harness.prompts) == 1, "the automatic breakdown stopped running for real requests"
    assert tracker.created == ["Gerar o pacote de fecho"], said


def test_the_chat_says_it_in_BOTH_languages(origin, monkeypatch):
    mod, _h, _t = _module(origin, monkeypatch)
    en = _confirmed_in_chat(mod, OBSERVED_N, lang="en")

    from openfactory.product.voice import accepted_nothing_to_build

    in_pt = accepted_nothing_to_build(number=OBSERVED_N, language="pt-BR")
    in_en = accepted_nothing_to_build(number=OBSERVED_N, language="en")
    assert in_pt and in_en and in_pt != in_en
    assert in_en in en, "the chat composed its own sentence instead of the shared one"
    assert str(OBSERVED_N) in in_pt and str(OBSERVED_N) in in_en


# ── 5. no door can route around it: the sink asks whether a PERSON asked ─────────────────────────

def test_break_down_cannot_be_called_without_saying_WHO_wanted_it(origin, monkeypatch):
    """The structural half. A new call site that forgets the rule does not file work quietly — it
    fails on its first run, by name."""
    mod, _h, _t = _module(origin, monkeypatch)
    parameter = inspect.signature(mod.break_down).parameters["asked_for"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty, (
        "`asked_for` has a default, so a caller can stay silent about whether a person asked — "
        "and silence is how the automatic chain reached a reading of the code")
    with pytest.raises(TypeError):
        mod.break_down(OBSERVED_N, actor=ADMIN)


def test_a_door_that_FORGETS_the_flag_is_still_stopped_at_the_sink(origin, monkeypatch):
    """An older panel against a newer worker, or the next call site: the breakdown nobody asked
    for is refused where the spend happens, not only where today's two doors decide."""
    mod, harness, tracker = _module(origin, monkeypatch)
    assert mod.accept(OBSERVED_N, actor=ADMIN).ok

    (result,) = mod.break_down(OBSERVED_N, actor=ADMIN, asked_for=False)

    assert harness.prompts == [] and tracker.created == []
    assert result.nothing_to_build is True
    # NOT `ok`: a caller that has never heard of the field — an older panel reading this worker —
    # counts every `ok` row as a card, and would announce "Work filed: ?" about nothing. As a
    # non-card carrying a sentence, the same caller prints why, and how to ask.
    assert result.ok is False and not result.ref
    assert "already does" in result.detail and "broken into tasks" in result.detail


def test_and_the_chat_reads_that_answer_as_NOTHING_TO_BUILD_not_as_a_card(origin, monkeypatch):
    """The same backstop, one layer up: a module that did not flag its acceptance (a double, an
    older build) still ends in the right sentence, never in "became 1 task"."""
    mod, harness, _t = _module(origin, monkeypatch)
    assert mod.accept(OBSERVED_N, actor=ADMIN).ok

    said = confirm_mod._also_broke_it_down(mod, OBSERVED_N, ADMIN, "Agreed.", "en", mod.project)

    assert harness.prompts == []
    assert "nothing to build" in said.lower(), said
    assert "backlog" not in said.lower(), said
    # A DECISION, NOT A FAILURE. Without its own branch this answer falls into the executor's
    # "Ainda não consegui transformar isso em frentes de trabalho…", with the right sentence
    # quoted inside the wrong one and an offer to "try again" at something that did not fail.
    assert "consegui" not in said.lower() and "tento de novo" not in said.lower(), said


# ── 6. …and a person who ASKS still gets the breakdown ───────────────────────────────────────────

def test_an_EXPLICIT_request_breaks_an_accepted_reading_down(origin, monkeypatch):
    """The person edited the text into something the code does not do yet. The factory cannot see
    that — the evidence line is still there — so the way through is a person saying so."""
    mod, harness, tracker = _module(origin, monkeypatch)
    assert mod.accept(OBSERVED_N, actor=ADMIN).ok

    results = mod.break_down(OBSERVED_N, actor=ADMIN, asked_for=True)

    assert len(harness.prompts) == 1 and tracker.created == ["Gerar o pacote de fecho"]
    assert [r.ok for r in results] == [True] and not results[0].nothing_to_build


def test_the_chat_s_own_gesture_IS_an_explicit_request(origin, monkeypatch):
    """`quebra o requisito N` typed by a person, through the real intent branch."""
    import openfactory.product.channel as pc
    from openfactory.memory import transcript

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    mod, harness, tracker = _module(origin, monkeypatch, language="pt-BR")
    assert mod.accept(OBSERVED_N, actor=ADMIN).ok

    pc.handle(mod.project, text=f"quebra o requisito {OBSERVED_N} em tarefas", user=ADMIN,
              thread="C1", channel="C1", module=mod)

    assert len(harness.prompts) == 1, "a person asked for the breakdown and did not get one"
    assert tracker.created == ["Gerar o pacote de fecho"]


def test_the_catalog_has_the_explicit_door_and_it_SAYS_a_person_asked(origin, monkeypatch, engine):
    """The panel and the CLI have no chat to type the gesture into; this is their way through."""
    mod, _h, _t = _module(origin, monkeypatch)
    _through_the_catalog(mod, monkeypatch)
    assert mod.accept(OBSERVED_N, actor=ADMIN).ok

    from openfactory import actions

    row = actions.CATALOG["product_break_down"]
    out = asyncio.run(row.run(project="books", number=str(OBSERVED_N), by=_panel_actor(),
                              yes=True))

    assert out.ok, out.message
    ((name, inp),) = engine.started
    assert name == "ProductBreakdownWorkflow" and inp.number == OBSERVED_N
    assert inp.asked_for is True, "the explicit door reached the worker as the automatic chain"
    assert "books#41" in out.message


def test_the_explicit_door_needs_YES_and_a_PROMISE(origin, monkeypatch, engine):
    mod, _h, _t = _module(origin, monkeypatch)
    _through_the_catalog(mod, monkeypatch)

    no_yes = asyncio.run(catalog._product_break_down(project="books", number=str(OBSERVED_N),
                                                     by=_panel_actor()))
    assert not no_yes.ok and engine.started == []

    # still `observed`: nobody confirmed it, so there is no promise to build from
    unconfirmed = asyncio.run(catalog._product_break_down(
        project="books", number=str(OBSERVED_N), by=_panel_actor(), yes=True))
    assert not unconfirmed.ok and engine.started == [], unconfirmed.message


def test_the_explicit_door_refuses_somebody_who_may_not_act_BEFORE_any_engine(
        origin, monkeypatch, engine):
    mod, _h, _t = _module(origin, monkeypatch)
    _through_the_catalog(mod, monkeypatch)
    assert mod.accept(OBSERVED_N, actor=ADMIN).ok
    outsider = Actor(id="U0RANDOM", display="Somebody", via="api", admin=True)

    out = asyncio.run(catalog._product_break_down(project="books", number=str(OBSERVED_N),
                                                  by=outsider, yes=True))

    assert not out.ok and out.code == "denied" and engine.started == []


def test_the_explicit_door_says_NOTHING_WAS_FILED_when_nothing_was(origin, monkeypatch):
    """A person asked, so unlike the acceptance there is no agreement to fall back on: a worker
    that did not answer, and a breakdown that filed nothing, are refusals that say so."""
    mod, _h, _t = _module(origin, monkeypatch)
    _through_the_catalog(mod, monkeypatch)
    assert mod.accept(OBSERVED_N, actor=ADMIN).ok

    async def _down():
        raise RuntimeError("the engine is not answering")

    monkeypatch.setattr(catalog, "_connected", _down)
    down = asyncio.run(catalog._product_break_down(project="books", number=str(OBSERVED_N),
                                                   by=_panel_actor(), yes=True))
    assert not down.ok and "nothing was filed" in down.message
    assert "not answering" in down.message, "the refusal does not carry the cause"

    class _Refusing:
        async def execute_workflow(self, *_a, **_k):
            return [{"ok": False, "ref": "", "url": "", "existed": False,
                     "detail": "the board refused the card."}]

    async def _up():
        return _Refusing(), None

    monkeypatch.setattr(catalog, "_connected", _up)
    none = asyncio.run(catalog._product_break_down(project="books", number=str(OBSERVED_N),
                                                   by=_panel_actor(), yes=True))
    assert not none.ok and none.message.endswith("the board refused the card."), none.message


def test_the_sentence_is_one_a_CLIENT_can_read_in_both_languages():
    from openfactory.product.voice import jargon_in, nothing_to_build

    for lang in ("pt-BR", "en"):
        assert jargon_in(nothing_to_build(number=12, language=lang)) == []


def test_the_WORKER_hands_the_module_what_the_door_said(monkeypatch):
    """The flag crosses a process boundary inside a pydantic model; a default on the far side that
    quietly answered True would turn every automatic chain into an explicit request."""
    from openfactory.runtime.temporal import activities
    from openfactory.runtime.temporal.io import ProductBreakdownInput

    assert ProductBreakdownInput(project="books", number=3).asked_for is False

    seen: list[bool] = []

    class _Module:
        def __init__(self, *_a, **_k):
            pass

        def break_down(self, number, *, actor, asked_for):
            seen.append(asked_for)
            return []

    monkeypatch.setattr("openfactory.product.module.ProductModule", _Module)
    monkeypatch.setattr(activities, "ProjectRegistry",
                        lambda: type("_R", (), {"get": lambda _s, _n: object()})())
    # THROUGH THE ACTIVITY ITSELF, which is where the field leaves the model: a call that forgot
    # `inp.asked_for` would pass every case that starts one layer down.
    for said in (False, True):
        asyncio.run(activities.product_role_break_down(
            ProductBreakdownInput(project="books", number=3, actor=ADMIN, asked_for=said)))

    assert seen == [False, True]


def test_the_command_line_NAMES_the_way_through(monkeypatch):
    """"Ask for it to be broken into tasks" is a sentence; on a shell it has to be a command."""
    from typer.testing import CliRunner

    from openfactory import cli
    from openfactory.actions.base import done

    asked: list[tuple[str, dict]] = []

    def _perform(name, **params):
        asked.append((name, params))
        return done("Agreed.", number=12, nothing_to_build=name == "product_accept")

    monkeypatch.setattr(cli, "_perform", _perform)
    runner = CliRunner()

    accepted = runner.invoke(cli.app, ["product", "accept", "books", "12", "--yes"])
    assert accepted.exit_code == 0, accepted.output
    assert "openfactory product break-down books 12 --yes" in accepted.output

    broken = runner.invoke(cli.app, ["product", "break-down", "books", "12", "--yes"])
    assert broken.exit_code == 0, broken.output
    assert asked[-1] == ("product_break_down", {"project": "books", "number": "12", "yes": True})
    assert "break-down" not in broken.output, "the hint is printed where nothing was withheld"


# ── 7. the page learns it from the server ───────────────────────────────────────────────────────

def test_the_requirements_row_carries_the_servers_own_verdict(origin, monkeypatch):
    mod, _h, _t = _module(origin, monkeypatch)
    _through_the_catalog(mod, monkeypatch)

    out = asyncio.run(catalog._product_requirements(project="books", by=_panel_actor()))

    rows = {r["number"]: r for r in out.data["requirements"]}
    assert rows[OBSERVED_N]["came_from_the_code"] is True
    assert rows[OBSERVED_N]["evidence"] == TESTED and rows[OBSERVED_N]["observed_at"] == COMMIT
    assert rows[AUTHORED]["came_from_the_code"] is False


_PANEL = Path(__file__).resolve().parents[1] / "openfactory" / "api" / "panel.html"


def _js(name: str) -> str:
    """One function of the page, comments stripped — so a sentence ABOUT the old dialog, kept in a
    comment beside the new one, cannot satisfy or fail a case (CONTRIBUTING: a guard reads the
    thing)."""
    import re

    source = _PANEL.read_text(encoding="utf-8")
    start = source.index(f"function {name}(")
    if source[:start].endswith("async "):
        start -= len("async ")
    depth, i = 0, source.index("{", start)
    for j in range(i, len(source)):
        depth += {"{": 1, "}": -1}.get(source[j], 0)
        if depth == 0:
            body = source[start:j + 1]
            break
    return re.sub(r"^\s*//.*$", "", body, flags=re.MULTILINE)


def test_the_dialog_decides_on_the_SERVERS_field_and_not_on_a_status_of_its_own():
    """The half that runs on a machine without node. Comments are stripped first, so the paragraph
    above the function — which names the field — cannot pass this for it."""
    code = _js("acceptRequirement")

    assert "row.came_from_the_code" in code, "the dialog no longer reads the server's verdict"
    assert "status" not in code, (
        "the dialog derives its own idea of what an acceptance does from the status — which "
        "agrees with the server today and drifts the day the rule learns something new")
    assert '"product_accept"' in code


def test_the_confirm_dialog_is_run_for_BOTH_kinds_and_promises_work_only_for_one():
    """The dialog is EXECUTED, in node, with `confirm` captured: what a person reads before the
    click, for a row the server marked and for one it did not."""
    import json
    import shutil

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed — the dialog is only proven where it can be run")
    script = f"""
      const asked=[];
      globalThis.confirm=(text)=>{{asked.push(text);return false}};
      globalThis._prod={{project:"books",reqs:[
        {{number:{OBSERVED_N},came_from_the_code:true}},{{number:{AUTHORED},came_from_the_code:false}}]}};
      {_js("acceptRequirement")}
      (async()=>{{await acceptRequirement({OBSERVED_N});await acceptRequirement("{AUTHORED}");
                 console.log(JSON.stringify(asked))}})();
    """
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-1500:]
    observed, authored = json.loads(done.stdout.strip().splitlines()[-1])

    assert "no work is filed" in observed.lower() and "already does" in observed.lower(), observed
    assert "filed onto the board" not in observed.lower(), observed
    assert "work is filed onto the board" in authored.lower(), authored
    assert "already does" not in authored.lower() and "no work" not in authored.lower(), authored
