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

After the extraction (#266 slice 2): the panel's turn IS the one turn engine, so the rows that cut
the panel's own copy of the stage (`activities._product_conversation`) are RE-PINNED onto what the
panel's turn reaches now — the engine's pipeline, and the worker's hand-off into it
(`activities._product_turn`) — each with its claim unchanged. Two claims are gone on purpose and
their rows RETIRED in place: the draft carried back for a propose button (the draft is STAGED now,
and the row that replaces it cuts the staged proposal's token on the way back), and the gap guard
that had to flip when a producer arrived (the gap closed, and its row now cuts a producer OFF the
panel's path).

After the door (#266 slice 3): every message reaches the engine through `product/door.py`, the
worker's hand-off into the engine is `activities._conversation_turn`, and the chat handler hands
its message to the door instead of taking the turn. The rows on those lines are RE-PINNED there,
each marked, with their claims unchanged.
"""

TEST = "tests/test_the_product_conversation_is_core.py"

ACTIVITIES = "openfactory/runtime/temporal/activities.py"
CHANNEL = "openfactory/product/channel.py"
ENGINE = "openfactory/product/engine.py"
CONFIRM = "openfactory/product/confirm.py"
CATALOG = "openfactory/actions/catalog.py"
BOT = "openfactory/runtime/slack/bot.py"
APP = "openfactory/api/app.py"

#: the settling stage as the ONE turn engine calls it — the panel's turn reaches it through the
#: engine since #266 slice 2
_ENGINE_SETTLE = (
    "    settled = settle(ex.project, text=ex.text, user=ex.user, thread=ex.thread, "
    "module=ex.module,\n"
    "                     channel=ex.channel, fingerprint=ex.fingerprint, on_it=ex.on_it, "
    "via=ex.via)\n")

MUTATIONS = [
    # RE-PINNED 2026-09-24: moved to engine.py — the panel's turn is the engine's turn
    ("the panel turn skips the settling stage — acceptance, yes/no and expiry are Slack-only again",
     ENGINE,
     _ENGINE_SETTLE,
     "    settled = Settled(None, None)\n"),
    # RE-PINNED 2026-09-24: moved to engine.py — the settled sentence is the turn's reply
    ("a settled turn comes back to the panel with its sentence blanked",
     ENGINE,
     "    if settled.reply is not None:\n"
     "        return settled.reply\n",
     "    if settled.reply is not None:\n"
     "        return \"\"\n"),
    # RE-PINNED 2026-09-24: moved to engine.py — the close is the turn's own, once per message
    ("the panel stops closing the decisions a reply answers",
     ENGINE,
     "            self.module.close_decisions_answered(channel=self.channel)\n",
     "            pass\n"),
    # RETIRED 2026-09-24: the panel's turn no longer carries a draft back for a propose button —
    # the one turn engine STAGES it and a yes performs it (#266 slice 2); the row below cuts the
    # staged proposal's token on its way back instead, which is what the panel's buttons read.
    ("the one row loses the staged proposal's token on the way back — the panel's buttons go "
     "dark",
     CATALOG,
     "                token=options.token if options else \"\",\n",
     "                token=\"\",\n"),
    # RE-PINNED 2026-09-24: the chat handler is the thin adapter in front of the engine now, so
    # the copy it could grow is a settle of its own before the turn
    # RE-PINNED 2026-09-24 (#266 slice 3): the adapter hands the message to the door instead of
    # taking the turn, and drops the module it no longer uses — the copy would grow before that
    ("the chat handler grows its own copy of the stage instead of sharing it",
     CHANNEL,
     "    del module  # the worker builds the module the turn answers with\n",
     "    if module is not None and module.settle_acceptance(text):\n"
     "        return \"ok\"\n"
     "    del module  # the worker builds the module the turn answers with\n"),
    # RE-PINNED 2026-09-24: moved to engine.py
    ("the acceptance verdict is cut out of the stage",
     ENGINE,
     "        answered = module.settle_acceptance(text)\n",
     "        answered = None\n"),
    # RE-PINNED 2026-09-24: moved to engine.py
    ("a late yes on an expired proposal falls through to the model again",
     ENGINE,
     "        return Settled(proposal_expired(language=lang), waiting)\n",
     "        return Settled(None, waiting)\n"),
    # RE-PINNED 2026-09-24: moved to engine.py
    ("a typed yes no longer performs the staged proposal",
     ENGINE,
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
    # RE-PINNED 2026-09-24: moved to engine.py
    ("the release gate is cut on the shared stage — anyone typing 'funcionou' in the panel "
     "releases production",
     ENGINE,
     "    if not may_act(project, user, via=via):\n"
     "        return unauthorized_message(project)\n\n"
     "    from openfactory.product.release import release\n",
     "    from openfactory.product.release import release\n"),
    # RE-PINNED 2026-09-24: moved to engine.py
    ("the release is performed for nobody — the gate refuses everyone, the positive twin sees it",
     ENGINE,
     "    if not may_act(project, user, via=via):\n"
     "        return unauthorized_message(project)\n\n"
     "    from openfactory.product.release import release\n",
     "    return unauthorized_message(project)\n\n"
     "    from openfactory.product.release import release\n"),
    # RE-PINNED 2026-09-24: the worker's turn hands the transport to the engine on the message
    # RE-PINNED 2026-09-24 (#266 slice 3): `_product_turn` became `_conversation_turn`, the
    # conversation's turn
    ("the worker tells the release gate 'slack' for a yes that came through the panel",
     ACTIVITIES,
     "                                     fingerprint=inp.fingerprint, via=via),\n",
     "                                     fingerprint=inp.fingerprint, via=\"slack\"),\n"),
    # RE-PINNED 2026-09-24: `_product_conversation` became `_product_turn`
    # RE-PINNED 2026-09-24 (#266 slice 3): `_product_turn` became `_conversation_turn`; the ceiling
    # it takes next is what tells it from the read-only path's identical two lines
    ("the worker reads a row that did not say its transport as the channel's",
     ACTIVITIES,
     "    via = inp.via or \"api\"\n"
     "    name = getattr(project, \"name\", \"\") or \"\"\n"
     "    with ceiling().hold(",
     "    via = inp.via or \"slack\"\n"
     "    name = getattr(project, \"name\", \"\") or \"\"\n"
     "    with ceiling().hold("),
    # RE-PINNED 2026-09-24: moved to engine.py
    ("the shared stage keeps the transport to itself — confirm's gate says 'slack' again",
     ENGINE,
     "                                      lang=lang, on_it=on_it, via=via),\n",
     "                                      lang=lang, on_it=on_it),\n"),
    # RE-PINNED 2026-09-24: moved to engine.py
    ("the rejection's gate keeps the transport to itself — a requester's no is stamped 'slack'",
     ENGINE,
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
    # both CATALOG rows re-pinned 2026-09-07: the thread key is computed once above the call
    # (`key_for(named=thread, own=…)`), so the argument reads `thread=key`
    # RE-PINNED 2026-09-24: the one row mints the message's id beside the transport
    # RE-PINNED 2026-09-24 (#266 slice 3): the row hands the door a `Message`, and the transport
    # rides on it
    ("the panel's row stops carrying its actor's transport into the workflow input",
     CATALOG,
     "                text=said, via=getattr(by, \"via\", \"\") or \"api\"),\n",
     "                text=said),\n"),
    ("the worker's answer row builds the module right and tells the gate nothing",
     ACTIVITIES,
     "                             module=ProductModule(project, via=via), via=via)\n",
     "                             module=ProductModule(project, via=via))\n"),
    # RETIRED 2026-09-24: the gap this guard measured is closed (#266 slice 2) — every staging
    # producer is on the panel's path — so the guard now fails when one LEAVES it, cut here
    ("a staging producer leaves the panel's path — a request typed there is never staged",
     ENGINE,
     "    offered = gestures(ex, answer) or staging(ex, answer)\n",
     "    offered = gestures(ex, answer)\n"),
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
    # RE-PINNED 2026-09-24: the one row mints the message's id beside the transport
    # RE-PINNED 2026-09-24 (#266 slice 3): the row hands the door a `Message`, and the transport
    # rides on it
    ("the say row keeps the keyword and swaps its actor's transport for the channel's",
     CATALOG,
     "                text=said, via=getattr(by, \"via\", \"\") or \"api\"),\n",
     "                text=said, via=\"slack\"),\n"),
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
    # RE-PINNED 2026-09-24: `_product_conversation` became `_product_turn`
    # RE-PINNED 2026-09-24 (#266 slice 3): `_product_turn` became `_conversation_turn`, which builds
    # it inside the ceiling (four spaces deeper than the read-only path's)
    ("the worker's turn builds the module as the channel's and tells settle right",
     ACTIVITIES,
     "                    module=ProductModule(project, via=via))\n",
     "                    module=ProductModule(project, via=\"slack\"))\n"),
    # ── after the third review: the hops a `panel`-driven run could not see ──────────────────
    # RE-PINNED 2026-09-24: moved to engine.py
    ("the stage tells confirm's gate 'panel' for a yes typed anywhere — the reviewer's cut C",
     ENGINE,
     "                                      lang=lang, on_it=on_it, via=via),\n",
     "                                      lang=lang, on_it=on_it, via=\"panel\"),\n"),
    # RE-PINNED 2026-09-24: moved to engine.py
    ("the stage tells the rejection's gate 'panel' for a no typed anywhere — the reviewer's "
     "cut D",
     ENGINE,
     "        if not may_act(project, user, via=via) and not _is_requester(waiting, user):\n",
     "        if not may_act(project, user, via=\"panel\") and not _is_requester(waiting, "
     "user):\n"),
    # RE-PINNED 2026-09-24: the chat handler hands its transport on the engine's message now,
    # so the default the claim is about is the adapter's own `via`, not the stage's
    # RE-PINNED 2026-09-24 (#266 slice 3): the adapter's `Message` goes to the door (`say`), one
    # space shallower. It SURVIVED the first run here, because the chat runs above take the turn in
    # process (`tests/the_chat_turn.py`) with a transport of their own; the message that crosses
    # the door is read now (`test_the_chat_handler_hands_the_door_the_CHANNEL_s_own_transport`)
    ("the stage's default becomes the panel's — the chat handler, which hands none, is stamped "
     "'panel' — the reviewer's cut E",
     CHANNEL,
     "                                   via=\"slack\"),\n",
     "                                   via=\"panel\"),\n"),
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
