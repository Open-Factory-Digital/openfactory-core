"""A failure explains itself without leaking machinery — ADR-0030.

`WriteResult.detail` is written for whoever reads it, and BOTH the team's log and the CLIENT'S
CHANNEL read it. Four `return result.detail` branches in the handler sent it straight into a
business conversation, so a git stderr, a repo slug, a branch name, a file path or an exception
class reached the person who runs an accounting firm.

That is the "two facts sharing one value" class again — one field serving two audiences with
opposite needs. Sanitised at the BOUNDARY rather than at every raise site: there are a dozen of
those and one of this, and the raw text is not lost, only relocated to the log where it belongs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from openfactory.product.voice import client_safe_detail

#: Real failure details this codebase produces, from the actual raise sites.
_MACHINERY = [
    "could not clone a/b: fatal: repository not found",
    "could not file 'Editar': requirements/0007-immutable.md already exists",
    "não consegui registrar (CalledProcessError: gh: HTTP 403)",
    "could not create req/0012: refs/heads/req/0012 exists",
    "não consegui anotar (FileNotFoundError: /tmp/openfactory-x/domain.yaml)",
    "gh: Resource not accessible by integration (HTTP 403)",
    "Traceback (most recent call last): ...",
    "remote: Permission to AcmeCorp/x.git denied",
]

#: Details that ARE explanations a person can act on — these must survive untouched, or the fix
#: replaces useful answers with a generic apology and the client learns nothing.
_ACTIONABLE = [
    "já tenho isto anotado sobre 'erp' (por rob): a firma usa Primavera",
    "o quadro recusou a movimentação",
    "já existe um requisito com esse título",
    "o levantamento já tinha sido proposto",
]


@pytest.mark.parametrize("detail", _MACHINERY)
def test_machinery_never_reaches_the_client(detail):
    safe, raw = client_safe_detail(detail, language="pt-BR")

    assert raw == detail, "the diagnosis was dropped instead of relocated to the log"
    assert safe != detail, f"machinery went to the client verbatim: {detail}"
    for leak in ("fatal:", "http", "refs/", "traceback", ".git", "gh:", "remote:", "error"):
        assert leak not in safe.lower(), f"{leak!r} survived in {safe!r}"


@pytest.mark.parametrize("detail", _ACTIONABLE)
def test_an_actionable_explanation_survives_untouched(detail):
    """The other half of the requirement. A sanitiser that swallows real answers is worse than the
    leak: the client is told "something went wrong" when the truth was "you already told me that"."""
    safe, raw = client_safe_detail(detail, language="pt-BR")

    assert safe == detail, f"a useful explanation was replaced: {detail}"
    assert raw == "", "an actionable detail was logged as a leak"


def test_the_client_message_says_whose_fault_it_is():
    """A person who is told "could not record" reasonably assumes they typed something wrong. They
    did not, and being told so is the difference between a bug report and a wasted hour."""
    safe, _ = client_safe_detail("fatal: repository not found", language="pt-BR")

    assert "do meu lado" in safe, safe
    assert "time já foi avisado" in safe or "time" in safe, safe


#: Functions that are themselves the sanitising boundary — every `detail` they receive goes
#: through `_client_detail` before any of it is returned. Named here rather than pattern-matched,
#: and each one is PROVEN to sanitise by the test below: a whitelist nobody re-checks is how a
#: guard becomes a formality, and this one only has to be wrong once.
_SANITISERS = ("_client_detail", "_still_to_say")

#: WHERE A `WriteResult.detail` CAN BE TURNED INTO A SENTENCE. The confirmation executor moved to
#: the core (#105) and took the sanitising boundary with it, while the typed intents kept composing
#: on the channel — so both files are scanned. Scanning only one is how this guard would keep
#: passing while every branch it was written for lived somewhere else.
_COMPOSING_FILES = ("openfactory/product/channel.py", "openfactory/product/confirm.py")


def _composing_tree() -> ast.Module:
    merged = ast.Module(body=[], type_ignores=[])
    for path in _COMPOSING_FILES:
        body = ast.parse(Path(path).read_text()).body
        assert any(isinstance(n, ast.FunctionDef) for n in body), (
            f"{path} contributed no functions — the leak scan is reading half the code")
        merged.body.extend(body)
    return merged


def test_every_named_sanitiser_really_sanitises():
    """The whitelist above is only safe while it is true. If `_still_to_say` ever stops routing
    through `_client_detail`, the structural guard below would wave through exactly the leak it
    exists to catch — so the exemption is re-derived from the source on every run."""
    tree = _composing_tree()
    for name in _SANITISERS:
        if name == "_client_detail":
            continue  # the boundary itself
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == name), None)
        assert fn is not None, f"{name} is exempted from the leak guard and does not exist"
        calls = {getattr(c.func, "id", "") for c in ast.walk(fn) if isinstance(c, ast.Call)}
        assert "_client_detail" in calls, (
            f"{name} is trusted to sanitise and does not call `_client_detail` — the exemption "
            f"would let a git error into a client's channel")


def test_NO_handler_branch_returns_a_raw_detail():
    """The structural half. Four branches did, and a test fixing three of them would pass the day
    somebody adds a fifth — so the assertion is over every branch in the file."""
    tree = _composing_tree()
    raw_returns = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        for sub in ast.walk(node.value):
            # `return X.detail` — a bare attribute access with no sanitiser around it
            if isinstance(sub, ast.Attribute) and sub.attr == "detail":
                text = ast.unparse(node.value)
                if not any(s in text for s in _SANITISERS):
                    raw_returns.append((node.lineno, text[:70]))
    assert not raw_returns, (
        "these return a WriteResult detail straight to the client:\n  "
        + "\n  ".join(f"line {n}: {t}" for n, t in raw_returns))
