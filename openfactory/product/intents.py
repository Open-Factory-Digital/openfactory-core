"""What a person can ASK the product role to do, beyond talking.

The announcement, the board triage and the Needs Action sweep are things this role can do on its
own. Until something schedules them they are functions nobody calls — so the cheapest way to make
them real is to let a person ask, in the channel, in their own words.

IT LIVED IN `openfactory/runtime/slack/` UNTIL #105, and nothing about it was ever Slack: 587 lines
whose
only import is `re`, matching a client's own sentence to an intent. Not one line of this file
changed on the way out, which is the evidence — a module that needed editing to leave a vendor's
package would have been coupled to it. ADR-0038 rule 3 says that package renders and parses; this
parses a PERSON, not a transport, and every word below already said "the channel" rather than
"Slack". A guard now scans that package for modules indifferent to Slack
(`test_provider_seams.py::test_nothing_in_the_slack_package_is_INDIFFERENT_TO_slack`), because the
seam guard that existed skipped the whole directory and could never have seen this.

MATCHED CONSERVATIVELY. These are the few messages that must NOT be answered as conversation, and
the cost of the two mistakes is not symmetric: a missed intent means somebody rephrases, while a
false one means the role answers a question by running a board sweep. So the patterns are anchored
and specific, and anything unrecognised falls through to the conversation — which is the path that
handles being wrong gracefully.

THE READING ONES NEVER WRITE. Triage reports, the sweep reports, the announcement announces —
the first-pass rule from ADR-0019, and it holds for the same reason: on request or on a schedule,
this role has the least context exactly when it is asked to look at everything at once.

MOST OF THE WRITING ONES ONLY PROPOSE. `accept`, `drop`, `close` and `align` each change what the
factory defends or what it builds, so matching one stages a confirmation and nothing else; an
authorised person's yes is what reaches the pen. For those four a pattern is never the last thing
standing between a sentence and an irreversible act in a client's name — which is what makes it
possible to match a gesture in the middle of a paragraph at all.

TWO OF THEM ARE THE LAST THING STANDING. `refine` edits a client's ticket and `breakdown` files
work, both on the match alone, with no confirmation in between. They are matched in the middle of a
paragraph for the same reason as the rest — that is where the regression happened — and they pay
for it with the strictest form of the four guards below: the imperative, a reference the gesture is
ATTACHED to, a clause that is not a question, and the gesture OPENING that clause.

AND THAT IS A DECLARED EXCEPTION, NOT AN OVERSIGHT. It is written down here, beside the rule it
breaks, because "is this deliberate?" is a question a reader of this file should never have to
carry into `_run_intent`. The argument, in full:

    what it costs      FILING SPENDS NOTHING. A card lands in Backlog, the poller pulls TO-DO, and
                       the only way out of Backlog is `promote` — reached by the `queue` gesture,
                       which IS staged and gated. So a wrong `breakdown` costs cards somebody can
                       close, never a run. `refine` writes criteria only where there are NONE (it
                       answers `existed` and refuses otherwise); the act that REPLACES criteria
                       somebody may already be working from is `align`, and that one is staged.
    who may do it      an approver, checked in the channel before anything is called and again in
                       the module. Never "whoever is in the room".
    what pays for it   the four guards below, which no staged gesture is held to.

WHAT IS NOT PART OF THE EXCEPTION: the authorisation. A gesture with no confirmation behind it must
still be refused to somebody who could not have confirmed one, and both branches check that in the
channel BEFORE they call anything. The channel used to check nothing here and lean entirely on the
module: a non-approver bought a receipt and a round-trip before hearing no, and the only gate lived
one layer down, where nobody writing the next branch would look for it.

If either of these ever grows a second write, or reaches anything outside Backlog, the exception
stops holding and they get staged like the rest — the cost of that is one extra message.

THE FOURTH GUARD IS WHERE THE TWO GROUPS DIFFER, and the difference is what a mistake costs. A
gesture that stages a proposal may be reached across a connective ("beleza, e fecha o #511"),
because being wrong there costs a person one question. The two that write on the match alone are
reached only where the clause itself begins, because being wrong there costs money and a client's
board — and «a gente vê isso, e quebra o requisito 8» is a plan with a connective in front of it.
"""

from __future__ import annotations

import re

#: An optional VOCATIVE before the verb. People address a named agent — "Nina, faz a triagem" — and
#: anchoring hard at the start made every one of those a miss, which is the most obvious way anyone
#: would actually phrase it. Deliberately narrow: one short token followed by a comma or a colon, so
#: "o que a triagem disse semana passada" (no comma) stays a question.
_VOCATIVE = r"(?:[@<]?[\w.-]{1,20}[>,:]\s*)?"

#: intent → pattern. Anchored at the start so "what did the triage say last week?" stays a question.
_START = r"^\s*" + _VOCATIVE

#: THE OTHER HALF OF THE ANCHOR, for the gestures that NAME A CARD OR A REQUIREMENT.
#:
#: Anchoring at the start is right for an intent whose verb is ordinary. It is wrong for one whose
#: object is a number, and the cost was measured: on 2026-07-31 "Nina, boa observação e vamos …
#: Refina o #523 …" fell through to conversation and minted a requirement nobody had asked for.
#: A preamble is how people write.
#:
#: So every gesture that names a thing scans the WHOLE message, and pays for it four times over:
#:
#:   the reference  the thing must be NAMED — a card (`#511`, "cartão 511") or a requirement
#:                  ("requisito 8") — and the number must be ATTACHED to the gesture (see
#:                  `_ATTACHED`). This is an accounting firm's channel: "fecha o mês 10" is an
#:                  ordinary sentence there, and a loose number would have read it as an
#:                  instruction to close a card.
#:   the mood       the IMPERATIVE only. Every modal in Portuguese takes the infinitive — "vamos
#:                  fechar", "podemos fechar", "quando vamos fechar" — so refusing the infinitive
#:                  refuses that entire class in one rule instead of a list of modals somebody has
#:                  to keep extending. The verbs therefore end at a word boundary on their
#:                  imperative form: "fecha"/"feche", never "fechar", never "fechamos". A near-miss
#:                  is cheap here: "escrever os critérios do #288 a partir do requisito 6" falls to
#:                  `refine`, whose refusal now names `alinhar`.
#:   the position   the gesture OPENS ITS CLAUSE (`_CLAUSE_START`). The mood guard alone assumes
#:                  every non-imperative reading takes the infinitive, and in this language one
#:                  does not: "a gente quebra" is the everyday first person plural and is spelled
#:                  exactly like the order.
#:   the negation   "não fecha o #511" is an instruction NOT to, and it is the one shape whose
#:                  meaning inverts while every other signal stays identical.
#: A LOOKBEHIND IS FIXED-WIDTH, so each negator is its own alternative and each must be spelled at
#: its own length. That is why this is a list of groups rather than one — and why a table like
#: `language/assent.py` cannot serve it directly.
#:
#: `no` IS NOT HERE AND MUST NOT BE, though it is how a Spanish or English speaker negates. In
#: Portuguese `no` is *in the* — "no PR 101 faz o merge" is an ordinary instruction with `no`
#: sitting right before the verb, and admitting it would refuse the sentence this platform exists
#: to obey. That is the collision discipline #157 wrote down for `ta`, on the other surface: a word
#: enters only if, as it appears here, it can mean nothing else in every catalogued language.
#: A Spanish deployment needs the gesture matcher to take its verbs from a table (#161's third
#: section); it does not need this list to guess.
_NOT_NEGATED = (r"(?<!n[ãa]o )(?<!nao )(?<!nunca )(?<!jamais )(?<!nem )"
                r"(?<!never )(?<!don't )(?<!dont )(?<!do not )")

#: Typographic quotes, and they are load-bearing twice. Every refusal that names "the sentence that
#: works" shows it in «…», and a client who copies it as shown types the guillemets too: a leading
#: one used to block the clause anchor, so the one instruction this surface asks people to say
#: matched NOTHING and fell through to the conversational model — the path that has already minted
#: a requirement nobody requested. Admitted as a clause boundary below, and stripped off captures
#: in `match_intent`, because a trailing » left inside a reason is written onto a client's card as
#: the grounds somebody decided.
_QUOTES = "«»\"“”'‘’"

#: WHERE AN INSTRUCTION IS ALLOWED TO BEGIN — the guard the other three cannot supply.
#:
#: Widening the scan made "amanhã a gente quebra o requisito 8 em tarefas" FILE WORK on a client's
#: board with nothing in between: a sentence about tomorrow, spending money today. The mood guard
#: could not see it, because "quebra" is both the imperative and the third person singular, and
#: "a gente + 3rd person" is how this language says "we". The same reading is available to every
#: scanned gesture — "o time aceita o requisito 1 na quinta", "a gente fecha o #511 amanhã".
#:
#: NOT A LIST OF PRONOUNS. Every noun phrase in the language is a candidate subject, so such a list
#: has holes nobody can see, and each hole is a write. What is not a list is the grammar: an
#: imperative OPENS ITS CLAUSE, and anything in front of the verb inside that clause is a subject or
#: an adjunct — a sentence describing rather than ordering. So the gesture must sit at the start of
#: the message or straight after a clause boundary.
_CLAUSE_START = r"(?:^|(?<=[,;:>\n…—–!?.\-" + re.escape(_QUOTES) + r"]))\s*"

#: What may still stand between the boundary and the gesture where a mistake costs a QUESTION.
#: People write "beleza, e fecha o #511" and "Nina, por favor encerra o #511", and refusing those
#: would push them back to prose. These are function words that cannot be a subject; the list is
#: closed, and its holes cost a rephrase rather than a write — the direction this surface is allowed
#: to fail in. The article is here for the gestures whose OBJECT comes first ("o #511 é duplicado do
#: #288"), and it is an article alone: "a gente" gets past it and then has to be the verb, and is
#: not.
#:
#: THE NEGATORS ARE ADMITTED HERE SO THAT `_NOT_NEGATED` IS THE THING THAT REFUSES THEM. Without
#: them nothing could ever place "não " immediately before a verb — `_CLAUSE_START` cannot anchor
#: past it and no bridge word could carry it — so the lookbehind the docstring above counts as one
#: of four guards decided nothing, and "não fecha o #511" was refused only by the clause anchor.
#: The next widening of that anchor (this file has already made one) would then have turned an
#: instruction NOT to close into a staged close on a client's board, with no test failing. Letting
#: the bridge consume the negator costs nothing — the lookbehind refuses at that position, and the
#: only other reading leaves the verb sitting on "não" — and it makes the guard real.
#: EVERY NEGATOR `_NOT_NEGATED` REFUSES IS ADMITTED HERE, and the two lists move together — a
#: guard asserts it. A negator the bridge does not carry can never reach the position the
#: lookbehind watches, so the lookbehind decides nothing about it and the clause anchor is the
#: only thing left; a widening of that anchor then turns an instruction NOT to close into a close.
_BRIDGE = (r"(?:(?:e|ent[ãa]o|a[íi]|da[íi]|mas|sim|ok|beleza|agora|depois|j[áa]|"
           r"n[ãa]o|nunca|jamais|nem|never|don'?t|do\s+not|por\s+favor|favor)[\s,]+){0,2}"
           r"(?:(?:os?|as?)\s+)?")

#: The gestures that reach a client's board with NO confirmation behind them — the declared
#: exception at the top of this file, and its membership. They get the boundary and nothing else: a
#: connective is exactly what carries an elided subject into the next clause ("a gente vê isso, e
#: quebra o requisito 8"), and there is nobody to ask before that files work.
#: Kept honest by two tests that derive, from the handler itself, which intents stage a proposal and
#: which merely gate — a set maintained by hand beside the fact it describes is what this file has
#: already paid for.
_UNCONFIRMED = frozenset({"breakdown", "refine"})

#: WHAT MAY STAND BETWEEN A GESTURE AND THE NUMBER IT NAMES: articles and prepositions, nothing
#: else. It used to be "any 20 to 40 characters", which is a whole clause — and a clause is where
#: the NEXT, unrelated number lives. That gap read a survivor out of "em lugar disso vamos ver o
#: #288", and it would read a card out of "refina isso pra mim até o dia 3". A number this rule
#: admits is attached to the gesture; one further away belongs to another sentence and is not
#: being named by it.
#: The English prepositions ride in the same bridge (#24 item 5): "as a duplicate OF #288" used
#: to stop at "of", so the survivor fell to the ask-which-card path — the taught sentence ending
#: in a question round-trip instead of the act it states. These are skippable connectors only;
#: none of them can start a match on its own.
_ATTACHED = (r"(?:\s+(?:d[oae]s?|pel[oa]s?|por|para|pra|pro|com|ao|[aoà]|os|as|um|uma"
             r"|of|to|with|by|for|the|an?)\b)*\s*")


def _card(group: str) -> str:
    """A CARD reference — `#511`, `# 511`, "cartão 511" — captured under `group`.

    Written once and used for both numbers a close can carry: the card that goes and the card that
    stays. A second hand-written copy is how one of them ends up accepting a bare number.
    """
    return (r"(?:#\s?|\b(?:cards?|cart[õo]es|cart[ãa]o|chamados?|itens|item|tarefas?)\s+#?)"
            rf"(?P<{group}>\d{{1,4}})\b")


def _requirement(group: str) -> str:
    """A REQUIREMENT reference — "requisito 8", "req 8", "requirement 8" — captured under `group`.

    The counterpart of `_card`, and written once for the same reason: four gestures name a
    requirement by number, and the fourth hand-written copy is where the word list drifts.
    """
    return rf"\b(?:requisito|req|requirement)\s*#?(?P<{group}>\d{{1,4}})\b"


#: The PHRASE that says a closure has a survivor. Never a bare word: `favor` was one, and "por
#: favor" is the commonest politeness phrase in this language — "fecha o #511, por favor, e depois
#: o #288" closed #511 in favour of #288, a relation nobody stated, written on the client's board
#: in their name. "em favor de" / "a favor de" is what means it; the noun on its own means nothing,
#: and the same is true of "lugar" ("em lugar de") and "prol" ("em prol de").
#: The ENGLISH half exists because the voice already spoke it (#24 item 5): every refusal and
#: instruction has an `en` catalogue entry — "close #N as a duplicate of #M" — and the connective
#: list only knew Portuguese, so an English deployment's own taught sentence stated a relation the
#: parser could not see: the close landed with no pointer, the exact half-act the connective rule
#: exists to prevent.
#: WHAT ONE CARD IS OF ANOTHER, as a NOUN — spelled ONCE (#161). This list lived here in both
#: languages and a second, Portuguese-only copy lived inside the copula row below, so "card 511 is
#: a duplicate of 288" matched nothing while "o card 511 é uma duplicata do 288" closed the card.
#: One fact spelled twice, and only one of the two spellings learned English.
_DUPLICATE_NOUN = (r"duplicad\w*|duplicata|duplicat\w*|\bdupe?\b|repetid\w*|c[óo]pia"
                   r"|cobert\w*|resolvid\w*|substitu\w*"
                   r"|\bcovered\b|\bresolved\b|supersed\w*|\breplaced\b")

_SURVIVOR_CONNECTIVE = (r"(?:" + _DUPLICATE_NOUN +
                        r"|\b(?:em|[aà]|ao|no|na)\s+favor\b|\b(?:em|no|ao)\s+prol\b|"
                        r"\b(?:em|no)\s+lugar\b|\bin\s+favou?r\b)")

#: The card a closure is decided IN FAVOUR OF, read off the CONNECTIVE rather than off "the next
#: number in the sentence". Without it, "fecha o #511, já falamos disso na semana 32" would have
#: closed #511 in favour of card 32 — and the closing comment would name it, in writing, on the
#: client's board.
#: The words before the connective are left free ("como duplicado", "está coberto") and capped at
#: two, so the connective is what has to be there and the phrasing around it is not a list somebody
#: maintains.
#:
#: THE SURVIVOR IS ALSO READ WHEN IT IS WRITTEN WITHOUT A `#`, under its own name. "fecha o #511
#: como duplicado do 288" is a stated duplicate, and dropping the second number silently turned it
#: into the OTHER act — the card closed with no pointer and the client shown the wording for work
#: being given up. Captured separately because a bare number is not proof enough to write with: it
#: costs a question (`survivor_unclear`), never a staged write.
#:
#: The separator admits a BRACKET because "fecha o #511 (duplicado do #288)" is how people write a
#: parenthetical, and there the connective is present and the relation stated plainly.
_IN_FAVOUR_OF = (r"(?:[\s,;:.()\[\]–—-]*(?:\w+\s+){0,2}" + _SURVIVOR_CONNECTIVE + _ATTACHED
                 + r"(?:" + _card("in_favour_of") + r"|(?P<in_favour_of_unclear>\d{1,4})\b))?")

#: A CARD reference ANYWHERE in the message. It answers the one question the survivor rule cannot:
#: did the person name a second card at all.
_ANY_CARD = re.compile(_card("card"), re.IGNORECASE)


def _other_card_named(text: str, number: str) -> str:
    """A card other than `number` named in this message, or "".

    THE GUARD WAS KEYED ON THE CONNECTIVE WHEN THE FACT IS THE SECOND CARD. `_IN_FAVOUR_OF` reads a
    survivor only through a listed word, so "fecha o #511 (duplicado do #288)", "encerra o #511, o
    #288 já cobre isso" and "fecha o #511 porque já está coberto pelo #288" each dropped #288 in
    silence and performed the OTHER of the two acts these texts exist to keep apart: #511 closed
    with no pointer, under the wording for work being given up, in answer to a sentence saying the
    work moved — and #288 never told it had absorbed anything. Meanwhile the strictly WEAKER signal,
    a bare number after a recognised connective, correctly cost a question. The clearer sentence
    bought the worse outcome.

    So a second card that the connective rule did not claim is ambiguity, and ambiguity costs a
    question. Never a survivor to write with: this cannot tell "o #288 já cobre isso" from "já
    falamos disso no #288", and only one of those states a relation. A CARD, not a number — "fecha
    o #511, já falamos na semana 32" names no second card and asks nothing.
    """
    for match in _ANY_CARD.finditer(text or ""):
        found = match.group("card")
        if found != number:
            return found
    return ""

#: WHY a card is being closed, read off a CAUSAL connective — never off the tail of the sentence.
#: `drop` takes everything after the number and can afford to: it is one requirement and the rest of
#: the message is the argument for retiring it. A closure is matched anywhere in a message, so a
#: tail capture would write the next unrelated clause onto a client's card as the reason somebody
#: decided. Without it the success line promised "quem decidiu e por quê" over a note that only ever
#: held the who.
_BECAUSE = (r"(?:[\s,;:—–-]*\b(?:porque|porqu[êe]|por que|pois|j[áa] que|uma vez que|visto que|"
            r"motivo:|raz[ãa]o:)\s+(?P<reason>[^.!?\n]{3,200}))?")

#: THE GESTURES AS THEY READ. What is matched is `_INTENTS` below, which is this table with the
#: clause anchor applied — kept apart so each pattern says only what makes it that gesture, and the
#: rule they all obey is written once instead of eleven times.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("announce", re.compile(
        _START + r"(se apresent|apresent[ae]([- ]se)?|quem (é|e) voc[êe]"
                 r"|introduce yourself|who are you)", re.IGNORECASE)),
    ("triage", re.compile(
        _START + r"(faz(er)?|faça|roda(r)?|rode|revis(a|ar|e)|organiz(a|ar|e)|run|do)\b"
                 r".{0,30}\b(triagem|board|quadro|casa|house|triage)s?\b", re.IGNORECASE)),
    ("needs_action", re.compile(
        _START + r"(olh(a|ar|e)|v[êe]|ver|revis(a|ar|e)|check|look)\b"
                 r".{0,30}\b(needs?[- ]action|impedimentos?|parad[ao]s?|bloquead[ao]s?)\b",
        re.IGNORECASE)),
    # "quebra o requisito 8 em tarefas" — the step that turns an agreed requirement into work.
    # Carries the number, because filing work for the wrong requirement is not a typo to shrug at.
    # ONE OF THE TWO THAT WRITE ON THE MATCH ALONE, so the mood guard is the whole defence:
    # "vamos quebrar o requisito 8 amanhã" is a plan, and filing eight tickets off it spends money
    # nobody released.
    ("breakdown", re.compile(
        _NOT_NEGATED + r"\b(?:quebr[ae]|divid[ae]|transform[ae]|break|split)\b"
                       r"[^\d]{0,40}" + _requirement("number"),
        re.IGNORECASE)),
    # "aceita o requisito 1" / "dá o requisito 1 como acordado" — the act that turns written text
    # into a promise the factory DEFENDS (ADR-0032). Imperative only and the number required, like
    # every other writing intent: this is the most consequential write on the surface.
    ("accept", re.compile(
        _NOT_NEGATED + r"\b(?:aceit[ae]|acord[ae]|aprov[ae])\b"
                       r"[^\d]{0,40}" + _requirement("number"),
        re.IGNORECASE)),
    # "dá o requisito 1 como acordado" — the same act with the object in the middle. A second
    # pattern rather than one clever regex: "dá" alone must never be a write ("dá uma olhada no
    # requisito 1" is a request to READ), so the qualifier is required and has to follow the number.
    # The one place the infinitive is admitted, and it is the qualifier that pays for it: "dar o
    # requisito 12 como aceito" is a decision stated, not a possibility raised, because no modal
    # reaches that far without a question mark behind it.
    ("accept", re.compile(
        _NOT_NEGATED + r"\bd[áa](?:r)?\s+(?:o\s+)?(?:requisito|req)\s*#?(?P<number>\d{1,4})\s+"
                       r"como\s+(?:acordad|aceit)\w*",
        re.IGNORECASE)),
    # "accept requirement 6" — the ENGLISH sentence the voice itself teaches ("say \"accept
    # requirement {successor}\"", voice.py) and the parser did not know (#24 item 5). TIGHT
    # adjacency where the Portuguese demands imperative morphology: English "accept" is also an
    # everyday verb ("I accept that requirement 3 is unclear"), and only the exact taught shape —
    # verb, optional article, the word requirement, the number — is a write order.
    ("accept", re.compile(
        _NOT_NEGATED + r"\baccept\s+(?:the\s+)?(?:requirement|req)\s*#?(?P<number>\d{1,4})\b",
        re.IGNORECASE)),
    # "registra no requisito 6 que o pró-labore entra como despesa fixa" — a decision taken AFTER
    # the text was written, into the document's own register.
    #
    # THE DECISION IS CAPTURED OFF A CONNECTIVE ("que", ":", "—"), never off the tail. `drop` takes
    # everything after the number and can afford to — one requirement, and the rest of the message
    # is the argument for retiring it. This one writes a SENTENCE into a client's document under
    # their name, so what gets written has to be something they said, in a clause they opened, and
    # the confirmation shows it back verbatim before anything is written.
    #
    # Staged like every act that changes the document. It is deliberately NOT in the unconfirmed
    # set: the two exceptions there file work into an inert column, while this puts words in a
    # person's mouth in a record whose entire value is that nobody edits it afterwards.
    ("decision", re.compile(
        _NOT_NEGATED + r"\b(?:registr[ae]|anot[ae]|grav[ae]|guard[ae]|record|note)\b"
                       r"(?:\s+(?:isso|isto|essa|esta|a)\s*)?"
                       r"(?:\s+(?:como|a)\s+decis[ãa]o)?"
                       r"[^\d]{0,30}" + _requirement("number") +
                       # `that` BESIDE `que` (#161). Every verb in this row already spoke both
                       # languages — `record`, `note` — and the CONNECTOR did not, so "record on
                       # requirement 4 that we will use postgres" matched nothing while its
                       # Portuguese twin matched. A row is bilingual at its narrowest point, not
                       # at its widest.
                       r"(?:\s*(?:que|that|:|—|-|,)\s*)(?P<decision>[^\n]{5,400})",
        re.IGNORECASE)),
    # "não vamos mais fazer o requisito 2" / "cancela o requisito 2" / "esquece o requisito 2" —
    # the act with no replacement, and the one the lifecycle had no word for. Until this existed the
    # only way to retire anything was to WRITE SOMETHING ELSE, so "we decided against it" had to be
    # dressed up as a new requirement nobody wanted.
    #
    # THREE SHAPES BECAUSE PEOPLE SAY ALL THREE, and the negated one ("não vamos mais fazer") cannot
    # share a pattern with the imperatives: it is the only one whose verb is ordinary — "fazer" —
    # and matching that verb loosely would turn "vamos fazer o requisito 2" into an abandonment.
    # The negation is therefore required and anchored, never inferred.
    #
    # An optional REASON is captured off the tail. It is what makes the record answer "why aren't we
    # doing this?" in six months instead of pointing at a status field and a date.
    ("drop", re.compile(
        _NOT_NEGATED + r"\b(?:cancel[ae]|abandon[ae]|descart[ae]|esque[çc][ae]|arquiv[ae]|drop)\b"
                       r"[^\d]{0,40}" + _requirement("number")
        + r"[\s,.:—-]*(?P<reason>.{0,300})$",
        re.IGNORECASE | re.DOTALL)),
    # NO `_NOT_NEGATED` ON THESE TWO: the negation is INSIDE them and is what they mean. A guard
    # against a preceding "não" would be a second negation reading the first one's meaning.
    ("drop", re.compile(
        r"(?:\bn[ãa]o\s+(?:vamos|vou|iremos|precisamos|pretendo|pretendemos)\s+"
        r"(?:mais\s+)?(?:fazer|construir|entregar|seguir\s+com|implementar)"
        # THE ENGLISH IDIOM, which this row did not have (#161). Same shape, same meaning, and
        # the same reason it must be anchored: the verb is ordinary — "build", "do" — so only the
        # negated form may match, or "we are building requirement 4" would retire it.
        r"|\b(?:we|i)\s*(?:'re|'m|\s+are|\s+am)?\s+not\s+(?:going\s+to\s+)?"
        r"(?:build|do|deliver|ship|implement)(?:ing)?"
        r"|\b(?:we|i)\s+(?:won'?t|will\s+not)\s+(?:be\s+)?"
        r"(?:build|do|deliver|ship|implement)(?:ing)?"
        r")\b"
        r"[^\d]{0,40}" + _requirement("number")
        + r"[\s,.:—-]*(?P<reason>.{0,300})$",
        re.IGNORECASE | re.DOTALL)),
    # "o requisito 2 não vale mais" / "o requisito 2 saiu de escopo" — the object first, which is
    # how somebody says it when the requirement is what they were already talking about.
    ("drop", re.compile(
        # `requirement` BESIDE `requisito` here too: this row spelled the noun itself in one
        # language, so no English sentence could reach it whatever it said (#161).
        r"\b(?:the\s+|o\s+)?(?:requisito|req|requirement)\s*#?(?P<number>\d{1,4})\s+"
        r"(?:n[ãa]o\s+(?:vale|serve|entra)\s+mais|saiu\s+de\s+escopo|"
        r"est[áa]\s+cancelad\w*|foi\s+cancelad\w*"
        r"|is\s+(?:out\s+of\s+scope|cancell?ed|dropped"
        r"|no\s+longer\s+(?:needed|wanted|valid|in\s+scope))"
        r"|(?:was|has\s+been)\s+(?:cancell?ed|dropped))\b"
        r"[\s,.:—-]*(?P<reason>.{0,300})$",
        re.IGNORECASE | re.DOTALL)),
    # "fecha o #511 como duplicado do #288" / "encerra o #511 em favor do #288" — the everyday PO
    # act the board had no operation behind. On 2026-07-31 the decision to close #511 in favour of
    # #288 was taken and confirmed by the client, the agent answered "registrado o pedido junto ao
    # time", and nothing existed to record it: the sentence matched no intent, fell through to
    # conversation, and the client was invited to check a request that did not exist. The next
    # queue proposal then put #511 first.
    #
    # The card it is closed in favour of is OPTIONAL: closing a card that simply will not be done
    # is the same gesture with nothing surviving it, and forcing a second number would push people
    # back to prose — which is where the missing operation was hiding in the first place.
    ("close", re.compile(
        _NOT_NEGATED + r"\b(?:fech[ae]|encerr[ae]|close)\b" + _ATTACHED + _card("number")
        + _IN_FAVOUR_OF + _BECAUSE,
        re.IGNORECASE)),
    # "o #511 é duplicado do #288" — the object first, which is how somebody says it when the card
    # is what they were already talking about. No verb: the duplication IS the instruction, and
    # this is the shape the real conversation used.
    ("close", re.compile(
        # `is`/`are` BESIDE `é`/`são` (#161): the whole row is one copula wide, and it spoke one
        # language — so "card 511 is a duplicate of 288" fell through to conversation while its
        # Portuguese twin closed the card.
        _NOT_NEGATED + _card("number") + r"\s+(?:[ée]|eh|s[ãa]o|is|are)\s+(?:an?\s+|uma?\s+)?"
        r"(?:" + _DUPLICATE_NOUN + r")" + _ATTACHED
        + r"(?:" + _card("in_favour_of") + r"|(?P<in_favour_of_unclear>\d{1,4})\b)",
        re.IGNORECASE)),
    # "alinha o #288 ao requisito 6" — rewrite what this card must satisfy FROM that requirement,
    # and cite it. The gap it closes: REQ-0004 was replaced by REQ-0006 and thirteen open cards
    # still execute the retired text, under a printed rule telling whoever works them not to go
    # beyond it.
    #
    # BOTH numbers are required, and that is the whole separation from `refine`: `refine` owns the
    # identical sentence WITHOUT a requirement in it, and the two are different acts. One writes
    # where nothing was written; this one REPLACES what somebody may already have worked from, so
    # it is staged for a confirmation and never runs on a hunch.
    ("align", re.compile(
        _NOT_NEGATED + r"\b(?:re)?alinh[ae]\b" + _ATTACHED + _card("number")
        + r"[^\d]{0,30}" + _requirement("requirement"),
        re.IGNORECASE)),
    # "align #288 to requirement 6" — the voice's own English instruction, verbatim (#24 item 5).
    # The preposition is REQUIRED ("to/with/against"): "align" floats free in English prose, and
    # the taught sentence always carries it.
    ("align", re.compile(
        _NOT_NEGATED + r"\b(?:re)?align\s+(?:the\s+)?" + _card("number")
        + r"\s+(?:to|with|against)\s+(?:the\s+)?" + _requirement("requirement"),
        re.IGNORECASE)),
    # "escreve os critérios do #288 a partir do requisito 6" — the same act said the long way, and
    # the reason `align` sits ABOVE `refine`: without the requirement this sentence is a refine,
    # with it the criteria are being derived from an agreed text instead of from the card's own
    # description.
    ("align", re.compile(
        _NOT_NEGATED + r"\b(?:(?:reescrev|escrev|defin|atualiz|ajust|corrig)[ae]"
                       r"|(?:re)?write|define|update|adjust|fix)\s+(?:os\s+|the\s+)?"
        r"(?:crit[ée]rios?|criteria|criterion)\b" + _ATTACHED + _card("number")
        + r"[^\d]{0,40}" + _requirement("requirement"),
        re.IGNORECASE)),
    # "escreve os critérios do #412" / "refina o #412" — the door `refine` never had. It is the one
    # capability here that EDITS a client's ticket; it was written, tested and reached by nothing,
    # while `triage` already finds exactly the tickets it fixes (`no-criteria`). The role could see
    # the problem it was built to solve and had no way to act on it.
    # Requires the number: rewriting the wrong ticket is not a typo to shrug at.
    #
    # THE INTENT THE PREAMBLE REGRESSION ACTUALLY HAPPENED TO, and the one it went on being anchored
    # on. "Nina, boa observação — e sim, refina o #523" is the sentence quoted at the top of this
    # file: it matched nothing, fell to conversation, and a requirement nobody asked for was drafted
    # from it. The number here may be written bare ("define os critérios do 412"), which only holds
    # because `_ATTACHED` keeps it welded to the gesture — a loose one would read the day out of
    # "refina isso pra mim até o dia 3".
    ("refine", re.compile(
        # THE NOUN IN BOTH LANGUAGES (#161). `refin[ae]` reaches English "refine" by an accident
        # of morphology, and the criteria phrasings did not reach it at all.
        _NOT_NEGATED + r"\b(?:refin[ae]"
                       r"|(?:re)?(?:escrev[ae]|write)\s+(?:os\s+|the\s+)?"
                       r"(?:crit[ée]rios?|criteria)"
                       r"|(?:defin[ae]|define)\s+(?:os\s+|the\s+)?"
                       r"(?:crit[ée]rios?|criteria))\b" + _ATTACHED
        + r"#?(?P<number>\d{1,4})\b",
        re.IGNORECASE)),
    # the brownfield first pass
    # Two shapes, because people say both: the verb ("documenta o que existe") and the noun with a
    # helper verb ("faz o levantamento do código"). Anchoring on only one of them missed the other,
    # which is the sort of gap that reads as "it just doesn't work".
    ("baseline", re.compile(
        _START + r"(?:(faz(er)?|faça|roda(r)?|rode|come[çc](a|ar|e)|start)\s+(o|a|um|uma)?\s*)?"
                 r"(document\w*|levant\w*|mapei\w*|mapeamento|engenharia reversa|survey)\b"
                 r".{0,40}\b(produto|c[óo]digo|codigo|que (j[áa] )?existe|sistema|code|product)\b",
        re.IGNORECASE)),
    # "anota que a firma usa Primavera" — dictating a fact to the person who keeps the record.
    # EXPLICIT on purpose: extracting facts from every message would be noisy, expensive, and
    # wrong exactly when it matters (a hypothetical discussed is not a fact learned). "Anota que"
    # is the natural gesture of telling your PO to write something down; what follows the verb IS
    # the fact, captured whole.
    ("fact", re.compile(
        _START + r"(?:(anot[ae]|registr[ae]|lembr[ae](?:-se)?|para constar|note down|remember)"
                 r"\s+(?:a[íi]\s+)?(?:que|:|that)?)\s*(?P<fact>.{10,400})$",
        re.IGNORECASE | re.DOTALL)),
    # "o que entra agora?" — the product owner's own question, and the one that keeps a factory
    # from sitting idle beside a full backlog.
    # The queue-word group is REQUIRED. Optional, it made bare "o que fazemos" a trigger — so
    # "o que fazemos com esse erro de ontem?" answered with a queue proposal ending in "Aprovo?",
    # and STAGED a pending whose admin "sim" would promote tickets (spend money) in a thread where
    # nobody mentioned the queue. A question about an incident must never arm the spend gate.
    ("queue", re.compile(
        _START + r"(?:(o )?que (entra|vem|fazemos|come[çc]amos)|pr[óo]xim[ao]s?|"
                 r"sugere?|sugir|monta|prioriz\w*|what.s next|next up)\b"
                 r".{0,30}\b(agora|seguir|fila|todo|to-?do|sequ[êe]ncia|next|queue)\b",
        re.IGNORECASE)),
    # "pode começar?" / "vamos tocar isso" / "bora começar" — HOW A CLIENT ASKS FOR THE THING the
    # queue gesture above is named after. Every word in that pattern is operator vocabulary
    # ("próximos", "fila", "TO-DO", "sequência"), and a client saying the ordinary sentence fell
    # through to conversation — where the role reads it as A REQUEST and offers to draft a NEW
    # REQUIREMENT to somebody who just asked to start the work already agreed. Answering "shall I
    # write that down?" to "can we start?" is the surface admitting its vocabulary is not the
    # client's.
    #
    # THE SAME GESTURE, SO THE SAME GATE: this stages a queue proposal, and an approver's yes is
    # what spends money. Nothing here reaches the pipeline on the match alone.
    #
    # END-ANCHORED, unlike its sibling above, and that is the whole defence. "vamos começar" IS the
    # gesture; "vamos começar a discutir o relatório de julho" is a plan for a conversation, and
    # arming the spend gate off it is precisely what the queue pattern's own comment warns about.
    # So the clause must END at the verb, give or take a particle people actually append.
    # THIS IS A SHORTCUT, NOT A GATE — and that changed after it failed on the first real use.
    # "podemos avançar?" carried none of these verbs, so the gesture fell through to conversation.
    # The list below is now an OPTIMISATION (one model call instead of two when it matches); the
    # escape is `role.QUEUE_MARKER`, declared by the model that reads every word of the message.
    # Adding verbs here is still worth it — it is free and it keeps the common phrasings cheap —
    # but a word missing from it costs a round trip now, not the gesture.
    ("queue", re.compile(
        _START + r"(?:pode(?:mos)?|posso|podia|vamos|bora|d[áa]\s+pra|"
                 r"can\s+we|shall\s+we|let'?s|should\s+we)\s+"
                 r"(?:j[áa]\s+)?(?:come[çc]ar|iniciar|tocar|arrancar|avan[çc]ar|seguir|"
                 r"prosseguir|andar|start|begin|proceed|move\s+on|get\s+going)\b"
                 r"(?:\s+(?:isso|iss[ao]\s+a[íi]|o\s+trabalho|as\s+tarefas|this|the\s+work))?"
                 r"(?:\s+(?:ent[ãa]o|j[áa]|agora|logo|hoje|amanh[ãa]|now|then|today))?"
                 r"\s*[?!.…]*\s*$",
        re.IGNORECASE)),
    # End-anchored: "como está A CORREÇÃO DAQUELE PROBLEMA?" is a question about one thing and
    # deserves an answer about that thing, not the whole board's status line.
    ("status", re.compile(
        _START + r"(status|situa[çc][ãa]o|como (est(á|a)|estamos|vai))\s*[?!.\s]*$",
        re.IGNORECASE)),
)


#: THE CLAUSE ANCHOR IS APPLIED HERE, ONCE, over the whole table. Written into eleven patterns by
#: hand it would be eleven chances to leave one out — and "the rule that reached one gesture and not
#: its siblings" is the defect this file exists downstream of, committed twice already. A pattern
#: that anchors at `^` already says where it begins and is left exactly as it is.
_INTENTS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, pattern if pattern.pattern.startswith("^") else re.compile(
        _CLAUSE_START + ("" if name in _UNCONFIRMED else _BRIDGE) + pattern.pattern, pattern.flags))
    for name, pattern in _PATTERNS)


#: The intents matched ANYWHERE in the message rather than at its start. Scanning is what lets a
#: preamble through; it is also what lets a QUESTION through, which anchoring used to prevent for
#: free. "quando fecha o #511?" is somebody asking, and the two mistakes still do not cost the
#: same: a miss is a rephrase, while a false positive stages an irreversible act against a card in
#: the client's name — and displaces whatever else was awaiting confirmation in the thread.
#:
#: DERIVED FROM THE PATTERNS, NEVER MAINTAINED BESIDE THEM. This was a hand-written set, and the
#: hand-written set was the defect: `close` and `align` were widened and listed here, the intent
#: the regression had actually happened to was not, and the two facts sat four lines apart looking
#: consistent. A pattern that does not anchor at `^` is scanned, and now cannot be scanned quietly.
_SCANNED = frozenset(name for name, pattern in _PATTERNS if not pattern.pattern.startswith("^"))


def _asks_rather_than_tells(text: str, end: int) -> bool:
    """Whether the gesture that ended at `end` sits inside a question.

    The CLAUSE decides, not the message: "Nina, o que você acha? fecha o #511 como duplicado do
    #288" is a question followed by an instruction, and reading the whole message would throw the
    instruction away with it.
    """
    terminator = re.search(r"[.!?;\n]", text[end:])
    return bool(terminator) and terminator.group(0) == "?"


def _gesture_end(m: re.Match) -> int:
    """Where the GESTURE ends — at the number it names, not at the end of the match.

    Several of these patterns swallow the rest of the message into a `reason`, so reading the
    question mark from `m.end()` looked past the whole sentence and found nothing: "cancela o
    requisito 2, isso ainda faz sentido?" is somebody wondering aloud, and it matched as an
    instruction to retire a requirement.
    """
    try:
        end = m.end("number")
    except (IndexError, re.error):
        return m.end()
    return end if end >= 0 else m.end()


def _unquote(value: str) -> str:
    """A capture with the quotation the person copied around it taken off.

    The clause anchor admits `_QUOTES` so a client can type the sentence exactly as it was shown to
    them. The other half of that is here: a capture is free text that travels ONWARD — `drop`'s
    reason is written onto the record in the client's name and read back to them — so a stray »
    must not become the grounds on which somebody decided something.
    """
    return value.strip().strip(_QUOTES).strip()


def match_intent(text: str) -> tuple[str, dict] | None:
    """`(intent, captures)`. The captures matter for the intents that name a thing: filing work for
    the wrong requirement is not a typo to shrug at."""
    body = text or ""
    for name, pattern in _INTENTS:
        m = pattern.search(body)
        if not m:
            continue
        if name in _SCANNED and _asks_rather_than_tells(body, _gesture_end(m)):
            # `continue`, not `return None`: a question about closing a card is still allowed to be
            # some other intent further down (a status, a queue proposal). Refusing this gesture
            # must not make the whole message unmatchable.
            continue
        groups = m.groupdict() or {}
        captures = {}
        for key, value in groups.items():
            trimmed = _unquote(value) if value else ""
            if trimmed:
                captures[key] = trimmed
        # KEYED ON THE GROUP THE PATTERN DECLARES, not on the intent's name. Whichever gesture can
        # carry a survivor asks this question, and one written later cannot forget to — a set kept
        # beside the fact it describes is what this file has already paid for twice.
        if ("in_favour_of_unclear" in groups and not captures.get("in_favour_of")
                and not captures.get("in_favour_of_unclear")):
            other = _other_card_named(body, captures.get("number", ""))
            if other:
                captures["in_favour_of_unclear"] = other
        return name, captures
    return None
