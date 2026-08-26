"""What a typed sentence on the FLOOR asks for — merge, discard, adjust (#120).

The pilot had `#87`'s PR open, the panel showing `View PR · Merge · Adjust… · Discard`, and typed
into the tech-lead chat:

    pode fazer o merge

and got back *"I can't merge from here — a merge is a human action, outside what I execute."*
Half right, and the wrong half is the expensive one: `merge_policy: human` means the DECISION is
the human's — the EXECUTION has always been the factory's, and `actions/catalog.py` carries the
row the panel's own button posts to. A human who has decided in words has decided.

THIS IS A MATCHER AND NOTHING ELSE. It never performs anything: the caller routes what it returns
through `actions.perform` with the actor that came through the door, so a sentence can never reach
something its author's credential could not — the rule `_say_as_an_intent` states for the product
side, and the reason this file holds no dispatch of its own.

THE ASYMMETRY OF MISTAKES DECIDES THE PATTERNS. A miss costs a rephrase. A false positive merges a
pull request into somebody's main branch on a sentence that was a question — so the gestures are
imperative, the question test from the product matcher is reused rather than reinvented, and
anything that reads as wondering aloud falls through to the tech-lead, who answers in prose.
"""

from __future__ import annotations

import re

from openfactory.product.intents import _asks_rather_than_tells

#: intent → the catalogue row it performs. The row is where the gate, the scope and the engine
#: check live; this table only says which door the sentence knocked on.
FLOOR_ROWS: dict[str, str] = {
    "merge": "merge",
    "discard": "discard",
    "adjust": "adjust",
    "review": "review",
    "stop": "stop",
    "resume": "resume",
    "skip": "skip",
}

#: An optional ticket ref riding on the instruction — `merge #87`, `faz o merge do 90`,
#: `descarta o CONT-412`. A DIGIT IS REQUIRED somewhere in the token, so "merge it" cannot read
#: "it" as a ticket; the shape is otherwise the provider's own (C-05: never assume numeric).
#:
#: CAPTURED SO THE CALLER CAN OBEY IT, and the sweep found all three costs of not doing so
#: (2026-08-16): a named ref was silently DROPPED, so "merge #90" merged whatever happened to be
#: waiting; and with two PRs waiting, the refusal dictated the reply `merge #87` — a sentence this
#: very matcher then threw the ref away from, re-entering the same refusal for ever. An
#: instruction's scope is part of the instruction.
_REF = r"(?:\s+(?:o\s+|a\s+|do\s+|de\s+|the\s+)?[#!]?(?P<ref>(?=[\w.-]*\d)[\w][\w.-]*))?"

#: The same ref, REQUIRED — for a verb whose false positive cannot be undone (#127).
#:
#: SPELLED OUT RATHER THAN DERIVED FROM `_REF`. The first version built it by string-surgery on
#: the pattern above (`_REF.replace("(?:\\s+", …)`), which left the trailing `?` in place — so the
#: ref stayed optional and "mata o job" matched with no ticket at all, which is the shape that
#: terminates whichever job happens to be first. Editing a regex by pattern is the mistake this
#: repository has a rule against, and it does not stop being one because the regex is ours.
_REF_REQUIRED = r"\s*(?:o\s+|a\s+|do\s+|de\s+|the\s+)?[#!]?(?P<ref>(?=[\w.-]*\d)[\w][\w.-]*)"

#: What may stand between the start of a clause and the verb that COMMANDS it. Politeness and
#: conjunctions, in both languages — never a determiner, never a subject, never another verb. It is
#: deliberately not a domain list: nothing in it names a stack, a vendor or this deployment.
#: `pode`/`vai lá`/`go ahead` ARE POLITENESS, not subjects (#158). The pilot typed "vai la da o
#: merge por favor" — as plain an order as the language has — and the head rule refused it because
#: two words stood in front of the verb. `vai` ALONE is not here and must not be: in Portuguese it
#: is also the future auxiliary, so "vai descartar tudo" ("that will discard everything") would
#: become an order to close a pull request. The two-word imperative cannot mean that.
_LEADER_WORDS = (r"ok|okay|please|por\s+favor|favor|e|and|then|ent[aã]o|agora|now|also|"
                 r"tamb[eé]m|depois|a[ií]|beleza|blz|pode|podes|poderia|"
                 r"vai\s+l[aá]|v[aá]\s+l[aá]|go\s+ahead")
_LEADERS = re.compile(rf"^(?:\s*(?:{_LEADER_WORDS})\b[,]?)*\s*$", re.I)

#: The same words as a PREFIX, for the bare verb below. One list, two uses: `_BARE` used to allow
#: exactly "ok," and nothing else, so `please merge` — the button's own word, politely — was
#: conversation. A second hand-written politeness list is the drift this file is made of.
#:
#: NO LEADING `\s*` INSIDE THE LOOP, and this is not style. With `\s*` at BOTH ends of a repeated
#: group a run of spaces can be eaten by the tail of one iteration or the head of the next — two
#: ways per space, 2^n paths, and the engine walks all of them before reporting failure. Every
#: typed message on the panel goes through here, so that is a denial of service on a web-facing
#: path, in a file whose whole job is to be handed arbitrary text. The trailing `\s*` alone is
#: unambiguous: each iteration must begin with a word from the list, so nothing competes for the
#: spaces in front of it.
_LEAD = rf"(?:(?:{_LEADER_WORDS})\b[,.!]?\s*)*"

#: "You may go ahead" — THE PERMISSION FORM OF AN ORDER, in every language this matcher
#: catalogues (#161, measured on the pilot 2026-08-21).
#:
#: THE FILE'S OWN HISTORY IS THE ARGUMENT. The Portuguese half was added the day the pilot typed
#: it — #153, "pode DAR o merge", with the Merge button on screen — and the English half was not.
#: Four months later the same pilot typed "you can merge" at the same gate, on a project
#: configured `en`, and got the identical failure: the sentence fell through to the tech-lead,
#: which answered with prose and a button asking him to decide a second time. A vocabulary grown
#: one live failure at a time grows exactly one language at a time.
#:
#: THE SUBJECT IS SECOND PERSON, AND IN ENGLISH IT IS REQUIRED. Portuguese drops it, so `pode` is
#: unambiguous alone; English does not, and "I can merge it" is a person saying they will do it
#: THEMSELVES — a permission form that accepts a first-person subject reads a withdrawal as a
#: grant. `we` is out for the same reason: it includes the speaker.
_MAY = (r"(?:pode|podes|poderia"
        r"|(?:you|y'?all)\s+(?:can|may|could)"
        r")\s+(?:go\s+ahead\s+and\s+)?")

#: Portuguese and English, imperative, and deliberately narrow. `merge` is the verb an operator
#: reaches for in both languages; the polite Brazilian form ("pode fazer o merge") is an
#: instruction, not a question, and is matched as one — while "posso fazer o merge?" ends in a
#: question mark and is refused by `_asks_rather_than_tells`.
#:
#: THE BARE VERB IS NOT HERE. "merge" alone is the word on the button and still counts — but only
#: as `_BARE`, anchored to a whole clause, because searched loose it also matched every sentence
#: that mentions merging: *"o merge falhou ontem"* — a narration — read as an order to do it
#: again. These patterns are the shapes where the verb is doing the commanding.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("adjust", re.compile(
        # `(?!\()` — A CONVENTIONAL-COMMIT SUBJECT IS NOT AN ORDER (#152). Every ticket in this
        # product is titled `fix(scope): …`, so quoting one back — which is what an operator does
        # when saying WHICH job they mean — read as `adjust`, with the title's own words as the
        # instruction. The verb that commands is followed by a space or a colon, never by a scope.
        r"\b(?:ajust[ae]|corrig[ei]|refaz|refaça|adjust|fix|rework)\b(?!\()"
        r"(?:\s*[#!](?P<ref>\w[\w.-]*))?"   # scope only when marked: "ajusta 2 coisas" has no ref
        r"\s*[:,]?\s*(?P<instruction>.+)",
        re.I)),
    # THE REPETITION IS THE VERB (#181). The bare word is not here for the reason `merge`'s is
    # not, and more so: these channels are full of sentences ABOUT reviews — "the review rejected
    # it", "a revisão está vencida", "review: OUT OF DATE" is a line this platform prints itself —
    # and a loose `review` reads every one of them as an order to spend a model pass. What
    # commands is asking for it AGAIN, in both languages, which is also exactly the gesture the
    # gate exists for.
    ("review", re.compile(
        # THE PERMISSION FORM IN BOTH LANGUAGES. `_MAY` leads the clause, so every shape a person
        # may put behind it has to be spelled here — an English "you can re-review it" reaching
        # only the bare alternative below is refused by `_commands_its_clause`, which is how a
        # gesture comes to exist in one language only.
        r"\b(?:" + _MAY + r"(?:(?:revisar|rever|reler)\s+(?:de\s+novo|novamente|outra\s+vez)"
        r"|re-?review|review\s+(?:it\s+|this\s+)?again|re-?run\s+(?:the\s+)?review)"
        r"|re-?review(?:s|ed)?"
        r"|re-?run\s+(?:the\s+|a\s+)?review"
        r"|review\s+(?:it\s+|this\s+|the\s+(?:pr|diff|change)\s+)?again"
        r"|(?:run|do|get|give\s+me)\s+(?:a\s+|one\s+)?(?:fresh|new|another)\s+review"
        r"|(?:a\s+|one\s+)?(?:fresh|new|another)\s+review"
        r"|revis[ae]r?\s+(?:isso\s+|o\s+pr\s+|a\s+mudan[çc]a\s+)?(?:de\s+novo|novamente|outra\s+vez)"
        r"|(?:nova|outra)\s+revis[ãa]o|revis[ãa]o\s+nova"
        r"|(?:roda|rodar|manda|mandar|passa|passar)\s+(?:a\s+)?revis[ãa]o\s+"
        r"(?:de\s+novo|novamente|outra\s+vez)"
        r")" + _REF,
        re.I)),
    ("discard", re.compile(
        # THE PERMISSION FORM TOO, for the reason `_MAY` states: the two gate verbs are the ones a
        # person answers WITH PERMISSION rather than with an imperative, because the platform has
        # just asked them a question. "you can discard it" is the same gesture as "discard it".
        r"\b(?:" + _MAY + r"(?:descartar?|discard)"
        r"|descarta(?:r)?|joga fora|fecha sem (?:o )?merge|discard|drop it|close without)\b"
        + _REF,
        re.I)),
    # STOP IS NARROWER THAN THE OTHERS, and deliberately (#127). It TERMINATES a running job and
    # does not resume — so a false positive costs a run, where a false positive on `merge` costs a
    # pull request somebody was going to land anyway. Only the imperative forms that can mean
    # nothing else: no bare "stop", no "para" (which is the preposition "for" in Portuguese and
    # appears in half of all sentences), and the object must be named.
    ("stop", re.compile(
        # `stop` IS IN THE LIST BECAUSE THE PLATFORM ITSELF TELLS PEOPLE TO TYPE IT. The
        # tech-lead's wedged-job alarm ends with `stop #{ticket}`, and a message dictating a
        # command no matcher accepts is the exact defect the merge gate paid for (#68/#120): the
        # operator types what they were asked to type and nothing happens. Safe here only because
        # the ref below is REQUIRED — bare "stop" stays conversation.
        # `(?<![\w-])` AND NOT `\b`: a hyphen is a word boundary, so `\bstop` matched "non-stop 3"
        # and read it as an order to terminate job 3. For the one verb here that cannot be undone,
        # the left edge has to be a real gap.
        r"(?<![\w-])(?:mata|matar|encerra(?:r)?|aborta(?:r)?|derruba(?:r)?"
        r"|kill|terminate|abort|stop)\s+(?:o\s+|a\s+|the\s+)?(?:job|ticket|card|run)?"
        + _REF_REQUIRED,
        re.I)),
    # RESUME AND SKIP CARRY A REQUIRED REF, like `stop` (#159): they act on a PARKED job, the
    # diagnosis that dictates them always names the ticket, and a bare "resume" typed into a chat
    # is as often a noun as an order. The park card's buttons stay the no-typing path.
    ("resume", re.compile(
        r"(?<![\w-])(?:resume|retom[ae]|retomar)\s+(?:o\s+|a\s+|the\s+)?"
        r"(?:job\s+|ticket\s+|card\s+)?" + _REF_REQUIRED,
        re.I)),
    ("skip", re.compile(
        r"(?<![\w-])(?:skip|pul[ae]|pular)\s+(?:o\s+|a\s+|the\s+)?"
        r"(?:job\s+|ticket\s+|card\s+)?" + _REF_REQUIRED,
        re.I)),
    ("merge", re.compile(
        # THE POLITE FORMS ARE THE COMMON ONES, and the list was one verb wide (#153). The pilot
        # typed "pode DAR o merge" — a merge gate on screen, a decision made in words — and it fell
        # through to the tech-lead, which answered with an opinion. That is #120's defect exactly,
        # surviving in a verb nobody had thought of.
        r"\b(?:" + _MAY + r"(?:fazer|dar|mandar|subir|integrar)?\s*(?:o\s+)?merge"
        r"|(?:faz|faça|manda|sobe|integra|d[aá])\s+(?:o\s+)?merge"
        r"|merge it|go ahead and merge|ship it|land it)"
        # …but never when the sentence is ABOUT the merge machinery: "pode fazer o merge policy
        # ser auto" carries no question mark and would otherwise land a pull request while
        # somebody was discussing configuration.
        r"(?!\s*[-_]?\s*(?:polic|gate|queue|commit|conflict|strateg|method))"
        + _REF,
        re.I)),
)

#: A clause that IS the verb — the word on the button, typed back: `merge`, `ok, merge #87`,
#: `mergeia`. Anchored to the whole clause, so a clause with anything else in it is conversation.
_BARE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("discard", re.compile(
        r"^\s*" + _LEAD + r"(?:descarta|discard)" + _REF + r"\s*[.!]?\s*$", re.I)),
    ("merge", re.compile(
        r"^\s*" + _LEAD + r"merge(?:ia|ar|a)?" + _REF + r"\s*[.!]?\s*$", re.I)),
)

#: What flips or holds an instruction. A NEGATED ORDER IS THE OPPOSITE ORDER (sweep, 2026-08-16):
#: "não faça o merge", "do not merge yet", "segura o merge" and "espera, não mergeia" all matched
#: `merge` and — with one PR waiting — would have MERGED, the human gate inverted by the exact
#: sentence that exercises it. The list holds negators and hold-verbs in both languages; it is
#: checked only within the verb's own clause, so "a espera acabou, faz o merge" still instructs.
_NEGATORS = re.compile(
    r"\b(?:n[aã]o|nunca|jamais|nem|never|don'?t|do\s+not|hold(?:\s+off)?|wait|stop"
    r"|segur[ae]|esper[ae]|aguard[ae]|adi[ae]|deixa)\b", re.I)

#: Clause boundaries. The comma is one on purpose: it is what separates "espera," from "não
#: mergeia" — and "ok," from "merge", which must keep working.
_CLAUSES = re.compile(r"[.!?;\n,]")




def _clause_start(body: str, start: int) -> int:
    last = 0
    for boundary in _CLAUSES.finditer(body, 0, start):
        last = boundary.end()
    return last


def _negated_before(body: str, start: int) -> bool:
    """Is there a negator or hold-verb between the verb and the start of its own clause?"""
    return bool(_NEGATORS.search(body, _clause_start(body, start), start))


#: A clause that is NOTHING BUT A HOLD — "wait", "hold off", "segura", "espera aí". It holds
#: whatever instruction sits in a later clause (product owner, 2026-08-21: *"hold e wait têm que
#: segurar"*).
#:
#: MEASURED, NOT SUSPECTED. `_NEGATORS` already carried `wait`, `hold`, `segura` and `espera` for
#: exactly this, and `_negated_before` searches only from the verb back to ITS OWN clause start —
#: so the comma that makes "hold off, merge it" two clauses put the hold out of reach:
#:
#:     'hold off, merge it'          -> merge      ← the gate inverted by the sentence
#:     'wait, discard it'            -> discard      that was typed to stop it
#:     'segura, pode fazer o merge'  -> merge
#:
#: AND THE COUNTEREXAMPLE THE FILE ALREADY NAMES SURVIVES, which is why this is a shape and not a
#: word search: "a espera acabou, faz o merge" says the wait is OVER. Its first clause is not a
#: hold instruction — it is a sentence containing the noun — so it does not match, and the merge
#: still lands. A blanket search for the word would have refused it.
#:
#: WHAT THE CLAUSE OPENS WITH IS THE WHOLE TEST, and the tail is deliberately unbounded. The
#: first version stopped at a short list of particles ("wait a second", "espera aí") on the theory
#: that anything longer is prose ABOUT waiting — and "wait for CI to finish, then merge it" landed
#: the pull request. At a gate whose entire purpose is to hold, the safe direction is to hold: a
#: refusal costs one more sentence, a wrong merge costs the pull request.
#:
#: It still cannot swallow the counterexample, because that one does not OPEN with the verb: "a
#: espera acabou" starts with an article and "esperei o suficiente" is a different word. A clause
#: that begins by telling somebody to wait is telling them to wait.
_BARE_HOLD = re.compile(
    r"^\s*(?:(?:" + _LEADER_WORDS + r")\b[,.!]?\s*)*"
    r"(?:hold(?:\s+on|\s+off)?|wait|hang\s+on|hold\s+your\s+horses"
    r"|segur[ae]|esper[ae]|aguard[ae]|calma|per[ae]\s*a[íi]|pera)\b"
    r"(?:\s+\S.*)?$",
    re.I | re.DOTALL)


#: A clause that is JUST a refusal — "não", "never", "nope". Same shape as the hold and the same
#: risk: it is the whole clause, so nothing inside the instruction's own clause carries it.
#: `no` is NOT here and cannot be: it is also the Portuguese contraction em+o, and the collision
#: discipline this codebase settled on (#157) says a word enters a language table only if, as a
#: complete message, it can mean nothing else in EVERY catalogued language.
_BARE_REFUSAL = re.compile(
    r"^\s*(?:(?:" + _LEADER_WORDS + r")\b[,.!]?\s*)*"
    r"(?:n[ãa]o|nunca|jamais|never|nope|nem pensar|de jeito nenhum)"
    r"\s*[.!]?\s*$",
    re.I)


def _held_by_another_clause(body: str, start: int, end: int) -> bool:
    """Does a clause of its own tell this instruction to wait, or refuse it outright?

    BOTH SIDES, because a person retracts in both directions: "wait, merge it" and "merge it —
    wait" are the same change of mind. The hold has to OPEN its own clause; a hold verb arriving
    later in a clause is prose about waiting ("a espera acabou" — the wait is over), and reading
    that as a hold would refuse the sentence it was written to permit.
    """
    head = body[:_clause_start(body, start)]
    tail = body[end:]
    for chunk in (head, tail):
        for clause in _CLAUSES.split(chunk):
            if clause.strip() and (_BARE_HOLD.match(clause) or _BARE_REFUSAL.match(clause)):
                return True
    return False


def _commands_its_clause(body: str, start: int) -> bool:
    """Is this verb DOING the commanding, or is it a word inside a sentence about it?

    THE DEFECT THIS ENDS (#152, measured on the pilot). Every pattern here was `search`ed across
    the whole message, so a verb anywhere in prose was an order. The operator pasted a 586-character
    review instruction into the tech-lead chat; it contained the words "a real type fix" near the
    end; that fired `adjust`, whose `(?P<instruction>.+)` then captured the twenty-six characters
    that happened to follow — and the platform spent a full agent pass on them, silently. A sweep
    of the other rows found the same shape everywhere: *"the discard button is confusing"* closed a
    pull request, *"I would drop it if the review were worse"* closed one, and *"stop #101 was
    suggested by the tech-lead earlier"* terminated a running job — a narration QUOTING the command
    the tech-lead itself dictates.

    An imperative opens its clause. That is the whole rule, and it is the one `_BARE` below already
    states for the bare verb ("a clause with anything more in it is conversation"); it simply was
    never applied to the verbs that carry an object.
    """
    return bool(_LEADERS.match(body[_clause_start(body, start):start]))


def _fills_its_clause(body: str, end: int) -> bool:
    """Does the command leave its clause, or does the sentence carry on past it?

    "descarta esse" is an instruction with a pronoun trailing it; "descartar seria um desperdício"
    is somebody thinking out loud, and the difference a reader hears is that the sentence keeps
    going. One trailing word is the allowance — enough for the demonstrative that follows a real
    order, and not enough for a predicate.

    IT COSTS `adjust` NOTHING, which is why there is no exemption for it: that pattern's
    `(?P<instruction>.+)` runs to the end of the line, and a newline is a clause boundary — so
    the match already fills its clause by construction. A special case here would have been a
    branch that can never be taken, and the mutation proving it was one is what removed it.
    """
    clause_end = len(body)
    match = _CLAUSES.search(body, end)
    if match:
        clause_end = match.start()
    # POLITENESS TRAILS AS WELL AS LEADS (#158). "vai la da o merge POR FAVOR" is an order with two
    # words of courtesy after it, and counting them refused the clearest instruction of the day.
    rest = re.sub(rf"\b(?:{_LEADER_WORDS}|obrigad[oa]|thanks|thank\s+you)\b", " ",
                  body[end:clause_end], flags=re.I)
    return len(rest.split()) <= 1


def _accept(name: str, m: re.Match[str], body: str) -> tuple[str, dict] | None:
    if _asks_rather_than_tells(body, m.end()):
        return None
    if _negated_before(body, m.start()):
        return None
    if _held_by_another_clause(body, m.start(), m.end()):
        return None
    if not _commands_its_clause(body, m.start()):
        return None
    if not _fills_its_clause(body, m.end()):
        return None
    captures = {k: (v or "").strip() for k, v in (m.groupdict() or {}).items() if v}
    if name == "adjust" and len(captures.get("instruction", "")) < 4:
        return None  # "ajusta" alone is not an instruction anybody can carry out
    return name, captures


def is_affirmation(text: str) -> bool:
    """Is this message a plain YES and nothing else? (#156)

    MEASURED ON THE PILOT. The tech-lead ended an answer staging `merge #101`; the operator typed
    "pode seguir"; nothing happened, because a staged proposal could only be accepted by PRESSING
    it. From his side the factory asked a yes/no question, was told yes, and changed the subject.

    THE VOCABULARY MOVED (#161) to `openfactory/language/assent.py`, and this is the mapping onto
    it. It moved because three surfaces carried three hand-rolled yes-lists that had already
    drifted — `certo` asserted approval on one, merely accompanied it on another, and was audited
    out here. A table nobody can compare is a table that disagrees with itself.

    THE QUESTION TEST STAYS HERE. "pode?" is asking permission, not granting it, and it is refused
    by the same `_asks_rather_than_tells` every other gesture in this file goes through — a second
    notion of "this is a question" is how two surfaces come to disagree about one sentence.
    """
    from openfactory.language import assent

    body = (text or "").strip()
    if not body or not assent.is_bare_assent(body):
        return False
    # FROM THE END OF THE ASSENT, not the end of the message: `_asks_rather_than_tells` reads the
    # terminator that FOLLOWS the gesture, so handing it `len(body)` gave it nothing to read.
    stripped = body.rstrip(".!?…").strip()
    return not _asks_rather_than_tells(body, len(stripped))


def match_floor_intent(text: str) -> tuple[str, dict] | None:
    """`(intent, captures)` for a sentence that INSTRUCTS, or None — and None is the common answer.

    `captures` may carry `ref` — the ticket the sentence itself names — and the caller is bound by
    it: acting on a different job than the one named is worse than refusing.

    Ordered `adjust` first because it swallows the rest of the sentence into an instruction, and
    an operator who writes "ajusta o merge para depois do CI" is asking for a repair pass, not a
    merge. A message that is a question about any of these falls through untouched."""
    body = text or ""
    for name, pattern in _PATTERNS:
        m = pattern.search(body)
        if not m:
            continue
        hit = _accept(name, m, body)
        if hit:
            # A rejected candidate FALLS THROUGH to the next pattern rather than ending the
            # search: "vale a pena mergear? descarta esse" is a question followed by an
            # instruction, and reading the whole message would throw the instruction away with it
            # (the rule the product matcher pays for by name).
            return hit
    # The bare verb, clause by clause: the word on the button typed back is an instruction, and a
    # clause with anything more in it is conversation about one.
    at = 0
    for chunk in _CLAUSES.split(body):
        for name, pattern in _BARE:
            m = pattern.match(chunk)
            if not m:
                continue
            # THE SAME FENCES AS THE ROWS ABOVE (2026-08-21). This path had only the question
            # test, because a clause-anchored verb cannot carry a negator INSIDE its own clause —
            # true, and beside the point: the hold lives in a DIFFERENT clause. Measured,
            # "espera o CI ficar verde, ai mergeia" landed the pull request through here while
            # the identical sentence with a carried object was correctly held one loop up.
            if _asks_rather_than_tells(body, min(at + m.end(), len(body))):
                continue
            if _held_by_another_clause(body, at + m.start(), min(at + m.end(), len(body))):
                continue
            return name, {k: (v or "").strip()
                          for k, v in (m.groupdict() or {}).items() if v}
        at += len(chunk) + 1
    return None
