"""A private key is read one way, whatever its case (#347).

ROW 1 IS THE DEFECT: `person_of` reads its prefix lower-cased again, so `Person:bruno` is Bruno's
to it and nobody's to `owner_of`.

ROW 2 IS THE OTHER WAY TO MAKE THEM AGREE, the one declined: `owner_of` folds the prefix's case,
and every reader hands Bruno a spelling v0.2.0 to v0.3.0 let anybody write in as a room.

ROWS 3-9 ARE EACH READER FOLDING THE CASE ON ITS OWN: `key_for`, the socket, the agenda, a
decision asked there, recall, the distillate and the read model's "your". One reader reading wider
than `owner_of` is the drift the issue asked to stop.

ROW 10 IS THE REDACTION FINDING THE PREFIX IN LOWER CASE ONLY AGAIN: Ana's pack prints
`Person:bruno`, his key and his id. ROW 11 IS THE KEY READ AS A ROOM.
"""

TEST = "tests/test_a_private_key_is_read_one_way_whatever_its_case.py"
CONVERSATION = "openfactory/product/conversation.py"
MODEL = "openfactory/product/model.py"

MUTATIONS = [
    ("`person_of` reads its prefix lower-cased again, so it disagrees with `owner_of`",
     CONVERSATION,
     '    return owner[len(PERSON):] if owner.startswith(PERSON) else ""',
     '    return owner[len(PERSON):] if owner.lower().startswith(PERSON) else ""'),

    ("`owner_of` folds the prefix's case, so a case-variant key is handed to the person it spells",
     CONVERSATION,
     '    key = str(key or "").strip()\n    if not is_private(key) or SESSION_SEP not in key:',
     '    key = str(key or "").strip()\n'
     '    key = PERSON + key[len(PERSON):] if key.lower().startswith(PERSON) else key\n'
     '    if not is_private(key) or SESSION_SEP not in key:'),

    ("`key_for` lets a caller into a case-variant of their own key",
     CONVERSATION,
     "    if is_private(named) and (not own or owner_of(named) != own):",
     "    if is_private(named) and (not own or owner_of(named).lower() != own.lower()):"),

    ("the socket hands a case-variant key's frames to the person it spells",
     "openfactory/api/product_chat.py",
     "        return bool(sub.own) and owner_of(conversation) == sub.own\n",
     "        return bool(sub.own) and owner_of(conversation).lower() == sub.own.lower()\n"),

    ("the agenda seals a case-variant key as the person it spells",
     "openfactory/product/agenda.py",
     "            return Audience(room=False, conversation=_sealed(owner_of(where)), "
     "person=requester)",
     "            return Audience(room=False, conversation=_sealed(owner_of(where).lower()), "
     "person=requester)"),

    ("a decision asked in a case-variant key is the spelled person's to answer",
     "openfactory/product/module.py",
     '    return {"asked_of": who, "asked_in": sealed(owner_of(conversation))}',
     '    return {"asked_of": who, "asked_in": sealed(owner_of(conversation).lower())}'),

    ("recall hands a case-variant key's turns to the person it spells",
     "openfactory/memory/recall.py",
     "            and (not is_private(h.said.where) or owner_of(h.said.where) == owner_of(own))]",
     "            and (not is_private(h.said.where) "
     "or owner_of(h.said.where).lower() == owner_of(own).lower())]"),

    ("the distillate reads a case-variant key as the spelled person's",
     "openfactory/product/distil.py",
     "    who = person_of(conversation)\n",
     "    who = person_of(conversation.lower())\n"),

    ("the read model tells the spelled person a case-variant key is their own conversation",
     MODEL,
     "        mine = self.speaker and person_of(key) == self.speaker",
     "        mine = self.speaker and person_of(key.lower()) == self.speaker"),

    ("the redaction finds a private key's prefix in lower case only, and prints the key",
     MODEL,
     '_PRIVATE_KEY = re.compile(r"\\b(?i:" + "|".join(re.escape(p) for p in PRIVATE_PREFIXES)',
     '_PRIVATE_KEY = re.compile(r"\\b(?:" + "|".join(re.escape(p) for p in PRIVATE_PREFIXES)'),

    ("a case-variant key is a room again",
     CONVERSATION,
     '    return str(key or "").strip().lower().startswith(PRIVATE_PREFIXES)',
     '    return str(key or "").strip().startswith(PRIVATE_PREFIXES)'),
]
