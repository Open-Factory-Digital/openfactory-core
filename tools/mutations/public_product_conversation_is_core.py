"""The product conversation is core, and the panel reaches its settling stage (2026-08-25).

Each cut breaks one thing the guards in `tests/test_the_product_conversation_is_core.py` claim:
the panel's turn settling, the settled sentence surviving, decisions closing, the draft surviving,
the chat handler sharing the stage, a channel growing the work back, core reaching into a channel,
each rescued branch inside the stage itself — and, after the review of the same day: the release
gate cut on the shared stage, the transport dropped at each of its three hops, and a staging
producer arriving on the panel's path (the gap guard must FLIP, which is its whole design).

After the second review (2026-08-26): the transport's VALUE swapped at every hop with the keyword
kept — the two cuts the reviewer made that the whole suite survived (the panel's own route, the
worker's answer row), the two catalog rows, and the module built beside each gate.

After the third review (2026-08-26): the six cuts that survived the whole suite because the hops
they sat on were driven only with the value the cut picks — `panel` at the stage's two inner
gates and on the module the token gate builds, the stage's own default, the token route's reject
gate (never driven with a refusal), and the answer row's empty fold (its twin was guarded, it was
not).
"""

TEST = "tests/test_the_product_conversation_is_core.py"

ACTIVITIES = "openfactory/runtime/temporal/activities.py"
CHANNEL = "openfactory/product/channel.py"
CONFIRM = "openfactory/product/confirm.py"
CATALOG = "openfactory/actions/catalog.py"
BOT = "openfactory/runtime/slack/bot.py"
APP = "openfactory/api/app.py"

_PANEL_SETTLE = (
    "    settled = settle(project, text=inp.message, user=inp.asked_by, thread=thread, "
    "module=module,\n"
    "                     via=via)\n")

MUTATIONS = [
    ("the panel turn skips the settling stage — acceptance, yes/no and expiry are Slack-only again",
     ACTIVITIES,
     _PANEL_SETTLE,
     "    settled = type(\"_S\", (), {\"reply\": None, \"waiting\": None})()\n"),
    ("a settled turn comes back to the panel with its sentence blanked",
     ACTIVITIES,
     "        return ProductAnswer(ok=True, text=settled.reply)\n",
     "        return ProductAnswer(ok=True, text=\"\")\n"),
    ("the panel stops closing the decisions a reply answers",
     ACTIVITIES,
     "        module.close_decisions_answered()\n",
     "        pass\n"),
    ("the panel turn drops the draft on the way back — the propose button goes dark",
     ACTIVITIES,
     "                    \"and nothing is tracking it\", name, exc_info=True)\n"
     "    return answer\n",
     "                    \"and nothing is tracking it\", name, exc_info=True)\n"
     "    return ProductAnswer(ok=answer.ok, text=answer.text)\n"),
    ("the chat handler grows its own copy of the stage instead of sharing it",
     CHANNEL,
     "    settled = settle(project, text=text, user=user, thread=thread, module=module, "
     "channel=channel,\n"
     "                     fingerprint=fingerprint, on_it=_on_it)\n",
     "    _k, _w = find_waiting(thread, channel, project=project)\n"
     "    settled = Settled(None, _w)\n"
     "    if not _w and module.settle_acceptance(text):\n"
     "        return \"ok\"\n"),
    ("the acceptance verdict is cut out of the stage",
     CHANNEL,
     "        answered = module.settle_acceptance(text)\n",
     "        answered = None\n"),
    ("a late yes on an expired proposal falls through to the model again",
     CHANNEL,
     "        return Settled(proposal_expired(language=lang), waiting)\n",
     "        return Settled(None, waiting)\n"),
    ("a typed yes no longer performs the staged proposal",
     CHANNEL,
     "        return Settled(confirm_staged(project, key=waiting_key, entry=waiting,\n"
     "                                      fingerprint=fingerprint, module=module, user=user,\n"
     "                                      lang=lang, on_it=on_it, via=via),\n"
     "                       waiting)\n",
     "        return Settled(None, waiting)\n"),
    ("a channel package grows the product role's work back",
     BOT,
     "",
     "\n\ndef _mutant(project, text):\n"
     "    from openfactory.product.module import ProductModule\n\n"
     "    return ProductModule(project).settle_acceptance(text)\n"),
    ("the core reaches into the Slack package",
     CHANNEL,
     "",
     "\n\ndef _mutant():\n"
     "    from openfactory.runtime.slack import mrkdwn\n\n"
     "    return mrkdwn\n"),
    # ── after the review ──────────────────────────────────────────────────────────────────────
    ("the release gate is cut on the shared stage — anyone typing 'funcionou' in the panel "
     "releases production",
     CHANNEL,
     "    if not may_act(project, user, via=via):\n"
     "        return unauthorized_message(project)\n\n"
     "    from openfactory.product.release import release\n",
     "    from openfactory.product.release import release\n"),
    ("the release is performed for nobody — the gate refuses everyone, the positive twin sees it",
     CHANNEL,
     "    if not may_act(project, user, via=via):\n"
     "        return unauthorized_message(project)\n\n"
     "    from openfactory.product.release import release\n",
     "    return unauthorized_message(project)\n\n"
     "    from openfactory.product.release import release\n"),
    ("the worker tells the release gate 'slack' for a yes that came through the panel",
     ACTIVITIES,
     _PANEL_SETTLE,
     "    settled = settle(project, text=inp.message, user=inp.asked_by, thread=thread, "
     "module=module,\n"
     "                     via=\"slack\")\n"),
    ("the worker reads a row that did not say its transport as the channel's",
     ACTIVITIES,
     "    via = inp.via or \"api\"\n"
     "    module = ProductModule(project, via=via)\n",
     "    via = inp.via or \"slack\"\n"
     "    module = ProductModule(project, via=via)\n"),
    ("the shared stage keeps the transport to itself — confirm's gate says 'slack' again",
     CHANNEL,
     "                                      lang=lang, on_it=on_it, via=via),\n",
     "                                      lang=lang, on_it=on_it),\n"),
    ("the rejection's gate keeps the transport to itself — a requester's no is stamped 'slack'",
     CHANNEL,
     "        if not may_act(project, user, via=via) and not _is_requester(waiting, user):\n",
     "        if not may_act(project, user) and not _is_requester(waiting, user):\n"),
    ("the token route's own gate forgets the transport it was told",
     CONFIRM,
     "    if not may_act(project, user, via=via):\n"
     "        # AUTHZ BEFORE POP, like every other confirmation path: an unauthorised click "
     "must not\n",
     "    if not may_act(project, user):\n"
     "        # AUTHZ BEFORE POP, like every other confirmation path: an unauthorised click "
     "must not\n"),
    ("the token route hands confirm a yes with no transport",
     CONFIRM,
     "                           user=user, lang=lang, via=via,\n",
     "                           user=user, lang=lang,\n"),
    ("the panel's row stops carrying its actor's transport into the workflow input",
     CATALOG,
     "                            thread=(thread or \"\").strip(), asked_by=by.id,\n"
     "                            via=getattr(by, \"via\", \"\") or \"\"),\n",
     "                            thread=(thread or \"\").strip(), asked_by=by.id),\n"),
    ("the worker's answer row builds the module right and tells the gate nothing",
     ACTIVITIES,
     "                             module=ProductModule(project, via=via), via=via)\n",
     "                             module=ProductModule(project, via=via))\n"),
    ("a staging producer arrives on the panel's path — the gap guard must flip, by design",
     ACTIVITIES,
     "",
     "\n\n@activity.defn\n"
     "async def _mutant_producer(inp):\n"
     "    from openfactory.product.staging import remember\n\n"
     "    return remember(inp.thread, {})\n"),
    # ── after the second review: the VALUE at every hop, keyword kept ─────────────────────────
    ("the panel's own route tells the gate 'slack' for a click on the panel — the reviewer's cut "
     "the whole suite survived",
     APP,
     "            proj, token=token, approved=(answer == \"approve\"), user=by, via=\"panel\")\n",
     "            proj, token=token, approved=(answer == \"approve\"), user=by, via=\"slack\")\n"),
    ("the token gate builds the module it was handed none of with its default, not with the "
     "transport it was told",
     CONFIRM,
     "    module = module or ProductModule(project, via=via)\n",
     "    module = module or ProductModule(project)\n"),
    ("the say row keeps the keyword and swaps its actor's transport for the channel's",
     CATALOG,
     "                            thread=(thread or \"\").strip(), asked_by=by.id,\n"
     "                            via=getattr(by, \"via\", \"\") or \"\"),\n",
     "                            thread=(thread or \"\").strip(), asked_by=by.id,\n"
     "                            via=\"slack\"),\n"),
    ("the answer row keeps the keyword and swaps its actor's transport for the channel's",
     CATALOG,
     "                               actor=by.id, via=getattr(by, \"via\", \"\") or \"\"),\n",
     "                               actor=by.id, via=\"slack\"),\n"),
    ("the worker's answer row keeps the keyword and tells the gate 'slack' — the reviewer's "
     "other cut",
     ACTIVITIES,
     "                             module=ProductModule(project, via=via), via=via)\n",
     "                             module=ProductModule(project, via=via), via=\"slack\")\n"),
    ("the worker's answer row builds the module as the channel's and tells the gate right",
     ACTIVITIES,
     "                             module=ProductModule(project, via=via), via=via)\n",
     "                             module=ProductModule(project, via=\"slack\"), via=via)\n"),
    ("the worker's turn builds the module as the channel's and tells settle right",
     ACTIVITIES,
     "    via = inp.via or \"api\"\n"
     "    module = ProductModule(project, via=via)\n",
     "    via = inp.via or \"api\"\n"
     "    module = ProductModule(project, via=\"slack\")\n"),
    # ── after the third review: the hops a `panel`-driven run could not see ──────────────────
    ("the stage tells confirm's gate 'panel' for a yes typed anywhere — the reviewer's cut C",
     CHANNEL,
     "                                      lang=lang, on_it=on_it, via=via),\n",
     "                                      lang=lang, on_it=on_it, via=\"panel\"),\n"),
    ("the stage tells the rejection's gate 'panel' for a no typed anywhere — the reviewer's "
     "cut D",
     CHANNEL,
     "        if not may_act(project, user, via=via) and not _is_requester(waiting, user):\n",
     "        if not may_act(project, user, via=\"panel\") and not _is_requester(waiting, "
     "user):\n"),
    ("the stage's default becomes the panel's — the chat handler, which hands none, is stamped "
     "'panel' — the reviewer's cut E",
     CHANNEL,
     "           fingerprint: str = \"\", on_it=None, via: str = \"slack\") -> Settled:\n",
     "           fingerprint: str = \"\", on_it=None, via: str = \"panel\") -> Settled:\n"),
    ("the token gate builds the module it was handed none of as the panel's, whatever it was "
     "told — the Slack click's writes recorded as the panel's",
     CONFIRM,
     "    module = module or ProductModule(project, via=via)\n",
     "    module = module or ProductModule(project, via=\"panel\")\n"),
    ("the token route's reject gate forgets the transport it was told",
     CONFIRM,
     "        if not may_act(project, user, via=via) and not _is_requester(entry, user):\n",
     "        if not may_act(project, user) and not _is_requester(entry, user):\n"),
    ("the worker's answer row reads a caller that did not say its transport as the channel's",
     ACTIVITIES,
     "        via = inp.via or \"api\"\n"
     "        return answer_staged(project, token=inp.token, approved=inp.approved, "
     "user=inp.actor,\n",
     "        via = inp.via or \"slack\"\n"
     "        return answer_staged(project, token=inp.token, approved=inp.approved, "
     "user=inp.actor,\n"),
]
