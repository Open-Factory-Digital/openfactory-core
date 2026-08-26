"""Three defects in one message the pilot could not parse (2026-08-16).

He dragged `#89 feat(billing): validate real Stripe checkout end-to-end in staging` — a ticket
asking for a VERIFICATION in staging, not a code change. The agent ran, changed nothing, and the
channel said:

    ⏸ #89 parou e precisa de vocês @solo-dev
    job errored after retries: ApplicationError: RuntimeError: gh pr create failed: pull request
    create failed: GraphQL: No commits between main and openfactory/89 (createPullReque…
    Isso é do requisito, não da execução — mandei para o produto.
    Responda *resume #89* para tentar de novo, ou *skip #89* para liberar a fila.

His reply, in full: **"não entendi"**. Three separate defects made that the only honest reaction.

  1. THE FACT WAS DISCOVERED THREE LAYERS AWAY AND REPORTED IN THE VENDOR'S WORDS. The real event
     is "the agent finished and changed nothing" — knowable from the diff the machine had already
     read, before the review pass, the push, and the PR. Instead the branch was pushed, GitHub
     refused it, and the GraphQL error became the park note. Fixed in `orchestrator/machine.py`.

  2. "MANDEI PARA O PRODUTO" — first person, past tense — WAS AN ACTION NOBODY PERFORMS.
     `remedy_for` returns `action="product"` and every reader of `.action` tests it against
     `"retry"`; nothing routes anything anywhere. He was told a thing had happened and there was
     nothing to look at. The module already learned this on the retry path and wrote it down:
     *"once somebody learns the messages are aspirational, they stop trusting all of them."*

  3. IT OFFERED `resume` UNDER A SENTENCE EXPLAINING THAT EXECUTION WAS NEVER THE PROBLEM. A
     re-run of a mis-scoped ticket re-parks on the same blocker at full price — the classifier's
     own rule — so the message contained two instructions that contradict each other.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re

import pytest

from openfactory.techlead.classify import REQUIREMENT, classify, remedy_for


def _machine_source() -> str:
    """The one method that reads the diff, pushes the branch and opens the PR."""
    from openfactory.orchestrator import machine

    return inspect.getsource(importlib.import_module(machine.__name__))


#: The note the pilot's job actually parked with.
NOTE_89 = ("job errored after retries: ApplicationError: RuntimeError: gh pr create failed: "
           "pull request create failed: GraphQL: No commits between main and openfactory/89")


# ── 1. an empty diff is an answer, not a forge error ────────────────────────────────────────────

def test_the_machine_decides_on_the_diff_BEFORE_it_pushes():
    """The fact is in the diff the machine already read for the hygiene gate. Anchored on order:
    the empty check must come before the push, or the forge keeps being the one that notices."""
    src = _machine_source()
    assert "if not diff.strip():" in src, (
        "nothing checks for an empty diff — an agent that changed nothing is still discovered by "
        "GitHub refusing the pull request")
    # WITHIN THE SAME FUNCTION, not across the file. The first cut compared indices module-wide
    # and matched a COMMENT mentioning `publish_branch` 200 lines earlier — a guard failing on
    # correct code, which is the shape that gets guards deleted.
    at = src.index("if not diff.strip():")
    after = src[at:]
    assert "publish_branch" in after, "this function no longer pushes — the anchor moved"
    assert "open_pr(" in after, "this function no longer opens the PR — the anchor moved"


def test_the_sentence_says_what_happened_and_refuses_to_guess_WHICH():
    """The platform cannot tell "no code was needed" from "the agent found nothing to do", and
    asserting either invents the half a human is being asked for."""
    from openfactory.orchestrator import machine

    src = machine.__loader__.get_source(machine.__name__)
    block = src[src.index("if not diff.strip():"):][:900]
    assert "changed nothing" in block
    assert "Either" in block and "or what it asks for is already true" in block, (
        "the message picks one of the two explanations it cannot distinguish")
    for vendor_noise in ("GraphQL", "gh pr create", "No commits between"):
        assert vendor_noise not in block, f"the park note still speaks {vendor_noise!r}"


# ── 2. no message claims an action nobody takes ─────────────────────────────────────────────────

def test_the_requirement_remedy_stops_claiming_it_routed_anything():
    say = remedy_for(classify(NOTE_89, state="on_hold")).say
    assert "mandei" not in say.lower(), (
        f"the channel still claims, in the past tense, to have sent the ticket somewhere no code "
        f"sends it: {say!r}")
    # Rendered in English by default since #124 — the claim is about WHO must act, so it is
    # pinned in both languages rather than on one wording.
    assert "rewriting by whoever asked" in say, "it no longer names who must act"
    pt = remedy_for(classify(NOTE_89, state="on_hold"), language="pt-BR").say
    assert "reescrito por quem o pediu" in pt
    assert "mandei" not in pt.lower(), "the pt-BR entry still claims it routed the ticket"


def test_no_remedy_claims_a_FIRST_PERSON_PAST_ACTION_that_nothing_performs():
    """The class, derived from the code: `remedy_for` may only say "I did X" for an action the
    platform actually consumes. Today the sole consumed action is `retry` (the self-heal); every
    other one is advice, and advice must not be phrased as a completed act."""
    # `import openfactory.techlead.classify as mod` BINDS THE FUNCTION, not the module: the
    # package's `__init__` re-exports a name `classify`, which shadows the submodule attribute.
    # Same family as the `namespace()` TypeError this repository paid for on 2026-08-16 — a name
    # that reads like a module and is not one.
    mod = importlib.import_module("openfactory.techlead.classify")

    consumed = set()
    for module in ("openfactory.techlead.watch", "openfactory.techlead.memory",
                   "openfactory.runtime.temporal.activities",
                   "openfactory.runtime.temporal.workflow"):
        src = inspect.getsource(importlib.import_module(module))
        consumed |= set(re.findall(r'\.action\s*[!=]=\s*"(\w+)"', src))
    assert "retry" in consumed, "the self-heal no longer gates on `retry` — this guard is stale"

    #: first-person past-tense verbs a Portuguese sentence uses to report a completed act
    claimed = re.compile(r"\b(mandei|enviei|abri|criei|movi|encaminhei|deleguei)\b", re.I)
    offenders = []
    tree = ast.parse(inspect.getsource(mod.remedy_for))
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "Remedy"):
            continue
        kw = {k.arg: k.value for k in call.keywords}
        action = getattr(kw.get("action"), "value", "")
        say = getattr(kw.get("say"), "value", "") or ""
        if action not in consumed and claimed.search(say):
            offenders.append((action, say[:80]))
    assert not offenders, (
        "these remedies report a completed action for a verdict nothing acts on — the reader is "
        f"told something happened and has nowhere to look: {offenders}")


# ── 3. resume is offered only where it could work ───────────────────────────────────────────────

@pytest.mark.parametrize("note,should_offer_resume", [
    (NOTE_89, False),                                             # the ticket, not the run
    ("rate limit reached, retrying later", True),                 # transient: a re-run may finish
])
def test_the_park_announcement_offers_resume_only_when_retrying_could_help(
        note, should_offer_resume):
    """Derived from the remedy's own `action`, which is the platform's existing test for "trying
    again could help" — the same one the self-heal gates on."""
    from openfactory.runtime.temporal import workflow as wf

    src = wf.__loader__.get_source(wf.__name__)
    assert 'remedy_here.action == "retry"' in src, (
        "the announcement no longer derives the offered verbs from the remedy — it is back to "
        "offering resume for every park, including the ones where it re-parks at full price")

    remedy = remedy_for(classify(note, state="on_hold"))
    retryable = remedy.action == "retry"
    assert retryable is should_offer_resume, (
        f"{note[:40]!r} classifies as action={remedy.action!r}; the announcement would "
        f"{'offer' if retryable else 'withhold'} resume")


def test_the_two_instructions_never_contradict_each_other():
    """The pilot's actual complaint: a sentence saying the execution was never the problem, with
    "try the execution again" printed under it."""
    say = remedy_for(classify(NOTE_89, state="on_hold")).say
    assert "resume" not in say.lower(), "the remedy itself now suggests the thing it just ruled out"
    assert REQUIREMENT == classify(NOTE_89, state="on_hold").cause
