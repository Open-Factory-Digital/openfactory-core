"""A message nobody asked for is written in the project's language — or it is registered (#160).

The sweep that opened this card found 26 sites and the two failure directions coexisted: an
English-configured client received Portuguese ("Dividi o #12 — era grande demais"), and a
Portuguese-configured one received English ("staging did not verify"), both from code sitting next
to a working per-language catalogue.

Fixing the 26 is worth one deployment. THIS is worth the next twenty: nothing structural made a
new composer language-aware, so the 27th arrived the same way the first twenty-six did — somebody
wrote a sentence at the call site because that is where the sentence was needed.

WHAT IT WALKS. Every call to a surface that leaves this process carrying words a person reads:
`notify`, `_notify` (the channel), `_say_on_ticket`, `comment` and `close_ticket` (the tracker —
a close's reason IS a comment on the card), `_coord_say` (the workflow's narration). If the
argument carries a string that reads as a SENTENCE and no localizing call renders it, the site
fails — unless it is registered below with a reason.

IT FOLLOWS A NAME BACK TO WHAT THE FUNCTION ASSIGNED TO IT (2026-09-19). `note = f"…"` two lines
above `self.comment(ref, note)` is the same welded sentence as the f-string written in the call,
and for a year it was invisible here: the Azure Boards row told a Portuguese board in English that
its card was not delivered, and #203's first draft was caught doing the same only because it
happened to write the sentence inline. ONLY ASSIGNMENTS IN THE ENCLOSING FUNCTIONS ARE READ — a
name that is a PARAMETER was composed by the caller, which is walked where it calls.

ONE STEP, AND THAT IS A MEASUREMENT RATHER THAN A SHRUG. A sentence relayed through a SECOND
variable (`said` → `note` → `comment`) is not seen here. Following the whole chain was written
and run: it found thirteen more sites, and the overwhelming majority were names interpolated into
a template that the chase then read as prose — `promotion-box-kind`, `agent auth failed`,
`classify-engine-interrupted`. Registering thirteen entries to buy one real finding is how a
registry becomes the standing permission this file exists to refuse, so the walk stops at one hop,
where every site it reports is a real one.

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
SURFACES = {"notify", "_notify", "_say_on_ticket", "_coord_say", "comment", "close_ticket"}

#: What renders a catalogue entry. A site whose argument reaches one of these has asked.
LOCALIZED = {"say", "_say", "_pick", "pick"}

#: The argument positions that carry the message (first positional, or these keywords).
MESSAGE_KEYWORDS = {None, "message", "body", "text", "reason"}

#: Registered exceptions: `path:line-independent reason`. A site here is NOT a person's language,
#: and says why. Keyed by file so a line number moving does not make somebody re-approve it.
NOT_A_PERSONS_LANGUAGE = {
    "openfactory/conformance/adapters.py":
        "the conformance probe writes a marker into a vendor's own API to prove the adapter can "
        "write at all — it is addressed to the next line of the probe, not to a reader",
}


#: WHAT THE WALK FOUND THE DAY IT LEARNED TO FOLLOW A NAME, beyond the two sites that change
#: fixed (the Azure Boards row's not-delivered note, the split parent's closing note). Each is a
#: real English sentence on a client's card, each wants a catalogue entry in two languages and
#: has tests pinned on its English, and none of them is about closing a card — so they are named
#: here, by FILE AND FUNCTION so that nothing else in those files is excused, and a case below
#: keeps this from growing and removes an entry the day its site is fixed.
SEEN_ONLY_SINCE_THE_WALK_FOLLOWS_A_NAME = {
    ("openfactory/actions/catalog.py", "_settle_after_stop"):
        "the note a stop leaves on the card (`Stopped by … The job was terminated in the engine`)",
    ("openfactory/orchestrator/machine.py", "_record_decision"):
        "the decision request posted on the card (`Decision needed — the job is on hold`)",
    ("openfactory/runtime/temporal/activities.py", "_do_coordinate"):
        "the tech-lead's take posted on the card (`Tech-lead take … Recommends`)",
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


_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _enclosing(tree: ast.AST) -> dict[ast.AST, list[ast.AST]]:
    """Every call → the functions it sits in, innermost first. A lambda is not one of them: a
    message composed in a function and posted from a `to_thread(lambda: …)` inside it is still
    that function's sentence."""
    inside: dict[ast.AST, list[ast.AST]] = {}

    def walk(node: ast.AST, chain: list[ast.AST]) -> None:
        if isinstance(node, ast.Call):
            inside[node] = chain
        deeper = [node, *chain] if isinstance(node, _FUNCTIONS) else chain
        for child in ast.iter_child_nodes(node):
            walk(child, deeper)

    walk(tree, [])
    return inside


def _assigned(functions: list[ast.AST], name: str) -> list[ast.AST]:
    """What these functions ASSIGN to `name` — every `name = …`, `name += …`, `name: T = …`. Empty
    for a parameter, which is the point: the caller composed it, and the caller is walked too."""
    values: list[ast.AST] = []
    for func in functions:
        for n in ast.walk(func):
            if isinstance(n, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
                    values.append(n.value)
            elif (isinstance(n, (ast.AugAssign, ast.AnnAssign)) and n.value is not None
                  and isinstance(n.target, ast.Name) and n.target.id == name):
                values.append(n.value)
    return values


def _welded_in(tree: ast.AST) -> list[tuple[int, str, str]]:
    """`(line, enclosing function, the sentence)` for every welded site in one parsed file."""
    out: list[tuple[int, str, str]] = []
    for node, functions in _enclosing(tree).items():
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name not in SURFACES:
            continue
        args = list(node.args) + [k.value for k in node.keywords if k.arg in MESSAGE_KEYWORDS]
        for arg in args:
            # THROUGH A NAME, ONE STEP: what the function put in the variable is what it says.
            carried = _assigned(functions, arg.id) if isinstance(arg, ast.Name) else [arg]
            said = [s for value in carried if not _asks(value) for s in _prose(value)]
            if said:
                out.append((node.lineno, getattr(functions[0], "name", "") if functions else "",
                            said[0][:80]))
                break
    return out


def _welded_sites(*, registered: bool = False) -> list[tuple[str, int, str]]:
    """Every welded site in the package. The ones `SEEN_ONLY_SINCE_THE_WALK_FOLLOWS_A_NAME`
    names are left out unless `registered` asks for exactly those."""
    out: list[tuple[str, int, str]] = []
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover — a broken file fails louder elsewhere
            continue
        for line, function, said in _welded_in(tree):
            if ((rel, function) in SEEN_ONLY_SINCE_THE_WALK_FOLLOWS_A_NAME) is registered:
                out.append((rel, line, said))
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


def test_the_sites_found_by_following_a_name_can_only_SHRINK():
    """Three, found 2026-09-19, each still welded — so an entry cannot outlive its site — and
    never a fourth: a new one is fixed where it is written, which is what the walk is for."""
    live = {rel for rel, _line, _said in _welded_sites(registered=True)}

    stale = sorted(k for k in SEEN_ONLY_SINCE_THE_WALK_FOLLOWS_A_NAME if k[0] not in live)

    assert not stale, f"registered and no longer welded — remove the entry: {stale}"
    assert len(SEEN_ONLY_SINCE_THE_WALK_FOLLOWS_A_NAME) <= 3


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
    # A CLOSE'S REASON IS A COMMENT ON THE CARD — the split parent's note got through as one.
    ('tracker.close_ticket(ref, f"Pre-flight: too large for one ticket ({why}). Split: {kids}.")',
     True),
    ('close_ticket(tracker, ref, tl_voice.say(T, "split.parent.closed", lang), delivered=False)',
     False),
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
                and (getattr(n.func, "attr", None) or getattr(n.func, "id", "")) in SURFACES)
    args = list(call.args) + [k.value for k in call.keywords if k.arg in MESSAGE_KEYWORDS]

    flagged = any(bool(_prose(a)) and not _asks(a) for a in args)

    assert flagged is welded, f"the detector read {source!r} as {'welded' if flagged else 'clean'}"
    assert bool(_welded_in(tree)) is welded, "the package walk and this probe disagree"


@pytest.mark.parametrize("source,welded", [
    # THE SHAPE THAT HID THE AZURE BOARDS ROW'S NOTE: composed, kept in a variable, then posted.
    ("""def close(self, ref, reason):
    note = reason or ""
    note = note + f"_Closed as NOT delivered. This process has no Removed state._"
    self.comment(ref, note)""", True),
    ("""def stop(tracker, by):
    said = f"Stopped by {by}. The job was terminated in the engine."
    run(lambda: tracker.comment("7", said))""", True),
    ("""def close(self, ref):
    note: str = "this card was closed by hand"
    self.comment(ref, note)""", True),
    ("""def close(self, ref, lang):
    note = _pick(_CLOSED_NOT_DELIVERED_NOTE, lang).format(status="Done")
    self.comment(ref, note)""", False),
    # A PARAMETER IS THE CALLER'S SENTENCE, and the caller is walked where it calls.
    ("""def comment_on(self, ref, body):
    self.comment(ref, body)""", False),
    ("""def count(self, ref):
    note = f"#{ref}"
    self.comment(ref, note)""", False),
])
def test_the_walk_sees_a_sentence_THROUGH_the_variable_that_carries_it(source, welded):
    found = _welded_in(ast.parse(source))

    assert bool(found) is welded, f"read as {'welded' if found else 'clean'}:\n{source}"
