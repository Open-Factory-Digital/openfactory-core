"""She may not tell a client she cannot see without having tried to look.

Seven consecutive mounts on 2026-07-31 logged `entries=2 docs_entries=2 code_entries=33`, not one
of them empty, and inside that same window she wrote to the client "o que está montado para mim
veio vazio" — once four minutes after having read and transcribed a requirement out of that very
mount. The platform is ruled out by measurement, so what remains is a sentence about her own
environment that nothing in her prompt required her to earn.

ASSERTED AGAINST THE PROMPT AN OPERATION ACTUALLY SENDS, never against `_sources_section()` alone:
a section that stopped being composed into `_prompt` would leave every one of those unit-level
assertions green while the model saw none of it — the defect class this codebase keeps paying for.
"""

from __future__ import annotations

from openfactory.contracts import AgentRunResult
from openfactory.product.role import ProductRole


class _Harness:
    name = "recording"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        return AgentRunResult(ok=True, summary="ok")


class _Sandbox:
    def run(self, **kw):
        return 0, ""


def _ws():
    from openfactory.adapters.sandbox.base import Workspace

    return Workspace(path="/tmp", branch="main", base_branch="main")


def _asked(mounted: dict[str, str]) -> str:
    """The prompt a real client message produces, mounted exactly as `module.mounted()` reports."""
    harness = _Harness()
    role = ProductRole(harness, mounted=mounted)
    role.answer(sandbox=_Sandbox(), workspace=_ws(),
                question="o requisito 4 ficou como a gente combinou?")
    return harness.prompts[0]


_MOUNTED = {"docs": "documentation", "code": "code"}
_DOCS_ONLY = {"docs": ".", "code": ""}


def test_saying_she_cannot_read_is_a_claim_she_has_to_earn():
    """The rule that stops the false sentence: an attempt she can name, or no claim at all."""
    prompt = _asked(_MOUNTED)
    assert "earn it by trying" in prompt
    assert "empty, missing or unreadable" in prompt
    assert "the path you opened and what came back" in prompt


def test_the_rule_survives_the_mount_state_it_was_never_about():
    """Every observed occurrence happened with the code MOUNTED, so a rule that lived only in the
    degraded branch would have caught none of them — and the degraded branch is where generalising
    from one missing thing to "all of it came empty" is most tempting."""
    prompt = _asked(_DOCS_ONLY)
    assert "earn it by trying" in prompt
    # the one statement she does NOT have to verify stays measured rather than guessed
    assert "NOT the source code" in prompt


def test_two_links_and_no_files_is_named_as_a_healthy_mount():
    """What she lands on: a root holding `documentation` and `code` as symlinks and nothing else.
    Two odd entries and no files is exactly the listing she read as an absence, so the prompt says
    what that shape means instead of leaving her to interpret it."""
    prompt = _asked(_MOUNTED)
    assert "HEALTHY mount" in prompt
    assert "one level in" in prompt


def test_the_rule_is_not_confined_to_the_conversational_reply():
    """`_sources_section` is unconditional in `_prompt` and must stay so: a survey that concluded
    "the code directory is empty" writes that reading into a baseline nobody re-checks."""
    harness = _Harness()
    role = ProductRole(harness, mounted=_MOUNTED)
    role.draft(sandbox=_Sandbox(), workspace=_ws(),
               request="preciso que a conciliação rode sozinha todo dia 5")
    assert "earn it by trying" in harness.prompts[0]


def test_the_client_is_still_never_handed_the_machinery():
    """The previous fix, re-asserted where it lives: a product owner who asks an accounting client
    to restore her access has broken the no-developer promise in one sentence."""
    prompt = _asked(_DOCS_ONLY)
    assert "Do NOT ask the person to restore your access" in prompt
    assert "do not describe how you are assembled" in prompt
