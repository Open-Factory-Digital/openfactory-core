"""Every verb a canned message tells somebody to type must parse (#124, step 1).

The tech-lead's messages instruct: *"Responda `resume #87` … ou `skip #87`"*. The operator grammar
in `contracts/commands.py` is what reads the reply, and it is deliberately BILINGUAL — `resume`,
`retry`, `continue` alongside `retomar`, `pular`, `descartar` — so the pt-BR sentences the platform
emits today are answerable.

That agreement is currently a coincidence of two files being written by the same person. #124
translates those sentences, and the moment one is rendered in a language whose verbs the parser
does not carry, the platform is telling a human to type a command its own channel will ignore.

It has already happened once, in the other direction: the merge gate's message dictated `resume` /
`skip`, which `commands.py` excludes from merge and release ON PURPOSE, so the instruction could
never work (fixed 2026-08-16, `f83df34`). A message and a parser are one vocabulary.

THE MESSAGES ARE GENERATED, NOT GREPPED. The first cut read string literals out of the source and
accused the modules of teaching `AskWorkflow`, `PromotionRunner` and `DecisionRequest` — backticked
IDENTIFIERS in docstrings, which no operator is being told to type. Calling the functions instead
means what is checked is what a human actually receives, and a docstring cannot fool it.
"""

from __future__ import annotations

import re

import pytest

from openfactory.contracts.commands import parse_command
from openfactory.techlead.classify import (
    CODE,
    CREDENTIAL,
    ENVIRONMENT,
    POLICY,
    PROJECT,
    REQUIREMENT,
    TRANSIENT,
    UNKNOWN,
    Verdict,
    remedy_for,
)

#: A verb a message TELLS somebody to type is written in backticks — the platform's own convention
#: for "this is a command", used by every canned sentence that carries one.
#:
#: A TRAILING COLON MEANS IT IS A KEY, NOT A COMMAND, and that is the codebase's own convention
#: rather than an exception invented here: the same sentences write `` `setup:` `` and
#: `` `validate:` `` for manifest fields and `` `resume` `` for something to type. Without the
#: distinction this guard accused the PROJECT remedy of teaching an operator to reply "setup" —
#: a false alarm on correct code, which is how a guard gets deleted.
#:
#: A path is excluded the same way, by its own punctuation: `.openfactory/project.yaml`.
_TAUGHT = re.compile(r"`([a-zA-Zà-ÿ]{3,})`")

#: One verdict per cause the taxonomy has, so a remedy added for a new cause is checked without
#: this file being updated.
_CAUSES = (TRANSIENT, CREDENTIAL, ENVIRONMENT, REQUIREMENT, CODE, POLICY, PROJECT, UNKNOWN)


def _every_remedy_sentence() -> list[tuple[str, str]]:
    """`(where, sentence)` for everything `remedy_for` can say — across causes, across an
    exhausted budget, and across an inherited exhaustion, since each takes a different branch."""
    out: list[tuple[str, str]] = []
    for cause in _CAUSES:
        for tried, spent in ((0, 0), (99, 0), (0, 3)):
            r = remedy_for(Verdict(cause=cause, detail="x", detail_source="x"),
                           already_tried=tried, already_spent=spent)
            for field in ("say", "reason"):
                text = getattr(r, field) or ""
                if text:
                    out.append((f"{cause}/tried={tried}/spent={spent}.{field}", text))
    return out


def test_every_verb_a_REMEDY_teaches_is_one_the_channel_accepts():
    """These sentences reach a person through the round's report and the park announcement, and
    both are answered by typing into the channel — so every command they name must parse there."""
    unparseable = []
    for where, sentence in _every_remedy_sentence():
        for verb in {m.group(1).lower() for m in _TAUGHT.finditer(sentence)}:
            if parse_command(f"{verb} #87") is None:
                unparseable.append((where, verb, sentence[:70]))
    assert not unparseable, (
        "these messages tell an operator to type a command `contracts/commands.py` does not "
        f"parse — the instruction is ignored by their own channel: {unparseable}")


def test_the_check_is_not_vacuous():
    """If the backtick convention moved, the assertion above would pass by finding nothing."""
    taught = {m.group(1).lower()
              for _w, s in _every_remedy_sentence() for m in _TAUGHT.finditer(s)}
    assert {"resume", "skip"} <= taught, (
        f"no known command verb was extracted from any remedy ({sorted(taught)}) — the convention "
        f"changed and this file is now decoration")


def test_the_grammar_really_is_bilingual_today():
    """The premise the guard rests on. If this narrows to one language, translating a message
    becomes unsafe again — and the failure would be silent."""
    assert parse_command("resume #87") == ("resume", "87")
    assert parse_command("retomar #87") == ("resume", "87"), (
        "the grammar stopped accepting Portuguese — every pt-BR message now teaches a command it "
        "cannot parse")
    assert parse_command("skip #87") == ("skip", "87")
    assert parse_command("pular #87") == ("skip", "87")


@pytest.mark.parametrize("verb", ["merge", "release", "deploy", "approve"])
def test_a_verb_the_grammar_EXCLUDES_stays_excluded(verb):
    """`commands.py` refuses merge/release on purpose — a channel message must never be able to
    land a pull request or ship. The guard above would happily accept a message teaching `merge`
    if the grammar had quietly grown it."""
    assert parse_command(f"{verb} #87") is None, (
        f"the channel grammar now parses `{verb}` — a chat message can trigger it")
