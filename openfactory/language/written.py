"""Which language a text the platform is about to write is IN — `None` when it cannot tell (#429).

A card the product role drafted for an English conversation came out in Portuguese: the layout was
Portuguese and the model wrote in the layout's language, whatever the prompt said. The drafter is
now handed a layout in the right language and told the language by name — and the floor checks
the result, because an instruction a model can ignore is not a guarantee.

A CHECK THAT REFUSES MUST NOT GUESS. A refused draft costs a redraft, and two refusals cost the
card: the person is asked a question instead of shown their card. So this answers only when the
evidence is lopsided — enough function words, most of them one language's — and `None` otherwise.
`None` passes. The words are the ones a sentence cannot avoid (articles, prepositions, the verb
"to be"), never content words: a card about "the Studio" or "o login" names things in any language.
"""

from __future__ import annotations

import re
import unicodedata

#: The words no sentence of that language avoids for long, normalised (lowercase, unaccented). A
#: word common to both — `a`, `do`, `no` — is in neither: it proves nothing.
FUNCTION_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset({
        "the", "and", "is", "are", "was", "were", "to", "of", "with", "when", "this", "that",
        "it", "for", "on", "in", "from", "by", "be", "not", "which", "there", "should", "must",
        "at", "or", "an", "its", "has", "have", "can",
    }),
    "pt": frozenset({
        "o", "os", "as", "um", "uma", "de", "da", "das", "dos", "que", "com", "para", "por",
        "quando", "nao", "esta", "sao", "foi", "ser", "deve", "na", "nas", "nos", "ao", "aos",
        "pelo", "pela", "isso", "este", "essa", "ou", "tem", "fica", "e",
    }),
}

#: How many function words a text must carry before it is judged at all, and how lopsided the
#: count must be. Measured on the cards the loop writes: a description is two to six sentences.
ENOUGH = 8
LOPSIDED = 3


def _words(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.findall(r"[a-z]+", plain)


def base(language: str | None) -> str:
    """`pt-BR` → `pt`, `en-US` → `en`, `None` → `""`."""
    return (language or "").strip().split("-")[0].lower()


def written_in(text: str) -> str | None:
    """`en`, `pt`, or `None` when the text does not say clearly enough."""
    counts = {lang: 0 for lang in FUNCTION_WORDS}
    for word in _words(text):
        for lang, table in FUNCTION_WORDS.items():
            if word in table:
                counts[lang] += 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    (top, most), (_other, next_most) = ranked[0], ranked[1]
    if most < ENOUGH or most < LOPSIDED * max(next_most, 1):
        return None
    return top


def not_in(text: str, language: str | None) -> str | None:
    """The language `text` is CLEARLY written in when that is not `language` — `None` when it is,
    when the text does not say, or when `language` is one this module has no words for."""
    wanted = base(language)
    if wanted not in FUNCTION_WORDS:
        return None
    found = written_in(text)
    return found if found and found != wanted else None
