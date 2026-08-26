"""#160: nothing speaks, unprompted, in a language nobody asked it about."""

TEST = "tests/test_nothing_speaks_before_it_asks_the_language.py"
WF = "openfactory/runtime/temporal/workflow.py"
ACT = "openfactory/runtime/temporal/activities.py"
PROMO = "openfactory/orchestrator/promotion.py"
MACHINE = "openfactory/orchestrator/machine.py"
NEEDS = "openfactory/product/needs_action.py"
MODULE = "openfactory/product/module.py"
WATCH = "openfactory/techlead/watch.py"

PARK = "tests/test_park_alert.py"
TAIL = "tests/test_the_promotion_tail_speaks.py"
VERDICT = "tests/test_the_announcement_carries_the_verdict.py"
SPLIT = "tests/test_sweep_records_only_what_posted.py"
ROLE = "tests/test_product_needs_action.py"
CARDS = "tests/test_card_maintenance.py"
REACH = "tests/test_the_language_reaches_every_unprompted_surface.py"
ONE_SECTION = "tests/test_the_card_carries_ONE_acceptance_section.py"

MUTATIONS = [
    # ── the detector itself, both ways ───────────────────────────────────────────────────────────
    ("a welded sentence at an outward surface goes unseen", ACT,
     'tl_voice.say(tl_voice.NARRATION, "preflight.unsized", _lang, why=reason))',
     'f"pre-flight sizing did not run ({reason}) — this ticket proceeds unsized")'),

    ("…and the channel half of the same gate", "openfactory/box_prove.py",
     '            message=tl_voice.say(tl_voice.NARRATION, "gate.pickup-held",\n'
     '                                 str(getattr(row, "language", "") or ""),\n'
     '                                 project=project, reason=reason),',
     '            message=f"tickets are not being picked up here — {reason}",'),

    ("the walk stops walking (a wrong root reports a clean package)", TEST,
     'for path in sorted((ROOT / "openfactory").rglob("*.py")):',
     'for path in sorted((ROOT / "openfactory" / "nowhere").rglob("*.py")):'),

    ("the registry keeps an entry nothing welds any more (a standing permission)", TEST,
     "NOT_A_PERSONS_LANGUAGE = {",
     'NOT_A_PERSONS_LANGUAGE = {\n    "openfactory/cli.py": "nothing is welded here at all",'),

    # ── the workflow's own eleven ────────────────────────────────────────────────────────────────
    ("the park alert welds its Portuguese back", WF,
     '                        tl_voice.say(tl_voice.NARRATION, "park.needs-you", params.language,\n'
     '                                     issue=params.issue, who=who, note=note, ways=ways),',
     '                        f"⏸ #{params.issue} parou e precisa de vocês{who}\\n"\n'
     '                        f"{note}\\n{ways}",',
     PARK),

    ("…and the two verbs it teaches", WF,
     '                    commands = tl_voice.say(\n'
     '                        tl_voice.NARRATION,\n'
     '                        "park.both-verbs" if retryable else "park.skip-only",\n'
     '                        params.language, issue=params.issue)',
     '                    commands = f"Responda *skip #{params.issue}*."',
     PARK),

    ("the promotion tail speaks English at a Portuguese client again", WF,
     '                        tl_voice.say(tl_voice.NARRATION, "stage.unverified", '
     'params.language,\n'
     '                                     issue=params.issue,\n'
     '                                     why=staging.note or staging.state),',
     '                        f"⚠️ #{params.issue}: staging did not verify "\n'
     '                        f"({staging.note or staging.state})",',
     TAIL),

    ("the release outcome loses its failing half", WF,
     '                             "prod.released" if ok else "prod.failed", params.language,',
     '                             "prod.released", params.language,', TAIL),

    ("the merge announcement stops asking", WF,
     'await self._coord_say(tl_voice.say(tl_voice.NARRATION, "merged", params.language,\n'
     '                                          issue=params.issue), "merge")  # the tech-lead',
     'await self._coord_say(f"✅ #{params.issue} merged to main", "merge")  # the tech-lead'),

    # ── the split announcement ───────────────────────────────────────────────────────────────────
    ("the split announcement welds its Portuguese back", ACT,
     '        head = tl_voice.say(tl_voice.NARRATION, "split.head", lang, parent=parent_ref,\n'
     '                            title=parent.title[:80], n=n, why=inp.reasons[:160])',
     '        head = (f"✂️ Dividi o {parent_ref} — {parent.title[:80]} em {n}: era grande demais "\n'
     '                f"({inp.reasons[:160]}).")', SPLIT),

    ("…and the destination it names", ACT,
     '                where=tl_voice.say(tl_voice.NARRATION,\n'
     '                                   "split.to-todo" if to_todo else '
     '"split.to-backlog", lang))',
     '                where="TO-DO (rodam um por vez, em ordem)")', SPLIT),

    # ── the runners ──────────────────────────────────────────────────────────────────────────────
    ("the promotion runner asks nobody what language to speak", PROMO,
     "        return tl_voice.say(tl_voice.NARRATION, key, self.language, **params)",
     '        return tl_voice.say(tl_voice.NARRATION, key, "en", **params)',
     REACH),

    ("…and the factory stops handing it one", "openfactory/factory.py",
     '        language=str(getattr(project, "language", "") or ""),\n'
     '        # THE PROJECT\'S CHANNEL, not the project-less fallback.',
     "        # THE PROJECT'S CHANNEL, not the project-less fallback.",
     REACH),

    ("the in-job machine speaks the deployment default", MACHINE,
     '        return tl_voice.say(tl_voice.NARRATION, key,\n'
     '                            str(getattr(self.project, "language", "") or ""), **params)',
     '        return tl_voice.say(tl_voice.NARRATION, key, "en", **params)',
     REACH),

    ("the PR announcement drops this platform's own verdict", MACHINE,
     '                ready = self._say("job.pr-ready", pr=pr, review=said)',
     '                ready = self._say("job.pr-ready", pr=pr, review="")', VERDICT),

    # ── the product role ─────────────────────────────────────────────────────────────────────────
    ("the role's hand-back is welded Portuguese again", NEEDS,
     "        return voice._pick(voice._HANDBACK_UNCLEAR, language).format(sig=sig, why=why)",
     '        return f"{sig} olhei este impedimento e não consegui dizer{why}."', ROLE),

    ("the role's language never arrives from the project", MODULE,
     '        return review(verdicts, may_act=False, agent_name=self._name(),\n'
     '                      language=getattr(self.project, "language", None)), ""',
     '        return review(verdicts, may_act=False, agent_name=self._name()), ""',
     REACH),

    # ── the card's own headings ──────────────────────────────────────────────────────────────────
    ("a second name for the acceptance section is minted again", MODULE,
     '    parts = [(body or "").rstrip(), "", "## Acceptance criteria", ""]',
     '    parts = [(body or "").rstrip(), "", "## Critérios de aceite", ""]', ONE_SECTION),

    ("…and the old name stops being readable", MODULE,
     '    "open questions": ("Em aberto",),', "", ONE_SECTION),

    # ── the round's own escalation ───────────────────────────────────────────────────────────────
    ("the tech-lead's round drops the language on the remedy again", WATCH,
     "        remedy = remedy_for(verdict, language=language)",
     "        remedy = remedy_for(verdict)",
     REACH),
]
