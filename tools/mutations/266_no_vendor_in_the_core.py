"""Mutation plan for #266 slice 6 — a core without a vendor, and addressing in a group (ADR-0051
D16 and D14, decisions 3 and 6).

Each row takes away one rule this slice stands on; every row must turn its test file red. In the
brief's order:

  - THE GUARD: a vendor's name planted in the core's code and in its page, and the guard's own
    machinery cut — its word match, its reading of strings, its reading of the page's script, and
    an allow-list that would let a whole file through;
  - THE ALIAS WARNING: the old keys never named, named below WARNING, named on every read, not
    named under `product:`; and what an alias may do — fold, never merge, never override, and
    never choose the channel again;
  - PERSON-BASED AUTHORISATION: a guest who may write, a vendor's id handed to the door or to a
    click's gate, an unmapped user taken as a person, the port never asked, and the vendor's
    mention syntax written back into what a turn stages;
  - EACH OF THE THREE ADDRESSING RULES — direct, mention, reply — in the core's definition, and
    what feeds each on the conversation (a private key read as direct, the panel's own mention,
    the row's default, the conversation learning the role joined, the door reading the memory);
  - KEPT, NEVER TURNED: a kept message turned anyway, kept unmarked, acknowledged into a chat
    room, or told nothing;
  - NEVER IN THE PROMPT: the transcript's default read, the recall's, the recall index's mark, and
    the engine's two reads for a prompt each asking for what was not addressed to the role.

The rows run against `tests/test_no_vendor_in_the_core.py`; the guard's rows against
`tests/test_the_core_names_no_vendor.py`.
"""

TEST = "tests/test_no_vendor_in_the_core.py"
GUARD = "tests/test_the_core_names_no_vendor.py"

ALIASES = "openfactory/contracts/aliases.py"
PRODUCT_CONFIG = "openfactory/contracts/product.py"
REGISTRY = "openfactory/registry.py"
CHANNELS = "openfactory/adapters/channel/registry.py"
MODULE = "openfactory/product/module.py"
CHANNEL = "openfactory/product/channel.py"
SPEAKER = "openfactory/product/speaker.py"
ENGINE = "openfactory/product/engine.py"
ADDRESSING = "openfactory/product/addressing.py"
DOOR = "openfactory/product/door.py"
CONVERSATION = "openfactory/runtime/temporal/conversation.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
TRANSCRIPT = "openfactory/memory/transcript.py"
RECALL = "openfactory/memory/recall.py"
PRODUCT_CHAT = "openfactory/api/product_chat.py"
CATALOG = "openfactory/actions/catalog.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── the guard: red with a planted vendor name, and its own machinery cut ─────────────────────
    ("a vendor's name is planted in the core's code — the door's own name for an event", DOOR,
     'EVENT = "event"', 'EVENT = "slack"', GUARD),
    ("a vendor's name is planted in what the panel's page shows", PANEL,
     '"say it to the room — @po asks the product role"',
     '"say it to the room — @po asks the product role, as on Slack"', GUARD),
    ("the guard matches no word at all", GUARD,
     "    for word in words:\n        if word in VENDORS:\n            return word\n",
     "    for word in []:\n        if word in VENDORS:\n            return word\n", GUARD),
    ("the guard stops reading the strings the code carries", GUARD,
     '            check(node, "string", node.value)', "            pass", GUARD),
    ("the guard reads none of the page's script", GUARD,
     "        kept = _without_script_comments(body)", '        kept = ""', GUARD),
    ("the allow-list lets a whole file through instead of one string", GUARD,
     "            if (rel, text) in ALLOWED:",
     "            if rel in {r for r, _t in ALLOWED}:", GUARD),

    # ── the alias warning (decision 6) ───────────────────────────────────────────────────────────
    ("a registry read never names the old keys", REGISTRY,
     "        self._report_old_keys(name, raw)\n", ""),
    ("a project asked for by name never names its old keys", REGISTRY,
     "            self._report_old_keys(name, raw[name])\n", "            pass\n"),
    ("the old keys are named below WARNING, where nobody reads", REGISTRY,
     '                log.warning("OPENFACTORY_DEPRECATED_KEY registry: project %r uses %r, which '
     'is "',
     '                log.info("OPENFACTORY_DEPRECATED_KEY registry: project %r uses %r, which '
     'is "'),
    ("each old key is named on every read, not once", REGISTRY,
     "                if not _first_time(str(self.path), name, old):",
     "                if False:"),
    ("the old keys under `product:` are never named", REGISTRY,
     "        if isinstance(product, dict):", "        if False:"),
    ("the product's old keys are not read at all — an existing configuration loses them",
     PRODUCT_CONFIG,
     "        return aliases.fold(data, aliases.PRODUCT_KEYS)[0]", "        return data"),
    ("an alias MERGES into the new spelling — an old admin list widens a new one", ALIASES,
     "            if not taken and value is not None:\n                out[head] = value",
     "            if isinstance(value, list) and isinstance(out.get(head), list):\n"
     "                out[head] = [*out[head], *value]\n"
     "            elif not taken and value is not None:\n                out[head] = value"),
    ("an alias OVERRIDES the new spelling — an old admin list replaces a new one", ALIASES,
     "            if not taken and value is not None:\n                out[head] = value",
     "            if value is not None:\n                out[head] = value"),
    ("an old coordinate chooses the channel again — the inference is back", CHANNELS,
     "    return explicit or DEFAULT_KIND",
     '    return explicit or ("chat" if (getattr(project, "channel_options", None) or {})'
     '.get("channel") else DEFAULT_KIND)'),

    # ── product writes are authorised by person ──────────────────────────────────────────────────
    ("a guest may write when a list happens to spell it", MODULE,
     "    if not user_id or is_guest(user_id):", "    if not user_id:"),
    ("the chat adapter hands the door the vendor's own id", CHANNEL,
     '                                   speaker=speaker, text=str(text or ""),',
     '                                   speaker=str(user or ""), text=str(text or ""),'),
    ("a click is authorised as the vendor's own id", CHANNEL,
     "    _code, sentence = answer_staged(project, token=token, approved=approved, user=person,",
     "    _code, sentence = answer_staged(project, token=token, approved=approved, user=user,"),
    ("a user the add-on cannot name is taken as a person anyway", SPEAKER,
     "    return person or guest(who, via=via)", "    return person or who"),
    ("the add-on's port is never asked — its user is the person", SPEAKER,
     '            person = str(ask(who, project=project) or "").strip()',
     "            person = who"),
    ("what a turn stages wears the vendor's mention syntax again", ENGINE,
     '                              asked_by=user or "", source=ex.source or "")',
     '                              asked_by=f"<@{user}>" if user else "", '
     'source=ex.source or "")'),

    # ── the three addressing rules (D14, decision 3) ─────────────────────────────────────────────
    ("a DIRECT conversation is not addressed to the role", ADDRESSING,
     "    if direct:\n        return DIRECT", "    if False:\n        return DIRECT"),
    ("a MENTION is not addressed to the role", ADDRESSING,
     "    if mentioned:\n        return MENTION", "    if False:\n        return MENTION"),
    ("a REPLY inside a conversation the role takes part in is not addressed to it", ADDRESSING,
     '    if str(in_reply_to or "").strip() and takes_part:', "    if False:"),
    ("a person's own conversation is not read as a direct one", DOOR,
     "    return bool(message.direct) or is_private(message.conversation)",
     "    return bool(message.direct)"),
    ("the panel's room detects no mention", PRODUCT_CHAT,
     '    return any(re.search(rf"(?<![\\w@])@{re.escape(n)}(?![\\w])", said) for n in names if n)',
     "    return False"),
    ("the product page's Ask button asks the room, not the role", PANEL,
     "  return(!_pc.room||/(^|[^\\w@])@(po|product)(?!\\w)/i.test(q))?q:`@po ${q}`;",
     "  return q;"),
    ("calling the role's own row no longer names it — the CLI is answered by nobody", CATALOG,
     "    return _waits(mentioned)", '    return mentioned in (True, "true")'),
    ("the conversation never learns the role joined it — a reply after a mention is kept",
     CONVERSATION,
     "            self._overheard.append(arrival)\n            return\n"
     "        self._joined = True\n",
     "            self._overheard.append(arrival)\n            return\n"),
    ("the door never reads the product's memory for a reply", DOOR,
     "        took_part = await asyncio.to_thread(transcript.took_part, project,\n"
     "                                            conversation=message.conversation)",
     "        took_part = False"),

    # ── kept, never turned ───────────────────────────────────────────────────────────────────────
    ("a message nobody addressed to the role takes a turn anyway", CONVERSATION,
     "            self._kept = [*self._kept, arrival.id][-SEEN:]\n"
     "            self._overheard.append(arrival)\n            return\n",
     "            self._kept = [*self._kept, arrival.id][-SEEN:]\n"
     "            self._overheard.append(arrival)\n"),
    ("a kept message is recorded as addressed to the role", ACTIVITIES,
     "        addressed=False)", "        addressed=True)"),
    ("the transcript never marks a kept line", TRANSCRIPT,
     "        if not addressed:\n            extra[ADDRESSED_MARK] = False\n", ""),
    ("a kept message's acknowledgement is posted into the chat room", DOOR,
     "        if notify is not None and ack.text and ack.state != OVERHEARD:",
     "        if notify is not None and ack.text:"),
    ("the sender of a kept message is told nothing — or told the role is on it", DOOR,
     '    if stands.get("state") == OVERHEARD:', "    if False:"),

    # ── never in the prompt ──────────────────────────────────────────────────────────────────────
    ("the read a prompt is built from reads what the room said to others", TRANSCRIPT,
     "                   and (overheard or _addressed(r))),", "                   ),"),
    ("the recall a turn reads finds what the room said to others", RECALL,
     "            and (overheard or h.said.addressed)\n", ""),
    ("the recall index forgets which lines were not for the role", RECALL,
     "                        addressed=extra.get(transcript.ADDRESSED_MARK) is not False))",
     "                        addressed=True))"),
    ("the turn asks its history for what was not addressed to the role", ENGINE,
     "        [t for t in transcript.recent(project, thread=thread, channel=channel)",
     "        [t for t in transcript.recent(project, thread=thread, channel=channel,\n"
     "                                      overheard=True)"),
    ("the turn asks the recall for what was not addressed to the role", ENGINE,
     "                      partition=transcript.partition(project))",
     "                      partition=transcript.partition(project), overheard=True)"),
]
