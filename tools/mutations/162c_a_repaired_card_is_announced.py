"""#162 (activities.py:3182): a repaired card is remembered and announced on any tracker.

The reverses are essential here. "The card is announced" is satisfied by a comparison that is
always TRUE, which would announce repairs the board refused — the opposite failure and the worse
one, because it tells a client their promise moved when it did not.
"""

TEST = "tests/test_a_repaired_card_is_announced_on_any_tracker.py"
ACT = "openfactory/runtime/temporal/activities.py"
REFS = "openfactory/contracts/refs.py"
OLD = "tests/test_orphaned_cards_are_repointed.py"

MUTATIONS = [
    # ── the defect itself, both directions ──────────────────────────────────────────────────────
    ("the ref is reduced to its digits again — nothing pairs, every round reads clean", ACT,
     '    return str(ref or "").strip().lstrip("#").strip()',
     '    digits = "".join(c for c in str(ref or "") if c.isdigit())\n'
     "    return int(digits) if digits else 0"),

    ("…and the reverse: everything pairs, so a REFUSED write is announced as repaired", ACT,
     '            fresh = {card: successor for (card, _cited, successor) in orphans\n'
     "                     if card in written}",
     "            fresh = {card: successor for (card, _cited, successor) in orphans}", OLD),

    ("a result that names no card pairs with everything", ACT,
     '                       if getattr(r, "ok", False)} - {""}',
     '                       if getattr(r, "ok", False)}'),

    # ── the memory ──────────────────────────────────────────────────────────────────────────────
    ("the memory skips every non-numeric card again", ACT,
     "        if not card.strip():\n            continue",
     "        if not card.strip().isdigit():\n            continue"),

    ("the card comes back from the memory as an int, so nothing it stores ever pairs", ACT,
     "        out.append((card.strip(), int(requirement) if requirement.strip().isdigit() "
     "else None))",
     "        out.append((int(card) if card.strip().isdigit() else card.strip(),\n"
     "                    int(requirement) if requirement.strip().isdigit() else None))"),

    ("a ref carrying the memory's own separator is written, splitting into two false facts", ACT,
     '        repaired = {c: r for c, r in repaired.items() if not _UNSTORABLE(c)}\n'
     "        announced = {(c, r) for c, r in announced if not _UNSTORABLE(c)}\n", ""),

    ("…and the reverse: one bad ref takes the storable facts down with it", ACT,
     '    return "|" in str(ref) or ":" in str(ref)', "    return True"),

    ("dropping every fact still writes an empty row", ACT,
     "        if not repaired and not announced:\n            return\n        kept_repaired",
     "        kept_repaired"),

    ("the unstorable refs are dropped in silence", ACT,
     '            activity.logger.error("OPENFACTORY_PRODUCT_ORPHANS_MEMORY_UNSTORABLE '
     'project=%s "\n                                  "cards=%s — these refs carry this memory\'s '
     'own separators, so "\n                                  "they cannot be remembered and will '
     'be announced again",\n                                  project_name, '
     '",".join(ref_label(c) for c in illegal))', "            pass"),

    # ── how a person reads it ───────────────────────────────────────────────────────────────────
    ("GitHub's hash is put on a Jira ref", REFS,
     '    return f"#{text.lstrip(\'#\')}" if text.lstrip("#").isdigit() else text',
     '    return f"#{text.lstrip(chr(35))}"'),

    ("…and the reverse: the hash is dropped from a numeric ref", REFS,
     '    return f"#{text.lstrip(\'#\')}" if text.lstrip("#").isdigit() else text',
     "    return text"),

    ("the cards are ordered as strings — #510 before #59", ACT,
     "    ordered = sorted(cards, key=ref_sort_key)", "    ordered = sorted(cards)"),

    # NOT "delete the fake's shape assertion" — that assert is a tripwire for FUTURE drift, and the
    # file's data is strings now, so removing it changes no current answer. A mutation that edits a
    # TEST to assert less can never be caught by a test; the claim it was reaching for is the last
    # guard in TEST, which reads the contract rather than the fixture.
]
