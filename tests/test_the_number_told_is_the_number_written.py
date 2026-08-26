"""The requirement number a client is told is the one that was WRITTEN, never the one predicted.

Board #14 filed this as cosmetic — *"a prévia pode divergir do número cunhado"* — and it is not.
The preview is never shown to anybody: it is staged with the pending draft and then, after the
write, handed to `written_up` as the number that exists. So a prediction became an assertion.

The two disagree for a real and recurring reason. `_next_number` derives from the base corpus;
`propose_requirement` mints against the base AND the unlanded `req/*` branches, adopting a number a
prior attempt already pushed or stepping past a rival's. A proposal pushed but never merged — which
is exactly what a failed `pr create` leaves behind until the weekly sweep rescues it — makes them
differ by one.

The client is then told *"o requisito 7 está registrado"* about a file called `0008-…md`, and their
next sentence is `aceita o requisito 7`, which finds nothing. The number is the handle: it is how
every subsequent gesture on this surface names the thing.

The fix is the rule this codebase keeps relearning: **the act reports its own outcome.** A
prediction is a fine thing to compute and a terrible thing to state as fact.
"""

from __future__ import annotations

import pytest

import openfactory.product.channel as pc
from openfactory.product.authoring import WriteResult


class _Draft:
    title = "Portal do cliente"
    must_be_true = ["abre"]
    conflicts: list = []
    supersedes: list = []


class _Answer:
    ok = True
    draft = _Draft()
    error = ""


class _Product:
    def __init__(self):
        self.admins = ["UADM"]
        self.agent_name, self.docs_repo, self.channel_id = "Nina", "a/docs", "C1"
        self.enabled, self.docs_branch, self.staging_url = True, "main", ""


class _Project:
    name, language = "books", "pt-BR"

    def __init__(self):
        self.product = _Product()


class _Module:
    def __init__(self, result):
        self._result = result

    def propose(self, _answer, *, actor, asked_by="", date="", source=""):
        return self._result

    def confirmed(self, *_a, **_k):
        return "neither"

    def context(self):
        from types import SimpleNamespace

        class _Corpus:
            requirements: list = []

            def by_number(self, _n):
                return None

        return SimpleNamespace(available=True, corpus=_Corpus(), reason="")


@pytest.fixture(autouse=True)
def _clean_stage(monkeypatch):
    # THE STATE LIVES IN `openfactory/product/staging.py` NOW (#98 slice 3), so isolation is
    # applied THERE. Rebinding the re-export on `product_channel` would leave the code
    # reading the original dict: the fixture would look like it isolates and would not,
    # which is how a staged proposal leaked into the next test when this move was first
    # attempted — with the symptom landing far from the cause.
    from openfactory.product import staging as _staging
    monkeypatch.setattr(_staging, "_PENDING", {})
    monkeypatch.setattr(_staging, "_EXPIRED_TOMBSTONES", {})
    from openfactory.memory import transcript

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    yield


def _confirm(result, *, staged_number=7):
    """Stage a draft carrying the PREDICTED number, then confirm it."""
    pc.remember("C1", {"kind": "draft", "answer": _Answer(), "asked_by": "<@UADM>",
                       "date": "2026-07-31", "source": "", "channel": "C1",
                       "number": staged_number})
    return pc.handle(_Project(), text="sim", user="UADM", thread="C1", channel="C1",
                     module=_Module(result))


def test_the_client_hears_the_number_the_WRITE_minted():
    """The incident: the base mints 7, an unlanded branch already claims it, the file becomes 8 —
    and the client was told 7."""
    said = _confirm(WriteResult(ok=True, url="u", ref="req/0008-portal", merged=True, number=8),
                    staged_number=7)

    assert "8" in said, f"the client was told the predicted number: {said}"
    assert "requisito 7" not in said, said


def test_the_ordinary_case_still_reads_exactly_as_it_did():
    """When nothing moved, the prediction and the mint agree — and this must not have grown any
    new ceremony for the case that is almost always true."""
    said = _confirm(WriteResult(ok=True, url="u", ref="req/0007-portal", merged=True, number=7),
                    staged_number=7)

    assert "7" in said, said


def test_a_result_carrying_NO_number_falls_back_and_never_says_zero():
    """The staged value stays as a fallback for a result that carries none — never as a correction
    of one that does. Saying "requisito 0" would be a handle that names nothing."""
    said = _confirm(WriteResult(ok=True, url="u", ref="req/0007-portal", merged=True),
                    staged_number=7)

    assert "7" in said, said
    assert "requisito 0" not in said, said


def test_the_write_CARRIES_the_number_it_minted():
    """Structural: `propose_requirement` decides the number — adopting a prior attempt's or
    stepping past a rival's — and it is the only thing that knows. A success that does not carry it
    forces the caller back to the prediction, which is the whole defect."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("openfactory/product/authoring.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "propose_requirement")

    successes = [
        ast.unparse(n) for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "WriteResult"
        and any(k.arg == "ok" and getattr(k.value, "value", None) is True for k in n.keywords)
    ]
    assert successes, "no success path found — the test is looking at the wrong function"
    for call in successes:
        assert "number=" in call, f"a successful write does not say what it minted: {call}"
