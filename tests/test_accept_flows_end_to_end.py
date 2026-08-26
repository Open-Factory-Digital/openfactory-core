"""The acceptance chain, end to end — channel contract → `module.accept` → `accept_requirement`.

THE FLOW WAS DEAD AT EVERY LINK (sweep findings 0/1/2/5), and no test drove the production
functions: the channel decorated the actor so the module's own re-gate refused every admin; the
module handed the corpus' FILENAME to a writer that resolved it at the clone ROOT, so nothing was
found; and the writer looked for a bare `status:` no production file ever carried, then reported
"esse requisito já estava acordado" over a file still `proposed` — the exact false success the
live client received. These tests drive the real chain against a real git repository, with a real
`render_requirement` file, and the `gh`-shaped seams faked at the production boundary — never the
live CLI, which spends the deployment's GitHub App quota.

THE CONTRACT (what the channel passes): `module.accept(number, actor=<raw slack id>)`. The raw id
is what `may_act` checks against `slack_admins`; the `<@…>` mention is decoration the module
applies ITSELF, only where the human-readable record is written. Callers never pre-decorate — the
one call site that did made every channel acceptance fail its own gate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product.authoring import render_requirement
from openfactory.product.config import ProductLink
from openfactory.product.corpus import load_corpus, parse_requirement
from openfactory.product.loader import ProductContext
from openfactory.product.module import ProductModule
from openfactory.product.role import RequirementDraft

DOCS = "acmecorp/acme-books-documentation"
ADMIN = "U0BJZADMIN"


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    for key, value in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"),
                       ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(key, value)


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _rendered(number: int = 7, title: str = "Pacote de fecho") -> str:
    draft = RequirementDraft(title=title, why="o cliente fecha o mês",
                             must_be_true=["o fecho gera o pacote completo"])
    return render_requirement(draft, number=number)


@pytest.fixture
def origin(tmp_path):
    """The docs repository, seeded with REQ-0007 exactly as `propose_requirement` writes one —
    under `requirements/`, in the bullet format, status `proposed`."""
    src = tmp_path / "docs-origin"
    src.mkdir()
    _git("init", "-q", "-b", "main", cwd=src)
    _git("config", "user.email", "t@t", cwd=src)
    _git("config", "user.name", "t", cwd=src)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=src)
    (src / "requirements").mkdir()
    (src / "requirements" / "0007-pacote-de-fecho.md").write_text(_rendered())
    _git("add", "-A", cwd=src)
    _git("commit", "-qm", "seed", cwd=src)
    return src


def _module(origin, monkeypatch) -> ProductModule:
    """The production module over the real corpus loader — `Requirement.path` arrives exactly as
    production sees it (filename-only), which is the trap finding 1 is about."""
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda project, repo="", *, token=None: str(origin))
    ctx = ProductContext(
        link=ProductLink(active=True, docs_repo=DOCS, kind="ok", reason="fine"),
        corpus=load_corpus(origin / "requirements"),
        docs_path=str(origin), docs_commit="abc123", requirements_dir="requirements")
    project = Project(name="books", repo_path="/work/books",
                      product=ProductConfig(docs_repo=DOCS, admins=[ADMIN]))
    return ProductModule(project, token="", context=ctx)


def _file_on_main(origin) -> str:
    return _git("show", "main:requirements/0007-pacote-de-fecho.md", cwd=origin).stdout


# ── the whole chain works ──────────────────────────────────────────────────────────────────────
def test_an_admins_RAW_id_accepts_and_the_real_file_flips(origin, monkeypatch):
    """Channel contract in, flipped file out. Fails if the actor gate demands decoration
    (finding 0's contract), if the path resolves at the clone root (finding 1), or if the status
    writer cannot read a production file (findings 2/5)."""
    mod = _module(origin, monkeypatch)
    assert "/" not in mod.context().corpus.by_number(7).path, (
        "precondition: the corpus stores the FILENAME — the join to requirements_dir is the fix "
        "under test")

    res = mod.accept(7, actor=ADMIN)          # RAW slack id: what the channel now passes

    assert res.ok is True, res.detail
    assert res.existed is False, "a fresh acceptance was reported as a prior one"
    req, findings = parse_requirement(Path("0007-pacote-de-fecho.md"), _file_on_main(origin))
    assert req is not None and req.status == "accepted"
    assert req.is_promise, "the factory still would not defend it"
    assert ADMIN in req.asked_by, "who agreed is not in the record the parser reads back"
    assert req.date, "no acceptance date was recorded"
    assert not [f for f in findings if f.code in ("no-asker", "no-date")]


def test_the_record_is_decorated_even_though_the_gate_took_the_raw_id(origin, monkeypatch):
    """One value used to carry two identities. Split: the RAW id authorises; the `<@…>` mention is
    written — by the module itself — into the human-readable record alone."""
    mod = _module(origin, monkeypatch)
    assert mod.accept(7, actor=ADMIN).ok is True

    message = _git("log", "-1", "--format=%B", "main", cwd=origin).stdout
    assert f"<@{ADMIN}>" in message, "the commit record does not attribute the agreement"
    assert f"<@{ADMIN}>" in _file_on_main(origin)


def test_a_PRE_DECORATED_actor_is_refused_before_anything_is_written(origin, monkeypatch):
    """The contract's other edge: `may_act` is exact membership over raw ids, so a caller that
    decorates recreates the dead-accept defect. It must fail here, loudly, not in production."""
    mod = _module(origin, monkeypatch)

    res = mod.accept(7, actor=f"<@{ADMIN}>")

    assert res.ok is False
    assert "**Status:** proposed" in _file_on_main(origin), (
        "an actor that failed the gate still flipped the file")


def test_an_outsider_cannot_create_a_promise(origin, monkeypatch):
    mod = _module(origin, monkeypatch)
    res = mod.accept(7, actor="U0RANDOM")
    assert res.ok is False
    assert "**Status:** proposed" in _file_on_main(origin)


def test_a_second_accept_says_already_agreed_only_when_that_is_TRUE(origin, monkeypatch):
    """"Já estava acordado" is now reachable only from a file that really says `accepted` — the
    false version of this sentence is what the live client got over a `proposed` file."""
    assert _module(origin, monkeypatch).accept(7, actor=ADMIN).ok is True

    res = _module(origin, monkeypatch).accept(7, actor=ADMIN)

    assert res.ok is True and res.existed is True
    assert "acordado" in res.detail


def test_an_unflippable_file_is_an_ERROR_not_a_false_agreement(origin, monkeypatch):
    """Findings 2/5's poison half, at the WriteResult level: ok/existed over an unflipped file is
    the lie that told the live client a promise existed when none did."""
    (origin / "requirements" / "0009-sem-status.md").write_text(
        "# REQ-0009 — Sem status\n\ncorpo\n")
    _git("add", "-A", cwd=origin)
    _git("commit", "-qm", "seed broken", cwd=origin)

    mod = _module(origin, monkeypatch)
    res = mod.accept(9, actor=ADMIN)

    assert res.ok is False and res.existed is False
    assert "já estava" not in res.detail, "an unreadable file was reported as a prior agreement"
    assert "não consegui" in res.detail          # said to the client, in their language
    assert _git("log", "-1", "--format=%s", "main", cwd=origin).stdout.strip() == "seed broken", (
        "a commit landed for an accept that must have written nothing")
