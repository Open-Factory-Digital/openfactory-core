"""The judge verdicts are read as EXACT tokens, and the lexical gate speaks one language.

Three gates decide whether the platform writes irreversibly in a client's name, and all three must
fail only in the cheap direction (ADR-0028/0029: ambiguity costs a question, never a write):

  1. `judge_confirmation` — its first parse scanned the model's COMPLETE final message for each
     verdict as a SUBSTRING, `approve` first, so "neither — this wasn't approved yet" parsed as
     an approval and opened the write the model explicitly refused.
  2. `judge_acceptance` — same class: "they didn't say it worked — neither" contains "worked",
     so a verbose refusal fabricated a client sign-off.
  3. `followup.acceptance_verdict` — its denial list carried English `no`, which is ALSO the
     Portuguese contraction em+o, so "sim, resolveu no sistema" closed a delivery as REJECTED
     against a client who had just accepted it.

Every test here drives the PRODUCTION parse path — the judge methods through a fake harness at
the `agent.ask()` seam, the lexical gate through `acceptance_verdict` — with the verbose replies
models actually produce. Each fails if the substring scan or the `\\bno\\b` token comes back.
"""

from __future__ import annotations

import re

import pytest

from openfactory.contracts import AgentRunResult
from openfactory.product import followup
from openfactory.product.role import ProductRole

# ── the seam: a harness that answers with a canned final message ───────────────────────────────


class _Harness:
    name = "recording"

    def __init__(self, answer: str = "", ok: bool = True) -> None:
        self.answer = answer
        self.ok = ok
        self.prompts: list[str] = []

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        return AgentRunResult(ok=self.ok, summary=self.answer)


class _Sandbox:
    def run(self, **kw):
        return 0, ""


def _ws():
    from openfactory.adapters.sandbox.base import Workspace

    return Workspace(path="/tmp", branch="main", base_branch="main")


def _confirm(answer: str, ok: bool = True) -> str:
    role = ProductRole(_Harness(answer, ok))
    return role.judge_confirmation(sandbox=_Sandbox(), workspace=_ws(),
                                   reply="sim", proposal="registrar o requisito 3")


def _accept(answer: str, ok: bool = True) -> str:
    role = ProductRole(_Harness(answer, ok))
    return role.judge_acceptance(sandbox=_Sandbox(), workspace=_ws(),
                                 reply="ok", delivered="requisito 7")


# ── 1. judge_confirmation: a verbose verdict must never open a write ───────────────────────────

@pytest.mark.parametrize("reply", [
    # each of these CONTAINS "approve" and none of them approves — under the substring scan
    # every one returned `approve` and executed a write in the client's name
    "neither — this wasn't approved yet",
    "reject: they have not approved it as-is",
    "I cannot approve this",
    "disapprove",
    "approve? I don't think they agreed",
    "they want the deadline changed before it is approved, so reject",
])
def test_a_verbose_reply_containing_approve_never_approves(reply):
    assert _confirm(reply) != "approve", reply


@pytest.mark.parametrize("reply", [
    "neither — this wasn't approved yet",
    "I cannot approve this",
    "disapprove",
    "approve? I don't think they agreed",
])
def test_an_ambiguous_confirmation_verdict_falls_to_neither(reply):
    """`reject` also consumes the staged proposal, so ambiguity may not fall there either —
    anything that is not an exact verdict leaves the proposal pending."""
    assert _confirm(reply) == "neither", reply


def test_two_lines_that_both_parse_but_disagree_are_ambiguity():
    assert _confirm("approve\nneither") == "neither"


@pytest.mark.parametrize(("reply", "expected"), [
    ("approve", "approve"),
    ("Approve.", "approve"),
    ("**approve**", "approve"),
    ("`neither`", "neither"),
    ("reject", "reject"),
    # verdict alone on its final line, after the reasoning the prompt told it not to write
    ("They agreed without conditions.\n\napprove", "approve"),
    # verdict first, parenthetical after — the word still stands alone on its line
    ("approve\n(they said pode registrar)", "approve"),
])
def test_a_compliant_confirmation_verdict_still_parses(reply, expected):
    assert _confirm(reply) == expected, reply


def test_a_failed_confirmation_judgment_leaves_the_proposal_pending():
    assert _confirm("", ok=False) == "neither"
    assert _confirm("   ") == "neither"


# ── 2. judge_acceptance: a verbose verdict must never fabricate a sign-off ─────────────────────

@pytest.mark.parametrize("reply", [
    # each CONTAINS "worked" without the literal "did-not-work" — under the scan each one closed
    # the delivery as a client sign-off nobody gave (the claim ADR-0021 forbids fabricating)
    "they didn't say it worked — neither",
    "not-worked",
    "it worked? I doubt it — neither",
    "I would not say it worked",
])
def test_a_verbose_reply_containing_worked_never_signs_off(reply):
    assert _accept(reply) == "neither", reply


@pytest.mark.parametrize(("reply", "expected"), [
    ("worked", "worked"),
    ("did-not-work", "did-not-work"),
    # the honest hyphen-free spelling of the same verdict
    ("did not work", "did-not-work"),
    ("The client only acknowledged.\nneither", "neither"),
    ("They said sim, resolveu.\n\nworked", "worked"),
])
def test_a_compliant_acceptance_verdict_still_parses(reply, expected):
    assert _accept(reply) == expected, reply


def test_a_failed_acceptance_judgment_leaves_the_delivery_open():
    assert _accept("", ok=False) == "neither"
    assert _accept("   ") == "neither"


# ── 3. the prompt and the parse agree ──────────────────────────────────────────────────────────

def test_the_confirmation_prompt_demands_the_exact_words_the_parse_accepts():
    """The parse only reads `approve`/`reject`/`neither`, so the prompt must ask for exactly
    those words — a verdict renamed on one side of this seam silently biases every answer."""
    role = ProductRole(h := _Harness("neither"))
    role.judge_confirmation(sandbox=_Sandbox(), workspace=_ws(), reply="r", proposal="p")
    prompt = h.prompts[0]
    assert "exactly one" in prompt
    for word in ("approve", "reject", "neither"):
        assert word in prompt, word


def test_the_acceptance_prompt_demands_the_exact_words_the_parse_accepts():
    role = ProductRole(h := _Harness("neither"))
    role.judge_acceptance(sandbox=_Sandbox(), workspace=_ws(), reply="r", delivered="d")
    prompt = h.prompts[0]
    assert "exactly one" in prompt
    for word in ("worked", "did-not-work", "neither"):
        assert word in prompt, word


# ── 4. the lexical gate: one token, one language ───────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    # the Portuguese contraction em+o, one of the most common words in pt-BR — English \bno\b
    # in the denial list read every one of these acceptances as a rejection
    "sim, resolveu no sistema",
    "funcionou no celular",
    "resolveu no caso da folha",
])
def test_an_acceptance_with_a_portuguese_locative_no_is_still_an_acceptance(text):
    assert followup.acceptance_verdict(text) == "worked", text


def test_a_bare_english_no_is_ambiguous_and_falls_to_the_judge():
    """One token, two languages, two opposite meanings — so it decides nothing by itself.
    "" routes the reply to the model judge; a closed verdict here would be a guess."""
    assert followup.acceptance_verdict("no") == ""


@pytest.mark.parametrize("text", [
    # real denials keep denying without the ambiguous token
    "não resolveu",
    "nao funcionou",
    "no, ainda quebra",
    "still broken",
    "nope",
])
def test_a_real_denial_still_closes_as_did_not_work(text):
    assert followup.acceptance_verdict(text) == "did-not-work", text


#: Words common enough in pt-BR that reading one as an English verdict token would misjudge
#: everyday sentences — the class English `no` belonged to. None may appear as a bare
#: alternation token in EITHER lexical gate; a new token that is a word in both languages
#: must go to the model judge instead.
_PT_FUNCTION_WORDS = {
    "no", "nos", "na", "nas", "o", "os", "a", "as", "e", "é", "em", "um", "uma",
    "de", "da", "do", "das", "dos", "que", "se", "por", "com", "para", "nada",
}


def _alternation_tokens(rx: re.Pattern) -> set[str]:
    body = re.search(r"\((.*)\)", rx.pattern, re.S)
    assert body, "the gate regex is no longer a single alternation — re-audit this guard"
    return {t.strip().lower() for t in body.group(1).split("|")}


@pytest.mark.parametrize("rx", [followup._DID_NOT_WORK, followup._WORKED_CORE],
                         ids=["did-not-work", "worked"])
def test_no_gate_token_collides_with_a_common_portuguese_word(rx):
    collisions = _alternation_tokens(rx) & _PT_FUNCTION_WORDS
    assert not collisions, (
        f"{sorted(collisions)} mean different things in English and pt-BR — an everyday "
        f"sentence would close a delivery on a preposition. Ambiguity goes to the judge.")
