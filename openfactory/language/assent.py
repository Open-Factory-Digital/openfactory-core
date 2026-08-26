"""Does this message ASSENT to what the platform just staged? — one table, every surface (#161).

Three hand-rolled vocabularies answered this before: `product/staging.py`, `runtime/slack/bot.py`
and (at phrase level) `actions/floor_intents.py`. The measured drift was `certo` — CORE on the
product channel, allowed-but-not-core on the operator channel, and audited OUT of the floor's
table with a reason ("understood as often as do it"). One word, three answers, same situation:
replying to a question the platform had just staged.

TWO BARS, DECLARED RATHER THAN ACCIDENTAL. The floor's gesture presses a button that MERGES, so
it asks that the whole message BE an assent (`is_bare_assent`). The product and operator channels
approve a staged proposal in conversation, where "sim, pode registrar" is the most Brazilian
confirmation there is, so they ask that every word be catalogued and at least one assert
(`asserts_assent`). Different bars, one vocabulary — which is the only way they can be compared
at all.

THE ADMISSION RULE FOR A NEW ROW, and every existing entry was audited against it: a word is CORE
only if, as the whole of a reply to a staged question, it can mean nothing but assent in EVERY
catalogued language. `ta` is out (British "thanks"); `certo` is out ("understood" as often as "do
it"); `pode ser` is out (it agrees with a suggestion rather than ordering it). A word that fails
is NOT dropped — dropping it lets the other list decide alone — it goes to FILLER, where it may
accompany a yes and never be one.
"""

from __future__ import annotations

import re

#: Single words that ASSERT assent, per language. Adding a language is a row here.
CORE: dict[str, tuple[str, ...]] = {
    "en": ("yes", "yep", "yeah", "sure", "ok", "okay", "confirm", "confirmed", "approved",
           "approve", "agreed", "go", "proceed", "lgtm"),
    # `tá` CARRIES ITS ACCENT ON PURPOSE — see the note beside `ta` in FILLER. It is how a
    # Brazilian answers a yes/no question, and it was dropped into FILLER when these three tables
    # were consolidated (c9096d7, mine): the pilot typing a bare `tá` beside a staged merge button
    # got nothing, and no guard noticed because the assertion was rewritten to `tá bom` in the
    # same commit. Restored with a guard on BOTH halves.
    "pt-br": ("sim", "tá", "isso", "confirmo", "confirma", "confirmado", "claro", "exato",
              "perfeito",
              "beleza", "blz", "fechado", "combinado", "aprovado", "aprovo", "pode", "podes",
              "manda", "bora", "segue", "faz", "faça", "faca"),
}

#: MULTI-WORD assents. They exist because the word tier cannot express them: `vai` alone is a
#: hedge (and, in Portuguese, the future auxiliary — "vai quebrar" is a warning), while `vai lá`
#: is nothing but "go ahead". Matched as a whole message, never searched inside one.
CORE_PHRASES: dict[str, tuple[str, ...]] = {
    "en": ("go ahead", "do it", "ship it", "sounds good", "sure thing", "that's right",
           "thats right"),
    "pt-br": ("pode seguir", "pode ir", "pode prosseguir", "pode mandar", "manda ver",
              "segue o baile", "vai lá", "vá lá", "tá bom", "ta bom", "isso aí", "isso ai"),
}

#: Words a yes may CARRY without being one: an echo of the question, a politeness, a hedge.
FILLER: dict[str, tuple[str, ...]] = {
    "en": ("please", "ahead", "right", "thats", "that's", "it", "then", "now", "also", "and",
           "do", "just"),
    # NO PHRASE-ONLY WORDS HERE. `seguir`, `mandar`, `bom` and friends exist only inside
    # CORE_PHRASES, which is matched as a WHOLE message — putting them here would let them
    # accompany a yes anywhere, and it did: "isso mesmo, pode mandar" became a fast-path approval
    # and promoted a queue the judge never saw. The existing money guard caught it in one run.
    "pt-br": ("certo", "correto", "mesmo", "registrar", "registra", "anotar", "anota", "vai",
              "lá", "la", "aí", "ai", "por", "favor", "então", "entao", "e", "depois", "agora",
              # `ta` — NOT `tá` — because in British English a bare "ta" is *thanks*, and
              # thanking a bot is not approving a merge. The accented form collides with no
              # catalogued language, so it lives in CORE above. This is the collision discipline,
              # not an oversight: `test_the_collision_discipline_holds` names both.
              "também", "tambem", "ta"),
}


def _flat(table: dict[str, tuple[str, ...]]) -> frozenset[str]:
    """THE UNION, NOT THE CONFIGURED LANGUAGE'S ROW — for the reason #157 measured: the pilot's
    project is configured `en` and he answers in Portuguese, because people reply in their own
    tongue whatever the config says. Keying on the setting would refuse the exact word the card
    was filed about. Safe here because assent is only consulted when something is actually staged,
    and because the message must be made ENTIRELY of catalogued words."""
    return frozenset(w for row in table.values() for w in row)


def core_words() -> frozenset[str]:
    return _flat(CORE)


def core_phrases() -> frozenset[str]:
    return _flat(CORE_PHRASES)


def filler_words() -> frozenset[str]:
    return _flat(FILLER)


def words_of(text: str) -> list[str]:
    """The message as words, accents kept — the split all three callers used to write themselves."""
    return re.findall(r"[a-zà-ÿ']+", (text or "").lower())


def is_bare_assent(text: str) -> bool:
    """The whole message IS an assent — the FLOOR's bar, because that gesture merges (#156).

    Anchored on purpose: a miss costs a rephrase, a false positive lands a pull request on a
    sentence that was agreement with an opinion. Trailing punctuation is allowed; a question mark
    is left for the caller's own question test, which every other gesture in `floor_intents` goes
    through — a second notion of "this is a question" is how two surfaces come to disagree.
    """
    body = (text or "").strip().rstrip(".!?…").strip()
    if not body:
        return False
    normalised = " ".join(body.lower().split())
    return normalised in core_words() or normalised in core_phrases()


def asserts_assent(text: str) -> bool:
    """Every word catalogued, at least one CORE — the CHANNEL's bar, where a yes travels with
    politeness and an echo of the question.

    Deliberately narrow, and narrowing it was tried and abandoned in both previous homes: no
    vocabulary list can tell an affirmation from a word that happens to appear in one. Anything
    this refuses is NOT a no — it goes to the model judge, which is the only thing that can read a
    sentence (ADR-0028/ADR-0029).
    """
    body = text or ""
    if "?" in body:
        return False
    if is_bare_assent(body):
        return True  # a phrase the word tier cannot see ("vai lá", "go ahead")
    words = words_of(body)
    if not words:
        return False
    catalogued = core_words() | filler_words()
    return all(w in catalogued for w in words) and any(w in core_words() for w in words)
