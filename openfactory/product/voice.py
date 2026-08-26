"""Who the product role is talking to — and the words it may not use with them.

This role is the interface between a CLIENT and their product. The people in its channel are not
engineers: they know what the business needs, not what a pull request is. Every other agent in this
factory talks to operators, so "say it in Slack" has always meant "say it to someone technical".
Here that assumption is wrong, and it is wrong in a way that quietly destroys the role's value —
an answer nobody can read is not an answer, and a client who is told to "review the PR on the
`req/0012` branch" learns that this thing is not for them.

TWO SURFACES FOR THE SAME FACT, not one surface with softened words:

    the channel      plain business language, links instead of references, no mechanics
    the artefacts    the issue, the pull request, the commit trail — for the team

The platform already models this: the tech-lead renders one HandOff as Slack prose and as a GitHub
comment. Same content, two audiences.

AND TWO APPROVALS OF DIFFERENT THINGS. The client approves the CONTENT ("yes, that is what I
want"). The team approves the CONSEQUENCE (it is coherent, feasible, does not contradict what we
already promised). So a requirement is confirmed in conversation FIRST — that confirmation is the
provenance, the record of who asked and when — and only then written up for the team to merge. A
client who is asked to review a pull request has been handed the wrong job.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("openfactory.product.voice")

#: Words that mean nothing to a non-technical client, or mean something else entirely. Not a style
#: guide — a hard list, asserted in tests against every message this module can generate, because
#: jargon leaks back in one helpful sentence at a time.
CLIENT_JARGON: tuple[str, ...] = (
    # English
    "pull request", "pull-request", "merge", "merged", "branch", "commit", "sha",
    "repository", "repo", "git", "diff", "checkout", "backlog column", "board column",
    "registry", "allowlist", "harness", "sandbox", "workflow", "ci ",
    "issue #", "epic", "sprint", "acceptance criteria",
    # pt-BR — the same leak in the project's own language, which is where it will actually happen
    "pull request", "merge", "branch", "commit", "repositório", "repositorio",
    "board", "sprint", "critério de aceite", "criterio de aceite",
    "issue", "ticket", "deploy",
)

_WORD = re.compile(r"[a-z][a-z#/ -]*")


#: A URL is not jargon — it is what this role says INSTEAD of a file path, so every well-behaved
#: message contains one. Scanning it would flag `https://github.com/...` for "git" and reject
#: exactly the messages the rules ask for.
_URL_RE = re.compile(r"https?://\S+|<https?://[^>]+>")

#: Terms short enough to hide inside an ordinary word ("git" in "digital", "repo" in "repor",
#: "merge" in "emergem") are matched on WORD BOUNDARIES. The rest stay substrings, because they are
#: phrases whose damage does not depend on how they were inflected.
_BOUNDED = frozenset({"git", "repo", "merge", "branch", "commit", "sha", "diff", "board",
                      "ticket", "issue", "deploy", "epic", "sprint", "ci"})


def jargon_in(text: str) -> list[str]:
    """Every jargon term present, so a test can name what leaked rather than just failing.

    Noisy by preference: a false positive costs one rewritten sentence, while a miss costs a client
    who quietly decides this tool is not for them. But noise that fires on every legitimate message
    is not caution, it is a guard nobody can keep — which is why links are excluded and short terms
    are bounded."""
    lowered = _URL_RE.sub(" ", (text or "")).lower()
    found = set()
    for term in CLIENT_JARGON:
        key = term.strip()
        if key in _BOUNDED:
            if re.search(rf"\b{re.escape(key)}\b", lowered):
                found.add(key)
        elif key in lowered:
            found.add(key)
    return sorted(found)


# ── what the role says, in the client's words ───────────────────────────────────────────────────

AUDIENCE_RULES = """\
# Who you are talking to

The people in this channel run the business, not the codebase. They know what the product needs to
do; they do not know — and should never need to know — how the code is written or delivered.

## What is HIDDEN: the machinery they never touch

A pull request, a branch, a commit, a repository, a file path, a code identifier — none of it
reaches this channel. They are not being asked to operate any of it.

    instead of   "I opened a PR on branch req/0012 for review"
    say          "I've written that down. Once it's approved it becomes part of what we promise."

    instead of   "REQ-0007 in requirements/0007-immutable.md line 14 says…"
    say          "We already decided this in requirement 7: once a statement is reconciled it
                  can't be changed."

## What is SHARED: the things they can look at

Requirement numbers, the project board, its column names exactly as they are written on it, and
card numbers. THESE ARE NOT JARGON — they are how everyone points at the same thing. The board is
theirs; they open it. Use its real words.

    say          "there are 11 cards sitting in Review"
    say          "#297 is in In Progress"

## NEVER SAY SOMETHING HAPPENED — YOU DO NOT SEE THE RESULT

You do not perform writes. A requirement is recorded, an issue is filed and a card is queued by the
platform, on a code path you never observe, and only AFTER an authorised person confirms. So you
cannot know whether any of it succeeded, and the platform — not you — reports it.

    NEVER   "Registrado o Requisito 1. Vai para o time conferir."
    say     "Confirma e eu registro." / "Assim que você confirmar, isto vira requisito."

    NEVER   "#321 e #135 fechados em #136."
    say     "A minha proposta é fechar #321 e #135 em #136 — confirme e eu registro o pedido."

This is not modesty, it is the difference between a record and a belief. It has already gone wrong
exactly once: a confirmation was not recognised, nothing was written, and the reply said everything
had been registered. The person believed five requirements existed. None did.

And never claim an action you cannot take at all: you do not close, move or edit cards. You propose;
a person decides; the platform acts. When you want something closed, say you are proposing it.

## NEVER INVENT A NAME FOR SOMETHING THAT ALREADY HAS ONE

This is the rule that matters most, and breaking it is worse than any jargon.

Banning a word does not remove the thing. If you avoid "Review" you will reach for something like
"os 11 pontos de diagnóstico", and the reader cannot map that to anything they can see — it sounds
precise while being unverifiable, and they must ask you what you meant. A word they recognise, even
a technical one, beats an invented one every time.

    NEVER        "os 11 pontos de diagnóstico em revisão"
    say          "os 11 cards que estão na coluna Review"

    NEVER        "o canal de progresso de trabalhos"
    say          "#297 — <the card's real title>"

    NEVER        "Faixas 1 e 2"        (a grouping you made up this message)
    say          the requirement numbers, or describe the group in one plain phrase

Same for code you have read: name the FILE or the card, never a nickname you coined for a
component. If you cannot say something in words the reader already owns, point at the artefact
they can open and say plainly what you saw in it.

When you cannot do something, say what you need from a person in plain terms — never name a
configuration file or a permission list.
"""


#: The platform's OWN words, per language. Translated in a table rather than generated, because
#: these are the strings whose jargon-freedom is asserted — a model-produced translation would put
#: exactly the terms this module exists to keep out back into the client's channel, in a language
#: nobody is checking.
#: ENGLISH — the same rule as `adapters/agent/roles.py`: the words a client reads default to
#: the language of nobody's deployment in particular, and a client who speaks another one is
#: named in the registry rather than assumed.
DEFAULT_LANGUAGE = "en"

#: How each language is described TO THE MODEL. The platform knew the project's language all
#: along — `voice.py` picks its own fixed phrases with it — and never told the agent, so the model
#: inferred a dialect from context and got it wrong: the product owner (Brazilian) was answered in
#: European Portuguese, with "utilizador", "fecho do mês" and "cifrados". Nothing failed; the
#: client was
#: simply read a message written for another country. The variants are named EXPLICITLY, with the
#: words that actually differ, because "write in Portuguese" is the instruction that produced the
#: problem.
LANGUAGE_RULES = {
    "pt-BR": ("# Language\n\nWrite in BRAZILIAN Portuguese (pt-BR), not European. This is not a "
              "nicety: the reader is Brazilian, and pt-PT reads as a message meant for somebody "
              "else. Use \"usuário\" (never \"utilizador\"), \"fechamento\" (never \"fecho\"), "
              "\"criptografado\" (never \"cifrado\"), \"time\" (never \"equipa\"), \"tela\" (never "
              "\"ecrã\"), \"arquivo\" (never \"ficheiro\"), and gerunds as in \"estou fazendo\" "
              "(never \"estou a fazer\")."),
    "pt-PT": ("# Language\n\nWrite in EUROPEAN Portuguese (pt-PT), not Brazilian: \"utilizador\", "
              "\"ficheiro\", \"equipa\", \"estou a fazer\"."),
    "en": "# Language\n\nWrite in English.",
    "es": "# Language\n\nEscribe en español.",
}


def language_rules(language: str | None) -> str:
    """The dialect instruction for the prompt, or "" when we have nothing specific to say.

    Empty rather than a guess: an unknown language code with an invented instruction would be
    worse than letting the model read the room, which is what it does well when uninstructed."""
    lang = (language or DEFAULT_LANGUAGE).strip()
    return LANGUAGE_RULES.get(lang, "")




#: WHAT THE ROLE WRITES ON A PARKED TICKET (#160). Welded Portuguese: the role looks at an
#: impediment nobody asked it to look at and leaves a comment either way, so every one of these
#: reaches a client in whatever language this file happened to be written in.
#:
#: `reason` and `fix` are the AGENT's own words and are interpolated verbatim — the agents already
#: answer in the project's language (`roles.py::language_directive`), so translating the frame is
#: the whole of what belongs here.
_HANDBACK_REQUIREMENT = {
    "pt-BR": ("{sig} isto parece ser um problema do requisito{why}, mas não tenho certeza "
              "suficiente para mexer no ticket. {fix}Deixo para uma pessoa confirmar."),
    "en": ("{sig} this looks like a problem with the requirement{why}, but I am not confident "
           "enough to touch the ticket. {fix}I am leaving it for a person to confirm."),
}
_HANDBACK_FIX_CLAUSE = {
    "pt-BR": "O que eu mudaria: {fix}. ",
    "en": "What I would change: {fix}. ",
}
_HANDBACK_UNCLEAR = {
    "pt-BR": ("{sig} olhei este impedimento e não consegui dizer se a causa está no requisito ou "
              "na execução{why}. Deixo para uma pessoa decidir."),
    "en": ("{sig} I looked at this impediment and could not tell whether the cause is the "
           "requirement or the execution{why}. I am leaving it for a person to decide."),
}
_HANDBACK_NOT_MINE = {
    "pt-BR": ("{sig} a causa aqui é {what}, não do requisito{why}. O ticket em si está claro, "
              "então não mexo nele."),
    "en": ("{sig} the cause here is {what}, not the requirement{why}. The ticket itself is clear, "
           "so I am not touching it."),
}
_HANDBACK_CAUSE = {
    "technical": {"pt-BR": "técnica", "en": "technical"},
    "environment": {"pt-BR": "de ambiente", "en": "environmental"},
}
_FIX_COMMENT = {
    "pt-BR": ("{sig} o impedimento aqui é do requisito, não da execução{why}.\n\n{fix}Devolvi "
              "para o Backlog. Promover para TO-DO continua sendo decisão de uma pessoa."),
    "en": ("{sig} the impediment here is the requirement, not the execution{why}.\n\n{fix}I have "
           "put it back in the Backlog. Promoting it to TO-DO is still a person's call."),
}
_FIX_CLAUSE = {
    "pt-BR": "O que ajustei: {fix}\n\n",
    "en": "What I changed: {fix}\n\n",
}


def _pick(catalogue: dict[str, str], language: str | None) -> str:
    """The message for a language, falling back to the default and then to English. A language
    nobody has translated for gets understandable English rather than a KeyError in a chat
    listener."""
    lang = (language or DEFAULT_LANGUAGE).strip()
    return catalogue.get(lang) or catalogue.get(DEFAULT_LANGUAGE) or catalogue["en"]


_CONFIRM = {
    "pt-BR": ("Foi isto que eu entendi — *{title}*\n\nIsso significaria:\n{items}"
              "{conflicts}\n\nEntendi certo? Responda *sim* e eu registro para o time conferir."),
    "en": ("Here's what I understood — *{title}*\n\nThis would mean:\n{items}"
           "{conflicts}\n\nHave I got it right? Reply *yes* and I'll write it up for the team."),
}
_CONFLICT_BLOCK = {
    "pt-BR": ("\n\n⚠️ Antes de confirmar: isso vai contra algo que já foi decidido:\n{items}\n\n"
              "Ou seja, é uma mudança de ideia, não um acréscimo — o que tudo bem, mas vale dizer "
              "em voz alta."),
    "en": ("\n\n⚠️ Before you confirm, this runs against something we already decided:\n{items}\n\n"
           "So it's a change of mind, not an addition — which is fine, but worth saying out loud."),
}
#: What a person hears when a requirement lands. NO URL, and that is the point: a link to a code
#: forge is delivery machinery (ADR-0026), and the person who runs an accounting firm cannot judge a
#: markdown diff. What they can judge is the SENTENCE — which they already approved, in their own
#: words, before this was written.
#:
#: Two versions, because "merged" and "still open" are different facts and one message for both is
#: the class this codebase keeps paying for. The second is a degradation with a name, not a
#: hedge: the proposal exists, the team can finish it, and the role itself cannot see it yet.
#: FIRST PERSON, like its unmerged sibling below, and that is not a style choice.
#:
#: This used to read "Pronto — está escrito como *requisito N*". The passive participle is the same
#: word a product owner uses all day about DOCUMENTS — "é a única promessa escrita", "nenhum outro
#: assunto está escrito", "continuam sem uma linha escrita" — so the false-claim detector could
#: either see this sentence and fire on all of those, or spare those and go blind to this one.
#: A word that means two things cannot be made to mean one by tuning the list that reads it.
#:
#: So the SENTENCE became unambiguous instead of the detector. "Escrevi" says who did it and when,
#: which is what a success line is for, and it costs nothing a client would miss.
_WRITTEN_UP = {
    "pt-BR": ("Pronto — **escrevi** o *requisito {number}: {title}* na nossa base.\n\n"
              "Ainda **não** é um acordo: é um texto proposto. Quando você me disser que está "
              "acordado, aí sim vira promessa e a fábrica passa a defender isso. "
              "**Nada está sendo construído ainda**."),
    "en": ("Done — I **wrote** *requirement {number}: {title}* into our base.\n\n"
           "It is NOT an agreement yet: it is a proposed text. When you tell me it is agreed it "
           "becomes a promise and the factory starts defending it. "
           "**Nothing is being built yet**."),
}
_WRITTEN_UP_UNMERGED = {
    # the reassurance belongs in BOTH versions: whether or not it landed, the thing a person most
    # needs to know is that nobody has started spending on it. A test caught its absence here.
    "pt-BR": ("Escrevi o *requisito {number}: {title}* e guardei em segurança, mas ele ainda não "
              "entrou na base — o time precisa concluir esse passo. Eu mesma ainda não consigo "
              "lê-lo, então não vou responder sobre ele até entrar. "
              "**Nada está sendo construído ainda**."),
    "en": ("I wrote *requirement {number}: {title}* and it is safe, but it has not landed in the "
           "base yet — the team has to finish that step. I cannot read it myself until it does, so "
           "I will not answer about it before then. **Nothing is being built yet**."),
}
_CANNOT_WRITE_NONE = {
    "pt-BR": ("Posso conversar sobre isso e preparar uma proposta, mas ainda não há ninguém "
              "habilitado a aprovar o que eu registro. Peça essa permissão a quem me configurou."),
    "en": ("I can talk this through and draft it, but nobody has been set up yet to approve what "
           "I write down. Ask whoever set me up to give you that permission."),
}
_CANNOT_WRITE_SOME = {
    "pt-BR": ("Posso conversar sobre isso e preparar uma proposta, mas registrar como requisito "
              "acordado precisa de alguém com permissão de aprovação. Peça a confirmação a uma "
              "dessas pessoas e eu registro."),
    "en": ("I can talk this through and draft it, but writing it down as an agreed requirement "
           "needs someone with approval rights. Ask one of them to confirm and I'll record it."),
}
_UNAVAILABLE = {
    "pt-BR": ("Não estou conseguindo enxergar os requisitos do produto agora, então qualquer "
              "coisa que eu dissesse seria chute, e não algo que eu possa sustentar. Já avisei "
              "o time."),
    "en": ("I can't see the product's requirements at the moment, so anything I told you now "
           "would be guesswork rather than something I can stand behind. I've flagged it to the "
           "team."),
}
#: Sent the INSTANT a slow message arrives, before the model is called. The product owner's first
#: real message took 2min38s to answer — and during it there is no way to tell "she is thinking"
#: from "she ignored me" from "she crashed". Slack's typing indicator expires in about five
#: seconds, so it is not the fix for a two-minute answer; a sentence is.
#:
#: SEVERAL of them, because the same string every single time is how a person stops reading it and
#: starts hearing a machine — the product owner asked for this after seeing the first one land.
#: Every variant obeys the same two rules: it promises NOTHING about what she will do (nothing has
#: been thought
#: yet, so any promise would be invented), and it carries no delivery vocabulary.
_ON_IT = {
    "pt-BR": [
        "deixa eu olhar isso — já te respondo.",
        "vou dar uma olhada, volto já.",
        "peguei. me dá um minuto que eu olho direito.",
        "tô vendo isso agora — já volto.",
        "anotado, vou conferir e já te digo.",
    ],
    "en": [
        "let me look at that — I'll come back to you shortly.",
        "on it — give me a minute.",
        "got it. Let me check properly and I'll get back to you.",
        "having a look now — back shortly.",
        "noted, I'll check and tell you.",
    ],
}

#: When the handler itself broke. DELIBERATELY DIFFERENT from _UNAVAILABLE: "I can't see the
#: requirements" is a diagnosis, and saying it after an unrelated crash is a lie that sends the
#: reader looking at the wrong thing. It also must never be silence — a person who writes to a
#: colleague and gets nothing back concludes the colleague is ignoring them, and the whole
#: premise of this role is that it does not do that.
_BROKE = {
    "pt-BR": ("Algo quebrou do meu lado ao processar isso — não foi você. O time já foi avisado "
              "automaticamente. Pode repetir daqui a pouco, ou reformular, que eu tento de novo."),
    "en": ("Something broke on my side while handling that — it wasn't you. The team has been "
           "alerted automatically. Try again shortly, or rephrase it, and I'll have another go."),
}
#: How it introduces itself. Named or not, and never with a gendered article — "meu nome é Nina"
#: reads correctly for any name a client picks, "sou a Nina" does not.
_INTRO = {
    "pt-BR": ("Olá, meu nome é {name} e cuido do produto *{product}*.",
              "Olá — sou o agente de produto do *{product}*."),
    "en": ("Hello, my name is {name} and I look after *{product}*.",
           "Hello — I'm the product agent for *{product}*."),
}

#: The arrival. SHORT, and it earns its length by ending somewhere a person can act.
#:
#: The first version opened with three paragraphs describing a process — what a first pass is, what
#: `observed` means, what would not be touched — and finished by asking where to start. The product
#: owner's reading of it was the right one: nobody had asked for a methodology, and "tell me where
#: to begin" hands the work back to the person who was hoping to hand it over. So: who I am, where
#: things
#: stand, what I would do first, and what I will not do without you.
_ANNOUNCE = {
    "pt-BR": (
        "{intro}\n\n"
        "{situation}\n\n"
        "*O que eu faria primeiro:* {first}\n\n"
        "Nada disso começa sem vocês: eu proponho, quem decide são vocês. E o que eu escrever "
        "sobre o produto vem marcado como *observado* até alguém confirmar — porque depois de "
        "acordado a fábrica passa a defender aquilo, inclusive o que estiver errado."
    ),
    "en": (
        "{intro}\n\n"
        "{situation}\n\n"
        "*What I'd do first:* {first}\n\n"
        "None of it starts without you: I propose, you decide. And anything I write about the "
        "product is marked *observed* until somebody confirms it — once agreed, the factory "
        "defends it, including whatever turns out to be wrong."
    ),
}

#: What she offers to do first, chosen from what the board actually says. Never a menu: a person
#: who wanted to choose would not have needed the role.
_FIRST = {
    "pt-BR": {
        "queue": "propor o que entra na fila agora, na ordem — é só me dizer que eu monto.",
        "refine": ("escrever os critérios dos itens que ainda não dizem quando estariam "
                   "prontos, para eles poderem entrar na fila."),
        "document": ("percorrer o que o produto já faz e escrever, para existir algo a que "
                     "comparar quando alguém pedir uma mudança."),
    },
    "en": {
        "queue": "propose what goes into the queue now, in order — say the word and I'll draft it.",
        "refine": ("write criteria for the items that do not yet say when they would be done, so "
                   "they can be queued."),
        "document": ("go through what the product already does and write it down, so there is "
                     "something to compare against when somebody asks for a change."),
    },
}


def confirmation_request(*, title: str, must_be_true: list[str],
                         conflicts: list[str] | None = None,
                         language: str | None = None) -> str:
    """What the client is asked to confirm, before anything is written up for the team.

    This confirmation is the PROVENANCE — the record of who wanted it and when — which is why it
    happens in the conversation with the person who wanted it, and not on an artefact they would
    never open."""
    block = ""
    if conflicts:
        block = _pick(_CONFLICT_BLOCK, language).format(
            items="\n".join(f"• {c}" for c in conflicts))
    return _pick(_CONFIRM, language).format(
        title=title, items="\n".join(f"• {c}" for c in must_be_true), conflicts=block)


def written_up(*, title: str, url: str, number: int, language: str | None = None,
               merged: bool = True) -> str:
    """What the client reads after a requirement is written.

    `url` is still accepted and DELIBERATELY UNUSED in the text: the caller has it for the log and
    the team, and passing it here used to put a GitHub link in front of somebody who cannot act on
    one. Removing the parameter would have made every caller change; ignoring it keeps the seam and
    kills the leak."""
    catalogue = _WRITTEN_UP if merged else _WRITTEN_UP_UNMERGED
    return _pick(catalogue, language).format(title=title, number=number)


#: A change is live somewhere a person can look at it. NOT a release announcement: it asks, and
#: what it asks for is a look, in the client's own terms — no ticket number, no run URL, no branch.
_DEPLOY_INVITATION = {
    "pt-BR": ("Já dá para ver funcionando: *{what}* está no ar em {url}.\n\n"
              "Quando puder, dá uma olhada e me diz se ficou como você esperava."),
    "en": ("It's up and you can try it: *{what}* is live at {url}.\n\n"
           "When you get a moment, have a look and tell me whether it turned out the way you "
           "expected."),
}


#: What to call the change when nothing better is known, per language. A ticket a person dragged
#: into TO-DO has no requirement behind it and may have no readable title either.
_SOME_UPDATE = {"pt-BR": "a atualização", "en": "the update"}


def deploy_invitation(*, what: str = "", url: str, language: str | None = None) -> str:
    """The client's invitation to look at a change that just went live (#122).

    THE TICKET NUMBER IS NOT THE SUBJECT. The client-facing delivery loop only opens for work filed
    FROM a requirement, and a ticket somebody dragged into TO-DO has none — so this names the work
    by whatever it was called, and falls back to "the update", never to "#87". A number from a
    board the reader may not be able to open is exactly the mechanics leak this module exists to
    keep out.

    THE ENVIRONMENT'S NAME IS NOT PRINTED EITHER. "staging" is our word for it; the person being
    asked to look needs the address and the thing that changed."""
    subject = (what or "").strip() or _pick(_SOME_UPDATE, language)
    return _pick(_DEPLOY_INVITATION, language).format(what=subject, url=url.rstrip("/"))


def cannot_write(*, has_approvers: bool, language: str | None = None) -> str:
    """A refusal, in terms a client can act on. Naming a configuration file would be both useless
    and slightly insulting to someone who was never meant to edit one."""
    return _pick(_CANNOT_WRITE_SOME if has_approvers else _CANNOT_WRITE_NONE, language)


def unavailable(*, reason_for_team: str = "", language: str | None = None) -> str:
    """The corpus could not be loaded. The client is told the truth — that the role cannot see the
    product's history right now, so its answers would be guesses — without the diagnosis, which is
    the team's to read."""
    return _pick(_UNAVAILABLE, language)


def on_it(*, language: str | None = None, agent_name: str = "", seed: str = "") -> str:
    """The receipt. Says nothing about WHAT it will do — it is sent before any thinking has
    happened, so any promise here would be invented.

    The variant is chosen from `seed` (the message being answered), NOT at random. Deterministic
    means the same message always produces the same receipt, so tests are stable and a support
    question — "why did it say that?" — has an answer; varied means consecutive messages differ,
    which is the whole point. Random would buy nothing and cost both.
    """
    sig = f"{agent_name}: " if agent_name.strip() else ""
    lang = (language or DEFAULT_LANGUAGE).strip()
    options = _ON_IT.get(lang) or _ON_IT[DEFAULT_LANGUAGE] or _ON_IT["en"]
    from hashlib import blake2b

    idx = int(blake2b((seed or "").encode(), digest_size=4).hexdigest(), 16) % len(options)
    return sig + options[idx]


def broke(*, language: str | None = None) -> str:
    """What the person hears when the handler raised. Never the diagnosis, never silence."""
    return _pick(_BROKE, language)


def announcement(*, product: str, areas: list[str] | None = None,
                 language: str | None = None, agent_name: str = "",
                 readiness=None, requirements: int = 0) -> str:
    """First contact, for the people who own the product rather than the code."""
    lang = (language or DEFAULT_LANGUAGE).strip()
    named, unnamed = _INTRO.get(lang, _INTRO["en"])
    template = named if agent_name.strip() else unnamed
    intro = template.format(name=agent_name.strip(), product=product)

    where = situation(readiness, requirements=requirements, language=language) if readiness else ""
    first = _first_move(readiness, requirements, lang)
    return _pick(_ANNOUNCE, language).format(intro=intro, situation=where, first=first)


def _first_move(readiness, requirements: int, lang: str) -> str:
    """The one thing worth doing next, read off the board rather than offered as a menu.

    Ordered by what costs something now: an idle factory beside ready work is losing capacity this
    hour; a backlog nobody can start is losing it next week; a product nobody wrote down costs on
    the day somebody argues about what was promised."""
    options = _FIRST.get(lang, _FIRST["en"])
    if readiness is None:
        return options["document"] if not requirements else options["queue"]
    if readiness.ready:
        return options["queue"]
    if readiness.needs_refinement:
        return options["refine"]
    return options["document"]


#: What she actually ASKS the person, per finding — a question someone can answer, not a status.
#: The platform's `Observation.detail` is English triage prose ("no acceptance criteria, so nobody
#: can say when it is done") and shipped VERBATIM to the client channel until a reviewer caught it:
#: two of the four askable kinds contained words from CLIENT_JARGON, in the wrong language. The
#: detail stays in the ledger for operators; the CLIENT hears one of these.
_ASK = {
    "pt-BR": {
        "no-criteria": "o que precisa ser verdade para considerarmos isso pronto? Hoje não está "
                       "escrito, então ninguém consegue dizer quando terminou.",
        "stalled": "isso começou e está sem movimento há um bom tempo — está esperando algo de "
                   "vocês, ou perdeu a prioridade?",
        "waiting-too-long": "isso está esperando uma decisão há tempo demais — o que falta para "
                            "decidirmos?",
        "done-but-open": "isso parece pronto do nosso lado — podemos dar por encerrado, ou ainda "
                         "falta alguma coisa?",
    },
    "en": {
        "no-criteria": "what has to be true for us to call this done? Nothing is written down, so "
                       "nobody can say when it is finished.",
        "stalled": "this was started and has not moved in a while — is it waiting on something "
                   "from you, or did it lose priority?",
        "waiting-too-long": "this has been waiting on a decision for too long — what is missing "
                            "to decide?",
        "done-but-open": "this looks finished on our side — can we call it done, or is something "
                         "still missing?",
    },
}


_DEFECT_CONFIRM = {
    "pt-BR": "Isso quebra o que já prometemos{req} — vou registrar como problema para corrigir, "
             "não como pedido novo. Confirma que é isso?",
    "en": "This breaks something we already promised{req} — I will register it as a problem to "
          "fix, not as a new request. Is that right?",
}

#: HONEST about the gate. The first version said "está na fila de correção" — but a defect lands
#: in Backlog, and by design (ADR-0019 §5) nothing leaves Backlog without a person promoting it:
#: starting work spends money. A client who hears "in the fix queue", waits two weeks and sees
#: nothing has been told a small lie, and a message caught once in a small lie discredits the true
#: ones. The requirement flow already got this right ("nada está sendo construído ainda").
_DEFECT_FILED = {
    "pt-BR": "Registrado{req}. Entra na fila de correção quando o time aprovar a próxima leva — "
             "e quando o conserto sair, eu aviso aqui.",
    "en": "Registered{req}. It joins the fix queue when the team approves the next batch — and "
          "when the fix ships, I will say so here.",
}

_FACT_CONFIRM = {
    "pt-BR": "Vou anotar assim — *{term}*: {body}\n\nFica registrado em seu nome, como algo "
             "aprendido (não como decisão). Confirma?",
    "en": "I will note it like this — *{term}*: {body}\n\nIt goes on record under your name, as "
          "something learned (not decided). Confirm?",
}

_FACT_NOTED = {
    "pt-BR": "Anotado. Quando alguém perguntar sobre {term}, é isso que vou responder — e vou "
             "dizer quem me contou.",
    "en": "Noted. When somebody asks about {term}, that is what I will answer — and I will say "
          "who told me.",
}


def defect_confirmation(*, violates: int | None, language: str | None = None) -> str:
    req = f" (requisito {violates})" if violates else ""
    return _pick(_DEFECT_CONFIRM, language).format(req=req)


def defect_filed(*, ref: str, violates: int | None, language: str | None = None,
                 existed: bool = False) -> str:
    req = f", contra o requisito {violates}" if violates else ""
    text = _pick(_DEFECT_FILED, language).format(req=req)
    if existed:
        text = _pick({"pt-BR": "Eu já tinha registrado esse problema — segue o mesmo registro. ",
                      "en": "I had already registered this problem — same record. "},
                     language) + text
    return text


def fact_confirmation(*, term: str, body: str, language: str | None = None) -> str:
    return _pick(_FACT_CONFIRM, language).format(term=term, body=body)


def fact_noted(*, term: str, language: str | None = None) -> str:
    return _pick(_FACT_NOTED, language).format(term=term)


_BASELINE_STARTED = {
    "pt-BR": "Vou ler o produto inteiro e escrever o que ele faz hoje. Leva alguns minutos — "
             "aviso aqui quando terminar.\n\nDuas coisas antes: o que eu escrever são "
             "OBSERVAÇÕES, não promessas. É o que o sistema aparenta fazer, e parte disso pode "
             "ser acidente ou defeito sem eu conseguir distinguir. Nada vira compromisso até "
             "alguém confirmar item a item.",
    "en": "I am going to read the whole product and write down what it does today. It takes a few "
          "minutes — I will say so here when it is done.\n\nTwo things first: what I write are "
          "OBSERVATIONS, not promises. Some of it may be an accident or a defect and I usually "
          "cannot tell which. Nothing becomes a commitment until somebody confirms it.",
}

#: NO LINK, and it is the same decision `written_up` already made one screen up. This interpolated
#: `{url}` — a forge pull-request URL, repository slug and all — into a business conversation, on
#: the HAPPY path, every time. Three statements in this module say it must not: `written_up`'s
#: docstring ("passing it here used to put a GitHub link in front of somebody who cannot act on
#: one"), AUDIENCE_RULES ("a pull request, a branch, a commit, a repository, a file path — none of
#: it reaches this channel"), and `_DIAGNOSTIC`, which classes `https?://` as machinery and is what
#: sanitises every OTHER detail this surface shows.
#:
#: The affordance the link looked like was never real. The entries land on a branch nobody has
#: merged, so the client cannot act on that page and the role cannot even read it yet — the honest
#: version of that is what `_WRITTEN_UP_UNMERGED` says, and it is said here too. Confirming an
#: observation happens in THIS channel, by name and number, which is the one gesture that turns
#: one into a promise (ADR-0032).
_BASELINE_DONE = {
    "pt-BR": "Terminei o levantamento — {n}.\n\nEscrevi tudo de uma vez, para dar para ler junto; "
             "o time ainda precisa concluir esse passo, e até lá nem eu consigo reler o que "
             "escrevi. Cada item entrou como observação: quando você me disser que um deles está "
             "acordado, ele vira promessa e passa a ser defendido. "
             "**Nada está sendo construído ainda**.",
    "en": "The first pass is done — {n}.\n\nI wrote it all in one go, so it can be read in one "
          "sitting; the team still has to finish that step, and until they do I cannot re-read it "
          "myself either. Every entry landed as an observation: tell me one is agreed and it "
          "becomes a promise that gets defended. **Nothing is being built yet**.",
}

_BASELINE_FAILED = {
    "pt-BR": "Não consegui concluir o levantamento: {detail}\n\nNada foi escrito. Pode pedir de "
             "novo — ou me diga por onde começar e eu tento só aquela parte.",
    "en": "I could not finish the first pass: {detail}\n\nNothing was written. Ask again, or "
          "tell me where to start and I will try just that part.",
}


def baseline_started(*, language: str | None = None, agent_name: str = "") -> str:
    sig = f"{agent_name}: " if agent_name.strip() else ""
    return sig + _pick(_BASELINE_STARTED, language)


def baseline_done(*, ok: bool, url: str = "", detail: str = "", existed: bool = False,
                  language: str | None = None, agent_name: str = "") -> str:
    """What the client reads when the brownfield pass finishes.

    `url` is accepted and DELIBERATELY UNUSED in the text, exactly as in `written_up`: the caller
    holds it for the team, and it is kept as a parameter so the seam survives — removing it would
    push every caller to change and the next one to pass a link somewhere new. It goes to the log,
    which is where a pull request address belongs.
    """
    sig = f"{agent_name}: " if agent_name.strip() else ""
    if not ok:
        # through the SAME sanitiser every other client-read detail passes. The baseline failure
        # arrives as raw machinery (an exception string, git stderr) and this composition site was
        # the one sibling shipping it verbatim. Sanitised HERE rather than at the call sites: a
        # caller that has to remember is a caller that forgets.
        safe, raw = client_safe_detail(detail, language=language)
        if raw:
            log.warning("a baseline failure detail the client must not read: %s", raw[:400])
        return sig + _pick(_BASELINE_FAILED, language).format(detail=safe or "não sei dizer")
    if url:
        log.info("the baseline pass is at %s — for the team; the channel is told in its own terms",
                 url)
    head = _pick({"pt-BR": "já estava proposto de antes", "en": "it was already proposed"},
                 language) if existed else _pick(
        {"pt-BR": "escrevi o que encontrei", "en": "I wrote down what I found"}, language)
    return sig + _pick(_BASELINE_DONE, language).format(n=head)


def question_for(kind: str, language: str | None = None) -> str:
    """The client-language question for one askable finding. Falls back to the pt-BR catalogue and,
    for a kind with no entry, to a generic ask — never to the platform's own words."""
    lang = (language or DEFAULT_LANGUAGE).strip()
    table = _ASK.get(lang) or _ASK.get(DEFAULT_LANGUAGE) or _ASK["en"]
    return table.get(kind) or _pick(
        {"pt-BR": "pode me dar mais contexto sobre isso? Do jeito que está eu não consigo levar "
                  "adiante.",
         "en": "could you give me more context on this? As it stands I cannot take it further."},
        language)


def signature(agent_name: str = "") -> str:
    """How the agent signs what it writes on a ticket.

    Names the ROLE as well as the person: the team reads these, and "Nina" alone tells a new joiner
    nothing about why the comment exists."""
    name = (agent_name or "").strip()
    return f"**{name} (produto):**" if name else "**Produto:**"


#: How each triage finding reads to someone who does not run the board. The kinds are the platform's
#: vocabulary; these are the client's.
_FINDING = {
    "pt-BR": {
        "stalled": "parado há tempo demais em andamento",
        "waiting-too-long": "esperando uma decisão há tempo demais",
        "no-criteria": "sem nada escrito que diga quando está pronto",
        "done-but-open": "aparece como pronto mas nunca foi encerrado",
        "closed-elsewhere": "já foi encerrado mas continua aparecendo como trabalho em aberto",
        "container-complete": "tudo dentro dele terminou, mas ele continua aberto",
    },
    "en": {
        "stalled": "stuck in progress for too long",
        "waiting-too-long": "waiting on a decision for too long",
        "no-criteria": "nothing written down that says when it is done",
        "done-but-open": "shows as finished but was never closed",
        "closed-elsewhere": "already closed but still showing as open work",
        "container-complete": "everything inside it finished, but it is still open",
    },
}

_TRIAGE_HEAD = {
    "pt-BR": ("Passei o olho no trabalho em andamento. **Não mudei nada** — isto é o que eu vi:",
              "Passei o olho no trabalho em andamento e **não achei nada fora do lugar**."),
    "en": ("I went through the work in flight. **I changed nothing** — here is what I saw:",
           "I went through the work in flight and **found nothing out of place**."),
}

_TRIAGE_STANDING = {
    "pt-BR": "Continuam pendentes de antes: {parts}.",
    "en": "Still outstanding from before: {parts}.",
}

_TRIAGE_NOTHING_NEW = {
    "pt-BR": "Nada novo desde a última vez.",
    "en": "Nothing new since last time.",
}

_TRIAGE_SKIPPED = {
    "pt-BR": "Deixei {n} de fora de propósito (alguém cuida deles, ou são guarda-chuva de outros).",
    "en": "I left {n} alone on purpose (someone owns them, or they are containers for other work).",
}


#: `**bold**` / `*italic*`, never spanning a line. Anchored so a stray asterisk inside a
#: requirement's title survives — this removes EMPHASIS, it does not sanitise text.
_EMPHASIS = re.compile(r"\*{1,2}([^*\n]+)\*{1,2}")


def strip_markup(text: str) -> str:
    """The same sentence with its emphasis removed, for a surface that renders none.

    WHY THIS EXISTS RATHER THAN A SECOND SET OF COMPOSERS. Every sentence in this module is
    written for a person, and a chat client is one of the places a person reads it — `*sim*` and
    `**não mexi em nada**` are the difference between a report and a wall of numbers there. But
    `Outcome.message` forbids markup in as many words (`actions/base.py`: "It must not contain
    mrkdwn, HTML, or a provider's link syntax… a message pre-decorated for Slack renders as
    literal asterisks in the panel"), and that is not a style rule — it is how the first
    impediment alert shipped.

    So the PROSE stays one implementation and the RENDERING is what differs, which is the same
    shape as the rest of this platform: one action, N transports. The action layer strips at its
    own boundary rather than every composer growing a flag, because the rule belongs to the layer
    that states it.

    IT IS THE ROW'S CALL, NOT `done()`'S. Folding this into `Outcome` would silently rewrite every
    message and make the defect invisible; a guard over the composing rows catches a forgotten
    call instead, and can be seen going red."""
    return _EMPHASIS.sub(r"\1", text or "")


#: What it concluded about each parked ticket. `mine` is where the requirement is at fault; the
#: other side is somebody else's problem and saying so is the point of the pass.
_NEEDS_ACTION_NOTHING = {
    "pt-BR": "Nada parado esperando decisão no momento.",
    "en": "Nothing parked and waiting on a decision right now.",
}

_NEEDS_ACTION_HEAD = {
    "pt-BR": "Olhei o que está parado. **Não mexi em nada** — isto é o que eu vi:",
    "en": "I went through what is parked. **I changed nothing** — here is what I saw:",
}

_NEEDS_ACTION_MINE = {
    "pt-BR": "• **{n}** onde o problema é do requisito (meu): {listed}",
    "en": "• **{n}** where the requirement is what is wrong (mine): {listed}",
}

_NEEDS_ACTION_THEIRS = {
    "pt-BR": "• **{n}** onde a causa não é do requisito: {listed}",
    "en": "• **{n}** where the cause is not the requirement: {listed}",
}


_WAITING_NONE = {
    "pt-BR": "Nada esperando por você agora.",
    "en": "Nothing waiting on you right now.",
}

_WAITING_SOME = {
    "pt-BR": "{n} proposta(s) esperando você confirmar.",
    "en": "{n} proposal(s) waiting for you to confirm.",
}


def waiting_on_you(*, count: int, language: str | None = None) -> str:
    """What is staged and waiting, in the client's own language.

    NO KINDS IN THE SENTENCE. The first version read "2 proposal(s) waiting on a person (accept,
    draft)" — English, in a thread whose every other line is the product's Portuguese voice, with
    two of this platform's INTERNAL entry slugs in brackets. `kind` is a routing key; it is data
    for a surface to render as it likes, and it was never a word anybody outside this codebase
    has a meaning for."""
    if count <= 0:
        return _pick(_WAITING_NONE, language)
    return _pick(_WAITING_SOME, language).format(n=count)


def needs_action_report(review, *, language: str | None = None, agent_name: str = "") -> str:
    """What the role concluded about each parked ticket — INCLUDING the ones it left alone.

    A ticket it looked at and did not touch must LOOK like that, or the next reader re-does the
    pass. The sentence says "I changed nothing" out loud for the same reason.

    LIFTED OUT OF `runtime/slack/product_channel.py` (#105), where it was the only composer in the
    product's voice that lived in a vendor's package — hardcoded pt-BR, with no `language`
    parameter, so a client on any other language got Portuguese and a deployment without Slack got
    nothing at all. Every sibling here takes `language`; this one now does too, which is the
    difference between moving a file and finishing the job."""
    head = f"{agent_name}: " if agent_name else ""
    decisions = list(getattr(review, "decisions", None) or ())
    if not decisions:
        return f"{head}{_pick(_NEEDS_ACTION_NOTHING, language)}"

    mine, theirs = review.mine(), review.handed_back()
    lines = [f"{head}{_pick(_NEEDS_ACTION_HEAD, language)}", ""]
    if mine:
        lines.append(_pick(_NEEDS_ACTION_MINE, language).format(
            n=len(mine), listed=", ".join(f"#{d.verdict.ticket}" for d in mine)))
    if theirs:
        lines.append(_pick(_NEEDS_ACTION_THEIRS, language).format(
            n=len(theirs), listed=", ".join(f"#{d.verdict.ticket}" for d in theirs)))
    return "\n".join(lines)


def triage_report(report, *, language: str | None = None, agent_name: str = "",
                  limit: int = 12, standing: dict | None = None) -> str:
    """A triage pass, said to the people who own the product.

    Findings are grouped by KIND rather than listed one by one: "seven tickets have nothing that
    says when they are done" is a decision someone can make, while seven separate lines are a chore
    nobody starts."""
    lang = (language or DEFAULT_LANGUAGE).strip()
    words = _FINDING.get(lang, _FINDING["en"])
    with_findings, clean = _TRIAGE_HEAD.get(lang, _TRIAGE_HEAD["en"])
    sig = f"{agent_name.strip()}: " if agent_name.strip() else ""

    if not report.observations:
        # Nothing NEW is not the same as nothing wrong. Saying only "nothing new" would let a
        # backlog of unfixed rot disappear from view precisely by not changing.
        out = f"{sig}{_pick(_TRIAGE_NOTHING_NEW, language) if standing else clean}"
        if standing:
            out += "\n" + _standing_line(standing, words, language)
        if report.skipped:
            out += "\n\n" + _pick(_TRIAGE_SKIPPED, language).format(n=len(report.skipped))
        return out

    lines = [f"{sig}{with_findings}", ""]
    by_kind: dict[str, list] = {}
    for o in report.observations:
        by_kind.setdefault(o.kind, []).append(o)
    for kind, found in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        what = words.get(kind, kind)
        shown = ", ".join(f"#{o.ticket}" for o in found[:limit])
        more = f" (+{len(found) - limit})" if len(found) > limit else ""
        lines.append(f"• **{len(found)}** {what}: {shown}{more}")
    if standing:
        lines += ["", _standing_line(standing, words, language)]
    if report.skipped:
        lines += ["", _pick(_TRIAGE_SKIPPED, language).format(n=len(report.skipped))]
    return "\n".join(lines)


def _standing_line(standing: dict, words: dict, language: str | None) -> str:
    """The rot that did NOT change, as one line of counts rather than a re-listing.

    Repeating forty ticket numbers every week is how a report becomes wallpaper; omitting them
    entirely is how a backlog vanishes by standing still. A count is the honest middle."""
    parts = ", ".join(f"{n} {words.get(kind, kind)}"
                      for kind, n in sorted(standing.items(), key=lambda kv: -kv[1]) if n)
    return _pick(_TRIAGE_STANDING, language).format(parts=parts) if parts else ""


_QUEUE_IDLE = {
    "pt-BR": ("A fábrica está parada e tem trabalho pronto esperando — isso é capacidade indo "
              "embora. Minha sugestão de por onde seguir, nesta ordem:"),
    "en": ("The factory is idle with ready work waiting — that is capacity going to waste. Here is "
           "what I suggest we start, in this order:"),
}
_QUEUE_BUSY = {
    "pt-BR": "Sugestão de ordem para o que vem a seguir:",
    "en": "Suggested order for what comes next:",
}
_QUEUE_BLOCKED = {
    "pt-BR": ("A fábrica está parada e o backlog tem {n} itens, mas **nenhum deles diz quando "
              "estaria pronto** — do jeito que estão, seriam recusados na entrada. Isso é comigo: "
              "posso escrever os critérios e trazer para vocês revisarem."),
    "en": ("The factory is idle and the backlog has {n} items, but **none of them says when it "
           "would be done** — as written they would be refused at the gate. That one is mine: I "
           "can write the criteria and bring them back for review."),
}
_QUEUE_EMPTY = {
    "pt-BR": "A fábrica está parada e não há nada no backlog pronto para começar.",
    "en": "The factory is idle and there is nothing in the backlog ready to start.",
}
_QUEUE_ASK = {
    "pt-BR": "Aprovo? Responda *sim* e eu coloco na fila nessa ordem.",
    "en": "Shall I? Reply *yes* and I'll queue them in that order.",
}
_QUEUE_HELD = {
    "pt-BR": "Deixei de fora por enquanto:",
    "en": "Left out for now:",
}
_QUEUE_REFINE = {
    "pt-BR": "({n} outros no backlog ainda não dizem quando estariam prontos.)",
    "en": "({n} others in the backlog do not yet say when they would be done.)",
}
_QUEUED = {
    "pt-BR": "Coloquei na fila, nesta ordem: {items}. A fábrica começa pelo primeiro.",
    "en": "Queued, in this order: {items}. The factory starts with the first.",
}

#: The header over a group that only means something whole. Written as WHAT THE CLIENT WILL BE ABLE
#: TO DO, because that is the decision they are being asked to make — not "these three tickets are
#: related", which they cannot act on.
_QUEUE_BATCH = {
    "pt-BR": "**Juntos, para vocês poderem testar “{what}”:**",
    "en": "**Together, so you can try “{what}”:**",
}
#: Back to items that stand on their own, after a group. Without it the list reads as though the
#: batch above swallowed everything below it.
_QUEUE_ALONE = {
    "pt-BR": "**Independentes entre si:**",
    "en": "**Independent of each other:**",
}


def queue_proposal(readiness, proposal, *, titles: dict[str, str] | None = None,
                   language: str | None = None, agent_name: str = "") -> str:
    """The proposal, led by WHY it matters — an idle floor beside ready work is the one finding
    here that costs something every hour it stays true."""
    titles = titles or {}
    sig = f"{agent_name.strip()}: " if agent_name.strip() else ""

    if not proposal or not proposal.items:
        if readiness.blocked_by_refinement:
            return sig + _pick(_QUEUE_BLOCKED, language).format(n=len(readiness.needs_refinement))
        return sig + _pick(_QUEUE_EMPTY, language)

    head = _QUEUE_IDLE if readiness.wasting_capacity else _QUEUE_BUSY
    lines = [sig + _pick(head, language), ""]
    # THE BATCH HAS TO BE VISIBLE OR IT DOES NOT EXIST. Grouping the tickets in the model and then
    # printing one flat numbered list would leave the client approving a sequence with no way to
    # see that three of its items are one deliverable — the care would be real in the JSON and
    # absent everywhere a person looks.
    shown = ""
    for i, item in enumerate(proposal.items, 1):
        batch = item.batch.strip()
        if batch and batch != shown:
            lines.append(("" if i == 1 else "") + _pick(_QUEUE_BATCH, language).format(what=batch))
        if not batch and shown:
            lines.append(_pick(_QUEUE_ALONE, language))
        shown = batch
        title = titles.get(item.ticket, "")
        lines.append(f"{i}. **#{item.ticket}**{f' — {title}' if title else ''}"
                     + (f"\n   _{item.why}_" if item.why else ""))
    if proposal.held_back:
        lines += ["", _pick(_QUEUE_HELD, language)]
        lines += [f"• #{h.ticket} — {h.why}" for h in proposal.held_back[:5]]
    if proposal.note:
        lines += ["", proposal.note]
    if readiness.needs_refinement:
        lines += ["", _pick(_QUEUE_REFINE, language).format(n=len(readiness.needs_refinement))]
    lines += ["", _pick(_QUEUE_ASK, language)]
    return "\n".join(lines)


def queued(numbers: list[str], *, language: str | None = None, agent_name: str = "") -> str:
    sig = f"{agent_name.strip()}: " if agent_name.strip() else ""
    return sig + _pick(_QUEUED, language).format(
        items=", ".join(f"#{n}" for n in numbers))


_SITUATION = {
    "pt-BR": {
        "idle_ready": ("Como está agora: a fábrica está **parada** e há **{ready}** itens prontos "
                       "para começar — isso é capacidade indo embora."),
        "idle_blocked": ("Como está agora: a fábrica está **parada**, e dos **{backlog}** itens no "
                         "backlog **nenhum** diz quando estaria pronto ({items})."),
        "busy": "Como está agora: **{running}** em andamento, **{todo}** na fila.",
        "quiet": "Como está agora: nada em andamento e nada esperando.",
        "refine": (" Outros **{n}** ainda não dizem quando estariam prontos ({items}) — posso "
                   "escrever os critérios deles."),
        "corpus": " Sobre o produto em si, **{n}** requisitos escritos.",
        "corpus_none": " Sobre o produto em si, ainda não há nada escrito — é por onde eu começo.",
        "trend": " Desde a última vez que olhei, o backlog {dir} **{n}**.",
    },
    "en": {
        "idle_ready": ("Where things stand: the factory is **idle** with **{ready}** items ready "
                       "to start — that is capacity going to waste."),
        "idle_blocked": ("Where things stand: the factory is **idle**, and of the **{backlog}** "
                         "items in the backlog **none** says when it would be done ({items})."),
        "busy": "Where things stand: **{running}** in flight, **{todo}** queued.",
        "quiet": "Where things stand: nothing in flight and nothing waiting.",
        "refine": (" Another **{n}** do not yet say when they would be done ({items}) — I can "
                   "write their criteria."),
        "corpus": " On the product itself, **{n}** requirements written down.",
        "corpus_none": " On the product itself, nothing is written yet — where I start.",
        "trend": " Since I last looked, the backlog {dir} by **{n}**.",
    },
}
_TREND_WORD = {"pt-BR": ("cresceu", "diminuiu"), "en": ("grew", "shrank")}


def _listed(numbers: list[str], *, limit: int = 6) -> str:
    """Ticket numbers a reader can actually go and look at.

    A count is a fact nobody can act on: "another 11 do not say when they would be done" leaves a
    person scrolling a board of fifty trying to work out WHICH eleven. Naming them costs one line
    and turns a statistic into a task."""
    shown = ", ".join(f"#{n}" for n in numbers[:limit])
    rest = len(numbers) - limit
    return f"{shown} e mais {rest}" if rest > 0 else shown


#: What the CLIENT hears about the state of their own requirements. The operator's version
#: (`ProductContext.health`) says "product module ready on clientorg/client-documentation —
#: 4 requirements, 1 accepted — 0 errors, 1 warnings · 1 aviso(s) de configuração: the source repo
#: does not declare docs_repo … in its .sdlc/project.yaml", and for months that string WAS the
#: answer to "como estamos?" — the most-asked question on this surface. A repository slug, English
#: prose, a file path and a warning count, every single day, to somebody who bought a product that
#: needs no developer.
#:
#: Two audiences, two surfaces (ADR-0026) — the same split the requirement flow already makes. The
#: operator's line keeps every diagnostic; this one carries the two facts a person who owns the
#: product actually asked for: how much is written down, and how much of it is a promise.
_CORPUS_STATE = {
    "pt-BR": ("Sobre o produto em si: **{n}** requisito{s} escrito{s}, "
              "**{promises}** valendo como promessa."),
    "en": ("On the product itself: **{n}** requirement{s} written down, **{promises}** counting "
           "as a promise."),
}
_CORPUS_EMPTY = {
    "pt-BR": "Sobre o produto em si, ainda não há nada escrito — é por onde eu começo.",
    "en": "On the product itself, nothing is written yet — that is where I start.",
}
_CORPUS_UNREADABLE = {
    "pt-BR": ("Não estou conseguindo abrir o que já foi escrito sobre o produto agora, então não "
              "vou dizer números que eu não conferi. O time já foi avisado."),
    "en": ("I cannot open what has been written about the product right now, so I will not quote "
           "numbers I have not checked. The team has been told."),
}


def corpus_state(*, available: bool, requirements: int, promises: int,
                 language: str | None = None) -> str:
    """The state of the written product, in the words of somebody who owns it.

    NUMBERS ONLY WHEN THEY WERE READ. An unreadable base answers with the limitation and not with
    a zero — "nada escrito" and "não consegui abrir" are opposite facts, and one of them would have
    a client believing their requirements are gone.
    """
    if not available:
        return _pick(_CORPUS_UNREADABLE, language)
    if not requirements:
        return _pick(_CORPUS_EMPTY, language)
    return _pick(_CORPUS_STATE, language).format(
        n=requirements, s="s" if requirements != 1 else "", promises=promises)


def situation(readiness, *, requirements: int = 0, previous_backlog: int | None = None,
              language: str | None = None) -> str:
    """Where things stand, in one paragraph, led by whichever fact costs something.

    An idle factory beside ready work is stated first and in those terms, because it is the only
    line here that is losing money while it is read."""
    lang = (language or DEFAULT_LANGUAGE).strip()
    w = _SITUATION.get(lang, _SITUATION["en"])
    backlog = len(readiness.ready) + len(readiness.needs_refinement)

    if readiness.wasting_capacity:
        out = w["idle_ready"].format(ready=len(readiness.ready))
    elif readiness.blocked_by_refinement:
        out = w["idle_blocked"].format(backlog=backlog,
                                       items=_listed(readiness.needs_refinement))
    elif readiness.idle:
        out = w["quiet"]
    else:
        out = w["busy"].format(running=readiness.in_progress, todo=len(readiness.todo))

    if readiness.needs_refinement and not readiness.blocked_by_refinement:
        out += w["refine"].format(n=len(readiness.needs_refinement),
                                  items=_listed(readiness.needs_refinement))
    if previous_backlog is not None and previous_backlog != backlog:
        grew, shrank = _TREND_WORD.get(lang, _TREND_WORD["en"])
        delta = backlog - previous_backlog
        out += w["trend"].format(dir=grew if delta > 0 else shrank, n=abs(delta))
    out += w["corpus"].format(n=requirements) if requirements else w["corpus_none"]
    return out


#: Words that assert a write ALREADY happened. The role has no way to know: the write runs on a
#: path it never observes, only after an authorised person confirms. When one of these appears in a
#: reply that wrote nothing, somebody is being told a record exists when it does not.
#:
#: DERIVED FROM THIS MODULE'S OWN SUCCESS SENTENCES, not from a list somebody imagined. The first
#: version was invented and therefore missed "Anotado" — the exact word `fact_noted` uses when a
#: glossary write really succeeded — along with "Coloquei na fila" (`queued`) and "Filei". An
#: agent echoing the platform's own confirmation was the likeliest false claim of all, and it was
#: the one the detector could not see. `test_every_success_sentence_is_detected` now derives the
#: coverage from the real phrases, so the vocabulary cannot fall behind them again.
#: `abri`/`abrimos`/`aberto` ARE NOT HERE, and their absence is a measurement rather than an
#: oversight. They were meant for "I opened an issue" — but in this role's actual vocabulary the
#: verb overwhelmingly means opening a FILE TO READ, which is the behaviour the prompt asks for on
#: every turn: *"Abri o requisito 3 e o código que ele cita"* fired this detector on 2026-07-31,
#: describing a read. No success sentence in this module uses them, so nothing is lost by their
#: going; keeping them cost a false alarm on the most desirable sentence she writes.
#:
#: `escrito`/`escrita` LEFT FOR THE SAME REASON `abri` DID, and it is a measurement rather than a
#: preference. They were meant for "I wrote it down" — but in THIS role's vocabulary the word
#: describes whether a REQUIREMENT EXISTS ON PAPER, which is the subject she talks about all day.
#: Her first substantial reply to the client (2026-08-01) fired the detector three times on
#: sentences that assert the opposite of a write:
#:
#:     "É a única promessa escrita deste produto hoje"
#:     "nenhum outro assunto está escrito"
#:     "Faixas 2 a 5 continuam sem uma linha escrita"     ← says nothing is written
#:
#: The first-person forms stay: `escrevi`/`escrevemos` ARE claims about this turn, and no sentence
#: about a document's existence uses them. A detector that fires on the most ordinary noun of the
#: domain it watches stops being read, which costs more than the true positives it would catch.
_CLAIMED_DONE = re.compile(
    r"\b(registrado|registrada|registrei|registramos|gravado|gravada|gravei|"
    r"anotado|anotada|anotei|anotamos|escrevi|escrevemos|"
    r"criado|criada|criei|criamos|"
    r"fechado|fechados|fechada|fechei|fechamos|movido|movi|movemos|arquivado|"
    r"encerrado|encerrada|encerrei|encerramos|alinhado|alinhada|alinhei|alinhamos|"
    r"filei|filado|coloquei|colocamos|inclu[ií]|inclu[ií]do|"
    # `wrote` and not `written`, for the reason the pt-BR side lost `escrito`: the participle is
    # what an English sentence about a document's existence uses ("nothing else is written"), and
    # the first person is only ever a claim about this turn.
    r"filed|recorded|created|closed|queued|logged|wrote)\b",
    re.IGNORECASE)


#: An explicit statement, in the same message, that nothing was written. A text that says "I said
#: it was registered — it was not" does NOT assert a write; it denies one. Detecting the claim word
#: and ignoring the denial around it is how the platform came to contradict a CORRECT
#: self-correction: Nina wrote "corrijo o que escrevi: eu disse 'Registrado o Requisito 1'. Não foi.
#: Eu não vejo o resultado de escrita nenhuma" — and the platform appended "nada foi gravado; o
#: texto acima diz o contrário, e está errado" underneath. The text did not say the contrary. Being
#: corrected while right is worse than not being corrected: it teaches the reader to distrust both
#: voices, and it punishes the exact behaviour the rule exists to produce.
#:
#: TWO KINDS OF SENTENCE WERE IN ONE LIST, and that was the defect. A RETRACTION refers BACK — it
#: exists to stop a reader believing a specific write happened, so it speaks for everything around
#: it. A statement that she CANNOT OBSERVE something refers to nothing but itself; the role adopted
#: "não vejo o resultado" as a habitual and correct formula in nearly every message, and treating
#: it as a retraction switched the detector off for the whole conversation. On 2026-07-31 she wrote
#: "Registrado o pedido junto ao time" about a request that exists nowhere and nothing said a word,
#: because the same message carried the formula: a true positive swallowed by the guard against
#: false ones.
#:
#: So they are separated, and they excuse different amounts of text (`claims_a_write`).
_RETRACTS_WRITE = re.compile(
    r"(n[ãa]o foi\b|n[ãa]o foram\b|nada foi (gravado|registrado|escrito)|"
    r"n[ãa]o (existe|existem) (nada|nenhum)|"
    r"n[ãa]o (est[áa]|estão) registrad|n[ãa]o (foi|foram) registrad|"
    r"corrijo o que|me corrijo|nada daquela mensagem existe|"
    r"nothing was (recorded|written)|was not (recorded|written))",
    re.IGNORECASE)

#: "I cannot see the outcome" — honest, asked for by the prompt, and NOT a denial that anything
#: happened. It is kept only because the sentence trips the claim detector on its own ("escrita" is
#: both the noun and the participle), and flagging her for saying it would punish the behaviour the
#: rule exists to produce. It therefore excuses ITS OWN SENTENCE and nothing further.
_CANNOT_OBSERVE = re.compile(r"n[ãa]o (vejo|consigo ver|posso ver) o resultado", re.IGNORECASE)


def claims_a_write(text: str) -> str:
    """The claim-of-completion found in `text`, or "".

    A function over TEXT, not a method on the module: what it inspects is a sentence, and putting it
    on the module made every test double have to know about it.

    Detection, not correction. Rewriting the agent's words would put the platform in the business of
    editing what it said, and a wrong edit is worse than a flagged sentence. What shipped was worse
    than both: a confirmation went unrecognised, nothing was written, and the reply announced five
    registered requirements to somebody who believed it.
    """
    body = text or ""
    if not _CLAIMED_DONE.search(body):
        return ""
    # EACH KIND OF DENIAL EXCUSES WHAT IT SPEAKS FOR, AND NOT THE WHOLE MESSAGE.
    #
    # A retraction speaks for its PARAGRAPH: "eu disse 'Registrado o Requisito 1'. Não foi." is one
    # thought, written together, and the claim it retracts is the sentence beside it. Tested
    # against the whole message it also excused every UNRELATED claim above it — one honest
    # correction at the bottom licensing anything asserted at the top.
    #
    # "Não vejo o resultado" speaks for its SENTENCE only. It refers to nothing before it, and the
    # single reason it is consulted at all is that the phrase trips the claim detector on itself.
    #
    # The paragraph is a boundary the ROLE puts in the text; the sentence split is coarse on
    # purpose — it only has to keep one clause from vouching for the next.
    for para in re.split(r"\n\s*\n", body):
        if not _CLAIMED_DONE.search(para):
            continue
        if _RETRACTS_WRITE.search(para):
            log.info("a claim-of-completion appeared inside an explicit retraction — not "
                     "correcting: %s", para[:120])
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n", para):
            m = _CLAIMED_DONE.search(sentence)
            if m and not _CANNOT_OBSERVE.search(sentence):
                return m.group(0)
    return ""


#: The platform's correction when a reply claims a write that did not happen. Appended, never a
#: replacement: editing what the agent said would hide the disagreement, and the disagreement is
#: exactly what a reader needs to see. Two versions, because "confirm and I record it" is only
#: useful advice when there is something staged to confirm.
#: What a click finds when the proposal is no longer there, or is no longer the same one. FOUR
#: distinct facts, four distinct sentences: a stale button, an EXPIRED proposal, a replaced
#: proposal and a rejection are different things, and one message for several would leave the
#: reader unable to tell which happened — the "two facts sharing one value" class this codebase
#: has paid for four times. And none of them may name machinery: "o worker reiniciou" told a
#: client about a process they never knew existed.
_CLICK_GONE = {
    "pt-BR": ("Esse pedido de confirmação já não está de pé — ou já foi resolvido, ou eu o perdi "
              "ao recomeçar. Se ainda quiser, me peça de novo que eu preparo outra proposta."),
    "en": ("That confirmation is no longer open — either it was already dealt with, or I lost it "
           "on a fresh start. If you still want it, ask me again and I'll prepare another."),
}
_PROPOSAL_EXPIRED = {
    "pt-BR": ("Aquela proposta esperou confirmação por tempo demais e expirou — descartei para "
              "ninguém confirmar um texto que já não lembra de ter lido. Se ainda quiser, me peça "
              "de novo que eu preparo outra."),
    "en": ("That proposal waited too long for a confirmation and expired — I dropped it so nobody "
           "confirms a text they no longer remember reading. If you still want it, ask me again "
           "and I'll prepare another."),
}
#: A confirmation that finds its proposal ALREADY BEING consumed — the same yes arriving twice
#: (a click and a typed "sim", or two people at once). The first one is doing the work; this one
#: must neither write again nor pretend to have.
_ALREADY_HANDLED = {
    "pt-BR": "Essa confirmação já está sendo registrada — um instante.",
    "en": "That confirmation is already being recorded — one moment.",
}
_CLICK_REPLACED = {
    "pt-BR": ("Não confirmei: o que está preparado agora é diferente do que estava neste botão. "
              "Não vou registrar em seu nome algo que você não leu — me peça a proposta atual."),
    "en": ("Not confirmed: what is staged now differs from what this button was posted for. I will "
           "not record something in your name that you did not read — ask me for the current one."),
}
_CLICK_REJECTED = {
    "pt-BR": "Certo, descartei a proposta. Nada foi registrado.",
    "en": "Right, I've dropped the proposal. Nothing was recorded.",
}


def proposal_gone(*, language: str | None = None) -> str:
    return _pick(_CLICK_GONE, language)


def proposal_expired(*, language: str | None = None) -> str:
    return _pick(_PROPOSAL_EXPIRED, language)


def proposal_already_handled(*, language: str | None = None) -> str:
    return _pick(_ALREADY_HANDLED, language)


def proposal_replaced(*, language: str | None = None) -> str:
    return _pick(_CLICK_REPLACED, language)


def proposal_rejected(*, language: str | None = None) -> str:
    return _pick(_CLICK_REJECTED, language)


#: The button labels. Short, unambiguous, and in the reader's language — a button reading "OK" next
#: to one reading "Cancel" is where people click the wrong one.
_CONFIRM_LABELS = {
    "pt-BR": ("Confirmar e registrar", "Não registrar"),
    "en": ("Confirm and record", "Do not record"),
}


def confirm_labels(*, language: str | None = None) -> tuple[str, str]:
    lang = (language or DEFAULT_LANGUAGE).strip()
    return _CONFIRM_LABELS.get(lang) or _CONFIRM_LABELS[DEFAULT_LANGUAGE]


#: Added to a proposal posted WITH buttons. It exists because of a dependency I cannot verify from
#: here: a click only reaches the worker when the Slack app has Interactivity enabled. If it is off,
#: the button post still succeeds — so the prose fallback would not be sent and the proposal would
#: wait for a click that can never arrive. One line keeps the typed path alive regardless, which is
#: cheaper than a runbook step somebody has to remember.
_OR_JUST_REPLY = {
    "pt-BR": "_(ou responda confirmando, se preferir — funciona igual.)_",
    "en": "_(or just reply confirming, if you prefer — it works the same.)_",
}


def or_just_reply(*, language: str | None = None) -> str:
    return _pick(_OR_JUST_REPLY, language)


#: What a raw failure detail looks like when it is diagnostics rather than an explanation a client
#: can act on. `WriteResult.detail` serves TWO audiences — the team's log and the client's channel —
#: which is the "two facts sharing one value" class this codebase has paid for repeatedly. Rather
#: than split the field everywhere, the CHANNEL decides what a client may read, and anything bearing
#: these marks is replaced with a sentence and kept in the log.
#: TWO KINDS OF THING A CLIENT MUST NOT READ, and the first version only knew one. It was built
#: from EXCEPTION SHAPES (`fatal:`, a traceback, an HTTP code) and therefore sailed past a perfectly
#: calm English sentence: "the branch req/0001-… was pushed but the pull request could not be
#: opened; open it by hand against main". No exception in it — just the exact delivery vocabulary
#: AUDIENCE_RULES forbids, plus an instruction the person cannot carry out.
#:
#: The forbidden words were already written down, in the rules the model reads. Two lists of "what
#: a client must not see" that did not know about each other is the same shape as every other defect
#: in this file's history; this one is now derived from both.
_DIAGNOSTIC = re.compile(
    r"(fatal:|stderr|traceback|https?://|refs/|\.git\b|"
    r"[\w-]+/[\w./-]+\.(py|ya?ml|md|json|txt)|"      # any path-with-extension, not just absolute
    r"HTTP \d{3}|exit status|gh: |remote:|error:|Exception|Traceback|"
    r"[A-Z][a-zA-Z]*Error\b|"
    # the delivery vocabulary ADR-0026 hides — machinery the client never touches
    r"\b(branch|pull request|merge request|commit|rebase|checkout|repositor(y|io|y)|"
    r"stack trace|traceback)\b)",
    re.IGNORECASE)

_WRITE_FAILED = {
    "pt-BR": ("Não consegui registrar isso agora — o problema é do meu lado, não do que você "
              "escreveu. O time já foi avisado com o detalhe técnico. Pode me pedir de novo daqui "
              "a pouco."),
    "en": ("I couldn't record that just now — the problem is on my side, not with what you wrote. "
           "The team has the technical detail. Ask me again shortly."),
}


def client_safe_detail(detail: str, *, language: str | None = None) -> tuple[str, str]:
    """`(what the client reads, what the log keeps)`.

    Returns the detail unchanged when it is an explanation somebody can act on ("já tenho isto
    anotado sobre 'erp'"), and swaps it for a plain sentence when it is machinery — a branch name, a
    repo slug, git stderr, a file path, an exception. The second element is always the original, so
    the diagnosis is never lost, only relocated to where it belongs.
    """
    raw = (detail or "").strip()
    if not raw or not _DIAGNOSTIC.search(raw):
        return raw, ""
    return _pick(_WRITE_FAILED, language), raw


#: Accepting is the single most consequential act on this surface: after it the factory ARGUES FROM
#: the statement. So the confirmation names what changes, in the client's terms, rather than saying
#: "status updated" — nobody confirms a field.
_ACCEPT_CONFIRM = {
    "pt-BR": ("Só para confirmar antes: dar o *requisito {number}: {title}* como **acordado** "
              "significa que ele passa a valer como promessa — a partir daí, se o produto fizer "
              "diferente disso, eu trato como defeito e não como pedido novo.\n\n"
              "Confirma?"),
    "en": ("To confirm first: marking *requirement {number}: {title}* as **agreed** makes it a "
           "promise — from then on, if the product behaves differently I treat that as a defect "
           "rather than a new request.\n\nConfirm?"),
}
_ACCEPTED = {
    "pt-BR": ("Acordado. O *requisito {number}* passa a valer como promessa, e fica registrado que "
              "foi você quem acordou e quando."),
    "en": ("Agreed. *Requirement {number}* now counts as a promise, recorded with who agreed and "
           "when."),
}


#: Abandoning. TWO TEXTS, because the two cases are not the same size. Dropping a text nobody agreed
#: to costs nothing — it was a draft. Dropping an ACCEPTED requirement takes a promise back, and the
#: person confirming it has to be told exactly that, in the same terms the acceptance used ("a
#: fábrica passa a defender isso" → "deixa de defender"), or the two acts would read alike while
#: being opposites.
_DROP_CONFIRM = {
    "pt-BR": ("Só para confirmar antes: dar o *requisito {number}: {title}* como **abandonado** "
              "quer dizer que ele sai do que o produto se propõe a fazer. O texto continua "
              "guardado e legível — fica registrado que foi decidido não fazer, por quem e "
              "quando — mas eu paro de tratá-lo como algo a cumprir.\n\nConfirma?"),
    "en": ("To confirm first: marking *requirement {number}: {title}* as **dropped** takes it out "
           "of what the product sets out to do. The text stays stored and readable — it records "
           "that this was decided against, by whom and when — but I stop treating it as something "
           "to deliver.\n\nConfirm?"),
}
_DROP_CONFIRM_PROMISE = {
    "pt-BR": ("Só para confirmar antes, e este é o caso mais sério: o *requisito {number}: "
              "{title}* está **acordado**, ou seja, hoje ele vale como promessa e a fábrica o "
              "defende — se o produto fizer diferente, eu trato como defeito.\n\nDar como "
              "abandonado **desfaz isso**: eu deixo de defendê-lo, e um comportamento que hoje "
              "seria defeito passa a ser só como o produto é. O texto e o registro de quem "
              "acordou continuam guardados.\n\nCards já abertos a partir dele não se fecham "
              "sozinhos — quem encerra card é uma pessoa; posso listar quais são se quiser."
              "\n\nConfirma?"),
    "en": ("To confirm first, and this is the serious case: *requirement {number}: {title}* is "
           "**agreed** — today it counts as a promise and the factory defends it; behaviour that "
           "differs is treated as a defect.\n\nDropping it **undoes that**: I stop defending it, "
           "and what would be a defect today becomes simply how the product is. The text and the "
           "record of who agreed stay stored.\n\nCards already opened from it do not close "
           "themselves — a person closes cards; I can list them if you want.\n\nConfirm?"),
}
_DROPPED = {
    "pt-BR": ("Registrado: o *requisito {number}* fica como abandonado, com o seu nome e a data. "
              "Ele sai do que eu cobro e do que eu defendo — o texto continua guardado, e se um "
              "dia voltar a fazer sentido é só me pedir que eu proponho de novo."),
    "en": ("Recorded: *requirement {number}* is now dropped, with your name and the date. It "
           "leaves what I chase and what I defend — the text stays stored, and if it ever makes "
           "sense again just ask and I'll propose it afresh."),
}
_DROPPED_PROMISE = {
    "pt-BR": ("Registrado: o *requisito {number}* deixa de valer como promessa, com o seu nome e "
              "a data de quem decidiu. A partir de agora eu não o defendo mais — o que antes eu "
              "trataria como defeito passa a ser só como o produto é. O texto e o registro de "
              "quem tinha acordado continuam guardados."),
    "en": ("Recorded: *requirement {number}* no longer counts as a promise, with your name and "
           "the date. From now on I do not defend it — what I would have treated as a defect is "
           "simply how the product is. The text and the record of who had agreed stay stored."),
}


def drop_confirmation(*, number: int, title: str, was_a_promise: bool = False,
                      language: str | None = None) -> str:
    catalogue = _DROP_CONFIRM_PROMISE if was_a_promise else _DROP_CONFIRM
    return _pick(catalogue, language).format(number=number, title=title)


def dropped(*, number: int, was_a_promise: bool = False, language: str | None = None,
            agent_name: str = "") -> str:
    sig = f"{agent_name}: " if agent_name.strip() else ""
    catalogue = _DROPPED_PROMISE if was_a_promise else _DROPPED
    return sig + _pick(catalogue, language).format(number=number)


def accept_confirmation(*, number: int, title: str, language: str | None = None) -> str:
    return _pick(_ACCEPT_CONFIRM, language).format(number=number, title=title)


#: Recording a decision taken AFTER the text was written. The confirmation SHOWS THE SENTENCE that
#: will be written, verbatim, because this act's whole value is that somebody reads the same words
#: in three months — and a paraphrase approved today is a paraphrase found then. It also says
#: plainly that this does not change the promise: a person who confirms a decision believing they
#: amended the requirement has agreed to something they did not mean.
_DECISION_CONFIRM = {
    "pt-BR": ("Só para confirmar antes: vou gravar isto no *requisito {number}*, no registro de "
              "decisões do próprio documento — com a data e o seu nome:\n\n> {decision}\n\n"
              "Isso **não muda o que o requisito promete**; fica registrado como uma decisão "
              "tomada pelo caminho, para quem abrir o documento daqui a três meses saber de onde "
              "veio.\n\nConfirma?"),
    "en": ("To confirm first: I will write this into *requirement {number}*, in the document's own "
           "decision register — with today's date and your name:\n\n> {decision}\n\nThis **does "
           "not change what the requirement promises**; it records a decision taken along the way, "
           "so whoever opens the document in three months knows where it came from.\n\nConfirm?"),
}
_DECISION_RECORDED = {
    "pt-BR": ("Registrado no *requisito {number}*, no documento — data, quem decidiu e de onde "
              "veio. Quem abrir o requisito vê a decisão junto com o texto que ela ajusta."),
    "en": ("Recorded in *requirement {number}*, in the document — the date, who decided and where "
           "it came from. Whoever opens the requirement sees the decision beside the text it "
           "adjusts."),
}
_DECISION_ALREADY = {
    "pt-BR": ("Essa decisão já estava registrada hoje no *requisito {number}* — não gravei de "
              "novo, para o registro não fazer um ato parecer dois."),
    "en": ("That decision was already recorded today on *requirement {number}* — I did not write "
           "it twice, so the register does not make one act look like two."),
}


def decision_confirmation(*, number: int, decision: str, language: str | None = None) -> str:
    return _pick(_DECISION_CONFIRM, language).format(number=number, decision=decision.strip())


def decision_recorded(*, number: int, existed: bool = False, language: str | None = None,
                      agent_name: str = "") -> str:
    sig = f"{agent_name}: " if agent_name.strip() else ""
    catalogue = _DECISION_ALREADY if existed else _DECISION_RECORDED
    return sig + _pick(catalogue, language).format(number=number)


def accepted(*, number: int, language: str | None = None, agent_name: str = "") -> str:
    sig = f"{agent_name}: " if agent_name.strip() else ""
    return sig + _pick(_ACCEPTED, language).format(number=number)


_REQUIREMENT_NOT_FOUND = {
    "pt-BR": "não encontrei o requisito {number} escrito na base.",
    "en": "I could not find requirement {number} written in our base.",
}


def requirement_not_found(*, number: int, language: str | None = None) -> str:
    """Said by every gesture that names a requirement by number. One sentence rather than one per
    branch: three hand-written copies is how the fourth one ends up saying something else."""
    return _pick(_REQUIREMENT_NOT_FOUND, language).format(number=number)


# ── the CARD acts: what happens on the board, not to what the product promises ──────────────────
#
# CLOSING A CARD IS NOT DROPPING A REQUIREMENT, and these texts exist mostly to keep the two from
# reading alike. They are one sentence apart in a chat window and opposite in weight: dropping a
# requirement takes back something the product promised and the factory defended; closing a card
# takes one item off the list of work, changes no promise, and costs nothing to ask for again. A
# person who confirms the wrong one of those has not made a small mistake.

#: Closing with nothing surviving it: this will not be done as its own item.
_CLOSE_CONFIRM = {
    "pt-BR": ("Só para confirmar antes: encerrar o *#{number}* tira esse item da lista de "
              "trabalho — deixa de ser algo a fazer, e ninguém pega ele por engano.\n\n"
              "Isso não mexe no que o produto promete: o que já foi acordado continua valendo do "
              "mesmo jeito. E se um dia voltar a fazer sentido, é só me pedir que eu proponho de "
              "novo.\n\nConfirma?"),
    "en": ("To confirm first: closing *#{number}* takes that item off the list of work — it stops "
           "being something to do, and nobody picks it up by mistake.\n\nIt does not touch what "
           "the product promises: whatever was agreed still stands. And if it ever makes sense "
           "again, just ask and I'll propose it afresh.\n\nConfirm?"),
}
#: Closing because another card already carries the work. A DIFFERENT decision from the one above,
#: and the difference is the whole point: nothing is being given up, the work moved.
_CLOSE_CONFIRM_DUPLICATE = {
    "pt-BR": ("Só para confirmar antes: o *#{number}* e o *#{other}* pedem a mesma coisa. "
              "Encerrar o *#{number}* deixa o *#{other}* como o único lugar onde esse trabalho é "
              "acompanhado — e eu escrevo nos dois qual foi a decisão, para quem procurar o "
              "*#{number}* depois achar para onde ele foi.\n\n"
              "O trabalho não está sendo cancelado: ele continua no *#{other}*. Nada do que o "
              "produto promete muda com isso, e nada começa por causa disso — começar continua "
              "sendo decisão de vocês.\n\nConfirma?"),
    "en": ("To confirm first: *#{number}* and *#{other}* ask for the same thing. Closing "
           "*#{number}* leaves *#{other}* as the only place this work is tracked — and I write the "
           "decision on both, so whoever looks for *#{number}* later finds where it went.\n\nThe "
           "work is not being cancelled: it carries on in *#{other}*. Nothing the product promises "
           "changes, and nothing starts because of this — starting is still your call."
           "\n\nConfirm?"),
}
#: WHAT THE CLOSING NOTE ACTUALLY HOLDS. `_closing_note` writes who asked, and the reason only when
#: somebody gave one — so the sentence that claimed "quem decidiu **e por quê**" over a note reading
#: "fechado a pedido de <@U…>." was promising the client a record that did not exist. Whoever opened
#: the card in six months found half of what they had been told was there.
_CARD_CLOSED = {
    "pt-BR": ("Encerrado o *#{number}*. Deixei escrito nele quem pediu, para quem abrir depois "
              "saber a quem perguntar."),
    "en": ("Closed *#{number}*. I wrote on it who asked, so whoever opens it later knows who to "
           "ask."),
}
_CARD_CLOSED_REASONED = {
    "pt-BR": ("Encerrado o *#{number}*. Deixei escrito nele quem pediu e por quê, para quem abrir "
              "depois não ficar adivinhando."),
    "en": ("Closed *#{number}*. I wrote on it who asked and why, so whoever opens it later is not "
           "left guessing."),
}
_CARD_CLOSED_DUPLICATE = {
    "pt-BR": ("Encerrado o *#{number}* em favor do *#{other}*. Escrevi nos dois: no que saiu, "
              "para onde o assunto foi; no que fica, que ele responde pelos dois agora. Nada "
              "começou por causa disso."),
    "en": ("Closed *#{number}* in favour of *#{other}*. I wrote on both: on the one that went, "
           "where the subject moved to; on the one that stays, that it now answers for both. "
           "Nothing started because of this."),
}
#: The half-done link. The close landed and the note on the surviving card did not, and the sentence
#: above would have told the client "escrevi nos dois" about writing that is not there — so whoever
#: picks up the survivor works from half the conversation while believing it carries the whole. The
#: module says what is missing; this only stops claiming the opposite.
_CARD_CLOSED_UNLINKED = {
    "pt-BR": ("Encerrado o *#{number}* em favor do *#{other}*. No *#{number}* ficou escrito para "
              "onde o assunto foi. Nada começou por causa disso."),
    "en": ("Closed *#{number}* in favour of *#{other}*. *#{number}* now says where the subject "
           "went. Nothing started because of this."),
}
#: The reason, shown back BEFORE it is written. It goes onto the client's card in their name, so
#: the person confirming has to have read it — a proposal is only a proposal for what it shows.
_CLOSE_REASON_LINE = {
    "pt-BR": "\n\nVou deixar escrito no cartão o motivo que você deu: «{reason}».",
    "en": "\n\nI'll write the reason you gave on the card: “{reason}”.",
}
#: Somebody named a surviving card and did not write it as a card. Closing anyway would perform the
#: OTHER act — the one whose whole text says the work is being given up — over a sentence that said
#: the work moved. So it costs a question, and the question names the sentence that works.
_SURVIVOR_UNCLEAR = {
    "pt-BR": ("você quer encerrar o *#{number}* porque esse trabalho passou para outro item, e eu "
              "não tenho certeza de qual — encerrar sozinho diria que o trabalho foi abandonado, e "
              "não foi isso que você me disse. Se for o *#{other}*, me diga «fecha o #{number} "
              "como duplicado do #{other}» e eu preparo."),
    "en": ("you want to close *#{number}* because that work moved to another item, and I am not "
           "sure which — closing it on its own would say the work was given up, which is not what "
           "you told me. If it is *#{other}*, say “close #{number} as a duplicate of "
           "#{other}” and I'll prepare it."),
}


def close_confirmation(*, number: str, in_favour_of: str | None = None, reason: str = "",
                       language: str | None = None) -> str:
    catalogue = _CLOSE_CONFIRM_DUPLICATE if in_favour_of else _CLOSE_CONFIRM
    text = _pick(catalogue, language).format(number=number, other=in_favour_of or "")
    if reason.strip():
        text += _pick(_CLOSE_REASON_LINE, language).format(reason=reason.strip())
    return text


def card_closed(*, number: str, in_favour_of: str | None = None, linked: bool = True,
                reasoned: bool = False, language: str | None = None, agent_name: str = "") -> str:
    """What the client reads after a card was closed — composed from what was actually written.

    `linked` is False when the pointer on the surviving card could not be left, `reasoned` True when
    a reason went onto the closed one. Both exist because the alternative is a sentence that
    describes the happy path and is read out over every other one.
    """
    sig = f"{agent_name}: " if agent_name.strip() else ""
    if in_favour_of:
        catalogue = _CARD_CLOSED_DUPLICATE if linked else _CARD_CLOSED_UNLINKED
    else:
        catalogue = _CARD_CLOSED_REASONED if reasoned else _CARD_CLOSED
    return sig + _pick(catalogue, language).format(number=number, other=in_favour_of or "")


def survivor_unclear(*, number: str, other: str, language: str | None = None) -> str:
    """Which card the work moved to, asked rather than guessed."""
    return _pick(_SURVIVOR_UNCLEAR, language).format(number=number, other=other)


#: Aligning. The confirmation has to say the thing a person would not guess: this is not tidying
#: wording, it changes WHAT GETS BUILT. Thirteen cards citing a retired requirement is what this
#: exists for, and each of those already carries criteria somebody may have started working from —
#: so the message names the replacement AND says plainly that nothing starts because of it.
_ALIGN_CONFIRM = {
    "pt-BR": ("Só para confirmar antes, porque isto muda **o que vai ser construído**: alinhar o "
              "*#{number}* ao *requisito {requirement}: {title}* faz duas coisas. O item passa a "
              "citar o requisito {requirement} como origem, e eu reescrevo o que precisa ser "
              "verdade para considerá-lo feito a partir desse texto — o que está escrito ali hoje "
              "sai.\n\n"
              "Não é acertar a redação: se alguém estava se guiando pelo que estava escrito, o "
              "alvo muda.\n\n"
              "Nada começa por causa disso — o item continua onde está, e começar continua sendo "
              "decisão de vocês.\n\nConfirma?"),
    "en": ("To confirm first, because this changes **what gets built**: aligning *#{number}* to "
           "*requirement {requirement}: {title}* does two things. The item starts citing "
           "requirement {requirement} as its source, and I rewrite what has to be true to call it "
           "done from that text — whatever is written there today goes.\n\nThis is not tidying "
           "wording: if somebody was working to what was written, the target moves.\n\nNothing "
           "starts because of it — the item stays where it is, and starting is still your call."
           "\n\nConfirm?"),
}
_CARD_ALIGNED = {
    "pt-BR": ("Alinhado: o *#{number}* passa a citar o *requisito {requirement}*, e o que precisa "
              "ser verdade para considerá-lo feito veio desse texto. Deixei registrado no item "
              "que fui eu e a partir de quê. **Nada começou por causa disso.**"),
    "en": ("Aligned: *#{number}* now cites *requirement {requirement}*, and what has to be true to "
           "call it done came from that text. I recorded on the item that it was me and what from. "
           "**Nothing started because of it.**"),
}
#: The same act with its second half missing — the criteria were replaced and the note explaining
#: that they were could not be left. TWO TEXTS, like `close`'s: the sentence above promises whoever
#: opens the card an explanation that is not on it, and that card is the one somebody picks up next.
#: What went wrong is said by the module, in its own words, straight after this.
_CARD_ALIGNED_UNEXPLAINED = {
    "pt-BR": ("Alinhado: o *#{number}* passa a citar o *requisito {requirement}*, e o que precisa "
              "ser verdade para considerá-lo feito veio desse texto. **Nada começou por causa "
              "disso.**"),
    "en": ("Aligned: *#{number}* now cites *requirement {requirement}*, and what has to be true to "
           "call it done came from that text. **Nothing started because of it.**"),
}
#: Refusing to write a card's criteria from a retired text — the exact damage this act exists to
#: undo, arriving from the other direction. It NAMES the replacement and the sentence that would
#: work, because a refusal that leaves somebody at a dead end is how a person stops asking.
_ALIGN_TO_SUPERSEDED = {
    "pt-BR": ("o *requisito {requirement}* foi substituído pelo *requisito {successor}* — escrever "
              "um item a partir de um texto aposentado é justamente o problema que eu estaria "
              "criando. Me diga «alinha o #{number} ao requisito {successor}» e eu preparo."),
    "en": ("*Requirement {requirement}* was replaced by *requirement {successor}* — writing an "
           "item from a retired text is exactly the problem I would be creating. Say \"align "
           "#{number} to requirement {successor}\" and I'll prepare it."),
}
_ALIGN_TO_DROPPED = {
    "pt-BR": ("o *requisito {requirement}* foi abandonado e nada entrou no lugar dele — não dá "
              "para dizer que o *#{number}* está pronto por um texto que ninguém vai cumprir. Se "
              "houver outro requisito que valha para ele, me diga qual."),
    "en": ("*Requirement {requirement}* was dropped and nothing replaced it — I cannot judge "
           "*#{number}* done against a text nobody will honour. If another requirement applies to "
           "it, tell me which."),
}
#: Replaced by a text NOBODY HAS AGREED TO YET — the commonest shape of all, and the one the three
#: sentences around it could not say. `propose_requirement` stamps the predecessor as retired in the
#: same commit that writes the replacement as a proposal, so between that commit and somebody's yes
#: every alignment onto the old number lands here. It is not a broken chain (the text is there and
#: reads fine) and it is not an abandonment (somebody decided the opposite), and being told either
#: sends a client to look for a problem that does not exist. What it is, is one confirmation away —
#: so the sentence names both steps, in the order they have to happen.
_ALIGN_TO_UNAGREED = {
    "pt-BR": ("o *requisito {requirement}* foi substituído pelo *requisito {successor}*, e o "
              "{successor} ainda não foi acordado — escrever o *#{number}* a partir de uma "
              "proposta seria decidir por vocês. Se ele já vale, me diga «aceita o requisito "
              "{successor}» e depois «alinha o #{number} ao requisito {successor}»."),
    "en": ("*Requirement {requirement}* was replaced by *requirement {successor}*, and "
           "{successor} has not been agreed yet — writing *#{number}* from a proposal would be "
           "deciding for you. If it holds, say \"accept requirement {successor}\" and then "
           "\"align #{number} to requirement {successor}\"."),
}
#: Replaced by a text that was ITSELF taken off the table — REQ-0004 `superseded-by 0006` with 0006
#: `dropped`. None of the sentences around it can say that: the chain is not broken (both texts read
#: perfectly well), the requirement was not abandoned with nothing in its place, and above all this
#: is not one confirmation away. Told it was, a client would be sent to agree to the very text they
#: had decided against — and agreeing writes it back into force. So this one names both numbers,
#: says neither holds, and asks the only question left.
_ALIGN_TO_DROPPED_REPLACEMENT = {
    "pt-BR": ("o *requisito {requirement}* foi substituído pelo *requisito {successor}*, e o "
              "{successor} também já não vale — escrever o *#{number}* a partir de qualquer um "
              "dos dois seria mandar construir por um texto que ninguém vai cumprir. Se houver "
              "outro requisito que valha para o *#{number}*, me diga qual."),
    "en": ("*Requirement {requirement}* was replaced by *requirement {successor}*, and "
           "{successor} no longer holds either — writing *#{number}* from either of them would "
           "mean building from a text nobody will honour. If another requirement applies to "
           "*#{number}*, tell me which."),
}
#: Replaced, and the replacement cannot be read. A retired requirement whose successor is not in the
#: base is an inconsistency on our side, and the two sentences above would each be a lie about it:
#: one would send the person to a number nobody can open, the other would tell them it was
#: abandoned. Saying so plainly costs the person one rephrase and costs us the bug report we need.
_ALIGN_CHAIN_BROKEN = {
    "pt-BR": ("o *requisito {requirement}* foi substituído, e eu não consegui achar o texto que "
              "entrou no lugar dele — então não escrevo o *#{number}* a partir de nenhum dos "
              "dois. O time já tem o detalhe. Se você souber qual requisito vale hoje, me diga o "
              "número."),
    "en": ("*Requirement {requirement}* was replaced and I could not find the text that took its "
           "place — so I am writing *#{number}* from neither. The team has the detail. If you know "
           "which requirement holds today, tell me the number."),
}


def align_confirmation(*, number: str, requirement: int, title: str,
                       language: str | None = None) -> str:
    return _pick(_ALIGN_CONFIRM, language).format(number=number, requirement=requirement,
                                                  title=title)


def card_aligned(*, number: str, requirement: int, noted: bool = True,
                 language: str | None = None, agent_name: str = "") -> str:
    """`noted` is False when the note explaining the rewrite could not be left on the card.

    The same split `card_closed` makes, for the same reason: a success line that describes the
    happy path is read out over every other one, and this one would promise an explanation to
    whoever opens a card whose criteria have just changed underneath them.
    """
    sig = f"{agent_name}: " if agent_name.strip() else ""
    catalogue = _CARD_ALIGNED if noted else _CARD_ALIGNED_UNEXPLAINED
    return sig + _pick(catalogue, language).format(number=number, requirement=requirement)


def align_refused(*, number: str, requirement: int, successor: int | None = None,
                  replaced: bool = False, language: str | None = None) -> str:
    """Why a card cannot be written from this requirement — and what to say instead.

    `successor` is the LIVE end of the supersession chain, never one hop along it: pointing at
    another retired text is the very thing this refusal exists to stop, and a person following the
    instruction would land on the same refusal one number further on. `replaced` says the chain
    exists but could not be walked, which is neither of the other two answers.
    """
    if successor:
        catalogue = _ALIGN_TO_SUPERSEDED
    else:
        catalogue = _ALIGN_CHAIN_BROKEN if replaced else _ALIGN_TO_DROPPED
    return _pick(catalogue, language).format(number=number, requirement=requirement,
                                             successor=successor or "")


def align_to_unagreed(*, number: str, requirement: int, successor: int,
                      language: str | None = None) -> str:
    """The replacement is written and readable, and nobody has said yes to it yet.

    Separate from `align_refused` because it is not a refusal of the same kind: the other three say
    what cannot be done, this one says what has to happen first — and names it as two sentences a
    person can type, in order.
    """
    return _pick(_ALIGN_TO_UNAGREED, language).format(number=number, requirement=requirement,
                                                      successor=successor)


def align_to_dropped_replacement(*, number: str, requirement: int, successor: int,
                                 language: str | None = None) -> str:
    """The replacement is readable and was itself taken off the table.

    The sibling of `align_to_unagreed`, and separate for the same reason: "not agreed yet" and "not
    agreed, ever" send a person to two different places. Only the first has a next step the client
    can type, and offering it here would be inviting them to reinstate what they cancelled.
    """
    return _pick(_ALIGN_TO_DROPPED_REPLACEMENT, language).format(
        number=number, requirement=requirement, successor=successor)


#: What `refine` says when the card already states what must be true. THE REFUSAL IS RIGHT — it
#: exists to unblock cards with nothing written, and rewriting prose nobody complained about is how
#: an agent churns a board and teaches people to stop reading its comments.
#:
#: What it lacked was somewhere to go. In production it fired on #516, correctly, and the client
#: was left holding a card whose criteria were written from a requirement that has since been
#: replaced — with no word for the act that would fix it. A refusal that names no alternative is
#: read as "this cannot be done"; the alternative is a different act, on purpose, because changing
#: criteria somebody may already be working from is not the same risk as writing where there was
#: nothing.
_REFINE_REFUSED = {
    "pt-BR": ("o *#{number}* já dizia quando estaria pronto — não mexi. Reescrever o que ninguém "
              "reclamou só ensina o time a parar de ler o que eu escrevo.\n\n"
              "Se o que está escrito ali não é mais o que foi combinado, aí é outro pedido, e ele "
              "tem nome: *alinhar*. Me diga «alinha o #{number} ao requisito N» e eu preparo a "
              "mudança para vocês confirmarem — nada muda antes disso."),
    "en": ("*#{number}* already said when it would be done — I left it alone. Rewriting what "
           "nobody complained about only teaches the team to stop reading what I write.\n\nIf what "
           "is written there is no longer what was agreed, that is a different request and it has "
           "a name: *align*. Say \"align #{number} to requirement N\" and I'll prepare the change "
           "for you to confirm — nothing changes before that."),
}


def refine_refused(*, number: str, language: str | None = None) -> str:
    return _pick(_REFINE_REFUSED, language).format(number=number)


#: What `refine` says when it wrote criteria onto a card that had none. `refine` writes TWICE — the
#: criteria, then the comment attributing them — and reports the second one failing as a SUCCESS
#: carrying a sentence for the client, exactly as `close_card` and `align_card` do.
#:
#: SO THE NOTE IS A FLAG, like `linked` and `noted` above it. The line used to announce the comment
#: unconditionally AND splice the module's "I could not leave the comment" sentence into the slot
#: meant for the count, so one sentence denied and asserted the same note eight words apart. Three
#: siblings had already been given this split; this was the fourth and it was left behind.
_CRITERIA_WRITTEN = {
    "pt-BR": ("escrevi no #{number} o que precisa ser verdade para considerá-lo feito{measure}, e "
              "deixei um comentário dizendo que fui eu. O texto de quem descreveu o item continua "
              "lá — só acrescentei."),
    "en": ("I wrote in #{number} what has to be true to call it done{measure}, and left a comment "
           "saying it was me. What the person who described the item wrote is still there — I only "
           "added to it."),
}
#: The same act with its second half missing. No count either: what the module has to say in place
#: of one is said straight after this, in its own words.
_CRITERIA_WRITTEN_UNEXPLAINED = {
    "pt-BR": ("escrevi no #{number} o que precisa ser verdade para considerá-lo feito. O texto de "
              "quem descreveu o item continua lá — só acrescentei."),
    "en": ("I wrote in #{number} what has to be true to call it done. What the person who "
           "described the item wrote is still there — I only added to it."),
}


def criteria_written(*, number: str, measure: str = "", noted: bool = True,
                     language: str | None = None) -> str:
    """`noted` is False when the comment saying who wrote them could not be left on the card.

    `measure` is what the module counted ("3 critérios") and is shown only alongside a whole act:
    the field it comes from carries a residue sentence instead whenever the second write failed,
    and a residue in the slot meant for a count is how the two facts got said in one breath.
    """
    catalogue = _CRITERIA_WRITTEN if noted else _CRITERIA_WRITTEN_UNEXPLAINED
    return _pick(catalogue, language).format(
        number=number, measure=f" ({measure.strip()})" if measure.strip() else "")


#: What she is still waiting on, said to the person who asked how things are going. Two clauses,
#: joined only when both apply — "aguardo resposta sobre nada" is worse than saying nothing.
_STILL_WAITING_QUESTIONS = {
    "pt-BR": "aguardo resposta sobre {listed}{more}",
    "en": "waiting on an answer about {listed}{more}",
}
_STILL_WAITING_MORE = {"pt-BR": " (+{n})", "en": " (+{n})"}
_STILL_WAITING_DELIVERIES = {
    "pt-BR": "acompanho a entrega de {n} pedido{s}",
    "en": "following the delivery of {n} request{s}",
}


def still_waiting(*, questions: list[str], deliveries: int,
                  language: str | None = None) -> str:
    """Her open loops in one line, or "" when there are none.

    THE CONVERSATIONAL HALF OF THE VISIBLE LIST — the panel's `/api/loops` is the other. The chase
    policy stops at one reminder by design, so anything past it must be findable by ASKING, or a
    question with a slow answer quietly stops existing.

    Refs are printed as the tracker wrote them (C-05); at most five are named, because a status
    line that lists twenty is a wall nobody reads and the count already says how many there are."""
    parts: list[str] = []
    if questions:
        listed = ", ".join(f"#{q}" for q in questions[:5])
        more = (_pick(_STILL_WAITING_MORE, language).format(n=len(questions) - 5)
                if len(questions) > 5 else "")
        parts.append(_pick(_STILL_WAITING_QUESTIONS, language).format(listed=listed, more=more))
    if deliveries:
        parts.append(_pick(_STILL_WAITING_DELIVERIES, language).format(
            n=deliveries, s="s" if deliveries != 1 else ""))
    return " · ".join(parts)
