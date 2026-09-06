"""The second yes belongs to whoever asked (ADR-0047 §4) — implemented, not only recorded.

hermes, approving #67 and #69 together (2026-09-06): §4 says an admin who did not ask may accept
on the requester's behalf "only if the deployment's configuration says so; the default is the
requester" — and #69 gated on `may_act` alone, so any allowlisted admin could give the second yes
for anybody, with a sentence in the product's own voice that read as if the path were sanctioned.
Not a regression (ADR-0032 gated the same way), but a decision in the record the code did not
implement. This is the gate:

  1. the requester gives the second yes; another admin is refused by default, and told whose
     yes it is and where the rule lives — never the config key;
  2. `product.accept_on_behalf: true` lets an admin accept for the requester (and the stamp on
     the card says so, as #69 already wrote);
  3. a requirement nobody is recorded as having asked for has nobody to defer to;
  4. `stamp_acceptance` keeps the same rule, so the visible copy cannot outrun the act;
  5. a proposal result that cannot say it landed did not (the `merged` fallback is the field's
     own default, False — hermes's minor on #69).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_product_module import ADMIN, _ctx, _Harness

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product import authoring
from openfactory.product import confirm as pc_confirm
from openfactory.product.authoring import WriteResult
from openfactory.product.corpus import Corpus, Requirement
from openfactory.product.module import ProductModule, _not_the_requester

REQUESTER = "U0PO"
DOCS = "acmecorp/acme-books-documentation"


def _project(**cfg) -> Project:
    product = {"docs_repo": DOCS, "slack_admins": [ADMIN, REQUESTER], **cfg}
    return Project(name="books", language="pt-BR", repo_path="/work/books",
                   product=ProductConfig(**product))


def _module(tmp_path, monkeypatch, **cfg) -> ProductModule:
    corpus = Corpus(requirements=[Requirement(number=4, slug="x", path="requirements/0004-x.md",
                                              title="Review queue", status="proposed",
                                              asked_by=f"<@{REQUESTER}>")])
    monkeypatch.setattr(authoring, "accept_requirement",
                        lambda **kw: WriteResult(ok=True, ref=kw["path"], merged=True))
    monkeypatch.setattr(ProductModule, "_corpus_changed", lambda self, result: result)
    return ProductModule(_project(**cfg), context=_ctx(tmp_path, corpus=corpus),
                         agent=_Harness("ok"))


# ── 1-3. the act ─────────────────────────────────────────────────────────────────────────────


def test_the_requester_gives_the_second_yes(tmp_path, monkeypatch):
    assert _module(tmp_path, monkeypatch).accept(4, actor=REQUESTER).ok


def test_another_admin_is_refused_by_default_and_told_whose_yes_it_is(tmp_path, monkeypatch):
    result = _module(tmp_path, monkeypatch).accept(4, actor=ADMIN)

    assert result.ok is False
    assert f"<@{REQUESTER}>" in result.detail, "the refusal must name whose yes it is"
    assert "configuração do produto" in result.detail and "accept_on_behalf" not in result.detail


def test_the_configuration_lets_an_admin_accept_on_the_requesters_behalf(tmp_path, monkeypatch):
    assert _module(tmp_path, monkeypatch, accept_on_behalf=True).accept(4, actor=ADMIN).ok


def test_a_requirement_nobody_asked_for_has_nobody_to_defer_to():
    cfg = ProductConfig(docs_repo=DOCS)
    assert _not_the_requester(cfg, actor=ADMIN, requester="") == ""
    assert _not_the_requester(cfg, actor=ADMIN, requester="não registrado") == ""
    assert _not_the_requester(cfg, actor=ADMIN, requester=f"<@{ADMIN}>") == ""
    assert _not_the_requester(cfg, actor=ADMIN, requester=f"<@{REQUESTER}>") != ""


# ── 4. the visible copy ──────────────────────────────────────────────────────────────────────


class _Tracker:
    def __init__(self):
        self.comments: list[tuple[str, str]] = []

    def comment(self, ref, body):
        self.comments.append((ref, body))


def test_the_stamp_keeps_the_same_rule(tmp_path, monkeypatch):
    tracker = _Tracker()
    (refused,) = _module(tmp_path, monkeypatch).stamp_acceptance(
        4, ["#501"], actor=ADMIN, requester=REQUESTER, tracker=tracker)
    assert refused.ok is False and tracker.comments == []

    (stamped,) = _module(tmp_path, monkeypatch, accept_on_behalf=True).stamp_acceptance(
        4, ["#501"], actor=ADMIN, requester=REQUESTER, tracker=tracker, today="2026-09-06")
    assert stamped.ok and "em nome de" in tracker.comments[0][1]


# ── 5. merged defaults to the field's own default ────────────────────────────────────────────


def test_a_result_that_cannot_say_it_landed_opens_no_card():
    calls = []

    class _Module:
        def propose(self, answer, *, actor, asked_by="", date="", source=""):
            return SimpleNamespace(ok=True, number=7, url="")     # no `merged` at all

        def open_cards_for(self, number, *, actor):
            calls.append(number)
            return []

    entry = {"answer": SimpleNamespace(draft=SimpleNamespace(title="t")), "asked_by": "<@U1>"}
    project = SimpleNamespace(name="books", product=SimpleNamespace(agent_name=""))

    pc_confirm._confirm_draft(project, entry, module=_Module(), user="U1", lang="pt-BR")

    assert calls == [], "a result that cannot say it landed must not open a card"


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    from openfactory.memory import messages

    monkeypatch.setattr(messages, "answer", lambda *a, **k: None)
