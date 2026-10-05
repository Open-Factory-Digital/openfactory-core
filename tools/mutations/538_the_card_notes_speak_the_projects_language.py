"""The notes the product role leaves on a card speak the project's language, and the capability
write answers in the language its caller hands it (#538).

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/538_the_card_notes_speak_the_projects_language.py

The claims:

  1. **Each of the five notes is written in the project's language.** Rows 1-6: the module hands
     the voice no language for the closed card, the card it closed into, the removed card, the
     aligned one, the re-pointed one and the refined one — each falls back to English, and the
     pt-BR project's card reads it. Row 7 drops the questions the model could not answer.
  2. **The voice picks the note in the language it is handed, and names the card with
     `ref_label`.** Rows 8-14: a closing note, a survivor note, the questions' heading and the
     re-point's "at the request of" pinned to one language; the closing note naming the surviving
     card bare; nobody named as "o time" in every language; the refine's count composed as
     "N critérios" again.
  3. **The capability write answers in the language its caller passes.** Row 15: the module
     stops handing it the project's; row 16: the retired capability ignores it; row 17: the name
     that is no capability is the Portuguese literal again.
  4. **The guard reads the notes and `capabilities.py`.** Rows 18-19 compose a note in the
     module — the refine's comment, the removal's `"note"` for the card's door; row 20 puts git's
     output back into the capability write's detail. Only the guard sees those as such.
"""

TEST = "tests/test_the_card_notes_speak_the_projects_language.py"

GUARD = ("tests/test_a_jira_card_is_named_as_jira_names_it.py::"
         "test_the_module_and_the_release_compose_no_detail_of_their_own")

MOD = "openfactory/product/module.py"
VOICE = "openfactory/product/voice.py"
CAPS = "openfactory/product/capabilities.py"

MUTATIONS = [
    # ── the module hands each note the project's language ─────────────────────────────────────
    ("the closed card's note is written in English on a pt-BR project", MOD,
     '                                  "note": closing_note(in_favour_of=in_favour_of, '
     'actor=actor,\n'
     '                                                       reason=reason, language=lang,\n',
     '                                  "note": closing_note(in_favour_of=in_favour_of, '
     'actor=actor,\n'
     '                                                       reason=reason, language=None,\n'),

    ("the card closed into is told in English on a pt-BR project", MOD,
     '                                survivor_note(closed=number, actor=actor, language=lang,\n',
     '                                survivor_note(closed=number, actor=actor, language=None,\n'),

    ("the removed card's note is written in English on a pt-BR project", MOD,
     '                           facts={"note": closing_note(in_favour_of=None, actor=actor,\n'
     '                                                       reason=reason, language=lang,\n',
     '                           facts={"note": closing_note(in_favour_of=None, actor=actor,\n'
     '                                                       reason=reason, language=None,\n'),

    ("the aligned card's note is written in English on a pt-BR project", MOD,
     '                requirement=requirement, questions=answer.get("questions") or (), '
     'language=lang,\n',
     '                requirement=requirement, questions=answer.get("questions") or (), '
     'language=None,\n'),

    ("the re-pointed card's warning is written in English on a pt-BR project", MOD,
     '                                repoint_note(cited=cited, successor=successor, actor=actor,\n'
     '                                             language=lang, agent_name=self._name()))',
     '                                repoint_note(cited=cited, successor=successor, actor=actor,\n'
     '                                             language=None, agent_name=self._name()))'),

    ("the refined card's note is written in English on a pt-BR project", MOD,
     '                criteria=len(criteria), questions=answer.get("questions") or (), '
     'language=lang,\n',
     '                criteria=len(criteria), questions=answer.get("questions") or (), '
     'language=None,\n'),

    ("the aligned card's note drops what the model could not determine", MOD,
     '                requirement=requirement, questions=answer.get("questions") or (), '
     'language=lang,\n',
     '                requirement=requirement, questions=(), language=lang,\n'),

    # ── the voice picks the language it is handed, and names the card ──────────────────────────
    ("the closing note is Portuguese whatever the project speaks", VOICE,
     '    note = _pick(catalogue, language).format(sig=signature(agent_name),',
     '    note = _pick(catalogue, "pt-BR").format(sig=signature(agent_name),'),

    ("the survivor note is Portuguese whatever the project speaks", VOICE,
     '    return _pick(_SURVIVOR_NOTE, language).format(',
     '    return _pick(_SURVIVOR_NOTE, "pt-BR").format('),

    ("what the model could not determine is headed in Portuguese everywhere", VOICE,
     '    return (_pick(_COULD_NOT_DETERMINE, language) + ',
     '    return (_pick(_COULD_NOT_DETERMINE, "pt-BR") + '),

    ("the re-point names who asked in Portuguese on an English card", VOICE,
     '    who = _pick(_REPOINT_WHO, language).format(actor=actor) if actor else ""',
     '    who = _pick(_REPOINT_WHO, "pt-BR").format(actor=actor) if actor else ""'),

    ("the closing note names the surviving card bare — `288`, not `#288`", VOICE,
     '                                             ref=ref_label(in_favour_of))',
     '                                             ref=in_favour_of)'),

    ("a close nobody named is \"o time\" in every language", VOICE,
     '                                             who=actor or _pick(_THE_TEAM, language),\n',
     '                                             who=actor or "o time",\n'),

    ("the refine note counts \"N critérios\" again, in every language and for one", VOICE,
     '        sig=signature(agent_name), criteria=criteria_counted(criteria, language=language))',
     '        sig=signature(agent_name), criteria=f"{criteria} critérios")'),

    # ── the capability write ───────────────────────────────────────────────────────────────────
    ("the module stops handing the capability write the project's language", MOD,
     '                    base=getattr(cfg, "docs_branch", "main"), language=lang),',
     '                    base=getattr(cfg, "docs_branch", "main")),'),

    ("a retired capability is refused in English whatever the caller speaks", CAPS,
     '                                   detail=record_said("capability_retired", '
     'language=language))',
     '                                   detail=record_said("capability_retired", language=None))'),

    ("the name that is no capability is the Portuguese literal again", CAPS,
     '        return WriteResult(ok=False, detail=record_said("not_a_capability", '
     'language=language))',
     '        return WriteResult(ok=False, detail="esse nome não é o de uma capacidade")'),

    # ── only the guard sees these ──────────────────────────────────────────────────────────────
    ("the refine's note is composed in the module, in Portuguese", MOD,
     '            tracker.comment(f"#{number}", refine_note(\n'
     '                criteria=len(criteria), questions=answer.get("questions") or (), '
     'language=lang,\n'
     '                agent_name=self._name()))\n',
     '            tracker.comment(f"#{number}", f"Escrevi {len(criteria)} critérios — corrijam se '
     'eu entendi errado.")\n',
     GUARD),

    ("the removal hands the card's door a note composed in the module", MOD,
     '                           facts={"note": closing_note(in_favour_of=None, actor=actor,\n'
     '                                                       reason=reason, language=lang,\n'
     '                                                       agent_name=self._name())},\n',
     '                           facts={"note": f"fechado a pedido de {actor}."},\n',
     GUARD),

    ("a clone that failed hands git's output to the person again", CAPS,
     '            return failed("could not clone", out)',
     '            return WriteResult(ok=False,\n'
     '                               detail=f"could not clone {docs_repo}: {_scrub(out)[-200:]}")',
     GUARD),
]
