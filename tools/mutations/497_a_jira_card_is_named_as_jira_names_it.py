"""On Jira, every sentence names a card as Jira does, and the board's refusals speak the
conversation's language (#497).

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/497_a_jira_card_is_named_as_jira_names_it.py

Row 1 is the label: a key a person typed with its `#` keeps it. Rows 2-19 put GitHub's `#` back in
front of a card, one sentence family at a time — the queue's and the filing's, a close catalogue,
a close composer handing the raw ref to a table with no `#` of its own (so `#12` would lose its
hash: the numbered half of the claim), an adjust pass made ready (#413) and the card's door's
three refusals, which `promote` answers with since it queues through the door (#414), the events'
card, the waiting line, the agenda's question, the cards named after a breakdown, the follow-ups
and the releases waiting. Rows 20-24 put the module's details back as Portuguese literals, or the
voice ignoring the conversation's language. Rows 25-26 are for the guard alone: a new catalogue
and a new f-string that write `#` before a card, which no rendered sentence under test reaches.
Row 27 is the order: the cards that landed are sorted again before the reply says "nesta ordem".
"""

TEST = "tests/test_a_jira_card_is_named_as_jira_names_it.py"

REFS = "openfactory/contracts/refs.py"
CONFIRM = "openfactory/product/confirm.py"
VOICE = "openfactory/product/voice.py"
MOD = "openfactory/product/module.py"
FOLLOWUP = "openfactory/product/followup.py"
ENGINE = "openfactory/product/engine.py"
PORTS = "openfactory/lifecycle/ports.py"

MUTATIONS = [
    # ── the label ──────────────────────────────────────────────────────────────────────────────
    ("a key typed with GitHub's `#` keeps it: `#CONT-412` is labelled `#CONT-412`", REFS,
     '    text = str(ref or "").strip().lstrip("#").strip()\n    if not text:\n        return ""\n'
     '    return f"#{text}" if text.isdigit() else text',
     '    text = str(ref or "").strip()\n    if not text:\n        return ""\n'
     '    return f"#{text.lstrip(\'#\')}" if text.lstrip("#").isdigit() else text'),

    # ── the `#` back in front of a card ─────────────────────────────────────────────────────────
    ("the order read back before the yes says `#CONT-412`", VOICE,
     '    return _pick(_REORDER_CONFIRM, language).format(\n'
     '        order=", ".join(ref_label(n) for n in numbers))',
     '    return _pick(_REORDER_CONFIRM, language).format(\n'
     '        order=", ".join(f"#{n}" for n in numbers))'),

    ("the order written is read back as `#DAR-10, #DAR-9`", VOICE,
     'return sig + _pick(_REORDERED, language).format(order=", ".join(ref_label(n) for n in '
     'numbers))',
     'return sig + _pick(_REORDERED, language).format(order=", ".join(f"#{n}" for n in '
     'numbers))'),

    ("the proposed queue names each card `**#CONT-412**`", VOICE,
     "        lines.append(f\"{i}. **{ref_label(item.ticket)}**",
     "        lines.append(f\"{i}. **#{item.ticket}**"),

    ("…and what it left out `• #CONT-431`", VOICE,
     '        lines += [f"• {ref_label(h.ticket)} — {h.why}" for h in proposal.held_back[:5]]',
     '        lines += [f"• #{h.ticket} — {h.why}" for h in proposal.held_back[:5]]'),

    ("a card filed with no link is `#CONT-412`", VOICE,
     "    where = url or ref_label(ref)\n",
     '    where = url or (f"#{ref}" if ref else "")\n'),

    ("a defect somebody just asked for is `#CONT-412`", VOICE,
     "        return just_asked_for_a_card(where=url or ref_label(ref), language=language)",
     '        return just_asked_for_a_card(where=url or (f"#{ref}" if ref else ""), '
     "language=language)"),

    ("the close-in-favour catalogue writes `*#{number}*` again", VOICE,
     '    "en": ("Closed *{number}* in favour of *{other}*. I wrote on both',
     '    "en": ("Closed *#{number}* in favour of *#{other}*. I wrote on both'),

    ("the close composer hands the raw ref to a table that no longer has a `#`, so `#12` reads "
     "`12`", VOICE,
     "    text = _pick(catalogue, language).format(number=ref_label(number),\n"
     "                                             other=ref_label(in_favour_of))",
     "    text = _pick(catalogue, language).format(number=number,\n"
     '                                             other=in_favour_of or "")'),

    ("the pass a requester is told is ready names its card `#CONT-412`", VOICE,
     '"pass_ready": ("{sig}Pass {pass_number} of {ref}{title} is ready',
     '"pass_ready": ("{sig}Pass {pass_number} of #{ref}{title} is ready'),

    ("the card's door refuses a card it cannot read as `#DAR-9`", PORTS,
     '            return Seen(cannot_tell=(f"{ref_label(card)} could not be read',
     '            return Seen(cannot_tell=(f"#{card} could not be read'),

    ("…a card on a board it cannot read", PORTS,
     '                f"{ref_label(card)} is. Nothing was changed — try again."))',
     '                f"#{card} is. Nothing was changed — try again."))'),

    ("…and a card in a column nobody mapped", PORTS,
     '                f"{ref_label(card)} is in {column!r}, which is not a column',
     '                f"#{card} is in {column!r}, which is not a column'),

    ("the events name the card `#CONT-412` (ready, preview, checks, withdrawn)", VOICE,
     '_CARD = {"pt-BR": "o {ref}{title}", "en": "{ref}{title}"}',
     '_CARD = {"pt-BR": "o #{ref}{title}", "en": "#{ref}{title}"}'),

    ("the waiting line names the question's card `#CONT-412`", VOICE,
     '        listed = ", ".join(ref_label(q) for q in questions[:5])',
     '        listed = ", ".join(f"#{q}" for q in questions[:5])'),

    ("the agenda's question names its card `#CONT-412`", VOICE,
     '"question": {"pt-BR": "uma resposta sobre o {card}", "en": "an answer about {card}"},',
     '"question": {"pt-BR": "uma resposta sobre o #{subject}", "en": "an answer about '
     '#{subject}"},'),

    ("the cards a breakdown opened are named as the module held them — `12`, not `#12`", VOICE,
     "    refs = [ref_label(c) for c in cards]\n",
     "    refs = [str(c) for c in cards]\n"),

    ("the question asked about a stalled card names it `#CONT-412`", FOLLOWUP,
     '    who = f"{mention} — " if mention else ""\n'
     '    title = (loop.context or {}).get("title", "")\n'
     '    about = f"{ref_label(loop.subject)} ({title})" if title else ref_label(loop.subject)',
     '    who = f"{mention} — " if mention else ""\n'
     '    title = (loop.context or {}).get("title", "")\n'
     '    about = f"#{loop.subject} ({title})" if title else f"#{loop.subject}"'),

    # re-pinned 2026-10-04: the "not yet" branch lists the same way since #508, so the anchor
    # carries the line before it and its indentation (review of the merge of #508)
    ("the releases waiting are listed `#CONT-412`", ENGINE,
     """        listed = _waiting_release_refs(project)\n"""
     """        which = f" ({', '.join(ref_label(r) for r in listed)})" if listed else \"\"""",
     """        listed = _waiting_release_refs(project)\n"""
     """        which = f" ({', '.join(f'#{r}' for r in listed)})" if listed else \"\""""),

    # ── the module's details, in one language ───────────────────────────────────────────────────
    # re-pinned 2026-10-04: merge of main into #458 (#514/#507) — the queue goes through the
    # card's door, and a placement it could not make is said from the module's own table
    ("the queue the board refused is answered in Portuguese again", MOD,
     '                said = _pick(_FILING, lang)',
     '                said = _pick(_FILING, "pt-BR")'),

    ("a queue move that raised is the Portuguese literal again, naming `#DAR-9`", MOD,
     '                out.append(_could_not(board_move_said("queue_failed", ref=number, '
     "language=lang),",
     '                out.append(_could_not(f"não consegui mover o #{number} para a fila agora. '
     'O time foi avisado e resolve.",'),

    ("the order the board refused is answered in Portuguese again", MOD,
     '        refused = board_move_said("order_refused", language=lang)',
     '        refused = "o quadro recusou a reordenação"'),

    ("an order move that raised is the Portuguese literal again, naming `#DAR-9`", MOD,
     '                out.append(_could_not(board_move_said("order_failed", ref=number, '
     "language=lang),",
     '                out.append(_could_not(f"não consegui reposicionar o #{number} agora. O time '
     'foi avisado e resolve.",'),

    ("the board's words ignore the conversation's language", VOICE,
     "    return _pick(_BOARD_MOVE_SAID[reason], language).format(ref=ref_label(ref))",
     '    return _pick(_BOARD_MOVE_SAID[reason], "pt-BR").format(ref=ref_label(ref))'),

    # ── for the guard alone ─────────────────────────────────────────────────────────────────────
    ("a new catalogue writes `#{ref}` — no sentence under test renders it", VOICE, "",
     '\n_LATER = {"pt-BR": "o #{ref} chegou", "en": "#{ref} arrived"}\n'),

    ("a new composer writes `f\"#{n}\"` — no sentence under test renders it", FOLLOWUP, "",
     '\n\ndef _later(n):\n    return f"card #{n}"\n'),

    # ── the order the person approved ───────────────────────────────────────────────────────────
    # re-pinned 2026-10-04: one line keeps the tracker's refs in the approved order (#491 + #497)
    ("the cards that landed are sorted before the reply says \"nesta ordem\"", CONFIRM,
     "    landed = list(dict.fromkeys(canonical_ref(r.ref) for r in results if r.ok and r.ref))",
     "    landed = sorted(dict.fromkeys(canonical_ref(r.ref) for r in results if r.ok and r.ref))"),
]
