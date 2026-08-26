"""A message nobody asked for is written in the project's language — or it is registered (#160).

The sweep that opened this card found 26 sites and the two failure directions coexisted: an
English-configured client received Portuguese ("Dividi o #12 — era grande demais"), and a
Portuguese-configured one received English ("staging did not verify"), both from code sitting next
to a working per-language catalogue.

Fixing the 26 is worth one deployment. THIS is worth the next twenty: nothing structural made a
new composer language-aware, so the 27th arrived the same way the first twenty-six did — somebody
wrote a sentence at the call site because that is where the sentence was needed.

WHAT IT WALKS. Every call to a surface that leaves this process carrying words a person reads:
`notify`, `_notify` (the channel), `_say_on_ticket` and `comment` (the tracker), `_coord_say` (the
workflow's narration). If the argument carries a string that reads as a SENTENCE and no localizing
call renders it, the site fails — unless it is registered below with a reason.

WHY A REGISTRY AND NOT A CLEAN ASSERTION. Some of these surfaces are genuinely not a person's
language: a conformance probe writes a marker into a fake tracker, and a note read back by
`classify()` is an identity. Those are real, they are few, and each one has to say so out loud.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: The calls that carry words out of this process to a person.
SURFACES = {"notify", "_notify", "_say_on_ticket", "_coord_say", "comment"}

#: What renders a catalogue entry. A site whose argument reaches one of these has asked.
LOCALIZED = {"say", "_say", "_pick", "pick"}

#: The argument positions that carry the message (first positional, or these keywords).
MESSAGE_KEYWORDS = {None, "message", "body", "text"}

#: Registered exceptions: `path:line-independent reason`. A site here is NOT a person's language,
#: and says why. Keyed by file so a line number moving does not make somebody re-approve it.
NOT_A_PERSONS_LANGUAGE = {
    "openfactory/conformance/adapters.py":
        "the conformance probe writes a marker into a vendor's own API to prove the adapter can "
        "write at all — it is addressed to the next line of the probe, not to a reader",
}


#: A WORD, for counting: two or more letters. Not digits, not punctuation, not an emoji. `#`,
#: `:`, `2` and `✅` are how a machine-readable line is punctuated and say nothing about language.
_WORD = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


def _prose(node: ast.AST) -> list[str]:
    """The strings in this expression that read as a sentence rather than as a token.

    AN F-STRING IS ONE STRING, not its fragments. `f"✅ #{issue} merged to main"` parses as the
    constants `"✅ #"` and `" merged to main"`, and counting either alone finds two words and lets
    a whole welded sentence through — measured: that exact line survived the first version of this
    guard. They are joined before counting, which is also what a reader sees.

    THREE WORDS, because that is what separates a sentence from an identifier or a punctuated
    template. `f"{icon} {p}#{i}: {env} deploy {status}"` is one word and is not prose in any
    language; "tickets are not being picked up" is prose in exactly one.
    """
    out: list[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.JoinedStr):
            out.append(" ".join(v.value for v in n.values
                                if isinstance(v, ast.Constant) and isinstance(v.value, str)))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return [t for t in out if len(_WORD.findall(t)) >= 3]


def _asks(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if name in LOCALIZED:
                return True
    return False


def _welded_sites() -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover — a broken file fails louder elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name not in SURFACES:
                continue
            args = list(node.args) + [k.value for k in node.keywords
                                      if k.arg in MESSAGE_KEYWORDS]
            for arg in args:
                if _asks(arg):
                    continue
                said = _prose(arg)
                if said:
                    out.append((rel, node.lineno, said[0][:80]))
                    break
    return out


def test_no_outward_surface_composes_a_sentence_of_its_own():
    """The measurement this card exists to keep at zero."""
    unregistered = [s for s in _welded_sites() if s[0] not in NOT_A_PERSONS_LANGUAGE]

    assert not unregistered, (
        "these speak to a person in a language nobody asked them about — render through "
        "`techlead.voice.say` / `product.voice._pick`, or register the file above with a reason:\n"
        + "\n".join(f"  {f}:{ln}  {text!r}" for f, ln, text in unregistered))


def test_and_every_REGISTERED_exception_is_still_real():
    """A registry nobody prunes becomes the thing it was protecting against. Each entry has to
    still name a live site — otherwise it is a standing permission for the next one."""
    files = {s[0] for s in _welded_sites()}

    stale = sorted(set(NOT_A_PERSONS_LANGUAGE) - files)

    assert not stale, f"registered as system-surface and no longer welded at all: {stale}"


def test_the_walk_actually_INSPECTS_the_package():
    """The failure this file would otherwise have: a detector that matches nothing passes for a
    clean codebase. Measured on a sibling guard the same week — a wrong `.parent` made a ratchet
    inspect zero files and report success for three months."""
    seen = 0
    for path in (ROOT / "openfactory").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and (getattr(node.func, "attr", None) or "") in SURFACES):
                seen += 1

    assert seen >= 40, f"the walk found {seen} outward calls in the whole package"


@pytest.mark.parametrize("source,welded", [
    ('self._notify("the factory stopped and needs you", "warning")', True),
    # THE ROW THAT CAUGHT THE FIRST VERSION OF THIS DETECTOR. Split across an interpolation, no
    # fragment of it reaches four words — and the whole line is a sentence.
    ('self._coord_say(f"✅ #{params.issue} merged to main", "merge")', True),
    ('self._notify(voice.say(NARRATION, "park.needs-you", lang), "warning")', False),
    ('tracker.comment(ref, tl_voice.say(T, "k", lang, why=r))', False),
    ('tracker.comment(ref, f"#{issue}")', False),
    ('notifier.notify(message=f"{icon} {p}#{i}: {env} deploy {status}", level="info")', False),
])
def test_the_detector_can_tell_the_two_apart(source, welded):
    """VERIFY THE VERIFIER. Five probes in one day passed for the wrong reason in this repository;
    a detector nobody fed a failing case to is a detector that reports whatever it likes.

    The last row is the shape that would make this guard useless in the other direction: an
    f-string of interpolations and punctuation is not prose, and flagging it would teach the next
    reader to delete the check.
    """
    tree = ast.parse(source)
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and (getattr(n.func, "attr", None) or "") in SURFACES)
    args = list(call.args) + [k.value for k in call.keywords if k.arg in MESSAGE_KEYWORDS]

    flagged = any(bool(_prose(a)) and not _asks(a) for a in args)

    assert flagged is welded, f"the detector read {source!r} as {'welded' if flagged else 'clean'}"
