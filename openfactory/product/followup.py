"""The product role following through (ADR-0021) — the half she did not have.

Her memory was genuinely good where it was designed to be: requirements and domain facts live in a
git repository, versioned, attributed, reviewable. What she had no record of was what she ASKED.

A question put to a person in the channel was fire-and-forget. If nobody answered, it was simply
gone — and the requirement it was blocking waited for ever with nobody aware, which is the exact
shape of the failure a product owner exists to prevent. She also never learned whether a
requirement she wrote became work, or whether that work shipped, so she could never say the two
sentences the job is actually made of: **this is stuck on you**, and **this is done**.

TWO LOOPS, AND BOTH CLOSE BY OBSERVATION — no new integration, no reading anybody's replies:

    question   she asks about a specific ticket   closes when that finding is gone from the board
    delivery   a requirement became filed work    closes when all of that work is closed

The question loop is the one worth explaining. It would be tempting to close it when somebody
replies in Slack, which needs conversation history, a token scope, and a rule for what counts as an
answer. But "did they answer?" is not the question a product owner cares about — **"did the thing
get fixed?"** is. A ticket that gained its acceptance criteria is answered whether or not anybody
typed a word back, and a polite reply that changed nothing is not an answer at all.

AND SHE NAMES THE PERSON. `people.mention` has existed, tested, since the product role shipped, and
was called by nothing — so every question she asked was addressed to the room. "Somebody should
clarify #412" is a message everybody reads and nobody owns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from openfactory.contracts.refs import canonical_ref
from openfactory.memory.ledger import ACCEPTANCE, DELIVERY, QUESTION, Loop, open_loop

OWNER = "product"

#: How long a question waits before she reminds the person once. DAYS, not hours: a product owner
#: who chases the morning after is not diligent, they are exhausting, and the requirement they are
#: chasing about was rarely urgent enough to justify it.
CHASE_AFTER_HOURS = 48.0

#: How many questions one pass may ask. A cap, and the reason is the first real sweep: a board
#: with 52 backlog cards produced THIRTEEN questions in one burst — thirteen separate messages,
#: which is not a colleague asking something, it is an inbox event. Nobody answers thirteen
#: questions; they mute the channel, and then the fourteenth — the one that mattered — is unread.
#: The rest are not lost: they are still findings in the weekly report, and the next pass asks the
#: next few once these are resolved.
MAX_QUESTIONS_PER_PASS = 3

#: Findings worth putting to a NAMED person rather than reporting to the room. Everything triage
#: notices is worth writing down; only some of it is worth interrupting somebody about, and the
#: difference is whether one identifiable person can resolve it.
#:
#: THESE ARE triage.py's OWN WORDS, and a test derives that module's vocabulary from its source and
#: asserts this is a subset. The first version of this tuple was invented here — five plausible
#: codes, ONE of which triage actually emits — and it read a `.code` attribute Observations do not
#: have. Both mistakes are the same mistake: writing both sides of a boundary from memory instead
#: of reading the side that already existed. The question loop shipped fully inert, eleventh
#: instance of the built-tested-reached-by-nothing class, and the only reason it was caught is
#: that the author went looking for it before anybody trusted it.
#:
#: `closed-elsewhere` and `container-complete` are deliberately absent: those are board hygiene the
#: report already covers, not something one identifiable person is sitting on.
ASKABLE = ("no-criteria", "stalled", "waiting-too-long", "done-but-open")


@dataclass(frozen=True)
class Question:
    """One thing she needs from one person."""

    ticket: str
    code: str
    text: str
    person: str = ""
    #: the card's own title — carried so the question can NAME what it is about. "sobre o #412"
    #: alone, in a channel whose audience does not open the board, is a question nobody can even
    #: understand, let alone answer.
    title: str = ""


def questions_from(findings, tickets, *, language: str | None = None) -> list[Question]:
    """What is worth asking a person, and who to ask.

    The assignee first, then whoever the board says owns it. Never a guess: an unowned finding is
    still asked, addressed to the channel, because an unowned problem is still a problem — it just
    cannot be anybody's to answer until somebody claims it."""
    # KEYED CANONICALLY (C-05). The two sides reach here from different readers — the findings from
    # triage, the cards from the board — and `#412` against `412` is a miss that shows up as a
    # question addressed to nobody rather than as an error.
    by_number = {canonical_ref(t.number): t for t in tickets}
    out: list[Question] = []
    for finding in findings:
        # `.kind` and `.detail` are triage.Observation's real field names — never aliased here,
        # so a rename there breaks THIS line and the vocabulary test, not the behaviour in prod.
        code = str(finding.kind)
        if code not in ASKABLE or not finding.ticket:
            continue
        ticket = by_number.get(canonical_ref(finding.ticket))
        assignees = [a for a in (getattr(ticket, "assignees", []) or [])
                     # the factory assigns ITSELF on pickup, so a stalled ticket's assignee is
                     # usually the bot — and the sweep once addressed a question to the robot, by
                     # name, in front of the client. A bot is never "the person who can answer".
                     if "bot" not in str(a).lower()]
        # `stalled` means the FACTORY is holding it (in progress, untouched) — the person listed
        # on the card did not go quiet, the machine did. That question belongs to the room.
        person = "" if code == "stalled" else (assignees[0] if assignees else "")
        # The client hears the QUESTION, in their language — never triage's own prose. The detail
        # is English platform vocabulary ("no acceptance criteria…"), two kinds of which carry
        # words from the jargon list; it shipped verbatim until a reviewer caught it.
        from openfactory.product.voice import question_for

        out.append(Question(
            # `int(...)` sat here and the field is typed `str` — a frozen dataclass validates
            # nothing, so the annotation was decoration and this line would have raised on the
            # first Jira ref, inside the sweep, taking every other question down with it.
            ticket=canonical_ref(finding.ticket), code=code, text=question_for(code, language),
            person=person, title=str(getattr(ticket, "title", "") or ""),
        ))
    return out


def to_open(questions: list[Question], waiting: list[Loop], *, ts: str) -> list[Loop]:
    """Loops for questions she is not already waiting on.

    Asking the same thing twice is how a channel teaches people that her messages are noise — and
    it is indistinguishable, from the reader's side, from an agent that is not paying attention."""
    already = {(loop.subject, loop.about) for loop in waiting if loop.kind == QUESTION}
    fresh = [
        open_loop(QUESTION, str(q.ticket), owner=OWNER, about=q.code, ts=ts,
                  context={"person": q.person, "asked": q.text[:300], "title": q.title[:120]})
        for q in questions
        if (str(q.ticket), q.code) not in already
    ]
    # Capped counting what is ALREADY open, not just what is new: three fresh questions a week on
    # top of ten unanswered ones is the same flood arriving slowly.
    room = max(0, MAX_QUESTIONS_PER_PASS - len([x for x in waiting if x.kind == QUESTION]))
    return fresh[:room]


def answered(waiting: list[Loop], live_keys: set[str]) -> dict[tuple[str, str, str], str]:
    """Which open questions the board has resolved — `{(kind, subject, about): outcome}`.

    `live_keys` is every `ticket:code` triage still reports. A question whose finding is gone was
    answered by the world, which is the only kind of answer that counts here.

    KEYED PER QUESTION, not per ticket: a ticket stalled for two weeks with no criteria holds TWO
    open questions, and the first version of this closed both the moment either resolved — the
    surviving problem died silently and was never chased again. Both reviewers found that hole
    independently, from opposite ends."""
    return {
        (QUESTION, loop.subject, loop.about): "resolved"
        for loop in waiting
        if loop.kind == QUESTION and f"{loop.subject}:{loop.about}" not in live_keys
    }


def deliveries_to_open(filed: dict[int, list[str]], waiting: list[Loop], *,
                       ts: str) -> list[Loop]:
    """A loop per requirement that just became work. `filed` is `requirement → issue numbers`."""
    already = {loop.subject for loop in waiting if loop.kind == DELIVERY}
    return [
        open_loop(DELIVERY, str(req), owner=OWNER, ts=ts,
                  context={"issues": ",".join(str(i) for i in issues)})
        for req, issues in sorted(filed.items())
        if str(req) not in already and issues
    ]


def delivered(waiting: list[Loop], closed_issues: set[str]) -> dict[tuple[str, str, str], str]:
    """Requirements whose work is now ALL closed.

    All, not some: telling somebody their requirement is done while half of it is still open is the
    single fastest way to make every future "it's done" worthless."""
    out: dict[tuple[str, str, str], str] = {}
    for loop in waiting:
        if loop.kind != DELIVERY:
            continue
        # THE PROVIDER'S REFS, COMPARED AS THEY WERE WRITTEN (C-05). `int(n)` sat here, which
        # raises on a Jira ref and would take the whole sweep down — and the set it is
        # compared against is built from `Ticket.number`, a string. A subset test between a
        # set of ints and a set of strings is never true, so no delivery would EVER be
        # announced: silence, which is the one failure this loop exists to prevent.
        issues = {canonical_ref(n) for n in (loop.context.get("issues") or "").split(",")
                  if n.strip()}
        if issues and issues <= closed_issues:
            out[(DELIVERY, loop.subject, loop.about)] = "delivered"
    return out


#: Why she is asking at all. Said ONCE per batch, never per question: three questions each
#: carrying the same closing paragraph is what the product owner saw in the channel on 2026-07-28:
#: the justification stops being a reason and becomes wallpaper, and the messages read as a bot
#: looping rather than a colleague asking.

#: THE PLATFORM'S OWN WORDS, PER LANGUAGE (#160). Every composer below wrote Brazilian Portuguese
#: unconditionally — on a surface that reaches whoever the registry says this client is, in a
#: product whose `DEFAULT_LANGUAGE` is English. An English-speaking client was going to be
#: asked, in Portuguese, whether a delivery worked.
#:
#: TRANSLATED IN A TABLE, NEVER GENERATED, for the reason `voice.py` gives beside its own: these
#: are the strings whose jargon-freedom is asserted, and a model-produced translation puts exactly
#: the operator vocabulary this surface exists to keep out back into the client's channel, in a
#: language nobody is checking.
_WHY_ASKING_T = {
    "pt-BR": ("Enquanto isso não estiver claro eu não consigo transformar isso em trabalho "
              "sem chutar, e prefiro perguntar."),
    "en": ("Until this is clear I cannot turn it into work without guessing, and I would rather "
           "ask."),
}
_ONE_LINE = {
    "pt-BR": "{who}sobre o {about}: {asked}",
    "en": "{who}about {about}: {asked}",
}
_BATCH_HEAD = {
    "pt-BR": "{sig}tenho {n} coisas que preciso entender antes de transformar em trabalho:",
    "en": "{sig}there are {n} things I need to understand before I can turn this into work:",
}
_CHASE = {
    "pt-BR": ("{sig}{who}voltando no {about}, que perguntei há {days} dias: {asked}\n\n"
              "Se não for prioridade agora, tudo bem — me diga e eu paro de cobrar. "
              "Só não quero que fique parado sem ninguém saber."),
    "en": ("{sig}{who}coming back to {about}, which I asked about {days} days ago: {asked}\n\n"
           "If it is not a priority right now that is fine — tell me and I will stop chasing. "
           "I just do not want it sitting still with nobody aware of it."),
}
_ACCEPTANCE_Q = {
    "pt-BR": ("\n\nDeu para conferir? Se resolveu, é só me dizer que sim — se não resolveu, me "
              "conte o que ainda está errado que eu registro. Sem pressa: só não quero dar como "
              "resolvido o que ainda te atrapalha."),
    "en": ("\n\nDid you get a chance to check? If it works, just tell me so — if it does not, "
           "tell me what is still wrong and I will write it down. No rush: I only do not want to "
           "call something done while it is still getting in your way."),
}
_DECISION_CHASE = {
    "pt-BR": ("{sig}{who}ainda preciso de uma decisão sua sobre isto: {asked}\n\n"
              "Se não for prioridade agora, me diga e eu paro de perguntar — só não quero seguir "
              "como se estivesse decidido."),
    "en": ("{sig}{who}I still need a decision from you on this: {asked}\n\n"
           "If it is not a priority right now, tell me and I will stop asking — I just do not "
           "want to carry on as though it had been decided."),
}
_DELIVERED_DEFECT = {
    "pt-BR": "{sig}o problema que foi reportado aqui está corrigido — a correção já entrou no "
             "produto.",
    "en": "{sig}the problem reported here is fixed — the fix is in the product.",
}
_DELIVERED_REQ = {
    "pt-BR": "{sig}o que foi pedido no requisito {subject} está pronto — todo o trabalho que saiu "
             "dele foi concluído.",
    "en": "{sig}what was asked for in requirement {subject} is ready — all the work that came out "
          "of it is finished.",
}


_RELEASE_ABOUT = {"pt-BR": " do requisito {requirement}",
                  "en": " in requirement {requirement}"}
_RELEASE_WITH_ADDRESS = {
    "pt-BR": ("{sig}o que foi pedido{about} está pronto e já está no **ambiente de testes** — "
              "nada disso está valendo para os seus usuários ainda."
              "\n\nPara experimentar: {where}\n\n"
              "Dá uma conferida quando puder e me diga se funcionou. "
              "**Se funcionou, é o seu \"sim\" que coloca no ar** — se não funcionou, me conte "
              "o que ficou errado que eu devolvo para o time e nada sobe."),
    "en": ("{sig}what was asked for{about} is ready and is on the **test environment** — none of "
           "it is live for your users yet."
           "\n\nTo try it: {where}\n\n"
           "Have a look when you can and tell me whether it worked. "
           "**If it worked, it is your \"yes\" that puts it live** — if it did not, tell me what "
           "went wrong and I will send it back to the team and nothing goes out."),
}
_RELEASE_NO_ADDRESS = {
    "pt-BR": ("{sig}o que foi pedido{about} está pronto e já está no **ambiente de testes** — "
              "nada disso está valendo para os seus usuários ainda.\n\n"
              "Só que eu **não tenho o endereço** desse ambiente para te passar: o projeto não "
              "declarou onde é. Se você já sabe onde olhar, confere lá e me diga se funcionou. "
              "**Se funcionou, é o seu \"sim\" que coloca no ar** — se não funcionou, me conte o "
              "que ficou errado que eu devolvo para o time e nada sobe.\n\n"
              "Se não sabe onde olhar, peça ao time para colocar o endereço no "
              "`.openfactory/project.yaml` que da próxima vez ele vem junto."),
    "en": ("{sig}what was asked for{about} is ready and is on the **test environment** — none of "
           "it is live for your users yet.\n\n"
           "Except I **do not have the address** of that environment to give you: the project has "
           "not declared where it is. If you already know where to look, check there and tell me "
           "whether it worked. **If it worked, it is your \"yes\" that puts it live** — if it did "
           "not, tell me what went wrong and I will send it back to the team and nothing goes "
           "out.\n\nIf you do not know where to look, ask the team to put the address in "
           "`.openfactory/project.yaml` and next time it will come with the message."),
}


def _say(catalogue: dict[str, str], language: str | None) -> str:
    """One home for the fallback, shared with `voice._pick`: the language, then the deployment's
    default, then English — never a `KeyError` in a chat listener."""
    from openfactory.product.voice import _pick

    return _pick(catalogue, language)



def _one_line(loop: Loop, mention: str = "", *, language: str | None = None) -> str:
    who = f"{mention} — " if mention else ""
    title = (loop.context or {}).get("title", "")
    about = f"#{loop.subject} ({title})" if title else f"#{loop.subject}"
    return _say(_ONE_LINE, language).format(
        who=who, about=about, asked=loop.context.get("asked", ""))


def ask_text(loop: Loop, *, mention: str = "", agent_name: str = "",
             language: str | None = None) -> str:
    """How ONE question reaches the person, in the client's terms.

    A wrong mention is worse than none (see `people.py`), so `mention` is whatever that module
    resolved — a real `<@U…>` when it identified somebody, a plain name when it could not."""
    sig = f"{agent_name}: " if agent_name else ""
    return (f"{sig}{_one_line(loop, mention, language=language)}\n\n"
            f"{_say(_WHY_ASKING_T, language)}")


def ask_batch(pairs: list[tuple[Loop, str]], *, agent_name: str = "",
              language: str | None = None) -> str:
    """Every question a pass asks, as ONE message.

    Three separate posts, each repeating the same closing paragraph, is what actually reached the
    client channel — and it reads as a machine emptying a queue, not as somebody asking. One
    message, one reason, one line per ticket: the same information at a third of the noise, and
    each line still names its own person and its own card."""
    if not pairs:
        return ""
    if len(pairs) == 1:
        loop, mention = pairs[0]
        return ask_text(loop, mention=mention, agent_name=agent_name, language=language)
    sig = f"{agent_name}: " if agent_name else ""
    lines = [_say(_BATCH_HEAD, language).format(sig=sig, n=len(pairs)), ""]
    lines += [f"• {_one_line(loop, mention, language=language)}" for loop, mention in pairs]
    lines += ["", _say(_WHY_ASKING_T, language)]
    return "\n".join(lines)


def chase_text(loop: Loop, *, mention: str = "", agent_name: str = "", days: int = 2,
               language: str | None = None) -> str:
    """The one reminder. Says it is a reminder, so nobody reads it as a new question they missed.

    `days` is COMPUTED from when the loop opened, never hardcoded: the first version said "há dois
    dias" while the only caller runs weekly — every reminder a client ever read would have stated
    an interval that never happened, and a message caught once in a small lie discredits all the
    true ones."""
    who = f"{mention} — " if mention else ""
    sig = f"{agent_name}: " if agent_name else ""
    title = (loop.context or {}).get("title", "")
    about = f"#{loop.subject} ({title})" if title else f"#{loop.subject}"
    return _say(_CHASE, language).format(sig=sig, who=who, about=about, days=days,
                                        asked=loop.context.get("asked", ""))


#: How long before she nudges an unanswered "did it work?". Longer than a question's chase: the
#: person has to actually go and USE the thing before they can answer honestly.
ACCEPTANCE_AFTER_HOURS = 72.0


def acceptance_of(loop: Loop, *, ts: str) -> Loop:
    """The loop the delivery announcement opens. `subject` stays the requirement (or defect
    handle) so the two are traceable to each other; `about` carries the channel it was asked in.

    THIS IS THE LOOP THE ROLE IS NAMED AFTER. Everything before it — the board closing, the PR
    merging — is the factory agreeing with itself. Only this one asks the person who wanted the
    thing whether they got it, and it is the difference between a product owner and a status feed.
    """
    return open_loop(ACCEPTANCE, loop.subject, owner=OWNER, ts=ts,
                     about=(loop.context or {}).get("channel", ""),
                     context={"defect": (loop.context or {}).get("defect", ""),
                              "asked_by": (loop.context or {}).get("person", "")})


#: A denial marker anywhere. CHECKED FIRST and deliberately broad: the honest answer to "did it
#: work?" names the failure, and every one of these means the thing is not done. Failing towards
#: "not accepted" is the only safe direction — a wrongly-open loop costs one more question, a
#: wrongly-closed one claims success on the client's behalf.
_DID_NOT_WORK = re.compile(
    # LITERAL ACCENTED CHARACTERS, never \u escapes: these are RAW strings, where \u00e3 is six
    # literal characters and not "ã". Written that way, "não resolveu" matched no denial word,
    # fell through to the positive branch, and closed a COMPLAINT as an acceptance — found by
    # sabotaging an unrelated guard, which is the only reason it was found at all.
    #
    # NO TOKEN THAT IS ALSO A COMMON WORD OF THE OTHER LANGUAGE. This is a pt-BR surface with a
    # few English fallbacks, and English "no" is ALSO the Portuguese contraction em+o — so "sim,
    # resolveu no sistema" closed a delivery as REJECTED against a client who had just accepted
    # it. A borrowed token must be unambiguous across BOTH languages ("nope"/"still"/"broken"
    # collide with nothing); a bare English "no" now matches neither list and falls through to
    # the model judge (ADR-0029), which is where ambiguity belongs — never a closed verdict.
    r"\b(não|nao|negativo|continua|continuam|ainda|persiste|piorou|pior|quebrou|quebra|"
    r"errado|falhou|falha|nunca|nem|mas|porém|porem|entretanto|nope|still|broken)\b",
    re.IGNORECASE)

#: A word that ASSERTS THE THING WORKS. Deliberately narrow, and narrowed once already: the first
#: version accepted "ok", "beleza", "isso", "conferi" and "testei", so "ok, entendi" closed a
#: delivery as ACCEPTED and "testei" — which says a person tested and says nothing about the result
#: — did the same. A false accept is the expensive direction: it records that the client signed off.
#: Everything ambiguous now returns "" and is read by a model instead (ADR-0029).
_WORKED_CORE = re.compile(
    r"\b(sim|resolveu|resolvido|resolveram|resolvida|funcionou|funciona|funcionando|"
    r"yes|works|worked|fixed|solved)\b",
    re.IGNORECASE)

#: Tokens that CANNOT decide, because they mean one thing in a catalogued language and another in
#: a language nobody catalogued — or in Portuguese itself. Their presence returns "" and the model
#: judge reads the sentence (ADR-0029), which is where ambiguity has always belonged.
#:
#: THE RULE THE FILE ALREADY STATED, now enforced instead of worked around: "a borrowed token must
#: be unambiguous across BOTH languages". `no` was DROPPED for failing it (English/Spanish denial,
#: Portuguese preposition) — and dropping is what let `funciona` decide a Spanish complaint on its
#: own. A token that fails the test must be heard as doubt, not silence.
#:
#: NEGATORS ONLY, and the list was wrong once before this shipped: `ya` ("already") was in it, so
#: "ya funciona" — a Spanish ACCEPTANCE — was deferred as doubtful. "ya no funciona" is a
#: regression and "ya funciona" is a sign-off; the word that separates them is `no`, not `ya`.
#: A temporal adverb negates nothing.
_CANNOT_DECIDE = re.compile(
    r"\b(no|nada|ni|sin|pas|nicht|niet|non)\b",
    re.IGNORECASE)

#: Acceptance is a SHORT answer. "funcionou perfeitamente" is one; three sentences that happen to
#: contain "ok" are a conversation, and reading one as acceptance would close a delivery on a
#: passing word. Ten is generous for "sim, resolveu certinho, obrigado" and far below a paragraph.
_ACCEPTANCE_MAX_WORDS = 10


def acceptance_verdict(text: str) -> str:
    """`worked` | `did-not-work` | "" — the client's own words, never inferred from silence.

    "" for anything that is not a clear answer, which falls through to the normal conversation.
    Guessing here would close a loop the person never answered, and an acceptance nobody gave is
    worse than an open one: it is a claim of success made on their behalf — exactly what ADR-0021
    forbids ("closed by observation, never by self-report").

    DENIAL IS TESTED FIRST, because "não resolveu" and "funcionou mas ainda trava" both contain a
    working-word. A positive-first order would read a complaint as an acceptance, which is the one
    direction this must never fail in.
    """
    body = (text or "").strip()
    if not body or "?" in body:
        return ""
    words = re.findall(r"[a-zà-ú']+", body.lower())
    # THE LENGTH BOUND GUARDS BOTH DIRECTIONS. An answer to "did it work?" is short either way.
    # Without it here, "nao sei se isso funciona bem para o nosso caso, porque..." — a normal
    # sentence containing "nao" — would close a delivery as rejected, and a paragraph mentioning
    # "ok" in passing would close one as accepted. Both are the machine deciding what a person
    # meant from a stray word.
    if not words or len(words) > _ACCEPTANCE_MAX_WORDS:
        return ""
    if _DID_NOT_WORK.search(body):
        return "did-not-work"
    # AMBIGUITY IS A VERDICT OF ITS OWN, AND DROPPING IT IS THE BUG (#161). A token that cannot be
    # trusted was simply left out of both lists — and leaving it out lets the OTHER list decide
    # alone. Measured: Spanish "todavía no funciona" is three words, matches no unambiguous denial
    # ("no" is excluded above because it is also the Portuguese em+o), and hits `funciona` in the
    # positive list — so a COMPLAINT closed the delivery as the client's sign-off. Checked after
    # the denials, so an unambiguous "não" still wins in the safe direction.
    positive = _WORKED_CORE.search(body)
    if not positive:
        return ""
    # POSITION DECIDES, because a negator PRECEDES what it negates — in all four languages here.
    # An ambiguous token AFTER the positive word is the Portuguese locative ("resolveu NO
    # sistema"); the same token BEFORE it is the Spanish/English/French negation ("todavía NO
    # funciona", "no está funcionando"). Both readings are real, both were pinned by tests written
    # from live client replies, and dropping the token — which is what this did — let the positive
    # decide a complaint on its own.
    doubt = _CANNOT_DECIDE.search(body)
    if doubt and doubt.start() < positive.start():
        return ""
    return "worked"


def acceptance_question(loop: Loop, *, agent_name: str = "",
                        language: str | None = None) -> str:
    """Appended to the delivery announcement. One question, answerable in one word, with the exit
    stated — a person who cannot check right now must not feel chased."""
    return _say(_ACCEPTANCE_Q, language)


def _which(loop: Loop, *, ambiguous: bool) -> str:
    """Which delivery this is about — spelled out ONLY when more than one was awaiting an answer.

    With two open acceptances a bare "sim, funcionou" settles against the most recent one, and the
    client had no way to see which: a wrong guess closed the wrong delivery invisibly. Naming it
    makes the guess correctable, which is the whole difference. With one open it would be noise, and
    a channel that restates the obvious gets skimmed.
    """
    if not ambiguous:
        return ""
    if (loop.context or {}).get("defect"):
        return " (o problema que você reportou)"
    return f" (o requisito {loop.subject})"


def accepted_text(loop: Loop, *, agent_name: str = "", ambiguous: bool = False) -> str:
    sig = f"{agent_name}: " if agent_name else ""
    return (f"{sig}ótimo — considero encerrado então{_which(loop, ambiguous=ambiguous)}. "
            f"Obrigada por confirmar.")


def rejected_text(loop: Loop, *, agent_name: str = "", ambiguous: bool = False) -> str:
    sig = f"{agent_name}: " if agent_name else ""
    return (f"{sig}entendido — então NÃO está resolvido{_which(loop, ambiguous=ambiguous)}, e eu "
            f"não vou dar como entregue. Me conta o que ainda acontece que eu registro como "
            f"defeito contra a promessa que ficou por cumprir.")


#: How long a decision waits before one reminder. Longer than a question about a card: a decision
#: usually needs somebody to talk to somebody else.
DECISION_AFTER_HOURS = 48.0


def decision_chase_text(loop: Loop, *, mention: str = "", agent_name: str = "",
                        language: str | None = None) -> str:
    """The reminder. It REPEATS THE DECISION, because a person reading this days later has none of
    the conversation in front of them — "voltando naquilo que te perguntei" is a reminder only for
    somebody who already remembers, which is exactly who does not need one."""
    who = f"{mention} " if mention else ""
    sig = f"{agent_name}: " if agent_name else ""
    asked = (loop.context or {}).get("asked", "").strip()
    return _say(_DECISION_CHASE, language).format(sig=sig, who=who, asked=asked)


def acceptance_chase_text(loop: Loop, *, mention: str = "", agent_name: str = "") -> str:
    who = f"{mention} " if mention else ""
    sig = f"{agent_name}: " if agent_name else ""
    return (f"{sig}{who}voltando no que te entreguei: chegou a conferir? Um \"sim\" ou um "
            f"\"não resolveu\" já me basta — se não for prioridade agora, me diga e eu paro de "
            f"perguntar.")


def release_of(issue: str, *, channel: str, ts: str, requirement: str = "",
               where: str = "") -> Loop:
    """The loop that opens when a job parks waiting to go to production.

    An ACCEPTANCE loop, deliberately, rather than a kind of its own: it asks the same question
    ("did this work for you?"), it is read by the same judge, and it closes the same way — on the
    person's own words and never on silence. What makes it a RELEASE is the context, which is also
    the only thing that can make an answer spend money, so it is one narrow field rather than a
    parallel machine somebody has to keep in step.

    `subject` is the issue, because that is what the approval names when it is delivered.
    """
    return open_loop(ACCEPTANCE, f"release-{issue}", owner=OWNER, ts=ts, about=channel,
                     context={"release_issue": str(issue), "requirement": requirement,
                              "where": where, "channel": channel})


def requirement_behind(issue: str, waiting: list[Loop]) -> str:
    """The requirement whose delivery this issue belongs to, or "" — read off the OPEN loops.

    Free: the delivery loop already carries `requirement → issues`, and it is already in memory
    when this is asked. The alternative was another board read to fetch a title, on a path that
    runs every hour, against a quota shared with the poller and every job.

    "" when nothing claims it, and that is said rather than guessed: an issue filed by hand, or one
    whose delivery loop already closed, belongs to no requirement this can name — and naming the
    wrong one to a client is worse than naming none.
    """
    for loop in waiting:
        if loop.kind != DELIVERY:
            continue
        issues = str((loop.context or {}).get("issues") or "").split(",")
        if str(issue) in [i.strip() for i in issues]:
            return loop.subject
    return ""


def is_release(loop: Loop) -> str:
    """The issue this loop would release, or "" — the ONE reading of that context field.

    A second hand-written `.get("release_issue")` beside a branch that spends money is how the two
    drift; this file has already paid for a set maintained beside the fact it describes."""
    return str((loop.context or {}).get("release_issue") or "") if loop else ""


def release_question(*, requirement: str = "", where: str = "", agent_name: str = "",
                     language: str | None = None) -> str:
    """What the client reads when something is ready for them to try.

    NO PIPELINE VOCABULARY. "staging", "deploy", "aprovação de produção" and "release" are all
    operator words, and the whole point of this bridge is that the person who knows whether the
    change is right should not have to learn them. What they are told is: it is ready to try, here
    is where, and their answer is what puts it in front of everyone.

    AND IT SAYS WHAT THE YES DOES. A confirmation whose consequence is unstated is not one — this
    particular yes puts software in front of the client's own users, which is the largest thing
    anybody is asked to approve on this surface.
    """
    sig = f"{agent_name}: " if agent_name else ""
    about = _say(_RELEASE_ABOUT, language).format(requirement=requirement) if requirement else ""
    # AN EMPTY ADDRESS CHANGES THE SENTENCE, it does not just remove a line (#122). Without this
    # the message still said "dá uma conferida quando puder" with nowhere to confer — the reader
    # looks for a link, finds none, and concludes the platform is broken rather than that their
    # own project never declared where to look. Saying so is what gets it declared.
    table = _RELEASE_WITH_ADDRESS if where else _RELEASE_NO_ADDRESS
    return _say(table, language).format(sig=sig, about=about, where=where)


def delivered_text(loop: Loop, *, agent_name: str = "", language: str | None = None) -> str:
    """The sentence she could never say. Unprompted, because somebody asked for this weeks ago and
    has no reason to be watching a board to find out it happened.

    A DEFECT delivery is a different sentence. Its loop subject is `defeito-88` — an internal
    handle around a board issue number the client never sees — and the requirement template would
    have produced "o que foi pedido no requisito defeito-88 está pronto": a phrase about a number
    nobody recognises, for something nobody *asked* for (somebody complained). The person who
    reported a problem gets the sentence that closes THAT loop: the problem is fixed."""
    sig = f"{agent_name}: " if agent_name else ""
    if (loop.context or {}).get("defect"):
        return _say(_DELIVERED_DEFECT, language).format(sig=sig)
    return _say(_DELIVERED_REQ, language).format(sig=sig, subject=loop.subject)


def waiting_line(project_name: str, *, language: str | None = None) -> str:
    """What the product role is still waiting on, as one line — or "" when she is waiting on
    nothing, or when the ledger could not be read.

    THE READ AND THE SENTENCE, TOGETHER, IN THE PRODUCT PACKAGE (C-24). This lived inside the
    Slack channel, where it opened the memory store, filtered loop kinds and wrote Portuguese —
    an application's logic inside one provider's adapter, which is the layer model upside down.
    A channel asks the role what it is waiting on; it does not work it out.

    Never raises: a status that answers without this line is a smaller answer, and an exception
    inside a chat listener is not an answer at all."""
    try:
        from openfactory.memory import store as loop_store

        # `waiting` is imported HERE and not at module scope because this file already binds that
        # name as a parameter in `to_open` — a module-level import would shadow silently.
        from openfactory.memory.ledger import waiting as open_loops

        loops = open_loops(loop_store.read(project_name), owner=OWNER)
        questions = [x.subject for x in loops if x.kind == QUESTION]
        deliveries = len([x for x in loops if x.kind == DELIVERY])
        if not questions and not deliveries:
            return ""
        from openfactory.product.voice import still_waiting

        return still_waiting(questions=questions, deliveries=deliveries, language=language)
    except Exception as exc:  # noqa: BLE001 — the status still answers without this line
        import logging

        logging.getLogger("openfactory.product").info(
            "could not read the open loops for the status line (%s)", exc)
        return ""
