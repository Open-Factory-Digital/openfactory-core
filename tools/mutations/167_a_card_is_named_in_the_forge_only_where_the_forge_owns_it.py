"""#167, proven by breaking it — a card is named in the forge's terms only where the forge owns it.

The job wrote the tracker's card id into the commit message and the pull request title
(`#12: title`) and wrote `Closes #12` into the body, whatever the pairing. On a local board over a
forge whose `#N` is an organisation-wide work item, ids 6, 7, 9, 10, 11, 12, 14, 15, 20, 50 and 100
all existed in other projects, so the early cards' pull requests linked somebody else's items.

THREE CLAIMS:

  1. **The rows decide, by equality.** Each shipped row declares where its numbers live; the forge
     owns the card exactly when the two declarations are equal, and an absent (or malformed)
     declaration matches nothing — not even another absent one.
  2. **Owned: the forge's own mention.** `#12: title`, and `#1234: title` for an id that carries
     no `#`, in the commit and the title, with the mention in the body.
  3. **Not owned: nothing the forge can read as its item** — the title alone, a `Card:` trailer
     on the commit, the card named in words with its URL in the body, and no closing keyword.
  4. **A closing line only where the forge owns the card AND its row declares a word.** GitHub
     declares `Closes` (nothing else closes its issue); Azure Repos declares none (its row refuses
     to be a second writer of the card's state), so an owned work item is named and not closed.

The guard is `tests/test_a_card_is_named_in_the_forge_only_where_the_forge_owns_it.py`.
"""

TEST = "tests/test_a_card_is_named_in_the_forge_only_where_the_forge_owns_it.py"

SPACE = "openfactory/contracts/item_space.py"
MACHINE = "openfactory/orchestrator/machine.py"
GH_TRACKER = "openfactory/adapters/tracker/github.py"
ADO_TRACKER = "openfactory/adapters/tracker/azure_devops.py"
ADO_FORGE = "openfactory/adapters/forge/azure_devops.py"
GH_FORGE = "openfactory/adapters/forge/github.py"

MUTATIONS = [
    # ── claim 1: the verdict ──────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF, AS A VERDICT: every forge owns every card", SPACE,
     "    return theirs is not None and theirs == declared_space(forge)\n",
     "    return True\n"),

    ("no forge ever owns a card, so the GitHub pairing loses its native link", SPACE,
     "    return theirs is not None and theirs == declared_space(forge)\n",
     "    return False\n"),

    ("two rows that declare nothing are read as sharing their numbers", SPACE,
     "    return theirs is not None and theirs == declared_space(forge)\n",
     "    return theirs == declared_space(forge)\n"),

    ("any answer counts as a declaration, so one mock handed to both axes 'owns' the card", SPACE,
     "    if (isinstance(space, tuple) and len(space) == 2\n",
     "    if True or (isinstance(space, tuple) and len(space) == 2\n"),

    ("the tracker declares its default repository instead of the card's (C-18)", GH_TRACKER,
     '        repo = (str(getattr(ticket, "repo", "") or "") or self.repo or "").strip().strip("/")\n',
     '        repo = (self.repo or "").strip().strip("/")\n'),

    # On the TRACKER row: the guard's upper-case spelling (`Acme`) is the tracker's, and a cut on
    # the forge's already-lower-case `acme` survived, measured — aimed wrong, not a weak guard.
    ("an organisation spelled with another case reads as another organisation", ADO_TRACKER,
     '        return ("azure_devops", org.lower()) if org else None\n',
     '        return ("azure_devops", org) if org else None\n'),

    # ── claim 2: owned ────────────────────────────────────────────────────────────────────────
    ("the owned mention is the raw id, so a work item's bare `1234` links nothing", MACHINE,
     '        mention = f"#{bare}"\n',
     '        mention = str(ticket.id)\n'),

    # ── claim 3: not owned, and no closing keyword ────────────────────────────────────────────
    # Re-pinned by #167's second half: the neutral title is now written `without_mentions`.
    ("THE DEFECT ITSELF, ON THE TITLE: the neutral title carries the tracker's id", MACHINE,
     '    return CardReference(title=without_mentions((ticket.title or "").strip()) or f"card {words}",\n',
     '    return CardReference(title=f"{ticket.id}: {ticket.title}",\n'),

    ("the neutral words keep the `#`, so the body and the trailer name a forge item", MACHINE,
     '    words = " ".join(part for part in bare.split("#") if part).strip() or bare\n',
     '    words = str(ticket.id)\n'),

    ("the commit loses its trailer, and with it the only place the card's id was", MACHINE,
     "        if card.trailer:\n",
     "        if False:\n"),

    ("the commit is written the old way, whatever the verdict", MACHINE,
     "        msg = shlex.quote(card.title)\n",
     '        msg = shlex.quote(f"{ticket.id}: {ticket.title}")\n'),

    ("the pull request is opened with the old title, whatever the verdict", MACHINE,
     "                head=branch, base=base, title=card.title,\n",
     '                head=branch, base=base, title=f"{ticket.id}: {ticket.title}",\n'),

    ("the body is built without the verdict, so an owned card loses its mention", MACHINE,
     "                body=self._pr_body(ticket, result, card=card),\n",
     "                body=self._pr_body(ticket, result),\n"),

    ("a closing line on EVERY pairing, so a neutral one closes somebody else's item", MACHINE,
     "            card.lead, *([\"\", card.closing] if card.closing else []),\n",
     "            card.lead, \"\", f\"Closes {ticket.id}\",\n"),

    # ── claim 4: who closes what it owns ─────────────────────────────────────────────────────
    # Re-pinned by #167's second half: the owned reference now also keeps its verdict.
    ("the owned pairing loses its closing line, so a delivered GitHub issue stays open", MACHINE,
     '                             closing=f"{keyword} {mention}" if keyword else "", owned=True)',
     '                             closing="", owned=True)'),

    ("GitHub stops declaring its word, so a delivered GitHub issue stays open", GH_FORGE,
     '    closing_keyword = "Closes"\n',
     '    closing_keyword = ""\n'),

    ("ADO OWNED GAINS A CLOSING LINE: the forge becomes a second writer of the work item", ADO_FORGE,
     '    closing_keyword = ""\n',
     '    closing_keyword = "Closes"\n'),

    ("the forge's declaration is ignored, so every owning forge is asked to close", MACHINE,
     '    keyword = closing_keyword(getattr(runner, "forge", None)) if owned else ""\n',
     '    keyword = "Closes" if owned else ""\n'),

    ("a phrase or a mock counts as a closing word", SPACE,
     "    if isinstance(word, str) and word.strip().isalpha():\n",
     "    if word:\n"),

    ("the card's URL is never asked for", MACHINE,
     '            url = str(ask(ticket.id) or "").strip() if callable(ask) else ""\n',
     '            url = ""\n'),
]
