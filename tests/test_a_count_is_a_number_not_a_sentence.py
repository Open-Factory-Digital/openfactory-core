"""The escalation stopped depending on how a sentence is worded (#124, step 1).

`#124` is a card about TRANSLATING the tech-lead's canned voice. Mapping it turned up four places
where a Portuguese string is not a message at all but a value something else MATCHES on — and this
is the one that would have failed silently and expensively:

    workflow.py            note = f"still rate-limited after {rate_resumes} auto-resumes"
    classify.py  _EXHAUSTED = re.compile(r"…after \\d+ auto-resumes?|já tentei .* e … continua")

The pause ladder knew `rate_resumes` exactly, threw it away into prose, and the classifier
recovered it with a regex over the platform's own sentence. So the escalation that stops the
factory proposing the very thing whose failure the note describes — the C-27 incident, measured
2026-08-05 — was wired to the wording. Translate either sentence and a job whose automatic
attempts are spent silently becomes one the factory retries again, at full price, for ever.

Worse, the pt-BR alternative matched `remedy_for`'s OWN output ("já tentei N tentativas e o
problema continua"), so the module could read its own voice back as evidence.

The number is data now — `RunResult.attempts_spent`, carried through the park payload the rounds
query, handed to `remedy_for` as `already_spent`. The regex survives for one reason only: a job
that parked BEFORE the field existed has a note and no number, and its escalation must keep
working. It reads only sentences the platform wrote in ENGLISH, and it must not grow.
"""

from __future__ import annotations

import inspect

import pytest

from openfactory.contracts import RunResult
from openfactory.techlead.classify import classify, remedy_for


def _remedy(note: str, *, spent: int = 0):
    return remedy_for(classify(note, state="paused"), already_spent=spent)


def test_the_number_alone_escalates():
    """The path that replaces the regex. No wording at all — just the count."""
    assert _remedy("rate limit exceeded", spent=3).action == "escalate", (
        "the automatic attempts are spent and the factory still proposes another one")


def test_no_exhaustion_still_retries():
    """The positive twin, and the one that decides whether this is a fix or a mute button: a
    genuinely fresh throttle is exactly what the factory SHOULD heal by itself."""
    assert _remedy("rate limit exceeded").action == "retry"


def test_a_job_parked_BEFORE_the_field_existed_still_escalates():
    """The legacy path, kept deliberately. A job that parked yesterday carries a note and no
    number; dropping the pattern would have made this fix a regression for every in-flight park."""
    assert _remedy("still rate-limited after 3 auto-resumes").action == "escalate"


def test_the_pattern_no_longer_recognises_the_modules_OWN_VOICE():
    """`remedy_for` emits "Já tentei N tentativas e continua"; the pattern used to match it. A
    module that reads its own output back as evidence cannot be translated, and cannot be trusted
    either — the same string arriving from anywhere would have counted."""
    from openfactory.techlead.classify import _EXHAUSTED_LEGACY

    own_voice = remedy_for(classify("boom", state="on_hold"), already_tried=99)
    for text in (own_voice.say, own_voice.reason,
                 "já tentei 2 tentativas e o problema continua"):
        assert not _EXHAUSTED_LEGACY.search(text or ""), (
            f"the classifier still recognises its own sentence as evidence: {text!r}")


def test_the_legacy_pattern_reads_only_ENGLISH_platform_notes():
    """It exists for notes the PLATFORM wrote, and the platform writes them in English. A
    Portuguese alternative here is a translation waiting to disarm it."""
    from openfactory.techlead.classify import _EXHAUSTED_LEGACY

    assert not any(ch in _EXHAUSTED_LEGACY.pattern for ch in "áàâãéêíóôõúç"), (
        "the legacy pattern grew an accented alternative — it is matching a sentence somebody "
        "will translate")


# ── the number reaches every reader ─────────────────────────────────────────────────────────────

def test_the_result_carries_it():
    from openfactory.contracts import JobState

    assert RunResult(ticket_id="1", state=JobState.PAUSED).attempts_spent == 0, (
        "a result with no exhaustion must not claim one")
    assert RunResult(ticket_id="1", state=JobState.PAUSED, attempts_spent=3).attempts_spent == 3


def test_the_pause_ladder_records_the_number_it_already_had():
    from openfactory.runtime.temporal import workflow as wf

    src = inspect.getsource(wf.JobWorkflow)
    assert "attempts_spent=rate_resumes" in src, (
        "the ladder still writes the count only into prose — the regex is load-bearing again")


def test_the_park_payload_carries_it_to_the_ROUNDS():
    """The rounds read the `awaiting_action` payload and nothing else, so a count that lives only
    on the workflow object is invisible to the one caller that reports on parks."""
    from openfactory.runtime.temporal import workflow as wf

    src = inspect.getsource(wf.JobWorkflow._wait_operator)
    assert '"attempts_spent"' in src, "the query payload drops the count"


@pytest.mark.parametrize("module,symbol", [
    ("openfactory.runtime.temporal.workflow", "JobWorkflow"),
    ("openfactory.runtime.temporal.activities", "techlead_watch"),
])
def test_every_caller_that_HAS_the_number_passes_it(module, symbol):
    """A caller holding the count and not passing it puts the regex back in charge for that path
    — which is how one of two call sites gets fixed and the defect survives."""
    import importlib

    src = inspect.getsource(getattr(importlib.import_module(module), symbol))
    assert "already_spent" in src, f"{symbol} calls remedy_for without the count it holds"
