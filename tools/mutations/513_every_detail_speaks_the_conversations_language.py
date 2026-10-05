"""Every detail the product role's writes answer speaks the conversation's language, and names a
card as its tracker does (#513).

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/513_every_detail_speaks_the_conversations_language.py

The claims:

  - the details of refine, close, remove, correct and align — and of every other write of
    `ProductModule`, and of the release — are voice entries in pt-BR and en, chosen by the
    conversation's language, and the module and the release compose none of their own;
  - they name a card with `ref_label`: `#12` on a numbered board, `CONT-412` on Jira;
  - `voice._listed` ends a cut list in the conversation's language, not a hard-coded "e mais";
  - #497's guard reads `module.py` and `release.py` too, and tells the ref handed to the tracker,
    the log line and the prompt from a sentence by where the string goes.

Rows 1-4 put a Portuguese-only literal back: refine's card not found, the criteria it counted, a
requirement already agreed, and the release that failed. Rows 5-7 write `#{…}` where `ref_label`
named the card: inside the card acts' own voice, in the release's refusal, and a card's note in
the module that no detail position reaches — only the guard sees that one. Row 8 is the cut-short
trailer of a queue proposal composed in the module again, the refs joined with GitHub's `#`. Rows
9-13 lose the conversation's language, or the label, one table at a time: the card acts, the
breakdown's card, the refusal to aim the factory at a text that is no promise, the release, and the
list cut short.
"""

TEST = "tests/test_a_jira_card_is_named_as_jira_names_it.py"

MOD = "openfactory/product/module.py"
VOICE = "openfactory/product/voice.py"
RELEASE = "openfactory/product/release.py"

MUTATIONS = [
    # ── a Portuguese-only literal back ──────────────────────────────────────────────────────────
    ("refine answers a card it cannot find in Portuguese, whatever the conversation speaks", MOD,
     '            return WriteResult(ok=False, detail=card_said("not_found", number=number,\n'
     '                                                          language=lang))\n'
     '        if has_criteria(ticket):',
     '            return WriteResult(ok=False, detail=f"não encontrei o {ref_label(number)}")\n'
     '        if has_criteria(ticket):'),

    # re-pinned 2026-10-05: the refine note is the voice's `refine_note` now (#538)
    ("refine counts what it wrote as \"3 critérios\" in every language", MOD,
     '        detail = criteria_counted(len(criteria), language=lang)\n'
     '        try:\n'
     '            tracker.comment(f"#{number}", refine_note(',
     '        detail = f"{len(criteria)} critérios"\n'
     '        try:\n'
     '            tracker.comment(f"#{number}", refine_note('),

    ("a requirement already agreed is \"esse já estava acordado\" again", MOD,
     '                               detail=record_said("already_agreed", language=lang),',
     '                               detail="esse já estava acordado",'),

    ("the release that failed says \"Nada subiu\" in an English conversation", RELEASE,
     '        return False, release_said("failed", language=lang)',
     '        return False, ("não consegui levar a sua liberação até a esteira agora. **Nada '
     'subiu**.")'),

    # ── `#{…}` where `ref_label` named the card ─────────────────────────────────────────────────
    ("the card acts name the card `#{number}` again — `#CONT-412` on Jira", VOICE,
     '    return _pick(_CARD_SAID[reason], language).format(\n'
     '        number=ref_label(number), other=ref_label(other), requirement=requirement)',
     '    return _pick(_CARD_SAID[reason], language).format(\n'
     '        number=f"#{number}", other=f"#{other}", requirement=requirement)'),

    ("the release that found nothing parked writes its own `o #{issue}` again", RELEASE,
     '            return False, release_said("not_waiting", ref=issue, language=lang)',
     '            return False, f"o #{issue} não está mais esperando essa liberação."'),

    # re-pinned 2026-10-05: the survivor note moved from the module into the voice (#538)
    ("the note on the surviving card says `o #DAR-9` — no detail reaches it, only the guard", VOICE,
     '    return _pick(_SURVIVOR_NOTE, language).format(sig=signature(agent_name), '
     'ref=ref_label(closed),',
     '    return _pick(_SURVIVOR_NOTE, language).format(sig=signature(agent_name), '
     'ref=f"#{closed}",'),

    ("the cards a batch boundary left are joined with `#` in the module again", MOD,
     '            trailer = queue_said("left_for_later", cards=[i.ticket for i in cut], '
     'language=lang)',
     '            trailer = queue_said("left_for_later", cards=[], language=lang).replace(\n'
     '                ": .", ": " + ", ".join(f"#{i.ticket}" for i in cut) + ".")'),

    # ── the conversation's language, or the label, lost one table at a time ─────────────────────
    ("the card acts ignore the conversation's language", VOICE,
     '    return _pick(_CARD_SAID[reason], language).format(\n',
     '    return _pick(_CARD_SAID[reason], "pt-BR").format(\n'),

    ("the breakdown's card is named as the module held it — `12`, not `#12`", VOICE,
     '        ref=ref_label(ref), title=title, why=why, number=number, default=where, '
     'target=target,',
     '        ref=ref, title=title, why=why, number=number, default=where, target=target,'),

    ("the refusal to aim the factory at a proposal is said in Portuguese everywhere", MOD,
     '    return not_a_promise(reason, number=number, language=language)',
     '    return not_a_promise(reason, number=number, language="pt-BR")'),

    ("the release forgets the project's language", RELEASE,
     '    lang = getattr(project, "language", None)\n',
     '    lang = None\n'),

    ("a list cut short ends in \"e mais\" again", VOICE,
     '    return _pick(_LISTED_MORE, language).format(shown=shown, rest=rest)',
     '    return f"{shown} e mais {rest}"'),
]
